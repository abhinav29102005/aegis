"""LangChain and LangGraph tool wrapper for non-privileged AEGIS spending authorization."""

from __future__ import annotations

import asyncio
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field

try:
    from langchain_core.tools import BaseTool
except ImportError:  # pragma: no cover
    # Minimal stub if langchain_core is not installed in the runtime environment
    class BaseTool:  # type: ignore[no-redef]
        name: str = ""
        description: str = ""
        args_schema: type[BaseModel] | None = None

        def __init__(self, **kwargs: Any) -> None:
            for k, v in kwargs.items():
                setattr(self, k, v)


class AegisPurchaseInput(BaseModel):
    """Schema for AI agent purchase authorization proposals."""

    merchant_id: str = Field(description="UUID of the merchant / vendor")
    merchant_name: str = Field(description="Display name of the merchant")
    amount_minor: int = Field(description="Total purchase amount in minor currency units (e.g. 1900 for $19.00)")
    item_summary: str = Field(description="Human-readable summary of items or services requested")
    rationale: str = Field(description="Detailed agent reasoning and goal justification for the spend")
    merchant_category: str = Field(default="SOFTWARE", description="Merchant category (e.g. SOFTWARE, CLOUD_INFRASTRUCTURE)")
    currency: str = Field(default="USD", description="ISO-4217 3-letter currency code")
    idempotency_key: str | None = Field(default=None, description="Optional unique idempotency token")


class AegisSpendingTool(BaseTool):
    """LangChain / LangGraph purchasing guard tool.

    Allows AI purchasing agents to submit proposals to AEGIS Guardian using restricted
    AGENT_SERVICE credentials. Prevents direct PayPal API access, halts unauthorized spend,
    and returns deterministic policy verdicts.
    """

    name: str = "request_purchase_authorization"
    description: str = (
        "Submit a deterministic purchasing proposal to AEGIS Guardian. "
        "Evaluates spending policy, daily budget, per-transaction limits, and merchant allowlists. "
        "Returns whether the spend is CHECKOUT_READY, AWAITING_APPROVAL, or DENIED without granting "
        "raw payment credentials."
    )
    args_schema: type[BaseModel] = AegisPurchaseInput

    client: Any = Field(default=None, exclude=True)
    agent_id: str = Field(default="", description="The agent's registered ID in AEGIS")
    passport_id: str = Field(default="", description="The spending passport assigned to this agent")

    def __init__(
        self,
        client: Any,
        agent_id: str | UUID,
        passport_id: str | UUID,
        **kwargs: Any,
    ) -> None:
        super().__init__(
            client=client,
            agent_id=str(agent_id),
            passport_id=str(passport_id),
            **kwargs,
        )

    def _run(
        self,
        merchant_id: str,
        merchant_name: str,
        amount_minor: int,
        item_summary: str,
        rationale: str,
        merchant_category: str = "SOFTWARE",
        currency: str = "USD",
        idempotency_key: str | None = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        """Execute authorization request synchronously."""
        # If client has sync method submit_purchase_proposal
        if hasattr(self.client, "submit_purchase_proposal"):
            res = self.client.submit_purchase_proposal(
                agent_id=self.agent_id,
                passport_id=self.passport_id,
                merchant_id=merchant_id,
                merchant_name=merchant_name,
                merchant_category=merchant_category,
                amount_minor=amount_minor,
                currency=currency,
                item_summary=item_summary,
                rationale=rationale,
                idempotency_key=idempotency_key,
            )
            return res
        raise RuntimeError("Provided client does not implement submit_purchase_proposal")

    async def _arun(
        self,
        merchant_id: str,
        merchant_name: str,
        amount_minor: int,
        item_summary: str,
        rationale: str,
        merchant_category: str = "SOFTWARE",
        currency: str = "USD",
        idempotency_key: str | None = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        """Execute authorization request asynchronously."""
        if hasattr(self.client, "asubmit_purchase_proposal"):
            return await self.client.asubmit_purchase_proposal(
                agent_id=self.agent_id,
                passport_id=self.passport_id,
                merchant_id=merchant_id,
                merchant_name=merchant_name,
                merchant_category=merchant_category,
                amount_minor=amount_minor,
                currency=currency,
                item_summary=item_summary,
                rationale=rationale,
                idempotency_key=idempotency_key,
            )
        # Fall back to thread executor for sync client in async environment
        return await asyncio.to_thread(
            self._run,
            merchant_id=merchant_id,
            merchant_name=merchant_name,
            amount_minor=amount_minor,
            item_summary=item_summary,
            rationale=rationale,
            merchant_category=merchant_category,
            currency=currency,
            idempotency_key=idempotency_key,
            **kwargs,
        )


def create_aegis_spending_tool(
    client: Any,
    agent_id: str | UUID,
    passport_id: str | UUID,
    tool_name: str = "request_purchase_authorization",
) -> AegisSpendingTool:
    """Convenience factory for AegisSpendingTool."""
    return AegisSpendingTool(
        client=client,
        agent_id=agent_id,
        passport_id=passport_id,
        name=tool_name,
    )
