"""Deterministic policy engine for AgentPay Guardian.

Never incorporates LLM reasoning or heuristic prompts in policy decisions.
All checks are deterministic, synchronous, and mathematically verifiable.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from contracts import (
    AgentIdentity,
    AuthorizationDecision,
    Merchant,
    PurchaseProposal,
    QuoteSnapshot,
    SpendingPassport,
    evaluate_policy_v1,
)


class PolicyEngine:
    """Deterministic policy evaluation engine."""

    def __init__(self, policy_version: str = "policy-v1") -> None:
        if policy_version != "policy-v1":
            raise ValueError(f"Unsupported policy_version: {policy_version!r}")
        self.policy_version = policy_version

    def evaluate(
        self,
        *,
        proposal: PurchaseProposal,
        passport: SpendingPassport,
        merchant: Merchant,
        quote: QuoteSnapshot,
        agent: AgentIdentity | None = None,
        daily_spent_minor: int = 0,
        monthly_spent_minor: int = 0,
        payment_intent_id: UUID | None = None,
        now: datetime | None = None,
    ) -> AuthorizationDecision:
        """Delegate policy-v1 evaluation strictly to canonical contracts.policy_v1."""
        return evaluate_policy_v1(
            proposal=proposal,
            passport=passport,
            merchant=merchant,
            quote=quote,
            agent=agent,
            daily_spent_minor=daily_spent_minor,
            monthly_spent_minor=monthly_spent_minor,
            now=now,
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
        daily_spent_minor=daily_spent_minor,
        monthly_spent_minor=monthly_spent_minor,
        payment_intent_id=payment_intent_id,
        now=now,
    )

