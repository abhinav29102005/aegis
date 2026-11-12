"""SaaS billing plans, Stripe Checkout/Portal, signed Stripe webhooks, and monthly quota enforcement."""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import time
from datetime import UTC, datetime
from typing import Annotated, Any, Literal
from uuid import UUID

import httpx
from database import BillingSubscriptionRow, PlatformRepository
from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, ConfigDict, Field
from security import AuthContext, NexusSettings, Permission
from sqlalchemy import select
from sqlalchemy.orm import Session

from aegis_api.deps import get_app_settings, get_db_session, require_permission

router = APIRouter(tags=["billing"])

_UNLIMITED_QUOTA = -1

PLAN_CATALOG: dict[str, dict[str, Any]] = {
    "FREE": {
        "id": "FREE",
        "name": "Free",
        "monthly_tx_quota": 1_000,
        "unlimited": False,
        "price_usd_monthly": 0,
        "features": [
            "Up to 1,000 governed agent transactions / month",
            "Deterministic spending passports & policy engine",
            "Hash-chained financial audit log",
        ],
    },
    "PRO": {
        "id": "PRO",
        "name": "Pro",
        "monthly_tx_quota": 50_000,
        "unlimited": False,
        "price_usd_monthly": 199,
        "features": [
            "Up to 50,000 governed agent transactions / month",
            "GhostPay counterfactual simulation & drift alerts",
            "DisputeOS evidence graph & grounded response drafts",
            "S3/R2 artifact storage & signed webhooks",
        ],
    },
    "ENTERPRISE": {
        "id": "ENTERPRISE",
        "name": "Enterprise",
        "monthly_tx_quota": None,
        "unlimited": True,
        "price_usd_monthly": None,
        "features": [
            "Unlimited / custom monthly transaction volume",
            "OIDC SSO, enforced MFA & custom data residency",
            "Dedicated KMS key wrapping & SLA support",
        ],
    },
}


def _plan_db_quota(plan: str) -> int:
    clean = plan.strip().upper()
    info = PLAN_CATALOG.get(clean)
    if info is None:
        raise ValueError(f"Unsupported billing plan: {plan}")
    quota = info["monthly_tx_quota"]
    return _UNLIMITED_QUOTA if quota is None else int(quota)


def _current_period_ym(now: datetime | None = None) -> str:
    return (now or datetime.now(UTC)).astimezone(UTC).strftime("%Y-%m")


def enforce_monthly_tx_quota(
    platform: PlatformRepository,
    tenant_id: UUID,
    *,
    period_ym: str | None = None,
    metric: str = "transactions",
) -> None:
    """Enforce active subscription status and monthly transaction quota for ``tenant_id``."""
    sub = platform.get_billing_subscription(tenant_id)
    if sub is None:
        plan = "FREE"
        sub_status = "ACTIVE"
        quota: int = int(PLAN_CATALOG["FREE"]["monthly_tx_quota"])
    else:
        plan = sub.plan.strip().upper()
        sub_status = sub.status.strip().upper()
        quota = int(sub.monthly_tx_quota)

    if sub_status in {"CANCELED", "PAST_DUE", "UNPAID", "INACTIVE"}:
        raise HTTPException(
            status_code=status.HTTP_402_PAYMENT_REQUIRED,
            detail={
                "error_code": "SUBSCRIPTION_INACTIVE",
                "message": f"Organization billing subscription is {sub_status}; update payment method to continue.",
            },
        )

    if plan == "ENTERPRISE" or quota < 0:
        return

    ym = period_ym or _current_period_ym()
    used = platform.get_usage_meter(tenant_id, period_ym=ym, metric=metric)
    if used >= quota:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail={
                "error_code": "MONTHLY_QUOTA_EXCEEDED",
                "message": f"Monthly {metric} quota ({quota}) exceeded for {plan} plan.",
                "plan": plan,
                "quota": quota,
                "used": used,
                "period_ym": ym,
            },
        )


class CheckoutSessionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    plan: Literal["PRO", "ENTERPRISE"] = "PRO"
    success_url: str = Field(min_length=8, max_length=500, pattern=r"^https?://")
    cancel_url: str = Field(min_length=8, max_length=500, pattern=r"^https?://")


class BillingPortalRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    return_url: str = Field(min_length=8, max_length=500, pattern=r"^https?://")


async def _stripe_post(
    request: Request,
    *,
    api_key: str,
    path: str,
    form_data: dict[str, str],
) -> dict[str, Any]:
    client: httpx.AsyncClient | None = getattr(request.app.state, "stripe_http_client", None)
    headers = {"Authorization": f"Bearer {api_key}"}
    if client is not None:
        resp = await client.post(path, data=form_data, headers=headers)
    else:
        async with httpx.AsyncClient(base_url="https://api.stripe.com", timeout=10.0) as managed:
            resp = await managed.post(path, data=form_data, headers=headers)
    if resp.status_code >= 400:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail={
                "error_code": "STRIPE_UPSTREAM_ERROR",
                "message": f"Stripe API returned {resp.status_code}.",
            },
        )
    return resp.json()


def verify_stripe_signature(
    payload_bytes: bytes,
    sig_header: str | None,
    *,
    webhook_secret: str,
    tolerance_seconds: int = 300,
    now_ts: float | None = None,
) -> bool:
    """Verify ``Stripe-Signature: t=...,v1=...`` HMAC-SHA256 signature with replay window."""
    if not sig_header or not webhook_secret:
        return False
    timestamp: int | None = None
    v1_signatures: list[str] = []
    for part in sig_header.split(","):
        if "=" not in part:
            continue
        key, val = part.strip().split("=", 1)
        if key == "t":
            try:
                timestamp = int(val)
            except ValueError:
                return False
        elif key == "v1":
            v1_signatures.append(val.strip().lower())

    if timestamp is None or not v1_signatures:
        return False

    current = time.time() if now_ts is None else now_ts
    if abs(current - timestamp) > tolerance_seconds:
        return False

    signed_payload = f"{timestamp}.".encode() + payload_bytes
    expected = hmac.new(webhook_secret.encode("utf-8"), signed_payload, hashlib.sha256).hexdigest()
    return any(hmac.compare_digest(expected, candidate) for candidate in v1_signatures)


@router.get("/billing/plans")
def list_billing_plans() -> dict[str, Any]:
    return {"plans": [PLAN_CATALOG["FREE"], PLAN_CATALOG["PRO"], PLAN_CATALOG["ENTERPRISE"]]}


@router.get("/billing/subscription")
def get_billing_subscription(
    auth: Annotated[AuthContext, Depends(require_permission(Permission.AUDIT_READ))],
    session: Annotated[Session, Depends(get_db_session)],
) -> dict[str, Any]:
    platform = PlatformRepository(session)
    sub = platform.get_billing_subscription(auth.tenant_id)
    period_ym = _current_period_ym()
    tx_count = platform.get_usage_meter(auth.tenant_id, period_ym=period_ym, metric="transactions")
    meters = platform.list_usage_meters(auth.tenant_id, period_ym=period_ym)

    if sub is None:
        plan = "FREE"
        sub_status = "ACTIVE"
        quota: int | None = int(PLAN_CATALOG["FREE"]["monthly_tx_quota"])
        unlimited = False
        stripe_customer_id = None
        stripe_subscription_id = None
        updated_at = None
    else:
        plan = sub.plan
        sub_status = sub.status
        unlimited = plan == "ENTERPRISE" or sub.monthly_tx_quota < 0
        quota = None if unlimited else int(sub.monthly_tx_quota)
        stripe_customer_id = sub.stripe_customer_id
        stripe_subscription_id = sub.stripe_subscription_id
        updated_at = sub.updated_at.isoformat()

    remaining = None if quota is None else max(0, quota - tx_count)
    return {
        "tenant_id": str(auth.tenant_id),
        "plan": plan,
        "status": sub_status,
        "monthly_tx_quota": quota,
        "unlimited": unlimited,
        "current_period_ym": period_ym,
        "current_period_tx_count": tx_count,
        "remaining_tx_quota": remaining,
        "stripe_customer_id": stripe_customer_id,
        "stripe_subscription_id": stripe_subscription_id,
        "updated_at": updated_at,
        "usage_meters": [
            {
                "period_ym": m.period_ym,
                "metric": m.metric,
                "count": m.count,
                "updated_at": m.updated_at.isoformat(),
            }
            for m in meters
        ],
    }


