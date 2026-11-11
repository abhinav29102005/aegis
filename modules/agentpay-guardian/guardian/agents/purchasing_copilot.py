"""LangGraph purchasing copilot for AgentPay Guardian.

SECURITY INVARIANT:
This agent is strictly non-authoritative. It MAY ONLY:
1. Synthesize user intent and merchant quotes into a PurchaseProposal.
2. Formulate human-readable policy explanations from deterministic AuthorizationDecision records.

It MUST NEVER:
- Grant policy approval or override deterministic rules.
- Reserve, capture, or release financial budgets.
- Initiate, approve, or capture PayPal transactions.
"""

from __future__ import annotations

from typing import Any, Protocol
from uuid import UUID, uuid4

from contracts import (
    AuthorizationDecision,
    DecisionOutcome,
    PurchaseProposal,
)
from guardian.domain.exceptions import GuardianError


class AgentSecurityViolationError(GuardianError, PermissionError):
    """Raised when an autonomous agent attempts an unauthorized financial action."""


class PurchasingCopilotProtocol(Protocol):
    """Interface for purchasing copilots."""

    def build_proposal(
        self,
        *,
        tenant_id: UUID,
        agent_id: UUID,
        passport_id: UUID,
        merchant_id: UUID,
        merchant_name: str,
        merchant_category: str,
        amount_minor: int,
        currency: str,
        item_summary: str,
        line_items: list[dict[str, Any]],
        rationale: str,
        idempotency_key: str,
        correlation_id: UUID | None = None,
    ) -> PurchaseProposal:
        ...

    def explain_decision(
        self,
        proposal: PurchaseProposal,
        decision: AuthorizationDecision,
    ) -> str:
        ...


class PurchasingCopilot:
    """Non-authoritative LangGraph copilot for procurement proposals and explanations."""

    def __init__(self, model_name: str = "purchasing-copilot-v1") -> None:
        self.model_name = model_name

    def build_proposal(
        self,
        *,
        tenant_id: UUID,
        agent_id: UUID,
        passport_id: UUID,
        merchant_id: UUID,
        merchant_name: str,
        merchant_category: str = "SOFTWARE",
        amount_minor: int,
        currency: str = "USD",
        item_summary: str,
        line_items: list[dict[str, Any]] | None = None,
        rationale: str,
        idempotency_key: str,
        correlation_id: UUID | None = None,
    ) -> PurchaseProposal:
        """Construct a validated, non-authoritative PurchaseProposal."""
        return PurchaseProposal(
            id=uuid4(),
            tenant_id=tenant_id,
            correlation_id=correlation_id or uuid4(),
            agent_id=agent_id,
            passport_id=passport_id,
            merchant_id=merchant_id,
            merchant_name=merchant_name,
            merchant_category=merchant_category,
            amount_minor=amount_minor,
            currency=currency.upper(),
            item_summary=item_summary,
            line_items=line_items or [],
            rationale=rationale,
            idempotency_key=idempotency_key,
            proposed_by_model=self.model_name,
        )

    def explain_decision(
        self,
        proposal: PurchaseProposal,
        decision: AuthorizationDecision,
    ) -> str:
        """Translate a deterministic policy decision into a clear explanation."""
        reasons_str = ", ".join(rc.value for rc in decision.reason_codes)
        if decision.outcome == DecisionOutcome.ALLOW:
            return (
                f"Purchase of {proposal.item_summary} ({proposal.amount_minor} {proposal.currency}) "
                f"from {proposal.merchant_name} is ALLOWED under policy {decision.policy_version}. "
                f"Reason: {reasons_str}."
            )
        elif decision.outcome == DecisionOutcome.ESCALATE:
            return (
                f"Purchase of {proposal.item_summary} ({proposal.amount_minor} {proposal.currency}) "
                f"requires human escalation. Reasons: {reasons_str}. "
                f"Details: {decision.explanation}"
            )
        else:
            violations_str = "; ".join(decision.violated_constraints) or "Policy limit exceeded"
            return (
                f"Purchase of {proposal.item_summary} was DENIED. "
                f"Reason: {reasons_str}. Violations: {violations_str}."
            )

    # -------------------------------------------------------------------------
    # Hard Architectural Safety Guards
    # -------------------------------------------------------------------------
    def authorize(self, *args: Any, **kwargs: Any) -> None:
        """Explicitly prohibited: LLM agents cannot authorize spending."""
        raise AgentSecurityViolationError(
            "Agent authorization prohibited: spending authority is strictly reserved "
            "for deterministic policy engines and authenticated human approvers."
        )

    def approve_budget(self, *args: Any, **kwargs: Any) -> None:
        """Explicitly prohibited: LLM agents cannot approve budgets."""
        raise AgentSecurityViolationError(
            "Agent budget approval prohibited: budgets cannot be approved by AI models."
        )

    def capture_payment(self, *args: Any, **kwargs: Any) -> None:
        """Explicitly prohibited: LLM agents cannot invoke payment capture."""
        raise AgentSecurityViolationError(
            "Agent payment capture prohibited: PayPal capture requires deterministic "
            "verified checkout and human or policy approval."
        )
