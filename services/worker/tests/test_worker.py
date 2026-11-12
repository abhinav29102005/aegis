"""Tests for AEGIS OutboxWorker: webhook delivery, signing, SSRF, leases, semaphore, healthcheck, reconciliation."""

from __future__ import annotations

import asyncio
import json
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import httpx
import pytest
from aegis_sdk import verify_webhook_signature
from aegis_worker import OutboxWorker, check_worker_health, touch_heartbeat
from aegis_worker.main import main as worker_main
from aegis_worker.main import run_worker_loop
from contracts import (
    AgentIdentity,
    FinancialEventType,
    Merchant,
    PassportStatus,
    PaymentState,
    SpendingPassport,
)
from database import (
    LedgerRepository,
    OutboxEventRow,
    PlatformRepository,
    create_db_engine,
    create_session_factory,
    init_db,
)
from guardian import GuardianService
from guardian.api.models import SubmitProposalRequest
from paypal import PayPalSandboxClient
from security import NexusSettings, verify_aegis_signature


@pytest.mark.asyncio
async def test_outbox_webhook_delivery_retry_dead_letter_and_requeue(tmp_path: Path) -> None:
    db_url = f"sqlite:///{tmp_path / 'worker_test.db'}"
    engine = create_db_engine(db_url)
    init_db(engine)
    session_factory = create_session_factory(engine)

    settings = NexusSettings(
        database_url=db_url,
        worker_max_attempts=2,
    )

    secret = "whsec_worker_test_secret_123"
    received_deliveries: list[tuple[bytes, str, str | None]] = []
    mode = {"fail": False}

    def webhook_handler(request: httpx.Request) -> httpx.Response:
        if mode["fail"]:
            return httpx.Response(500, text="temporary upstream failure secret-backend-trace")
        sig = request.headers.get("AEGIS-Signature", "")
        legacy_sig = request.headers.get("X-AEGIS-Signature")
        received_deliveries.append((request.content, sig, legacy_sig))
        return httpx.Response(202, json={"ok": True})

    # Seed tenant, webhook endpoint, and outbox events
    with session_factory() as session:
        platform = PlatformRepository(session)
        ledger = LedgerRepository(session)
        org = platform.create_organization(name="Worker Org", slug="worker-org")
        platform.create_webhook_endpoint(
            tenant_id=org.id,
            url="https://webhook.example.test/aegis",
            description="Test receiver",
            signing_secret=secret,
            event_types=["*"],
        )
        ledger.append_financial_event(
            tenant_id=org.id,
            correlation_id=uuid4(),
            payment_intent_id=None,
            event_type=FinancialEventType.PROPOSAL_CREATED,
            actor_type="SYSTEM",
            actor_id="test",
            payload={"amount_minor": 1200},
        )
        session.commit()
        tenant_id = org.id

    async with httpx.AsyncClient(transport=httpx.MockTransport(webhook_handler)) as http_client:
        worker = OutboxWorker(session_factory, settings=settings, http_client=http_client)
        res = await worker.process_outbox_batch()
        assert res["claimed"] == 1
        assert res["published"] == 1
        assert len(received_deliveries) == 1
        raw_body, sig_header, legacy_header = received_deliveries[0]
        assert legacy_header is None
        assert sig_header.startswith("t=") and ",v1=" in sig_header
        assert verify_aegis_signature(
            secret=secret,
            raw_body=raw_body,
            header_value=sig_header,
        )

        # Now enqueue a second event while webhook endpoint fails -> retries -> dead-lettered -> requeued
        mode["fail"] = True
        with session_factory() as session:
            LedgerRepository(session).append_financial_event(
                tenant_id=tenant_id,
                correlation_id=uuid4(),
                payment_intent_id=None,
                event_type=FinancialEventType.PAYPAL_CAPTURE_VERIFIED,
                actor_type="SYSTEM",
                actor_id="test",
                payload={"amount_minor": 3900},
            )
            session.commit()

        t0 = datetime.now(UTC)
        r1 = await worker.process_outbox_batch(now=t0)
        assert r1["retried"] == 1
        assert r1["dead_lettered"] == 0

        # Before backoff window expires, claiming yields 0
        r_early = await worker.process_outbox_batch(now=t0 + timedelta(seconds=1))
        assert r_early["claimed"] == 0

        # After backoff window, 2nd attempt fails and moves to DEAD_LETTER (max_attempts=2)
        r2 = await worker.process_outbox_batch(now=t0 + timedelta(seconds=20))
        assert r2["dead_lettered"] == 1

        with session_factory() as session:
            platform = PlatformRepository(session)
            dead = platform.list_outbox_events(tenant_id, status="DEAD_LETTER")
            assert len(dead) == 1
            dead_id = dead[0].id
            assert dead[0].last_error == "HTTP 500"
            deliveries = platform.list_webhook_deliveries(tenant_id)
            failed = [d for d in deliveries if d.status == "FAILED"]
            assert failed
            assert all(d.last_error == "HTTP 500" for d in failed)
            assert all("temporary upstream failure" not in (d.last_error or "") for d in failed)

            # Requeue dead letter and recover once receiver is healthy
            platform.requeue_dead_letter_outbox(tenant_id, dead_id)
            session.commit()

        mode["fail"] = False
        r3 = await worker.process_outbox_batch(now=t0 + timedelta(seconds=30))
        assert r3["published"] == 1


