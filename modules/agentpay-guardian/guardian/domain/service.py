"""Guardian domain service orchestrating the end-to-end payment intent lifecycle.

Strictly enforces:
1. Deterministic policy evaluation before any reservation.
2. Cryptographic quote binding & human approval consumption.
3. Atomic budget reservation and capture via LedgerRepository.
4. Complete append-only audit trail and PayPal safety invariants.
"""

from __future__ import annotations

import contextlib
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

from contracts import (
    ApprovalRecord,
    AuthorizationDecision,
    DecisionOutcome,
    FinancialEventType,
    PaymentAttempt,
    PaymentIntent,
    PaymentState,
    PurchaseProposal,
    QuoteSnapshot,
)
from paypal import PayPalSandboxClient

from guardian.approvals.service import ApprovalService
from guardian.budgets.coordinator import BudgetCoordinator
from guardian.domain.exceptions import (
    DuplicateIntentError,
    IntentNotFoundError,
    InvalidStateTransitionError,
    PolicyDeniedError,
)
from guardian.passports.service import PassportService
from guardian.payments.coordinator import PaymentCoordinator
from guardian.policies.engine import PolicyEngine

try:
    from database import LedgerRepository
except (ImportError, ModuleNotFoundError):
    LedgerRepository = Any  # type: ignore[misc, assignment]


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
    def submit_proposal(
        self,
        *,
        proposal: PurchaseProposal,
        quote: QuoteSnapshot,
        auto_reserve_if_allowed: bool = True,
    ) -> tuple[PaymentIntent, AuthorizationDecision]:
        """Submit a purchase proposal, perform deterministic policy check, and transition intent."""
        # 1. Idempotency verification
        existing_intent = self.repo.get_intent_by_idempotency(
            proposal.tenant_id, proposal.idempotency_key
        )
        if existing_intent is not None:
            if (
                existing_intent.amount_minor != proposal.amount_minor
                or existing_intent.currency.upper() != proposal.currency.upper()
                or existing_intent.merchant_id != proposal.merchant_id
                or existing_intent.agent_id != proposal.agent_id
                or existing_intent.quote_hash != quote.quote_hash
            ):
                raise DuplicateIntentError(
                    f"Idempotency key '{proposal.idempotency_key}' already used with different parameters"
                )

            decision = None
            if existing_intent.authorization_decision_id:
                decision = self.repo.get_decision(
                    proposal.tenant_id, existing_intent.authorization_decision_id
                )
            if decision is None:
                # Retrieve or construct existing decision representation
                decision = AuthorizationDecision(
                    tenant_id=proposal.tenant_id,
                    correlation_id=proposal.correlation_id,
                    payment_intent_id=existing_intent.id,
                    proposal_id=proposal.id,
                    passport_id=proposal.passport_id,
                    quote_snapshot_id=quote.id,
                    quote_hash=quote.quote_hash,
                    outcome=DecisionOutcome.ALLOW if existing_intent.state != PaymentState.FAILED else DecisionOutcome.DENY,
                    reason_codes=[],
                    explanation="Retrieved existing idempotent intent",
                )
            return existing_intent, decision

        # 2. Persist proposal and quote
        self.repo.save_proposal(proposal)
        self.repo.save_quote(quote)

        # 3. Create PaymentIntent in CREATED state
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
        saved_intent = self.repo.save_intent(intent)

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

        # 5. Fetch passport, merchant, agent, and rolling daily spend
        passport = self.passport_service.get_passport(proposal.tenant_id, proposal.passport_id)
        merchant = self.passport_service.get_merchant(proposal.tenant_id, proposal.merchant_id)
        agent = None
        get_agent_fn = getattr(self.repo, "get_agent", None)
        if callable(get_agent_fn):
            with contextlib.suppress(Exception):
                agent = get_agent_fn(proposal.tenant_id, proposal.agent_id)

        daily_spent = 0
        list_intents_fn = getattr(self.repo, "list_intents", None)
        if callable(list_intents_fn):
            try:
                today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
                intents = list_intents_fn(proposal.tenant_id, agent_id=proposal.agent_id, limit=100)
                for it in intents:
                    it_created = it.created_at
                    if it_created.tzinfo is None:
                        it_created = it_created.replace(tzinfo=UTC)
                    if (
                        it.passport_id == proposal.passport_id
                        and it_created >= today_start
                        and it.state in (PaymentState.SUCCEEDED, PaymentState.CAPTURE_PENDING, PaymentState.PENDING_PROVIDER)
                    ):
                        daily_spent += it.amount_minor
            except Exception:
                daily_spent = 0

        # 6. Evaluate policy deterministically
        decision = self.policy_engine.evaluate(
            proposal=proposal,
            passport=passport,
            merchant=merchant,
            quote=quote,
            agent=agent,
            historical_daily_spend_minor=daily_spent,
            payment_intent_id=saved_intent.id,
            now=now,
        )
        saved_decision = self.repo.save_decision(decision)

        # Record passport snapshot if supported by repo (GAP-022)
        save_snapshot_fn = getattr(self.repo, "save_passport_snapshot", None)
        if callable(save_snapshot_fn):
            with contextlib.suppress(Exception):
                save_snapshot_fn(
                    tenant_id=proposal.tenant_id,
                    passport_id=passport.id,
                    decision_id=saved_decision.id,
                    snapshot_data=passport.model_dump(mode="json"),
                )

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
        comment: str | None = None,
    ) -> tuple[PaymentIntent, ApprovalRecord]:
        """Record human approval and consume it atomically, advancing intent to CHECKOUT_READY."""
        intent = self.repo.get_intent(tenant_id, intent_id)
        if intent is None:
            raise IntentNotFoundError(f"PaymentIntent {intent_id} not found")

        if intent.state != PaymentState.AWAITING_APPROVAL:
            raise InvalidStateTransitionError(
                f"Cannot consume approval for intent in state {intent.state.value} "
                f"(must be AWAITING_APPROVAL)"
            )

        # Decide approval
        self.approval_service.decide_approval(
            tenant_id=tenant_id,
            approval_id=approval_id,
            approver_id=approver_id,
            approved=True,
            comment=comment,
        )

        # Consume approval with cryptographic binding checks
        consumed_approval = self.approval_service.consume_approval(
            tenant_id=tenant_id,
            approval_id=approval_id,
            current_merchant_id=intent.merchant_id,
            current_amount_minor=intent.amount_minor,
            current_currency=intent.currency,
            current_quote_hash=intent.quote_hash,
            payment_intent_id=intent.id,
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

    def reject_approval(
        self,
        *,
        tenant_id: UUID,
        intent_id: UUID,
        approval_id: UUID,
        approver_id: str,
        comment: str | None = None,
    ) -> tuple[PaymentIntent, ApprovalRecord]:
        """Record human rejection of a proposal, cancel intent and release budget hold."""
        intent = self.repo.get_intent(tenant_id, intent_id)
        if intent is None:
            raise IntentNotFoundError(f"PaymentIntent {intent_id} not found")

        if intent.state != PaymentState.AWAITING_APPROVAL:
            raise InvalidStateTransitionError(
                f"Cannot reject approval for intent in state {intent.state.value} "
                f"(must be AWAITING_APPROVAL)"
            )

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
                reason=comment or "Rejected by human approver",
            )

        cancelled_intent = self.repo.transition_intent(
            tenant_id=tenant_id,
            intent_id=intent_id,
            target_state=PaymentState.CANCELLED,
            approval_record_id=rejected_approval.id,
        )
        return cancelled_intent, rejected_approval

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

    async def refund_intent(
        self,
        *,
        tenant_id: UUID,
        intent_id: UUID,
        amount_minor: int | None = None,
        note: str | None = None,
    ) -> tuple[PaymentIntent, Any]:
        """Refund a succeeded payment intent."""
        return await self.payment_coordinator.refund_order(
            tenant_id=tenant_id,
            intent_id=intent_id,
            amount_minor=amount_minor,
            note=note,
        )

    async def void_intent(
        self,
        *,
        tenant_id: UUID,
        intent_id: UUID,
        note: str | None = None,
    ) -> PaymentIntent:
        """Void an authorized payment intent and release budget hold."""
        return await self.payment_coordinator.void_authorization(
            tenant_id=tenant_id,
            intent_id=intent_id,
            note=note,
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
