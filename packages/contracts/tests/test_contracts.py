"""Contract tests covering state machines, hashing, ISO 4217, policy-v1, and fixtures."""

from datetime import timedelta
from uuid import uuid4

import pytest
from contracts import (
    AP2MandatePayload,
    DecisionOutcome,
    DecisionReasonCode,
    DeflectionAlert,
    DisputeStatus,
    PassportStatus,
    PaymentProviderAdapter,
    PaymentState,
    QuoteSnapshot,
    StripeEventEnvelope,
    TAPTokenPayload,
    X402SettlementProof,
    assert_dispute_transition,
    assert_payment_transition,
    can_transition_dispute,
    can_transition_payment,
    compute_quote_hash,
    decimal_str_to_minor,
    evaluate_policy_v1,
    get_currency_exponent,
    minor_to_decimal_str,
)
from contracts.export_schemas import MODELS, export_all_schemas
from contracts.fixtures import (
    BASE_TIME,
    build_authorized_39_purchase_fixture,
    build_base_entities,
    build_synthetic_dispute_fixture,
)


def test_payment_state_machine_transitions() -> None:
    assert can_transition_payment(PaymentState.CREATED, PaymentState.POLICY_CHECK)
    assert can_transition_payment(PaymentState.POLICY_CHECK, PaymentState.AWAITING_APPROVAL)
    assert can_transition_payment(PaymentState.CAPTURE_PENDING, PaymentState.PENDING_PROVIDER)
    assert can_transition_payment(PaymentState.PENDING_PROVIDER, PaymentState.SUCCEEDED)

    # Refund and expiry transitions
    assert can_transition_payment(PaymentState.SUCCEEDED, PaymentState.REFUNDED)
    assert can_transition_payment(PaymentState.SUCCEEDED, PaymentState.PARTIALLY_REFUNDED)
    assert can_transition_payment(PaymentState.PARTIALLY_REFUNDED, PaymentState.REFUNDED)
    assert not can_transition_payment(PaymentState.PARTIALLY_REFUNDED, PaymentState.SUCCEEDED)
    assert not can_transition_payment(PaymentState.REFUNDED, PaymentState.PARTIALLY_REFUNDED)

    assert can_transition_payment(PaymentState.AWAITING_APPROVAL, PaymentState.EXPIRED)
    assert can_transition_payment(PaymentState.CHECKOUT_READY, PaymentState.EXPIRED)
    assert can_transition_payment(PaymentState.AWAITING_PAYPAL_BUYER, PaymentState.EXPIRED)
    assert not can_transition_payment(PaymentState.EXPIRED, PaymentState.SUCCEEDED)

    # Cannot jump directly from CREATED or POLICY_CHECK to SUCCEEDED
    assert not can_transition_payment(PaymentState.CREATED, PaymentState.SUCCEEDED)
    assert not can_transition_payment(PaymentState.POLICY_CHECK, PaymentState.SUCCEEDED)
    assert not can_transition_payment(PaymentState.AWAITING_PAYPAL_BUYER, PaymentState.SUCCEEDED)

    with pytest.raises(ValueError, match="Illegal payment state transition"):
        assert_payment_transition(PaymentState.CREATED, PaymentState.SUCCEEDED)


