"""Tests for AEGIS Model Context Protocol (MCP) Server."""

from __future__ import annotations

import json
from uuid import uuid4

import pytest
from contracts import (
    PassportStatus,
    SpendingPassport,
)
from contracts.fixtures import (
    AGENT_PROCUREMENT_ID,
    MERCHANT_SANDBOX_CLOUD_ID,
    TENANT_ALPHA_ID,
)
from contracts.models import utc_now

from guardian.domain.service import GuardianService
from guardian.mcp_server import AegisMCPServer
from guardian.passports.service import PassportService
from tests.conftest import InMemoryLedgerRepository, MockPayPalClient


@pytest.fixture
def ledger_repo() -> InMemoryLedgerRepository:
    return InMemoryLedgerRepository()


@pytest.fixture
def paypal_client() -> MockPayPalClient:
    return MockPayPalClient()


@pytest.fixture
def passport_svc(ledger_repo: InMemoryLedgerRepository) -> PassportService:
    svc = PassportService(repo=ledger_repo)
    now = utc_now()
    passport = SpendingPassport(
        id=uuid4(),
        tenant_id=TENANT_ALPHA_ID,
        agent_id=AGENT_PROCUREMENT_ID,
        status=PassportStatus.ACTIVE,
        per_tx_limit_minor=5000,
        daily_limit_minor=20000,
        total_budget_minor=100000,
        currency="USD",
        allowed_merchant_ids=[MERCHANT_SANDBOX_CLOUD_ID],
        allowed_categories=["cloud_infrastructure"],
        expires_at=now.replace(year=now.year + 1),
        created_at=now,
    )
    svc.create_passport(passport)
    return svc


@pytest.fixture
def mcp_server(
    ledger_repo: InMemoryLedgerRepository,
    passport_svc: PassportService,
    paypal_client: MockPayPalClient,
) -> AegisMCPServer:
    guardian_svc = GuardianService(repo=ledger_repo, passport_service=passport_svc, paypal_client=paypal_client)
    return AegisMCPServer(guardian_service=guardian_svc, passport_service=passport_svc)


def test_mcp_initialize(mcp_server: AegisMCPServer) -> None:
    req = {
        "jsonrpc": "2.0",
        "id": "1",
        "method": "initialize",
        "params": {},
    }
    resp = mcp_server.handle_request(req)
    assert resp["jsonrpc"] == "2.0"
    assert resp["id"] == "1"
    assert resp["result"]["serverInfo"]["name"] == "aegis-guardian-mcp"


def test_mcp_tools_list(mcp_server: AegisMCPServer) -> None:
    req = {
        "jsonrpc": "2.0",
        "id": "2",
        "method": "tools/list",
        "params": {},
    }
    resp = mcp_server.handle_request(req)
    assert "tools" in resp["result"]
    tool_names = [t["name"] for t in resp["result"]["tools"]]
    assert "check_policy" in tool_names
    assert "propose_payment" in tool_names
    assert "get_passport_budget" in tool_names
    assert "list_audit_timeline" in tool_names


def test_mcp_tool_check_policy_allow_and_deny(mcp_server: AegisMCPServer, passport_svc: PassportService) -> None:
    passports = passport_svc.list_passports(TENANT_ALPHA_ID)
    passport = passports[0]

    # 1. Within policy -> ALLOW
    req_allow = {
        "jsonrpc": "2.0",
        "id": "3",
        "method": "tools/call",
        "params": {
            "name": "check_policy",
            "arguments": {
                "tenant_id": str(TENANT_ALPHA_ID),
                "spending_passport_id": str(passport.id),
                "merchant_id": MERCHANT_SANDBOX_CLOUD_ID,
                "amount_minor": 3500,
                "currency": "USD",
            },
        },
    }
    resp = mcp_server.handle_request(req_allow)
    data = json.loads(resp["result"]["content"][0]["text"])
    assert data["outcome"] == "ALLOW"
    assert data["reason_code"] == "OK_WITHIN_POLICY"

    # 2. Exceeds limit -> DENY
    req_deny = {
        "jsonrpc": "2.0",
        "id": "4",
        "method": "tools/call",
        "params": {
            "name": "check_policy",
            "arguments": {
                "tenant_id": str(TENANT_ALPHA_ID),
                "spending_passport_id": str(passport.id),
                "merchant_id": MERCHANT_SANDBOX_CLOUD_ID,
                "amount_minor": 10000,  # exceeds 5000 per tx
                "currency": "USD",
            },
        },
    }
    resp_deny = mcp_server.handle_request(req_deny)
    data_deny = json.loads(resp_deny["result"]["content"][0]["text"])
    assert data_deny["outcome"] == "DENY"
    assert "DENIED" in data_deny["reason_code"]


def test_mcp_tool_propose_payment_non_authoritative(mcp_server: AegisMCPServer) -> None:
    req = {
        "jsonrpc": "2.0",
        "id": "5",
        "method": "tools/call",
        "params": {
            "name": "propose_payment",
            "arguments": {
                "tenant_id": str(TENANT_ALPHA_ID),
                "agent_id": str(AGENT_PROCUREMENT_ID),
                "merchant_id": MERCHANT_SANDBOX_CLOUD_ID,
                "amount_minor": 2500,
                "currency": "USD",
                "purpose": "Procure staging servers",
                "line_items": [{"description": "Compute node", "amount_minor": 2500}],
            },
        },
    }
    resp = mcp_server.handle_request(req)
    data = json.loads(resp["result"]["content"][0]["text"])
    assert data["status"] == "PROPOSED"
    assert data["non_authoritative"] is True
    assert "quote_hash" in data


def test_mcp_tool_get_passport_budget(mcp_server: AegisMCPServer, passport_svc: PassportService) -> None:
    passports = passport_svc.list_passports(TENANT_ALPHA_ID)
    passport = passports[0]

    req = {
        "jsonrpc": "2.0",
        "id": "6",
        "method": "tools/call",
        "params": {
            "name": "get_passport_budget",
            "arguments": {
                "tenant_id": str(TENANT_ALPHA_ID),
                "passport_id": str(passport.id),
            },
        },
    }
    resp = mcp_server.handle_request(req)
    data = json.loads(resp["result"]["content"][0]["text"])
    assert data["passport_id"] == str(passport.id)
    assert data["per_tx_limit_minor"] == 5000
    assert data["daily_limit_minor"] == 20000
