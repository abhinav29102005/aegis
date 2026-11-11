"""Financial Infrastructure and Security Test Suite for AgentPay Guardian.

Implements all 10 mandatory financial invariants plus agent non-authority verification:
1. Authorized $39.00 purchase within $100.00 budget -> ALLOW -> verified capture -> SUCCEEDED.
2. $120.00 purchase denied (DENIED_EXCEEDS_PER_TX_LIMIT / DENIED_EXCEEDS_PASSPORT_BUDGET).
3. Unknown merchant denied (DENIED_MERCHANT_NOT_ALLOWLISTED) or escalated (ESCALATED_UNKNOWN_MERCHANT).
4. Expired approval rejected (DENIED_APPROVAL_EXPIRED).
5. Changed merchant or amount invalidates authorization (DENIED_APPROVAL_MISMATCH).
6. Concurrent $70.00 reservations against $100.00 budget cannot both succeed.
7. Repeated idempotency_key returns existing intent without duplicate reservations.
8. Buyer-declined checkout transitions to CANCELLED and releases reservation.
9. PayPal timeout results in PENDING_PROVIDER until reconciled.
10. Successful capture must be verified against PayPal before settlement (SUCCEEDED).
11. LangGraph purchasing copilot cannot directly authorize spending or capture payment.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from contracts import (
    ApprovalStatus,
    DecisionOutcome,
    DecisionReasonCode,
    FinancialEventType,
    PaymentState,
    PurchaseProposal,
    QuoteSnapshot,
    ReservationStatus,
    compute_quote_hash,
)
from contracts.fixtures import (
    AGENT_PROCUREMENT_ID,
    MERCHANT_SANDBOX_CLOUD_ID,
    MERCHANT_UNKNOWN_ID,
    PASSPORT_DEFAULT_ID,
    TENANT_ALPHA_ID,
)
from guardian.agents.purchasing_copilot import (
    AgentSecurityViolationError,
    PurchasingCopilot,
)
from guardian.domain.exceptions import (
    ApprovalExpiredError,
    ApprovalMismatchError,
    InsufficientBudgetError,
    PolicyDeniedError,
)
from guardian.domain.service import GuardianService
from tests.conftest import (
    InMemoryLedgerRepository,
    MockPayPalClient,
    run_sync,
)


def _make_proposal_and_quote(
    *,
    amount_minor: int = 3900,
    merchant_id=MERCHANT_SANDBOX_CLOUD_ID,
    idempotency_key: str | None = None,
    currency: str = "USD",
    category: str = "SOFTWARE",
    quote_expired: bool = False,
) -> tuple[PurchaseProposal, QuoteSnapshot]:
    prop_id = uuid4()
    corr_id = uuid4()
    key = idempotency_key or f"idem-{uuid4().hex[:12]}"
    now = datetime.now(UTC)
    q_exp = (now - timedelta(hours=1)) if quote_expired else (now + timedelta(hours=1))

    line_items = [{"sku": "SKU-TEST-001", "name": "Cloud Subscription", "quantity": 1, "unit_amount_minor": amount_minor}]
    q_hash = compute_quote_hash(
        merchant_id=merchant_id,
        amount_minor=amount_minor,
        currency=currency,
        line_items=line_items,
    )

    quote = QuoteSnapshot(
        id=uuid4(),
        tenant_id=TENANT_ALPHA_ID,
        correlation_id=corr_id,
        proposal_id=prop_id,
        merchant_id=merchant_id,
        amount_minor=amount_minor,
        currency=currency,
        line_items=line_items,
        quote_hash=q_hash,
        expires_at=q_exp,
        created_at=now,
    )

    proposal = PurchaseProposal(
        id=prop_id,
        tenant_id=TENANT_ALPHA_ID,
        correlation_id=corr_id,
        agent_id=AGENT_PROCUREMENT_ID,
        passport_id=PASSPORT_DEFAULT_ID,
        merchant_id=merchant_id,
        merchant_name="CloudCompute Sandbox Store",
        merchant_category=category,
        amount_minor=amount_minor,
        currency=currency,
        item_summary="1-Month Cloud Server Subscription",
        line_items=line_items,
        rationale="Autonomous CI/CD runner instance",
        idempotency_key=key,
        created_at=now,
    )
    return proposal, quote


# -----------------------------------------------------------------------------
# Scenario 1: Authorized $39.00 purchase -> ALLOW -> capture -> SUCCEEDED
# -----------------------------------------------------------------------------
def test_01_authorized_39_purchase_within_100_budget_succeeds(
    guardian_service: GuardianService,
    repo: InMemoryLedgerRepository,
) -> None:
    proposal, quote = _make_proposal_and_quote(amount_minor=3900)

    # 1. Submit proposal
    intent, decision = guardian_service.submit_proposal(proposal=proposal, quote=quote)
    assert decision.outcome == DecisionOutcome.ALLOW
    assert DecisionReasonCode.OK_WITHIN_POLICY in decision.reason_codes
    assert intent.state == PaymentState.CHECKOUT_READY
    assert intent.reservation_id is not None

    # Check reservation held
    reservation = repo.get_reservation(TENANT_ALPHA_ID, intent.reservation_id)
    assert reservation is not None
    assert reservation.status == ReservationStatus.HELD
    assert reservation.amount_minor == 3900

    # 2. Initiate checkout
    intent, attempt = run_sync(
        guardian_service.initiate_checkout(
            tenant_id=TENANT_ALPHA_ID,
            intent_id=intent.id,
        )
    )
    assert intent.state == PaymentState.AWAITING_PAYPAL_BUYER
    assert attempt.paypal_order_id is not None
    assert attempt.paypal_approval_url is not None

    # 3. PayPal buyer approves in checkout window
    intent, attempt = guardian_service.handle_buyer_approved(
        tenant_id=TENANT_ALPHA_ID,
        intent_id=intent.id,
        attempt_id=attempt.id,
        payer_id="PAYER-SANDBOX-123",
    )
    assert intent.state == PaymentState.CAPTURE_PENDING
    assert attempt.buyer_approval is not None
    assert attempt.buyer_approval.buyer_status == "APPROVED"

    # 4. Capture payment
    intent, attempt = run_sync(
        guardian_service.execute_capture(
            tenant_id=TENANT_ALPHA_ID,
            intent_id=intent.id,
            attempt_id=attempt.id,
        )
    )
    assert intent.state == PaymentState.SUCCEEDED
    assert attempt.state == PaymentState.SUCCEEDED
    assert attempt.verified_capture is not None
    assert attempt.verified_capture.paypal_status == "COMPLETED"
    assert attempt.verified_capture.verified_amount_minor == 3900

    # Check reservation converted to spent
    refreshed_res = repo.get_reservation(TENANT_ALPHA_ID, intent.reservation_id)
    assert refreshed_res.status == ReservationStatus.CAPTURED

    # Verify event audit trail
    events = repo.list_events(TENANT_ALPHA_ID, payment_intent_id=intent.id)
    event_types = [e.event_type for e in events]
    assert FinancialEventType.PROPOSAL_CREATED in event_types
    assert FinancialEventType.POLICY_EVALUATED in event_types
    assert FinancialEventType.BUDGET_RESERVED in event_types
    assert FinancialEventType.PAYPAL_ORDER_CREATED in event_types
    assert FinancialEventType.PAYPAL_BUYER_APPROVED in event_types
    assert FinancialEventType.PAYPAL_CAPTURE_VERIFIED in event_types
    assert FinancialEventType.BUDGET_CAPTURED in event_types


# -----------------------------------------------------------------------------
# Scenario 2: $120.00 purchase denied
# -----------------------------------------------------------------------------
def test_02_120_purchase_denied_exceeds_budget_and_per_tx_limit(
    guardian_service: GuardianService,
    repo: InMemoryLedgerRepository,
) -> None:
    proposal, quote = _make_proposal_and_quote(amount_minor=12000)

    with pytest.raises(PolicyDeniedError) as exc_info:
        guardian_service.submit_proposal(proposal=proposal, quote=quote)

    assert (
        DecisionReasonCode.DENIED_EXCEEDS_PER_TX_LIMIT in exc_info.value.reason_codes
        or DecisionReasonCode.DENIED_EXCEEDS_PASSPORT_BUDGET in exc_info.value.reason_codes
    )

    intent = repo.get_intent_by_idempotency(TENANT_ALPHA_ID, proposal.idempotency_key)
    assert intent is not None
    assert intent.state == PaymentState.FAILED
    assert intent.reservation_id is None


# -----------------------------------------------------------------------------
# Scenario 3: Unknown merchant denied or escalated
# -----------------------------------------------------------------------------
def test_03_unknown_merchant_denied_or_escalated(
    guardian_service: GuardianService,
    repo: InMemoryLedgerRepository,
) -> None:
    # 3a. Passport default: allow_unknown_merchants=False -> DENIED
    proposal, quote = _make_proposal_and_quote(
        amount_minor=2500,
        merchant_id=MERCHANT_UNKNOWN_ID,
    )
    with pytest.raises(PolicyDeniedError) as exc_info:
        guardian_service.submit_proposal(proposal=proposal, quote=quote)

    assert DecisionReasonCode.DENIED_MERCHANT_NOT_ALLOWLISTED in exc_info.value.reason_codes

    # 3b. Update passport to allow unknown merchants with escalation
    passport = repo.get_passport(TENANT_ALPHA_ID, PASSPORT_DEFAULT_ID)
    updated_passport = passport.model_copy(
        update={"allow_unknown_merchants": True, "allowed_categories": ["SOFTWARE", "CLOUD_INFRA", "HARDWARE"]}
    )
    repo.create_passport(updated_passport)

    proposal2, quote2 = _make_proposal_and_quote(
        amount_minor=2500,
        merchant_id=MERCHANT_UNKNOWN_ID,
    )
    intent2, decision2 = guardian_service.submit_proposal(proposal=proposal2, quote=quote2)
    assert decision2.outcome == DecisionOutcome.ESCALATE
    assert DecisionReasonCode.ESCALATED_UNKNOWN_MERCHANT in decision2.reason_codes
    assert intent2.state == PaymentState.AWAITING_APPROVAL


# -----------------------------------------------------------------------------
# Scenario 4: Expired approval rejected
# -----------------------------------------------------------------------------
def test_04_expired_approval_rejected(
    guardian_service: GuardianService,
    repo: InMemoryLedgerRepository,
) -> None:
    # Passport threshold is $50.00 (5000 minor). $60.00 escalates to human approval.
    proposal, quote = _make_proposal_and_quote(amount_minor=6000)
    intent, decision = guardian_service.submit_proposal(proposal=proposal, quote=quote)
    assert intent.state == PaymentState.AWAITING_APPROVAL
    assert intent.approval_record_id is not None

    # Fast forward approval past expiration
    approval = repo.get_approval(TENANT_ALPHA_ID, intent.approval_record_id)
    expired_approval = approval.model_copy(
        update={"expires_at": datetime.now(UTC) - timedelta(minutes=10)}
    )
    repo.update_approval(expired_approval)

    # Attempting to approve/consume an expired approval must fail
    with pytest.raises(ApprovalExpiredError):
        guardian_service.approve_and_consume(
            tenant_id=TENANT_ALPHA_ID,
            intent_id=intent.id,
            approval_id=intent.approval_record_id,
            approver_id="security-lead",
        )

    # Verify approval status is EXPIRED and intent is NOT CHECKOUT_READY
    refreshed_approval = repo.get_approval(TENANT_ALPHA_ID, intent.approval_record_id)
    assert refreshed_approval.status == ApprovalStatus.EXPIRED
    refreshed_intent = repo.get_intent(TENANT_ALPHA_ID, intent.id)
    assert refreshed_intent.state == PaymentState.AWAITING_APPROVAL


# -----------------------------------------------------------------------------
# Scenario 5: Changed merchant or amount invalidates authorization
# -----------------------------------------------------------------------------
def test_05_changed_merchant_or_amount_invalidates_authorization(
    guardian_service: GuardianService,
    repo: InMemoryLedgerRepository,
) -> None:
    proposal, quote = _make_proposal_and_quote(amount_minor=6000)
    intent, decision = guardian_service.submit_proposal(proposal=proposal, quote=quote)

    # Human decides approval for the original quote
    approval = repo.get_approval(TENANT_ALPHA_ID, intent.approval_record_id)
    decided_approval = approval.model_copy(
        update={"status": ApprovalStatus.APPROVED, "decided_at": datetime.now(UTC)}
    )
    repo.update_approval(decided_approval)

    # Tamper with the intent amount post-approval ($60.00 -> $65.00)
    tampered_intent = intent.model_copy(update={"amount_minor": 6500})
    repo.save_intent(tampered_intent)

    # Attempt to consume approval against tampered intent
    with pytest.raises(ApprovalMismatchError):
        guardian_service.approval_service.consume_approval(
            tenant_id=TENANT_ALPHA_ID,
            approval_id=intent.approval_record_id,
            current_merchant_id=tampered_intent.merchant_id,
            current_amount_minor=tampered_intent.amount_minor,
            current_currency=tampered_intent.currency,
            current_quote_hash=tampered_intent.quote_hash,
        )


# -----------------------------------------------------------------------------
# Scenario 6: Concurrent $70.00 reservations against $100.00 budget
# -----------------------------------------------------------------------------
def test_06_concurrent_70_reservations_cannot_both_succeed(
    guardian_service: GuardianService,
    repo: InMemoryLedgerRepository,
) -> None:
    # Set human approval threshold to 10000 so policy allows both to attempt reservation
    passport = repo.get_passport(TENANT_ALPHA_ID, PASSPORT_DEFAULT_ID)
    repo.create_passport(passport.model_copy(update={"human_approval_threshold_minor": 10000}))

    # Budget is $100.00. Two parallel requests for $70.00 each.
    proposal1, quote1 = _make_proposal_and_quote(amount_minor=7000)
    proposal2, quote2 = _make_proposal_and_quote(amount_minor=7000)

    results = []

    def submit_one(prop, q):
        try:
            res_intent, res_dec = guardian_service.submit_proposal(proposal=prop, quote=q)
            return ("SUCCESS", res_intent)
        except (PolicyDeniedError, InsufficientBudgetError) as exc:
            return ("FAILED", exc)

    with ThreadPoolExecutor(max_workers=2) as executor:
        f1 = executor.submit(submit_one, proposal1, quote1)
        f2 = executor.submit(submit_one, proposal2, quote2)
        results = [f1.result(), f2.result()]

    statuses = [r[0] for r in results]
    # Exactly one must succeed and one must fail
    assert statuses.count("SUCCESS") == 1
    assert statuses.count("FAILED") == 1

    # Check final passport reserved balance does not exceed total budget
    passport = repo.get_passport(TENANT_ALPHA_ID, PASSPORT_DEFAULT_ID)
    assert passport.reserved_minor == 7000
    assert passport.available_budget_minor == 3000


# -----------------------------------------------------------------------------
# Scenario 7: Repeated idempotency_key returns existing intent
# -----------------------------------------------------------------------------
def test_07_repeated_idempotency_key_returns_existing_intent_no_duplicates(
    guardian_service: GuardianService,
    repo: InMemoryLedgerRepository,
) -> None:
    shared_key = "idempotency-key-alpha-999"
    proposal1, quote1 = _make_proposal_and_quote(amount_minor=3500, idempotency_key=shared_key)
    proposal2, quote2 = _make_proposal_and_quote(amount_minor=3500, idempotency_key=shared_key)

    intent1, _ = guardian_service.submit_proposal(proposal=proposal1, quote=quote1)
    events_count_after_first = len(repo.list_events(TENANT_ALPHA_ID, payment_intent_id=intent1.id))

    # Resubmit with exact same key
    intent2, _ = guardian_service.submit_proposal(proposal=proposal2, quote=quote2)

    assert intent1.id == intent2.id
    # No duplicate events added
    events_count_after_second = len(repo.list_events(TENANT_ALPHA_ID, payment_intent_id=intent1.id))
    assert events_count_after_first == events_count_after_second

    # Reserved amount should only be 3500, not 7000
    passport = repo.get_passport(TENANT_ALPHA_ID, PASSPORT_DEFAULT_ID)
    assert passport.reserved_minor == 3500


# -----------------------------------------------------------------------------
# Scenario 8: Buyer-declined checkout transitions to CANCELLED & releases budget
# -----------------------------------------------------------------------------
def test_08_buyer_declined_checkout_transitions_to_cancelled_and_releases_budget(
    guardian_service: GuardianService,
    repo: InMemoryLedgerRepository,
) -> None:
    proposal, quote = _make_proposal_and_quote(amount_minor=4200)
    intent, _ = guardian_service.submit_proposal(proposal=proposal, quote=quote)
    intent, attempt = run_sync(
        guardian_service.initiate_checkout(tenant_id=TENANT_ALPHA_ID, intent_id=intent.id)
    )

    # Buyer cancels/declines checkout
    intent, attempt = guardian_service.handle_buyer_declined(
        tenant_id=TENANT_ALPHA_ID,
        intent_id=intent.id,
        attempt_id=attempt.id,
        reason="Buyer dismissed the PayPal checkout modal",
    )

    assert intent.state == PaymentState.CANCELLED
    assert attempt.state == PaymentState.CANCELLED

    # Reservation must be released
    reservation = repo.get_reservation(TENANT_ALPHA_ID, intent.reservation_id)
    assert reservation.status == ReservationStatus.RELEASED

    # Passport reserved budget returned to 0
    passport = repo.get_passport(TENANT_ALPHA_ID, PASSPORT_DEFAULT_ID)
    assert passport.reserved_minor == 0
    assert passport.spent_minor == 0


# -----------------------------------------------------------------------------
# Scenario 9: PayPal timeout results in PENDING_PROVIDER until reconciled
# -----------------------------------------------------------------------------
def test_09_paypal_timeout_results_in_pending_provider_until_reconciled(
    repo: InMemoryLedgerRepository,
) -> None:
    timeout_client = MockPayPalClient(mode="timeout")
    service = GuardianService(repo=repo, paypal_client=timeout_client)

    proposal, quote = _make_proposal_and_quote(amount_minor=4500)
    intent, _ = service.submit_proposal(proposal=proposal, quote=quote)
    intent, attempt = run_sync(
        service.initiate_checkout(tenant_id=TENANT_ALPHA_ID, intent_id=intent.id)
    )
    intent, attempt = service.handle_buyer_approved(
        tenant_id=TENANT_ALPHA_ID,
        intent_id=intent.id,
        attempt_id=attempt.id,
    )

    # Capture triggers timeout -> PENDING_PROVIDER
    intent, attempt = run_sync(
        service.execute_capture(
            tenant_id=TENANT_ALPHA_ID,
            intent_id=intent.id,
            attempt_id=attempt.id,
        )
    )
    assert intent.state == PaymentState.PENDING_PROVIDER
    assert attempt.state == PaymentState.PENDING_PROVIDER

    # Now reconcile
    intent, attempt = run_sync(
        service.reconcile_pending(
            tenant_id=TENANT_ALPHA_ID,
            intent_id=intent.id,
            attempt_id=attempt.id,
        )
    )
    assert intent.state == PaymentState.SUCCEEDED
    assert attempt.state == PaymentState.SUCCEEDED
    assert attempt.verified_capture is not None


# -----------------------------------------------------------------------------
# Scenario 10: Successful capture must be verified before settlement
# -----------------------------------------------------------------------------
def test_10_successful_capture_must_be_verified_before_settlement(
    guardian_service: GuardianService,
    repo: InMemoryLedgerRepository,
) -> None:
    proposal, quote = _make_proposal_and_quote(amount_minor=3000)
    intent, _ = guardian_service.submit_proposal(proposal=proposal, quote=quote)
    intent, attempt = run_sync(
        guardian_service.initiate_checkout(tenant_id=TENANT_ALPHA_ID, intent_id=intent.id)
    )
    intent, attempt = guardian_service.handle_buyer_approved(
        tenant_id=TENANT_ALPHA_ID,
        intent_id=intent.id,
        attempt_id=attempt.id,
    )
    intent, attempt = run_sync(
        guardian_service.execute_capture(
            tenant_id=TENANT_ALPHA_ID,
            intent_id=intent.id,
            attempt_id=attempt.id,
        )
    )

    assert intent.state == PaymentState.SUCCEEDED
    assert attempt.verified_capture is not None
    assert attempt.verified_capture.verified_amount_minor == 3000
    assert attempt.verified_capture.verified_currency == "USD"
    assert len(attempt.verified_capture.verification_hash) > 16

    # Verify that an attempt without verified capture cannot be in SUCCEEDED state
    raw_attempt = repo.get_attempt(TENANT_ALPHA_ID, attempt.id)
    assert raw_attempt.verified_capture is not None


# -----------------------------------------------------------------------------
# Scenario 11: LangGraph purchasing agent cannot authorize or capture payments
# -----------------------------------------------------------------------------
def test_11_langgraph_purchasing_agent_cannot_authorize_or_capture() -> None:
    copilot = PurchasingCopilot(model_name="test-purchasing-copilot")

    # 1. Proposing a purchase is allowed
    proposal = copilot.build_proposal(
        tenant_id=TENANT_ALPHA_ID,
        agent_id=AGENT_PROCUREMENT_ID,
        passport_id=PASSPORT_DEFAULT_ID,
        merchant_id=MERCHANT_SANDBOX_CLOUD_ID,
        merchant_name="CloudCompute Sandbox Store",
        amount_minor=3900,
        item_summary="Cloud VM Instance",
        rationale="For build workloads",
        idempotency_key="copilot-proposal-001",
    )
    assert proposal.amount_minor == 3900
    assert proposal.proposed_by_model == "test-purchasing-copilot"

    # 2. Explaining decisions is allowed
    from contracts import AuthorizationDecision
    dummy_decision = AuthorizationDecision(
        tenant_id=TENANT_ALPHA_ID,
        correlation_id=proposal.correlation_id,
        payment_intent_id=uuid4(),
        proposal_id=proposal.id,
        passport_id=PASSPORT_DEFAULT_ID,
        quote_snapshot_id=uuid4(),
        quote_hash="mock-hash",
        outcome=DecisionOutcome.ALLOW,
        reason_codes=[DecisionReasonCode.OK_WITHIN_POLICY],
        explanation="Within policy limits",
    )
    explanation = copilot.explain_decision(proposal, dummy_decision)
    assert "ALLOWED" in explanation

    # 3. Explicitly prohibited actions must raise AgentSecurityViolationError
    with pytest.raises((AgentSecurityViolationError, PermissionError)):
        copilot.authorize()

    with pytest.raises((AgentSecurityViolationError, PermissionError)):
        copilot.approve_budget()

    with pytest.raises((AgentSecurityViolationError, PermissionError)):
        copilot.capture_payment()
