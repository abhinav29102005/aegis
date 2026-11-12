"""Property-based parity verification: 1,000 test cases between Guardian and GhostPay policy-v1 engine."""

from __future__ import annotations

import random
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from contracts import (
    ApprovalRecord,
    ApprovalStatus,
    Merchant,
    PassportStatus,
    PurchaseProposal,
    QuoteSnapshot,
    SpendingPassport,
    compute_quote_hash,
)
from ghostpay.replay.engine import evaluate_deterministic_policy
from guardian.policies.engine import PolicyEngine


@pytest.mark.parametrize("seed", [42, 1337, 2026])
def test_1000_case_guardian_ghostpay_parity(seed: int) -> None:
    """Run 1,000 randomized synthetic test cases verifying 100% decision and reason code parity."""
    rng = random.Random(seed)
    tenant_id = UUID("00000000-0000-4000-8000-000000000001")
    agent_id = UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa")
    allowed_merchant_id = UUID("33333333-3333-4000-8000-000000000001")
    other_merchant_id = UUID("99999999-9999-4999-8999-999999999999")

    currencies = ["USD", "EUR", "GBP", "JPY", "KWD"]
    categories = ["SOFTWARE", "CLOUD", "HARDWARE", "MARKETING", "TRAVEL"]

    guardian_engine = PolicyEngine(policy_version="policy-v1")

    total_cases = 1000
    now = datetime(2026, 11, 12, 12, 0, 0, tzinfo=UTC)

    for i in range(total_cases):
        # 1. Randomize parameters
        currency = rng.choice(currencies)
        total_budget = rng.choice([10000, 50000, 100000, 500000])
        per_tx_limit = rng.choice([1000, 2500, 5000, 10000])
        daily_limit = rng.choice([2000, 5000, 20000])
        human_threshold = rng.choice([2000, 5000, 10000])

        is_allowed_merchant = rng.choice([True, True, False])
        target_merchant_id = allowed_merchant_id if is_allowed_merchant else other_merchant_id

        # Amount variations: $0.01, under limit, exact limit, $0.01 over limit, massive
        amount_type = rng.choice(["tiny", "exact", "under", "over_tx", "over_budget"])
        if amount_type == "tiny":
            amount_minor = 1
        elif amount_type == "exact":
            amount_minor = per_tx_limit
        elif amount_type == "under":
            amount_minor = max(1, per_tx_limit - rng.randint(10, 500))
        elif amount_type == "over_tx":
            amount_minor = per_tx_limit + rng.randint(1, 1000)
        else:
            amount_minor = total_budget + rng.randint(100, 10000)

        passport_status = rng.choice([
            PassportStatus.ACTIVE,
            PassportStatus.ACTIVE,
            PassportStatus.ACTIVE,
            PassportStatus.REVOKED,
            PassportStatus.PAUSED,
            PassportStatus.EXPIRED,
        ])

        passport_expired = passport_status == PassportStatus.EXPIRED or rng.random() < 0.05
        passport_exp = (now - timedelta(days=1)) if passport_expired else (now + timedelta(days=30))

        passport = SpendingPassport(
            id=uuid4(),
            tenant_id=tenant_id,
            agent_id=agent_id,
            total_budget_minor=total_budget,
            per_tx_limit_minor=per_tx_limit,
            daily_limit_minor=daily_limit,
            human_approval_threshold_minor=human_threshold,
            allowed_merchant_ids=[allowed_merchant_id],
            allowed_categories=["SOFTWARE", "CLOUD"],
            status=passport_status,
            expires_at=passport_exp,
            currency=currency,
            created_at=now,
        )

        merchant_category = rng.choice(categories)
        merchant = Merchant(
            id=target_merchant_id,
            tenant_id=tenant_id,
            name="Test Merchant",
            domain="test.example.com",
            category=merchant_category,
            is_allowlisted=is_allowed_merchant,
            created_at=now,
        )

        # Quote
        quote_expired = rng.random() < 0.1
        quote_exp = (now - timedelta(minutes=5)) if quote_expired else (now + timedelta(minutes=15))
        line_items = [{"name": "Item A", "amount_minor": amount_minor}]
        q_hash = compute_quote_hash(
            merchant_id=target_merchant_id,
            amount_minor=amount_minor,
            currency=currency,
            line_items=line_items,
        )

        proposal_id = uuid4()
        quote = QuoteSnapshot(
            id=uuid4(),
            tenant_id=tenant_id,
            correlation_id=uuid4(),
            proposal_id=proposal_id,
            merchant_id=target_merchant_id,
            amount_minor=amount_minor,
            currency=currency,
            line_items=line_items,
            expires_at=quote_exp,
        )

        proposal = PurchaseProposal(
            id=proposal_id,
            tenant_id=tenant_id,
            correlation_id=quote.correlation_id,
            agent_id=agent_id,
            passport_id=passport.id,
            merchant_id=target_merchant_id,
            merchant_name="Test Merchant",
            merchant_category=merchant_category,
            amount_minor=amount_minor,
            currency=currency,
            item_summary="Purchase item",
            line_items=line_items,
            rationale="Test purchase",
            idempotency_key=f"prop-{i}-{rng.randint(1000, 9999)}",
            created_at=now,
        )

        # Approval Record (optional)
        approval_record = None
        has_approval = rng.choice([False, False, True])
        if has_approval:
            app_expired = rng.random() < 0.1
            app_tampered = rng.random() < 0.1
            approval_record = ApprovalRecord(
                id=uuid4(),
                tenant_id=tenant_id,
                correlation_id=quote.correlation_id,
                payment_intent_id=uuid4(),
                decision_id=uuid4(),
                approver_id="human-reviewer",
                status=ApprovalStatus.APPROVED,
                bound_merchant_id=target_merchant_id if not app_tampered else uuid4(),
                bound_amount_minor=amount_minor if not app_tampered else (amount_minor + 100),
                bound_currency=currency,
                bound_quote_hash=q_hash if not app_tampered else "tampered_hash_1234567890",
                decided_at=now,
                expires_at=(now - timedelta(minutes=10)) if app_expired else (now + timedelta(hours=1)),
                created_at=now,
            )

        # 2. Evaluate with Guardian PolicyEngine
        guardian_decision = guardian_engine.evaluate(
            proposal=proposal,
            passport=passport,
            merchant=merchant,
            quote=quote,
            approval_record=approval_record,
            now=now,
        )

        # 3. Evaluate with GhostPay ReplayEngine
        # For historical forensic replay, quote expiration check is passed matching real-time evaluation
        ghostpay_outcome, ghostpay_reason_codes, _ = evaluate_deterministic_policy(
            proposal=proposal,
            passport=passport,
            merchant=merchant,
            quote=quote,
            approval_record=approval_record,
            now=now,
            check_quote_expiration=True,
        )

        # 4. Assert strict parity
        assert guardian_decision.outcome == ghostpay_outcome, (
            f"Case {i} outcome mismatch: Guardian={guardian_decision.outcome} vs GhostPay={ghostpay_outcome}\n"
            f"Amount: {amount_minor}, Per-tx: {per_tx_limit}, Budget: {total_budget}, Merchant Allowed: {is_allowed_merchant}"
        )
        assert set(guardian_decision.reason_codes) == set(ghostpay_reason_codes), (
            f"Case {i} reason codes mismatch: Guardian={guardian_decision.reason_codes} vs GhostPay={ghostpay_reason_codes}"
        )