@router.post("/billing/checkout")
async def create_checkout_session(
    payload: CheckoutSessionRequest,
    request: Request,
    auth: Annotated[AuthContext, Depends(require_permission(Permission.BILLING_MANAGE))],
    session: Annotated[Session, Depends(get_db_session)],
    settings: Annotated[NexusSettings, Depends(get_app_settings)],
) -> dict[str, Any]:
    if not settings.stripe_api_key.strip():
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"error_code": "STRIPE_NOT_CONFIGURED", "message": "Stripe API key is not configured."},
        )

    price_env = "STRIPE_PRICE_PRO" if payload.plan == "PRO" else "STRIPE_PRICE_ENTERPRISE"
    price_id = os.getenv(price_env, f"price_aegis_{payload.plan.lower()}")
    form_data: dict[str, str] = {
        "mode": "subscription",
        "success_url": payload.success_url,
        "cancel_url": payload.cancel_url,
        "client_reference_id": str(auth.tenant_id),
        "metadata[tenant_id]": str(auth.tenant_id),
        "metadata[plan]": payload.plan,
        "line_items[0][price]": price_id,
        "line_items[0][quantity]": "1",
    }
    sub = PlatformRepository(session).get_billing_subscription(auth.tenant_id)
    if sub is not None and sub.stripe_customer_id:
        form_data["customer"] = sub.stripe_customer_id

    data = await _stripe_post(
        request,
        api_key=settings.stripe_api_key,
        path="/v1/checkout/sessions",
        form_data=form_data,
    )
    PlatformRepository(session).record_admin_audit(
        tenant_id=auth.tenant_id,
        actor_type=auth.actor_type,
        actor_id=auth.actor_id,
        action="BILLING_CHECKOUT_CREATED",
        resource_type="billing_subscription",
        resource_id=str(auth.tenant_id),
        details={"plan": payload.plan, "session_id": data.get("id")},
    )
    return {
        "session_id": data.get("id"),
        "checkout_url": data.get("url"),
        "plan": payload.plan,
    }


@router.post("/billing/portal")
async def create_billing_portal_session(
    payload: BillingPortalRequest,
    request: Request,
    auth: Annotated[AuthContext, Depends(require_permission(Permission.BILLING_MANAGE))],
    session: Annotated[Session, Depends(get_db_session)],
    settings: Annotated[NexusSettings, Depends(get_app_settings)],
) -> dict[str, Any]:
    if not settings.stripe_api_key.strip():
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"error_code": "STRIPE_NOT_CONFIGURED", "message": "Stripe API key is not configured."},
        )

    platform = PlatformRepository(session)
    sub = platform.get_billing_subscription(auth.tenant_id)
    if sub is None or not sub.stripe_customer_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "error_code": "STRIPE_CUSTOMER_MISSING",
                "message": "Organization does not have an associated Stripe customer yet.",
            },
        )

    data = await _stripe_post(
        request,
        api_key=settings.stripe_api_key,
        path="/v1/billing_portal/sessions",
        form_data={"customer": sub.stripe_customer_id, "return_url": payload.return_url},
    )
    platform.record_admin_audit(
        tenant_id=auth.tenant_id,
        actor_type=auth.actor_type,
        actor_id=auth.actor_id,
        action="BILLING_PORTAL_CREATED",
        resource_type="billing_subscription",
        resource_id=str(auth.tenant_id),
        details={"customer_id": sub.stripe_customer_id},
    )
    return {"portal_url": data.get("url")}


