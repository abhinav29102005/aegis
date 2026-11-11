"""Webhook management, PayPal signed webhook ingestion, and worker outbox inspection."""

from __future__ import annotations

import secrets
from typing import Annotated, Any
from uuid import UUID

from contracts import FinancialEventType
from database import LedgerRepository, PlatformRepository
from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from paypal import PayPalSandboxClient
from pydantic import BaseModel, ConfigDict, Field
from security import AuthContext, Permission
from sqlalchemy.orm import Session

from aegis_api.deps import get_db_session, get_paypal_client, require_permission

router = APIRouter(tags=["webhooks-worker"])


class CreateWebhookEndpointRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    url: str = Field(min_length=8, max_length=500, pattern=r"^https?://")
    description: str = Field(default="", max_length=255)
    event_types: list[str] = Field(default_factory=lambda: ["*"])


@router.get("/webhooks/endpoints")
def list_webhook_endpoints(
    auth: Annotated[AuthContext, Depends(require_permission(Permission.WEBHOOKS_MANAGE))],
    session: Annotated[Session, Depends(get_db_session)],
) -> list[dict[str, Any]]:
    platform = PlatformRepository(session)
    return [
        {
            "id": str(ep.id),
            "url": ep.url,
            "description": ep.description,
            "event_types": ep.event_types,
            "status": ep.status,
            "created_at": ep.created_at.isoformat(),
        }
        for ep in platform.list_webhook_endpoints(auth.tenant_id)
    ]


@router.post("/webhooks/endpoints", status_code=status.HTTP_201_CREATED)
def create_webhook_endpoint(
    payload: CreateWebhookEndpointRequest,
    auth: Annotated[AuthContext, Depends(require_permission(Permission.WEBHOOKS_MANAGE))],
    session: Annotated[Session, Depends(get_db_session)],
) -> dict[str, Any]:
    platform = PlatformRepository(session)
    signing_secret = f"whsec_{secrets.token_urlsafe(24)}"
    ep = platform.create_webhook_endpoint(
        tenant_id=auth.tenant_id,
        url=payload.url,
        description=payload.description,
        signing_secret=signing_secret,
        event_types=payload.event_types,
    )
    platform.record_admin_audit(
        tenant_id=auth.tenant_id,
        actor_type=auth.actor_type,
        actor_id=auth.actor_id,
        action="WEBHOOK_ENDPOINT_CREATED",
        resource_type="webhook_endpoint",
        resource_id=str(ep.id),
        details={"url": ep.url, "event_types": ep.event_types},
    )
    return {
        "id": str(ep.id),
        "url": ep.url,
        "description": ep.description,
        "signing_secret": signing_secret,
        "event_types": ep.event_types,
        "status": ep.status,
        "created_at": ep.created_at.isoformat(),
    }


@router.delete("/webhooks/endpoints/{endpoint_id}")
def disable_webhook_endpoint(
    endpoint_id: UUID,
    auth: Annotated[AuthContext, Depends(require_permission(Permission.WEBHOOKS_MANAGE))],
    session: Annotated[Session, Depends(get_db_session)],
) -> dict[str, Any]:
    platform = PlatformRepository(session)
    try:
        ep = platform.revoke_webhook_endpoint(auth.tenant_id, endpoint_id)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return {"id": str(ep.id), "status": ep.status}


