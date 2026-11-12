"""Database adapters for GhostPay read-only replay and tenant-scoped demo seeding."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any, Protocol, runtime_checkable
from uuid import UUID, uuid4

from contracts import (
    AgentIdentity,
    ApprovalStatus,
    AuthorizationDecision,
    BudgetReservation,
    DecisionOutcome,
    DecisionReasonCode,
    EvidenceRecord,
    EvidenceSourceType,
    FinancialEvent,
    FinancialEventType,
    Merchant,
    PassportStatus,
    PaymentAttempt,
    PaymentIntent,
    PaymentState,
    PurchaseProposal,
    QuoteSnapshot,
    ReplayRequest,
    ReplayResult,
    ReservationStatus,
    SpendingPassport,
    compute_payload_hash,
    compute_quote_hash,
)
from contracts.fixtures import (
    BASE_TIME,
    build_authorized_39_purchase_fixture,
    build_synthetic_dispute_fixture,
)
from database import LedgerRepository, PlatformRepository
from ghostpay.agentdna.profiles import AgentBehaviorProfile
from ghostpay.domain.models import PaymentTrace
from ghostpay.repository import (
    GhostPayReplayRepository,
    InvestigationListResponse,
    PersistedInvestigation,
)
from pydantic import ValidationError
from security import assert_same_tenant


@runtime_checkable
class GhostPayTraceAndDnaPlatformProtocol(Protocol):
    """Optional PlatformRepository interface for persisted GhostPay traces and Agent DNA profiles."""

    def save_ghostpay_trace(
        self,
        tenant_id: UUID,
        trace_id: str,
        agent_id: str | UUID,
        payload_json: dict[str, Any],
        recorded_decision_json: dict[str, Any] | None = None,
        correlation_id: str | UUID = "",
    ) -> Any: ...

    def list_ghostpay_traces(
        self,
        tenant_id: UUID,
        agent_id: str | UUID | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[Any]: ...

    def get_ghostpay_trace(self, tenant_id: UUID, trace_id: str) -> Any | None: ...

    def save_agent_dna_profile(
        self,
        tenant_id: UUID,
        agent_id: str | UUID,
        profile_json: dict[str, Any],
    ) -> Any: ...

    def get_agent_dna_profile(
        self, tenant_id: UUID, agent_id: str | UUID
    ) -> Any | None: ...


def _first_nonneg_int(mapping: dict[str, Any], keys: tuple[str, ...]) -> int | None:
    for key in keys:
        val = mapping.get(key)
        if isinstance(val, int) and not isinstance(val, bool) and val >= 0:
            return val
    return None


class SqlAlchemyGhostPayRepository(GhostPayReplayRepository):
    """Read-only forensic loader + investigation/trace audit adapter backed by SQLAlchemy."""

    def __init__(self, ledger: LedgerRepository, platform: PlatformRepository) -> None:
        self.ledger = ledger
        self.platform = platform

    def _reconstruct_decision_passport(
        self,
        tenant_id: UUID,
        intent: PaymentIntent,
        passport: SpendingPassport,
        decision: AuthorizationDecision,
    ) -> SpendingPassport:
        """Reconstruct decision-time SpendingPassport from immutable snapshots & policy_inputs."""
        snapshot_getter = getattr(self.ledger, "get_passport_snapshot_for_decision", None)
        snapshot = snapshot_getter(tenant_id, decision.id) if callable(snapshot_getter) else None

        base_passport: SpendingPassport | None = None
        if isinstance(snapshot, dict) and isinstance(snapshot.get("snapshot_json"), dict):
            try:
                candidate = SpendingPassport.model_validate(snapshot["snapshot_json"])
                assert_same_tenant(tenant_id, candidate.tenant_id, "spending_passport_snapshot")
                base_passport = candidate
            except (ValidationError, ValueError):
                base_passport = None

        used_snapshot = base_passport is not None
        if base_passport is None:
            base_passport = passport

        policy_inputs = decision.policy_inputs if isinstance(decision.policy_inputs, dict) else {}
        updates: dict[str, Any] = {}

        if not used_snapshot:
            per_tx = _first_nonneg_int(
                policy_inputs, ("per_tx_limit_minor", "passport_per_tx_limit_minor")
            )
            if per_tx is not None:
                updates["per_tx_limit_minor"] = per_tx

            daily = _first_nonneg_int(policy_inputs, ("daily_limit_minor",))
            if daily is not None:
                updates["daily_limit_minor"] = daily

            monthly = _first_nonneg_int(policy_inputs, ("monthly_limit_minor",))
            if monthly is not None:
                updates["monthly_limit_minor"] = monthly

            threshold = _first_nonneg_int(
                policy_inputs,
                (
                    "approval_threshold_minor",
                    "human_approval_threshold_minor",
                    "passport_human_approval_threshold_minor",
                ),
            )
            if threshold is not None:
                updates["human_approval_threshold_minor"] = threshold

            passport_currency = policy_inputs.get("passport_currency")
            if isinstance(passport_currency, str) and len(passport_currency.strip()) == 3:
                updates["currency"] = passport_currency.strip().upper()

            allowed_currencies = policy_inputs.get("allowed_currencies")
            if isinstance(allowed_currencies, list) and all(
                isinstance(c, str) and len(c.strip()) == 3 for c in allowed_currencies
            ):
                updates["allowed_currencies"] = [c.strip().upper() for c in allowed_currencies]

            recorded_pv = policy_inputs.get("policy_version")
            if isinstance(recorded_pv, str) and recorded_pv.strip():
                updates["policy_version"] = recorded_pv.strip()

        available_budget = _first_nonneg_int(
            policy_inputs, ("available_budget_minor", "passport_available_budget_minor")
        )
        if available_budget is not None:
            total_budget = updates.get("total_budget_minor", base_passport.total_budget_minor)
            if available_budget <= total_budget:
                updates["spent_minor"] = total_budget - available_budget
                updates["reserved_minor"] = 0
            else:
                updates["total_budget_minor"] = available_budget
                updates["spent_minor"] = 0
                updates["reserved_minor"] = 0
        elif not used_snapshot:
            reservation = (
                self.ledger.get_reservation(tenant_id, intent.reservation_id)
                if intent.reservation_id
                else None
            )
            if reservation is not None and reservation.status == ReservationStatus.HELD:
                updates["reserved_minor"] = max(
                    0, base_passport.reserved_minor - reservation.amount_minor
                )
            elif intent.state == PaymentState.SUCCEEDED or (
                reservation is not None and reservation.status == ReservationStatus.CAPTURED
            ):
                updates["spent_minor"] = max(
                    0, base_passport.spent_minor - intent.amount_minor
                )

        return base_passport.model_copy(update=updates) if updates else base_passport

    def _build_replay_request(self, tenant_id: UUID, intent: PaymentIntent) -> ReplayRequest | None:
        proposal = self.ledger.get_proposal(tenant_id, intent.proposal_id)
        quote = self.ledger.get_quote(tenant_id, intent.quote_snapshot_id)
        passport = self.ledger.get_passport(tenant_id, intent.passport_id)
        merchant = self.ledger.get_merchant(tenant_id, intent.merchant_id)
        decision = (
            self.ledger.get_decision(tenant_id, intent.authorization_decision_id)
            if intent.authorization_decision_id
            else None
        )
        if proposal is None or quote is None or passport is None or merchant is None or decision is None:
            return None

        approval = (
            self.ledger.get_approval(tenant_id, intent.approval_record_id)
            if intent.approval_record_id
            else None
        )
        # Reconstruct decision-time approval & passport state so post-decision capture or policy
        # mutations do not look like policy drift during deterministic replay.
        replay_approval = approval
        if (
            approval is not None
            and decision.outcome == DecisionOutcome.ESCALATE
            and (
                DecisionReasonCode.ESCALATED_REQUIRES_HUMAN_APPROVAL in decision.reason_codes
                or approval.decided_at is None
                or approval.decided_at >= decision.decided_at
            )
        ):
            replay_approval = approval.model_copy(
                update={"status": ApprovalStatus.PENDING, "decided_at": None}
            )

        replay_passport = self._reconstruct_decision_passport(
            tenant_id, intent, passport, decision
        )

        events = self.ledger.list_events(tenant_id, correlation_id=intent.correlation_id)
        evidence = self.ledger.list_evidence(tenant_id, correlation_id=intent.correlation_id)
        return ReplayRequest(
            tenant_id=tenant_id,
            correlation_id=intent.correlation_id,
            payment_intent=intent,
            proposal=proposal,
            quote_snapshot=quote,
            recorded_passport=replay_passport,
            recorded_merchant=merchant,
            recorded_decision=decision,
            approval_record=replay_approval,
            policy_version=decision.policy_version,
            events=events,
            evidence_records=evidence,
            evaluation_time=decision.decided_at,
        )

    def load_replay_request(self, tenant_id: UUID, correlation_id: UUID) -> ReplayRequest | None:
        intents = self.ledger.list_intents(tenant_id, limit=200)
        for intent in intents:
            if intent.correlation_id == correlation_id:
                return self._build_replay_request(tenant_id, intent)
        return None

    def load_replay_request_by_payment(self, tenant_id: UUID, payment_intent_id: UUID) -> ReplayRequest | None:
        intent = self.ledger.get_intent(tenant_id, payment_intent_id)
        if intent is None:
            return None
        return self._build_replay_request(tenant_id, intent)

    def load_timeline_records_by_payment(
        self,
        tenant_id: UUID,
        payment_intent_id: UUID,
    ) -> tuple[list[FinancialEvent], list[EvidenceRecord]] | None:
        intent = self.ledger.get_intent(tenant_id, payment_intent_id)
        if intent is None:
            return None
        events = self.ledger.list_events(tenant_id, correlation_id=intent.correlation_id)
        evidence = self.ledger.list_evidence(tenant_id, correlation_id=intent.correlation_id)
        return events, evidence

    _INVESTIGATION_TRACE_AGENT_ID = "__investigation__"
    _INVESTIGATION_TRACE_PREFIX = "investigation:"

    def save_investigation(
        self,
        *,
        tenant_id: UUID,
        result: ReplayResult,
        mode: str,
        overrides: dict[str, Any],
        created_by: str,
    ) -> PersistedInvestigation:
        assert_same_tenant(tenant_id, result.tenant_id, "replay_result")
        if self.ledger.get_intent(tenant_id, result.payment_intent_id) is not None:
            row = self.platform.save_replay_investigation(
                investigation_id=result.replay_id,
                tenant_id=tenant_id,
                correlation_id=result.correlation_id,
                payment_intent_id=result.payment_intent_id,
                policy_version=result.policy_version,
                mode=mode,
                overrides=overrides,
                result_payload=result.model_dump(mode="json"),
                consistency_status=result.consistency_status,
                drift_detected=result.drift_detected,
                integrity_valid=result.integrity_valid,
                created_by=created_by,
            )
            return self._to_investigation(row)

        persisted = PersistedInvestigation(
            investigation_id=result.replay_id,
            tenant_id=tenant_id,
            correlation_id=result.correlation_id,
            payment_intent_id=result.payment_intent_id,
            policy_version=result.policy_version,
            mode=mode,
            overrides=overrides,
            consistency_status=result.consistency_status,
            drift_detected=result.drift_detected,
            integrity_valid=result.integrity_valid,
            created_by=created_by,
            created_at=datetime.now(UTC),
            result=result,
        )
        # Standalone ingested traces may reference synthetic payment_intent_id values not present in
        # payment_intents; persist those trace-only investigations via ghostpay_traces (no FK to payment_intents).
        saver = getattr(self.platform, "save_ghostpay_trace", None)
        if callable(saver):
            saver(
                tenant_id=tenant_id,
                trace_id=f"{self._INVESTIGATION_TRACE_PREFIX}{result.replay_id}",
                agent_id=self._INVESTIGATION_TRACE_AGENT_ID,
                payload_json=persisted.model_dump(mode="json"),
                recorded_decision_json=None,
                correlation_id=str(result.correlation_id),
            )
        return persisted

    def _row_to_persisted_investigation(self, row: Any) -> PersistedInvestigation | None:
        payload = row.get("payload_json") if isinstance(row, dict) else getattr(row, "payload_json", None)
        if not isinstance(payload, dict):
            return None
        try:
            return PersistedInvestigation.model_validate(payload)
        except ValidationError:
            return None

    def get_investigation(self, tenant_id: UUID, investigation_id: UUID) -> PersistedInvestigation | None:
        row = self.platform.get_replay_investigation(tenant_id, investigation_id)
        if row is not None:
            return self._to_investigation(row)
        getter = getattr(self.platform, "get_ghostpay_trace", None)
        if not callable(getter):
            return None
        trace_row = getter(tenant_id, f"{self._INVESTIGATION_TRACE_PREFIX}{investigation_id}")
        if trace_row is None:
            return None
        item = self._row_to_persisted_investigation(trace_row)
        if item is not None:
            assert_same_tenant(tenant_id, item.tenant_id, "investigation")
        return item

    def _list_trace_only_investigations(
        self,
        tenant_id: UUID,
        *,
        payment_intent_id: UUID | None = None,
        consistency_status: str | None = None,
        drift_detected: bool | None = None,
    ) -> list[PersistedInvestigation]:
        lister = getattr(self.platform, "list_ghostpay_traces", None)
        if not callable(lister):
            return []
        rows = lister(
            tenant_id,
            agent_id=self._INVESTIGATION_TRACE_AGENT_ID,
            limit=500,
            offset=0,
        )
        items: list[PersistedInvestigation] = []
        for row in rows:
            item = self._row_to_persisted_investigation(row)
            if item is None:
                continue
            assert_same_tenant(tenant_id, item.tenant_id, "investigation")
            if payment_intent_id is not None and item.payment_intent_id != payment_intent_id:
                continue
            if consistency_status is not None and item.consistency_status != consistency_status:
                continue
            if drift_detected is not None and item.drift_detected != drift_detected:
                continue
            items.append(item)
        return items

    def list_investigations(
        self,
        tenant_id: UUID,
        *,
        payment_intent_id: UUID | None = None,
        consistency_status: str | None = None,
        drift_detected: bool | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> InvestigationListResponse:
        trace_only = self._list_trace_only_investigations(
            tenant_id,
            payment_intent_id=payment_intent_id,
            consistency_status=consistency_status,
            drift_detected=drift_detected,
        )
        if not trace_only:
            rows, total = self.platform.list_replay_investigations(
                tenant_id,
                payment_intent_id=payment_intent_id,
                consistency_status=consistency_status,
                drift_detected=drift_detected,
                limit=limit,
                offset=offset,
            )
            return InvestigationListResponse(
                items=[self._to_investigation(r) for r in rows],
                total=total,
                limit=limit,
                offset=offset,
            )

        rows, db_total = self.platform.list_replay_investigations(
            tenant_id,
            payment_intent_id=payment_intent_id,
            consistency_status=consistency_status,
            drift_detected=drift_detected,
            limit=max(limit + offset + 100, 500),
            offset=0,
        )
        merged_by_id: dict[UUID, PersistedInvestigation] = {
            item.investigation_id: item for item in (self._to_investigation(r) for r in rows)
        }
        for item in trace_only:
            merged_by_id.setdefault(item.investigation_id, item)
        merged = sorted(
            merged_by_id.values(),
            key=lambda x: (
                x.created_at.replace(tzinfo=UTC) if x.created_at.tzinfo is None else x.created_at
            ),
            reverse=True,
        )
        total = max(db_total + len(trace_only), len(merged)) if db_total > len(rows) else len(merged)
        return InvestigationListResponse(
            items=merged[offset : offset + limit],
            total=total,
            limit=limit,
            offset=offset,
        )

    def save_trace(self, tenant_id: UUID, trace: PaymentTrace) -> None:
        """Persist a payment trace defensively if Machine 1 database methods are active."""
        save_fn = getattr(self.ledger, "save_ghostpay_trace", getattr(self.platform, "save_ghostpay_trace", None))
        if save_fn:
            save_fn(tenant_id, trace)

    def get_trace(self, tenant_id: UUID, trace_id: UUID) -> PaymentTrace | None:
        """Fetch a payment trace defensively if Machine 1 database methods are active."""
        get_fn = getattr(self.ledger, "get_ghostpay_trace", getattr(self.platform, "get_ghostpay_trace", None))
        if get_fn:
            return get_fn(tenant_id, trace_id)
        return None

    def list_traces(
        self,
        tenant_id: UUID,
        *,
        agent_id: UUID | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[PaymentTrace]:
        """List payment traces defensively via Machine 1 DB or reconstructed from intents."""
        list_fn = getattr(self.ledger, "list_ghostpay_traces", getattr(self.platform, "list_ghostpay_traces", None))
        if list_fn:
            return list_fn(tenant_id, agent_id=agent_id, limit=limit, offset=offset)

        intents = self.ledger.list_intents(tenant_id, limit=limit, offset=offset)
        traces: list[PaymentTrace] = []
        for intent in intents:
            if agent_id and intent.agent_id != agent_id:
                continue
            rep_req = self._build_replay_request(tenant_id, intent)
            if rep_req:
                traces.append(
                    PaymentTrace(
                        trace_id=intent.id,
                        tenant_id=tenant_id,
                        agent_id=intent.agent_id,
                        payment_intent_id=intent.id,
                        policy_version=rep_req.policy_version,
                        payment_intent=intent,
                        proposal=rep_req.proposal,
                        quote_snapshot=rep_req.quote_snapshot,
                        recorded_passport=rep_req.recorded_passport,
                        recorded_merchant=rep_req.recorded_merchant,
                        recorded_decision=rep_req.recorded_decision,
                        approval_record=rep_req.approval_record,
                        ordered_events=rep_req.events,
                        authorization_evidence=rep_req.evidence_records,
                    )
                )
        return traces

    def save_agent_dna_profile(self, tenant_id: UUID, profile: Any) -> None:
        """Persist an Agent DNA profile defensively if Machine 1 DB methods are active."""
        save_fn = getattr(self.ledger, "save_agent_dna_profile", getattr(self.platform, "save_agent_dna_profile", None))
        if save_fn:
            save_fn(tenant_id, profile)

    def get_agent_dna_profile(self, tenant_id: UUID, agent_id: UUID) -> Any | None:
        """Fetch an Agent DNA profile defensively if Machine 1 DB methods are active."""
        get_fn = getattr(self.ledger, "get_agent_dna_profile", getattr(self.platform, "get_agent_dna_profile", None))
        if get_fn:
            return get_fn(tenant_id, agent_id)
        return None

    @staticmethod
    def _to_investigation(row: Any) -> PersistedInvestigation:
        return PersistedInvestigation(
            investigation_id=row.id,
            tenant_id=row.tenant_id,
            correlation_id=row.correlation_id,
            payment_intent_id=row.payment_intent_id,
            policy_version=row.policy_version,
            mode=row.mode,
            overrides=row.overrides,
            consistency_status=row.consistency_status,
            drift_detected=row.drift_detected,
            integrity_valid=row.integrity_valid,
            created_by=row.created_by,
            created_at=row.created_at,
            result=ReplayResult.model_validate(row.result_payload),
        )

    @staticmethod
    def _resolve_trace_correlation_id(trace: PaymentTrace) -> str:
        if trace.recorded_decision is not None:
            return str(trace.recorded_decision.correlation_id)
        if trace.quote_snapshot is not None:
            return str(trace.quote_snapshot.correlation_id)
        if trace.payment_intent is not None:
            return str(trace.payment_intent.correlation_id)
        if trace.ordered_events:
            return str(trace.ordered_events[0].correlation_id)
        return ""

    @classmethod
    def _row_to_trace(cls, row: Any) -> PaymentTrace | None:
        row_agent_id = row.get("agent_id") if isinstance(row, dict) else getattr(row, "agent_id", None)
        if row_agent_id == cls._INVESTIGATION_TRACE_AGENT_ID:
            return None
        payload = row.get("payload_json") if isinstance(row, dict) else getattr(row, "payload_json", None)
        if not isinstance(payload, dict):
            return None
        try:
            return PaymentTrace.model_validate(payload)
        except ValidationError:
            return None

    def save_ghostpay_trace(self, tenant_id: UUID, trace: PaymentTrace) -> PaymentTrace:
        """Persist a normalized PaymentTrace in PostgreSQL if supported by platform repository."""
        assert_same_tenant(tenant_id, trace.tenant_id, "payment_trace")
        saver = getattr(self.platform, "save_ghostpay_trace", None)
        if not callable(saver):
            return trace
        recorded_decision_json = (
            trace.recorded_decision.model_dump(mode="json")
            if trace.recorded_decision is not None
            else None
        )
        saver(
            tenant_id=tenant_id,
            trace_id=str(trace.trace_id),
            agent_id=str(trace.agent_id),
            payload_json=trace.model_dump(mode="json"),
            recorded_decision_json=recorded_decision_json,
            correlation_id=self._resolve_trace_correlation_id(trace),
        )
        return trace

    def list_ghostpay_traces(
        self,
        tenant_id: UUID,
        *,
        agent_id: UUID | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[PaymentTrace]:
        """List persisted tenant-scoped PaymentTraces with optional agent filter and pagination."""
        lister = getattr(self.platform, "list_ghostpay_traces", None)
        if not callable(lister):
            return []
        if agent_id is not None:
            rows = lister(
                tenant_id,
                agent_id=str(agent_id),
                limit=limit,
                offset=offset,
            )
            traces: list[PaymentTrace] = []
            for row in rows:
                trace = self._row_to_trace(row)
                if trace is not None:
                    assert_same_tenant(tenant_id, trace.tenant_id, "payment_trace")
                    traces.append(trace)
            return traces

        rows = lister(
            tenant_id,
            agent_id=None,
            limit=max(limit + offset + 100, 500),
            offset=0,
        )
        traces = []
        for row in rows:
            trace = self._row_to_trace(row)
            if trace is not None:
                assert_same_tenant(tenant_id, trace.tenant_id, "payment_trace")
                traces.append(trace)
        return traces[offset : offset + limit]

    def get_ghostpay_trace(self, tenant_id: UUID, trace_id: UUID) -> PaymentTrace | None:
        """Load a persisted PaymentTrace by ID for the given tenant."""
        getter = getattr(self.platform, "get_ghostpay_trace", None)
        if not callable(getter):
            return None
        row = getter(tenant_id, str(trace_id))
        if row is None:
            return None
        trace = self._row_to_trace(row)
        if trace is None:
            return None
        assert_same_tenant(tenant_id, trace.tenant_id, "payment_trace")
        return trace

    def save_agent_dna_profile(
        self, tenant_id: UUID, profile: AgentBehaviorProfile
    ) -> AgentBehaviorProfile:
        """Persist or update an AgentBehaviorProfile in PostgreSQL if supported."""
        assert_same_tenant(tenant_id, profile.tenant_id, "agent_dna_profile")
        saver = getattr(self.platform, "save_agent_dna_profile", None)
        if not callable(saver):
            return profile
        saver(
            tenant_id=tenant_id,
            agent_id=str(profile.agent_id),
            profile_json=profile.model_dump(mode="json"),
        )
        return profile

    def get_agent_dna_profile(
        self, tenant_id: UUID, agent_id: UUID
    ) -> AgentBehaviorProfile | None:
        """Load a persisted AgentBehaviorProfile for the given tenant and agent."""
        getter = getattr(self.platform, "get_agent_dna_profile", None)
        if not callable(getter):
            return None
        row = getter(tenant_id, str(agent_id))
        if row is None:
            return None
        profile_json = (
            row.get("profile_json") if isinstance(row, dict) else getattr(row, "profile_json", None)
        )
        if not isinstance(profile_json, dict):
            return None
        try:
            profile = AgentBehaviorProfile.model_validate(profile_json)
        except ValidationError:
            return None
        assert_same_tenant(tenant_id, profile.tenant_id, "agent_dna_profile")
        return profile


def ensure_synthetic_sandbox_payment_chain(ledger: LedgerRepository, tenant_id: UUID) -> dict[str, Any]:
    """Ensure a labeled synthetic sandbox agent, merchant, passport, and succeeded payment exist for tenant."""
    dispute_fx = build_synthetic_dispute_fixture()
    base_fx = build_authorized_39_purchase_fixture()
    is_alpha = tenant_id == base_fx["tenant"].id

    if is_alpha:
        existing_intent = ledger.get_intent(tenant_id, base_fx["payment_intent"].id)
        if existing_intent is not None:
            return {"payment_intent": existing_intent, "dispute_fixture": dispute_fx}

    agent_id = base_fx["agent"].id if is_alpha else uuid4()
    merchant_id = base_fx["approved_merchant"].id if is_alpha else uuid4()
    passport_id = base_fx["passport"].id if is_alpha else uuid4()
    corr_id = base_fx["payment_intent"].correlation_id if is_alpha else uuid4()
    proposal_id = base_fx["proposal"].id if is_alpha else uuid4()
    quote_id = base_fx["quote_snapshot"].id if is_alpha else uuid4()
    intent_id = base_fx["payment_intent"].id if is_alpha else uuid4()
    decision_id = base_fx["decision"].id if is_alpha else uuid4()

    agent = AgentIdentity(
        id=agent_id,
        tenant_id=tenant_id,
        name="Synthetic Sandbox Copilot",
        purpose="Clearly labeled synthetic demo procurement agent",
        framework="langgraph",
        status="ACTIVE",
        public_fingerprint=f"fp-sandbox-{str(agent_id)[:8]}",
    )
    ledger.create_agent(agent)

    merchant = Merchant(
        id=merchant_id,
        tenant_id=tenant_id,
        name="CloudCompute Sandbox Store",
        domain="sandbox-store.cloudcompute.example",
        category="SOFTWARE",
        paypal_merchant_id="SB_MERCHANT_001",
        is_allowlisted=True,
        is_sandbox_verified=True,
    )
    ledger.create_merchant(merchant)

    passport = SpendingPassport(
        id=passport_id,
        tenant_id=tenant_id,
        agent_id=agent_id,
        policy_version="policy-v1",
        currency="USD",
        total_budget_minor=10000,
        spent_minor=3900,
        reserved_minor=0,
        per_tx_limit_minor=7500,
        daily_limit_minor=10000,
        human_approval_threshold_minor=5000,
        allowed_merchant_ids=[merchant_id],
        allowed_categories=["SOFTWARE", "CLOUD_INFRA"],
        allow_unknown_merchants=False,
        status=PassportStatus.ACTIVE,
        expires_at=BASE_TIME + timedelta(days=365),
    )
    ledger.create_passport(passport)

    line_items = [{"sku": "API-PRO-MO", "name": "CloudCompute Monthly API Tier", "qty": 1, "unit_amount_minor": 3900}]
    q_hash = compute_quote_hash(
        merchant_id=merchant_id,
        amount_minor=3900,
        currency="USD",
        line_items=line_items,
    )
    proposal = PurchaseProposal(
        id=proposal_id,
        tenant_id=tenant_id,
        correlation_id=corr_id,
        agent_id=agent_id,
        passport_id=passport_id,
        merchant_id=merchant_id,
        merchant_name=merchant.name,
        merchant_category=merchant.category,
        amount_minor=3900,
        currency="USD",
        item_summary="CloudCompute API Pro monthly plan (synthetic sandbox demo)",
        line_items=line_items,
        rationale="Synthetic demo purchase within $100 budget.",
        idempotency_key=f"sandbox-demo-{str(intent_id)[:12]}",
        proposed_by_model="synthetic-demo-fixture",
    )
    ledger.save_proposal(proposal)

    quote = QuoteSnapshot(
        id=quote_id,
        tenant_id=tenant_id,
        correlation_id=corr_id,
        proposal_id=proposal_id,
        merchant_id=merchant_id,
        amount_minor=3900,
        currency="USD",
        line_items=line_items,
        quote_hash=q_hash,
        expires_at=BASE_TIME + timedelta(hours=24),
    )
    ledger.save_quote(quote)

    intent = PaymentIntent(
        id=intent_id,
        tenant_id=tenant_id,
        correlation_id=corr_id,
        proposal_id=proposal_id,
        agent_id=agent_id,
        passport_id=passport_id,
        merchant_id=merchant_id,
        quote_snapshot_id=quote_id,
        quote_hash=q_hash,
        amount_minor=3900,
        currency="USD",
        state=PaymentState.SUCCEEDED,
        idempotency_key=proposal.idempotency_key,
        authorization_decision_id=decision_id,
    )
    ledger.save_intent(intent)

    decision = AuthorizationDecision(
        id=decision_id,
        tenant_id=tenant_id,
        correlation_id=corr_id,
        payment_intent_id=intent_id,
        proposal_id=proposal_id,
        passport_id=passport_id,
        quote_snapshot_id=quote_id,
        quote_hash=q_hash,
        policy_version="policy-v1",
        outcome=DecisionOutcome.ALLOW,
        reason_codes=[DecisionReasonCode.OK_WITHIN_POLICY],
        explanation="Synthetic sandbox transaction authorized under policy-v1.",
        policy_inputs={"amount_minor": 3900, "per_tx_limit_minor": 7500},
        decided_at=BASE_TIME + timedelta(seconds=1),
    )
    ledger.save_decision(decision)

    ev_quote = EvidenceRecord(
        id=uuid4(),
        tenant_id=tenant_id,
        correlation_id=corr_id,
        payment_intent_id=intent_id,
        source_type=EvidenceSourceType.QUOTE,
        source_ref=f"quote:{quote_id}",
        title="Synthetic Quote Snapshot ($39.00)",
        content={"quote_hash": q_hash, "amount_minor": 3900, "currency": "USD"},
        content_hash=compute_payload_hash({"quote_hash": q_hash, "amount_minor": 3900, "currency": "USD"}),
        is_synthetic=True,
    )
    ledger.save_evidence(ev_quote)

    ledger.append_financial_event(
        tenant_id=tenant_id,
        correlation_id=corr_id,
        payment_intent_id=intent_id,
        event_type=FinancialEventType.PROPOSAL_CREATED,
        actor_type="AGENT",
        actor_id=str(agent_id),
        payload={"proposal_id": str(proposal_id), "amount_minor": 3900, "is_synthetic": True},
    )
    ledger.append_financial_event(
        tenant_id=tenant_id,
        correlation_id=corr_id,
        payment_intent_id=intent_id,
        event_type=FinancialEventType.POLICY_EVALUATED,
        actor_type="POLICY_ENGINE",
        actor_id="policy-v1",
        payload={"decision_id": str(decision_id), "outcome": "ALLOW", "is_synthetic": True},
    )
    ledger.append_financial_event(
        tenant_id=tenant_id,
        correlation_id=corr_id,
        payment_intent_id=intent_id,
        event_type=FinancialEventType.PAYPAL_CAPTURE_VERIFIED,
        actor_type="PAYPAL_SANDBOX",
        actor_id="SB_SYNTHETIC",
        payload={"amount_minor": 3900, "currency": "USD", "is_synthetic": True},
    )
    return {"payment_intent": intent, "dispute_fixture": dispute_fx, "unused": (BudgetReservation, PaymentAttempt)}