def test_dispute_status_monotonic_transitions() -> None:
    assert can_transition_dispute(DisputeStatus.OPEN, DisputeStatus.UNDER_INVESTIGATION)
    assert can_transition_dispute(DisputeStatus.OPEN, DisputeStatus.DRAFT_READY)
    assert can_transition_dispute(DisputeStatus.UNDER_INVESTIGATION, DisputeStatus.DRAFT_READY)
    assert can_transition_dispute(DisputeStatus.DRAFT_READY, DisputeStatus.APPROVED_FOR_SUBMISSION)
    assert can_transition_dispute(DisputeStatus.APPROVED_FOR_SUBMISSION, DisputeStatus.SUBMITTED)
    assert can_transition_dispute(DisputeStatus.SUBMITTED, DisputeStatus.RESOLVED)

    # Disallow backward or self-transitions
    assert not can_transition_dispute(DisputeStatus.DRAFT_READY, DisputeStatus.OPEN)
    assert not can_transition_dispute(DisputeStatus.SUBMITTED, DisputeStatus.APPROVED_FOR_SUBMISSION)
    assert not can_transition_dispute(DisputeStatus.RESOLVED, DisputeStatus.OPEN)
    assert not can_transition_dispute(DisputeStatus.OPEN, DisputeStatus.OPEN)

    with pytest.raises(ValueError, match="Illegal dispute status transition"):
        assert_dispute_transition(DisputeStatus.SUBMITTED, DisputeStatus.DRAFT_READY)


def test_quote_hash_verification_rejects_tampering() -> None:
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

    with pytest.raises(ValueError, match="quote_hash mismatch"):
        QuoteSnapshot(
            tenant_id=quote.tenant_id,
            correlation_id=quote.correlation_id,
            proposal_id=quote.proposal_id,
            merchant_id=quote.merchant_id,
            amount_minor=quote.amount_minor,
            currency=quote.currency,
            line_items=quote.line_items,
            quote_hash="0" * 64,
            expires_at=quote.expires_at,
        )

    # Empty quote_hash auto-populates deterministically
    auto_quote = QuoteSnapshot(
        tenant_id=quote.tenant_id,
        correlation_id=quote.correlation_id,
        proposal_id=quote.proposal_id,
        merchant_id=quote.merchant_id,
        amount_minor=quote.amount_minor,
        currency=quote.currency,
        line_items=quote.line_items,
        expires_at=quote.expires_at,
    )
    assert auto_quote.quote_hash == quote.quote_hash


def test_iso4217_currency_exponent_helpers() -> None:
    assert get_currency_exponent("JPY") == 0
    assert get_currency_exponent("kwd") == 3
    assert get_currency_exponent("USD") == 2

    assert minor_to_decimal_str(1500, "JPY") == "1500"
    assert minor_to_decimal_str(1500, "KWD") == "1.500"
    assert minor_to_decimal_str(3900, "USD") == "39.00"

    assert decimal_str_to_minor("1500", "JPY") == 1500
    assert decimal_str_to_minor("1.500", "KWD") == 1500
    assert decimal_str_to_minor("39.00", "USD") == 3900

    with pytest.raises(ValueError, match="exceeds 0 decimal places"):
        decimal_str_to_minor("10.5", "JPY")


