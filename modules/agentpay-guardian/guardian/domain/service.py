"""Guardian domain service orchestrating the end-to-end payment intent lifecycle.

Strictly enforces:
1. Deterministic policy evaluation before any reservation.
2. Cryptographic quote binding & human approval consumption.
3. Atomic budget reservation and capture via LedgerRepository.
4. Complete append-only audit trail and PayPal safety invariants.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

from contracts import (
    ApprovalRecord,
    AuthorizationDecision,
    DecisionOutcome,
    DecisionReasonCode,
    FinancialEventType,
    PaymentAttempt,
    PaymentIntent,
    PaymentState,
    PurchaseProposal,
    QuoteSnapshot,
    compute_payload_hash,
)
from paypal import PayPalSandboxClient

from guardian.approvals.service import ApprovalService
from guardian.budgets.coordinator import BudgetCoordinator
from guardian.domain.exceptions import (
    ApprovalMismatchError,
    ApprovalNotFoundError,
    DuplicateIntentError,
    IntentNotFoundError,
    InvalidStateTransitionError,
    PolicyDeniedError,
)
from guardian.passports.service import PassportService
from guardian.payments.coordinator import PaymentCoordinator
from guardian.policies.engine import PolicyEngine

try:
    from database import DuplicateIdempotencyError, LedgerRepository
except (ImportError, ModuleNotFoundError):
    LedgerRepository = Any  # type: ignore[misc, assignment]

    class DuplicateIdempotencyError(ValueError):  # type: ignore[no-redef]
        pass


try:
    from sqlalchemy.exc import IntegrityError
except (ImportError, ModuleNotFoundError):
    class IntegrityError(RuntimeError):  # type: ignore[no-redef]
        pass


_SPEND_COUNTING_STATES = frozenset({
    PaymentState.CHECKOUT_READY,
    PaymentState.AWAITING_PAYPAL_BUYER,
    PaymentState.CAPTURE_PENDING,
    PaymentState.PENDING_PROVIDER,
    PaymentState.SUCCEEDED,
    PaymentState.PARTIALLY_REFUNDED,
})


def _utc_now() -> datetime:
    return datetime.now(UTC)


class GuardianService:
    """Primary orchestrator for AgentPay Guardian."""

    def __init__(
        self,
        repo: LedgerRepository,
        paypal_client: PayPalSandboxClient,
        policy_engine: PolicyEngine | None = None,
        passport_service: PassportService | None = None,
        budget_coordinator: BudgetCoordinator | None = None,
        approval_service: ApprovalService | None = None,
        payment_coordinator: PaymentCoordinator | None = None,
    ) -> None:
        self.repo = repo
        self.paypal_client = paypal_client
        self.policy_engine = policy_engine or PolicyEngine()
        self.passport_service = passport_service or PassportService(repo)
        self.budget_coordinator = budget_coordinator or BudgetCoordinator(repo)
        self.approval_service = approval_service or ApprovalService(repo)
        self.payment_coordinator = payment_coordinator or PaymentCoordinator(
            repo=repo,
            paypal_client=paypal_client,
            budget_coordinator=self.budget_coordinator,
        )

    # -------------------------------------------------------------------------
    # Intent and Proposal Ingestion
    # -------------------------------------------------------------------------
    @staticmethod
    def _proposal_payload_hash(
        *,
        passport_id: UUID,
        merchant_id: UUID,
        amount_minor: int,
        currency: str,
        line_items: list[dict[str, Any]] | None = None,
    ) -> str:
        return compute_payload_hash({
            "passport_id": str(passport_id),
            "merchant_id": str(merchant_id),
            "amount_minor": amount_minor,
            "currency": currency.upper(),
            "line_items": line_items or [],
        })

    def _assert_idempotent_match(
        self,
        *,
        existing_intent: PaymentIntent,
        proposal: PurchaseProposal,
        quote: QuoteSnapshot,
    ) -> None:
        incoming_hash = self._proposal_payload_hash(
            passport_id=proposal.passport_id,
            merchant_id=proposal.merchant_id,
            amount_minor=proposal.amount_minor,
            currency=proposal.currency,
            line_items=proposal.line_items,
        )
        get_proposal_fn = getattr(self.repo, "get_proposal", None)
        existing_proposal = (
            get_proposal_fn(proposal.tenant_id, existing_intent.proposal_id)
            if callable(get_proposal_fn)
            else None
        )
        existing_line_items = (
            existing_proposal.line_items
            if existing_proposal is not None
            else proposal.line_items
        )
        existing_hash = self._proposal_payload_hash(
            passport_id=existing_intent.passport_id,
            merchant_id=existing_intent.merchant_id,
            amount_minor=existing_intent.amount_minor,
            currency=existing_intent.currency,
            line_items=existing_line_items,
        )
        if (
            existing_intent.passport_id != proposal.passport_id
            or existing_intent.merchant_id != proposal.merchant_id
            or existing_intent.amount_minor != proposal.amount_minor
            or existing_intent.currency.upper() != proposal.currency.upper()
            or existing_intent.quote_hash != quote.quote_hash
            or existing_hash != incoming_hash
        ):
            raise DuplicateIntentError(
                f"Idempotency key '{proposal.idempotency_key}' was already used with a different proposal payload"
            )

    def _build_existing_intent_result(
        self,
        *,
        existing_intent: PaymentIntent,
        proposal: PurchaseProposal,
        quote: QuoteSnapshot,
    ) -> tuple[PaymentIntent, AuthorizationDecision]:
        self._assert_idempotent_match(
            existing_intent=existing_intent,
            proposal=proposal,
            quote=quote,
        )
        decision = None
        if existing_intent.authorization_decision_id:
            decision = self.repo.get_decision(
                proposal.tenant_id, existing_intent.authorization_decision_id
            )
        if decision is None:
            if existing_intent.state in {
                PaymentState.FAILED,
                PaymentState.CANCELLED,
                PaymentState.EXPIRED,
            }:
                fallback_outcome = DecisionOutcome.DENY
                fallback_reason = DecisionReasonCode.DENIED_INSUFFICIENT_BUDGET
            elif existing_intent.state == PaymentState.AWAITING_APPROVAL:
                fallback_outcome = DecisionOutcome.ESCALATE
                fallback_reason = DecisionReasonCode.ESCALATED_REQUIRES_HUMAN_APPROVAL
            else:
                fallback_outcome = DecisionOutcome.ALLOW
                fallback_reason = DecisionReasonCode.OK_WITHIN_POLICY
            decision = AuthorizationDecision(
                tenant_id=proposal.tenant_id,
                correlation_id=existing_intent.correlation_id,
                payment_intent_id=existing_intent.id,
                proposal_id=existing_intent.proposal_id,
                passport_id=existing_intent.passport_id,
                quote_snapshot_id=existing_intent.quote_snapshot_id,
                quote_hash=existing_intent.quote_hash,
                outcome=fallback_outcome,
                reason_codes=[fallback_reason],
                explanation="Retrieved existing idempotent intent",
            )
        return existing_intent, decision

    def _list_all_intents(self, tenant_id: UUID) -> list[PaymentIntent]:
        list_fn = getattr(self.repo, "list_intents", None)
        if not callable(list_fn):
            return []
        page_size = 200
        offset = 0
        all_intents: list[PaymentIntent] = []
        while True:
            try:
                batch = list_fn(tenant_id, limit=page_size, offset=offset)
            except TypeError:
                return list_fn(tenant_id)
            all_intents.extend(batch)
            if len(batch) < page_size:
                return all_intents
            offset += page_size

    def _compute_rolling_spend(
        self,
        *,
        tenant_id: UUID,
        passport_id: UUID,
        exclude_intent_id: UUID,
        now: datetime,
    ) -> tuple[int, int]:
        day_cutoff = now - timedelta(hours=24)
        month_cutoff = now - timedelta(days=30)
        daily_spent = 0
        monthly_spent = 0
        for item in self._list_all_intents(tenant_id):
            if item.id == exclude_intent_id or item.passport_id != passport_id:
                continue
            if item.state not in _SPEND_COUNTING_STATES:
                continue
            created = (
                item.created_at.astimezone(UTC)
                if item.created_at.tzinfo
                else item.created_at.replace(tzinfo=UTC)
            )
            if created >= month_cutoff:
                monthly_spent += item.amount_minor
                if created >= day_cutoff:
                    daily_spent += item.amount_minor
        return daily_spent, monthly_spent

    def submit_proposal(
        self,
        *,
        proposal: PurchaseProposal,
        quote: QuoteSnapshot,
        auto_reserve_if_allowed: bool = True,
    ) -> tuple[PaymentIntent, AuthorizationDecision]:
        """Submit a purchase proposal, perform deterministic policy check, and transition intent."""
        # 0. Narrow transaction-scoped advisory lock per (tenant_id, idempotency_key)
        acquire_lock = getattr(self.repo, "acquire_proposal_idempotency_lock", None)
        if callable(acquire_lock):
            acquire_lock(proposal.tenant_id, proposal.idempotency_key)

        # 1. Idempotency verification
        existing_intent = self.repo.get_intent_by_idempotency(
            proposal.tenant_id, proposal.idempotency_key
        )
        if existing_intent is not None:
            return self._build_existing_intent_result(
                existing_intent=existing_intent,
                proposal=proposal,
                quote=quote,
            )

        # 2. Persist proposal, quote, and PaymentIntent inside transactional savepoint if available
        intent_id = uuid4()
        now = _utc_now()
        intent = PaymentIntent(
            id=intent_id,
            tenant_id=proposal.tenant_id,
            correlation_id=proposal.correlation_id,
            proposal_id=proposal.id,
            agent_id=proposal.agent_id,
            passport_id=proposal.passport_id,
            merchant_id=proposal.merchant_id,
            quote_snapshot_id=quote.id,
            quote_hash=quote.quote_hash,
            amount_minor=proposal.amount_minor,
            currency=proposal.currency,
            state=PaymentState.CREATED,
            idempotency_key=proposal.idempotency_key,
            created_at=now,
            updated_at=now,
        )

        session = getattr(self.repo, "session", None)
        begin_nested = getattr(session, "begin_nested", None) if session is not None else None
        try:
            if callable(begin_nested):
                with begin_nested():
                    self.repo.save_proposal(proposal)
                    self.repo.save_quote(quote)
                    saved_intent = self.repo.save_intent(intent)
            else:
                self.repo.save_proposal(proposal)
                self.repo.save_quote(quote)
                saved_intent = self.repo.save_intent(intent)
        except (DuplicateIdempotencyError, IntegrityError):
            existing_after_race = self.repo.get_intent_by_idempotency(
                proposal.tenant_id, proposal.idempotency_key
            )
            if existing_after_race is not None:
                return self._build_existing_intent_result(
                    existing_intent=existing_after_race,
                    proposal=proposal,
                    quote=quote,
                )
            raise

        self.repo.append_financial_event(
            tenant_id=proposal.tenant_id,
            correlation_id=proposal.correlation_id,
            payment_intent_id=saved_intent.id,
            event_type=FinancialEventType.PROPOSAL_CREATED,
            actor_type="AGENT",
            actor_id=str(proposal.agent_id),
            payload={
                "proposal_id": str(proposal.id),
                "quote_id": str(quote.id),
                "amount_minor": proposal.amount_minor,
                "currency": proposal.currency,
                "merchant_id": str(proposal.merchant_id),
            },
        )

        # 4. Transition to POLICY_CHECK
        self.repo.transition_intent(
            tenant_id=proposal.tenant_id,
            intent_id=saved_intent.id,
            target_state=PaymentState.POLICY_CHECK,
        )

        # 5. Fetch agent, passport, merchant, and rolling spend for deterministic policy-v1 evaluation
        passport = self.passport_service.get_passport(proposal.tenant_id, proposal.passport_id)
        merchant = self.passport_service.get_merchant(proposal.tenant_id, proposal.merchant_id)
        get_agent_fn = getattr(self.repo, "get_agent", None)
        agent = get_agent_fn(proposal.tenant_id, proposal.agent_id) if callable(get_agent_fn) else None
        daily_spent_minor, monthly_spent_minor = self._compute_rolling_spend(
            tenant_id=proposal.tenant_id,
            passport_id=proposal.passport_id,
            exclude_intent_id=saved_intent.id,
            now=now,
        )

        # 6. Evaluate policy deterministically
        decision = self.policy_engine.evaluate(
            proposal=proposal,
            passport=passport,
            merchant=merchant,
            quote=quote,
            agent=agent,
            daily_spent_minor=daily_spent_minor,
            monthly_spent_minor=monthly_spent_minor,
            payment_intent_id=saved_intent.id,
            now=now,
        )
        saved_decision = self.repo.save_decision(decision)

        self.repo.append_financial_event(
            tenant_id=proposal.tenant_id,
            correlation_id=proposal.correlation_id,
            payment_intent_id=saved_intent.id,
            event_type=FinancialEventType.POLICY_EVALUATED,
            actor_type="POLICY_ENGINE",
            actor_id=decision.policy_version,
            payload={
                "decision_id": str(saved_decision.id),
                "outcome": decision.outcome.value,
                "reason_codes": [rc.value for rc in decision.reason_codes],
                "requires_human_approval": decision.requires_human_approval,
            },
        )

        # 7. Act on decision outcome
        if decision.outcome == DecisionOutcome.DENY:
            self.repo.transition_intent(
                tenant_id=proposal.tenant_id,
                intent_id=saved_intent.id,
                target_state=PaymentState.FAILED,
                authorization_decision_id=saved_decision.id,
            )
            self.repo.append_financial_event(
                tenant_id=proposal.tenant_id,
                correlation_id=proposal.correlation_id,
                payment_intent_id=saved_intent.id,
                event_type=FinancialEventType.PAYMENT_FAILED,
                actor_type="POLICY_ENGINE",
                actor_id=decision.policy_version,
                payload={
                    "reason_codes": [rc.value for rc in decision.reason_codes],
                    "violations": decision.violated_constraints,
                },
            )
            raise PolicyDeniedError(
                f"Purchase proposal denied by policy: {decision.explanation}",
                reason_codes=[rc.value for rc in decision.reason_codes],
            )

        if decision.outcome == DecisionOutcome.ESCALATE or decision.requires_human_approval:
            # Create pending approval record
            approval = self.approval_service.create_approval_request(
                tenant_id=proposal.tenant_id,
                correlation_id=proposal.correlation_id,
                payment_intent_id=saved_intent.id,
                decision_id=saved_decision.id,
                approver_id="pending-human-review",
                bound_merchant_id=proposal.merchant_id,
                bound_amount_minor=proposal.amount_minor,
                bound_currency=proposal.currency,
                bound_quote_hash=quote.quote_hash,
                comment="Escalated for human policy review",
            )
            # Transition from POLICY_CHECK to AWAITING_APPROVAL
            awaiting_intent = self.repo.transition_intent(
                tenant_id=proposal.tenant_id,
                intent_id=saved_intent.id,
                target_state=PaymentState.AWAITING_APPROVAL,
                authorization_decision_id=saved_decision.id,
                approval_record_id=approval.id,
            )
            return awaiting_intent, saved_decision

        # ALLOW without human escalation
        reservation_id: UUID | None = None
        if auto_reserve_if_allowed:
            reservation = self.budget_coordinator.reserve(
                tenant_id=proposal.tenant_id,
                correlation_id=proposal.correlation_id,
                passport_id=proposal.passport_id,
                payment_intent_id=saved_intent.id,
                amount_minor=proposal.amount_minor,
                currency=proposal.currency,
            )
            reservation_id = reservation.id

        ready_intent = self.repo.transition_intent(
            tenant_id=proposal.tenant_id,
            intent_id=saved_intent.id,
            target_state=PaymentState.CHECKOUT_READY,
            authorization_decision_id=saved_decision.id,
            reservation_id=reservation_id,
        )
        return ready_intent, saved_decision

    # -------------------------------------------------------------------------
    # Human Approvals
    # -------------------------------------------------------------------------
    def approve_and_consume(
        self,
        *,
        tenant_id: UUID,
        intent_id: UUID,
        approval_id: UUID,
        approver_id: str,
        approved: bool = True,
        comment: str | None = None,
    ) -> tuple[PaymentIntent, ApprovalRecord]:
        """Record human approval or rejection; on approval, consume atomically and reserve budget."""
        intent = self.repo.get_intent(tenant_id, intent_id)
        if intent is None:
            raise IntentNotFoundError(f"PaymentIntent {intent_id} not found")

        if intent.state != PaymentState.AWAITING_APPROVAL:
            raise InvalidStateTransitionError(
                f"Cannot decide approval for intent in state {intent.state.value} "
                f"(must be AWAITING_APPROVAL)"
            )

        approval = self.approval_service.get_approval(tenant_id, approval_id)
        if approval is None:
            raise ApprovalNotFoundError(f"ApprovalRecord {approval_id} not found")
        if approval.payment_intent_id != intent.id:
            raise ApprovalMismatchError(
                f"Approval {approval_id} is bound to intent {approval.payment_intent_id}, "
                f"not {intent.id}"
            )

        if not approved:
            rejected_approval = self.approval_service.decide_approval(
                tenant_id=tenant_id,
                approval_id=approval_id,
                approver_id=approver_id,
                approved=False,
                comment=comment,
            )
            if intent.reservation_id:
                self.budget_coordinator.release(
                    tenant_id=tenant_id,
                    correlation_id=intent.correlation_id,
                    payment_intent_id=intent.id,
                    reservation_id=intent.reservation_id,
                    actor_type="HUMAN_APPROVER",
                    actor_id=approver_id,
                    reason=comment or "Human approver rejected proposal",
                )
            failed_intent = self.repo.transition_intent(
                tenant_id=tenant_id,
                intent_id=intent_id,
                target_state=PaymentState.FAILED,
                approval_record_id=rejected_approval.id,
            )
            self.repo.append_financial_event(
                tenant_id=tenant_id,
                correlation_id=intent.correlation_id,
                payment_intent_id=intent.id,
                event_type=FinancialEventType.PAYMENT_FAILED,
                actor_type="HUMAN_APPROVER",
                actor_id=approver_id,
                payload={
                    "approval_id": str(rejected_approval.id),
                    "reason": comment or "Human approver rejected proposal",
                },
            )
            return failed_intent, rejected_approval

        quote = self.repo.get_quote(tenant_id, intent.quote_snapshot_id)
        passport = self.repo.get_passport(tenant_id, intent.passport_id)

        # Decide approval
        self.approval_service.decide_approval(
            tenant_id=tenant_id,
            approval_id=approval_id,
            approver_id=approver_id,
            approved=True,
            comment=comment,
        )

        # Consume approval with cryptographic binding and expiry checks
        consumed_approval = self.approval_service.consume_approval(
            tenant_id=tenant_id,
            approval_id=approval_id,
            current_merchant_id=intent.merchant_id,
            current_amount_minor=intent.amount_minor,
            current_currency=intent.currency,
            current_quote_hash=intent.quote_hash,
            payment_intent_id=intent.id,
            quote=quote,
            passport=passport,
        )

        # Reserve budget atomically
        reservation = self.budget_coordinator.reserve(
            tenant_id=tenant_id,
            correlation_id=intent.correlation_id,
            passport_id=intent.passport_id,
            payment_intent_id=intent.id,
            amount_minor=intent.amount_minor,
            currency=intent.currency,
        )

        ready_intent = self.repo.transition_intent(
            tenant_id=tenant_id,
            intent_id=intent_id,
            target_state=PaymentState.CHECKOUT_READY,
            approval_record_id=consumed_approval.id,
            reservation_id=reservation.id,
        )
        return ready_intent, consumed_approval

    # -------------------------------------------------------------------------
    # Checkout & PayPal Flow
    # -------------------------------------------------------------------------
    async def initiate_checkout(
        self,
        *,
        tenant_id: UUID,
        intent_id: UUID,
        attempt_number: int = 1,
        idempotency_key: str | None = None,
        return_url: str | None = None,
        cancel_url: str | None = None,
    ) -> tuple[PaymentIntent, PaymentAttempt]:
        intent = self.repo.get_intent(tenant_id, intent_id)
        if intent is None:
            raise IntentNotFoundError(f"PaymentIntent {intent_id} not found")

        key = idempotency_key or f"attempt-{intent.id}-{attempt_number}"
        attempt = await self.payment_coordinator.create_checkout(
            intent=intent,
            attempt_number=attempt_number,
            idempotency_key=key,
            return_url=return_url,
            cancel_url=cancel_url,
        )
        refreshed_intent = self.repo.get_intent(tenant_id, intent_id)
        assert refreshed_intent is not None
        return refreshed_intent, attempt

    def handle_buyer_approved(
        self,
        *,
        tenant_id: UUID,
        intent_id: UUID,
        attempt_id: UUID,
        payer_id: str | None = None,
    ) -> tuple[PaymentIntent, PaymentAttempt]:
        attempt = self.payment_coordinator.record_buyer_approval(
            tenant_id=tenant_id,
            intent_id=intent_id,
            attempt_id=attempt_id,
            payer_id=payer_id,
        )
        intent = self.repo.get_intent(tenant_id, intent_id)
        assert intent is not None
        return intent, attempt

    async def execute_capture(
        self,
        *,
        tenant_id: UUID,
        intent_id: UUID,
        attempt_id: UUID,
    ) -> tuple[PaymentIntent, PaymentAttempt]:
        return await self.payment_coordinator.capture_order(
            tenant_id=tenant_id,
            intent_id=intent_id,
            attempt_id=attempt_id,
        )

    def handle_buyer_declined(
        self,
        *,
        tenant_id: UUID,
        intent_id: UUID,
        attempt_id: UUID,
        reason: str = "Buyer cancelled or closed checkout modal",
    ) -> tuple[PaymentIntent, PaymentAttempt]:
        return self.payment_coordinator.handle_buyer_declined(
            tenant_id=tenant_id,
            intent_id=intent_id,
            attempt_id=attempt_id,
            reason=reason,
        )

    async def reconcile_pending(
        self,
        *,
        tenant_id: UUID,
        intent_id: UUID,
        attempt_id: UUID,
    ) -> tuple[PaymentIntent, PaymentAttempt]:
        return await self.payment_coordinator.reconcile_pending(
            tenant_id=tenant_id,
            intent_id=intent_id,
            attempt_id=attempt_id,
        )

    async def refund_payment(
        self,
        *,
        tenant_id: UUID,
        intent_id: UUID,
        attempt_id: UUID | None = None,
        amount_minor: int | None = None,
        reason: str = "Operator requested refund",
    ) -> tuple[PaymentIntent, PaymentAttempt, dict[str, Any]]:
        return await self.payment_coordinator.refund_payment(
            tenant_id=tenant_id,
            intent_id=intent_id,
            attempt_id=attempt_id,
            amount_minor=amount_minor,
            reason=reason,
        )

    # -------------------------------------------------------------------------
    # Read-Only Lookups
    # -------------------------------------------------------------------------
    def get_intent(self, tenant_id: UUID, intent_id: UUID) -> PaymentIntent | None:
        return self.repo.get_intent(tenant_id, intent_id)

    def get_attempt(self, tenant_id: UUID, attempt_id: UUID) -> PaymentAttempt | None:
        return self.repo.get_attempt(tenant_id, attempt_id)

    def get_decision(self, tenant_id: UUID, decision_id: UUID) -> AuthorizationDecision | None:
        return self.repo.get_decision(tenant_id, decision_id)

    def get_approval(self, tenant_id: UUID, approval_id: UUID) -> ApprovalRecord | None:
        return self.repo.get_approval(tenant_id, approval_id)
