"""Tests for LangChain / LangGraph and OpenAI agent middleware integrations."""

from __future__ import annotations

import json
from unittest.mock import MagicMock

import pytest
from aegis_sdk.integrations import (
    AegisPurchaseInput,
    AegisSpendingTool,
    OpenAIPurchaseGuard,
    ahandle_openai_purchase_call,
    create_aegis_spending_tool,
    get_openai_purchase_tool_spec,
    handle_openai_purchase_call,
)


def test_openai_tool_spec_structure() -> None:
    spec = get_openai_purchase_tool_spec()
    assert spec["type"] == "function"
    assert spec["function"]["name"] == "request_purchase_authorization"
    params = spec["function"]["parameters"]
    assert "properties" in params
    assert set(params["required"]) == {"merchant_id", "merchant_name", "amount_minor", "item_summary", "rationale"}


def test_handle_openai_purchase_call_sync() -> None:
    mock_client = MagicMock()
    mock_client.submit_purchase_proposal.return_value = {
        "payment_intent": {"id": "pi-123", "state": "CHECKOUT_READY"},
        "decision": {"decision": "APPROVE"},
    }

    raw_args = json.dumps(
        {
            "merchant_id": "m-456",
            "merchant_name": "Cloud Vendor",
            "amount_minor": 1500,
            "item_summary": "Database Tier",
            "rationale": "Scaling DB",
        }
    )

    res = handle_openai_purchase_call(
        mock_client,
        agent_id="agent-001",
        passport_id="passport-001",
        arguments=raw_args,
    )
    assert res["payment_intent"]["state"] == "CHECKOUT_READY"
    mock_client.submit_purchase_proposal.assert_called_once_with(
        agent_id="agent-001",
        passport_id="passport-001",
        merchant_id="m-456",
        merchant_name="Cloud Vendor",
        merchant_category="SOFTWARE",
        amount_minor=1500,
        currency="USD",
        item_summary="Database Tier",
        rationale="Scaling DB",
        idempotency_key=None,
    )


@pytest.mark.asyncio
async def test_handle_openai_purchase_call_async() -> None:
    class AsyncMockClient:
        async def asubmit_purchase_proposal(self, **kwargs):
            return {"payment_intent": {"id": "pi-async-1", "state": "CHECKOUT_READY"}, "kwargs": kwargs}

    client = AsyncMockClient()
    guard = OpenAIPurchaseGuard(client, agent_id="ag-1", passport_id="pass-1")

    res = await guard.aexecute(
        {
            "merchant_id": "m-1",
            "merchant_name": "API Provider",
            "amount_minor": 2000,
            "item_summary": "Monthly plan",
            "rationale": "Productive tasks",
        }
    )
    assert res["payment_intent"]["state"] == "CHECKOUT_READY"
    assert res["kwargs"]["merchant_name"] == "API Provider"


def test_langchain_aegis_spending_tool() -> None:
    mock_client = MagicMock()
    mock_client.submit_purchase_proposal.return_value = {
        "payment_intent": {"id": "pi-langchain-1", "state": "CHECKOUT_READY"}
    }

    tool = create_aegis_spending_tool(
        client=mock_client,
        agent_id="ag-langchain",
        passport_id="pass-langchain",
    )

    assert tool.name == "request_purchase_authorization"
    assert tool.args_schema == AegisPurchaseInput

    res = tool.run(
        {
            "merchant_id": "m-777",
            "merchant_name": "Analytics Co",
            "amount_minor": 4500,
            "item_summary": "Analytics quota",
            "rationale": "Data dashboard queries",
        }
    )
    assert res["payment_intent"]["id"] == "pi-langchain-1"


@pytest.mark.asyncio
async def test_langchain_aegis_spending_tool_async() -> None:
    class AsyncMockClient:
        async def asubmit_purchase_proposal(self, **kwargs):
            return {"payment_intent": {"id": "pi-arun-1", "state": "CHECKOUT_READY"}}

    tool = AegisSpendingTool(
        client=AsyncMockClient(),
        agent_id="ag-async",
        passport_id="pass-async",
    )

    res = await tool.arun(
        {
            "merchant_id": "m-999",
            "merchant_name": "Storage Vendor",
            "amount_minor": 1200,
            "item_summary": "Backup storage",
            "rationale": "Weekly snapshots",
        }
    )
    assert res["payment_intent"]["id"] == "pi-arun-1"
