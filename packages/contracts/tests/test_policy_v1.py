"""Tests for unified policy-v1 evaluator and ISO 4217 currency helpers."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from contracts.enums import (
    DecisionOutcome,
    DecisionReasonCode,
)
from contracts.export_schemas import export_all_schemas
from contracts.fixtures import (
    MERCHANT_SANDBOX_CLOUD_ID,
    TENANT_ALPHA_ID,
    build_authorized_39_purchase_fixture,
)
from contracts.hashing import compute_quote_hash
from contracts.models import (
    AgentIdentity,
    Merchant,
    QuoteSnapshot,
)
from contracts.policy_v1 import (
    evaluate_policy_v1,
    format_minor_to_major,
    get_currency_exponent,
    parse_major_to_minor,
)


def test_iso_4217_currency_exponent_and_formatting() -> None:
    # JPY exponent 0
    assert get_currency_exponent("JPY") == 0
    assert format_minor_to_major(3900, "JPY") == "3900"
    assert parse_major_to_minor("3900", "JPY") == 3900

    # KWD exponent 3
    assert get_currency_exponent("KWD") == 3
    assert format_minor_to_major(3900, "KWD") == "3.900"
    assert parse_major_to_minor("3.900", "KWD") == 3900

    # USD exponent 2
    assert get_currency_exponent("USD") == 2
    assert format_minor_to_major(3900, "USD") == "39.00"
    assert parse_major_to_minor("39.00", "USD") == 3900


def test_quote_snapshot_hash_verification() -> None:
    line_items = [{"sku": "ITEM-1", "name": "Item 1", "amount_minor": 1000, "quantity": 1}]
    valid_hash = compute_quote_hash(
        merchant_id=MERCHANT_SANDBOX_CLOUD_ID,
        amount_minor=1000,
        currency="USD",
        line_items=line_items,
    )
    # Valid explicit quote hash succeeds
    quote = QuoteSnapshot(
        tenant_id=TENANT_ALPHA_ID,
        correlation_id=uuid4(),
        proposal_id=uuid4(),
        merchant_id=MERCHANT_SANDBOX_CLOUD_ID,
        amount_minor=1000,
        currency="USD",
        line_items=line_items,
        quote_hash=valid_hash,
        expires_at=datetime.now(UTC) + timedelta(hours=1),
    )
    assert quote.quote_hash == valid_hash

    # Forged quote hash fails
    with pytest.raises(ValueError, match="Quote hash mismatch"):
        QuoteSnapshot(
            tenant_id=TENANT_ALPHA_ID,
            correlation_id=uuid4(),
            proposal_id=uuid4(),
            merchant_id=MERCHANT_SANDBOX_CLOUD_ID,
            amount_minor=1000,
            currency="USD",
            line_items=line_items,
            quote_hash="forged-hash-1234567890",
            expires_at=datetime.now(UTC) + timedelta(hours=1),
        )


def test_policy_v1_evaluation_allow() -> None:
    fixture = build_authorized_39_purchase_fixture()
    decision = evaluate_policy_v1(
        proposal=fixture["proposal"],
        passport=fixture["passport"],
        merchant=fixture["approved_merchant"],
        quote=fixture["quote_snapshot"],
    )
    assert decision.outcome == DecisionOutcome.ALLOW
    assert decision.reason_codes == [DecisionReasonCode.OK_WITHIN_POLICY]
    assert decision.requires_human_approval is False


def test_policy_v1_agent_identity_suspended_denied() -> None:
    fixture = build_authorized_39_purchase_fixture()
    agent = AgentIdentity(
        tenant_id=TENANT_ALPHA_ID,
        name="Procurement Agent",
        status="SUSPENDED",
        public_fingerprint="fingerprint-12345",
    )
    decision = evaluate_policy_v1(
        proposal=fixture["proposal"],
        passport=fixture["passport"],
        merchant=fixture["approved_merchant"],
        quote=fixture["quote_snapshot"],
        agent=agent,
    )
    assert decision.outcome == DecisionOutcome.DENY
    assert DecisionReasonCode.DENIED_AGENT_SUSPENDED in decision.reason_codes


def test_policy_v1_strict_merchant_allowlist() -> None:
    fixture = build_authorized_39_purchase_fixture()
    # Merchant with is_allowlisted=True globally, BUT not in passport.allowed_merchant_ids
    unallowlisted_merchant = Merchant(
        id=uuid4(),
        tenant_id=TENANT_ALPHA_ID,
        name="Global Merchant",
        domain="global.example.com",
        category="SOFTWARE",
        is_allowlisted=True,
    )
    decision = evaluate_policy_v1(
        proposal=fixture["proposal"],
        passport=fixture["passport"],
        merchant=unallowlisted_merchant,
        quote=fixture["quote_snapshot"],
    )
    assert decision.outcome == DecisionOutcome.DENY
    assert DecisionReasonCode.DENIED_MERCHANT_NOT_ALLOWLISTED in decision.reason_codes


def test_policy_v1_rolling_daily_limit() -> None:
    fixture = build_authorized_39_purchase_fixture()
    # Passport daily_limit_minor is 10000 ($100.00). Already spent 8000 ($80.00) today.
    # New purchase is 3900 ($39.00) -> 8000 + 3900 = 11900 > 10000 -> DENIED_EXCEEDS_DAILY_LIMIT
    decision = evaluate_policy_v1(
        proposal=fixture["proposal"],
        passport=fixture["passport"],
        merchant=fixture["approved_merchant"],
        quote=fixture["quote_snapshot"],
        historical_daily_spend_minor=8000,
    )
    assert decision.outcome == DecisionOutcome.DENY
    assert DecisionReasonCode.DENIED_EXCEEDS_DAILY_LIMIT in decision.reason_codes


def test_policy_v1_exact_threshold_operator() -> None:
    fixture = build_authorized_39_purchase_fixture()
    passport = fixture["passport"]  # threshold is 5000

    # 1. Exactly at threshold: 5000 -> ALLOW (not strictly greater than threshold)
    line_items_50 = [{"sku": "50", "name": "50", "amount_minor": 5000, "quantity": 1}]
    q_hash_50 = compute_quote_hash(
        merchant_id=fixture["approved_merchant"].id,
        amount_minor=5000,
        currency="USD",
        line_items=line_items_50,
    )
    quote_50 = QuoteSnapshot(
        tenant_id=TENANT_ALPHA_ID,
        correlation_id=uuid4(),
        proposal_id=uuid4(),
        merchant_id=fixture["approved_merchant"].id,
        amount_minor=5000,
        currency="USD",
        line_items=line_items_50,
        quote_hash=q_hash_50,
        expires_at=datetime.now(UTC) + timedelta(hours=1),
    )
    prop_50 = fixture["proposal"].model_copy(update={"amount_minor": 5000, "id": quote_50.proposal_id})
    dec_50 = evaluate_policy_v1(
        proposal=prop_50,
        passport=passport,
        merchant=fixture["approved_merchant"],
        quote=quote_50,
    )
    assert dec_50.outcome == DecisionOutcome.ALLOW

    # 2. Above threshold: 5001 -> ESCALATE
    line_items_51 = [{"sku": "51", "name": "51", "amount_minor": 5001, "quantity": 1}]
    q_hash_51 = compute_quote_hash(
        merchant_id=fixture["approved_merchant"].id,
        amount_minor=5001,
        currency="USD",
        line_items=line_items_51,
    )
    quote_51 = QuoteSnapshot(
        tenant_id=TENANT_ALPHA_ID,
        correlation_id=uuid4(),
        proposal_id=uuid4(),
        merchant_id=fixture["approved_merchant"].id,
        amount_minor=5001,
        currency="USD",
        line_items=line_items_51,
        quote_hash=q_hash_51,
        expires_at=datetime.now(UTC) + timedelta(hours=1),
    )
    prop_51 = fixture["proposal"].model_copy(update={"amount_minor": 5001, "id": quote_51.proposal_id})
    dec_51 = evaluate_policy_v1(
        proposal=prop_51,
        passport=passport,
        merchant=fixture["approved_merchant"],
        quote=quote_51,
    )
    assert dec_51.outcome == DecisionOutcome.ESCALATE
    assert DecisionReasonCode.ESCALATED_REQUIRES_HUMAN_APPROVAL in dec_51.reason_codes


def test_export_schemas_runs_cleanly() -> None:
    schema = export_all_schemas()
    assert "$defs" in schema or "properties" in schema
    assert "Tenant" in str(schema)
    assert "AP2CheckoutMandate" in str(schema)
