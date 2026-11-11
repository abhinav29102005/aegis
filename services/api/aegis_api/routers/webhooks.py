"""Webhook management, PayPal signed webhook ingestion, and worker outbox inspection."""

from __future__ import annotations

import inspect
import logging
import secrets
from typing import Annotated, Any
from uuid import UUID

from contracts import FinancialEventType, compute_payload_hash
from database import (
    LedgerRepository,
    OutboxEventRow,
    PaymentAttemptRow,
    PlatformRepository,
    WebhookDeliveryRow,
    WebhookEndpointRow,
)
from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from paypal import PayPalSandboxClient
from pydantic import BaseModel, ConfigDict, Field
from security import (
    AuthContext,
    NexusSettings,
    Permission,
    SSRFValidationError,
    validate_webhook_url,
)
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from aegis_api.deps import (
    get_app_settings,
    get_db_session,
    get_paypal_client,
    require_permission,
)

logger = logging.getLogger("aegis.api.webhooks")

router = APIRouter(tags=["webhooks-worker"])


class CreateWebhookEndpointRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    url: str = Field(min_length=8, max_length=500, pattern=r"^https?://")
    description: str = Field(default="", max_length=255)
    event_types: list[str] = Field(default_factory=lambda: ["*"])


@router.get("/webhooks/endpoints")
def list_webhook_endpoints(
    response: Response,
    auth: Annotated[AuthContext, Depends(require_permission(Permission.WEBHOOKS_MANAGE))],
    session: Annotated[Session, Depends(get_db_session)],
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[dict[str, Any]]:
    platform = PlatformRepository(session)
    total = int(
        session.scalar(
            select(func.count())
            .select_from(WebhookEndpointRow)
            .where(WebhookEndpointRow.tenant_id == auth.tenant_id)
        )
        or 0
    )
    response.headers["X-Total-Count"] = str(total)
    return [
        {
            "id": str(ep.id),
            "url": ep.url,
            "description": ep.description,
            "event_types": ep.event_types,
            "status": ep.status,
            "created_at": ep.created_at.isoformat(),
        }
        for ep in platform.list_webhook_endpoints(auth.tenant_id, limit=limit, offset=offset)
    ]


@router.post("/webhooks/endpoints", status_code=status.HTTP_201_CREATED)
def create_webhook_endpoint(
    payload: CreateWebhookEndpointRequest,
    auth: Annotated[AuthContext, Depends(require_permission(Permission.WEBHOOKS_MANAGE))],
    session: Annotated[Session, Depends(get_db_session)],
    settings: Annotated[NexusSettings, Depends(get_app_settings)],
) -> dict[str, Any]:
    resolve_dns = settings.app_env.strip().lower() in {"staging", "production", "prod"}
    try:
        validate_webhook_url(
            payload.url,
            require_https=bool(settings.webhook_require_https),
            resolve_dns=resolve_dns,
        )
    except SSRFValidationError as exc:
        raise HTTPException(
            status_code=422,
            detail={"error_code": "INVALID_WEBHOOK_URL", "message": str(exc)},
        ) from exc

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
    response: Response,
    auth: Annotated[AuthContext, Depends(require_permission(Permission.AUDIT_READ))],
    session: Annotated[Session, Depends(get_db_session)],
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[dict[str, Any]]:
    platform = PlatformRepository(session)
    total = int(
        session.scalar(
            select(func.count())
            .select_from(WebhookDeliveryRow)
            .where(WebhookDeliveryRow.tenant_id == auth.tenant_id)
        )
        or 0
    )
    response.headers["X-Total-Count"] = str(total)
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
        for d in platform.list_webhook_deliveries(auth.tenant_id, limit=limit, offset=offset)
    ]


@router.get("/worker/outbox")
def list_outbox_events(
    response: Response,
    auth: Annotated[AuthContext, Depends(require_permission(Permission.AUDIT_READ))],
    session: Annotated[Session, Depends(get_db_session)],
    status_filter: str | None = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[dict[str, Any]]:
    platform = PlatformRepository(session)
    count_stmt = (
        select(func.count())
        .select_from(OutboxEventRow)
        .where(OutboxEventRow.tenant_id == auth.tenant_id)
    )
    if status_filter:
        count_stmt = count_stmt.where(OutboxEventRow.status == status_filter)
    total = int(session.scalar(count_stmt) or 0)
    response.headers["X-Total-Count"] = str(total)
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
        for o in platform.list_outbox_events(
            auth.tenant_id, status=status_filter, limit=limit, offset=offset
        )
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
    try:
        payload = await request.json()
    except Exception as exc:
        logger.warning("Invalid JSON payload on PayPal webhook: %s", type(exc).__name__)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"error_code": "INVALID_WEBHOOK_PAYLOAD", "message": "Invalid webhook JSON payload."},
        ) from exc
    if not isinstance(payload, dict):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"error_code": "INVALID_WEBHOOK_PAYLOAD", "message": "Invalid webhook JSON payload."},
        )

    headers = {k.lower(): v for k, v in request.headers.items()}
    try:
        verified = await paypal_client.verify_webhook_signature(headers=headers, webhook_event=payload)
    except Exception as exc:
        logger.warning("PayPal webhook verification error (%s): %s", type(exc).__name__, exc)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={
                "error_code": "PAYPAL_WEBHOOK_VERIFICATION_FAILED",
                "message": "PayPal webhook verification failed.",
            },
        ) from exc
    if not verified:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={
                "error_code": "PAYPAL_WEBHOOK_INVALID_SIGNATURE",
                "message": "Invalid PayPal webhook signature.",
            },
        )

    event_type = str(payload.get("event_type", "UNKNOWN"))
    raw_resource = payload.get("resource")
    resource: dict[str, Any] = raw_resource if isinstance(raw_resource, dict) else {}

    payload_hash = compute_payload_hash(payload)
    raw_event_id = str(payload.get("id") or "").strip()
    event_id = (raw_event_id or payload_hash)[:128]
    resource_id = str(resource.get("id") or "").strip()[:128] or None

    platform = PlatformRepository(session)
    is_new = platform.record_paypal_webhook_once(
        event_id=event_id,
        event_type=event_type,
        resource_id=resource_id,
        payload_hash=payload_hash,
    )
    if not is_new:
        return {"verified": True, "deduplicated": True, "event_type": event_type}

    supplementary_data = resource.get("supplementary_data")
    related_ids = supplementary_data.get("related_ids") if isinstance(supplementary_data, dict) else None
    paypal_order_id = (
        related_ids.get("order_id") if isinstance(related_ids, dict) else None
    ) or resource.get("id")

    ledger = LedgerRepository(session)

    matched_intent_id: UUID | None = None
    if paypal_order_id:
        attempt_row = session.scalar(
            select(PaymentAttemptRow)
            .where(PaymentAttemptRow.paypal_order_id == str(paypal_order_id))
            .limit(1)
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

    response_body: dict[str, Any] = {
        "verified": True,
        "deduplicated": False,
        "event_type": event_type,
        "matched_payment_intent_id": str(matched_intent_id) if matched_intent_id else None,
    }

    if event_type.startswith("CUSTOMER.DISPUTE."):
        try:
            from disputeos.paypal.webhook_handler import handle_paypal_dispute_webhook

            dispute_res = handle_paypal_dispute_webhook(
                ledger,
                event_type,
                resource,
                str(payload.get("id", "webhook")),
            )
            if inspect.isawaitable(dispute_res):
                dispute_res = await dispute_res
            response_body["dispute_handler"] = dispute_res
        except ImportError:
            response_body["dispute_handler"] = "not_installed_yet"

    return response_body
