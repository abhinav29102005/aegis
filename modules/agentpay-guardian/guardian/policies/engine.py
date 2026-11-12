"""Deterministic policy engine for AgentPay Guardian.

Never incorporates LLM reasoning or heuristic prompts in policy decisions.
All checks are deterministic, synchronous, and mathematically verifiable.
Delegates canonical 'policy-v1' evaluation to contracts.policy_v1.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

from contracts import (
    AgentIdentity,
    ApprovalRecord,
    AuthorizationDecision,
    DecisionOutcome,
    DecisionReasonCode,
    Merchant,
    PassportStatus,
    PurchaseProposal,
    QuoteSnapshot,
    SpendingPassport,
)
from contracts.policy_v1 import evaluate_policy_v1


def _utc_now() -> datetime:
    return datetime.now(UTC)


class PolicyEngine:
    """Deterministic policy evaluation engine."""

    def __init__(self, policy_version: str = "policy-v1") -> None:
        self.policy_version = policy_version

    def evaluate(
        self,
        *,
        proposal: PurchaseProposal,
        passport: SpendingPassport,
        merchant: Merchant,
        quote: QuoteSnapshot,
        agent: AgentIdentity | None = None,
        approval_record: ApprovalRecord | None = None,
        historical_daily_spend_minor: int = 0,
        payment_intent_id: UUID | None = None,
        now: datetime | None = None,
    ) -> AuthorizationDecision:
        current_time = now or _utc_now()
        intent_id = payment_intent_id or uuid4()

        if self.policy_version == "policy-v1":
            return evaluate_policy_v1(
                proposal=proposal,
                passport=passport,
                merchant=merchant,
                quote=quote,
                agent=agent,
                approval_record=approval_record,
                historical_daily_spend_minor=historical_daily_spend_minor,
                payment_intent_id=intent_id,
                evaluation_time=current_time,
                policy_version=self.policy_version,
            )

        # Fallback evaluation for legacy / alternative policy versions
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
                f"Cross-tenant access attempted: proposal={proposal.tenant_id}, "
                f"passport={passport.tenant_id}, merchant={merchant.tenant_id}"
            )

        # 2. Currency check
        if proposal.currency.upper() != passport.currency.upper() or proposal.currency.upper() != quote.currency.upper():
            denials.append(DecisionReasonCode.DENIED_CATEGORY_NOT_ALLOWED)
            violations.append(
                f"Currency mismatch: proposal={proposal.currency}, "
                f"passport={passport.currency}, quote={quote.currency}"
            )

        # 3. Passport status check
        if passport.status == PassportStatus.EXPIRED:
            denials.append(DecisionReasonCode.DENIED_PASSPORT_EXPIRED)
            violations.append("Spending passport is in EXPIRED status")
        elif passport.status in (PassportStatus.REVOKED, PassportStatus.PAUSED):
            denials.append(DecisionReasonCode.DENIED_PASSPORT_REVOKED)
            violations.append(f"Spending passport is in {passport.status.value} status")

        # 4. Passport expiration timestamp
        if passport.expires_at < current_time:
            if DecisionReasonCode.DENIED_PASSPORT_EXPIRED not in denials:
                denials.append(DecisionReasonCode.DENIED_PASSPORT_EXPIRED)
            violations.append(
                f"Passport expired at {passport.expires_at.isoformat()} (now: {current_time.isoformat()})"
            )

        # 5. Quote expiration check
        if quote.expires_at < current_time:
            denials.append(DecisionReasonCode.DENIED_QUOTE_EXPIRED)
            violations.append(
                f"Quote expired at {quote.expires_at.isoformat()} (now: {current_time.isoformat()})"
            )

        # 6. Per-transaction limit check
        if proposal.amount_minor > passport.per_tx_limit_minor:
            denials.append(DecisionReasonCode.DENIED_EXCEEDS_PER_TX_LIMIT)
            violations.append(
                f"Proposal amount ({proposal.amount_minor}) exceeds per-tx limit ({passport.per_tx_limit_minor})"
            )

        # 7. Available budget check
        if proposal.amount_minor > passport.available_budget_minor:
            denials.append(DecisionReasonCode.DENIED_EXCEEDS_PASSPORT_BUDGET)
            violations.append(
                f"Proposal amount ({proposal.amount_minor}) exceeds available budget ({passport.available_budget_minor})"
            )

        # 8. Merchant allowlist check
        is_merchant_allowed = (
            merchant.id in passport.allowed_merchant_ids
            or merchant.is_allowlisted
        )
        if not is_merchant_allowed:
            if not passport.allow_unknown_merchants:
                denials.append(DecisionReasonCode.DENIED_MERCHANT_NOT_ALLOWLISTED)
                violations.append(f"Merchant '{merchant.name}' ({merchant.id}) is not allowlisted")
            else:
                escalations.append(DecisionReasonCode.ESCALATED_UNKNOWN_MERCHANT)

        # 9. Allowed category check
        if passport.allowed_categories and merchant.category not in passport.allowed_categories:
            denials.append(DecisionReasonCode.DENIED_CATEGORY_NOT_ALLOWED)
            violations.append(
                f"Merchant category '{merchant.category}' not in allowed categories: {passport.allowed_categories}"
            )

        # 10. Human approval threshold check
        if proposal.amount_minor > passport.human_approval_threshold_minor:
            escalations.append(DecisionReasonCode.ESCALATED_REQUIRES_HUMAN_APPROVAL)

        # Determine outcome
        policy_inputs: dict[str, Any] = {
            "proposal_amount_minor": proposal.amount_minor,
            "passport_per_tx_limit_minor": passport.per_tx_limit_minor,
            "passport_available_budget_minor": passport.available_budget_minor,
            "passport_human_approval_threshold_minor": passport.human_approval_threshold_minor,
            "merchant_id": str(merchant.id),
            "merchant_allowlisted": is_merchant_allowed,
            "merchant_category": merchant.category,
            "evaluated_at": current_time.isoformat(),
        }

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
                f"Policy ESCALATED: requires human approval. Reasons: "
                f"{', '.join(rc.value for rc in escalations)}"
            )
        else:
            outcome = DecisionOutcome.ALLOW
            reason_codes = [DecisionReasonCode.OK_WITHIN_POLICY]
            requires_human_approval = False
            explanation = "Proposal is fully within spending passport policy limits"

        return AuthorizationDecision(
            tenant_id=proposal.tenant_id,
            correlation_id=proposal.correlation_id,
            payment_intent_id=intent_id,
            proposal_id=proposal.id,
            passport_id=passport.id,
            quote_snapshot_id=quote.id,
            quote_hash=quote.quote_hash,
            policy_version=self.policy_version,
            outcome=outcome,
            reason_codes=reason_codes,
            violated_constraints=violations,
            requires_human_approval=requires_human_approval,
            explanation=explanation,
            policy_inputs=policy_inputs,
            decided_at=current_time,
        )


def evaluate_proposal(
    *,
    proposal: PurchaseProposal,
    passport: SpendingPassport,
    merchant: Merchant,
    quote: QuoteSnapshot,
    agent: AgentIdentity | None = None,
    approval_record: ApprovalRecord | None = None,
    historical_daily_spend_minor: int = 0,
    payment_intent_id: UUID | None = None,
    now: datetime | None = None,
    policy_version: str = "policy-v1",
) -> AuthorizationDecision:
    """Convenience function evaluating a proposal against policy."""
    engine = PolicyEngine(policy_version=policy_version)
    return engine.evaluate(
        proposal=proposal,
        passport=passport,
        merchant=merchant,
        quote=quote,
        agent=agent,
        approval_record=approval_record,
        historical_daily_spend_minor=historical_daily_spend_minor,
        payment_intent_id=payment_intent_id,
        now=now,
    )
