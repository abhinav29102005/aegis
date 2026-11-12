"""API tests for webhook SSRF protection, secret masking, pagination, and PayPal webhook hardening."""

from __future__ import annotations

import socket
import sys
import types
from pathlib import Path
from uuid import UUID, uuid4

import httpx
import pytest
from aegis_api.app import create_app
from contracts import FinancialEventType
from database import (
    LedgerRepository,
    PlatformRepository,
    create_db_engine,
    create_session_factory,
)
from fastapi.testclient import TestClient
from paypal import PayPalSandboxClient
from security import NexusSettings


def _build_mock_paypal_client() -> tuple[PayPalSandboxClient, dict[str, str]]:
    state: dict[str, str] = {"mode": "success"}

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path == "/v1/oauth2/token":
            return httpx.Response(200, json={"access_token": "mock-pp-token", "expires_in": 3600})
        if path == "/v1/notifications/verify-webhook-signature":
            if state["mode"] == "error":
                raise httpx.ConnectError("INTERNAL_PAYPAL_SECRET_TRACE_9000")
            verdict = "SUCCESS" if state["mode"] == "success" else "FAILURE"
            return httpx.Response(200, json={"verification_status": verdict})
        return httpx.Response(404)

    settings = NexusSettings(
        paypal_client_id="sandbox-client",
        paypal_client_secret="sandbox-secret",
        paypal_webhook_id="WH-TEST-1",
    )
    async_client = httpx.AsyncClient(
        base_url="https://api-m.sandbox.paypal.com",
        transport=httpx.MockTransport(handler),
    )
    return PayPalSandboxClient(settings=settings, http_client=async_client), state


def _register_owner(client: TestClient, slug: str = "wh-org") -> tuple[dict[str, str], UUID]:
    resp = client.post(
        "/v1/auth/register",
        json={
            "email": f"{slug}@example.com",
            "password": "StrongPassword!123",
            "full_name": "Webhook Owner",
            "organization_name": f"Org {slug}",
            "organization_slug": slug,
        },
    )
    assert resp.status_code == 201
    data = resp.json()
    return {"Authorization": f"Bearer {data['access_token']}"}, UUID(data["active_tenant_id"])


def test_webhook_registration_ssrf_and_secret_masking(tmp_path: Path) -> None:
    db_path = tmp_path / "wh_ssrf.db"
    settings = NexusSettings(
        database_url=f"sqlite:///{db_path}",
        jwt_secret="test-jwt-secret-for-webhooks-32b",
        signing_secret="test-hmac-secret-for-webhooks",
        rate_limit_rpm=5000,
    )
    pp_client, _ = _build_mock_paypal_client()
    app = create_app(settings=settings, paypal_client=pp_client, create_tables=True)

    with TestClient(app) as client:
        headers, _ = _register_owner(client, slug="ssrf-org")

        blocked_urls = [
            "http://169.254.169.254/latest/meta-data/",
            "http://127.0.0.1:8080/hook",
            "https://[::1]/hook",
            "http://localhost/hook",
            "https://metadata.google.internal/computeMetadata/v1/",
            "https://internal-svc.local/hook",
            "https://10.0.0.12/hook",
            "https://user:pass@hooks.customer.example/events",
        ]
        for bad_url in blocked_urls:
            resp = client.post(
                "/v1/webhooks/endpoints",
                headers=headers,
                json={"url": bad_url, "description": "blocked"},
            )
            assert resp.status_code == 422, f"Expected 422 for {bad_url}, got {resp.status_code}"
            assert resp.json()["detail"]["error_code"] == "INVALID_WEBHOOK_URL"

        created = client.post(
            "/v1/webhooks/endpoints",
            headers=headers,
            json={"url": "https://hooks.customer.example/events", "description": "prod receiver"},
        )
        assert created.status_code == 201
        created_data = created.json()
        assert created_data["signing_secret"].startswith("whsec_")

        listed = client.get("/v1/webhooks/endpoints", headers=headers)
        assert listed.status_code == 200
        assert listed.headers["X-Total-Count"] == "1"
        items = listed.json()
        assert len(items) == 1
        assert "signing_secret" not in items[0]