def test_evaluate_policy_v1_comprehensive() -> None:
    fx = build_authorized_39_purchase_fixture()
    proposal = fx["proposal"]
    passport = fx["passport"]
    merchant = fx["approved_merchant"]
    quote = fx["quote_snapshot"]
    agent = fx["agent"]
    eval_now = BASE_TIME + timedelta(minutes=2)

    # 1. Valid baseline -> ALLOW
    allow_dec = evaluate_policy_v1(
        proposal=proposal,
        passport=passport,
        merchant=merchant,
        quote=quote,
        agent=agent,
        now=eval_now,
    )
    assert allow_dec.outcome == DecisionOutcome.ALLOW
    assert allow_dec.reason_codes == [DecisionReasonCode.OK_WITHIN_POLICY]
    assert allow_dec.policy_inputs["merchant_allowlisted"] is True

    # 2. Unsupported policy version
    with pytest.raises(ValueError, match="Unsupported policy_version"):
        evaluate_policy_v1(
            proposal=proposal,
            passport=passport,
            merchant=merchant,
            policy_version="policy-v99",
            now=eval_now,
        )

    # 3. Cross-tenant mismatch
    other_tenant = uuid4()
    cross_dec = evaluate_policy_v1(
        proposal=proposal,
        passport=passport.model_copy(update={"tenant_id": other_tenant}),
        merchant=merchant,
        now=eval_now,
    )
    assert cross_dec.outcome == DecisionOutcome.DENY
    assert DecisionReasonCode.DENIED_CROSS_TENANT in cross_dec.reason_codes

    # 4. Suspended agent
    susp_dec = evaluate_policy_v1(
        proposal=proposal,
        passport=passport,
        merchant=merchant,
        agent=agent.model_copy(update={"status": "SUSPENDED"}),
        now=eval_now,
    )
    assert susp_dec.outcome == DecisionOutcome.DENY
    assert DecisionReasonCode.DENIED_AGENT_SUSPENDED in susp_dec.reason_codes

    # 5. Passport paused / revoked / expired
    paused_dec = evaluate_policy_v1(
        proposal=proposal,
        passport=passport.model_copy(update={"status": PassportStatus.PAUSED}),
        merchant=merchant,
        now=eval_now,
    )
    assert DecisionReasonCode.DENIED_PASSPORT_PAUSED in paused_dec.reason_codes

    revoked_dec = evaluate_policy_v1(
        proposal=proposal,
        passport=passport.model_copy(update={"status": PassportStatus.REVOKED}),
        merchant=merchant,
        now=eval_now,
    )
    assert DecisionReasonCode.DENIED_PASSPORT_REVOKED in revoked_dec.reason_codes

    expired_dec = evaluate_policy_v1(
        proposal=proposal,
        passport=passport,
        merchant=merchant,
        now=passport.expires_at,
    )
    assert DecisionReasonCode.DENIED_PASSPORT_EXPIRED in expired_dec.reason_codes

    # 6. Quote expired & mismatch
    quote_exp_dec = evaluate_policy_v1(
        proposal=proposal,
        passport=passport,
        merchant=merchant,
        quote=quote,
        now=quote.expires_at,
    )
    assert DecisionReasonCode.DENIED_QUOTE_EXPIRED in quote_exp_dec.reason_codes

    bad_quote = QuoteSnapshot(
        tenant_id=quote.tenant_id,
        correlation_id=quote.correlation_id,
        proposal_id=quote.proposal_id,
        merchant_id=quote.merchant_id,
        amount_minor=quote.amount_minor + 50,
        currency=quote.currency,
        expires_at=quote.expires_at,
    )
    mismatch_dec = evaluate_policy_v1(
        proposal=proposal,
        passport=passport,
        merchant=merchant,
        quote=bad_quote,
        now=eval_now,
    )
    assert DecisionReasonCode.DENIED_APPROVAL_MISMATCH in mismatch_dec.reason_codes

    # 7. Currency check
    eur_prop = proposal.model_copy(update={"currency": "EUR"})
    curr_dec = evaluate_policy_v1(
        proposal=eur_prop,
        passport=passport.model_copy(update={"allowed_currencies": ["USD", "GBP"]}),
        merchant=merchant,
        now=eval_now,
    )
    assert DecisionReasonCode.DENIED_CURRENCY_NOT_ALLOWED in curr_dec.reason_codes

    # 8. Daily and monthly limits
    daily_dec = evaluate_policy_v1(
        proposal=proposal,
        passport=passport,
        merchant=merchant,
        daily_spent_minor=7000,
        now=eval_now,
    )
    assert DecisionReasonCode.DENIED_EXCEEDS_DAILY_LIMIT in daily_dec.reason_codes

    monthly_dec = evaluate_policy_v1(
        proposal=proposal,
        passport=passport.model_copy(update={"monthly_limit_minor": 5000}),
        merchant=merchant,
        monthly_spent_minor=2000,
        now=eval_now,
    )
    assert DecisionReasonCode.DENIED_MONTHLY_LIMIT in monthly_dec.reason_codes

    # 9. Strict merchant allowlist (global merchant.is_allowlisted must NOT bypass!)
    base = build_base_entities()
    non_passport_merchant = base["unknown_merchant"].model_copy(
        update={"is_allowlisted": True, "category": "SOFTWARE"}
    )
    denied_merchant_dec = evaluate_policy_v1(
        proposal=proposal.model_copy(update={"merchant_id": non_passport_merchant.id}),
        passport=passport,
        merchant=non_passport_merchant,
        now=eval_now,
    )
    assert denied_merchant_dec.outcome == DecisionOutcome.DENY
    assert DecisionReasonCode.DENIED_MERCHANT_NOT_ALLOWLISTED in denied_merchant_dec.reason_codes

    esc_merchant_dec = evaluate_policy_v1(
        proposal=proposal.model_copy(update={"merchant_id": non_passport_merchant.id}),
        passport=passport.model_copy(update={"allow_unknown_merchants": True}),
        merchant=non_passport_merchant,
        now=eval_now,
    )
    assert esc_merchant_dec.outcome == DecisionOutcome.ESCALATE
    assert DecisionReasonCode.ESCALATED_UNKNOWN_MERCHANT in esc_merchant_dec.reason_codes

    # 10. Approval threshold (strict >)
    exact_threshold = evaluate_policy_v1(
        proposal=proposal.model_copy(update={"amount_minor": 5000}),
        passport=passport,
        merchant=merchant,
        now=eval_now,
    )
    assert exact_threshold.outcome == DecisionOutcome.ALLOW

    above_threshold = evaluate_policy_v1(
        proposal=proposal.model_copy(update={"amount_minor": 5001}),
        passport=passport,
        merchant=merchant,
        now=eval_now,
    )
    assert above_threshold.outcome == DecisionOutcome.ESCALATE
    assert DecisionReasonCode.ESCALATED_REQUIRES_HUMAN_APPROVAL in above_threshold.reason_codes


