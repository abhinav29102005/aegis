"""AEGIS Model Context Protocol (MCP) JSON-RPC 2.0 Server for AgentPay Guardian.

Exposes strictly governed, tenant-isolated tools over standard MCP JSON-RPC 2.0:
- `check_policy`: Read-only deterministic PolicyEngine evaluation (never reserves/captures).
- `propose_payment`: Submits a sanitized PurchaseProposal through GuardianService (never bypasses policy).
- `get_passport_budget`: Read-only SpendingPassport budget and constraint lookup.
- `list_audit_timeline`: Read-only tenant-scoped FinancialEvent audit timeline.

SECURITY INVARIANT:
Every tool invocation requires a verified AuthContext, enforces RBAC Permission checks,
derives tenant_id strictly from AuthContext, and NEVER exposes budget approval, policy
override, or PayPal capture capabilities.
"""

from __future__ import annotations

import inspect
import json
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

from contracts import (
    AuthorizationDecision,
    PaymentIntent,
    PurchaseProposal,
    QuoteSnapshot,
    compute_quote_hash,
)
from fastapi import APIRouter
from pydantic import BaseModel, ConfigDict, Field, ValidationError
from security import (
    AuthContext,
    AuthorizationError,
    Permission,
    TenantIsolationError,
    assert_same_tenant,
)

from guardian.agents.purchasing_copilot import PurchasingCopilot
from guardian.domain.exceptions import GuardianError, PolicyDeniedError
from guardian.domain.service import GuardianService
from guardian.policies.engine import PolicyEngine

MCP_PROTOCOL_VERSION = "2024-11-05"
MCP_SERVER_NAME = "aegis-guardian-mcp"
MCP_SERVER_VERSION = "1.0.0"

# Standard JSON-RPC 2.0 error codes + domain security codes
JSONRPC_PARSE_ERROR = -32700
JSONRPC_INVALID_REQUEST = -32600
JSONRPC_METHOD_NOT_FOUND = -32601
JSONRPC_INVALID_PARAMS = -32602
JSONRPC_INTERNAL_ERROR = -32603
MCP_UNAUTHORIZED = -32001
MCP_TENANT_FORBIDDEN = -32003


class _CheckPolicyArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tenant_id: UUID | None = None
    agent_id: UUID
    passport_id: UUID
    merchant_id: UUID
    amount_minor: int = Field(gt=0)
    currency: str = Field(default="USD", min_length=3, max_length=3)
    merchant_category: str = Field(default="SOFTWARE", max_length=64)
    item_summary: str = Field(default="Policy pre-check", min_length=1, max_length=500)
    line_items: list[dict[str, Any]] = Field(default_factory=list)


class _ProposePaymentArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tenant_id: UUID | None = None
    agent_id: UUID
    passport_id: UUID
    merchant_id: UUID
    merchant_name: str = Field(min_length=1, max_length=160)
    merchant_category: str = Field(default="SOFTWARE", max_length=64)
    amount_minor: int = Field(gt=0)
    currency: str = Field(default="USD", min_length=3, max_length=3)
    item_summary: str = Field(min_length=1, max_length=500)
    line_items: list[dict[str, Any]] = Field(default_factory=list)
    rationale: str = Field(min_length=1, max_length=2000)
    idempotency_key: str = Field(min_length=1, max_length=128)
    correlation_id: UUID | None = None
    quote_ttl_minutes: int = Field(default=15, ge=1, le=60)


class _GetPassportBudgetArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tenant_id: UUID | None = None
    passport_id: UUID


class _ListAuditTimelineArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tenant_id: UUID | None = None
    payment_intent_id: UUID | None = None
    correlation_id: UUID | None = None
    limit: int = Field(default=50, ge=1, le=200)
    offset: int = Field(default=0, ge=0)


