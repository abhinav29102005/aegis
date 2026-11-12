"""PayPal Disputes webhook handler for DisputeOS."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

from contracts import (
    DisputeCase,
    DisputeSourceType,
    DisputeStatus,
)
from paypal import paypal_value_to_minor


async def handle_paypal_dispute_webhook(
    repo: Any,
    event_type: str,
    resource: dict[str, Any],
    event_id: str | None = None,
    tenant_id: UUID | None = None,
) -> dict[str, Any]:
    """Handle PayPal dispute webhooks and update dispute case state idempotently (GAP-009, GAP-017)."""
    dispute_id = resource.get("dispute_id")
    if not dispute_id:
        return {"handled": False, "reason": "missing dispute_id in webhook resource"}

    # Attempt to locate existing case by paypal_dispute_id
    case = None
    if hasattr(repo, "get_dispute_case_by_paypal_id"):
        res = repo.get_dispute_case_by_paypal_id(dispute_id)
        case = await res if hasattr(res, "__await__") else res
    elif hasattr(repo, "list_dispute_cases"):
        res = repo.list_dispute_cases(tenant_id=tenant_id) if tenant_id else repo.list_dispute_cases()
        cases = await res if hasattr(res, "__await__") else res
        for c in cases:
            if getattr(c, "paypal_dispute_id", None) == dispute_id:
                case = c
                break
    elif hasattr(repo, "list_cases"):
        res = repo.list_cases(tenant_id) if tenant_id else repo.list_cases()
        cases = await res if hasattr(res, "__await__") else res
        for c in cases:
            if getattr(c, "paypal_dispute_id", None) == dispute_id:
                case = c
                break
    elif hasattr(repo, "_cases"):
        for c in repo._cases.values():
            if getattr(c, "paypal_dispute_id", None) == dispute_id:
                case = c
                break

    if event_type == "CUSTOMER.DISPUTE.CREATED":
        if case is not None:
            # Idempotent re-delivery
            return {"handled": True, "action": "already_exists", "case_id": str(case.id)}

        amount_val = resource.get("dispute_amount", {}).get("value", "0.00")
        currency = resource.get("dispute_amount", {}).get("currency_code", "USD")
        amount_minor = paypal_value_to_minor(amount_val, currency)

        response_due_str = resource.get("seller_response_due_date") or resource.get("response_due_date")
        response_due_by = None
        if response_due_str:
            try:
                response_due_by = datetime.fromisoformat(response_due_str)
            except (ValueError, TypeError):
                response_due_by = None

        new_case = DisputeCase(
            id=uuid4(),
            tenant_id=tenant_id or UUID("00000000-0000-0000-0000-000000000001"),
            correlation_id=uuid4(),
            payment_intent_id=uuid4(),
            status=DisputeStatus.UNDER_INVESTIGATION,
            source_type=DisputeSourceType.PAYPAL_SANDBOX,
            reason=resource.get("reason", "MERCHANDISE_OR_SERVICE_NOT_RECEIVED"),
            buyer_claim=resource.get("dispute_life_cycle_stage", "Dispute created in PayPal"),
            amount_minor=amount_minor,
            currency=currency,
            is_synthetic=False,
            paypal_dispute_id=dispute_id,
            response_due_by=response_due_by,
        )
        if hasattr(repo, "save_dispute_case"):
            res = repo.save_dispute_case(new_case)
            if hasattr(res, "__await__"):
                await res
        elif hasattr(repo, "_cases"):
            repo._cases[new_case.id] = new_case
        return {"handled": True, "action": "created", "case_id": str(new_case.id)}

    elif event_type == "CUSTOMER.DISPUTE.UPDATED":
        if case is None:
            return {"handled": False, "reason": f"DisputeCase for {dispute_id} not found"}

        external_status = resource.get("status")
        response_due_str = resource.get("seller_response_due_date") or resource.get("response_due_date")
        response_due_by = None
        if response_due_str:
            try:
                response_due_by = datetime.fromisoformat(response_due_str)
            except (ValueError, TypeError):
                response_due_by = None

        updates: dict[str, Any] = {}
        if hasattr(case, "external_status") and external_status:
            updates["external_status"] = external_status
        if response_due_by and hasattr(case, "response_due_by"):
            updates["response_due_by"] = response_due_by

        if updates:
            updated_case = case.model_copy(update=updates) if hasattr(case, "model_copy") else case
            if hasattr(repo, "update_dispute_case"):
                res = repo.update_dispute_case(updated_case)
                if hasattr(res, "__await__"):
                    await res
            elif hasattr(repo, "_cases"):
                repo._cases[updated_case.id] = updated_case

        return {"handled": True, "action": "updated", "case_id": str(case.id)}

    elif event_type == "CUSTOMER.DISPUTE.RESOLVED":
        if case is None:
            return {"handled": False, "reason": f"DisputeCase for {dispute_id} not found"}

        outcome_info = resource.get("dispute_outcome", {})
        outcome_code = outcome_info.get("outcome_code", "RESOLVED")
        updates = {
            "status": DisputeStatus.RESOLVED,
            "resolved_at": datetime.now(UTC),
        }
        if hasattr(case, "resolution_outcome"):
            updates["resolution_outcome"] = outcome_code

        updated_case = case.model_copy(update=updates) if hasattr(case, "model_copy") else case
        if hasattr(repo, "update_dispute_case"):
            res = repo.update_dispute_case(updated_case)
            if hasattr(res, "__await__"):
                await res
        elif hasattr(repo, "_cases"):
            repo._cases[updated_case.id] = updated_case

        return {
            "handled": True,
            "action": "resolved",
            "case_id": str(case.id),
            "resolution_outcome": outcome_code,
        }

    return {"handled": False, "reason": f"unhandled event type: {event_type}"}
