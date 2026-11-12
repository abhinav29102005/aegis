"""Unified canonical policy-v1 evaluator and ISO 4217 currency exponent utilities.

Used identically by AgentPay Guardian (pre-transaction authorization) and
GhostPay (post-transaction deterministic counterfactual replay).
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import ROUND_HALF_UP, Decimal
from typing import Any
from uuid import UUID, uuid4

from contracts.enums import (
    ApprovalStatus,
    DecisionOutcome,
    DecisionReasonCode,
    PassportStatus,
)
from contracts.hashing import compute_quote_hash
from contracts.models import (
    AgentIdentity,
    ApprovalRecord,
    AuthorizationDecision,
    Merchant,
    PurchaseProposal,
    QuoteSnapshot,
    SpendingPassport,
)

# ---------------------------------------------------------------------------
# ISO 4217 Currency Exponents
# ---------------------------------------------------------------------------

CURRENCY_EXPONENTS: dict[str, int] = {
    # 0 decimal places
    "BIF": 0, "CLP": 0, "DJF": 0, "GNF": 0, "ISK": 0, "JPY": 0,
    "KMF": 0, "KRW": 0, "PYG": 0, "RWF": 0, "UGX": 0, "UYI": 0,
    "VND": 0, "VUV": 0, "XAF": 0, "XOF": 0, "XPF": 0,
    # 3 decimal places
    "BHD": 3, "IQD": 3, "JOD": 3, "KWD": 3, "LYD": 3, "OMR": 3, "TND": 3,
    # 4 decimal places
    "CLF": 4, "UYW": 4,
}
DEFAULT_CURRENCY_EXPONENT: int = 2


def get_currency_exponent(currency: str) -> int:
    """Return ISO 4217 exponent (fraction digits) for currency code."""
    return CURRENCY_EXPONENTS.get(currency.strip().upper(), DEFAULT_CURRENCY_EXPONENT)


def format_minor_to_major(amount_minor: int, currency: str = "USD") -> str:
    """Format integer minor units to standard major decimal string (e.g. 3900 USD -> '39.00', 3900 JPY -> '3900')."""
    exp = get_currency_exponent(currency)
    if exp == 0:
        return str(amount_minor)
    scale = Decimal(10) ** exp
    dec_val = Decimal(amount_minor) / scale
    return f"{dec_val:.{exp}f}"


def parse_major_to_minor(amount_str: str, currency: str = "USD") -> int:
    """Parse major decimal string to integer minor units using exact arithmetic."""
    exp = get_currency_exponent(currency)
    dec_val = Decimal(amount_str.strip())
    scale = Decimal(10) ** exp
    minor_val = (dec_val * scale).to_integral_value(rounding=ROUND_HALF_UP)
    return int(minor_val)


# ---------------------------------------------------------------------------
# Unified policy-v1 Evaluation
# ---------------------------------------------------------------------------

def evaluate_policy_v1_rules(
    *,
    proposal: PurchaseProposal,
    quote: QuoteSnapshot,
    passport: SpendingPassport,
    merchant: Merchant,
    agent: AgentIdentity | None = None,
    approval_record: ApprovalRecord | None = None,
    historical_daily_spend_minor: int = 0,
    evaluation_time: datetime | None = None,
    check_quote_expiration: bool = True,
) -> tuple[DecisionOutcome, list[DecisionReasonCode], list[str]]:
    """Evaluate canonical 'policy-v1' deterministic rules.

    Returns:
        (outcome, reason_codes, violated_constraints)
    """
    eval_time = evaluation_time or quote.created_at
    if eval_time.tzinfo is None:
        eval_time = eval_time.replace(tzinfo=UTC)

    denials: list[DecisionReasonCode] = []
    escalations: list[DecisionReasonCode] = []
    violations: list[str] = []

    # 1. Tenant boundary enforcement
    if (
        proposal.tenant_id != passport.tenant_id
        or proposal.tenant_id != merchant.tenant_id
        or proposal.tenant_id != quote.tenant_id
    ):
        denials.append(DecisionReasonCode.DENIED_CROSS_TENANT)
        violations.append(
            f"Cross-tenant mismatch: proposal={proposal.tenant_id}, "
            f"passport={passport.tenant_id}, merchant={merchant.tenant_id}, quote={quote.tenant_id}"
        )

    # 2. Agent identity status (GAP-011)
    if agent is not None:
        agent_status = getattr(agent, "status", "ACTIVE")
        if agent_status in ("SUSPENDED", "REVOKED", "PAUSED"):
            denials.append(DecisionReasonCode.DENIED_AGENT_SUSPENDED)
            violations.append(f"Agent {agent.id} is in non-active status: {agent_status}")

    # 3. Spending passport status & expiration check (GAP-011)
    if passport.status == PassportStatus.EXPIRED:
        denials.append(DecisionReasonCode.DENIED_PASSPORT_EXPIRED)
        violations.append("Passport status is EXPIRED")
    elif passport.status == PassportStatus.REVOKED:
        denials.append(DecisionReasonCode.DENIED_PASSPORT_REVOKED)
        violations.append("Passport status is REVOKED")
    elif passport.status != PassportStatus.ACTIVE:
        denials.append(DecisionReasonCode.DENIED_PASSPORT_REVOKED)
        violations.append(f"Passport status is {passport.status.value}")

    passport_exp = passport.expires_at
    if passport_exp.tzinfo is None:
        passport_exp = passport_exp.replace(tzinfo=UTC)
    if eval_time > passport_exp:
        if DecisionReasonCode.DENIED_PASSPORT_EXPIRED not in denials:
            denials.append(DecisionReasonCode.DENIED_PASSPORT_EXPIRED)
        violations.append(f"Passport expired at {passport_exp.isoformat()} (eval_time: {eval_time.isoformat()})")

    # 4. Currency matching
    if proposal.currency.upper() != passport.currency.upper() or proposal.currency.upper() != quote.currency.upper():
        denials.append(DecisionReasonCode.DENIED_CATEGORY_NOT_ALLOWED)
        violations.append(
            f"Currency mismatch: proposal={proposal.currency}, passport={passport.currency}, quote={quote.currency}"
        )

    # 5. Quote expiration & hash verification (GAP-005, GAP-011)
    if check_quote_expiration:
        quote_exp = quote.expires_at
        if quote_exp.tzinfo is None:
            quote_exp = quote_exp.replace(tzinfo=UTC)
        if eval_time > quote_exp:
            denials.append(DecisionReasonCode.DENIED_QUOTE_EXPIRED)
            violations.append(f"Quote expired at {quote_exp.isoformat()} (eval_time: {eval_time.isoformat()})")

    recomputed_q_hash = compute_quote_hash(
        merchant_id=quote.merchant_id,
        amount_minor=quote.amount_minor,
        currency=quote.currency,
        line_items=quote.line_items,
    )
    if quote.quote_hash != recomputed_q_hash:
        denials.append(DecisionReasonCode.DENIED_APPROVAL_MISMATCH)
        violations.append(f"Quote hash tampered: stored {quote.quote_hash} != computed {recomputed_q_hash}")

    # 6. Transaction limits & total budget
    amount = proposal.amount_minor
    if amount > passport.per_tx_limit_minor:
        denials.append(DecisionReasonCode.DENIED_EXCEEDS_PER_TX_LIMIT)
        violations.append(f"Amount {amount} exceeds per-transaction limit of {passport.per_tx_limit_minor}")

    if amount > passport.available_budget_minor:
        denials.append(DecisionReasonCode.DENIED_EXCEEDS_PASSPORT_BUDGET)
        violations.append(f"Amount {amount} exceeds available budget of {passport.available_budget_minor}")

    # Rolling daily limit check (GAP-011)
    if passport.daily_limit_minor > 0:
        total_daily = historical_daily_spend_minor + amount
        if total_daily > passport.daily_limit_minor:
            denials.append(DecisionReasonCode.DENIED_EXCEEDS_DAILY_LIMIT)
            violations.append(f"Total daily spend {total_daily} exceeds daily limit of {passport.daily_limit_minor}")

    # 7. Strict Merchant Allowlist & Category Intersection (GAP-011: no global merchant.is_allowlisted bypass)
    is_merchant_in_passport = merchant.id in passport.allowed_merchant_ids
    if not is_merchant_in_passport:
        if not passport.allow_unknown_merchants:
            denials.append(DecisionReasonCode.DENIED_MERCHANT_NOT_ALLOWLISTED)
            violations.append(f"Merchant '{merchant.name}' ({merchant.id}) not in passport allowed_merchant_ids")
        else:
            escalations.append(DecisionReasonCode.ESCALATED_UNKNOWN_MERCHANT)

    if passport.allowed_categories:
        merchant_cat = (merchant.category or "").strip().upper()
        proposal_cat = (proposal.merchant_category or "").strip().upper()
        allowed_cats = {c.strip().upper() for c in passport.allowed_categories}
        if merchant_cat not in allowed_cats or proposal_cat not in allowed_cats:
            denials.append(DecisionReasonCode.DENIED_CATEGORY_NOT_ALLOWED)
            violations.append(
                f"Merchant category '{merchant_cat}' or proposal '{proposal_cat}' not in allowed: {sorted(allowed_cats)}"
            )

    # 8. Human Approval Threshold & Approval Record verification (GAP-005, GAP-011)
    # Exact threshold operator: amount_minor > human_approval_threshold_minor
    requires_approval_by_threshold = amount > passport.human_approval_threshold_minor
    if requires_approval_by_threshold:
        if approval_record is None:
            escalations.append(DecisionReasonCode.ESCALATED_REQUIRES_HUMAN_APPROVAL)
        else:
            # Check approval record binding & status
            app_exp = approval_record.expires_at
            if app_exp.tzinfo is None:
                app_exp = app_exp.replace(tzinfo=UTC)
            if eval_time > app_exp:
                denials.append(DecisionReasonCode.DENIED_APPROVAL_EXPIRED)
                violations.append(f"Approval record expired at {app_exp.isoformat()}")
            elif approval_record.status == ApprovalStatus.REJECTED:
                denials.append(DecisionReasonCode.DENIED_APPROVAL_MISMATCH)
                violations.append("Approval record is in REJECTED status")
            elif approval_record.status not in (ApprovalStatus.APPROVED, ApprovalStatus.CONSUMED):
                escalations.append(DecisionReasonCode.ESCALATED_REQUIRES_HUMAN_APPROVAL)
            else:
                # Validate binding parameters
                if approval_record.bound_merchant_id != merchant.id:
                    denials.append(DecisionReasonCode.DENIED_APPROVAL_MISMATCH)
                    violations.append(f"Approval merchant {approval_record.bound_merchant_id} != {merchant.id}")
                if approval_record.bound_amount_minor != amount:
                    denials.append(DecisionReasonCode.DENIED_APPROVAL_MISMATCH)
                    violations.append(f"Approval amount {approval_record.bound_amount_minor} != {amount}")
                if approval_record.bound_currency.upper() != proposal.currency.upper():
                    denials.append(DecisionReasonCode.DENIED_APPROVAL_MISMATCH)
                    violations.append(f"Approval currency {approval_record.bound_currency} != {proposal.currency}")
                if approval_record.bound_quote_hash != quote.quote_hash:
                    denials.append(DecisionReasonCode.DENIED_APPROVAL_MISMATCH)
                    violations.append("Approval quote hash does not match proposal quote hash")

    # Determine final outcome
    if denials:
        return DecisionOutcome.DENY, denials, violations
    if escalations:
        return DecisionOutcome.ESCALATE, escalations, violations
    return DecisionOutcome.ALLOW, [DecisionReasonCode.OK_WITHIN_POLICY], []


def evaluate_policy_v1(
    *,
    proposal: PurchaseProposal,
    passport: SpendingPassport,
    merchant: Merchant,
    quote: QuoteSnapshot,
    agent: AgentIdentity | None = None,
    approval_record: ApprovalRecord | None = None,
    historical_daily_spend_minor: int = 0,
    payment_intent_id: UUID | None = None,
    evaluation_time: datetime | None = None,
    policy_version: str = "policy-v1",
) -> AuthorizationDecision:
    """Evaluate canonical policy-v1 and return an immutable AuthorizationDecision contract."""
    eval_time = evaluation_time or quote.created_at or datetime.now(UTC)
    if eval_time.tzinfo is None:
        eval_time = eval_time.replace(tzinfo=UTC)

    outcome, reasons, violations = evaluate_policy_v1_rules(
        proposal=proposal,
        quote=quote,
        passport=passport,
        merchant=merchant,
        agent=agent,
        approval_record=approval_record,
        historical_daily_spend_minor=historical_daily_spend_minor,
        evaluation_time=eval_time,
    )

    requires_human_approval = (outcome == DecisionOutcome.ESCALATE)
    if outcome == DecisionOutcome.DENY:
        explanation = f"Policy DENIED: {'; '.join(violations)}"
    elif outcome == DecisionOutcome.ESCALATE:
        explanation = f"Policy ESCALATED: requires human approval. Reasons: {', '.join(rc.value for rc in reasons)}"
    else:
        explanation = "Proposal is fully within spending passport policy limits"

    policy_inputs: dict[str, Any] = {
        "proposal_amount_minor": proposal.amount_minor,
        "passport_per_tx_limit_minor": passport.per_tx_limit_minor,
        "passport_available_budget_minor": passport.available_budget_minor,
        "passport_human_approval_threshold_minor": passport.human_approval_threshold_minor,
        "merchant_id": str(merchant.id),
        "merchant_allowlisted": merchant.id in passport.allowed_merchant_ids,
        "merchant_category": merchant.category,
        "historical_daily_spend_minor": historical_daily_spend_minor,
        "evaluated_at": eval_time.isoformat(),
    }

    return AuthorizationDecision(
        tenant_id=proposal.tenant_id,
        correlation_id=proposal.correlation_id,
        payment_intent_id=payment_intent_id or uuid4(),
        proposal_id=proposal.id,
        passport_id=passport.id,
        quote_snapshot_id=quote.id,
        quote_hash=quote.quote_hash,
        policy_version=policy_version,
        outcome=outcome,
        reason_codes=reasons,
        violated_constraints=violations,
        requires_human_approval=requires_human_approval,
        explanation=explanation,
        policy_inputs=policy_inputs,
        decided_at=eval_time,
    )
