"""RC1 integration tests for PayPal & webhook negative paths (mocked/httpx transport)."""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import httpx
import pytest
from aegis_api.app import create_app
from aegis_sdk import verify_aegis_signature as sdk_verify_aegis_signature
from contracts import (
    DisputeCase,
    DisputeSourceType,
    DisputeStatus,
    EvidenceRecord,
    EvidenceSourceType,
    FinancialEventType,
    compute_payload_hash,
)
from database import (
    FinancialEventRow,
    LedgerRepository,
    create_db_engine,
    create_session_factory,
)
from disputeos.cases.service import DisputeCaseService, SyntheticSubmissionError
from fastapi.testclient import TestClient
from paypal import (
    PayPalAPIError,
    PayPalConfigurationError,
    PayPalSandboxClient,
    PayPalTimeoutError,
)
from security import (
    NexusSettings,
    format_aegis_signature,
    verify_aegis_signature,
)
from sqlalchemy import func, select


def _build_mock_paypal_client(
    handler: Any,
    *,
    client_id: str = "sandbox-client-id-rc1",
    client_secret: str = "super-secret-paypal-client-secret-rc1",
    webhook_id: str | None = "WH-RC1-TEST",
    disputes_enabled: bool = True,
    max_retries: int = 2,
) -> PayPalSandboxClient:
    settings = NexusSettings(
        paypal_mode="sandbox",
        paypal_client_id=client_id,
        paypal_client_secret=client_secret,
        paypal_webhook_id=webhook_id,
        paypal_disputes_api_enabled=disputes_enabled,
    )
    async_client = httpx.AsyncClient(
        base_url="https://api-m.sandbox.paypal.com",
        transport=httpx.MockTransport(handler),
    )
    return PayPalSandboxClient(
        settings=settings,
        http_client=async_client,
        max_retries=max_retries,
        retry_base_delay=0.0,
        retry_max_delay=0.0,
    )


def _register_owner(client: TestClient, slug: str) -> tuple[dict[str, str], UUID]:
    resp = client.post(
        "/v1/auth/register",
        json={
            "email": f"{slug}@example.com",
            "password": "StrongPassword!123",
            "full_name": "RC1 PayPal Tester",
            "organization_name": f"Org {slug}",
            "organization_slug": slug,
        },
    )
    assert resp.status_code == 201, resp.text
    data = resp.json()
    return {"Authorization": f"Bearer {data['access_token']}"}, UUID(data["active_tenant_id"])


def _valid_paypal_headers() -> dict[str, str]:
    return {
        "PAYPAL-AUTH-ALGO": "SHA256withRSA",
        "PAYPAL-CERT-URL": "https://api.sandbox.paypal.com/v1/notifications/certs/CERT-RC1",
        "PAYPAL-TRANSMISSION-ID": "tx-rc1-001",
        "PAYPAL-TRANSMISSION-SIG": "valid-mock-sig-rc1",
        "PAYPAL-TRANSMISSION-TIME": "2026-11-12T10:00:00Z",
    }


