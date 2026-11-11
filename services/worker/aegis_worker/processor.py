"""Durable outbox processor, HMAC-signed webhook dispatcher, and PayPal reconciliation worker."""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

import httpx
from database import LedgerRepository, PlatformRepository, WebhookDeliveryRow
from guardian.budgets.coordinator import BudgetCoordinator
from guardian.payments.coordinator import PaymentCoordinator
from paypal import PayPalAPIError, PayPalSandboxClient, PayPalTimeoutError
from security import NexusSettings, get_settings, sign_hmac_sha256
from sqlalchemy.orm import Session, sessionmaker

logger = logging.getLogger("aegis.worker")


def _utc_now() -> datetime:
    return datetime.now(UTC)


class OutboxWorker:
    """Processes durable outbox events with retries/dead-lettering and reconciles pending payments."""

    def __init__(
        self,
        session_factory: sessionmaker[Session],
        *,
        settings: NexusSettings | None = None,
        paypal_client: PayPalSandboxClient | None = None,
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        self.session_factory = session_factory
        self.settings = settings or get_settings()
        self.paypal_client = paypal_client or PayPalSandboxClient(settings=self.settings)
        self._injected_http = http_client

    async def process_outbox_batch(self, *, limit: int = 25, now: datetime | None = None) -> dict[str, int]:
        ts = now or _utc_now()
        published = 0
        retried = 0
        dead_lettered = 0

        with self.session_factory() as session:
            platform = PlatformRepository(session)
            claimed = platform.claim_due_outbox_events(limit=limit, now=ts)
            claimed_ids = [row.id for row in claimed]
            session.commit()

        if not claimed_ids:
            return {"claimed": 0, "published": 0, "retried": 0, "dead_lettered": 0}

        own_client = self._injected_http is None
        client = self._injected_http or httpx.AsyncClient(timeout=5.0)
        try:
            for outbox_id in claimed_ids:
                with self.session_factory() as session:
                    platform = PlatformRepository(session)
                    from database import OutboxEventRow

                    event_row = session.get(OutboxEventRow, outbox_id)
                    if event_row is None:
                        continue
                    endpoints = [
                        ep
                        for ep in platform.list_webhook_endpoints(event_row.tenant_id)
                        if ep.status == "ACTIVE"
                        and ("*" in ep.event_types or event_row.event_type in ep.event_types)
                    ]

                    delivery_errors: list[str] = []
                    for ep in endpoints:
                        delivery_id = uuid4()
                        body = {
                            "id": str(event_row.id),
                            "tenant_id": str(event_row.tenant_id),
                            "aggregate_type": event_row.aggregate_type,
                            "aggregate_id": str(event_row.aggregate_id),
                            "event_type": event_row.event_type,
                            "payload": event_row.payload,
                            "created_at": event_row.created_at.isoformat(),
                        }
                        sig = sign_hmac_sha256(body, ep.signing_secret)
                        resp_status: int | None = None
                        err_msg: str | None = None
                        status_str = "DELIVERED"
                        delivered_at: datetime | None = _utc_now()
                        try:
                            resp = await client.post(
                                ep.url,
                                json=body,
                                headers={
                                    "X-AEGIS-Delivery-Id": str(delivery_id),
                                    "X-AEGIS-Event-Type": event_row.event_type,
                                    "X-AEGIS-Signature": f"sha256={sig}",
                                },
                            )
                            resp_status = resp.status_code
                            if resp.status_code >= 400:
                                status_str = "FAILED"
                                delivered_at = None
                                err_msg = f"HTTP {resp.status_code}: {resp.text[:250]}"
                                delivery_errors.append(err_msg)
                        except (httpx.HTTPError, OSError, TimeoutError, ValueError) as exc:
                            status_str = "FAILED"
                            delivered_at = None
                            err_msg = str(exc)
                            delivery_errors.append(err_msg)

                        session.add(
                            WebhookDeliveryRow(
                                id=delivery_id,
                                tenant_id=event_row.tenant_id,
                                endpoint_id=ep.id,
                                outbox_event_id=event_row.id,
                                event_type=event_row.event_type,
                                payload=body,
                                status=status_str,
                                attempts=event_row.attempts + 1,
                                response_status=resp_status,
                                last_error=err_msg,
                                delivered_at=delivered_at,
                                created_at=ts,
                            )
                        )

                    if delivery_errors:
                        updated = platform.mark_outbox_failed(
                            event_row.id,
                            error_message="; ".join(delivery_errors),
                            max_attempts=self.settings.worker_max_attempts,
                            now=ts,
                        )
                        if updated.status == "DEAD_LETTER":
                            dead_lettered += 1
                        else:
                            retried += 1
                    else:
                        platform.mark_outbox_published(event_row.id, now=ts)
                        published += 1
                    session.commit()
        finally:
            if own_client:
                await client.aclose()

        return {
            "claimed": len(claimed_ids),
            "published": published,
            "retried": retried,
            "dead_lettered": dead_lettered,
        }

    async def reconcile_pending_payments(self, *, limit: int = 25) -> dict[str, int]:
        with self.session_factory() as session:
            platform = PlatformRepository(session)
            pending = platform.list_pending_provider_attempts(limit=limit)
            targets = [(row.tenant_id, row.payment_intent_id, row.id) for row in pending]

        reconciled = 0
        errors = 0
        for tenant_id, intent_id, attempt_id in targets:
            with self.session_factory() as session:
                try:
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
                    logger.warning("Reconciliation failed for intent=%s: %s", intent_id, exc)

        return {"checked": len(targets), "reconciled": reconciled, "errors": errors}

    async def run_once(self, *, now: datetime | None = None) -> dict[str, Any]:
        outbox_stats = await self.process_outbox_batch(now=now)
        reconcile_stats = await self.reconcile_pending_payments()
        return {"outbox": outbox_stats, "reconciliation": reconcile_stats}