@pytest.mark.asyncio
async def test_webhook_legacy_signature_fallback_emits_both_headers(tmp_path: Path) -> None:
    db_url = f"sqlite:///{tmp_path / 'worker_legacy_sig.db'}"
    engine = create_db_engine(db_url)
    init_db(engine)
    session_factory = create_session_factory(engine)

    settings = NexusSettings(
        database_url=db_url,
        webhook_legacy_signature_fallback=True,
    )
    secret = "whsec_legacy_fallback_123"
    captured: list[tuple[bytes, dict[str, str]]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append((request.content, dict(request.headers)))
        return httpx.Response(200, json={"ok": True})

    with session_factory() as session:
        platform = PlatformRepository(session)
        ledger = LedgerRepository(session)
        org = platform.create_organization(name="Legacy Sig Org", slug="legacy-sig-org")
        platform.create_webhook_endpoint(
            tenant_id=org.id,
            url="https://hooks.customer.example/events",
            description="legacy fallback",
            signing_secret=secret,
            event_types=["*"],
        )
        ledger.append_financial_event(
            tenant_id=org.id,
            correlation_id=uuid4(),
            payment_intent_id=None,
            event_type=FinancialEventType.PROPOSAL_CREATED,
            actor_type="SYSTEM",
            actor_id="test",
            payload={"amount_minor": 500},
        )
        session.commit()

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http_client:
        worker = OutboxWorker(session_factory, settings=settings, http_client=http_client)
        res = await worker.process_outbox_batch()
        assert res["published"] == 1

    raw_body, headers = captured[0]
    lower_headers = {k.lower(): v for k, v in headers.items()}
    assert verify_aegis_signature(secret, raw_body, lower_headers["aegis-signature"])
    assert verify_webhook_signature(
        payload_body=json.loads(raw_body.decode("utf-8")),
        signature_header=lower_headers["x-aegis-signature"],
        signing_secret=secret,
    )


@pytest.mark.asyncio
async def test_worker_ssrf_blocking_redirects_and_redacted_errors(tmp_path: Path) -> None:
    db_url = f"sqlite:///{tmp_path / 'worker_ssrf.db'}"
    engine = create_db_engine(db_url)
    init_db(engine)
    session_factory = create_session_factory(engine)
    settings = NexusSettings(database_url=db_url, worker_max_attempts=5)

    transport_calls: list[str] = []
    mode = {"case": "redirect"}

    def handler(request: httpx.Request) -> httpx.Response:
        transport_calls.append(str(request.url))
        if mode["case"] == "redirect":
            return httpx.Response(302, headers={"Location": "http://169.254.169.254/latest/meta-data/"})
        if mode["case"] == "timeout":
            raise httpx.ReadTimeout("timed out talking to internal-host-10.0.0.5:8443")
        raise httpx.ConnectError("connection refused to secret-internal.corp:9200")

    with session_factory() as session:
        platform = PlatformRepository(session)
        ledger = LedgerRepository(session)

        # 1. SSRF URLs must be blocked before transport and dead-lettered immediately
        for idx, bad_url in enumerate([
            "http://169.254.169.254/latest/meta-data/",
            "http://127.0.0.1:8080/hook",
            "https://[::1]/hook",
        ]):
            org = platform.create_organization(name=f"SSRF Org {idx}", slug=f"ssrf-org-{idx}")
            platform.create_webhook_endpoint(
                tenant_id=org.id,
                url=bad_url,
                description="bad",
                signing_secret="whsec_bad",
                event_types=["*"],
            )
            ledger.append_financial_event(
                tenant_id=org.id,
                correlation_id=uuid4(),
                payment_intent_id=None,
                event_type=FinancialEventType.PROPOSAL_CREATED,
                actor_type="SYSTEM",
                actor_id="test",
                payload={"idx": idx},
            )

        # 2. Redirect / Timeout / ConnectError endpoints
        org_http = platform.create_organization(name="HTTP Err Org", slug="http-err-org")
        platform.create_webhook_endpoint(
            tenant_id=org_http.id,
            url="https://hooks.customer.example/events",
            description="redirect/error test",
            signing_secret="whsec_err",
            event_types=["*"],
        )
        session.commit()
        org_http_id = org_http.id

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http_client:
        worker = OutboxWorker(session_factory, settings=settings, http_client=http_client)
        res = await worker.process_outbox_batch()
        assert res["claimed"] == 3
        assert res["dead_lettered"] == 3
        assert transport_calls == []

        # Redirect must NOT be followed and must fail as HTTP 302
        with session_factory() as session:
            LedgerRepository(session).append_financial_event(
                tenant_id=org_http_id,
                correlation_id=uuid4(),
                payment_intent_id=None,
                event_type=FinancialEventType.PROPOSAL_CREATED,
                actor_type="SYSTEM",
                actor_id="test",
                payload={"case": "redirect"},
            )
            session.commit()

        t0 = datetime.now(UTC)
        r_redir = await worker.process_outbox_batch(now=t0)
        assert r_redir["retried"] == 1
        assert len(transport_calls) == 1  # Never followed redirect to 169.254.169.254

        # Timeout error must be redacted to HTTP_TIMEOUT
        mode["case"] = "timeout"
        r_timeout = await worker.process_outbox_batch(now=t0 + timedelta(seconds=30))
        assert r_timeout["retried"] == 1

        # Connect error must be redacted to REQUEST_ERROR
        mode["case"] = "connect"
        r_conn = await worker.process_outbox_batch(now=t0 + timedelta(seconds=90))
        assert r_conn["retried"] == 1

    with session_factory() as session:
        deliveries = PlatformRepository(session).list_webhook_deliveries(org_http_id)
        errors = {d.last_error for d in deliveries}
        assert errors == {"HTTP 302", "HTTP_TIMEOUT", "REQUEST_ERROR"}


@pytest.mark.asyncio
async def test_worker_lease_expiration_reaping(tmp_path: Path) -> None:
    db_url = f"sqlite:///{tmp_path / 'worker_lease.db'}"
    engine = create_db_engine(db_url)
    init_db(engine)
    session_factory = create_session_factory(engine)
    settings = NexusSettings(database_url=db_url, worker_max_attempts=3)

    now = datetime.now(UTC)
    delivered_ids: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        delivered_ids.append(json.loads(request.content.decode("utf-8"))["id"])
        return httpx.Response(200, json={"ok": True})

    with session_factory() as session:
        platform = PlatformRepository(session)
        org = platform.create_organization(name="Lease Org", slug="lease-org")
        platform.create_webhook_endpoint(
            tenant_id=org.id,
            url="https://hooks.customer.example/lease",
            description="lease test",
            signing_secret="whsec_lease_123",
            event_types=["*"],
        )
        recoverable_id = uuid4()
        poison_id = uuid4()
        session.add(
            OutboxEventRow(
                id=recoverable_id,
                tenant_id=org.id,
                aggregate_type="payment_intent",
                aggregate_id=uuid4(),
                event_type="PROPOSAL_CREATED",
                payload={"x": 1},
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
                id=poison_id,
                tenant_id=org.id,
                aggregate_type="payment_intent",
                aggregate_id=uuid4(),
                event_type="PROPOSAL_CREATED",
                payload={"x": 2},
                status="PROCESSING",
                attempts=2,  # max_attempts=3 -> next expired lease moves to DEAD_LETTER
                locked_at=now - timedelta(seconds=120),
                lease_expires_at=now - timedelta(seconds=30),
                locked_by="crashed-worker-2",
                created_at=now - timedelta(seconds=120),
            )
        )
        session.commit()

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http_client:
        worker = OutboxWorker(session_factory, settings=settings, http_client=http_client, worker_id="worker-live-1")
        res = await worker.process_outbox_batch(now=now)
        assert res["claimed"] == 1
        assert res["published"] == 1
        assert delivered_ids == [str(recoverable_id)]

    with session_factory() as session:
        rec_row = session.get(OutboxEventRow, recoverable_id)
        poison_row = session.get(OutboxEventRow, poison_id)
        assert rec_row is not None and rec_row.status == "PUBLISHED"
        assert rec_row.attempts == 1
        assert rec_row.locked_by is None and rec_row.lease_expires_at is None
        assert poison_row is not None and poison_row.status == "DEAD_LETTER"
        assert poison_row.attempts == 3
        assert poison_row.last_error == "WORKER_LEASE_EXPIRED"


@pytest.mark.asyncio
async def test_worker_concurrency_semaphore_bounds_inflight_requests(tmp_path: Path) -> None:
    db_url = f"sqlite:///{tmp_path / 'worker_semaphore.db'}"
    engine = create_db_engine(db_url)
    init_db(engine)
    session_factory = create_session_factory(engine)
    settings = NexusSettings(database_url=db_url, worker_max_concurrent_webhooks=2)

    state = {"in_flight": 0, "max_in_flight": 0, "total": 0}

    class SlowAsyncTransport(httpx.AsyncBaseTransport):
        async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
            state["in_flight"] += 1
            state["max_in_flight"] = max(state["max_in_flight"], state["in_flight"])
            try:
                await asyncio.sleep(0.02)
                state["total"] += 1
                return httpx.Response(200, json={"ok": True})
            finally:
                state["in_flight"] -= 1

    with session_factory() as session:
        platform = PlatformRepository(session)
        ledger = LedgerRepository(session)
        org = platform.create_organization(name="Sem Org", slug="sem-org")
        platform.create_webhook_endpoint(
            tenant_id=org.id,
            url="https://hooks.customer.example/sem",
            description="sem",
            signing_secret="whsec_sem_123",
            event_types=["*"],
        )
        for idx in range(6):
            ledger.append_financial_event(
                tenant_id=org.id,
                correlation_id=uuid4(),
                payment_intent_id=None,
                event_type=FinancialEventType.PROPOSAL_CREATED,
                actor_type="SYSTEM",
                actor_id="test",
                payload={"idx": idx},
            )
        session.commit()

    async with httpx.AsyncClient(transport=SlowAsyncTransport()) as http_client:
        worker = OutboxWorker(session_factory, settings=settings, http_client=http_client)
        res = await worker.process_outbox_batch()
        assert res["claimed"] == 6
        assert res["published"] == 6

    assert state["total"] == 6
    assert 1 <= state["max_in_flight"] <= 2


@pytest.mark.asyncio
async def test_worker_healthcheck_cli_and_loop_resilience(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db_url = f"sqlite:///{tmp_path / 'worker_health.db'}"
    engine = create_db_engine(db_url)
    init_db(engine)
    engine.dispose()

    hb_path = tmp_path / "heartbeat"
    settings = NexusSettings(database_url=db_url, worker_poll_interval_seconds=0.05)

    # Missing heartbeat -> unhealthy
    assert check_worker_health(settings=settings, heartbeat_path=hb_path) is False

    # Stale heartbeat -> unhealthy
    now = time.time()
    touch_heartbeat(hb_path, now=now - 120.0)
    assert check_worker_health(settings=settings, heartbeat_path=hb_path, max_age_seconds=30.0, now=now) is False

    # Fresh heartbeat + valid DB -> healthy
    touch_heartbeat(hb_path, now=now)
    assert check_worker_health(settings=settings, heartbeat_path=hb_path, max_age_seconds=30.0, now=now) is True

    # Fresh heartbeat + unreachable DB -> unhealthy
    bad_settings = NexusSettings(database_url="postgresql+psycopg://invalid:invalid@127.0.0.1:1/missing")
    assert check_worker_health(settings=bad_settings, heartbeat_path=hb_path, max_age_seconds=30.0, now=now) is False

    # CLI --healthcheck exit codes 0 and 1
    monkeypatch.setenv("DATABASE_URL", db_url)
    monkeypatch.setenv("AEGIS_WORKER_HEARTBEAT_FILE", str(hb_path))
    from security import get_settings

    get_settings.cache_clear()
    try:
        with pytest.raises(SystemExit) as exc_ok:
            worker_main(["--healthcheck"])
        assert exc_ok.value.code == 0

        hb_path.unlink()
        with pytest.raises(SystemExit) as exc_fail:
            worker_main(["--healthcheck"])
        assert exc_fail.value.code == 1
    finally:
        get_settings.cache_clear()

    # Worker loop survives transient httpx.HTTPError and updates heartbeat cleanly before stopping
    stop_event = asyncio.Event()
    calls = {"n": 0}

    async def flaky_run_once(self, *, now=None):  # type: ignore[no-untyped-def]
        calls["n"] += 1
        if calls["n"] == 1:
            raise httpx.ConnectError("transient network error")
        stop_event.set()
        return {"outbox": {"claimed": 0}, "reconciliation": {"checked": 0}}

    monkeypatch.setattr(OutboxWorker, "run_once", flaky_run_once)
    await run_worker_loop(settings=settings, heartbeat_path=hb_path, stop_event=stop_event)
    assert calls["n"] >= 2
    assert hb_path.exists()


@pytest.mark.asyncio
async def test_worker_reconciles_pending_provider_payments(tmp_path: Path) -> None:
    db_url = f"sqlite:///{tmp_path / 'worker_reconcile.db'}"
    engine = create_db_engine(db_url)
    init_db(engine)
    session_factory = create_session_factory(engine)

    pp_state = {"capture_status": "TIMEOUT", "order_status": "APPROVED"}

    def pp_handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path == "/v1/oauth2/token":
            return httpx.Response(200, json={"access_token": "tok", "expires_in": 3600})
        if path == "/v2/checkout/orders" and request.method == "POST":
            return httpx.Response(201, json={"id": "PP-ORD-REC", "status": "CREATED", "links": []})
        if path == "/v2/checkout/orders/PP-ORD-REC" and request.method == "GET":
            if pp_state["order_status"] == "COMPLETED":
                return httpx.Response(
                    200,
                    json={
                        "id": "PP-ORD-REC",
                        "status": "COMPLETED",
                        "purchase_units": [
                            {"payments": {"captures": [{"id": "CAP-REC-1", "status": "COMPLETED", "amount": {"currency_code": "USD", "value": "15.00"}}]}}
                        ],
                    },
                )
            return httpx.Response(200, json={"id": "PP-ORD-REC", "status": pp_state["order_status"]})
        if path == "/v2/checkout/orders/PP-ORD-REC/capture":
            if pp_state["capture_status"] == "TIMEOUT":
                raise httpx.ReadTimeout("Simulated PayPal capture timeout")
            return httpx.Response(201, json={"id": "PP-ORD-REC", "status": "COMPLETED"})
        return httpx.Response(404)

    settings = NexusSettings(database_url=db_url, paypal_client_id="c", paypal_client_secret="s")
    pp_client = PayPalSandboxClient(
        settings=settings,
        http_client=httpx.AsyncClient(base_url="https://api-m.sandbox.paypal.com", transport=httpx.MockTransport(pp_handler)),
    )

    with session_factory() as session:
        platform = PlatformRepository(session)
        ledger = LedgerRepository(session)
        org = platform.create_organization(name="Reconcile Org", slug="reconcile-org")
        agent = ledger.create_agent(
            AgentIdentity(tenant_id=org.id, name="A1", purpose="test", framework="custom", public_fingerprint="fp-rec-1")
        )
        merchant = ledger.create_merchant(
            Merchant(tenant_id=org.id, name="M1", domain="m1.example.com", category="SOFTWARE", is_allowlisted=True)
        )
        passport = ledger.create_passport(
            SpendingPassport(
                tenant_id=org.id,
                agent_id=agent.id,
                policy_version="v1",
                currency="USD",
                total_budget_minor=5000,
                per_tx_limit_minor=5000,
                daily_limit_minor=5000,
                human_approval_threshold_minor=4000,
                allowed_merchant_ids=[merchant.id],
                allowed_categories=["SOFTWARE"],
                status=PassportStatus.ACTIVE,
                expires_at=datetime.now(UTC) + timedelta(days=30),
            )
        )
        svc = GuardianService(ledger, pp_client)
        proposal, quote = SubmitProposalRequest(
            tenant_id=org.id,
            agent_id=agent.id,
            passport_id=passport.id,
            merchant_id=merchant.id,
            merchant_name="M1",
            merchant_category="SOFTWARE",
            amount_minor=1500,
            currency="USD",
            item_summary="API credits",
            line_items=[{"description": "Credits", "quantity": 1, "unit_price_minor": 1500}],
            rationale="worker test",
            idempotency_key="worker-rec-1",
        ).to_proposal_and_quote()
        intent, _ = svc.submit_proposal(proposal=proposal, quote=quote)
        intent, attempt = await svc.initiate_checkout(tenant_id=org.id, intent_id=intent.id)
        svc.handle_buyer_approved(tenant_id=org.id, intent_id=intent.id, attempt_id=attempt.id, payer_id="P1")
        intent, attempt = await svc.execute_capture(tenant_id=org.id, intent_id=intent.id, attempt_id=attempt.id)
        assert intent.state == PaymentState.PENDING_PROVIDER
        intent_id = intent.id
        tenant_id = org.id
        session.commit()

    # Now PayPal settled on remote side -> worker reconciles to CAPTURED
    pp_state["order_status"] = "COMPLETED"
    worker = OutboxWorker(session_factory, settings=settings, paypal_client=pp_client)
    rec = await worker.reconcile_pending_payments()
    assert rec["checked"] == 1
    assert rec["reconciled"] == 1

    with session_factory() as session:
        refreshed = LedgerRepository(session).get_intent(tenant_id, intent_id)
        assert refreshed is not None
        assert refreshed.state == PaymentState.SUCCEEDED
