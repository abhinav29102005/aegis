"""Deterministic spending policy engine for AgentPay Guardian.

Evaluates proposals against SpendingPassport constraints, approval records,
merchant allowlists, category restrictions, and velocity limits.
Delegates canonical 'policy-v1' evaluation to contracts.policy_v1.
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from contracts import (
    AgentIdentity,
    ApprovalRecord,
    AuthorizationDecision,
    Merchant,
    PurchaseProposal,
    QuoteSnapshot,
    SpendingPassport,
)
from contracts.policy_v1 import evaluate_policy_v1


def _utc_now() -> datetime:
    return datetime.now(UTC)


class PolicyEngine:
    """Evaluates spending policy rules against proposals deterministically."""

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
        historical_daily_spend_minor: int | None = None,
        daily_spent_minor: int = 0,
        monthly_spent_minor: int = 0,
        payment_intent_id: UUID | None = None,
        now: datetime | None = None,
    ) -> AuthorizationDecision:
        """Delegate policy evaluation strictly to canonical contracts.policy_v1."""
        eff_daily = historical_daily_spend_minor if historical_daily_spend_minor is not None else daily_spent_minor
        return evaluate_policy_v1(
            proposal=proposal,
            passport=passport,
            merchant=merchant,
            quote=quote,
            agent=agent,
            approval_record=approval_record,
            daily_spent_minor=eff_daily,
            monthly_spent_minor=monthly_spent_minor,
            now=now or _utc_now(),
            correlation_id=proposal.correlation_id,
            policy_version=self.policy_version,
            payment_intent_id=payment_intent_id,
        )


def evaluate_proposal(
    *,
    proposal: PurchaseProposal,
    passport: SpendingPassport,
    merchant: Merchant,
    quote: QuoteSnapshot,
    agent: AgentIdentity | None = None,
    approval_record: ApprovalRecord | None = None,
    historical_daily_spend_minor: int | None = None,
    daily_spent_minor: int = 0,
    monthly_spent_minor: int = 0,
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
        daily_spent_minor=daily_spent_minor,
        monthly_spent_minor=monthly_spent_minor,
        payment_intent_id=payment_intent_id,
        now=now,
    )
