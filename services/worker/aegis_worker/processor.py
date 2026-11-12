"""Durable outbox processor, HMAC-signed webhook dispatcher, and PayPal reconciliation worker."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import secrets
import socket
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

import httpx
from contracts import PaymentState
from database import (
    LedgerRepository,
    OutboxEventRow,
    PaymentAttemptRow,
    PlatformRepository,
    WebhookDeliveryRow,
    WebhookEndpointRow,
)
from guardian.budgets.coordinator import BudgetCoordinator
from guardian.payments.coordinator import PaymentCoordinator
from paypal import PayPalAPIError, PayPalSandboxClient, PayPalTimeoutError
from security import (
    NexusSettings,
    SSRFValidationError,
    format_aegis_signature,
    get_settings,
    sign_hmac_sha256,
    validate_webhook_url,
)
from sqlalchemy import and_, or_, select
from sqlalchemy.orm import Session, sessionmaker

logger = logging.getLogger("aegis.worker")
_JITTER_RNG = secrets.SystemRandom()


def _utc_now() -> datetime:
    return datetime.now(UTC)


@dataclass(frozen=True)
class _ClaimedEvent:
    id: UUID
    tenant_id: UUID
    aggregate_type: str
    aggregate_id: UUID
    event_type: str
    payload: dict[str, Any]
    created_at: datetime
    attempts: int


@dataclass(frozen=True)
class _EndpointTarget:
    id: UUID
    url: str
    signing_secret: str


@dataclass(frozen=True)
class _DeliveryOutcome:
    delivery_id: UUID
    endpoint_id: UUID
    body: dict[str, Any]
    status: str
    attempts: int
    response_status: int | None
    error_message: str | None
    delivered_at: datetime | None
    permanent_failure: bool = False


class OutboxWorker:
    """Processes durable outbox events with retries/dead-lettering and reconciles pending payments."""

    def __init__(
        self,
        session_factory: sessionmaker[Session],
        *,
        settings: NexusSettings | None = None,
        paypal_client: PayPalSandboxClient | None = None,
        http_client: httpx.AsyncClient | None = None,
        worker_id: str | None = None,
        lease_seconds: int = 60,
    ) -> None:
        self.session_factory = session_factory
        self.settings = settings or get_settings()
        self.paypal_client = paypal_client or PayPalSandboxClient(settings=self.settings)
        self._injected_http = http_client
        default_worker_id = f"{socket.gethostname()}-{os.getpid()}"
        self.worker_id = (worker_id or default_worker_id)[:128]
        self.lease_seconds = max(5, int(lease_seconds))

    def reap_stale_leases(self, *, now: datetime | None = None) -> int:
        """Reclaim or dead-letter PROCESSING outbox rows whose lease has expired."""
        ts = now or _utc_now()
        stale_cutoff = ts - timedelta(seconds=self.lease_seconds)
        with self.session_factory() as session:
            platform = PlatformRepository(session)
            stmt = select(OutboxEventRow).where(
                OutboxEventRow.status == "PROCESSING",
                or_(
                    and_(
                        OutboxEventRow.lease_expires_at.is_not(None),
                        OutboxEventRow.lease_expires_at < ts,
                    ),
                    and_(
                        OutboxEventRow.lease_expires_at.is_(None),
                        OutboxEventRow.locked_at.is_not(None),
                        OutboxEventRow.locked_at < stale_cutoff,
                    ),
                ),
            )
            if platform._is_postgres():
                stmt = stmt.with_for_update(skip_locked=True)
            stale_rows = list(session.scalars(stmt).all())
            for row in stale_rows:
                next_attempts = row.attempts + 1
                if next_attempts >= self.settings.worker_max_attempts:
                    platform.mark_outbox_failed(
                        row.id,
                        error_message="WORKER_LEASE_EXPIRED",
                        max_attempts=self.settings.worker_max_attempts,
                        now=ts,
                    )
                else:
                    row.attempts = next_attempts
                    row.status = "RETRY"
                    row.next_retry_at = ts
                    row.last_error = "WORKER_LEASE_EXPIRED"
                    row.locked_at = None
                    row.lease_expires_at = None
                    row.locked_by = None
            session.commit()
            return len(stale_rows)

    async def _deliver_to_endpoint(
        self,
        *,
        client: httpx.AsyncClient,
        semaphore: asyncio.Semaphore,
        event: _ClaimedEvent,
        endpoint: _EndpointTarget,
    ) -> _DeliveryOutcome:
        delivery_id = uuid4()
        body = {
            "id": str(event.id),
            "tenant_id": str(event.tenant_id),
            "aggregate_type": event.aggregate_type,
            "aggregate_id": str(event.aggregate_id),
            "event_type": event.event_type,
            "payload": event.payload,
            "created_at": event.created_at.isoformat(),
        }
        raw_body = json.dumps(body, separators=(",", ":"), sort_keys=True, default=str).encode("utf-8")

        resolve_dns = self.settings.app_env.strip().lower() in {"staging", "production", "prod"}
        try:
            validate_webhook_url(
                endpoint.url,
                require_https=bool(self.settings.webhook_require_https),
                resolve_dns=resolve_dns,
            )
        except SSRFValidationError:
            return _DeliveryOutcome(
                delivery_id=delivery_id,
                endpoint_id=endpoint.id,
                body=body,
                status="FAILED",
                attempts=event.attempts + 1,
                response_status=None,
                error_message="SSRF_BLOCKED",
                delivered_at=None,
                permanent_failure=True,
            )

        headers: dict[str, str] = {
            "Content-Type": "application/json",
            "X-AEGIS-Delivery-Id": str(delivery_id),
            "X-AEGIS-Event-Type": event.event_type,
            "AEGIS-Signature": format_aegis_signature(endpoint.signing_secret, raw_body),
        }
        if self.settings.webhook_legacy_signature_fallback:
            legacy_sig = sign_hmac_sha256(body, endpoint.signing_secret)
            headers["X-AEGIS-Signature"] = f"sha256={legacy_sig}"

        resp_status: int | None = None
        err_msg: str | None = None
        status_str = "DELIVERED"
        delivered_at: datetime | None = _utc_now()

        async with semaphore:
            try:
                resp = await client.post(
                    endpoint.url,
                    content=raw_body,
                    headers=headers,
                    follow_redirects=False,
                )
                resp_status = resp.status_code
                if resp.status_code >= 300:
                    status_str = "FAILED"
                    delivered_at = None
                    err_msg = f"HTTP {resp.status_code}"
            except (httpx.TimeoutException, TimeoutError):
                status_str = "FAILED"
                delivered_at = None
                err_msg = "HTTP_TIMEOUT"
            except (httpx.HTTPError, OSError, ValueError):
                status_str = "FAILED"
                delivered_at = None
                err_msg = "REQUEST_ERROR"

        return _DeliveryOutcome(
            delivery_id=delivery_id,
            endpoint_id=endpoint.id,
            body=body,
            status=status_str,
            attempts=event.attempts + 1,
            response_status=resp_status,
            error_message=err_msg,
            delivered_at=delivered_at,
            permanent_failure=False,
        )

    async def _process_claimed_event(
        self,
        *,
        client: httpx.AsyncClient,
        semaphore: asyncio.Semaphore,
        event: _ClaimedEvent,
        endpoints: list[_EndpointTarget],
        ts: datetime,
    ) -> str:
        outcomes: list[_DeliveryOutcome] = []
        if endpoints:
            outcomes = list(
                await asyncio.gather(
                    *(
                        self._deliver_to_endpoint(
                            client=client,
                            semaphore=semaphore,
                            event=event,
                            endpoint=ep,
                        )
                        for ep in endpoints
                    )
                )
            )

        with self.session_factory() as session:
            platform = PlatformRepository(session)
            delivery_errors: list[str] = []
            has_transient_error = False
            has_permanent_error = False
            for outcome in outcomes:
                session.add(
                    WebhookDeliveryRow(
                        id=outcome.delivery_id,
                        tenant_id=event.tenant_id,
                        endpoint_id=outcome.endpoint_id,
                        outbox_event_id=event.id,
                        event_type=event.event_type,
                        payload=outcome.body,
                        status=outcome.status,
                        attempts=outcome.attempts,
                        response_status=outcome.response_status,
                        last_error=outcome.error_message,
                        delivered_at=outcome.delivered_at,
                        created_at=ts,
                    )
                )
                if outcome.error_message is not None:
                    delivery_errors.append(outcome.error_message)
                    if outcome.permanent_failure:
                        has_permanent_error = True
                    else:
                        has_transient_error = True

            if delivery_errors:
                effective_max_attempts = (
                    1 if (has_permanent_error and not has_transient_error) else self.settings.worker_max_attempts
                )
                updated = platform.mark_outbox_failed(
                    event.id,
                    error_message="; ".join(delivery_errors),
                    max_attempts=effective_max_attempts,
                    now=ts,
                )
                if updated.status == "RETRY" and updated.next_retry_at is not None:
                    base_delay = min(300, 5 * (2 ** (updated.attempts - 1)))
                    jitter = _JITTER_RNG.uniform(0.0, min(10.0, base_delay * 0.25))
                    updated.next_retry_at = updated.next_retry_at + timedelta(seconds=jitter)
                    session.flush()
                result_state = "dead_lettered" if updated.status == "DEAD_LETTER" else "retried"
            else:
                platform.mark_outbox_published(event.id, now=ts)
                result_state = "published"
            session.commit()
            return result_state

    async def process_outbox_batch(self, *, limit: int = 25, now: datetime | None = None) -> dict[str, int]:
        ts = now or _utc_now()
        self.reap_stale_leases(now=ts)

        claimed_events: list[_ClaimedEvent] = []
        endpoints_by_event: dict[UUID, list[_EndpointTarget]] = {}

        with self.session_factory() as session:
            platform = PlatformRepository(session)
            claimed = platform.claim_due_outbox_events(
                limit=limit,
                now=ts,
                worker_id=self.worker_id,
                lease_seconds=self.lease_seconds,
            )
            tenant_ids = {row.tenant_id for row in claimed}
            active_endpoints_by_tenant: dict[UUID, list[WebhookEndpointRow]] = {tid: [] for tid in tenant_ids}
            if tenant_ids:
                ep_rows = list(
                    session.scalars(
                        select(WebhookEndpointRow).where(
                            WebhookEndpointRow.tenant_id.in_(tenant_ids),
                            WebhookEndpointRow.status == "ACTIVE",
                        )
                    ).all()
                )
                for ep in ep_rows:
                    active_endpoints_by_tenant.setdefault(ep.tenant_id, []).append(ep)

            for row in claimed:
                claimed_events.append(
                    _ClaimedEvent(
                        id=row.id,
                        tenant_id=row.tenant_id,
                        aggregate_type=row.aggregate_type,
                        aggregate_id=row.aggregate_id,
                        event_type=row.event_type,
                        payload=dict(row.payload or {}),
                        created_at=row.created_at,
                        attempts=row.attempts,
                    )
                )
                endpoints_by_event[row.id] = [
                    _EndpointTarget(id=ep.id, url=ep.url, signing_secret=ep.signing_secret)
                    for ep in active_endpoints_by_tenant.get(row.tenant_id, [])
                    if "*" in ep.event_types or row.event_type in ep.event_types
                ]
            session.commit()

        if not claimed_events:
            return {"claimed": 0, "published": 0, "retried": 0, "dead_lettered": 0}

        semaphore = asyncio.Semaphore(max(1, self.settings.worker_max_concurrent_webhooks))
        own_client = self._injected_http is None
        client = self._injected_http or httpx.AsyncClient(timeout=5.0, follow_redirects=False)
        try:
            outcomes = await asyncio.gather(
                *(
                    self._process_claimed_event(
                        client=client,
                        semaphore=semaphore,
                        event=ev,
                        endpoints=endpoints_by_event.get(ev.id, []),
                        ts=ts,
                    )
                    for ev in claimed_events
                )
            )
        finally:
            if own_client:
                await client.aclose()

        published = sum(1 for item in outcomes if item == "published")
        retried = sum(1 for item in outcomes if item == "retried")
        dead_lettered = sum(1 for item in outcomes if item == "dead_lettered")

        return {
            "claimed": len(claimed_events),
            "published": published,
            "retried": retried,
            "dead_lettered": dead_lettered,
        }

    async def reconcile_pending_payments(self, *, limit: int = 25) -> dict[str, int]:
        with self.session_factory() as session:
            platform = PlatformRepository(session)
            pending = platform.list_pending_provider_attempts(
                limit=limit,
                for_update_skip_locked=False,
            )
            targets = [(row.tenant_id, row.payment_intent_id, row.id) for row in pending]

        checked = 0
        reconciled = 0
        errors = 0
        for tenant_id, intent_id, attempt_id in targets:
            with self.session_factory() as session:
                try:
                    platform = PlatformRepository(session)
                    lock_stmt = select(PaymentAttemptRow).where(
                        PaymentAttemptRow.id == attempt_id,
                        PaymentAttemptRow.state == PaymentState.PENDING_PROVIDER.value,
                    )
                    if platform._is_postgres():
                        lock_stmt = lock_stmt.with_for_update(skip_locked=True)
                    locked_attempt = session.scalar(lock_stmt)
                    if locked_attempt is None:
                        continue
                    checked += 1

                    ledger = LedgerRepository(session)
                    coordinator = PaymentCoordinator(
                        repo=ledger,
                        paypal_client=self.paypal_client,
                        budget_coordinator=BudgetCoordinator(ledger),
                    )
                    await coordinator.reconcile_pending(
                        tenant_id=tenant_id,
                        intent_id=intent_id,
                        attempt_id=attempt_id,
                    )
                    session.commit()
                    reconciled += 1
                except (PayPalAPIError, PayPalTimeoutError, ValueError, RuntimeError, OSError) as exc:
                    session.rollback()
                    errors += 1
                    logger.warning("Reconciliation failed for intent=%s (%s)", intent_id, type(exc).__name__)

        return {"checked": checked, "reconciled": reconciled, "errors": errors}

    async def run_once(self, *, now: datetime | None = None) -> dict[str, Any]:
        outbox_stats = await self.process_outbox_batch(now=now)
        reconcile_stats = await self.reconcile_pending_payments()
        return {"outbox": outbox_stats, "reconciliation": reconcile_stats}