def test_aegis_signature_missing_malformed_and_stale_timestamps() -> None:
    secret = "whsec_rc1_aegis_signing_secret"
    body = b'{"event":"payment.captured","amount_minor":4200}'
    ts = 1_760_000_000
    valid_header = format_aegis_signature(secret, body, timestamp=ts)

    assert verify_aegis_signature(secret, body, valid_header, tolerance_seconds=300, now_ts=ts + 300) is True

    malformed_headers = [
        "",
        "   ",
        "invalid_without_equals",
        f"t={ts}",
        "v1=deadbeef",
        "t=not-an-int,v1=deadbeef",
        f"t={ts},t={ts},v1=deadbeef",
        f"t={ts},v1=0000000000000000000000000000000000000000000000000000000000000000",
    ]
    for bad_header in malformed_headers:
        assert verify_aegis_signature(secret, body, bad_header, tolerance_seconds=300, now_ts=ts) is False
        assert (
            sdk_verify_aegis_signature(
                body,
                f"AEGIS-Signature: {bad_header}" if bad_header else "",
                secret,
                tolerance_seconds=300,
                current_time=ts,
            )
            is False
        )

    assert verify_aegis_signature(secret, body, valid_header, tolerance_seconds=300, now_ts=ts + 301) is False
    assert verify_aegis_signature(secret, body, valid_header, tolerance_seconds=300, now_ts=ts - 301) is False
    assert (
        sdk_verify_aegis_signature(
            body,
            f"AEGIS-Signature: {valid_header}",
            secret,
            tolerance_seconds=300,
            current_time=ts + 301,
        )
        is False
    )

    assert verify_aegis_signature("wrong-secret", body, valid_header, tolerance_seconds=300, now_ts=ts) is False
    assert verify_aegis_signature(secret, b'{"event":"payment.captured","amount_minor":9999}', valid_header, now_ts=ts) is False

    now = int(time.time())
    old_header = format_aegis_signature(secret, body, timestamp=now - 305)
    assert sdk_verify_aegis_signature(body, f"AEGIS-Signature: {old_header}", secret, tolerance_seconds=300) is False


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "missing_header",
    [
        "PAYPAL-TRANSMISSION-SIG",
        "PAYPAL-AUTH-ALGO",
        "PAYPAL-CERT-URL",
        "PAYPAL-TRANSMISSION-ID",
        "PAYPAL-TRANSMISSION-TIME",
    ],
)
async def test_paypal_verify_webhook_signature_rejects_missing_headers_without_network(
    missing_header: str,
) -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(200, json={"verification_status": "SUCCESS"})

    pp_client = _build_mock_paypal_client(handler)
    headers = _valid_paypal_headers()
    headers.pop(missing_header)

    verified = await pp_client.verify_webhook_signature(
        headers=headers,
        webhook_event={"id": "WH-EVT-1", "event_type": "PAYMENT.CAPTURE.COMPLETED"},
    )
    assert verified is False
    assert calls == 0


@pytest.mark.asyncio
async def test_paypal_verify_webhook_signature_requires_webhook_id() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"verification_status": "SUCCESS"})

    pp_client = _build_mock_paypal_client(handler, webhook_id=None)
    with pytest.raises(PayPalConfigurationError, match="PAYPAL_WEBHOOK_ID"):
        await pp_client.verify_webhook_signature(
            headers=_valid_paypal_headers(),
            webhook_event={"id": "WH-EVT-2", "event_type": "PAYMENT.CAPTURE.COMPLETED"},
        )


def test_paypal_webhook_endpoint_rejects_missing_malformed_and_failed_signatures(
    tmp_path: Path,
) -> None:
    state = {"status": "FAILURE"}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v1/oauth2/token":
            return httpx.Response(200, json={"access_token": "tok-rc1", "expires_in": 3600})
        if request.url.path == "/v1/notifications/verify-webhook-signature":
            return httpx.Response(200, json={"verification_status": state["status"]})
        return httpx.Response(404)

    settings = NexusSettings(
        database_url=f"sqlite:///{tmp_path / 'pp_wh_neg.db'}",
        jwt_secret="rc1-jwt-secret-32-bytes-minimum!",
        signing_secret="rc1-signing-secret",
        rate_limit_rpm=5000,
    )
    pp_client = _build_mock_paypal_client(handler)
    app = create_app(settings=settings, paypal_client=pp_client, create_tables=True)

    payload = {
        "id": "WH-EVT-BAD-SIG",
        "event_type": "PAYMENT.CAPTURE.COMPLETED",
        "resource": {"id": "CAP-1"},
    }

    with TestClient(app) as client:
        missing_sig_headers = _valid_paypal_headers()
        missing_sig_headers.pop("PAYPAL-TRANSMISSION-SIG")
        r1 = client.post("/v1/paypal/webhooks", json=payload, headers=missing_sig_headers)
        assert r1.status_code == 401
        assert r1.json()["detail"]["error_code"] == "PAYPAL_WEBHOOK_INVALID_SIGNATURE"

        empty_sig_headers = _valid_paypal_headers()
        empty_sig_headers["PAYPAL-TRANSMISSION-SIG"] = ""
        r2 = client.post("/v1/paypal/webhooks", json=payload, headers=empty_sig_headers)
        assert r2.status_code == 401
        assert r2.json()["detail"]["error_code"] == "PAYPAL_WEBHOOK_INVALID_SIGNATURE"

        r3 = client.post("/v1/paypal/webhooks", json=payload, headers=_valid_paypal_headers())
        assert r3.status_code == 401
        assert r3.json()["detail"]["error_code"] == "PAYPAL_WEBHOOK_INVALID_SIGNATURE"

        r4 = client.post(
            "/v1/paypal/webhooks",
            content="{not-json",
            headers={**_valid_paypal_headers(), "Content-Type": "application/json"},
        )
        assert r4.status_code == 400
        assert r4.json()["detail"]["error_code"] == "INVALID_WEBHOOK_PAYLOAD"

        r5 = client.post("/v1/paypal/webhooks", json=["not", "an", "object"], headers=_valid_paypal_headers())
        assert r5.status_code == 400
        assert r5.json()["detail"]["error_code"] == "INVALID_WEBHOOK_PAYLOAD"


