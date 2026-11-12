"""AEGIS Model Context Protocol (MCP) Server for Agentic Payment Governance."""

from __future__ import annotations

import json
from typing import Any
from uuid import UUID, uuid4

from contracts import (
    Merchant,
    PurchaseProposal,
    QuoteSnapshot,
    compute_quote_hash,
)
from contracts.models import utc_now

from guardian.domain.service import GuardianService
from guardian.passports.service import PassportService
from guardian.policies.engine import PolicyEngine

# Canonical MCP Tool Definitions
TOOLS_SCHEMA = [
    {
        "name": "check_policy",
        "description": "Deterministically evaluates whether an agent payment intent satisfies spending policy constraints without executing or reserving funds.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "tenant_id": {"type": "string", "description": "Tenant UUID"},
                "spending_passport_id": {"type": "string", "description": "SpendingPassport UUID"},
                "merchant_id": {"type": "string", "description": "Target Merchant identifier"},
                "amount_minor": {"type": "integer", "description": "Transaction amount in minor units (e.g. cents)"},
                "currency": {"type": "string", "default": "USD", "description": "ISO-4217 Currency Code"},
                "category": {"type": "string", "description": "Optional merchant category code or classification"},
            },
            "required": ["tenant_id", "spending_passport_id", "merchant_id", "amount_minor"],
        },
    },
    {
        "name": "propose_payment",
        "description": "Constructs a non-authoritative PurchaseProposal for human or policy review. Strictly lacks financial execution authority.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "tenant_id": {"type": "string", "description": "Tenant UUID"},
                "agent_id": {"type": "string", "description": "Autonomous purchasing agent UUID or ID"},
                "merchant_id": {"type": "string", "description": "Merchant ID"},
                "amount_minor": {"type": "integer", "description": "Total amount in minor currency units"},
                "currency": {"type": "string", "default": "USD"},
                "purpose": {"type": "string", "description": "Business justification or task description"},
                "line_items": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "description": {"type": "string"},
                            "amount_minor": {"type": "integer"},
                        },
                        "required": ["description", "amount_minor"],
                    },
                },
            },
            "required": ["tenant_id", "agent_id", "merchant_id", "amount_minor"],
        },
    },
    {
        "name": "get_passport_budget",
        "description": "Inspects remaining budget, per-tx limit, and current status of an agent spending passport.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "tenant_id": {"type": "string", "description": "Tenant UUID"},
                "passport_id": {"type": "string", "description": "SpendingPassport UUID"},
            },
            "required": ["tenant_id", "passport_id"],
        },
    },
    {
        "name": "list_audit_timeline",
        "description": "Retrieves the immutable financial event hash-chain audit timeline for a payment intent.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "tenant_id": {"type": "string", "description": "Tenant UUID"},
                "payment_intent_id": {"type": "string", "description": "Payment Intent UUID"},
            },
            "required": ["tenant_id", "payment_intent_id"],
        },
    },
]


