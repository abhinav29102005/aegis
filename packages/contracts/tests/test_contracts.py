"""Contract tests covering state machines, hashing, ISO 4217, policy-v1, and fixtures."""

from datetime import UTC, date, datetime, timedelta, timezone
from decimal import Decimal
from uuid import uuid4

import pytest
from contracts import (
    AP2MandatePayload,
    DecisionOutcome,
    DecisionReasonCode,
    DeflectionAlert,
    DisputeStatus,
    FinancialEvent,
    FinancialEventType,
    PassportStatus,
    PaymentProviderAdapter,
    PaymentState,
    QuoteSnapshot,
    SpendingPassport,
    StripeEventEnvelope,
    TAPTokenPayload,
    X402SettlementProof,
    assert_dispute_transition,
    assert_payment_transition,
    can_transition_dispute,
    can_transition_payment,
    canonical_json,
    compute_payload_hash,
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
from pydantic import ValidationError


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


def test_payment_state_machine_matrix_completeness_and_invariants() -> None:
    from contracts.enums import VALID_PAYMENT_TRANSITIONS

    # 1. Completeness: all enum values exist as keys
    all_states = set(PaymentState)
    assert set(VALID_PAYMENT_TRANSITIONS.keys()) == all_states

    # 2. Total valid transitions: exactly 29 out of 169 combinations
    total_valid = 0
    total_illegal = 0
    terminal_states = {
        PaymentState.REFUNDED,
        PaymentState.FAILED,
        PaymentState.CANCELLED,
        PaymentState.EXPIRED,
    }

    for current in PaymentState:
        # Non-reflexivity: self-transitions are strictly illegal
        assert not can_transition_payment(current, current)
        with pytest.raises(ValueError, match="Illegal payment state transition"):
            assert_payment_transition(current, current)

        # Terminal state invariance: empty outgoing set
        if current in terminal_states:
            assert len(VALID_PAYMENT_TRANSITIONS[current]) == 0

        for target in PaymentState:
            if target in VALID_PAYMENT_TRANSITIONS[current]:
                total_valid += 1
                assert can_transition_payment(current, target)
                # should not raise
                assert_payment_transition(current, target)
            else:
                total_illegal += 1
                assert not can_transition_payment(current, target)
                with pytest.raises(ValueError, match="Illegal payment state transition"):
                    assert_payment_transition(current, target)

    assert total_valid == 29
    assert total_illegal == 140
    assert total_valid + total_illegal == len(PaymentState) * len(PaymentState)


def test_payment_state_machine_dag_and_reachability() -> None:
    from contracts.enums import VALID_PAYMENT_TRANSITIONS

    # Verify no cycles (strict DAG)
    visited: dict[PaymentState, int] = {}
    path: list[PaymentState] = []
    cycles: list[list[PaymentState]] = []

    def dfs(node: PaymentState) -> None:
        visited[node] = 1
        path.append(node)
        for neighbor in VALID_PAYMENT_TRANSITIONS[node]:
            if visited.get(neighbor) == 1:
                idx = path.index(neighbor)
                cycles.append(path[idx:] + [neighbor])
            elif visited.get(neighbor) != 2:
                dfs(neighbor)
        path.pop()
        visited[node] = 2

    for state in PaymentState:
        if visited.get(state) != 2:
            dfs(state)

    assert not cycles, f"Detected cycles in PaymentState machine: {cycles}"

    # Verify reachability: all states reachable from CREATED
    reachable = {PaymentState.CREATED}
    frontier = [PaymentState.CREATED]
    while frontier:
        curr = frontier.pop()
        for nxt in VALID_PAYMENT_TRANSITIONS[curr]:
            if nxt not in reachable:
                reachable.add(nxt)
                frontier.append(nxt)

    assert reachable == set(PaymentState), f"Unreachable states: {set(PaymentState) - reachable}"


def test_payment_state_transition_edge_cases_and_type_coercion() -> None:
    # String input support
    assert can_transition_payment("CREATED", "POLICY_CHECK")
    assert not can_transition_payment("CREATED", "SUCCEEDED")
    assert_payment_transition("CREATED", "POLICY_CHECK")

    with pytest.raises(ValueError, match="Illegal payment state transition: CREATED -> SUCCEEDED"):
        assert_payment_transition("CREATED", "SUCCEEDED")

    # Invalid / unknown string inputs
    assert not can_transition_payment("UNKNOWN_STATE", "CREATED")
    assert not can_transition_payment("CREATED", "UNKNOWN_STATE")

    with pytest.raises(ValueError, match="Invalid current payment state: UNKNOWN_STATE"):
        assert_payment_transition("UNKNOWN_STATE", "CREATED")

    with pytest.raises(ValueError, match="Invalid target payment state: UNKNOWN_STATE"):
        assert_payment_transition("CREATED", "UNKNOWN_STATE")

    # None / non-string type inputs
    assert not can_transition_payment(None, PaymentState.CREATED)  # type: ignore[arg-type]
    assert not can_transition_payment(PaymentState.CREATED, 123)  # type: ignore[arg-type]

    with pytest.raises(ValueError, match="Invalid current payment state"):
        assert_payment_transition(None, PaymentState.CREATED)  # type: ignore[arg-type]

    with pytest.raises(ValueError, match="Invalid target payment state"):
        assert_payment_transition(PaymentState.CREATED, 123)  # type: ignore[arg-type]


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


def test_dispute_status_transition_edge_cases_and_type_coercion() -> None:
    # String input support
    assert can_transition_dispute("OPEN", "UNDER_INVESTIGATION")
    assert not can_transition_dispute("SUBMITTED", "DRAFT_READY")
    assert_dispute_transition("OPEN", "UNDER_INVESTIGATION")

    with pytest.raises(ValueError, match="Illegal dispute status transition"):
        assert_dispute_transition("SUBMITTED", "DRAFT_READY")

    # Invalid / unknown string inputs
    assert not can_transition_dispute("UNKNOWN_STATUS", "OPEN")
    assert not can_transition_dispute("OPEN", "UNKNOWN_STATUS")

    with pytest.raises(ValueError, match="Invalid current dispute status"):
        assert_dispute_transition("UNKNOWN_STATUS", "OPEN")

    with pytest.raises(ValueError, match="Invalid target dispute status"):
        assert_dispute_transition("OPEN", "UNKNOWN_STATUS")


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


def test_canonical_json_and_quote_hashing_invariants_and_edge_cases() -> None:
    """Audit and verify all invariants and edge cases for canonical JSON and quote hashing."""
    # 1. Canonical JSON key sorting at multiple nesting depths
    d1 = {"z": 1, "a": {"k2": "v2", "k1": "v1", "nested": {"y": 2, "x": 1}}, "m": [1, 2]}
    d2 = {"m": [1, 2], "a": {"nested": {"x": 1, "y": 2}, "k1": "v1", "k2": "v2"}, "z": 1}
    assert canonical_json(d1) == canonical_json(d2)
    expected_json = '{"a":{"k1":"v1","k2":"v2","nested":{"x":1,"y":2}},"m":[1,2],"z":1}'
    assert canonical_json(d1) == expected_json
    assert compute_payload_hash(d1) == compute_payload_hash(d2)

    # 2. Whitespace separation invariant (no spaces around delimiters)
    assert " " not in canonical_json({"a": 1, "b": [1, 2, 3], "c": {"d": "val"}})

    # 3. Type serialization in canonical JSON
    u = uuid4()
    assert canonical_json({"id": u}) == f'{{"id":"{u!s}"}}'

    # Datetime UTC normalization
    dt_utc = datetime(2026, 11, 19, 12, 0, 0, tzinfo=UTC)
    dt_est = datetime(2026, 11, 19, 7, 0, 0, tzinfo=timezone(timedelta(hours=-5)))
    assert canonical_json({"ts": dt_utc}) == canonical_json({"ts": dt_est})
    assert canonical_json({"ts": dt_utc}) == '{"ts":"2026-11-19T12:00:00+00:00"}'

    # Date and Decimal serialization
    d = date(2026, 11, 19)
    assert canonical_json({"date": d}) == '{"date":"2026-11-19"}'
    dec = Decimal("123.45")
    assert canonical_json({"dec": dec}) == '{"dec":"123.45"}'

    # Rejection of invalid floats (NaN, Inf)
    with pytest.raises(ValueError, match="Out of range float values"):
        canonical_json({"nan": float("nan")})
    with pytest.raises(ValueError, match="Out of range float values"):
        canonical_json({"inf": float("inf")})

    # Rejection of unsupported types
    with pytest.raises(TypeError, match="is not JSON serializable"):
        canonical_json({"set": {1, 2, 3}})
    with pytest.raises(TypeError, match="is not JSON serializable"):
        canonical_json({"bytes": b"binary_data"})

    # 4. compute_quote_hash invariants
    base_merchant = uuid4()
    h_base = compute_quote_hash(
        merchant_id=base_merchant,
        amount_minor=5000,
        currency="USD",
        line_items=[{"sku": "SKU-001", "name": "Item A", "unit_price_minor": 5000, "qty": 1}],
    )

    # UUID normalization: UUID object vs lowercase str vs uppercase str vs whitespace str
    h_lower_str = compute_quote_hash(
        merchant_id=str(base_merchant).lower(),
        amount_minor=5000,
        currency="USD",
        line_items=[{"sku": "SKU-001", "name": "Item A", "unit_price_minor": 5000, "qty": 1}],
    )
    h_upper_str = compute_quote_hash(
        merchant_id=str(base_merchant).upper(),
        amount_minor=5000,
        currency="USD",
        line_items=[{"sku": "SKU-001", "name": "Item A", "unit_price_minor": 5000, "qty": 1}],
    )
    h_whitespace_str = compute_quote_hash(
        merchant_id=f"  {base_merchant!s}  ",
        amount_minor=5000,
        currency="USD",
        line_items=[{"sku": "SKU-001", "name": "Item A", "unit_price_minor": 5000, "qty": 1}],
    )
    assert h_base == h_lower_str == h_upper_str == h_whitespace_str

    # Non-UUID merchant strings are preserved
    h_custom_merchant = compute_quote_hash(
        merchant_id="merchant_paypal_express_99",
        amount_minor=5000,
        currency="USD",
    )
    assert len(h_custom_merchant) == 64

    # Currency normalization: casing & whitespace
    h_curr_lower = compute_quote_hash(
        merchant_id=base_merchant,
        amount_minor=5000,
        currency="usd",
        line_items=[{"sku": "SKU-001", "name": "Item A", "unit_price_minor": 5000, "qty": 1}],
    )
    h_curr_spaces = compute_quote_hash(
        merchant_id=base_merchant,
        amount_minor=5000,
        currency="  USD  ",
        line_items=[{"sku": "SKU-001", "name": "Item A", "unit_price_minor": 5000, "qty": 1}],
    )
    assert h_base == h_curr_lower == h_curr_spaces

    # Line items: None vs empty list equivalence
    h_no_items = compute_quote_hash(merchant_id=base_merchant, amount_minor=5000, currency="USD", line_items=None)
    h_empty_items = compute_quote_hash(merchant_id=base_merchant, amount_minor=5000, currency="USD", line_items=[])
    assert h_no_items == h_empty_items

    # Line items: dict key ordering within line items
    h_reordered_keys = compute_quote_hash(
        merchant_id=base_merchant,
        amount_minor=5000,
        currency="USD",
        line_items=[{"qty": 1, "unit_price_minor": 5000, "name": "Item A", "sku": "SKU-001"}],
    )
    assert h_base == h_reordered_keys

    # Line items: Unicode / multi-lingual text determinism
    h_unicode = compute_quote_hash(
        merchant_id=base_merchant,
        amount_minor=3000,
        currency="JPY",
        line_items=[{"sku": "JP-1", "name": "東京サーバ 🚀", "note": "Café München"}],
    )
    h_unicode_repeat = compute_quote_hash(
        merchant_id=base_merchant,
        amount_minor=3000,
        currency="JPY",
        line_items=[{"note": "Café München", "name": "東京サーバ 🚀", "sku": "JP-1"}],
    )
    assert h_unicode == h_unicode_repeat

    # Tamper resistance across every dimension
    # 1. Amount minor
    assert compute_quote_hash(merchant_id=base_merchant, amount_minor=5001, currency="USD") != h_no_items
    assert compute_quote_hash(merchant_id=base_merchant, amount_minor=4999, currency="USD") != h_no_items
    # 2. Currency
    assert compute_quote_hash(merchant_id=base_merchant, amount_minor=5000, currency="EUR") != h_no_items
    # 3. Merchant
    assert compute_quote_hash(merchant_id=uuid4(), amount_minor=5000, currency="USD") != h_no_items
    # 4. Line items quantity/price/sku alteration
    assert compute_quote_hash(
        merchant_id=base_merchant,
        amount_minor=5000,
        currency="USD",
        line_items=[{"sku": "SKU-001", "name": "Item A", "unit_price_minor": 5000, "qty": 2}],
    ) != h_base
    # 5. Line items order alteration (sequence matters)
    item_1 = {"sku": "A", "price": 10}
    item_2 = {"sku": "B", "price": 20}
    h_seq1 = compute_quote_hash(merchant_id=base_merchant, amount_minor=30, currency="USD", line_items=[item_1, item_2])
    h_seq2 = compute_quote_hash(merchant_id=base_merchant, amount_minor=30, currency="USD", line_items=[item_2, item_1])
    assert h_seq1 != h_seq2

    # 5. QuoteSnapshot integration and validation
    qs = QuoteSnapshot(
        tenant_id=uuid4(),
        correlation_id=uuid4(),
        proposal_id=uuid4(),
        merchant_id=base_merchant,
        amount_minor=5000,
        currency="usd",
        line_items=[{"sku": "SKU-001", "name": "Item A", "unit_price_minor": 5000, "qty": 1}],
        expires_at=datetime.now(UTC) + timedelta(minutes=15),
    )
    assert qs.quote_hash == h_base
    assert qs.currency == "USD"

    # Rejection of invalid quote_hash
    with pytest.raises(ValueError, match="quote_hash mismatch"):
        QuoteSnapshot(
            tenant_id=qs.tenant_id,
            correlation_id=qs.correlation_id,
            proposal_id=qs.proposal_id,
            merchant_id=base_merchant,
            amount_minor=5000,
            currency="USD",
            line_items=qs.line_items,
            quote_hash="badhash" + "0" * 57,
            expires_at=qs.expires_at,
        )

    # Rejection of non-positive amount_minor
    with pytest.raises(ValidationError):
        QuoteSnapshot(
            tenant_id=qs.tenant_id,
            correlation_id=qs.correlation_id,
            proposal_id=qs.proposal_id,
            merchant_id=base_merchant,
            amount_minor=0,
            currency="USD",
            expires_at=qs.expires_at,
        )


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


def test_financial_event_canonical_structure_and_invariants() -> None:
    # 1. FinancialEventType canonical enum completeness (24 lifecycle events)
    expected_event_types = {
        "PROPOSAL_CREATED",
        "POLICY_EVALUATED",
        "APPROVAL_REQUESTED",
        "HUMAN_APPROVED",
        "HUMAN_REJECTED",
        "BUDGET_RESERVED",
        "BUDGET_RELEASED",
        "BUDGET_CAPTURED",
        "PAYPAL_ORDER_CREATED",
        "PAYPAL_BUYER_APPROVED",
        "PAYPAL_BUYER_CANCELLED",
        "PAYPAL_CAPTURE_REQUESTED",
        "PAYPAL_CAPTURE_VERIFIED",
        "PAYPAL_TIMEOUT_PENDING",
        "PAYPAL_WEBHOOK_RECEIVED",
        "PAYMENT_FAILED",
        "PAYMENT_REFUNDED",
        "PAYMENT_VOIDED",
        "DISPUTE_OPENED",
        "DISPUTE_EVIDENCE_ATTACHED",
        "DISPUTE_ANALYZED",
        "DISPUTE_RESPONSE_APPROVED",
        "DISPUTE_SUBMITTED",
        "DISPUTE_RESOLVED",
    }
    actual_event_types = {e.value for e in FinancialEventType}
    assert actual_event_types == expected_event_types
    assert len(FinancialEventType) == 24

    # 2. Valid instantiation with full and minimal payloads
    tenant_id = uuid4()
    corr_id = uuid4()
    pi_id = uuid4()
    ev_hash = "a" * 64
    base_time = datetime(2026, 11, 19, 12, 0, 0, tzinfo=UTC)

    event_full = FinancialEvent(
        tenant_id=tenant_id,
        correlation_id=corr_id,
        payment_intent_id=pi_id,
        sequence_number=1,
        event_type=FinancialEventType.PROPOSAL_CREATED,
        actor_type="agent",
        actor_id="autonomous-buyer-1",
        payload={"amount_minor": 3900, "currency": "USD"},
        previous_event_hash=None,
        event_hash=ev_hash,
        occurred_at=base_time,
    )
    assert event_full.schema_version == "1.0.0"
    assert event_full.payment_intent_id == pi_id
    assert event_full.sequence_number == 1
    assert event_full.event_type == FinancialEventType.PROPOSAL_CREATED
    assert event_full.payload == {"amount_minor": 3900, "currency": "USD"}
    assert event_full.previous_event_hash is None
    assert event_full.event_hash == ev_hash
    assert event_full.occurred_at.tzinfo == UTC

    # Minimal payload without payment_intent_id (e.g., pre-intent or dispute event)
    event_min = FinancialEvent(
        tenant_id=tenant_id,
        correlation_id=corr_id,
        sequence_number=1,
        event_type=FinancialEventType.DISPUTE_OPENED,
        actor_type="webhook",
        actor_id="paypal-listener",
        event_hash=ev_hash,
    )
    assert event_min.payment_intent_id is None
    assert event_min.payload == {}
    assert event_min.previous_event_hash is None
    assert event_min.occurred_at.tzinfo == UTC

    # 3. Invariant: sequence_number must be ge=1 (0 or negative rejected)
    with pytest.raises(ValidationError) as exc_info:
        FinancialEvent(
            tenant_id=tenant_id,
            correlation_id=corr_id,
            sequence_number=0,
            event_type=FinancialEventType.PROPOSAL_CREATED,
            actor_type="agent",
            actor_id="a1",
            event_hash=ev_hash,
        )
    assert "Input should be greater than or equal to 1" in str(exc_info.value)

    # 4. Invariant: actor_type and actor_id length bounds (reject empty strings)
    with pytest.raises(ValidationError):
        FinancialEvent(
            tenant_id=tenant_id,
            correlation_id=corr_id,
            sequence_number=1,
            event_type=FinancialEventType.PROPOSAL_CREATED,
            actor_type="",
            actor_id="a1",
            event_hash=ev_hash,
        )

    with pytest.raises(ValidationError):
        FinancialEvent(
            tenant_id=tenant_id,
            correlation_id=corr_id,
            sequence_number=1,
            event_type=FinancialEventType.PROPOSAL_CREATED,
            actor_type="agent",
            actor_id="",
            event_hash=ev_hash,
        )

    # 5. Invariant: event_hash length bounds (min_length=16, max_length=128)
    with pytest.raises(ValidationError):
        FinancialEvent(
            tenant_id=tenant_id,
            correlation_id=corr_id,
            sequence_number=1,
            event_type=FinancialEventType.PROPOSAL_CREATED,
            actor_type="agent",
            actor_id="a1",
            event_hash="too_short",
        )

    # 6. Invariant: extra fields forbidden (NexusBaseModel)
    with pytest.raises(ValidationError):
        FinancialEvent(
            tenant_id=tenant_id,
            correlation_id=corr_id,
            sequence_number=1,
            event_type=FinancialEventType.PROPOSAL_CREATED,
            actor_type="agent",
            actor_id="a1",
            event_hash=ev_hash,
            unexpected_field="disallowed",
        )

    # 7. Invariant: UTC timestamp normalization for naive and timezone-aware inputs
    naive_dt = datetime(2026, 11, 19, 14, 30, 0)
    ev_naive = FinancialEvent(
        tenant_id=tenant_id,
        correlation_id=corr_id,
        sequence_number=1,
        event_type=FinancialEventType.PROPOSAL_CREATED,
        actor_type="agent",
        actor_id="a1",
        event_hash=ev_hash,
        occurred_at=naive_dt,
    )
    assert ev_naive.occurred_at.tzinfo == UTC
    assert ev_naive.occurred_at.hour == 14

    offset_dt = datetime(2026, 11, 19, 20, 0, 0, tzinfo=timezone(timedelta(hours=5, minutes=30)))
    ev_offset = FinancialEvent(
        tenant_id=tenant_id,
        correlation_id=corr_id,
        sequence_number=1,
        event_type=FinancialEventType.PROPOSAL_CREATED,
        actor_type="agent",
        actor_id="a1",
        event_hash=ev_hash,
        occurred_at=offset_dt,
    )
    assert ev_offset.occurred_at.tzinfo == UTC
    assert ev_offset.occurred_at.hour == 14
    assert ev_offset.occurred_at.minute == 30

    # 8. Deterministic canonical JSON and payload hash computation
    canonical_str = canonical_json(event_full)
    hash1 = compute_payload_hash(event_full)
    hash2 = compute_payload_hash(event_full)
    assert hash1 == hash2
    assert isinstance(canonical_str, str)
    assert '"schema_version":"1.0.0"' in canonical_str


def test_spending_passport_schema_and_expiration_invariants() -> None:
    tenant_id = uuid4()
    agent_id = uuid4()
    base_created = datetime(2026, 11, 19, 10, 0, 0, tzinfo=UTC)
    base_expires = base_created + timedelta(days=30)

    # 1. Valid passport construction with default and explicit fields
    passport = SpendingPassport(
        tenant_id=tenant_id,
        agent_id=agent_id,
        currency="usd",
        total_budget_minor=10000,
        per_tx_limit_minor=2500,
        daily_limit_minor=5000,
        monthly_limit_minor=10000,
        expires_at=base_expires,
        created_at=base_created,
    )
    assert passport.schema_version == "1.0.0"
    assert passport.currency == "USD"
    assert passport.status == PassportStatus.ACTIVE
    assert passport.spent_minor == 0
    assert passport.reserved_minor == 0
    assert passport.human_approval_threshold_minor == 5000
    assert passport.approval_threshold_minor == 5000
    assert passport.allow_unknown_merchants is False
    assert passport.allowed_currencies == []
    assert passport.allowed_merchant_ids == []
    assert passport.allowed_categories == []
    assert passport.available_budget_minor == 10000

    # 2. Strict model config: extra fields forbidden
    with pytest.raises(ValidationError):
        SpendingPassport(
            tenant_id=tenant_id,
            agent_id=agent_id,
            total_budget_minor=10000,
            per_tx_limit_minor=2500,
            daily_limit_minor=5000,
            expires_at=base_expires,
            unauthorized_field="malicious_payload",
        )

    # 3. Currency normalization and length invariants
    with pytest.raises(ValidationError):
        SpendingPassport(
            tenant_id=tenant_id,
            agent_id=agent_id,
            currency="US",  # min_length=3
            total_budget_minor=10000,
            per_tx_limit_minor=2500,
            daily_limit_minor=5000,
            expires_at=base_expires,
        )

    with pytest.raises(ValidationError):
        SpendingPassport(
            tenant_id=tenant_id,
            agent_id=agent_id,
            currency="USDD",  # max_length=3
            total_budget_minor=10000,
            per_tx_limit_minor=2500,
            daily_limit_minor=5000,
            expires_at=base_expires,
        )

    passport_curr = SpendingPassport(
        tenant_id=tenant_id,
        agent_id=agent_id,
        currency="eur",
        allowed_currencies=["usd", "eur", "gbp"],
        total_budget_minor=10000,
        per_tx_limit_minor=2500,
        daily_limit_minor=5000,
        expires_at=base_expires,
    )
    assert passport_curr.currency == "EUR"
    assert passport_curr.allowed_currencies == ["USD", "EUR", "GBP"]

    # 4. Non-negative numeric invariants (ge=0)
    base_kwargs = {
        "tenant_id": tenant_id,
        "agent_id": agent_id,
        "total_budget_minor": 10000,
        "per_tx_limit_minor": 2500,
        "daily_limit_minor": 5000,
        "expires_at": base_expires,
    }
    for field_name in [
        "total_budget_minor",
        "spent_minor",
        "reserved_minor",
        "per_tx_limit_minor",
        "daily_limit_minor",
        "monthly_limit_minor",
        "human_approval_threshold_minor",
    ]:
        with pytest.raises(ValidationError):
            SpendingPassport(**{**base_kwargs, field_name: -1})

    # 5. available_budget_minor property invariants
    p_budget = SpendingPassport(
        tenant_id=tenant_id,
        agent_id=agent_id,
        total_budget_minor=10000,
        spent_minor=3000,
        reserved_minor=2000,
        per_tx_limit_minor=2500,
        daily_limit_minor=5000,
        expires_at=base_expires,
    )
    assert p_budget.available_budget_minor == 5000

    # Overdraft / exceeding budget clamps to 0 (cannot be negative)
    p_over = p_budget.model_copy(update={"spent_minor": 8000, "reserved_minor": 4000})
    assert p_over.available_budget_minor == 0

    p_zero = p_budget.model_copy(update={"total_budget_minor": 0, "spent_minor": 0, "reserved_minor": 0})
    assert p_zero.available_budget_minor == 0

    # 6. PassportStatus enum invariants
    for st in [PassportStatus.ACTIVE, PassportStatus.PAUSED, PassportStatus.REVOKED, PassportStatus.EXPIRED]:
        p_st = passport.model_copy(update={"status": st})
        assert p_st.status == st

    with pytest.raises(ValidationError):
        SpendingPassport(
            tenant_id=tenant_id,
            agent_id=agent_id,
            status="INVALID_STATUS",
            total_budget_minor=10000,
            per_tx_limit_minor=2500,
            daily_limit_minor=5000,
            expires_at=base_expires,
        )

    # 7. Timezone normalization on expires_at and created_at
    naive_exp = datetime(2026, 12, 1, 12, 0, 0)
    p_naive = SpendingPassport(
        tenant_id=tenant_id,
        agent_id=agent_id,
        total_budget_minor=10000,
        per_tx_limit_minor=2500,
        daily_limit_minor=5000,
        expires_at=naive_exp,
    )
    assert p_naive.expires_at.tzinfo == UTC
    assert p_naive.expires_at.hour == 12

    offset_exp = datetime(2026, 12, 1, 17, 30, 0, tzinfo=timezone(timedelta(hours=5, minutes=30)))
    p_offset = SpendingPassport(
        tenant_id=tenant_id,
        agent_id=agent_id,
        total_budget_minor=10000,
        per_tx_limit_minor=2500,
        daily_limit_minor=5000,
        expires_at=offset_exp,
    )
    assert p_offset.expires_at.tzinfo == UTC
    assert p_offset.expires_at.hour == 12
    assert p_offset.expires_at.minute == 0

    # 8. JSON serialization and round-trip preservation
    dumped = passport.model_dump_json()
    rehydrated = SpendingPassport.model_validate_json(dumped)
    assert rehydrated == passport
    assert rehydrated.expires_at == passport.expires_at
    assert rehydrated.expires_at.tzinfo == UTC

    # 9. Expiration boundary conditions under evaluate_policy_v1
    fx = build_authorized_39_purchase_fixture()
    proposal = fx["proposal"]
    merchant = fx["approved_merchant"]
    exp_time = base_created + timedelta(days=7)

    passport_eval = SpendingPassport(
        id=proposal.passport_id,
        tenant_id=proposal.tenant_id,
        agent_id=proposal.agent_id,
        currency="USD",
        total_budget_minor=10000,
        per_tx_limit_minor=5000,
        daily_limit_minor=10000,
        allowed_merchant_ids=[merchant.id],
        allowed_categories=["SOFTWARE"],
        status=PassportStatus.ACTIVE,
        expires_at=exp_time,
        created_at=base_created,
    )

    # Sub-second before expiration -> ALLOW
    dec_before = evaluate_policy_v1(
        proposal=proposal,
        passport=passport_eval,
        merchant=merchant,
        now=exp_time - timedelta(microseconds=1),
    )
    assert dec_before.outcome == DecisionOutcome.ALLOW
    assert DecisionReasonCode.OK_WITHIN_POLICY in dec_before.reason_codes

    # Exact boundary timestamp -> DENIED_PASSPORT_EXPIRED (fail-secure boundary: expires_at <= ts)
    dec_exact = evaluate_policy_v1(
        proposal=proposal,
        passport=passport_eval,
        merchant=merchant,
        now=exp_time,
    )
    assert dec_exact.outcome == DecisionOutcome.DENY
    assert DecisionReasonCode.DENIED_PASSPORT_EXPIRED in dec_exact.reason_codes

    # Sub-second after expiration -> DENIED_PASSPORT_EXPIRED
    dec_after = evaluate_policy_v1(
        proposal=proposal,
        passport=passport_eval,
        merchant=merchant,
        now=exp_time + timedelta(microseconds=1),
    )
    assert dec_after.outcome == DecisionOutcome.DENY
    assert DecisionReasonCode.DENIED_PASSPORT_EXPIRED in dec_after.reason_codes

    # 10. PassportStatus vs Expiration matrix in evaluate_policy_v1
    # Status EXPIRED with now < expires_at
    dec_status_exp = evaluate_policy_v1(
        proposal=proposal,
        passport=passport_eval.model_copy(update={"status": PassportStatus.EXPIRED}),
        merchant=merchant,
        now=exp_time - timedelta(days=1),
    )
    assert dec_status_exp.outcome == DecisionOutcome.DENY
    assert DecisionReasonCode.DENIED_PASSPORT_EXPIRED in dec_status_exp.reason_codes
    assert "Spending passport status is EXPIRED" in dec_status_exp.violated_constraints

    # Status EXPIRED with now >= expires_at (deduplicated reason code in reason_codes)
    dec_both_exp = evaluate_policy_v1(
        proposal=proposal,
        passport=passport_eval.model_copy(update={"status": PassportStatus.EXPIRED}),
        merchant=merchant,
        now=exp_time + timedelta(days=1),
    )
    assert dec_both_exp.outcome == DecisionOutcome.DENY
    assert dec_both_exp.reason_codes.count(DecisionReasonCode.DENIED_PASSPORT_EXPIRED) == 1
    assert any("status is EXPIRED" in v for v in dec_both_exp.violated_constraints)
    assert any("expired at" in v for v in dec_both_exp.violated_constraints)

    # Status REVOKED with now >= expires_at -> reports both REVOKED and EXPIRED
    dec_rev_exp = evaluate_policy_v1(
        proposal=proposal,
        passport=passport_eval.model_copy(update={"status": PassportStatus.REVOKED}),
        merchant=merchant,
        now=exp_time + timedelta(days=1),
    )
    assert dec_rev_exp.outcome == DecisionOutcome.DENY
    assert DecisionReasonCode.DENIED_PASSPORT_REVOKED in dec_rev_exp.reason_codes
    assert DecisionReasonCode.DENIED_PASSPORT_EXPIRED in dec_rev_exp.reason_codes

    # Status PAUSED with now >= expires_at -> reports both PAUSED and EXPIRED
    dec_pause_exp = evaluate_policy_v1(
        proposal=proposal,
        passport=passport_eval.model_copy(update={"status": PassportStatus.PAUSED}),
        merchant=merchant,
        now=exp_time + timedelta(days=1),
    )
    assert dec_pause_exp.outcome == DecisionOutcome.DENY
    assert DecisionReasonCode.DENIED_PASSPORT_PAUSED in dec_pause_exp.reason_codes
    assert DecisionReasonCode.DENIED_PASSPORT_EXPIRED in dec_pause_exp.reason_codes

    # 11. Replay & historical evaluation isolation
    # When now is omitted, it evaluates against current real time (datetime.now(UTC))
    past_passport = passport_eval.model_copy(
        update={"expires_at": datetime.now(UTC) - timedelta(minutes=5)}
    )
    dec_live = evaluate_policy_v1(
        proposal=proposal,
        passport=past_passport,
        merchant=merchant,
    )
    assert dec_live.outcome == DecisionOutcome.DENY
    assert DecisionReasonCode.DENIED_PASSPORT_EXPIRED in dec_live.reason_codes

    # But historical replay at a timestamp before expiration ALLOWS the transaction
    dec_replay = evaluate_policy_v1(
        proposal=proposal,
        passport=past_passport,
        merchant=merchant,
        now=past_passport.expires_at - timedelta(minutes=10),
    )
    assert dec_replay.outcome == DecisionOutcome.ALLOW
    assert DecisionReasonCode.OK_WITHIN_POLICY in dec_replay.reason_codes