_TOOL_DEFINITIONS: tuple[dict[str, Any], ...] = (
    {
        "name": "check_policy",
        "description": (
            "Evaluate deterministic Guardian policy rules for a prospective purchase "
            "without creating an intent or reserving budget."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "agent_id": {"type": "string", "format": "uuid"},
                "passport_id": {"type": "string", "format": "uuid"},
                "merchant_id": {"type": "string", "format": "uuid"},
                "amount_minor": {"type": "integer", "minimum": 1},
                "currency": {"type": "string", "minLength": 3, "maxLength": 3, "default": "USD"},
                "merchant_category": {"type": "string", "default": "SOFTWARE"},
                "item_summary": {"type": "string", "default": "Policy pre-check"},
                "line_items": {"type": "array", "items": {"type": "object"}},
            },
            "required": ["agent_id", "passport_id", "merchant_id", "amount_minor"],
            "additionalProperties": False,
        },
    },
    {
        "name": "propose_payment",
        "description": (
            "Submit a non-authoritative purchase proposal through GuardianService's "
            "deterministic policy engine and state machine."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "agent_id": {"type": "string", "format": "uuid"},
                "passport_id": {"type": "string", "format": "uuid"},
                "merchant_id": {"type": "string", "format": "uuid"},
                "merchant_name": {"type": "string"},
                "merchant_category": {"type": "string", "default": "SOFTWARE"},
                "amount_minor": {"type": "integer", "minimum": 1},
                "currency": {"type": "string", "minLength": 3, "maxLength": 3, "default": "USD"},
                "item_summary": {"type": "string"},
                "line_items": {"type": "array", "items": {"type": "object"}},
                "rationale": {"type": "string"},
                "idempotency_key": {"type": "string"},
                "correlation_id": {"type": "string", "format": "uuid"},
                "quote_ttl_minutes": {"type": "integer", "minimum": 1, "maximum": 60, "default": 15},
            },
            "required": [
                "agent_id",
                "passport_id",
                "merchant_id",
                "merchant_name",
                "amount_minor",
                "item_summary",
                "rationale",
                "idempotency_key",
            ],
            "additionalProperties": False,
        },
    },
    {
        "name": "get_passport_budget",
        "description": "Retrieve read-only budget balances and policy thresholds for a SpendingPassport.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "passport_id": {"type": "string", "format": "uuid"},
            },
            "required": ["passport_id"],
            "additionalProperties": False,
        },
    },
    {
        "name": "list_audit_timeline",
        "description": "List tenant-scoped hash-chained FinancialEvent audit timeline entries.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "payment_intent_id": {"type": "string", "format": "uuid"},
                "correlation_id": {"type": "string", "format": "uuid"},
                "limit": {"type": "integer", "minimum": 1, "maximum": 200, "default": 50},
                "offset": {"type": "integer", "minimum": 0, "default": 0},
            },
            "additionalProperties": False,
        },
    },
)


def _jsonrpc_ok(req_id: Any, result: dict[str, Any]) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": req_id, "result": result}


def _jsonrpc_error(
    req_id: Any,
    code: int,
    message: str,
    *,
    data: Any | None = None,
) -> dict[str, Any]:
    error: dict[str, Any] = {"code": code, "message": message}
    if data is not None:
        error["data"] = data
    return {"jsonrpc": "2.0", "id": req_id, "error": error}


def _tool_result(payload: dict[str, Any], *, is_error: bool = False) -> dict[str, Any]:
    return {
        "content": [{"type": "text", "text": json.dumps(payload, sort_keys=True, default=str)}],
        "structuredContent": payload,
        "isError": is_error,
    }


def _require_auth(auth: AuthContext | None) -> AuthContext:
    if auth is None:
        raise AuthorizationError("Authenticated AuthContext is required for MCP tool operations.")
    return auth


def _enforce_optional_tenant_arg(auth: AuthContext, provided_tenant_id: UUID | None) -> UUID:
    if provided_tenant_id is not None:
        assert_same_tenant(auth.tenant_id, provided_tenant_id, resource="mcp_tool_argument")
    return auth.tenant_id


