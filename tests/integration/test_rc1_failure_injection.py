"""RC1 Failure Injection & Worker Recovery integration tests.

Verifies:
1. Worker lease expiration and reclamation (without premature preemption of active leases).
2. Dead-letter queue (DLQ) transition after max retries and operator requeue recovery.
3. API `/ready` 503 sanitization (no DB credentials or stack traces leaked) and recovery to 200.
4. API `/metrics` Prometheus exposition format with `aegis_` metrics.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import uuid4

import httpx
import pytest
from aegis_api.app import create_app
from aegis_worker.processor import OutboxWorker
from database import (
    OutboxEventRow,
    PlatformRepository,
    create_db_engine,
    create_session_factory,
    init_db,
)
from fastapi.testclient import TestClient
from security import NexusSettings


def _make_settings(db_url: str, tmp_path: Path, **overrides: Any) -> NexusSettings:
    defaults: dict[str, Any] = {
        "app_env": "test",
        "database_url": db_url,
        "evidence_storage_dir": str(tmp_path / "evidence"),
        "signing_secret": "test-signing-secret-rc1-fi-minimum-32b",
        "jwt_secret": "test-jwt-secret-rc1-fi-minimum-32-chars",
        "api_key": "test-api-key-rc1-fi-123456",
        "webhook_require_https": False,
    }
    defaults.update(overrides)
    return NexusSettings(**defaults)


@pytest.mark.asyncio
async def test_worker_lease_expiration_and_reclamation(tmp_path: Path) -> None:
    """Expired PROCESSING leases are reclaimed and delivered; active leases are untouched."""
    db_url = f"sqlite:///{tmp_path / 'fi_lease.db'}"
    engine = create_db_engine(db_url)
    init_db(engine)
    session_factory = create_session_factory(engine)
    settings = _make_settings(db_url, tmp_path, worker_max_attempts=3)

    now = datetime.now(UTC)
    delivered_ids: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        delivered_ids.append(json.loads(request.content.decode("utf-8"))["id"])
        return httpx.Response(200, json={"ok": True})

    with session_factory() as session:
        platform = PlatformRepository(session)
        org = platform.create_organization(name="FI Lease Org", slug="fi-lease-org")
        platform.create_webhook_endpoint(
            tenant_id=org.id,
            url="https://hooks.customer.example/fi-lease",
            description="fi lease test",
            signing_secret="whsec_fi_lease_123",
            event_types=["*"],
        )
        expired_id = uuid4()
        active_id = uuid4()
        session.add(
            OutboxEventRow(
                id=expired_id,
                tenant_id=org.id,
                aggregate_type="payment_intent",
                aggregate_id=uuid4(),
                event_type="PROPOSAL_CREATED",
                payload={"case": "expired"},
                status="PROCESSING",
                attempts=0,
                locked_at=now - timedelta(seconds=120),
                lease_expires_at=now - timedelta(seconds=30),
                locked_by="crashed-worker-1",
                created_at=now - timedelta(seconds=120),
            )
        )
        session.add(
            OutboxEventRow(
                id=active_id,
                tenant_id=org.id,
                aggregate_type="payment_intent",
                aggregate_id=uuid4(),
                event_type="PROPOSAL_CREATED",
                payload={"case": "active"},
                status="PROCESSING",
                attempts=0,
                locked_at=now - timedelta(seconds=5),
                lease_expires_at=now + timedelta(seconds=55),
                locked_by="healthy-worker-2",
                created_at=now - timedelta(seconds=5),
            )
        )
        session.commit()

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http_client:
        worker = OutboxWorker(session_factory, settings=settings, http_client=http_client, worker_id="worker-recovery-1")
        result = await worker.process_outbox_batch(now=now)
        assert result["claimed"] == 1
        assert result["published"] == 1
        assert result["dead_lettered"] == 0
        assert delivered_ids == [str(expired_id)]

    with session_factory() as session:
        expired_row = session.get(OutboxEventRow, expired_id)
        active_row = session.get(OutboxEventRow, active_id)
        assert expired_row is not None
        assert expired_row.status == "PUBLISHED"
        assert expired_row.attempts == 1
        assert expired_row.locked_by is None
        assert expired_row.lease_expires_at is None

        assert active_row is not None
        assert active_row.status == "PROCESSING"
        assert active_row.locked_by == "healthy-worker-2"
        assert active_row.lease_expires_at is not None

    engine.dispose()


@pytest.mark.asyncio
async def test_worker_dlq_transition_after_max_retries_and_requeue(tmp_path: Path) -> None:
    """Events exceeding worker_max_attempts transition to DEAD_LETTER and can be requeued."""
    db_url = f"sqlite:///{tmp_path / 'fi_dlq.db'}"
    engine = create_db_engine(db_url)
    init_db(engine)
    session_factory = create_session_factory(engine)
    settings = _make_settings(db_url, tmp_path, worker_max_attempts=2)

    t0 = datetime.now(UTC)
    fail_mode = {"fail": True}

    def handler(request: httpx.Request) -> httpx.Response:
        if fail_mode["fail"]:
            return httpx.Response(503, json={"error": "downstream unavailable"})
        return httpx.Response(200, json={"ok": True})

    with session_factory() as session:
        platform = PlatformRepository(session)
        org = platform.create_organization(name="FI DLQ Org", slug="fi-dlq-org")
        platform.create_webhook_endpoint(
            tenant_id=org.id,
            url="https://hooks.customer.example/fi-dlq",
            description="fi dlq test",
            signing_secret="whsec_fi_dlq_123",
            event_types=["*"],
        )
        outbox_id = uuid4()
        session.add(
            OutboxEventRow(
                id=outbox_id,
                tenant_id=org.id,
                aggregate_type="payment_intent",
                aggregate_id=uuid4(),
                event_type="PAYMENT_CAPTURED",
                payload={"amount": "42.00"},
                status="PENDING",
                attempts=0,
                created_at=t0,
            )
        )

        lease_poison_id = uuid4()
        session.add(
            OutboxEventRow(
                id=lease_poison_id,
                tenant_id=org.id,
                aggregate_type="payment_intent",
                aggregate_id=uuid4(),
                event_type="PAYMENT_CAPTURED",
                payload={"amount": "99.00"},
                status="PROCESSING",
                attempts=1,  # max_attempts=2 -> expired lease moves to DEAD_LETTER
                locked_at=t0 - timedelta(seconds=120),
                lease_expires_at=t0 - timedelta(seconds=30),
                locked_by="crashed-worker-dlq",
                created_at=t0 - timedelta(seconds=120),
            )
        )
        session.commit()

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http_client:
        worker = OutboxWorker(session_factory, settings=settings, http_client=http_client, worker_id="worker-dlq-1")

        # Attempt 1: transient 503 -> RETRY; lease_poison_id -> DEAD_LETTER
        r1 = await worker.process_outbox_batch(now=t0)
        assert r1["claimed"] == 1
        assert r1["retried"] == 1
        assert r1["dead_lettered"] == 0

        with session_factory() as session:
            row1 = session.get(OutboxEventRow, outbox_id)
            poison_row = session.get(OutboxEventRow, lease_poison_id)
            assert row1 is not None and row1.status == "RETRY"
            assert row1.next_retry_at is not None
            retry_at = row1.next_retry_at
            assert poison_row is not None and poison_row.status == "DEAD_LETTER"
            assert poison_row.last_error == "WORKER_LEASE_EXPIRED"
            assert poison_row.dead_lettered_at is not None

        # Attempt 2 after backoff window: still 503 -> DEAD_LETTER (max_attempts=2)
        t_retry = retry_at + timedelta(seconds=1)
        r2 = await worker.process_outbox_batch(now=t_retry)
        assert r2["claimed"] == 1
        assert r2["dead_lettered"] == 1

        with session_factory() as session:
            dead_row = session.get(OutboxEventRow, outbox_id)
            assert dead_row is not None
            assert dead_row.status == "DEAD_LETTER"
            assert dead_row.attempts == 2
            assert dead_row.dead_lettered_at is not None
            assert dead_row.locked_by is None
            assert dead_row.lease_expires_at is None

            # Operator requeue after downstream recovers
            platform = PlatformRepository(session)
            requeued = platform.requeue_dead_letter_outbox(org.id, outbox_id, now=t_retry + timedelta(seconds=5))
            session.commit()
            assert requeued.status == "PENDING"
            assert requeued.attempts == 0
            assert requeued.dead_lettered_at is None

        fail_mode["fail"] = False
        r3 = await worker.process_outbox_batch(now=t_retry + timedelta(seconds=6))
        assert r3["claimed"] == 1
        assert r3["published"] == 1

    engine.dispose()


def test_api_ready_503_sanitization_and_recovery(tmp_path: Path) -> None:
    """`/ready` returns sanitized 503 on DB outage (no credentials/tracebacks) and recovers to 200."""
    db_url = f"sqlite:///{tmp_path / 'fi_ready.db'}"
    settings = _make_settings(db_url, tmp_path)
    engine = create_db_engine(db_url)
    app = create_app(settings=settings, engine=engine, create_tables=True)

    original_connect = engine.connect

    def _failing_connect() -> Any:
        raise RuntimeError(
            "FATAL: password authentication failed for user secret_pg_user "
            "dsn=postgresql://aegis:super_secret_pw@internal-pg:5432/aegis_platform"
        )

    with TestClient(app) as client:
        # Healthy baseline
        ok_resp = client.get("/ready")
        assert ok_resp.status_code == 200
        assert ok_resp.json()["status"] == "ready"
        assert ok_resp.json()["database"] == "connected"

        # Inject DB outage
        engine.connect = _failing_connect  # type: ignore[method-assign]
        fail_resp = client.get("/ready")
        assert fail_resp.status_code == 503
        body = fail_resp.json()
        assert body == {
            "detail": {
                "error_code": "DB_UNAVAILABLE",
                "message": "Database readiness check failed.",
            }
        }
        assert "secret_pg_user" not in fail_resp.text
        assert "super_secret_pw" not in fail_resp.text
        assert "postgresql://" not in fail_resp.text
        assert "Traceback" not in fail_resp.text

        # Restore DB connectivity
        engine.connect = original_connect  # type: ignore[method-assign]
        rec_resp = client.get("/ready")
        assert rec_resp.status_code == 200
        assert rec_resp.json()["database"] == "connected"

    engine.dispose()


def test_api_metrics_prometheus_exposition(tmp_path: Path) -> None:
    """`/metrics` emits Prometheus text exposition format with `aegis_` metrics."""
    db_url = f"sqlite:///{tmp_path / 'fi_metrics.db'}"
    settings = _make_settings(db_url, tmp_path)
    engine = create_db_engine(db_url)
    app = create_app(settings=settings, engine=engine, create_tables=True)

    with TestClient(app) as client:
        assert client.get("/health").status_code == 200
        metrics_resp = client.get("/metrics")
        assert metrics_resp.status_code == 200
        assert "text/plain" in metrics_resp.headers["content-type"]
        assert "aegis_http_requests_total" in metrics_resp.text
        assert "aegis_http_request_duration_seconds" in metrics_resp.text

    engine.dispose()
