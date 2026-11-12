"""Tests for nexus-paypal sandbox adapter using MockTransport (no live PayPal claims)."""

import json

import httpx
import pytest
from paypal import (
    PayPalAPIError,
    PayPalConfigurationError,
    PayPalDisputesDisabledError,
    PayPalSandboxClient,
    PayPalTimeoutError,
    minor_to_paypal_value,
    paypal_value_to_minor,
)
from security import NexusSettings


def _sandbox_settings(**overrides) -> NexusSettings:
    defaults = {
        "paypal_mode": "sandbox",
        "paypal_base_url": "https://api-m.sandbox.paypal.com",
        "paypal_client_id": "sb-client-id",
        "paypal_client_secret": "sb-client-secret",
        "paypal_webhook_id": "WH-123",
        "paypal_disputes_api_enabled": False,
    }
    defaults.update(overrides)
    return NexusSettings(**defaults)


def test_minor_to_paypal_value_formatting() -> None:
    assert minor_to_paypal_value(3900) == "39.00"
    assert minor_to_paypal_value(5) == "0.05"
    assert minor_to_paypal_value(1500, "JPY") == "1500"
    assert minor_to_paypal_value(12500, "KWD") == "12.500"
    assert minor_to_paypal_value(1005, "BHD") == "1.005"

    assert paypal_value_to_minor("39.00", "USD") == 3900
    assert paypal_value_to_minor("1500", "JPY") == 1500
    assert paypal_value_to_minor("12.500", "KWD") == 12500
    assert paypal_value_to_minor("1.005", "BHD") == 1005


@pytest.mark.asyncio
async def test_refund_and_void_operations() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v1/oauth2/token":
            return httpx.Response(200, json={"access_token": "tok-123", "expires_in": 3600})
        if request.url.path == "/v2/payments/captures/CAP-1/refund":
            return httpx.Response(201, json={"id": "REF-1", "status": "COMPLETED", "amount": {"value": "39.00", "currency_code": "USD"}})
        if request.url.path == "/v2/payments/authorizations/AUTH-1/void":
            return httpx.Response(204)
        return httpx.Response(404)

    async_client = httpx.AsyncClient(base_url="https://api-m.sandbox.paypal.com", transport=httpx.MockTransport(handler))
    client = PayPalSandboxClient(_sandbox_settings(), http_client=async_client)

    refund = await client.refund_capture(capture_id="CAP-1", amount_minor=3900, currency="USD")
    assert refund["id"] == "REF-1" or getattr(refund, "refund_id", "") == "REF-1"
    assert refund["status"] == "COMPLETED" or getattr(refund, "status", "") == "COMPLETED"

    void_res = await client.void_authorization(authorization_id="AUTH-1")
    assert void_res["status"] == "VOIDED"
    await async_client.aclose()


@pytest.mark.asyncio
async def test_disputes_provide_evidence_and_accept_claim() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v1/oauth2/token":
            return httpx.Response(200, json={"access_token": "tok-123", "expires_in": 3600})
        if request.url.path == "/v1/customer/disputes/DISP-1/provide-evidence":
            return httpx.Response(200, json={"status": "EVIDENCE_SUBMITTED"})
        if request.url.path == "/v1/customer/disputes/DISP-1/accept-claim":
            return httpx.Response(200, json={"status": "CLAIM_ACCEPTED"})
        return httpx.Response(404)

    async_client = httpx.AsyncClient(base_url="https://api-m.sandbox.paypal.com", transport=httpx.MockTransport(handler))
    client = PayPalSandboxClient(_sandbox_settings(paypal_disputes_api_enabled=True), http_client=async_client)

    ev_res = await client.provide_evidence(dispute_id="DISP-1", evidence_type="PROOF_OF_FULFILLMENT")
    assert ev_res["status"] == "EVIDENCE_SUBMITTED" or ev_res.get("status") == "EVIDENCE_SUBMITTED"

    claim_res = await client.accept_claim(dispute_id="DISP-1", note="Settled")
    assert claim_res["status"] == "CLAIM_ACCEPTED" or claim_res.get("status") == "CLAIM_ACCEPTED"
    await async_client.aclose()


@pytest.mark.asyncio
async def test_missing_credentials_fail_closed() -> None:
    client = PayPalSandboxClient(_sandbox_settings(paypal_client_id="", paypal_client_secret=""))
    with pytest.raises(PayPalConfigurationError):
        await client.get_access_token()