def _resolve_stripe_tenant(
    session: Session,
    obj: dict[str, Any],
) -> tuple[UUID | None, BillingSubscriptionRow | None]:
    metadata = obj.get("metadata") if isinstance(obj.get("metadata"), dict) else {}
    raw_tid = metadata.get("tenant_id") or obj.get("client_reference_id")
    if raw_tid:
        try:
            tid = UUID(str(raw_tid))
            return tid, PlatformRepository(session).get_billing_subscription(tid)
        except ValueError:
            pass

    sub_id = obj.get("subscription") or obj.get("id")
    cust_id = obj.get("customer")
    if sub_id:
        row = session.scalar(
            select(BillingSubscriptionRow).where(BillingSubscriptionRow.stripe_subscription_id == str(sub_id))
        )
        if row is not None:
            return row.tenant_id, row
    if cust_id:
        row = session.scalar(
            select(BillingSubscriptionRow).where(BillingSubscriptionRow.stripe_customer_id == str(cust_id))
        )
        if row is not None:
            return row.tenant_id, row
    return None, None


@router.post("/billing/webhooks/stripe")
async def receive_stripe_webhook(
    request: Request,
    session: Annotated[Session, Depends(get_db_session)],
    settings: Annotated[NexusSettings, Depends(get_app_settings)],
) -> dict[str, Any]:
    if not settings.stripe_webhook_secret.strip():
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"error_code": "STRIPE_WEBHOOK_NOT_CONFIGURED", "message": "Stripe webhook secret is not configured."},
        )

    raw_body = await request.body()
    sig_header = request.headers.get("Stripe-Signature")
    if not verify_stripe_signature(raw_body, sig_header, webhook_secret=settings.stripe_webhook_secret):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"error_code": "INVALID_STRIPE_SIGNATURE", "message": "Invalid Stripe-Signature header."},
        )

    try:
        event = json.loads(raw_body.decode("utf-8"))
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"error_code": "INVALID_WEBHOOK_PAYLOAD", "message": "Malformed JSON payload."},
        ) from exc

    event_type = str(event.get("type", "unknown"))
    obj = event.get("data", {}).get("object", {}) if isinstance(event.get("data"), dict) else {}
    if not isinstance(obj, dict):
        obj = {}

    tenant_id, existing = _resolve_stripe_tenant(session, obj)
    if tenant_id is None:
        return {"received": True, "event_type": event_type, "applied": False}

    metadata = obj.get("metadata") if isinstance(obj.get("metadata"), dict) else {}
    raw_plan = str(metadata.get("plan") or (existing.plan if existing else "PRO")).strip().upper()
    if raw_plan not in PLAN_CATALOG:
        raw_plan = existing.plan if existing else "PRO"

    stripe_customer_id = str(obj["customer"]) if obj.get("customer") else (existing.stripe_customer_id if existing else None)
    stripe_subscription_id = (
        str(obj.get("subscription") or (obj.get("id") if event_type.startswith("customer.subscription.") else ""))
        or (existing.stripe_subscription_id if existing else None)
    )

    if event_type == "checkout.session.completed":
        new_status = "ACTIVE"
    elif event_type == "customer.subscription.deleted":
        new_status = "CANCELED"
    elif event_type == "invoice.payment_failed":
        new_status = "PAST_DUE"
    else:
        raw_status = str(obj.get("status") or "active").strip().lower()
        status_map = {
            "active": "ACTIVE",
            "trialing": "ACTIVE",
            "past_due": "PAST_DUE",
            "unpaid": "PAST_DUE",
            "canceled": "CANCELED",
            "incomplete_expired": "CANCELED",
        }
        new_status = status_map.get(raw_status, "ACTIVE")

    platform = PlatformRepository(session)
    sub = platform.upsert_billing_subscription(
        tenant_id=tenant_id,
        plan=raw_plan,
        status=new_status,
        stripe_customer_id=stripe_customer_id,
        stripe_subscription_id=stripe_subscription_id,
        monthly_tx_quota=_plan_db_quota(raw_plan),
    )
    platform.record_admin_audit(
        tenant_id=tenant_id,
        actor_type="STRIPE_WEBHOOK",
        actor_id=str(event.get("id", "stripe")),
        action="BILLING_SUBSCRIPTION_UPDATED",
        resource_type="billing_subscription",
        resource_id=str(sub.id),
        details={"event_type": event_type, "plan": sub.plan, "status": sub.status},
    )
    return {
        "received": True,
        "applied": True,
        "event_type": event_type,
        "tenant_id": str(tenant_id),
        "plan": sub.plan,
        "status": sub.status,
    }
