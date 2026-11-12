"""Canonical pure deterministic policy-v1 evaluator for AgentPay Nexus.

Unified evaluator and ISO 4217 currency exponent utilities used identically
by AgentPay Guardian (pre-transaction authorization) and GhostPay
(post-transaction deterministic counterfactual replay).
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import InvalidOperation, ROUND_HALF_UP, Decimal
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
# ISO 4217 Currency Exponents & Decimal Formatters
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


def minor_to_decimal_str(amount_minor: int, currency: str = "USD") -> str:
    """Format integer minor units to standard major decimal string (e.g. 3900 USD -> '39.00', 1500 JPY -> '1500')."""
    exp = get_currency_exponent(currency)
    if exp == 0:
        return str(amount_minor)
    scale = Decimal(10) ** exp
    dec_val = Decimal(amount_minor) / scale
    return f"{dec_val:.{exp}f}"


format_minor_to_major = minor_to_decimal_str


def decimal_str_to_minor(amount_str: str, currency: str = "USD") -> int:
    """Parse major decimal string to integer minor units using exact arithmetic."""
    exp = get_currency_exponent(currency)
    s = amount_str.strip()
    try:
        dec = Decimal(s)
    except (InvalidOperation, ValueError) as exc:
        raise ValueError(f"Invalid decimal amount: {amount_str!r}") from exc
    scale = Decimal(10) ** exp
    scaled = dec * scale
    if scaled != scaled.to_integral_value():
        raise ValueError(
            f"Amount {amount_str!r} exceeds {exp} decimal places for currency {currency.upper()}"
        )
    return int(scaled)


parse_major_to_minor = decimal_str_to_minor


def _normalize_utc(dt: datetime | None) -> datetime:
    if dt is None:
        return datetime.now(UTC)
    return dt.astimezone(UTC) if dt.tzinfo else dt.replace(tzinfo=UTC)


# ---------------------------------------------------------------------------
# Core Policy Evaluation Rules
# ---------------------------------------------------------------------------

def evaluate_policy_v1_rules(
    *,
    proposal: PurchaseProposal,
    passport: SpendingPassport,
    merchant: Merchant,
    quote: QuoteSnapshot | None = None,
    agent: AgentIdentity | None = None,
    approval_record: ApprovalRecord | None = None,
    historical_daily_spend_minor: int = 0,
    daily_spent_minor: int | None = None,
    monthly_spent_minor: int = 0,
    evaluation_time: datetime | None = None,
    now: datetime | None = None,
    check_quote_expiration: bool = True,
) -> tuple[DecisionOutcome, list[DecisionReasonCode], list[str]]:
    """Evaluate canonical 'policy-v1' deterministic rules.

    Returns:
        (outcome, reason_codes, violated_constraints)
    """
    ts = _normalize_utc(evaluation_time or now)
    if quote is not None and evaluation_time is None and now is None:
        ts = _normalize_utc(quote.created_at)

    effective_daily_spend = historical_daily_spend_minor if daily_spent_minor is None else daily_spent_minor

    denials: list[DecisionReasonCode] = []
    escalations: list[DecisionReasonCode] = []
    violations: list[str] = []

    def _add_denial(code: DecisionReasonCode, message: str) -> None:
        if code not in denials:
            denials.append(code)
        violations.append(message)

    def _add_escalation(code: DecisionReasonCode, message: str) -> None:
        if code not in escalations:
            escalations.append(code)
        violations.append(message)

    # 1. Cross-tenant boundary enforcement
    tenant_ids = {proposal.tenant_id, passport.tenant_id, merchant.tenant_id}
    if agent is not None:
        tenant_ids.add(agent.tenant_id)
    if quote is not None:
        tenant_ids.add(quote.tenant_id)
    if len(tenant_ids) > 1:
        _add_denial(
            DecisionReasonCode.DENIED_CROSS_TENANT,
            "Cross-tenant mismatch across proposal, passport, merchant, agent, or quote",
        )

    # 2. Agent status check
    if agent is not None and agent.status.upper() != "ACTIVE":
        _add_denial(
            DecisionReasonCode.DENIED_AGENT_SUSPENDED,
            f"Agent {agent.id} is not ACTIVE (status={agent.status})",
        )

    # 3. Passport status & expiry
    if passport.status == PassportStatus.REVOKED:
        _add_denial(
            DecisionReasonCode.DENIED_PASSPORT_REVOKED,
            "Spending passport is REVOKED",
        )
    elif passport.status == PassportStatus.PAUSED:
        _add_denial(
            DecisionReasonCode.DENIED_PASSPORT_PAUSED,
            "Spending passport is PAUSED",
        )
    elif passport.status == PassportStatus.EXPIRED:
        _add_denial(
            DecisionReasonCode.DENIED_PASSPORT_EXPIRED,
            "Spending passport status is EXPIRED",
        )

    if passport.expires_at <= ts:
        _add_denial(
            DecisionReasonCode.DENIED_PASSPORT_EXPIRED,
            f"Spending passport expired at {passport.expires_at.isoformat()} (evaluated at {ts.isoformat()})",
        )

    # 4. Quote checks (when quote is provided)
    if quote is not None:
        if check_quote_expiration and quote.expires_at <= ts:
            _add_denial(
                DecisionReasonCode.DENIED_QUOTE_EXPIRED,
                f"Quote expired at {quote.expires_at.isoformat()} (evaluated at {ts.isoformat()})",
            )
        if (
            quote.merchant_id != proposal.merchant_id
            or quote.amount_minor != proposal.amount_minor
            or quote.currency.upper() != proposal.currency.upper()
        ):
            _add_denial(
                DecisionReasonCode.DENIED_APPROVAL_MISMATCH,
                "Quote merchant, amount, or currency does not match proposal",
            )
        expected_quote_hash = compute_quote_hash(
            merchant_id=quote.merchant_id,
            amount_minor=quote.amount_minor,
            currency=quote.currency,
            line_items=quote.line_items,
        )
        if quote.quote_hash != expected_quote_hash:
            _add_denial(
                DecisionReasonCode.DENIED_QUOTE_HASH_MISMATCH,
                "Quote hash tampering detected; does not match line-item canonical hash",
            )

    # 5. Currency check
    allowed_currencies = (
        [c.upper() for c in passport.allowed_currencies]
        if passport.allowed_currencies
        else [passport.currency.upper()]
    )
    if proposal.currency.upper() not in allowed_currencies:
        _add_denial(
            DecisionReasonCode.DENIED_CURRENCY_NOT_ALLOWED,
            f"Currency {proposal.currency.upper()} is not in allowed currencies {allowed_currencies}",
        )

    # 6. Budget & velocity limits
    available_minor = max(
        0,
        passport.total_budget_minor - passport.spent_minor - passport.reserved_minor,
    )
    if proposal.amount_minor > available_minor:
        _add_denial(
            DecisionReasonCode.DENIED_EXCEEDS_PASSPORT_BUDGET,
            f"Proposal amount {proposal.amount_minor} exceeds available budget {available_minor}",
        )
    if proposal.amount_minor > passport.per_tx_limit_minor:
        _add_denial(
            DecisionReasonCode.DENIED_EXCEEDS_PER_TX_LIMIT,
            f"Proposal amount {proposal.amount_minor} exceeds per-tx limit {passport.per_tx_limit_minor}",
        )
    if effective_daily_spend + proposal.amount_minor > passport.daily_limit_minor:
        _add_denial(
            DecisionReasonCode.DENIED_EXCEEDS_DAILY_LIMIT,
            f"Daily spend {effective_daily_spend} + {proposal.amount_minor} exceeds daily limit {passport.daily_limit_minor}",
        )
    if (
        passport.monthly_limit_minor is not None
        and monthly_spent_minor + proposal.amount_minor > passport.monthly_limit_minor
    ):
        _add_denial(
            DecisionReasonCode.DENIED_MONTHLY_LIMIT,
            f"Monthly spend {monthly_spent_minor} + {proposal.amount_minor} exceeds monthly limit {passport.monthly_limit_minor}",
        )

    # 7. Strict merchant allowlist (no global merchant.is_allowlisted bypass)
    if passport.allowed_merchant_ids and merchant.id not in passport.allowed_merchant_ids:
        if passport.allow_unknown_merchants:
            _add_escalation(
                DecisionReasonCode.ESCALATED_UNKNOWN_MERCHANT,
                f"Merchant {merchant.id} is not in passport allowed_merchant_ids; human approval required",
            )
        else:
            _add_denial(
                DecisionReasonCode.DENIED_MERCHANT_NOT_ALLOWLISTED,
                f"Merchant {merchant.id} is not in passport allowed_merchant_ids",
            )

    # 8. Category allowlist
    proposal_category = getattr(proposal, "category", None) or proposal.merchant_category
    if passport.allowed_categories:
        allowed_cats = {c.strip().upper() for c in passport.allowed_categories}
        merchant_cat = (merchant.category or "").strip().upper()
        prop_cat = (proposal_category or "").strip().upper()
        if (merchant_cat and merchant_cat not in allowed_cats) or (prop_cat and prop_cat not in allowed_cats):
            _add_denial(
                DecisionReasonCode.DENIED_CATEGORY_NOT_ALLOWED,
                f"Category ({merchant.category}/{proposal_category}) not in allowed_categories {passport.allowed_categories}",
            )

    # 9. Approval Record validation (if provided)
    valid_approval = False
    if approval_record is not None:
        if approval_record.tenant_id != proposal.tenant_id:
            _add_denial(
                DecisionReasonCode.DENIED_CROSS_TENANT,
                "ApprovalRecord tenant does not match proposal tenant",
            )
        elif approval_record.status != ApprovalStatus.APPROVED:
            _add_denial(
                DecisionReasonCode.DENIED_APPROVAL_REJECTED,
                f"ApprovalRecord status is {approval_record.status}",
            )
        elif approval_record.expires_at <= ts:
            _add_denial(
                DecisionReasonCode.DENIED_APPROVAL_EXPIRED,
                f"ApprovalRecord expired at {approval_record.expires_at.isoformat()}",
            )
        elif (
            approval_record.bound_merchant_id != proposal.merchant_id
            or approval_record.bound_amount_minor != proposal.amount_minor
            or approval_record.bound_currency.upper() != proposal.currency.upper()
            or (quote is not None and approval_record.bound_quote_hash != quote.quote_hash)
        ):
            _add_denial(
                DecisionReasonCode.DENIED_APPROVAL_MISMATCH,
                "ApprovalRecord does not bind to current merchant, amount, currency, or quote hash",
            )
        else:
            valid_approval = True

    # 10. Human approval threshold check
    if proposal.amount_minor > passport.approval_threshold_minor:
        if not valid_approval and not denials:
            _add_escalation(
                DecisionReasonCode.ESCALATED_REQUIRES_HUMAN_APPROVAL,
                f"Proposal amount {proposal.amount_minor} exceeds approval threshold {passport.approval_threshold_minor}",
            )

    # 11. Final outcome determination
    if denials:
        return DecisionOutcome.DENY, denials, violations
    if escalations and not valid_approval:
        return DecisionOutcome.ESCALATE, escalations, violations
    return DecisionOutcome.ALLOW, [DecisionReasonCode.OK_WITHIN_POLICY], []


def evaluate_policy_v1(
    proposal: PurchaseProposal,
    passport: SpendingPassport,
    merchant: Merchant,
    quote: QuoteSnapshot | None = None,
    agent: AgentIdentity | None = None,
    approval_record: ApprovalRecord | None = None,
    daily_spent_minor: int = 0,
    historical_daily_spend_minor: int | None = None,
    monthly_spent_minor: int = 0,
    now: datetime | None = None,
    evaluation_time: datetime | None = None,
    correlation_id: UUID | None = None,
    policy_version: str = "policy-v1",
    payment_intent_id: UUID | None = None,
    check_quote_expiration: bool = True,
) -> AuthorizationDecision:
    """Evaluate canonical policy-v1 and return an immutable AuthorizationDecision contract."""
    if policy_version != "policy-v1":
        raise ValueError(f"Unsupported policy_version: {policy_version!r}")

    ts = _normalize_utc(now or evaluation_time)
    if quote is not None and now is None and evaluation_time is None:
        ts = _normalize_utc(quote.created_at)

    corr_id = correlation_id or proposal.correlation_id
    intent_id = payment_intent_id or uuid4()

    eff_daily = historical_daily_spend_minor if historical_daily_spend_minor is not None else daily_spent_minor

    outcome, reasons, violations = evaluate_policy_v1_rules(
        proposal=proposal,
        passport=passport,
        merchant=merchant,
        quote=quote,
        agent=agent,
        approval_record=approval_record,
        historical_daily_spend_minor=eff_daily,
        monthly_spent_minor=monthly_spent_minor,
        evaluation_time=ts,
        check_quote_expiration=check_quote_expiration,
    )

    requires_human_approval = (outcome == DecisionOutcome.ESCALATE)
    if outcome == DecisionOutcome.DENY:
        explanation = f"Policy DENIED: {'; '.join(violations)}"
    elif outcome == DecisionOutcome.ESCALATE:
        explanation = (
            "Policy ESCALATED: requires human approval. Reasons: "
            + ", ".join(rc.value for rc in reasons)
        )
    else:
        explanation = "Proposal is fully within spending passport policy limits."

    quote_snapshot_id = quote.id if quote is not None else proposal.id
    quote_hash = (
        quote.quote_hash
        if quote is not None
        else compute_quote_hash(
            merchant_id=proposal.merchant_id,
            amount_minor=proposal.amount_minor,
            currency=proposal.currency,
            line_items=proposal.line_items,
        )
    )

    allowed_currencies = (
        [c.upper() for c in passport.allowed_currencies]
        if passport.allowed_currencies
        else [passport.currency.upper()]
    )
    merchant_allowlisted = (
        not passport.allowed_merchant_ids
        or merchant.id in passport.allowed_merchant_ids
    )
    proposal_category = getattr(proposal, "category", None) or proposal.merchant_category
    available_minor = max(
        0,
        passport.total_budget_minor - passport.spent_minor - passport.reserved_minor,
    )

    policy_inputs: dict[str, Any] = {
        "policy_version": policy_version,
        "proposal_amount_minor": proposal.amount_minor,
        "proposal_currency": proposal.currency.upper(),
        "passport_currency": passport.currency.upper(),
        "allowed_currencies": allowed_currencies,
        "available_budget_minor": available_minor,
        "per_tx_limit_minor": passport.per_tx_limit_minor,
        "daily_limit_minor": passport.daily_limit_minor,
        "daily_spent_minor": eff_daily,
        "monthly_limit_minor": passport.monthly_limit_minor,
        "monthly_spent_minor": monthly_spent_minor,
        "approval_threshold_minor": passport.approval_threshold_minor,
        "merchant_id": str(merchant.id),
        "merchant_allowlisted": merchant_allowlisted,
        "merchant_category": merchant.category,
        "proposal_category": proposal_category,
        "quote_id": str(quote.id) if quote is not None else None,
        "agent_id": str(agent.id) if agent is not None else None,
        "evaluated_at": ts.isoformat(),
    }

    return AuthorizationDecision(
        tenant_id=proposal.tenant_id,
        correlation_id=corr_id,
        payment_intent_id=intent_id,
        proposal_id=proposal.id,
        passport_id=passport.id,
        quote_snapshot_id=quote_snapshot_id,
        quote_hash=quote_hash,
        policy_version=policy_version,
        outcome=outcome,
        reason_codes=reasons,
        violated_constraints=violations,
        requires_human_approval=requires_human_approval,
        explanation=explanation[:1000],
        policy_inputs=policy_inputs,
        decided_at=ts,
    )