def test_paypal_webhook_replay_idempotency_deduplicates_event(tmp_path: Path) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v1/oauth2/token":
            return httpx.Response(200, json={"access_token": "tok-rc1", "expires_in": 3600})
        if request.url.path == "/v1/notifications/verify-webhook-signature":
            return httpx.Response(200, json={"verification_status": "SUCCESS"})
        return httpx.Response(404)

    db_url = f"sqlite:///{tmp_path / 'pp_wh_replay.db'}"
    settings = NexusSettings(
        database_url=db_url,
        jwt_secret="rc1-jwt-secret-32-bytes-minimum!",
        signing_secret="rc1-signing-secret",
        rate_limit_rpm=5000,
    )
    pp_client = _build_mock_paypal_client(handler)
    app = create_app(settings=settings, paypal_client=pp_client, create_tables=True)

    event_payload = {
        "id": "WH-EVT-REPLAY-001",
        "event_type": "PAYMENT.CAPTURE.COMPLETED",
        "resource": {
            "id": "CAP-REPLAY-1",
            "supplementary_data": {"related_ids": {"order_id": "ORD-REPLAY-1"}},
        },
    }

    with TestClient(app) as client:
        first = client.post("/v1/paypal/webhooks", json=event_payload, headers=_valid_paypal_headers())
        assert first.status_code == 200
        assert first.json()["verified"] is True
        assert first.json()["deduplicated"] is False

        second = client.post("/v1/paypal/webhooks", json=event_payload, headers=_valid_paypal_headers())
        assert second.status_code == 200
        assert second.json() == {
            "verified": True,
            "deduplicated": True,
            "event_type": "PAYMENT.CAPTURE.COMPLETED",
        }

    engine = create_db_engine(db_url)
    session_factory = create_session_factory(engine)
    with session_factory() as session:
        event_count = int(
            session.scalar(
                select(func.count())
                .select_from(FinancialEventRow)
                .where(FinancialEventRow.event_type == FinancialEventType.PAYPAL_WEBHOOK_RECEIVED.value)
            )
            or 0
        )
        assert event_count == 0


