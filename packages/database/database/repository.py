"""Tenant-scoped canonical ledger repository with atomic budget & outbox support."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from contracts import (
    AgentIdentity,
    ApprovalRecord,
    ApprovalStatus,
    AuthorizationDecision,
    BudgetReservation,
    DecisionOutcome,
    DecisionReasonCode,
    DisputeAnalysis,
    DisputeCase,
    EvidenceRecord,
    FinancialEvent,
    FinancialEventType,
    Merchant,
    PassportStatus,
    PayPalBuyerApproval,
    PaymentAttempt,
    PaymentIntent,
    PaymentState,
    PurchaseProposal,
    QuoteSnapshot,
    ReservationStatus,
    SpendingPassport,
    Tenant,
    VerifiedPayPalCapture,
    assert_payment_transition,
)
from database.orm import (
    AgentRow,
    ApprovalRecordRow,
    AuthorizationDecisionRow,
    BudgetReservationRow,
    DisputeAnalysisRow,
    DisputeCaseRow,
    EvidenceRecordRow,
    FinancialEventRow,
    IdempotencyRecordRow,
    MerchantRow,
    OutboxEventRow,
    PaymentAttemptRow,
    PaymentIntentRow,
    PurchaseProposalRow,
    QuoteSnapshotRow,
    SpendingPassportRow,
    TenantRow,
)
from security import assert_same_tenant, compute_financial_event_hash


class InsufficientBudgetError(ValueError):
    """Raised when atomic passport budget reservation fails."""


class DuplicateIdempotencyError(ValueError):
    """Raised when an idempotency key is reused with a conflicting request payload."""


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _ensure_utc(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    return dt.astimezone(timezone.utc) if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


class LedgerRepository:
    """Tenant-scoped repository encapsulating atomic financial invariants."""

    def __init__(self, session: Session) -> None:
        self.session = session

    # ------------------------------------------------------------------
    # Tenants, Agents, Merchants, Passports
    # ------------------------------------------------------------------
    def upsert_tenant(self, tenant: Tenant) -> Tenant:
        row = self.session.get(TenantRow, tenant.id)
        if row is None:
            row = TenantRow(
                id=tenant.id,
                name=tenant.name,
                slug=tenant.slug,
                created_at=tenant.created_at,
            )
            self.session.add(row)
            self.session.flush()
        return Tenant(id=row.id, name=row.name, slug=row.slug, created_at=row.created_at)

    def create_agent(self, agent: AgentIdentity) -> AgentIdentity:
        row = self.session.get(AgentRow, agent.id)
        if row is None:
            row = AgentRow(
                id=agent.id,
                tenant_id=agent.tenant_id,
                name=agent.name,
                purpose=agent.purpose,
                framework=agent.framework,
                status=agent.status,
                public_fingerprint=agent.public_fingerprint,
                created_at=agent.created_at,
            )
            self.session.add(row)
            self.session.flush()
        else:
            assert_same_tenant(agent.tenant_id, row.tenant_id, "agent")
        return self._to_agent(row)

    def list_agents(self, tenant_id: UUID) -> list[AgentIdentity]:
        rows = self.session.scalars(
            select(AgentRow).where(AgentRow.tenant_id == tenant_id).order_by(AgentRow.created_at.desc())
        ).all()
        return [self._to_agent(r) for r in rows]

    def get_agent(self, tenant_id: UUID, agent_id: UUID) -> AgentIdentity | None:
        row = self.session.get(AgentRow, agent_id)
        if row is None:
            return None
        assert_same_tenant(tenant_id, row.tenant_id, "agent")
        return self._to_agent(row)

    def create_merchant(self, merchant: Merchant) -> Merchant:
        row = self.session.get(MerchantRow, merchant.id)
        if row is None:
            row = MerchantRow(
                id=merchant.id,
                tenant_id=merchant.tenant_id,
                name=merchant.name,
                domain=merchant.domain,
                category=merchant.category,
                paypal_merchant_id=merchant.paypal_merchant_id,
                is_allowlisted=merchant.is_allowlisted,
                is_sandbox_verified=merchant.is_sandbox_verified,
                created_at=merchant.created_at,
            )
            self.session.add(row)
            self.session.flush()
        else:
            assert_same_tenant(merchant.tenant_id, row.tenant_id, "merchant")
        return self._to_merchant(row)

    def list_merchants(self, tenant_id: UUID) -> list[Merchant]:
        rows = self.session.scalars(
            select(MerchantRow).where(MerchantRow.tenant_id == tenant_id).order_by(MerchantRow.created_at.desc())
        ).all()
        return [self._to_merchant(r) for r in rows]

    def get_merchant(self, tenant_id: UUID, merchant_id: UUID) -> Merchant | None:
        row = self.session.get(MerchantRow, merchant_id)
        if row is None:
            return None
        assert_same_tenant(tenant_id, row.tenant_id, "merchant")
        return self._to_merchant(row)

    def create_passport(self, passport: SpendingPassport) -> SpendingPassport:
        row = self.session.get(SpendingPassportRow, passport.id)
        if row is None:
            row = SpendingPassportRow(
                id=passport.id,
                tenant_id=passport.tenant_id,
                agent_id=passport.agent_id,
                policy_version=passport.policy_version,
                currency=passport.currency,
                total_budget_minor=passport.total_budget_minor,
                spent_minor=passport.spent_minor,
                reserved_minor=passport.reserved_minor,
                per_tx_limit_minor=passport.per_tx_limit_minor,
                daily_limit_minor=passport.daily_limit_minor,
                human_approval_threshold_minor=passport.human_approval_threshold_minor,
                allowed_merchant_ids=[str(m) for m in passport.allowed_merchant_ids],
                allowed_categories=list(passport.allowed_categories),
                allow_unknown_merchants=passport.allow_unknown_merchants,
                status=passport.status.value,
                expires_at=passport.expires_at,
                created_at=passport.created_at,
            )
            self.session.add(row)
            self.session.flush()
        else:
            assert_same_tenant(passport.tenant_id, row.tenant_id, "spending_passport")
        return self._to_passport(row)

    def list_passports(self, tenant_id: UUID) -> list[SpendingPassport]:
        rows = self.session.scalars(
            select(SpendingPassportRow)
            .where(SpendingPassportRow.tenant_id == tenant_id)
            .order_by(SpendingPassportRow.created_at.desc())
        ).all()
        return [self._to_passport(r) for r in rows]

    def get_passport(self, tenant_id: UUID, passport_id: UUID) -> SpendingPassport | None:
        row = self.session.get(SpendingPassportRow, passport_id)
        if row is None:
            return None
        assert_same_tenant(tenant_id, row.tenant_id, "spending_passport")
        return self._to_passport(row)

    # ------------------------------------------------------------------
    # Proposals, Quotes, Intents, Decisions, Approvals
    # ------------------------------------------------------------------
    def save_proposal(self, proposal: PurchaseProposal) -> PurchaseProposal:
        row = PurchaseProposalRow(
            id=proposal.id,
            tenant_id=proposal.tenant_id,
            correlation_id=proposal.correlation_id,
            agent_id=proposal.agent_id,
            passport_id=proposal.passport_id,
            merchant_id=proposal.merchant_id,
            merchant_name=proposal.merchant_name,
            merchant_category=proposal.merchant_category,
            amount_minor=proposal.amount_minor,
            currency=proposal.currency,
            item_summary=proposal.item_summary,
            line_items=proposal.line_items,
            rationale=proposal.rationale,
            idempotency_key=proposal.idempotency_key,
            proposed_by_model=proposal.proposed_by_model,
            created_at=proposal.created_at,
        )
        self.session.add(row)
        self.session.flush()
        return proposal

    def get_proposal(self, tenant_id: UUID, proposal_id: UUID) -> PurchaseProposal | None:
        row = self.session.get(PurchaseProposalRow, proposal_id)
        if row is None:
            return None
        assert_same_tenant(tenant_id, row.tenant_id, "purchase_proposal")
        return self._to_proposal(row)

    def save_quote(self, quote: QuoteSnapshot) -> QuoteSnapshot:
        row = QuoteSnapshotRow(
            id=quote.id,
            tenant_id=quote.tenant_id,
            correlation_id=quote.correlation_id,
            proposal_id=quote.proposal_id,
            merchant_id=quote.merchant_id,
            amount_minor=quote.amount_minor,
            currency=quote.currency,
            line_items=quote.line_items,
            quote_hash=quote.quote_hash,
            expires_at=quote.expires_at,
            created_at=quote.created_at,
        )
        self.session.add(row)
        self.session.flush()
        return quote

    def get_quote(self, tenant_id: UUID, quote_id: UUID) -> QuoteSnapshot | None:
        row = self.session.get(QuoteSnapshotRow, quote_id)
        if row is None:
            return None
        assert_same_tenant(tenant_id, row.tenant_id, "quote_snapshot")
        return self._to_quote(row)

    def get_intent_by_idempotency(self, tenant_id: UUID, idempotency_key: str) -> PaymentIntent | None:
        row = self.session.scalar(
            select(PaymentIntentRow).where(
                PaymentIntentRow.tenant_id == tenant_id,
                PaymentIntentRow.idempotency_key == idempotency_key,
            )
        )
        return self._to_intent(row) if row else None

    def save_intent(self, intent: PaymentIntent) -> PaymentIntent:
        row = PaymentIntentRow(
            id=intent.id,
            tenant_id=intent.tenant_id,
            correlation_id=intent.correlation_id,
            proposal_id=intent.proposal_id,
            agent_id=intent.agent_id,
            passport_id=intent.passport_id,
            merchant_id=intent.merchant_id,
            quote_snapshot_id=intent.quote_snapshot_id,
            quote_hash=intent.quote_hash,
            amount_minor=intent.amount_minor,
            currency=intent.currency,
            state=intent.state.value,
            idempotency_key=intent.idempotency_key,
            authorization_decision_id=intent.authorization_decision_id,
            approval_record_id=intent.approval_record_id,
            reservation_id=intent.reservation_id,
            active_attempt_id=intent.active_attempt_id,
            created_at=intent.created_at,
            updated_at=intent.updated_at,
        )
        self.session.add(row)
        self.session.flush()
        return intent

    def get_intent(self, tenant_id: UUID, intent_id: UUID) -> PaymentIntent | None:
        row = self.session.get(PaymentIntentRow, intent_id)
        if row is None:
            return None
        assert_same_tenant(tenant_id, row.tenant_id, "payment_intent")
        return self._to_intent(row)

    def list_intents(self, tenant_id: UUID) -> list[PaymentIntent]:
        rows = self.session.scalars(
            select(PaymentIntentRow)
            .where(PaymentIntentRow.tenant_id == tenant_id)
            .order_by(PaymentIntentRow.created_at.desc())
        ).all()
        return [self._to_intent(r) for r in rows]

    def transition_intent(
        self,
        tenant_id: UUID,
        intent_id: UUID,
        target_state: PaymentState,
        *,
        authorization_decision_id: UUID | None = None,
        approval_record_id: UUID | None = None,
        reservation_id: UUID | None = None,
        active_attempt_id: UUID | None = None,
    ) -> PaymentIntent:
        row = self.session.get(PaymentIntentRow, intent_id)
        if row is None:
            raise ValueError(f"PaymentIntent {intent_id} not found")
        assert_same_tenant(tenant_id, row.tenant_id, "payment_intent")
        current = PaymentState(row.state)
        assert_payment_transition(current, target_state)
        row.state = target_state.value
        if authorization_decision_id is not None:
            row.authorization_decision_id = authorization_decision_id
        if approval_record_id is not None:
            row.approval_record_id = approval_record_id
        if reservation_id is not None:
            row.reservation_id = reservation_id
        if active_attempt_id is not None:
            row.active_attempt_id = active_attempt_id
        row.updated_at = _utc_now()
        self.session.flush()
        return self._to_intent(row)

    def save_decision(self, decision: AuthorizationDecision) -> AuthorizationDecision:
        row = AuthorizationDecisionRow(
            id=decision.id,
            tenant_id=decision.tenant_id,
            correlation_id=decision.correlation_id,
            payment_intent_id=decision.payment_intent_id,
            proposal_id=decision.proposal_id,
            passport_id=decision.passport_id,
            quote_snapshot_id=decision.quote_snapshot_id,
            quote_hash=decision.quote_hash,
            policy_version=decision.policy_version,
            outcome=decision.outcome.value,
            reason_codes=[rc.value for rc in decision.reason_codes],
            violated_constraints=decision.violated_constraints,
            requires_human_approval=decision.requires_human_approval,
            explanation=decision.explanation,
            policy_inputs=decision.policy_inputs,
            decided_at=decision.decided_at,
        )
        self.session.add(row)
        self.session.flush()
        return decision

    def get_decision(self, tenant_id: UUID, decision_id: UUID) -> AuthorizationDecision | None:
        row = self.session.get(AuthorizationDecisionRow, decision_id)
        if row is None:
            return None
        assert_same_tenant(tenant_id, row.tenant_id, "authorization_decision")
        return self._to_decision(row)

    def save_approval(self, approval: ApprovalRecord) -> ApprovalRecord:
        row = ApprovalRecordRow(
            id=approval.id,
            tenant_id=approval.tenant_id,
            correlation_id=approval.correlation_id,
            payment_intent_id=approval.payment_intent_id,
            decision_id=approval.decision_id,
            approver_id=approval.approver_id,
            status=approval.status.value,
            bound_merchant_id=approval.bound_merchant_id,
            bound_amount_minor=approval.bound_amount_minor,
            bound_currency=approval.bound_currency,
            bound_quote_hash=approval.bound_quote_hash,
            comment=approval.comment,
            expires_at=approval.expires_at,
            decided_at=approval.decided_at,
            consumed_at=approval.consumed_at,
            created_at=approval.created_at,
        )
        self.session.add(row)
        self.session.flush()
        return approval

    def get_approval(self, tenant_id: UUID, approval_id: UUID) -> ApprovalRecord | None:
        row = self.session.get(ApprovalRecordRow, approval_id)
        if row is None:
            return None
        assert_same_tenant(tenant_id, row.tenant_id, "approval_record")
        return self._to_approval(row)

    def update_approval(self, approval: ApprovalRecord) -> ApprovalRecord:
        row = self.session.get(ApprovalRecordRow, approval.id)
        if row is None:
            raise ValueError(f"ApprovalRecord {approval.id} not found")
        assert_same_tenant(approval.tenant_id, row.tenant_id, "approval_record")
        row.status = approval.status.value
        row.comment = approval.comment
        row.decided_at = approval.decided_at
        row.consumed_at = approval.consumed_at
        self.session.flush()
        return self._to_approval(row)

    # ------------------------------------------------------------------
    # Atomic Budget Reservations
    # ------------------------------------------------------------------
    def reserve_budget_atomic(
        self,
        *,
        tenant_id: UUID,
        correlation_id: UUID,
        passport_id: UUID,
        payment_intent_id: UUID,
        amount_minor: int,
        currency: str,
        expires_at: datetime,
    ) -> BudgetReservation:
        """Atomically hold budget using conditional SQL UPDATE (prevents double-spend races)."""
        if amount_minor <= 0:
            raise ValueError("Reservation amount must be positive")

        existing = self.session.scalar(
            select(BudgetReservationRow).where(
                BudgetReservationRow.payment_intent_id == payment_intent_id
            )
        )
        if existing is not None:
            assert_same_tenant(tenant_id, existing.tenant_id, "budget_reservation")
            return self._to_reservation(existing)

        stmt = (
            update(SpendingPassportRow)
            .where(
                SpendingPassportRow.id == passport_id,
                SpendingPassportRow.tenant_id == tenant_id,
                SpendingPassportRow.status == PassportStatus.ACTIVE.value,
                SpendingPassportRow.currency == currency.upper(),
                (
                    SpendingPassportRow.total_budget_minor
                    - SpendingPassportRow.spent_minor
                    - SpendingPassportRow.reserved_minor
                )
                >= amount_minor,
            )
            .values(reserved_minor=SpendingPassportRow.reserved_minor + amount_minor)
        )
        res = self.session.execute(stmt)
        if res.rowcount != 1:
            raise InsufficientBudgetError(
                f"Insufficient available budget or inactive passport {passport_id} for {amount_minor} {currency}"
            )

        reservation = BudgetReservation(
            tenant_id=tenant_id,
            correlation_id=correlation_id,
            passport_id=passport_id,
            payment_intent_id=payment_intent_id,
            amount_minor=amount_minor,
            currency=currency.upper(),
            status=ReservationStatus.HELD,
            expires_at=expires_at,
        )
        row = BudgetReservationRow(
            id=reservation.id,
            tenant_id=reservation.tenant_id,
            correlation_id=reservation.correlation_id,
            passport_id=reservation.passport_id,
            payment_intent_id=reservation.payment_intent_id,
            amount_minor=reservation.amount_minor,
            currency=reservation.currency,
            status=reservation.status.value,
            expires_at=reservation.expires_at,
            created_at=reservation.created_at,
            updated_at=reservation.updated_at,
        )
        self.session.add(row)
        self.session.flush()
        return reservation

    def capture_reservation_atomic(self, tenant_id: UUID, reservation_id: UUID) -> BudgetReservation:
        row = self.session.get(BudgetReservationRow, reservation_id)
        if row is None:
            raise ValueError(f"BudgetReservation {reservation_id} not found")
        assert_same_tenant(tenant_id, row.tenant_id, "budget_reservation")
        if row.status == ReservationStatus.CAPTURED.value:
            return self._to_reservation(row)
        if row.status != ReservationStatus.HELD.value:
            raise ValueError(f"Cannot capture reservation in state {row.status}")

        stmt = (
            update(SpendingPassportRow)
            .where(
                SpendingPassportRow.id == row.passport_id,
                SpendingPassportRow.tenant_id == tenant_id,
                SpendingPassportRow.reserved_minor >= row.amount_minor,
            )
            .values(
                reserved_minor=SpendingPassportRow.reserved_minor - row.amount_minor,
                spent_minor=SpendingPassportRow.spent_minor + row.amount_minor,
            )
        )
        res = self.session.execute(stmt)
        if res.rowcount != 1:
            raise InsufficientBudgetError("Failed to move reserved funds to spent_minor")
        row.status = ReservationStatus.CAPTURED.value
        row.updated_at = _utc_now()
        self.session.flush()
        return self._to_reservation(row)

    def release_reservation_atomic(self, tenant_id: UUID, reservation_id: UUID) -> BudgetReservation:
        row = self.session.get(BudgetReservationRow, reservation_id)
        if row is None:
            raise ValueError(f"BudgetReservation {reservation_id} not found")
        assert_same_tenant(tenant_id, row.tenant_id, "budget_reservation")
        if row.status == ReservationStatus.RELEASED.value:
            return self._to_reservation(row)
        if row.status != ReservationStatus.HELD.value:
            raise ValueError(f"Cannot release reservation in state {row.status}")

        stmt = (
            update(SpendingPassportRow)
            .where(
                SpendingPassportRow.id == row.passport_id,
                SpendingPassportRow.tenant_id == tenant_id,
                SpendingPassportRow.reserved_minor >= row.amount_minor,
            )
            .values(reserved_minor=SpendingPassportRow.reserved_minor - row.amount_minor)
        )
        self.session.execute(stmt)
        row.status = ReservationStatus.RELEASED.value
        row.updated_at = _utc_now()
        self.session.flush()
        return self._to_reservation(row)

    def get_reservation(self, tenant_id: UUID, reservation_id: UUID) -> BudgetReservation | None:
        row = self.session.get(BudgetReservationRow, reservation_id)
        if row is None:
            return None
        assert_same_tenant(tenant_id, row.tenant_id, "budget_reservation")
        return self._to_reservation(row)

    # ------------------------------------------------------------------
    # Payment Attempts
    # ------------------------------------------------------------------
    def save_attempt(self, attempt: PaymentAttempt) -> PaymentAttempt:
        row = PaymentAttemptRow(
            id=attempt.id,
            tenant_id=attempt.tenant_id,
            correlation_id=attempt.correlation_id,
            payment_intent_id=attempt.payment_intent_id,
            attempt_number=attempt.attempt_number,
            idempotency_key=attempt.idempotency_key,
            provider=attempt.provider,
            paypal_order_id=attempt.paypal_order_id,
            paypal_approval_url=attempt.paypal_approval_url,
            buyer_approval=attempt.buyer_approval.model_dump(mode="json") if attempt.buyer_approval else None,
            verified_capture=attempt.verified_capture.model_dump(mode="json") if attempt.verified_capture else None,
            state=attempt.state.value,
            failure_code=attempt.failure_code,
            failure_reason=attempt.failure_reason,
            created_at=attempt.created_at,
            updated_at=attempt.updated_at,
        )
        self.session.add(row)
        self.session.flush()
        return attempt

    def get_attempt(self, tenant_id: UUID, attempt_id: UUID) -> PaymentAttempt | None:
        row = self.session.get(PaymentAttemptRow, attempt_id)
        if row is None:
            return None
        assert_same_tenant(tenant_id, row.tenant_id, "payment_attempt")
        return self._to_attempt(row)

    def get_attempt_by_paypal_order(self, tenant_id: UUID, paypal_order_id: str) -> PaymentAttempt | None:
        row = self.session.scalar(
            select(PaymentAttemptRow).where(
                PaymentAttemptRow.tenant_id == tenant_id,
                PaymentAttemptRow.paypal_order_id == paypal_order_id,
            )
        )
        return self._to_attempt(row) if row else None

    def update_attempt(self, attempt: PaymentAttempt) -> PaymentAttempt:
        row = self.session.get(PaymentAttemptRow, attempt.id)
        if row is None:
            raise ValueError(f"PaymentAttempt {attempt.id} not found")
        assert_same_tenant(attempt.tenant_id, row.tenant_id, "payment_attempt")
        row.paypal_order_id = attempt.paypal_order_id
        row.paypal_approval_url = attempt.paypal_approval_url
        row.buyer_approval = attempt.buyer_approval.model_dump(mode="json") if attempt.buyer_approval else None
        row.verified_capture = attempt.verified_capture.model_dump(mode="json") if attempt.verified_capture else None
        row.state = attempt.state.value
        row.failure_code = attempt.failure_code
        row.failure_reason = attempt.failure_reason
        row.updated_at = _utc_now()
        self.session.flush()
        return self._to_attempt(row)

    # ------------------------------------------------------------------
    # Append-Only Audit Trail & Transactional Outbox
    # ------------------------------------------------------------------
    def append_financial_event(
        self,
        *,
        tenant_id: UUID,
        correlation_id: UUID,
        payment_intent_id: UUID | None,
        event_type: FinancialEventType,
        actor_type: str,
        actor_id: str,
        payload: dict[str, Any],
        also_enqueue_outbox: bool = True,
    ) -> FinancialEvent:
        """Append a hash-chained immutable FinancialEvent + optional transactional outbox entry."""
        last = self.session.scalar(
            select(FinancialEventRow)
            .where(
                FinancialEventRow.tenant_id == tenant_id,
                FinancialEventRow.correlation_id == correlation_id,
            )
            .order_by(FinancialEventRow.sequence_number.desc())
            .limit(1)
        )
        seq = (last.sequence_number + 1) if last else 1
        prev_hash = last.event_hash if last else None
        ev_id = uuid4()
        occurred_at = _utc_now()
        ev_hash = compute_financial_event_hash(
            event_id=ev_id,
            tenant_id=tenant_id,
            correlation_id=correlation_id,
            payment_intent_id=payment_intent_id,
            sequence_number=seq,
            event_type=event_type.value,
            actor_type=actor_type,
            actor_id=actor_id,
            payload=payload,
            previous_event_hash=prev_hash,
            occurred_at_iso=occurred_at.isoformat(),
        )
        row = FinancialEventRow(
            id=ev_id,
            tenant_id=tenant_id,
            correlation_id=correlation_id,
            payment_intent_id=payment_intent_id,
            sequence_number=seq,
            event_type=event_type.value,
            actor_type=actor_type,
            actor_id=actor_id,
            payload=payload,
            previous_event_hash=prev_hash,
            event_hash=ev_hash,
            occurred_at=occurred_at,
        )
        self.session.add(row)
        if also_enqueue_outbox:
            self.session.add(
                OutboxEventRow(
                    id=uuid4(),
                    tenant_id=tenant_id,
                    aggregate_type="payment_intent" if payment_intent_id else "dispute_case",
                    aggregate_id=payment_intent_id or correlation_id,
                    event_type=event_type.value,
                    payload={"event_id": str(ev_id), "correlation_id": str(correlation_id), **payload},
                    status="PENDING",
                    attempts=0,
                    created_at=occurred_at,
                )
            )
        self.session.flush()
        return self._to_event(row)

    def list_events(
        self,
        tenant_id: UUID,
        *,
        correlation_id: UUID | None = None,
        payment_intent_id: UUID | None = None,
    ) -> list[FinancialEvent]:
        stmt = select(FinancialEventRow).where(FinancialEventRow.tenant_id == tenant_id)
        if correlation_id is not None:
            stmt = stmt.where(FinancialEventRow.correlation_id == correlation_id)
        if payment_intent_id is not None:
            stmt = stmt.where(FinancialEventRow.payment_intent_id == payment_intent_id)
        stmt = stmt.order_by(FinancialEventRow.occurred_at.asc(), FinancialEventRow.sequence_number.asc())
        return [self._to_event(r) for r in self.session.scalars(stmt).all()]

    def list_pending_outbox(self, limit: int = 50) -> list[OutboxEventRow]:
        return list(
            self.session.scalars(
                select(OutboxEventRow)
                .where(OutboxEventRow.status == "PENDING")
                .order_by(OutboxEventRow.created_at.asc())
                .limit(limit)
            ).all()
        )

    # ------------------------------------------------------------------
    # Evidence & Disputes
    # ------------------------------------------------------------------
    def save_evidence(self, evidence: EvidenceRecord) -> EvidenceRecord:
        row = self.session.get(EvidenceRecordRow, evidence.id)
        if row is None:
            row = EvidenceRecordRow(
                id=evidence.id,
                tenant_id=evidence.tenant_id,
                correlation_id=evidence.correlation_id,
                payment_intent_id=evidence.payment_intent_id,
                dispute_case_id=evidence.dispute_case_id,
                source_type=evidence.source_type.value,
                source_ref=evidence.source_ref,
                title=evidence.title,
                content=evidence.content,
                content_hash=evidence.content_hash,
                is_synthetic=evidence.is_synthetic,
                collected_at=evidence.collected_at,
            )
            self.session.add(row)
            self.session.flush()
        else:
            assert_same_tenant(evidence.tenant_id, row.tenant_id, "evidence_record")
        return self._to_evidence(row)

    def list_evidence(
        self,
        tenant_id: UUID,
        *,
        correlation_id: UUID | None = None,
        payment_intent_id: UUID | None = None,
        dispute_case_id: UUID | None = None,
    ) -> list[EvidenceRecord]:
        stmt = select(EvidenceRecordRow).where(EvidenceRecordRow.tenant_id == tenant_id)
        if correlation_id is not None:
            stmt = stmt.where(EvidenceRecordRow.correlation_id == correlation_id)
        if payment_intent_id is not None:
            stmt = stmt.where(EvidenceRecordRow.payment_intent_id == payment_intent_id)
        if dispute_case_id is not None:
            stmt = stmt.where(EvidenceRecordRow.dispute_case_id == dispute_case_id)
        stmt = stmt.order_by(EvidenceRecordRow.collected_at.asc())
        return [self._to_evidence(r) for r in self.session.scalars(stmt).all()]

    def save_dispute_case(self, case: DisputeCase) -> DisputeCase:
        row = self.session.get(DisputeCaseRow, case.id)
        if row is None:
            row = DisputeCaseRow(
                id=case.id,
                tenant_id=case.tenant_id,
                correlation_id=case.correlation_id,
                payment_intent_id=case.payment_intent_id,
                paypal_dispute_id=case.paypal_dispute_id,
                source_type=case.source_type.value,
                is_synthetic=case.is_synthetic,
                reason=case.reason,
                buyer_claim=case.buyer_claim,
                amount_minor=case.amount_minor,
                currency=case.currency,
                status=case.status.value,
                evidence_ids=[str(eid) for eid in case.evidence_ids],
                human_approved_for_submission=case.human_approved_for_submission,
                approved_by=case.approved_by,
                approved_at=case.approved_at,
                response_payload_hash=case.response_payload_hash,
                opened_at=case.opened_at,
                updated_at=case.updated_at,
            )
            self.session.add(row)
        else:
            assert_same_tenant(case.tenant_id, row.tenant_id, "dispute_case")
            row.status = case.status.value
            row.evidence_ids = [str(eid) for eid in case.evidence_ids]
            row.human_approved_for_submission = case.human_approved_for_submission
            row.approved_by = case.approved_by
            row.approved_at = case.approved_at
            row.response_payload_hash = case.response_payload_hash
            row.updated_at = _utc_now()
        self.session.flush()
        return self._to_dispute_case(row)

    def get_dispute_case(self, tenant_id: UUID, case_id: UUID) -> DisputeCase | None:
        row = self.session.get(DisputeCaseRow, case_id)
        if row is None:
            return None
        assert_same_tenant(tenant_id, row.tenant_id, "dispute_case")
        return self._to_dispute_case(row)

    def list_dispute_cases(self, tenant_id: UUID) -> list[DisputeCase]:
        rows = self.session.scalars(
            select(DisputeCaseRow)
            .where(DisputeCaseRow.tenant_id == tenant_id)
            .order_by(DisputeCaseRow.opened_at.desc())
        ).all()
        return [self._to_dispute_case(r) for r in rows]

    def save_dispute_analysis(self, analysis: DisputeAnalysis) -> DisputeAnalysis:
        row = DisputeAnalysisRow(
            id=analysis.id,
            tenant_id=analysis.tenant_id,
            correlation_id=analysis.correlation_id,
            dispute_case_id=analysis.dispute_case_id,
            is_synthetic=analysis.is_synthetic,
            recommendation=analysis.recommendation.value,
            confidence_score=analysis.confidence_score,
            agent_authorized=analysis.agent_authorized,
            agent_followed_policy=analysis.agent_followed_policy,
            merchant_fulfilled_order=analysis.merchant_fulfilled_order,
            contradictions=analysis.contradictions,
            missing_evidence=analysis.missing_evidence,
            citations=[c.model_dump(mode="json") for c in analysis.citations],
            rejected_claims=analysis.rejected_claims,
            grounded_summary=analysis.grounded_summary,
            draft_response_text=analysis.draft_response_text,
            requires_human_approval=analysis.requires_human_approval,
            generated_with_llm=analysis.generated_with_llm,
            analyzed_at=analysis.analyzed_at,
        )
        self.session.add(row)
        self.session.flush()
        return analysis

    def get_latest_dispute_analysis(self, tenant_id: UUID, case_id: UUID) -> DisputeAnalysis | None:
        row = self.session.scalar(
            select(DisputeAnalysisRow)
            .where(
                DisputeAnalysisRow.tenant_id == tenant_id,
                DisputeAnalysisRow.dispute_case_id == case_id,
            )
            .order_by(DisputeAnalysisRow.analyzed_at.desc())
            .limit(1)
        )
        return self._to_dispute_analysis(row) if row else None

    # ------------------------------------------------------------------
    # Row -> Contract Mappers
    # ------------------------------------------------------------------
    @staticmethod
    def _to_agent(row: AgentRow) -> AgentIdentity:
        return AgentIdentity(
            id=row.id,
            tenant_id=row.tenant_id,
            name=row.name,
            purpose=row.purpose,
            framework=row.framework,
            status=row.status,
            public_fingerprint=row.public_fingerprint,
            created_at=_ensure_utc(row.created_at),  # type: ignore[arg-type]
        )

    @staticmethod
    def _to_merchant(row: MerchantRow) -> Merchant:
        return Merchant(
            id=row.id,
            tenant_id=row.tenant_id,
            name=row.name,
            domain=row.domain,
            category=row.category,
            paypal_merchant_id=row.paypal_merchant_id,
            is_allowlisted=row.is_allowlisted,
            is_sandbox_verified=row.is_sandbox_verified,
            created_at=_ensure_utc(row.created_at),  # type: ignore[arg-type]
        )

    @staticmethod
    def _to_passport(row: SpendingPassportRow) -> SpendingPassport:
        return SpendingPassport(
            id=row.id,
            tenant_id=row.tenant_id,
            agent_id=row.agent_id,
            policy_version=row.policy_version,
            currency=row.currency,
            total_budget_minor=row.total_budget_minor,
            spent_minor=row.spent_minor,
            reserved_minor=row.reserved_minor,
            per_tx_limit_minor=row.per_tx_limit_minor,
            daily_limit_minor=row.daily_limit_minor,
            human_approval_threshold_minor=row.human_approval_threshold_minor,
            allowed_merchant_ids=[UUID(m) for m in row.allowed_merchant_ids],
            allowed_categories=list(row.allowed_categories),
            allow_unknown_merchants=row.allow_unknown_merchants,
            status=PassportStatus(row.status),
            expires_at=_ensure_utc(row.expires_at),  # type: ignore[arg-type]
            created_at=_ensure_utc(row.created_at),  # type: ignore[arg-type]
        )

    @staticmethod
    def _to_proposal(row: PurchaseProposalRow) -> PurchaseProposal:
        return PurchaseProposal(
            id=row.id,
            tenant_id=row.tenant_id,
            correlation_id=row.correlation_id,
            agent_id=row.agent_id,
            passport_id=row.passport_id,
            merchant_id=row.merchant_id,
            merchant_name=row.merchant_name,
            merchant_category=row.merchant_category,
            amount_minor=row.amount_minor,
            currency=row.currency,
            item_summary=row.item_summary,
            line_items=row.line_items,
            rationale=row.rationale,
            idempotency_key=row.idempotency_key,
            proposed_by_model=row.proposed_by_model,
            created_at=_ensure_utc(row.created_at),  # type: ignore[arg-type]
        )

    @staticmethod
    def _to_quote(row: QuoteSnapshotRow) -> QuoteSnapshot:
        return QuoteSnapshot(
            id=row.id,
            tenant_id=row.tenant_id,
            correlation_id=row.correlation_id,
            proposal_id=row.proposal_id,
            merchant_id=row.merchant_id,
            amount_minor=row.amount_minor,
            currency=row.currency,
            line_items=row.line_items,
            quote_hash=row.quote_hash,
            expires_at=_ensure_utc(row.expires_at),  # type: ignore[arg-type]
            created_at=_ensure_utc(row.created_at),  # type: ignore[arg-type]
        )

    @staticmethod
    def _to_intent(row: PaymentIntentRow) -> PaymentIntent:
        return PaymentIntent(
            id=row.id,
            tenant_id=row.tenant_id,
            correlation_id=row.correlation_id,
            proposal_id=row.proposal_id,
            agent_id=row.agent_id,
            passport_id=row.passport_id,
            merchant_id=row.merchant_id,
            quote_snapshot_id=row.quote_snapshot_id,
            quote_hash=row.quote_hash,
            amount_minor=row.amount_minor,
            currency=row.currency,
            state=PaymentState(row.state),
            idempotency_key=row.idempotency_key,
            authorization_decision_id=row.authorization_decision_id,
            approval_record_id=row.approval_record_id,
            reservation_id=row.reservation_id,
            active_attempt_id=row.active_attempt_id,
            created_at=_ensure_utc(row.created_at),  # type: ignore[arg-type]
            updated_at=_ensure_utc(row.updated_at),  # type: ignore[arg-type]
        )

    @staticmethod
    def _to_decision(row: AuthorizationDecisionRow) -> AuthorizationDecision:
        return AuthorizationDecision(
            id=row.id,
            tenant_id=row.tenant_id,
            correlation_id=row.correlation_id,
            payment_intent_id=row.payment_intent_id,
            proposal_id=row.proposal_id,
            passport_id=row.passport_id,
            quote_snapshot_id=row.quote_snapshot_id,
            quote_hash=row.quote_hash,
            policy_version=row.policy_version,
            outcome=DecisionOutcome(row.outcome),
            reason_codes=[DecisionReasonCode(rc) for rc in row.reason_codes],
            violated_constraints=row.violated_constraints,
            requires_human_approval=row.requires_human_approval,
            explanation=row.explanation,
            policy_inputs=row.policy_inputs,
            decided_at=_ensure_utc(row.decided_at),  # type: ignore[arg-type]
        )

    @staticmethod
    def _to_approval(row: ApprovalRecordRow) -> ApprovalRecord:
        return ApprovalRecord(
            id=row.id,
            tenant_id=row.tenant_id,
            correlation_id=row.correlation_id,
            payment_intent_id=row.payment_intent_id,
            decision_id=row.decision_id,
            approver_id=row.approver_id,
            status=ApprovalStatus(row.status),
            bound_merchant_id=row.bound_merchant_id,
            bound_amount_minor=row.bound_amount_minor,
            bound_currency=row.bound_currency,
            bound_quote_hash=row.bound_quote_hash,
            comment=row.comment,
            expires_at=_ensure_utc(row.expires_at),  # type: ignore[arg-type]
            decided_at=_ensure_utc(row.decided_at),
            consumed_at=_ensure_utc(row.consumed_at),
            created_at=_ensure_utc(row.created_at),  # type: ignore[arg-type]
        )

    @staticmethod
    def _to_reservation(row: BudgetReservationRow) -> BudgetReservation:
        return BudgetReservation(
            id=row.id,
            tenant_id=row.tenant_id,
            correlation_id=row.correlation_id,
            passport_id=row.passport_id,
            payment_intent_id=row.payment_intent_id,
            amount_minor=row.amount_minor,
            currency=row.currency,
            status=ReservationStatus(row.status),
            expires_at=_ensure_utc(row.expires_at),  # type: ignore[arg-type]
            created_at=_ensure_utc(row.created_at),  # type: ignore[arg-type]
            updated_at=_ensure_utc(row.updated_at),  # type: ignore[arg-type]
        )

    @staticmethod
    def _to_attempt(row: PaymentAttemptRow) -> PaymentAttempt:
        return PaymentAttempt(
            id=row.id,
            tenant_id=row.tenant_id,
            correlation_id=row.correlation_id,
            payment_intent_id=row.payment_intent_id,
            attempt_number=row.attempt_number,
            idempotency_key=row.idempotency_key,
            provider=row.provider,
            paypal_order_id=row.paypal_order_id,
            paypal_approval_url=row.paypal_approval_url,
            buyer_approval=PayPalBuyerApproval.model_validate(row.buyer_approval) if row.buyer_approval else None,
            verified_capture=VerifiedPayPalCapture.model_validate(row.verified_capture) if row.verified_capture else None,
            state=PaymentState(row.state),
            failure_code=row.failure_code,
            failure_reason=row.failure_reason,
            created_at=_ensure_utc(row.created_at),  # type: ignore[arg-type]
            updated_at=_ensure_utc(row.updated_at),  # type: ignore[arg-type]
        )

    @staticmethod
    def _to_event(row: FinancialEventRow) -> FinancialEvent:
        return FinancialEvent(
            id=row.id,
            tenant_id=row.tenant_id,
            correlation_id=row.correlation_id,
            payment_intent_id=row.payment_intent_id,
            sequence_number=row.sequence_number,
            event_type=FinancialEventType(row.event_type),
            actor_type=row.actor_type,
            actor_id=row.actor_id,
            payload=row.payload,
            previous_event_hash=row.previous_event_hash,
            event_hash=row.event_hash,
            occurred_at=_ensure_utc(row.occurred_at),  # type: ignore[arg-type]
        )

    @staticmethod
    def _to_evidence(row: EvidenceRecordRow) -> EvidenceRecord:
        return EvidenceRecord(
            id=row.id,
            tenant_id=row.tenant_id,
            correlation_id=row.correlation_id,
            payment_intent_id=row.payment_intent_id,
            dispute_case_id=row.dispute_case_id,
            source_type=row.source_type,  # type: ignore[arg-type]
            source_ref=row.source_ref,
            title=row.title,
            content=row.content,
            content_hash=row.content_hash,
            is_synthetic=row.is_synthetic,
            collected_at=_ensure_utc(row.collected_at),  # type: ignore[arg-type]
        )

    @staticmethod
    def _to_dispute_case(row: DisputeCaseRow) -> DisputeCase:
        return DisputeCase(
            id=row.id,
            tenant_id=row.tenant_id,
            correlation_id=row.correlation_id,
            payment_intent_id=row.payment_intent_id,
            paypal_dispute_id=row.paypal_dispute_id,
            source_type=row.source_type,  # type: ignore[arg-type]
            is_synthetic=row.is_synthetic,
            reason=row.reason,
            buyer_claim=row.buyer_claim,
            amount_minor=row.amount_minor,
            currency=row.currency,
            status=row.status,  # type: ignore[arg-type]
            evidence_ids=[UUID(eid) for eid in row.evidence_ids],
            human_approved_for_submission=row.human_approved_for_submission,
            approved_by=row.approved_by,
            approved_at=_ensure_utc(row.approved_at),
            response_payload_hash=row.response_payload_hash,
            opened_at=_ensure_utc(row.opened_at),  # type: ignore[arg-type]
            updated_at=_ensure_utc(row.updated_at),  # type: ignore[arg-type]
        )

    @staticmethod
    def _to_dispute_analysis(row: DisputeAnalysisRow) -> DisputeAnalysis:
        return DisputeAnalysis(
            id=row.id,
            tenant_id=row.tenant_id,
            correlation_id=row.correlation_id,
            dispute_case_id=row.dispute_case_id,
            is_synthetic=row.is_synthetic,
            recommendation=row.recommendation,  # type: ignore[arg-type]
            confidence_score=row.confidence_score,
            agent_authorized=row.agent_authorized,
            agent_followed_policy=row.agent_followed_policy,
            merchant_fulfilled_order=row.merchant_fulfilled_order,
            contradictions=row.contradictions,
            missing_evidence=row.missing_evidence,
            citations=row.citations,  # type: ignore[arg-type]
            rejected_claims=row.rejected_claims,
            grounded_summary=row.grounded_summary,
            draft_response_text=row.draft_response_text,
            requires_human_approval=row.requires_human_approval,
            generated_with_llm=row.generated_with_llm,
            analyzed_at=_ensure_utc(row.analyzed_at),  # type: ignore[arg-type]
        )