def test_webhook_registration_production_dns_rebinding_and_https(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db_path = tmp_path / "wh_prod_ssrf.db"
    settings = NexusSettings(
        app_env="production",
        database_url=f"sqlite:///{db_path}",
        jwt_secret="prod-jwt-secret-at-least-32-characters-long",
        signing_secret="prod-signing-secret-at-least-32-chars",
        api_key="prod-api-key-at-least-24-chars",
        rate_limit_rpm=5000,
    )
    pp_client, _ = _build_mock_paypal_client()
    app = create_app(settings=settings, paypal_client=pp_client, create_tables=True)

    resolved_ip = {"ip": "127.0.0.1"}

    def fake_getaddrinfo(host: str, port: int, *args, **kwargs):
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (resolved_ip["ip"], port))]

    monkeypatch.setattr(socket, "getaddrinfo", fake_getaddrinfo)

    with TestClient(app) as client:
        headers, _ = _register_owner(client, slug="prod-ssrf-org")

        # HTTP rejected in production (webhook_require_https=True)
        http_resp = client.post(
            "/v1/webhooks/endpoints",
            headers=headers,
            json={"url": "http://93.184.216.34/hook"},
        )
        assert http_resp.status_code == 422
        assert http_resp.json()["detail"]["error_code"] == "INVALID_WEBHOOK_URL"

        # DNS resolving to loopback rejected
        rebind_resp = client.post(
            "/v1/webhooks/endpoints",
            headers=headers,
            json={"url": "https://rebind.customer.example/hook"},
        )
        assert rebind_resp.status_code == 422
        assert rebind_resp.json()["detail"]["error_code"] == "INVALID_WEBHOOK_URL"

        # DNS resolving to public IP succeeds
        resolved_ip["ip"] = "93.184.216.34"
        ok_resp = client.post(
            "/v1/webhooks/endpoints",
            headers=headers,
            json={"url": "https://hooks.customer.example/events"},
        )
        assert ok_resp.status_code == 201


def test_webhooks_deliveries_and_outbox_pagination(tmp_path: Path) -> None:
    db_path = tmp_path / "wh_page.db"
    db_url = f"sqlite:///{db_path}"
    settings = NexusSettings(
        database_url=db_url,
        jwt_secret="test-jwt-secret-for-pagination-32b",
        signing_secret="test-hmac-secret-for-pagination",
        rate_limit_rpm=5000,
    )
    pp_client, _ = _build_mock_paypal_client()
    app = create_app(settings=settings, paypal_client=pp_client, create_tables=True)

    with TestClient(app) as client:
        headers, tenant_id = _register_owner(client, slug="page-org")

        for idx in range(3):
            resp = client.post(
                "/v1/webhooks/endpoints",
                headers=headers,
                json={"url": f"https://hooks{idx}.customer.example/events"},
            )
            assert resp.status_code == 201

        engine = create_db_engine(db_url)
        session_factory = create_session_factory(engine)
        try:
            with session_factory() as session:
                ledger = LedgerRepository(session)
                platform = PlatformRepository(session)
                endpoints = platform.list_webhook_endpoints(tenant_id)
                for idx in range(3):
                    ledger.append_financial_event(
                        tenant_id=tenant_id,
                        correlation_id=uuid4(),
                        payment_intent_id=None,
                        event_type=FinancialEventType.PROPOSAL_CREATED,
                        actor_type="SYSTEM",
                        actor_id="test",
                        payload={"idx": idx},
                    )
                from database import WebhookDeliveryRow

                for idx in range(3):
                    session.add(
                        WebhookDeliveryRow(
                            id=uuid4(),
                            tenant_id=tenant_id,
                            endpoint_id=endpoints[0].id,
                            outbox_event_id=None,
                            event_type="PROPOSAL_CREATED",
                            payload={"idx": idx},
                            status="DELIVERED",
                            attempts=1,
                            response_status=200,
                        )
                    )
                session.commit()
        finally:
            engine.dispose()

        ep_p1 = client.get("/v1/webhooks/endpoints", headers=headers, params={"limit": 2, "offset": 0})
        ep_p2 = client.get("/v1/webhooks/endpoints", headers=headers, params={"limit": 2, "offset": 2})
        assert ep_p1.status_code == 200
        assert ep_p1.headers["X-Total-Count"] == "3"
        assert len(ep_p1.json()) == 2
        assert len(ep_p2.json()) == 1
        assert ep_p1.json()[0]["id"] != ep_p2.json()[0]["id"]

        del_p1 = client.get("/v1/webhooks/deliveries", headers=headers, params={"limit": 2, "offset": 1})
        assert del_p1.status_code == 200
        assert del_p1.headers["X-Total-Count"] == "3"
        assert len(del_p1.json()) == 2

        out_p1 = client.get(
            "/v1/worker/outbox",
            headers=headers,
            params={"status_filter": "PENDING", "limit": 2, "offset": 0},
        )
        out_p2 = client.get(
            "/v1/worker/outbox",
            headers=headers,
            params={"status_filter": "PENDING", "limit": 2, "offset": 2},
        )
        assert out_p1.status_code == 200
        assert out_p1.headers["X-Total-Count"] == "3"
        assert len(out_p1.json()) == 2
        assert len(out_p2.json()) == 1