@router.get("/webhooks/deliveries")
def list_webhook_deliveries(
    auth: Annotated[AuthContext, Depends(require_permission(Permission.AUDIT_READ))],
    session: Annotated[Session, Depends(get_db_session)],
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> list[dict[str, Any]]:
    platform = PlatformRepository(session)
    return [
        {
            "id": str(d.id),
            "endpoint_id": str(d.endpoint_id),
            "event_type": d.event_type,
            "status": d.status,
            "attempts": d.attempts,
            "response_status": d.response_status,
            "last_error": d.last_error,
            "delivered_at": d.delivered_at.isoformat() if d.delivered_at else None,
            "created_at": d.created_at.isoformat(),
        }
        for d in platform.list_webhook_deliveries(auth.tenant_id, limit=limit)
    ]


@router.get("/worker/outbox")
def list_outbox_events(
    auth: Annotated[AuthContext, Depends(require_permission(Permission.AUDIT_READ))],
    session: Annotated[Session, Depends(get_db_session)],
    status_filter: str | None = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> list[dict[str, Any]]:
    platform = PlatformRepository(session)
    return [
        {
            "id": str(o.id),
            "aggregate_type": o.aggregate_type,
            "aggregate_id": str(o.aggregate_id),
            "event_type": o.event_type,
            "status": o.status,
            "attempts": o.attempts,
            "last_error": o.last_error,
            "next_retry_at": o.next_retry_at.isoformat() if o.next_retry_at else None,
            "dead_lettered_at": o.dead_lettered_at.isoformat() if o.dead_lettered_at else None,
            "published_at": o.published_at.isoformat() if o.published_at else None,
            "created_at": o.created_at.isoformat(),
        }
        for o in platform.list_outbox_events(auth.tenant_id, status=status_filter, limit=limit)
    ]


@router.post("/worker/outbox/{outbox_id}/requeue")
def requeue_dead_letter(
    outbox_id: UUID,
    auth: Annotated[AuthContext, Depends(require_permission(Permission.WORKER_MANAGE))],
    session: Annotated[Session, Depends(get_db_session)],
) -> dict[str, Any]:
    platform = PlatformRepository(session)
    try:
        row = platform.requeue_dead_letter_outbox(auth.tenant_id, outbox_id)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return {"id": str(row.id), "status": row.status}


@router.post("/paypal/webhooks")
async def receive_paypal_webhook(
    request: Request,
    session: Annotated[Session, Depends(get_db_session)],
    paypal_client: Annotated[PayPalSandboxClient, Depends(get_paypal_client)],
) -> dict[str, Any]:
    """Verify PayPal Sandbox webhook signature fail-closed and record verified webhook events."""
    payload = await request.json()
    headers = {k.lower(): v for k, v in request.headers.items()}
    try:
        verified = await paypal_client.verify_webhook_signature(headers=headers, webhook_event=payload)
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"error_code": "PAYPAL_WEBHOOK_VERIFICATION_FAILED", "message": str(exc)},
        ) from exc
    if not verified:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"error_code": "PAYPAL_WEBHOOK_INVALID_SIGNATURE", "message": "Invalid PayPal webhook signature."},
        )

    event_type = str(payload.get("event_type", "UNKNOWN"))
    resource = payload.get("resource") or {}
    paypal_order_id = (
        resource.get("supplementary_data", {}).get("related_ids", {}).get("order_id")
        or resource.get("id")
    )
    ledger = LedgerRepository(session)

    # Locate matching attempt across orders cleanly
    from database import PaymentAttemptRow
    from sqlalchemy import select

    matched_intent_id: UUID | None = None
    if paypal_order_id:
        attempt_row = session.scalar(
            select(PaymentAttemptRow).where(PaymentAttemptRow.paypal_order_id == str(paypal_order_id)).limit(1)
        )
        if attempt_row is not None:
            matched_intent_id = attempt_row.payment_intent_id
            ledger.append_financial_event(
                tenant_id=attempt_row.tenant_id,
                correlation_id=attempt_row.correlation_id,
                payment_intent_id=attempt_row.payment_intent_id,
                event_type=FinancialEventType.PAYPAL_WEBHOOK_RECEIVED,
                actor_type="PAYPAL_WEBHOOK",
                actor_id=str(payload.get("id", "webhook")),
                payload={
                    "paypal_event_type": event_type,
                    "paypal_order_id": str(paypal_order_id),
                    "resource_id": resource.get("id"),
                },
            )

    return {
        "verified": True,
        "event_type": event_type,
        "matched_payment_intent_id": str(matched_intent_id) if matched_intent_id else None,
    }