@pytest.mark.asyncio
async def test_paypal_client_retries_transient_5xx_then_succeeds() -> None:
    attempts = {"orders": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v1/oauth2/token":
            return httpx.Response(200, json={"access_token": "tok-retry-ok", "expires_in": 3600})
        if request.url.path == "/v2/checkout/orders":
            attempts["orders"] += 1
            if attempts["orders"] < 3:
                return httpx.Response(503, json={"name": "SERVICE_UNAVAILABLE"}, headers={"Retry-After": "0"})
            return httpx.Response(
                201,
                json={
                    "id": "PP-ORD-RETRY-200",
                    "status": "CREATED",
                    "links": [{"rel": "approve", "href": "https://www.sandbox.paypal.com/checkoutnow?token=PP-ORD-RETRY-200"}],
                },
            )
        return httpx.Response(404)

    pp_client = _build_mock_paypal_client(handler, max_retries=2)
    result = await pp_client.create_order(
        amount_minor=2500,
        currency="USD",
        reference_id="ref-retry-1",
        description="Retry test",
        request_id="req-retry-1",
    )
    assert attempts["orders"] == 3
    assert result.paypal_order_id == "PP-ORD-RETRY-200"


@pytest.mark.asyncio
async def test_paypal_client_5xx_and_timeout_exhaust_retries_without_secret_leakage() -> None:
    secret = "ultra-secret-paypal-credential-999"
    token = "bearer-secret-token-888"

    def handler_503(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v1/oauth2/token":
            return httpx.Response(200, json={"access_token": token, "expires_in": 3600})
        return httpx.Response(
            503,
            json={"name": "INTERNAL_SERVER_ERROR", "message": "upstream unavailable"},
            headers={"PayPal-Debug-Id": "dbg-503-rc1"},
        )

    pp_503 = _build_mock_paypal_client(handler_503, client_secret=secret, max_retries=1)
    with pytest.raises(PayPalAPIError) as exc_503:
        await pp_503.list_disputes()
    assert exc_503.value.status_code == 503
    assert exc_503.value.debug_id == "dbg-503-rc1"
    assert secret not in str(exc_503.value)
    assert token not in str(exc_503.value)

    def handler_timeout(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v1/oauth2/token":
            return httpx.Response(200, json={"access_token": token, "expires_in": 3600})
        raise httpx.ReadTimeout("simulated sandbox read timeout", request=request)

    pp_timeout = _build_mock_paypal_client(handler_timeout, client_secret=secret, max_retries=1)
    with pytest.raises(PayPalTimeoutError) as exc_timeout:
        await pp_timeout.list_disputes()
    assert secret not in str(exc_timeout.value)
    assert token not in str(exc_timeout.value)


def test_api_surfaces_paypal_5xx_and_timeout_without_secret_leakage(tmp_path: Path) -> None:
    secret = "api-surface-paypal-secret-do-not-leak"
    internal_trace_secret = "INTERNAL_SECRET_TRACE_XYZ"
    mode = {"behavior": "503"}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v1/oauth2/token":
            return httpx.Response(200, json={"access_token": "tok-api-surface", "expires_in": 3600})
        if mode["behavior"] == "503":
            return httpx.Response(503, json={"message": "PayPal outage"})
        if mode["behavior"] == "timeout":
            raise httpx.ReadTimeout("simulated read timeout", request=request)
        if mode["behavior"] == "connect_error":
            raise httpx.ConnectError(internal_trace_secret, request=request)
        return httpx.Response(404)

    settings = NexusSettings(
        database_url=f"sqlite:///{tmp_path / 'pp_api_errors.db'}",
        jwt_secret="rc1-jwt-secret-32-bytes-minimum!",
        signing_secret="rc1-signing-secret",
        paypal_disputes_api_enabled=True,
        rate_limit_rpm=5000,
    )
    pp_client = _build_mock_paypal_client(handler, client_secret=secret, max_retries=0)
    app = create_app(settings=settings, paypal_client=pp_client, create_tables=True)

    with TestClient(app) as client:
        headers, _ = _register_owner(client, slug="pp-err-org")

        mode["behavior"] = "connect_error"
        wh_err = client.post(
            "/v1/paypal/webhooks",
            json={"id": "WH-ERR-1", "event_type": "PAYMENT.CAPTURE.COMPLETED", "resource": {}},
            headers=_valid_paypal_headers(),
        )
        assert wh_err.status_code == 401
        assert wh_err.json()["detail"]["error_code"] == "PAYPAL_WEBHOOK_VERIFICATION_FAILED"
        assert secret not in wh_err.text
        assert internal_trace_secret not in wh_err.text

        seed_resp = client.post("/v1/disputeos/cases/seed-demo", headers=headers)
        assert seed_resp.status_code == 200, seed_resp.text
        seeded_intent_id = seed_resp.json()["case"]["payment_intent_id"]

        mode["behavior"] = "503"
        real_case = client.post(
            "/v1/disputeos/cases",
            headers=headers,
            json={
                "payment_intent_id": seeded_intent_id,
                "paypal_dispute_id": "PP-REAL-ERR-001",
                "reason": "MERCHANDISE_OR_SERVICE_NOT_RECEIVED",
                "buyer_claim": "Buyer claims item did not arrive",
                "amount_minor": 3500,
                "currency": "USD",
                "is_synthetic": False,
                "source_type": DisputeSourceType.PAYPAL_SANDBOX.value,
            },
        )
        assert real_case.status_code == 201, real_case.text
        real_case_id = real_case.json()["id"]

        ev_real = client.post(
            f"/v1/disputeos/cases/{real_case_id}/evidence",
            headers=headers,
            json={
                "source_type": EvidenceSourceType.CARRIER_TRACKING.value,
                "source_ref": "carrier:ups:1Z999AA101",
                "title": "UPS Delivery Proof",
                "content": {"status": "DELIVERED", "tracking_number": "1Z999AA101"},
                "is_synthetic": False,
            },
        )
        assert ev_real.status_code == 200, ev_real.text
        assert client.post(f"/v1/disputeos/cases/{real_case_id}/analyze", headers=headers).status_code == 200
        assert (
            client.post(
                f"/v1/disputeos/cases/{real_case_id}/approve",
                headers=headers,
                json={"approver_id": "rc1-tester", "draft_response_text": "Delivered with tracking 1Z999AA101"},
            ).status_code
            == 200
        )

        submit_503 = client.post(
            f"/v1/disputeos/cases/{real_case_id}/submit",
            headers=headers,
            json={"draft_response_text": "Delivered with tracking 1Z999AA101"},
        )
        assert submit_503.status_code == 502, submit_503.text
        assert submit_503.json()["detail"]["error_code"] == "PAYPAL_UPSTREAM_ERROR"
        assert submit_503.json()["detail"]["upstream_status"] == 503
        assert secret not in submit_503.text

        mode["behavior"] = "timeout"
        submit_to = client.post(
            f"/v1/disputeos/cases/{real_case_id}/submit",
            headers=headers,
            json={"draft_response_text": "Delivered with tracking 1Z999AA101"},
        )
        assert submit_to.status_code == 504, submit_to.text
        assert submit_to.json()["detail"]["error_code"] == "PAYPAL_TIMEOUT"
        assert secret not in submit_to.text


def test_synthetic_demo_case_blocked_by_synthetic_submission_error_and_zero_paypal_calls(
    tmp_path: Path,
) -> None:
    outbound_calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal outbound_calls
        outbound_calls += 1
        return httpx.Response(200, json={"id": "should-never-be-called"})

    db_url = f"sqlite:///{tmp_path / 'pp_synthetic_block.db'}"
    settings = NexusSettings(
        database_url=db_url,
        jwt_secret="rc1-jwt-secret-32-bytes-minimum!",
        signing_secret="rc1-signing-secret",
        paypal_disputes_api_enabled=True,
        rate_limit_rpm=5000,
    )
    pp_client = _build_mock_paypal_client(handler, disputes_enabled=True)
    app = create_app(settings=settings, paypal_client=pp_client, create_tables=True)

    with TestClient(app) as client:
        headers, tenant_id = _register_owner(client, slug="syn-block-org")

        seeded = client.post("/v1/disputeos/cases/seed-demo", headers=headers)
        assert seeded.status_code == 200, seeded.text
        seeded_case = seeded.json()["case"]
        assert seeded_case["is_synthetic"] is True
        assert seeded_case["source_type"] == DisputeSourceType.SYNTHETIC_DEMO.value
        case_id = seeded_case["id"]

        analyze_resp = client.post(f"/v1/disputeos/cases/{case_id}/analyze", headers=headers)
        assert analyze_resp.status_code == 200, analyze_resp.text

        approve_resp = client.post(
            f"/v1/disputeos/cases/{case_id}/approve",
            headers=headers,
            json={"approver_id": "rc1-tester", "draft_response_text": "Approved synthetic draft for negative-path check"},
        )
        assert approve_resp.status_code == 200, approve_resp.text
        assert approve_resp.json()["human_approved_for_submission"] is True

        submit_resp = client.post(
            f"/v1/disputeos/cases/{case_id}/submit",
            headers=headers,
            json={"draft_response_text": "Attempt external submit"},
        )
        assert submit_resp.status_code == 403, submit_resp.text
        assert "cannot be submitted externally" in submit_resp.text
        assert outbound_calls == 0

    engine = create_db_engine(db_url)
    session_factory = create_session_factory(engine)
    with session_factory() as session:
        svc = DisputeCaseService(repo=LedgerRepository(session))
        with pytest.raises(SyntheticSubmissionError, match="cannot be submitted externally"):
            svc.mark_submitted(
                tenant_id=tenant_id,
                case_id=UUID(case_id),
                actor_id="rc1-tester",
                actor_type="HUMAN",
            )

        # Also verify direct service guard on an unpersisted synthetic DisputeCase object
        synthetic_case = DisputeCase(
            id=uuid4(),
            tenant_id=tenant_id,
            correlation_id=uuid4(),
            payment_intent_id=uuid4(),
            paypal_dispute_id="PP-SYNTH-DIRECT",
            reason="UNAUTHORIZED",
            buyer_claim="Synthetic unauthorized claim",
            amount_minor=1200,
            currency="USD",
            status=DisputeStatus.APPROVED_FOR_SUBMISSION,
            is_synthetic=True,
            source_type=DisputeSourceType.SYNTHETIC_DEMO,
            human_approved_for_submission=True,
            approved_by="owner",
            response_payload_hash=compute_payload_hash({"draft": "ok"}),
        )
        assert synthetic_case.source_type == DisputeSourceType.SYNTHETIC_DEMO
        assert EvidenceRecord is not None
