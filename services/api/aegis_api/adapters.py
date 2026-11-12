"""Database adapters for GhostPay read-only replay and tenant-scoped demo seeding."""

from __future__ import annotations

from datetime import timedelta
from typing import Any
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
from ghostpay.domain.models import PaymentTrace
from ghostpay.repository import (
    GhostPayReplayRepository,
    InvestigationListResponse,
    PersistedInvestigation,
)
from security import assert_same_tenant


class SqlAlchemyGhostPayRepository(GhostPayReplayRepository):
    """Read-only forensic loader + investigation audit adapter backed by SQLAlchemy."""

    def __init__(self, ledger: LedgerRepository, platform: PlatformRepository) -> None:
        self.ledger = ledger
        self.platform = platform

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
        # Reconstruct decision-time approval & passport balances so post-decision capture/consumption
        # does not look like policy drift during deterministic replay.
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

        replay_passport = passport
        snapshot_fn = getattr(self.ledger, "get_passport_snapshot_for_decision", None)
        snapshot = snapshot_fn(tenant_id, decision.id) if snapshot_fn else None

        if snapshot is not None:
            # Reconstruct exact immutable snapshot state at decision time (GAP-013)
            replay_passport = SpendingPassport(
                id=getattr(snapshot, "passport_id", passport.id),
                tenant_id=tenant_id,
                agent_id=getattr(snapshot, "agent_id", passport.agent_id),
                per_tx_limit_minor=getattr(snapshot, "per_tx_limit_minor", passport.per_tx_limit_minor),
                daily_limit_minor=getattr(snapshot, "daily_limit_minor", passport.daily_limit_minor),
                total_budget_minor=getattr(snapshot, "total_budget_minor", passport.total_budget_minor),
                spent_minor=getattr(snapshot, "spent_minor", passport.spent_minor),
                reserved_minor=getattr(snapshot, "reserved_minor", passport.reserved_minor),
                currency=getattr(snapshot, "currency", passport.currency),
                allowed_merchant_ids=getattr(snapshot, "allowed_merchant_ids", passport.allowed_merchant_ids),
                allow_unknown_merchants=getattr(snapshot, "allow_unknown_merchants", passport.allow_unknown_merchants),
                allowed_categories=getattr(snapshot, "allowed_categories", passport.allowed_categories),
                human_approval_threshold_minor=getattr(snapshot, "human_approval_threshold_minor", passport.human_approval_threshold_minor),
                status=getattr(snapshot, "status", passport.status),
                policy_version=getattr(snapshot, "policy_version", passport.policy_version),
                created_at=getattr(snapshot, "created_at", passport.created_at),
                updated_at=getattr(snapshot, "created_at", passport.updated_at),
                expires_at=getattr(snapshot, "expires_at", passport.expires_at),
            )
        elif decision.policy_inputs and "passport" in decision.policy_inputs:
            # Reconstruct from AuthorizationDecision.policy_inputs (GAP-013)
            p_dict = decision.policy_inputs["passport"]
            if isinstance(p_dict, dict):
                replay_passport = SpendingPassport.model_validate(p_dict)
        else:
            reservation = (
                self.ledger.get_reservation(tenant_id, intent.reservation_id)
                if intent.reservation_id
                else None
            )
            if reservation is not None and reservation.status == ReservationStatus.HELD:
                replay_passport = passport.model_copy(
                    update={"reserved_minor": max(0, passport.reserved_minor - reservation.amount_minor)}
                )
            elif intent.state == PaymentState.SUCCEEDED or (
                reservation is not None and reservation.status == ReservationStatus.CAPTURED
            ):
                replay_passport = passport.model_copy(
                    update={"spent_minor": max(0, passport.spent_minor - intent.amount_minor)}
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

    def get_investigation(self, tenant_id: UUID, investigation_id: UUID) -> PersistedInvestigation | None:
        row = self.platform.get_replay_investigation(tenant_id, investigation_id)
        if row is None:
            return None
        return self._to_investigation(row)

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
        content_hash=compute_payload_hash({"quote_hash": q_hash, "amount_minor": 3900}),
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