class AegisMCPServer:
    """AEGIS MCP Server exposing secure governance tools over JSON-RPC 2.0."""

    def __init__(
        self,
        guardian_service: GuardianService | None = None,
        passport_service: PassportService | None = None,
    ) -> None:
        self.guardian_service = guardian_service or GuardianService()
        self.passport_service = passport_service or PassportService()

    def handle_request(self, request: dict[str, Any]) -> dict[str, Any]:
        """Process incoming JSON-RPC 2.0 request."""
        req_id = request.get("id")
        method = request.get("method")
        params = request.get("params", {})

        if not method or request.get("jsonrpc") != "2.0":
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "error": {"code": -32600, "message": "Invalid Request: expected jsonrpc 2.0"},
            }

        if method == "initialize":
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {"tools": {}},
                    "serverInfo": {"name": "aegis-guardian-mcp", "version": "1.0.0"},
                },
            }

        if method == "tools/list":
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {"tools": TOOLS_SCHEMA},
            }

        if method == "tools/call":
            tool_name = params.get("name")
            args = params.get("arguments", {})
            try:
                data = self._dispatch_tool(tool_name, args)
                return {
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "result": {
                        "content": [{"type": "text", "text": json.dumps(data, default=str)}],
                        "isError": False,
                    },
                }
            except Exception as exc:
                return {
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "result": {
                        "content": [{"type": "text", "text": f"Error executing tool {tool_name}: {exc}"}],
                        "isError": True,
                    },
                }

        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "error": {"code": -32601, "message": f"Method not found: {method}"},
        }

    def _dispatch_tool(self, tool_name: str, args: dict[str, Any]) -> dict[str, Any]:
        if tool_name == "check_policy":
            return self._tool_check_policy(args)
        elif tool_name == "propose_payment":
            return self._tool_propose_payment(args)
        elif tool_name == "get_passport_budget":
            return self._tool_get_passport_budget(args)
        elif tool_name == "list_audit_timeline":
            return self._tool_list_audit_timeline(args)
        else:
            raise ValueError(f"Unknown tool: {tool_name}")

    def _tool_check_policy(self, args: dict[str, Any]) -> dict[str, Any]:
        tenant_id = UUID(args["tenant_id"])
        passport_id = UUID(args["spending_passport_id"])
        merchant_id = args["merchant_id"]
        amount_minor = int(args["amount_minor"])
        currency_str = args.get("currency", "USD")

        passport = self.passport_service.get_passport(tenant_id, passport_id)
        if passport is None:
            raise ValueError(f"Passport {passport_id} not found")

        merchant_uuid = (
            UUID(str(merchant_id))
            if isinstance(merchant_id, (str, UUID)) and len(str(merchant_id)) == 36
            else uuid4()
        )
        proposal = PurchaseProposal(
            id=uuid4(),
            tenant_id=tenant_id,
            correlation_id=uuid4(),
            agent_id=passport.agent_id,
            passport_id=passport.id,
            merchant_id=merchant_uuid,
            merchant_name="Merchant",
            merchant_category=args.get("category", "cloud_infrastructure"),
            amount_minor=amount_minor,
            currency=currency_str,
            item_summary="Policy check query",
            line_items=[],
            rationale="MCP policy pre-check",
            idempotency_key=f"check-{uuid4().hex[:12]}",
            created_at=utc_now(),
        )

        quote = QuoteSnapshot(
            id=uuid4(),
            tenant_id=tenant_id,
            correlation_id=proposal.correlation_id,
            proposal_id=proposal.id,
            merchant_id=merchant_uuid,
            amount_minor=amount_minor,
            currency=currency_str,
            line_items=[],
            expires_at=passport.expires_at,
        )

        merchant = Merchant(
            id=merchant_uuid,
            tenant_id=tenant_id,
            name="Merchant",
            domain="merchant.example.com",
            category=args.get("category", "cloud_infrastructure"),
            is_allowlisted=True,
            created_at=utc_now(),
        )

        decision = PolicyEngine().evaluate(
            proposal=proposal,
            passport=passport,
            merchant=merchant,
            quote=quote,
        )
        primary_reason = (
            decision.reason_codes[0].value
            if getattr(decision, "reason_codes", None)
            else getattr(decision, "reason_code", "OK_WITHIN_POLICY")
        )
        return {
            "outcome": decision.outcome.value,
            "reason_code": str(primary_reason),
            "reason_codes": [rc.value if hasattr(rc, "value") else str(rc) for rc in getattr(decision, "reason_codes", [])],
            "explanation": decision.explanation,
            "requires_human_approval": decision.requires_human_approval,
            "passport_id": str(passport.id),
            "amount_minor": amount_minor,
            "currency": currency_str,
        }

    def _tool_propose_payment(self, args: dict[str, Any]) -> dict[str, Any]:
        tenant_id = UUID(args["tenant_id"])
        agent_id = (
            UUID(args["agent_id"])
            if isinstance(args["agent_id"], str) and len(args["agent_id"]) == 36
            else uuid4()
        )
        merchant_id = args["merchant_id"]
        merchant_uuid = (
            UUID(str(merchant_id))
            if isinstance(merchant_id, (str, UUID)) and len(str(merchant_id)) == 36
            else uuid4()
        )
        passport_uuid = (
            UUID(args["passport_id"])
            if "passport_id" in args and len(args["passport_id"]) == 36
            else uuid4()
        )
        amount_minor = int(args["amount_minor"])
        currency_str = args.get("currency", "USD")
        purpose = args.get("purpose") or args.get("rationale") or "Autonomous payment proposal"
        item_summary = args.get("item_summary") or purpose[:100]

        raw_items = args.get("line_items", [])
        line_items = list(raw_items)

        q_hash = compute_quote_hash(
            merchant_id=merchant_uuid,
            amount_minor=amount_minor,
            currency=currency_str,
            line_items=line_items,
        )

        proposal = PurchaseProposal(
            id=uuid4(),
            tenant_id=tenant_id,
            correlation_id=uuid4(),
            agent_id=agent_id,
            passport_id=passport_uuid,
            merchant_id=merchant_uuid,
            merchant_name=args.get("merchant_name", "Test Merchant"),
            merchant_category=args.get("category", "SOFTWARE"),
            amount_minor=amount_minor,
            currency=currency_str,
            item_summary=item_summary,
            line_items=line_items,
            rationale=purpose,
            idempotency_key=args.get("idempotency_key") or f"mcp-prop-{uuid4().hex[:12]}",
            created_at=utc_now(),
        )

        return {
            "proposal_id": str(proposal.id),
            "correlation_id": str(proposal.correlation_id),
            "merchant_id": merchant_id,
            "amount_minor": amount_minor,
            "currency": currency_str,
            "quote_hash": q_hash,
            "status": "PROPOSED",
            "non_authoritative": True,
            "notice": "This proposal does not hold budget or authorize payment until evaluated by Guardian deterministic policies.",
        }

    def _tool_get_passport_budget(self, args: dict[str, Any]) -> dict[str, Any]:
        tenant_id = UUID(args["tenant_id"])
        passport_id = UUID(args["passport_id"])
        passport = self.passport_service.get_passport(tenant_id, passport_id)
        if passport is None:
            raise ValueError(f"Passport {passport_id} not found")

        return {
            "passport_id": str(passport.id),
            "status": passport.status.value,
            "per_tx_limit_minor": passport.per_tx_limit_minor,
            "daily_limit_minor": passport.daily_limit_minor,
            "total_budget_minor": passport.total_budget_minor,
            "spent_minor": passport.spent_minor,
            "reserved_minor": passport.reserved_minor,
            "available_budget_minor": passport.available_budget_minor,
            "currency": str(passport.currency),
            "expires_at": passport.expires_at.isoformat(),
        }

    def _tool_list_audit_timeline(self, args: dict[str, Any]) -> dict[str, Any]:
        tenant_id = UUID(args["tenant_id"])
        payment_intent_id = UUID(args["payment_intent_id"])

        events = self.guardian_service.list_events(tenant_id=tenant_id, payment_intent_id=payment_intent_id)
        return {
            "payment_intent_id": str(payment_intent_id),
            "tenant_id": str(tenant_id),
            "event_count": len(events),
            "events": [
                {
                    "event_id": str(ev.id),
                    "event_type": ev.event_type.value,
                    "actor_type": ev.actor_type,
                    "payload_hash": ev.payload_hash,
                    "prev_event_hash": ev.prev_event_hash,
                    "created_at": ev.created_at.isoformat(),
                }
                for ev in events
            ],
        }
