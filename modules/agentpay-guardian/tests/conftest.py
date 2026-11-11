"""Test configuration and fixtures for AgentPay Guardian."""

from __future__ import annotations

import threading
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

import pytest
from contracts import (
    AgentIdentity,
    ApprovalRecord,
    ApprovalStatus,
    AuthorizationDecision,
    BudgetReservation,
    EvidenceRecord,
    FinancialEvent,
    FinancialEventType,
    Merchant,
    PassportStatus,
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
    compute_payload_hash,
    compute_quote_hash,
)
from contracts.fixtures import (
    AGENT_PROCUREMENT_ID,
    BASE_TIME,
    MERCHANT_SANDBOX_CLOUD_ID,
    MERCHANT_UNKNOWN_ID,
    PASSPORT_DEFAULT_ID,
    TENANT_ALPHA_ID,
    build_base_entities,
)
from guardian.budgets.coordinator import BudgetCoordinator
from guardian.domain.exceptions import GuardianError, InsufficientBudgetError
from guardian.domain.service import GuardianService
from guardian.passports.service import PassportService
from guardian.policies.engine import PolicyEngine
from paypal import (
    PayPalCaptureResult,
    PayPalOrderCreationResult,
    PayPalReconciliationResult,
    PayPalTimeoutError,
)
from security import compute_financial_event_hash


def run_sync(coro):
    """Run an async coroutine synchronously without creating OS network sockets."""
    stack = [coro]
    last_res = None
    while stack:
        curr = stack[-1]
        try:
            res = curr.send(last_res)
            last_res = None
            if hasattr(res, "send"):
                stack.append(res)
        except StopIteration as e:
            last_res = e.value
            stack.pop()
    return last_res


