"""Tests for AEGIS OutboxWorker: webhook delivery, HMAC signing, backoff/dead-letter, and reconciliation."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import httpx
import pytest
from aegis_sdk import verify_webhook_signature
from aegis_worker import OutboxWorker
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
    PlatformRepository,
    create_db_engine,
    create_session_factory,
    init_db,
)
from guardian import GuardianService
from guardian.api.models import SubmitProposalRequest
from paypal import PayPalSandboxClient
from security import NexusSettings


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
    received_deliveries: list[tuple[dict, str]] = []
    mode = {"fail": False}

    def webhook_handler(request: httpx.Request) -> httpx.Response:
        if mode["fail"]:
            return httpx.Response(500, text="temporary upstream failure")
        body = json.loads(request.content.decode("utf-8"))
        sig = request.headers.get("X-AEGIS-Signature", "")
        received_deliveries.append((body, sig))
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
        payload_body, sig_header = received_deliveries[0]
        assert verify_webhook_signature(
            payload_body=payload_body,
            signature_header=sig_header,
            signing_secret=secret,
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
            deliveries = platform.list_webhook_deliveries(tenant_id)
            assert any(d.status == "FAILED" for d in deliveries)

            # Requeue dead letter and recover once receiver is healthy
            platform.requeue_dead_letter_outbox(tenant_id, dead_id)
            session.commit()

        mode["fail"] = False
        r3 = await worker.process_outbox_batch(now=t0 + timedelta(seconds=30))
        assert r3["published"] == 1


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