class AegisMCPServer:
    """Standard Model Context Protocol (MCP) JSON-RPC 2.0 server for AEGIS Guardian."""

    def __init__(
        self,
        *,
        service: GuardianService,
        copilot: PurchasingCopilot | None = None,
        policy_engine: PolicyEngine | None = None,
    ) -> None:
        self.service = service
        self.repo = service.repo
        self.copilot = copilot or PurchasingCopilot(repo=service.repo)
        self.policy_engine = policy_engine or service.policy_engine

    def handle_raw_json(
        self,
        raw_body: str | bytes,
        *,
        auth: AuthContext | None,
    ) -> dict[str, Any] | None:
        """Parse a raw JSON-RPC 2.0 message and dispatch it."""
        try:
            payload = json.loads(raw_body)
        except ValueError as exc:
            return _jsonrpc_error(None, JSONRPC_PARSE_ERROR, f"Parse error: {exc}")
        return self.handle_request(payload, auth=auth)

    def handle_request(
        self,
        request: Any,
        *,
        auth: AuthContext | None,
    ) -> dict[str, Any] | None:
        """Dispatch a single JSON-RPC 2.0 MCP request with strict AuthContext enforcement."""
        if not isinstance(request, dict):
            return _jsonrpc_error(None, JSONRPC_INVALID_REQUEST, "Invalid Request: expected JSON object")

        req_id = request.get("id")
        if request.get("jsonrpc") != "2.0":
            return _jsonrpc_error(req_id, JSONRPC_INVALID_REQUEST, "Invalid Request: jsonrpc must be '2.0'")

        method = request.get("method")
        if not isinstance(method, str) or not method:
            return _jsonrpc_error(req_id, JSONRPC_INVALID_REQUEST, "Invalid Request: missing method")

        params = request.get("params")
        if params is None:
            params = {}
        elif not isinstance(params, dict):
            return _jsonrpc_error(req_id, JSONRPC_INVALID_PARAMS, "Invalid params: expected object")

        # MCP lifecycle notifications carry no id
        if method == "notifications/initialized":
            return None if "id" not in request or req_id is None else _jsonrpc_ok(req_id, {})

        if method == "initialize":
            return _jsonrpc_ok(
                req_id,
                {
                    "protocolVersion": MCP_PROTOCOL_VERSION,
                    "capabilities": {"tools": {"listChanged": False}},
                    "serverInfo": {"name": MCP_SERVER_NAME, "version": MCP_SERVER_VERSION},
                },
            )

        if method == "ping":
            return _jsonrpc_ok(req_id, {})

        try:
            verified_auth = _require_auth(auth)

            if method == "tools/list":
                return _jsonrpc_ok(req_id, {"tools": list(_TOOL_DEFINITIONS)})

            if method == "tools/call":
                tool_name = params.get("name")
                arguments = params.get("arguments")
                if not isinstance(tool_name, str) or not tool_name:
                    return _jsonrpc_error(req_id, JSONRPC_INVALID_PARAMS, "Missing tool name")
                if arguments is None:
                    arguments = {}
                if not isinstance(arguments, dict):
                    return _jsonrpc_error(req_id, JSONRPC_INVALID_PARAMS, "Tool arguments must be an object")
                result = self._dispatch_tool(tool_name, arguments, auth=verified_auth)
                return _jsonrpc_ok(req_id, result)

            return _jsonrpc_error(req_id, JSONRPC_METHOD_NOT_FOUND, f"Method not found: {method}")

        except AuthorizationError as exc:
            return _jsonrpc_error(req_id, MCP_UNAUTHORIZED, str(exc))
        except TenantIsolationError as exc:
            return _jsonrpc_error(req_id, MCP_TENANT_FORBIDDEN, str(exc))
        except ValidationError as exc:
            return _jsonrpc_error(req_id, JSONRPC_INVALID_PARAMS, "Invalid tool parameters", data=exc.errors())
        except ValueError as exc:
            return _jsonrpc_error(req_id, JSONRPC_INVALID_PARAMS, str(exc))
        except Exception as exc:  # noqa: BLE001
            return _jsonrpc_error(req_id, JSONRPC_INTERNAL_ERROR, f"Internal MCP server error: {exc}")

    def _dispatch_tool(
        self,
        tool_name: str,
        arguments: dict[str, Any],
        *,
        auth: AuthContext,
    ) -> dict[str, Any]:
        if tool_name == "check_policy":
            auth.require_permission(Permission.PASSPORTS_READ)
            args = _CheckPolicyArgs.model_validate(arguments)
            tenant_id = _enforce_optional_tenant_arg(auth, args.tenant_id)
            return self._tool_check_policy(tenant_id, args)

        if tool_name == "propose_payment":
            auth.require_permission(Permission.PROPOSALS_WRITE)
            args = _ProposePaymentArgs.model_validate(arguments)
            tenant_id = _enforce_optional_tenant_arg(auth, args.tenant_id)
            return self._tool_propose_payment(tenant_id, args)

        if tool_name == "get_passport_budget":
            auth.require_permission(Permission.PASSPORTS_READ)
            args = _GetPassportBudgetArgs.model_validate(arguments)
            tenant_id = _enforce_optional_tenant_arg(auth, args.tenant_id)
            return self._tool_get_passport_budget(tenant_id, args)

        if tool_name == "list_audit_timeline":
            auth.require_permission(Permission.AUDIT_READ)
            args = _ListAuditTimelineArgs.model_validate(arguments)
            tenant_id = _enforce_optional_tenant_arg(auth, args.tenant_id)
            return self._tool_list_audit_timeline(tenant_id, args)

        raise ValueError(f"Unknown or prohibited MCP tool: '{tool_name}'")

    def _tool_check_policy(self, tenant_id: UUID, args: _CheckPolicyArgs) -> dict[str, Any]:
        passport = self.repo.get_passport(tenant_id, args.passport_id)
        if passport is None:
            return _tool_result(
                {"error": "PASSPORT_NOT_FOUND", "passport_id": str(args.passport_id)},
                is_error=True,
            )
        assert_same_tenant(tenant_id, passport.tenant_id, resource=f"passport:{passport.id}")

        merchant = self.repo.get_merchant(tenant_id, args.merchant_id)
        if merchant is None:
            return _tool_result(
                {"error": "MERCHANT_NOT_FOUND", "merchant_id": str(args.merchant_id)},
                is_error=True,
            )
        assert_same_tenant(tenant_id, merchant.tenant_id, resource=f"merchant:{merchant.id}")

        if passport.agent_id != args.agent_id:
            return _tool_result(
                {
                    "error": "AGENT_PASSPORT_MISMATCH",
                    "message": "Agent ID does not match the specified SpendingPassport.",
                },
                is_error=True,
            )

        now = datetime.now(UTC)
        proposal = self.copilot.build_proposal(
            tenant_id=tenant_id,
            agent_id=args.agent_id,
            passport_id=args.passport_id,
            merchant_id=args.merchant_id,
            merchant_name=merchant.name,
            merchant_category=args.merchant_category,
            amount_minor=args.amount_minor,
            currency=args.currency,
            item_summary=args.item_summary,
            line_items=args.line_items,
            rationale="MCP read-only policy pre-check",
            idempotency_key=f"mcp-check-{uuid4()}",
        )
        quote = QuoteSnapshot(
            id=uuid4(),
            tenant_id=tenant_id,
            correlation_id=proposal.correlation_id,
            proposal_id=proposal.id,
            merchant_id=merchant.id,
            amount_minor=proposal.amount_minor,
            currency=proposal.currency,
            line_items=proposal.line_items,
            quote_hash=compute_quote_hash(
                merchant_id=merchant.id,
                amount_minor=proposal.amount_minor,
                currency=proposal.currency,
                line_items=proposal.line_items,
            ),
            expires_at=now + timedelta(minutes=15),
            created_at=now,
        )
        decision: AuthorizationDecision = self.policy_engine.evaluate(
            proposal=proposal,
            passport=passport,
            merchant=merchant,
            quote=quote,
            now=now,
        )
        return _tool_result(
            {
                "outcome": decision.outcome.value,
                "reason_codes": [rc.value for rc in decision.reason_codes],
                "violated_constraints": decision.violated_constraints,
                "requires_human_approval": decision.requires_human_approval,
                "policy_version": decision.policy_version,
                "explanation": decision.explanation,
                "available_budget_minor": passport.available_budget_minor,
                "read_only": True,
            }
        )

    def _tool_propose_payment(self, tenant_id: UUID, args: _ProposePaymentArgs) -> dict[str, Any]:
        passport = self.repo.get_passport(tenant_id, args.passport_id)
        if passport is None:
            return _tool_result(
                {"error": "PASSPORT_NOT_FOUND", "passport_id": str(args.passport_id)},
                is_error=True,
            )
        assert_same_tenant(tenant_id, passport.tenant_id, resource=f"passport:{passport.id}")

        merchant = self.repo.get_merchant(tenant_id, args.merchant_id)
        if merchant is None:
            return _tool_result(
                {"error": "MERCHANT_NOT_FOUND", "merchant_id": str(args.merchant_id)},
                is_error=True,
            )
        assert_same_tenant(tenant_id, merchant.tenant_id, resource=f"merchant:{merchant.id}")

        if passport.agent_id != args.agent_id:
            return _tool_result(
                {
                    "error": "AGENT_PASSPORT_MISMATCH",
                    "message": "Agent ID does not match the specified SpendingPassport.",
                },
                is_error=True,
            )

        now = datetime.now(UTC)
        proposal: PurchaseProposal = self.copilot.build_proposal(
            tenant_id=tenant_id,
            agent_id=args.agent_id,
            passport_id=args.passport_id,
            merchant_id=args.merchant_id,
            merchant_name=args.merchant_name,
            merchant_category=args.merchant_category,
            amount_minor=args.amount_minor,
            currency=args.currency,
            item_summary=args.item_summary,
            line_items=args.line_items,
            rationale=args.rationale,
            idempotency_key=args.idempotency_key,
            correlation_id=args.correlation_id,
        )
        quote = QuoteSnapshot(
            id=uuid4(),
            tenant_id=tenant_id,
            correlation_id=proposal.correlation_id,
            proposal_id=proposal.id,
            merchant_id=args.merchant_id,
            amount_minor=proposal.amount_minor,
            currency=proposal.currency,
            line_items=proposal.line_items,
            quote_hash=compute_quote_hash(
                merchant_id=args.merchant_id,
                amount_minor=proposal.amount_minor,
                currency=proposal.currency,
                line_items=proposal.line_items,
            ),
            expires_at=now + timedelta(minutes=args.quote_ttl_minutes),
            created_at=now,
        )

        try:
            intent: PaymentIntent
            decision: AuthorizationDecision
            intent, decision = self.service.submit_proposal(proposal=proposal, quote=quote)
        except PolicyDeniedError as exc:
            return _tool_result(
                {
                    "error": "POLICY_DENIED",
                    "reason_codes": exc.reason_codes,
                    "message": str(exc),
                },
                is_error=True,
            )
        except GuardianError as exc:
            return _tool_result(
                {
                    "error": "GUARDIAN_ERROR",
                    "message": str(exc),
                },
                is_error=True,
            )

        explanation = self.copilot.explain_decision(proposal, decision)
        return _tool_result(
            {
                "payment_intent": intent.model_dump(mode="json"),
                "decision": decision.model_dump(mode="json"),
                "requires_human_approval": decision.requires_human_approval,
                "copilot_explanation": explanation,
            }
        )

    def _tool_get_passport_budget(self, tenant_id: UUID, args: _GetPassportBudgetArgs) -> dict[str, Any]:
        passport = self.repo.get_passport(tenant_id, args.passport_id)
        if passport is None:
            return _tool_result(
                {"error": "PASSPORT_NOT_FOUND", "passport_id": str(args.passport_id)},
                is_error=True,
            )
        assert_same_tenant(tenant_id, passport.tenant_id, resource=f"passport:{passport.id}")
        return _tool_result(
            {
                "passport_id": str(passport.id),
                "tenant_id": str(passport.tenant_id),
                "agent_id": str(passport.agent_id),
                "status": passport.status.value,
                "currency": passport.currency,
                "total_budget_minor": passport.total_budget_minor,
                "spent_minor": passport.spent_minor,
                "reserved_minor": passport.reserved_minor,
                "available_budget_minor": passport.available_budget_minor,
                "per_tx_limit_minor": passport.per_tx_limit_minor,
                "daily_limit_minor": passport.daily_limit_minor,
                "human_approval_threshold_minor": passport.human_approval_threshold_minor,
                "expires_at": passport.expires_at.isoformat(),
            }
        )

    def _tool_list_audit_timeline(self, tenant_id: UUID, args: _ListAuditTimelineArgs) -> dict[str, Any]:
        sig = inspect.signature(self.repo.list_events)
        kwargs: dict[str, Any] = {
            "correlation_id": args.correlation_id,
            "payment_intent_id": args.payment_intent_id,
        }
        if "limit" in sig.parameters and "offset" in sig.parameters:
            kwargs["limit"] = args.limit
            kwargs["offset"] = args.offset
            events = self.repo.list_events(tenant_id, **kwargs)
        else:
            all_events = self.repo.list_events(tenant_id, **kwargs)
            events = all_events[args.offset : args.offset + args.limit]
        timeline: list[dict[str, Any]] = []
        for ev in events:
            assert_same_tenant(tenant_id, ev.tenant_id, resource=f"financial_event:{ev.id}")
            timeline.append(ev.model_dump(mode="json"))
        return _tool_result({"events": timeline, "count": len(timeline)})


def create_mcp_router(
    server: AegisMCPServer,
    *,
    auth_resolver: Any,
) -> APIRouter:
    """Create an optional FastAPI router exposing the AEGIS MCP JSON-RPC 2.0 endpoint."""
    router = APIRouter(prefix="/mcp", tags=["mcp"])

    @router.post("")
    def mcp_rpc(payload: dict[str, Any], auth: AuthContext = auth_resolver) -> dict[str, Any]:
        response = server.handle_request(payload, auth=auth)
        return response if response is not None else {}

    return router