def test_paypal_webhook_error_sanitization_dedup_and_dispute_hook(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db_path = tmp_path / "pp_wh.db"
    settings = NexusSettings(
        database_url=f"sqlite:///{db_path}",
        jwt_secret="test-jwt-secret-for-paypal-wh-32b",
        signing_secret="test-hmac-secret-for-paypal-wh",
        rate_limit_rpm=5000,
    )
    pp_client, pp_state = _build_mock_paypal_client()
    app = create_app(settings=settings, paypal_client=pp_client, create_tables=True)

    pp_headers = {
        "paypal-auth-algo": "SHA256withRSA",
        "paypal-cert-url": "https://api.sandbox.paypal.com/v1/notifications/certs/CERT-1",
        "paypal-transmission-id": "TX-1",
        "paypal-transmission-sig": "sig-1",
        "paypal-transmission-time": "2026-11-11T00:00:00Z",
    }

    with TestClient(app) as client:
        # Verification exception must be sanitized (no internal error text leaked)
        pp_state["mode"] = "error"
        err_resp = client.post(
            "/v1/paypal/webhooks",
            headers=pp_headers,
            json={"id": "WH-ERR-1", "event_type": "PAYMENT.CAPTURE.COMPLETED"},
        )
        assert err_resp.status_code == 401
        assert err_resp.json()["detail"]["error_code"] == "PAYPAL_WEBHOOK_VERIFICATION_FAILED"
        assert err_resp.json()["detail"]["message"] == "PayPal webhook verification failed."
        assert "INTERNAL_PAYPAL_SECRET_TRACE_9000" not in err_resp.text

        # Invalid signature fails closed
        pp_state["mode"] = "failure"
        bad_resp = client.post(
            "/v1/paypal/webhooks",
            headers=pp_headers,
            json={"id": "WH-BAD-1", "event_type": "PAYMENT.CAPTURE.COMPLETED"},
        )
        assert bad_resp.status_code == 401
        assert bad_resp.json()["detail"]["error_code"] == "PAYPAL_WEBHOOK_INVALID_SIGNATURE"

        # Valid webhook recorded once, duplicate event_id deduplicated
        pp_state["mode"] = "success"
        evt = {
            "id": "WH-DEDUP-1",
            "event_type": "PAYMENT.CAPTURE.COMPLETED",
            "resource": {"id": "CAP-1"},
        }
        first = client.post("/v1/paypal/webhooks", headers=pp_headers, json=evt)
        assert first.status_code == 200
        assert first.json()["verified"] is True
        assert first.json()["deduplicated"] is False

        dup = client.post("/v1/paypal/webhooks", headers=pp_headers, json=evt)
        assert dup.status_code == 200
        assert dup.json() == {
            "verified": True,
            "deduplicated": True,
            "event_type": "PAYMENT.CAPTURE.COMPLETED",
        }

        # CUSTOMER.DISPUTE.* falls back cleanly if handler module not installed
        with monkeypatch.context() as mp:
            mp.setitem(sys.modules, "disputeos.paypal.webhook_handler", None)
            dispute_evt_missing = {
                "id": "WH-DISP-MISSING",
                "event_type": "CUSTOMER.DISPUTE.CREATED",
                "resource": {"id": "PP-D-MISSING"},
            }
            disp_missing_resp = client.post(
                "/v1/paypal/webhooks", headers=pp_headers, json=dispute_evt_missing
            )
            assert disp_missing_resp.status_code == 200
            assert disp_missing_resp.json()["dispute_handler"] == "not_installed_yet"

        # When real disputeos.paypal.webhook_handler is installed, unknown disputes fail safely
        dispute_evt = {
            "id": "WH-DISP-1",
            "event_type": "CUSTOMER.DISPUTE.CREATED",
            "resource": {"id": "PP-D-100"},
        }
        disp_resp = client.post("/v1/paypal/webhooks", headers=pp_headers, json=dispute_evt)
        assert disp_resp.status_code == 200
        assert disp_resp.json()["dispute_handler"]["handled"] is False

        # When disputeos.paypal.webhook_handler is installed, it is invoked
        called: list[tuple[str, dict, str]] = []
        fake_mod = types.ModuleType("disputeos.paypal.webhook_handler")

        def handle_paypal_dispute_webhook(ledger, event_type: str, resource: dict, event_id: str):
            called.append((event_type, resource, event_id))
            return {"handled": True, "dispute_id": resource.get("id")}

        fake_mod.handle_paypal_dispute_webhook = handle_paypal_dispute_webhook  # type: ignore[attr-defined]
        monkeypatch.setitem(sys.modules, "disputeos.paypal.webhook_handler", fake_mod)

        dispute_evt_2 = {
            "id": "WH-DISP-2",
            "event_type": "CUSTOMER.DISPUTE.UPDATED",
            "resource": {"id": "PP-D-200"},
        }
        disp_resp_2 = client.post("/v1/paypal/webhooks", headers=pp_headers, json=dispute_evt_2)
        assert disp_resp_2.status_code == 200
        assert disp_resp_2.json()["dispute_handler"] == {"handled": True, "dispute_id": "PP-D-200"}
        assert called == [("CUSTOMER.DISPUTE.UPDATED", {"id": "PP-D-200"}, "WH-DISP-2")]