@pytest.mark.asyncio
async def test_disputes_api_requires_feature_flag() -> None:
    client = PayPalSandboxClient(_sandbox_settings(paypal_disputes_api_enabled=False))
    with pytest.raises(PayPalDisputesDisabledError):
        await client.list_disputes()
    with pytest.raises(PayPalDisputesDisabledError):
        await client.provide_evidence("PP-D-1", {"evidence_type": "PROOF_OF_DELIVERY"})
    with pytest.raises(PayPalDisputesDisabledError):
        await client.accept_claim("PP-D-1", note="Accepted")


@pytest.mark.asyncio
async def test_create_and_verified_capture_flow() -> None:
    state = {"get_calls": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v1/oauth2/token":
            return httpx.Response(200, json={"access_token": "tok-123", "expires_in": 3600})
        if request.url.path == "/v2/checkout/orders" and request.method == "POST":
            body = json.loads(request.content)
            assert body["purchase_units"][0]["amount"]["value"] == "39.00"
            return httpx.Response(
                201,
                json={
                    "id": "ORD-SB-1",
                    "status": "CREATED",
                    "links": [{"rel": "approve", "href": "https://www.sandbox.paypal.com/checkoutnow?token=ORD-SB-1"}],
                },
            )
        if request.url.path == "/v2/checkout/orders/ORD-SB-1" and request.method == "GET":
            state["get_calls"] += 1
            if state["get_calls"] == 1:
                return httpx.Response(200, json={"id": "ORD-SB-1", "status": "APPROVED"})
            return httpx.Response(
                200,
                json={
                    "id": "ORD-SB-1",
                    "status": "COMPLETED",
                    "purchase_units": [
                        {
                            "payments": {
                                "captures": [
                                    {"id": "CAP-SB-1", "status": "COMPLETED", "amount": {"currency_code": "USD", "value": "39.00"}}
                                ]
                            }
                        }
                    ],
                },
            )
        if request.url.path == "/v2/checkout/orders/ORD-SB-1/capture" and request.method == "POST":
            return httpx.Response(201, json={"id": "ORD-SB-1", "status": "COMPLETED"})
        return httpx.Response(404)

    async_client = httpx.AsyncClient(base_url="https://api-m.sandbox.paypal.com", transport=httpx.MockTransport(handler))
    client = PayPalSandboxClient(_sandbox_settings(), http_client=async_client, retry_base_delay=0.0)

    created = await client.create_order(
        amount_minor=3900,
        currency="USD",
        reference_id="intent-1",
        description="CloudCompute API Tier",
        request_id="req-1",
    )
    assert created.paypal_order_id == "ORD-SB-1"
    assert "sandbox.paypal.com" in (created.approval_url or "")

    captured = await client.capture_order(
        paypal_order_id="ORD-SB-1",
        expected_amount_minor=3900,
        expected_currency="USD",
        request_id="cap-req-1",
    )
    assert captured.verified_capture.paypal_capture_id == "CAP-SB-1"
    assert captured.verified_capture.verified_amount_minor == 3900
    await async_client.aclose()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("currency", "amount_minor", "expected_value"),
    [
        ("JPY", 1500, "1500"),
        ("KWD", 12500, "12.500"),
    ],
)
async def test_multicurrency_order_and_capture_precision(
    currency: str,
    amount_minor: int,
    expected_value: str,
) -> None:
    state = {"get_calls": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v1/oauth2/token":
            return httpx.Response(200, json={"access_token": "tok-mc", "expires_in": 3600})
        if request.url.path == "/v2/checkout/orders" and request.method == "POST":
            body = json.loads(request.content)
            amount_obj = body["purchase_units"][0]["amount"]
            assert amount_obj["currency_code"] == currency
            assert amount_obj["value"] == expected_value
            return httpx.Response(201, json={"id": f"ORD-{currency}", "status": "CREATED", "links": []})
        if request.url.path == f"/v2/checkout/orders/ORD-{currency}" and request.method == "GET":
            state["get_calls"] += 1
            if state["get_calls"] == 1:
                return httpx.Response(200, json={"id": f"ORD-{currency}", "status": "APPROVED"})
            return httpx.Response(
                200,
                json={
                    "id": f"ORD-{currency}",
                    "status": "COMPLETED",
                    "purchase_units": [
                        {
                            "payments": {
                                "captures": [
                                    {
                                        "id": f"CAP-{currency}",
                                        "status": "COMPLETED",
                                        "amount": {"currency_code": currency, "value": expected_value},
                                    }
                                ]
                            }
                        }
                    ],
                },
            )
        if request.url.path == f"/v2/checkout/orders/ORD-{currency}/capture":
            return httpx.Response(201, json={"id": f"ORD-{currency}", "status": "COMPLETED"})
        return httpx.Response(404)

    async_client = httpx.AsyncClient(base_url="https://api-m.sandbox.paypal.com", transport=httpx.MockTransport(handler))
    client = PayPalSandboxClient(_sandbox_settings(), http_client=async_client, retry_base_delay=0.0)

    created = await client.create_order(
        amount_minor=amount_minor,
        currency=currency,
        reference_id=f"ref-{currency}",
        description="Multi-currency test",
        request_id=f"req-{currency}",
    )
    assert created.paypal_order_id == f"ORD-{currency}"

    captured = await client.capture_order(
        paypal_order_id=f"ORD-{currency}",
        expected_amount_minor=amount_minor,
        expected_currency=currency,
        request_id=f"cap-{currency}",
    )
    assert captured.verified_capture.verified_amount_minor == amount_minor
    assert captured.verified_capture.verified_currency == currency
    await async_client.aclose()


@pytest.mark.asyncio
async def test_transient_retries_recover_from_429_5xx_and_transport_errors() -> None:
    attempts = {"order": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v1/oauth2/token":
            return httpx.Response(200, json={"access_token": "tok-retry", "expires_in": 3600})
        if request.url.path == "/v2/checkout/orders":
            attempts["order"] += 1
            if attempts["order"] == 1:
                raise httpx.ConnectError("transient socket reset", request=request)
            if attempts["order"] == 2:
                return httpx.Response(429, headers={"Retry-After": "0"}, text="rate limited")
            if attempts["order"] == 3:
                return httpx.Response(503, text="service unavailable")
            return httpx.Response(201, json={"id": "ORD-RECOVERED", "status": "CREATED", "links": []})
        return httpx.Response(404)

    async_client = httpx.AsyncClient(base_url="https://api-m.sandbox.paypal.com", transport=httpx.MockTransport(handler))
    client = PayPalSandboxClient(
        _sandbox_settings(),
        http_client=async_client,
        max_retries=3,
        retry_base_delay=0.0,
    )

    created = await client.create_order(
        amount_minor=2500,
        currency="USD",
        reference_id="ref-retry",
        description="Retry check",
        request_id="req-retry-1",
    )
    assert created.paypal_order_id == "ORD-RECOVERED"
    assert attempts["order"] == 4
    await async_client.aclose()


@pytest.mark.asyncio
async def test_capture_timeout_raises_paypal_timeout_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v1/oauth2/token":
            return httpx.Response(200, json={"access_token": "tok-123", "expires_in": 3600})
        if request.url.path == "/v2/checkout/orders/ORD-TIMEOUT" and request.method == "GET":
            return httpx.Response(200, json={"id": "ORD-TIMEOUT", "status": "APPROVED"})
        if request.url.path == "/v2/checkout/orders/ORD-TIMEOUT/capture":
            raise httpx.ReadTimeout("Simulated PayPal timeout", request=request)
        return httpx.Response(404)

    async_client = httpx.AsyncClient(base_url="https://api-m.sandbox.paypal.com", transport=httpx.MockTransport(handler))
    client = PayPalSandboxClient(
        _sandbox_settings(),
        http_client=async_client,
        max_retries=1,
        retry_base_delay=0.0,
    )

    with pytest.raises(PayPalTimeoutError):
        await client.capture_order(
            paypal_order_id="ORD-TIMEOUT",
            expected_amount_minor=3900,
            expected_currency="USD",
            request_id="cap-timeout-1",
        )
    await async_client.aclose()


@pytest.mark.asyncio
async def test_refund_capture_and_void_authorization() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v1/oauth2/token":
            return httpx.Response(200, json={"access_token": "tok-ops", "expires_in": 3600})
        if request.url.path == "/v2/payments/captures/CAP-KWD-1/refund" and request.method == "POST":
            body = json.loads(request.content)
            assert body["amount"] == {"currency_code": "KWD", "value": "12.500"}
            assert body["note_to_payer"] == "Partial refund"
            assert request.headers.get("PayPal-Request-Id") == "idem-refund-1"
            return httpx.Response(201, json={"id": "REF-1", "status": "COMPLETED"})
        if request.url.path == "/v2/payments/authorizations/AUTH-1/void" and request.method == "POST":
            assert request.headers.get("PayPal-Request-Id") == "idem-void-1"
            return httpx.Response(204)
        return httpx.Response(404)

    async_client = httpx.AsyncClient(base_url="https://api-m.sandbox.paypal.com", transport=httpx.MockTransport(handler))
    client = PayPalSandboxClient(_sandbox_settings(), http_client=async_client, retry_base_delay=0.0)

    refund = await client.refund_capture(
        "CAP-KWD-1",
        12500,
        "KWD",
        idempotency_key="idem-refund-1",
        note="Partial refund",
    )
    assert refund["id"] == "REF-1"
    assert refund["status"] == "COMPLETED"

    voided = await client.void_authorization("AUTH-1", idempotency_key="idem-void-1")
    assert voided == {"id": "AUTH-1", "status": "VOIDED"}
    await async_client.aclose()


@pytest.mark.asyncio
async def test_disputes_list_provide_evidence_and_accept_claim() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v1/oauth2/token":
            return httpx.Response(200, json={"access_token": "tok-disp", "expires_in": 3600})
        if request.url.path == "/v1/customer/disputes" and request.method == "GET":
            assert request.url.params["page_size"] == "10"
            assert request.url.params["next_page_token"] == "page-2"
            assert request.url.params["dispute_state"] == "OPEN_INQUIRIES"
            return httpx.Response(200, json={"items": [{"dispute_id": "PP-D-100"}]})
        if request.url.path == "/v1/customer/disputes/PP-D-100/provide-evidence" and request.method == "POST":
            content_type = request.headers.get("content-type", "")
            if "multipart/form-data" in content_type:
                assert b"tracking.pdf" in request.content
                assert b"PROOF_OF_DELIVERY" in request.content
                return httpx.Response(200, json={"links": [{"rel": "self", "href": "..."}]})
            body = json.loads(request.content)
            assert body["evidences"][0]["evidence_type"] == "PROOF_OF_FULFILLMENT"
            return httpx.Response(200, json={"status": "EVIDENCE_SUBMITTED"})
        if request.url.path == "/v1/customer/disputes/PP-D-100/accept-claim" and request.method == "POST":
            body = json.loads(request.content)
            assert body["note"] == "Merchant accepts claim"
            return httpx.Response(200, json={"dispute_id": "PP-D-100", "status": "RESOLVED"})
        if request.url.path == "/v1/customer/disputes" and request.method == "POST":
            return httpx.Response(405)
        return httpx.Response(404)

    async_client = httpx.AsyncClient(base_url="https://api-m.sandbox.paypal.com", transport=httpx.MockTransport(handler))
    client = PayPalSandboxClient(
        _sandbox_settings(paypal_disputes_api_enabled=True),
        http_client=async_client,
        retry_base_delay=0.0,
    )

    listed = await client.list_disputes(
        page_size=10,
        next_page_token="page-2",
        dispute_state="OPEN_INQUIRIES",
        timeout_seconds=5.0,
    )
    assert listed["items"][0]["dispute_id"] == "PP-D-100"

    ev_json = await client.provide_evidence(
        "PP-D-100",
        {"evidences": [{"evidence_type": "PROOF_OF_FULFILLMENT"}]},
    )
    assert ev_json["status"] == "EVIDENCE_SUBMITTED"

    ev_multipart = await client.provide_evidence(
        "PP-D-100",
        {"evidences": [{"evidence_type": "PROOF_OF_DELIVERY"}]},
        files=[("tracking.pdf", b"%PDF-1.4 mock", "application/pdf")],
    )
    assert "links" in ev_multipart

    accepted = await client.accept_claim("PP-D-100", note="Merchant accepts claim")
    assert accepted["status"] == "RESOLVED"
    await async_client.aclose()


@pytest.mark.asyncio
async def test_list_disputes_timeout_and_api_errors() -> None:
    def timeout_handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v1/oauth2/token":
            return httpx.Response(200, json={"access_token": "tok-disp", "expires_in": 3600})
        raise httpx.ReadTimeout("disputes timeout", request=request)

    t_client = httpx.AsyncClient(base_url="https://api-m.sandbox.paypal.com", transport=httpx.MockTransport(timeout_handler))
    client = PayPalSandboxClient(
        _sandbox_settings(paypal_disputes_api_enabled=True),
        http_client=t_client,
        max_retries=0,
    )
    with pytest.raises(PayPalTimeoutError):
        await client.list_disputes(timeout_seconds=1.0)
    with pytest.raises(ValueError):
        await client.list_disputes(page_size=100)
    await t_client.aclose()

    def api_error_handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v1/oauth2/token":
            return httpx.Response(200, json={"access_token": "tok-disp", "expires_in": 3600})
        return httpx.Response(403, headers={"PayPal-Debug-Id": "dbg-403"}, text="forbidden")

    e_client = httpx.AsyncClient(base_url="https://api-m.sandbox.paypal.com", transport=httpx.MockTransport(api_error_handler))
    err_pp = PayPalSandboxClient(
        _sandbox_settings(paypal_disputes_api_enabled=True),
        http_client=e_client,
        max_retries=0,
    )
    with pytest.raises(PayPalAPIError) as exc_info:
        await err_pp.list_disputes()
    assert exc_info.value.status_code == 403
    assert exc_info.value.debug_id == "dbg-403"
    await e_client.aclose()
