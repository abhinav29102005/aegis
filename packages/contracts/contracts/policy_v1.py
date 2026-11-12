"""Canonical pure deterministic policy-v1 evaluator for AgentPay Nexus."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

from contracts.enums import (
    DecisionOutcome,
    DecisionReasonCode,
    PassportStatus,
)
from contracts.hashing import compute_quote_hash
from contracts.models import (
    AgentIdentity,
    AuthorizationDecision,
    Merchant,
    PurchaseProposal,
    QuoteSnapshot,
    SpendingPassport,
)


def _normalize_utc(dt: datetime | None) -> datetime:
    if dt is None:
        return datetime.now(UTC)
    return dt.astimezone(UTC) if dt.tzinfo else dt.replace(tzinfo=UTC)


def evaluate_policy_v1(
    proposal: PurchaseProposal,
    passport: SpendingPassport,
    merchant: Merchant,
    quote: QuoteSnapshot | None = None,
    agent: AgentIdentity | None = None,
    daily_spent_minor: int = 0,
    monthly_spent_minor: int = 0,
    now: datetime | None = None,
    correlation_id: UUID | None = None,
    policy_version: str = "policy-v1",
    payment_intent_id: UUID | None = None,
) -> AuthorizationDecision:
    """Evaluate a purchase proposal deterministically under canonical policy-v1."""
    if policy_version != "policy-v1":
        raise ValueError(f"Unsupported policy_version: {policy_version!r}")

    ts = _normalize_utc(now)
    corr_id = correlation_id or proposal.correlation_id
    intent_id = payment_intent_id or uuid4()

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
        if quote.expires_at <= ts:
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
    if daily_spent_minor + proposal.amount_minor > passport.daily_limit_minor:
        _add_denial(
            DecisionReasonCode.DENIED_EXCEEDS_DAILY_LIMIT,
            f"Daily spend {daily_spent_minor} + {proposal.amount_minor} exceeds daily limit {passport.daily_limit_minor}",
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
    merchant_allowlisted = (
        not passport.allowed_merchant_ids
        or merchant.id in passport.allowed_merchant_ids
    )
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
        if merchant_cat not in allowed_cats or (prop_cat and prop_cat not in allowed_cats):
            _add_denial(
                DecisionReasonCode.DENIED_CATEGORY_NOT_ALLOWED,
                f"Category ({merchant.category}/{proposal_category}) not in allowed_categories {passport.allowed_categories}",
            )

    # 9. Human approval threshold (strict >)
    if proposal.amount_minor > passport.approval_threshold_minor:
        _add_escalation(
            DecisionReasonCode.ESCALATED_REQUIRES_HUMAN_APPROVAL,
            f"Proposal amount {proposal.amount_minor} exceeds approval threshold {passport.approval_threshold_minor}",
        )

    # 10. Resolve final deterministic outcome
    if denials:
        outcome = DecisionOutcome.DENY
        reason_codes = denials
        requires_human_approval = False
        explanation = f"Policy DENIED: {'; '.join(violations)}"
    elif escalations:
        outcome = DecisionOutcome.ESCALATE
        reason_codes = escalations
        requires_human_approval = True
        explanation = (
            "Policy ESCALATED: requires human approval. Reasons: "
            + ", ".join(rc.value for rc in escalations)
        )
    else:
        outcome = DecisionOutcome.ALLOW
        reason_codes = [DecisionReasonCode.OK_WITHIN_POLICY]
        requires_human_approval = False
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

    policy_inputs: dict[str, Any] = {
        "policy_version": policy_version,
        "proposal_amount_minor": proposal.amount_minor,
        "proposal_currency": proposal.currency.upper(),
        "passport_currency": passport.currency.upper(),
        "allowed_currencies": allowed_currencies,
        "available_budget_minor": available_minor,
        "per_tx_limit_minor": passport.per_tx_limit_minor,
        "daily_limit_minor": passport.daily_limit_minor,
        "daily_spent_minor": daily_spent_minor,
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
        reason_codes=reason_codes,
        violated_constraints=violations,
        requires_human_approval=requires_human_approval,
        explanation=explanation[:1000],
        policy_inputs=policy_inputs,
        decided_at=ts,
    )