def test_multirail_models_and_schema_export() -> None:
    tenant_id = uuid4()
    agent_id = uuid4()
    corr_id = uuid4()
    expires = BASE_TIME + timedelta(hours=1)

    ap2 = AP2MandatePayload(
        mandate_id="ap2-001",
        tenant_id=tenant_id,
        agent_id=agent_id,
        max_amount_minor=5000,
        currency="usd",
        scope=["purchase:software"],
        expires_at=expires,
        signature="sig-ap2-12345678",
    )
    tap = TAPTokenPayload(
        token_id="tap-001",
        tenant_id=tenant_id,
        agent_id=agent_id,
        merchant_domain="sandbox.example",
        amount_minor=3900,
        nonce="nonce-12345678",
        expires_at=expires,
        signature="sig-tap-12345678",
    )
    x402 = X402SettlementProof(
        proof_id="x402-001",
        tenant_id=tenant_id,
        network="base-sepolia",
        asset="USDC",
        amount_minor=3900,
        tx_hash="0x1234567890abcdef",
        payer_address="0xpayer123",
        payee_address="0xpayee456",
    )
    stripe_env = StripeEventEnvelope(
        event_id="evt_12345",
        tenant_id=tenant_id,
        event_type="charge.dispute.created",
        amount_minor=3900,
        currency="usd",
    )
    alert = DeflectionAlert(
        tenant_id=tenant_id,
        correlation_id=corr_id,
        alert_type="PRE_DISPUTE_RISK",
        severity="HIGH",
        reason="Tracking shows delay",
        recommended_action="Proactively notify buyer",
    )

    assert ap2.currency == "USD"
    assert tap.currency == "USD"
    assert x402.asset == "USDC"
    assert stripe_env.currency == "USD"
    assert alert.severity == "HIGH"

    schema = export_all_schemas()
    defs = schema.get("$defs", {})
    for model in MODELS:
        assert model.__name__ in defs

    assert hasattr(PaymentProviderAdapter, "create_order")
    assert hasattr(PaymentProviderAdapter, "refund_capture")


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