class InMemoryLedgerRepository:
    """Thread-safe in-memory implementation of the canonical LedgerRepository contract."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.tenants: dict[UUID, Tenant] = {}
        self.agents: dict[UUID, AgentIdentity] = {}
        self.merchants: dict[UUID, Merchant] = {}
        self.passports: dict[UUID, SpendingPassport] = {}
        self.proposals: dict[UUID, PurchaseProposal] = {}
        self.quotes: dict[UUID, QuoteSnapshot] = {}
        self.intents: dict[UUID, PaymentIntent] = {}
        self.idempotency_map: dict[tuple[UUID, str], UUID] = {}
        self.decisions: dict[UUID, AuthorizationDecision] = {}
        self.approvals: dict[UUID, ApprovalRecord] = {}
        self.reservations: dict[UUID, BudgetReservation] = {}
        self.attempts: dict[UUID, PaymentAttempt] = {}
        self.paypal_order_map: dict[str, UUID] = {}
        self.events: list[FinancialEvent] = []
        self.evidence: list[EvidenceRecord] = []

    def upsert_tenant(self, tenant: Tenant) -> Tenant:
        with self._lock:
            self.tenants[tenant.id] = tenant
            return tenant

    def create_agent(self, agent: AgentIdentity) -> AgentIdentity:
        with self._lock:
            self.agents[agent.id] = agent
            return agent

    def get_agent(self, tenant_id: UUID, agent_id: UUID) -> AgentIdentity | None:
        with self._lock:
            return self.agents.get(agent_id)

    def list_agents(self, tenant_id: UUID) -> list[AgentIdentity]:
        with self._lock:
            return [a for a in self.agents.values() if a.tenant_id == tenant_id]

    def create_merchant(self, merchant: Merchant) -> Merchant:
        with self._lock:
            self.merchants[merchant.id] = merchant
            return merchant

    def get_merchant(self, tenant_id: UUID, merchant_id: UUID) -> Merchant | None:
        with self._lock:
            return self.merchants.get(merchant_id)

    def list_merchants(self, tenant_id: UUID) -> list[Merchant]:
        with self._lock:
            return [m for m in self.merchants.values() if m.tenant_id == tenant_id]

    def create_passport(self, passport: SpendingPassport) -> SpendingPassport:
        with self._lock:
            self.passports[passport.id] = passport
            return passport

    def get_passport(self, tenant_id: UUID, passport_id: UUID) -> SpendingPassport | None:
        with self._lock:
            return self.passports.get(passport_id)

    def list_passports(self, tenant_id: UUID) -> list[SpendingPassport]:
        with self._lock:
            return [p for p in self.passports.values() if p.tenant_id == tenant_id]

    def save_proposal(self, proposal: PurchaseProposal) -> PurchaseProposal:
        with self._lock:
            self.proposals[proposal.id] = proposal
            return proposal

    def get_proposal(self, tenant_id: UUID, proposal_id: UUID) -> PurchaseProposal | None:
        with self._lock:
            return self.proposals.get(proposal_id)

    def save_quote(self, quote: QuoteSnapshot) -> QuoteSnapshot:
        with self._lock:
            self.quotes[quote.id] = quote
            return quote

    def get_quote(self, tenant_id: UUID, quote_id: UUID) -> QuoteSnapshot | None:
        with self._lock:
            return self.quotes.get(quote_id)

    def get_intent_by_idempotency(self, tenant_id: UUID, idempotency_key: str) -> PaymentIntent | None:
        with self._lock:
            intent_id = self.idempotency_map.get((tenant_id, idempotency_key))
            return self.intents.get(intent_id) if intent_id else None

    def save_intent(self, intent: PaymentIntent) -> PaymentIntent:
        with self._lock:
            self.intents[intent.id] = intent
            self.idempotency_map[(intent.tenant_id, intent.idempotency_key)] = intent.id
            return intent

    def get_intent(self, tenant_id: UUID, intent_id: UUID) -> PaymentIntent | None:
        with self._lock:
            return self.intents.get(intent_id)

    def list_intents(self, tenant_id: UUID) -> list[PaymentIntent]:
        with self._lock:
            return [i for i in self.intents.values() if i.tenant_id == tenant_id]

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
        with self._lock:
            intent = self.intents.get(intent_id)
            if intent is None:
                raise ValueError(f"PaymentIntent {intent_id} not found")
            assert_payment_transition(intent.state, target_state)
            updates: dict[str, Any] = {"state": target_state, "updated_at": datetime.now(UTC)}
            if authorization_decision_id is not None:
                updates["authorization_decision_id"] = authorization_decision_id
            if approval_record_id is not None:
                updates["approval_record_id"] = approval_record_id
            if reservation_id is not None:
                updates["reservation_id"] = reservation_id
            if active_attempt_id is not None:
                updates["active_attempt_id"] = active_attempt_id
            updated = intent.model_copy(update=updates)
            self.intents[intent_id] = updated
            return updated

    def save_decision(self, decision: AuthorizationDecision) -> AuthorizationDecision:
        with self._lock:
            self.decisions[decision.id] = decision
            return decision

    def get_decision(self, tenant_id: UUID, decision_id: UUID) -> AuthorizationDecision | None:
        with self._lock:
            return self.decisions.get(decision_id)

    def save_approval(self, approval: ApprovalRecord) -> ApprovalRecord:
        with self._lock:
            self.approvals[approval.id] = approval
            return approval

    def get_approval(self, tenant_id: UUID, approval_id: UUID) -> ApprovalRecord | None:
        with self._lock:
            return self.approvals.get(approval_id)

    def update_approval(self, approval: ApprovalRecord) -> ApprovalRecord:
        with self._lock:
            self.approvals[approval.id] = approval
            return approval

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
        with self._lock:
            # Check existing reservation for this intent
            for res in self.reservations.values():
                if res.payment_intent_id == payment_intent_id:
                    return res

            passport = self.passports.get(passport_id)
            if passport is None:
                raise ValueError(f"SpendingPassport {passport_id} not found")

            avail = passport.total_budget_minor - passport.spent_minor - passport.reserved_minor
            if avail < amount_minor or passport.status != PassportStatus.ACTIVE:
                raise InsufficientBudgetError(
                    f"Insufficient available budget on passport {passport_id}: requested {amount_minor}, available {avail}"
                )

            # Atomically increment reserved_minor
            updated_passport = passport.model_copy(
                update={"reserved_minor": passport.reserved_minor + amount_minor}
            )
            self.passports[passport_id] = updated_passport

            reservation = BudgetReservation(
                id=uuid4(),
                tenant_id=tenant_id,
                correlation_id=correlation_id,
                passport_id=passport_id,
                payment_intent_id=payment_intent_id,
                amount_minor=amount_minor,
                currency=currency.upper(),
                status=ReservationStatus.HELD,
                expires_at=expires_at,
            )
            self.reservations[reservation.id] = reservation
            return reservation

    def capture_reservation_atomic(self, tenant_id: UUID, reservation_id: UUID) -> BudgetReservation:
        with self._lock:
            reservation = self.reservations.get(reservation_id)
            if reservation is None:
                raise ValueError(f"BudgetReservation {reservation_id} not found")
            if reservation.status == ReservationStatus.CAPTURED:
                return reservation
            if reservation.status != ReservationStatus.HELD:
                raise ValueError(f"Cannot capture reservation in state {reservation.status}")

            passport = self.passports.get(reservation.passport_id)
            if passport is None:
                raise ValueError(f"Passport {reservation.passport_id} not found")

            # Atomically move reserved -> spent
            updated_passport = passport.model_copy(
                update={
                    "reserved_minor": passport.reserved_minor - reservation.amount_minor,
                    "spent_minor": passport.spent_minor + reservation.amount_minor,
                }
            )
            self.passports[passport.id] = updated_passport

            captured = reservation.model_copy(
                update={"status": ReservationStatus.CAPTURED, "updated_at": datetime.now(UTC)}
            )
            self.reservations[reservation_id] = captured
            return captured

    def release_reservation_atomic(self, tenant_id: UUID, reservation_id: UUID) -> BudgetReservation:
        with self._lock:
            reservation = self.reservations.get(reservation_id)
            if reservation is None:
                raise ValueError(f"BudgetReservation {reservation_id} not found")
            if reservation.status == ReservationStatus.RELEASED:
                return reservation
            if reservation.status != ReservationStatus.HELD:
                raise ValueError(f"Cannot release reservation in state {reservation.status}")

            passport = self.passports.get(reservation.passport_id)
            if passport is not None:
                updated_passport = passport.model_copy(
                    update={
                        "reserved_minor": max(0, passport.reserved_minor - reservation.amount_minor),
                    }
                )
                self.passports[passport.id] = updated_passport

            released = reservation.model_copy(
                update={"status": ReservationStatus.RELEASED, "updated_at": datetime.now(UTC)}
            )
            self.reservations[reservation_id] = released
            return released

    def get_reservation(self, tenant_id: UUID, reservation_id: UUID) -> BudgetReservation | None:
        with self._lock:
            return self.reservations.get(reservation_id)

    def save_attempt(self, attempt: PaymentAttempt) -> PaymentAttempt:
        with self._lock:
            self.attempts[attempt.id] = attempt
            if attempt.paypal_order_id:
                self.paypal_order_map[attempt.paypal_order_id] = attempt.id
            return attempt

    def get_attempt(self, tenant_id: UUID, attempt_id: UUID) -> PaymentAttempt | None:
        with self._lock:
            return self.attempts.get(attempt_id)

    def get_attempt_by_paypal_order(self, tenant_id: UUID, paypal_order_id: str) -> PaymentAttempt | None:
        with self._lock:
            attempt_id = self.paypal_order_map.get(paypal_order_id)
            return self.attempts.get(attempt_id) if attempt_id else None

    def update_attempt(self, attempt: PaymentAttempt) -> PaymentAttempt:
        with self._lock:
            self.attempts[attempt.id] = attempt
            if attempt.paypal_order_id:
                self.paypal_order_map[attempt.paypal_order_id] = attempt.id
            return attempt

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
        with self._lock:
            # Hash chaining
            matching = [
                e for e in self.events if e.tenant_id == tenant_id and e.correlation_id == correlation_id
            ]
            seq = len(matching) + 1
            prev_hash = matching[-1].event_hash if matching else None
            ev_id = uuid4()
            occurred_at = datetime.now(UTC)

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

            event = FinancialEvent(
                id=ev_id,
                tenant_id=tenant_id,
                correlation_id=correlation_id,
                payment_intent_id=payment_intent_id,
                sequence_number=seq,
                event_type=event_type,
                actor_type=actor_type,
                actor_id=actor_id,
                payload=payload,
                previous_event_hash=prev_hash,
                event_hash=ev_hash,
                occurred_at=occurred_at,
            )
            self.events.append(event)
            return event

    def list_events(
        self,
        tenant_id: UUID,
        *,
        correlation_id: UUID | None = None,
        payment_intent_id: UUID | None = None,
    ) -> list[FinancialEvent]:
        with self._lock:
            result = [e for e in self.events if e.tenant_id == tenant_id]
            if correlation_id:
                result = [e for e in result if e.correlation_id == correlation_id]
            if payment_intent_id:
                result = [e for e in result if e.payment_intent_id == payment_intent_id]
            return sorted(result, key=lambda e: e.sequence_number)

    def save_evidence(self, evidence: EvidenceRecord) -> EvidenceRecord:
        with self._lock:
            self.evidence.append(evidence)
            return evidence

    def list_evidence(
        self,
        tenant_id: UUID,
        *,
        correlation_id: UUID | None = None,
        payment_intent_id: UUID | None = None,
    ) -> list[EvidenceRecord]:
        with self._lock:
            result = [ev for ev in self.evidence if ev.tenant_id == tenant_id]
            if correlation_id:
                result = [ev for ev in result if ev.correlation_id == correlation_id]
            if payment_intent_id:
                result = [ev for ev in result if ev.payment_intent_id == payment_intent_id]
            return result


class MockPayPalClient:
    """Mock PayPal sandbox client returning deterministic results."""

    def __init__(self, mode: str = "success") -> None:
        self.mode = mode  # "success", "timeout", "buyer_cancelled"

    async def create_order(
        self,
        *,
        amount_minor: int,
        currency: str,
        reference_id: str,
        description: str,
        request_id: str,
        return_url: str | None = None,
        cancel_url: str | None = None,
    ) -> PayPalOrderCreationResult:
        order_id = f"PAYPAL-ORDER-{uuid4().hex[:8].upper()}"
        return PayPalOrderCreationResult(
            paypal_order_id=order_id,
            status="CREATED",
            approval_url=f"https://sandbox.paypal.com/checkout?token={order_id}",
            raw_response={"id": order_id, "status": "CREATED"},
        )

    async def capture_order(
        self,
        *,
        paypal_order_id: str,
        expected_amount_minor: int,
        expected_currency: str,
        request_id: str,
    ) -> PayPalCaptureResult:
        if self.mode == "timeout":
            raise PayPalTimeoutError("Sandbox PayPal capture timed out")
        capture_id = f"PAYPAL-CAP-{uuid4().hex[:8].upper()}"
        verified = VerifiedPayPalCapture(
            paypal_order_id=paypal_order_id,
            paypal_capture_id=capture_id,
            paypal_status="COMPLETED",
            verified_amount_minor=expected_amount_minor,
            verified_currency=expected_currency,
            verification_hash=compute_payload_hash({
                "order_id": paypal_order_id,
                "capture_id": capture_id,
                "status": "COMPLETED",
                "amount": expected_amount_minor,
            }),
            verified_at=datetime.now(UTC),
        )
        return PayPalCaptureResult(verified_capture=verified, raw_response={"id": capture_id, "status": "COMPLETED"})

    async def reconcile_order(
        self,
        *,
        paypal_order_id: str,
        expected_amount_minor: int,
        expected_currency: str,
    ) -> PayPalReconciliationResult:
        capture_id = f"PAYPAL-CAP-REC-{uuid4().hex[:8].upper()}"
        verified = VerifiedPayPalCapture(
            paypal_order_id=paypal_order_id,
            paypal_capture_id=capture_id,
            paypal_status="COMPLETED",
            verified_amount_minor=expected_amount_minor,
            verified_currency=expected_currency,
            verification_hash=compute_payload_hash({"order_id": paypal_order_id, "status": "COMPLETED"}),
            verified_at=datetime.now(UTC),
        )
        return PayPalReconciliationResult(
            paypal_order_id=paypal_order_id,
            order_status="COMPLETED",
            verified_capture=verified,
            raw_response={"status": "COMPLETED"},
        )


@pytest.fixture
def repo() -> InMemoryLedgerRepository:
    r = InMemoryLedgerRepository()
    base = build_base_entities()
    r.upsert_tenant(base["tenant"])
    r.create_agent(base["agent"])
    r.create_merchant(base["approved_merchant"])
    r.create_merchant(base["unknown_merchant"])
    r.create_passport(base["passport"])
    return r


@pytest.fixture
def paypal_client() -> MockPayPalClient:
    return MockPayPalClient(mode="success")


@pytest.fixture
def guardian_service(repo: InMemoryLedgerRepository, paypal_client: MockPayPalClient) -> GuardianService:
    return GuardianService(repo=repo, paypal_client=paypal_client)

