"""OpenAI tool/function-calling integration for AEGIS spending governance."""

from __future__ import annotations

import asyncio
import json
from typing import Any
from uuid import UUID


def get_openai_purchase_tool_spec(name: str = "request_purchase_authorization") -> dict[str, Any]:
    """Return canonical OpenAI Tool JSON schema specification for AEGIS purchase authorization."""
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": (
                "Submit a deterministic purchase proposal to AEGIS Guardian for policy evaluation "
                "and budget reservation. Returns state (CHECKOUT_READY, AWAITING_APPROVAL, DENIED). "
                "The agent is never given direct payment credentials."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "merchant_id": {
                        "type": "string",
                        "description": "UUID of the merchant / vendor.",
                    },
                    "merchant_name": {
                        "type": "string",
                        "description": "Display name of the merchant.",
                    },
                    "merchant_category": {
                        "type": "string",
                        "description": "Category e.g. SOFTWARE, HARDWARE, CLOUD_INFRASTRUCTURE.",
                        "default": "SOFTWARE",
                    },
                    "amount_minor": {
                        "type": "integer",
                        "description": "Amount in minor currency units (e.g. 1900 for $19.00 USD).",
                    },
                    "currency": {
                        "type": "string",
                        "description": "ISO-4217 three-letter currency code (e.g. USD).",
                        "default": "USD",
                    },
                    "item_summary": {
                        "type": "string",
                        "description": "Brief description of the items or service purchased.",
                    },
                    "rationale": {
                        "type": "string",
                        "description": "Reasoning why this purchase is necessary for the agent task.",
                    },
                    "idempotency_key": {
                        "type": "string",
                        "description": "Optional client-generated idempotency key.",
                    },
                },
                "required": ["merchant_id", "merchant_name", "amount_minor", "item_summary", "rationale"],
            },
        },
    }


def _parse_arguments(arguments: dict[str, Any] | str) -> dict[str, Any]:
    if isinstance(arguments, str):
        try:
            return json.loads(arguments)
        except Exception as exc:
            raise ValueError(f"Failed to parse tool call arguments as JSON: {exc}") from exc
    return dict(arguments)


def handle_openai_purchase_call(
    client: Any,
    agent_id: str | UUID,
    passport_id: str | UUID,
    arguments: dict[str, Any] | str,
) -> dict[str, Any]:
    """Execute a purchase authorization call from OpenAI function arguments synchronously."""
    args = _parse_arguments(arguments)
    return client.submit_purchase_proposal(
        agent_id=agent_id,
        passport_id=passport_id,
        merchant_id=args["merchant_id"],
        merchant_name=args["merchant_name"],
        merchant_category=args.get("merchant_category", "SOFTWARE"),
        amount_minor=int(args["amount_minor"]),
        currency=args.get("currency", "USD"),
        item_summary=args["item_summary"],
        rationale=args["rationale"],
        idempotency_key=args.get("idempotency_key"),
    )


async def ahandle_openai_purchase_call(
    client: Any,
    agent_id: str | UUID,
    passport_id: str | UUID,
    arguments: dict[str, Any] | str,
) -> dict[str, Any]:
    """Execute a purchase authorization call from OpenAI function arguments asynchronously."""
    args = _parse_arguments(arguments)
    if hasattr(client, "asubmit_purchase_proposal"):
        return await client.asubmit_purchase_proposal(
            agent_id=agent_id,
            passport_id=passport_id,
            merchant_id=args["merchant_id"],
            merchant_name=args["merchant_name"],
            merchant_category=args.get("merchant_category", "SOFTWARE"),
            amount_minor=int(args["amount_minor"]),
            currency=args.get("currency", "USD"),
            item_summary=args["item_summary"],
            rationale=args["rationale"],
            idempotency_key=args.get("idempotency_key"),
        )
    return await asyncio.to_thread(handle_openai_purchase_call, client, agent_id, passport_id, args)


class OpenAIPurchaseGuard:
    """Wrapper that binds an AEGIS client with agent credentials for OpenAI tool calling."""

    def __init__(
        self,
        client: Any,
        agent_id: str | UUID,
        passport_id: str | UUID,
        tool_name: str = "request_purchase_authorization",
    ) -> None:
        self.client = client
        self.agent_id = str(agent_id)
        self.passport_id = str(passport_id)
        self.tool_name = tool_name
        self.tool_spec = get_openai_purchase_tool_spec(name=tool_name)

    def execute(self, arguments: dict[str, Any] | str) -> dict[str, Any]:
        """Execute the tool call synchronously."""
        return handle_openai_purchase_call(self.client, self.agent_id, self.passport_id, arguments)

    async def aexecute(self, arguments: dict[str, Any] | str) -> dict[str, Any]:
        """Execute the tool call asynchronously."""
        return await ahandle_openai_purchase_call(self.client, self.agent_id, self.passport_id, arguments)
