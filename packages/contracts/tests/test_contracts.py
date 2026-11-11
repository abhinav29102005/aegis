"""Contract tests covering state machine, hashing, stage separation, and fixtures."""

from datetime import timedelta
import pytest

from contracts import (
    DecisionOutcome,
    PaymentState,
    assert_payment_transition,
    can_transition_payment,
    compute_quote_hash,
)
from contracts.fixtures import (
    build_authorized_39_purchase_fixture,
    build_synthetic_dispute_fixture,
)


def test_payment_state_machine_transitions() -> None:
    assert can_transition_payment(PaymentState.CREATED, PaymentState.POLICY_CHECK)
    assert can_transition_payment(PaymentState.POLICY_CHECK, PaymentState.AWAITING_APPROVAL)
    assert can_transition_payment(PaymentState.CAPTURE_PENDING, PaymentState.PENDING_PROVIDER)
    assert can_transition_payment(PaymentState.PENDING_PROVIDER, PaymentState.SUCCEEDED)

    # Cannot jump directly from CREATED or POLICY_CHECK to SUCCEEDED
    assert not can_transition_payment(PaymentState.CREATED, PaymentState.SUCCEEDED)
    assert not can_transition_payment(PaymentState.POLICY_CHECK, PaymentState.SUCCEEDED)
    assert not can_transition_payment(PaymentState.AWAITING_PAYPAL_BUYER, PaymentState.SUCCEEDED)

    with pytest.raises(ValueError, match="Illegal payment state transition"):
        assert_payment_transition(PaymentState.CREATED, PaymentState.SUCCEEDED)


def test_quote_hash_detects_merchant_or_amount_tampering() -> None:
    fx = build_authorized_39_purchase_fixture()
    quote = fx["quote_snapshot"]
    tampered_amount = compute_quote_hash(
        merchant_id=quote.merchant_id,
        amount_minor=quote.amount_minor + 100,
        currency=quote.currency,
        line_items=quote.line_items,
    )
    tampered_merchant = compute_quote_hash(
        merchant_id=fx["unknown_merchant"].id,
        amount_minor=quote.amount_minor,
        currency=quote.currency,
        line_items=quote.line_items,
    )
    assert tampered_amount != quote.quote_hash
    assert tampered_merchant != quote.quote_hash


def test_authorized_and_synthetic_dispute_fixtures_validate() -> None:
    demo_a = build_authorized_39_purchase_fixture()
    assert demo_a["decision"].outcome == DecisionOutcome.ALLOW
    assert demo_a["payment_intent"].state == PaymentState.SUCCEEDED
    assert demo_a["attempt"].buyer_approval is not None
    assert demo_a["attempt"].verified_capture is not None
    assert demo_a["events"][-1].previous_event_hash == demo_a["events"][-2].event_hash

    demo_c = build_synthetic_dispute_fixture()
    assert demo_c["dispute_case"].is_synthetic is True
    assert len(demo_c["all_evidence"]) == 4
