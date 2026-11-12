"""Tests for nexus-paypal sandbox adapter using MockTransport (no live PayPal claims)."""

import json

import httpx
import pytest
from paypal import (
    PayPalConfigurationError,
    PayPalDisputesDisabledError,
    PayPalSandboxClient,
    PayPalTimeoutError,
    minor_to_paypal_value,
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
    # ISO 4217 exponents
    assert minor_to_paypal_value(3900, "JPY") == "3900"
    assert minor_to_paypal_value(3900, "KWD") == "3.900"
    assert minor_to_paypal_value(50, "BHD") == "0.050"


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
    assert refund.refund_id == "REF-1"
    assert refund.status == "COMPLETED"

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
    assert ev_res["status"] == "EVIDENCE_SUBMITTED"

    claim_res = await client.accept_claim(dispute_id="DISP-1", note="Settled")
    assert claim_res["status"] == "CLAIM_ACCEPTED"
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


@pytest.mark.asyncio
async def test_create_and_verified_capture_flow() -> None:
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
            # First GET is pre-capture (APPROVED); second GET is post-capture verification (COMPLETED)
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

    state = {"get_calls": 0}
    async_client = httpx.AsyncClient(base_url="https://api-m.sandbox.paypal.com", transport=httpx.MockTransport(handler))
    client = PayPalSandboxClient(_sandbox_settings(), http_client=async_client)

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
    client = PayPalSandboxClient(_sandbox_settings(), http_client=async_client)

    with pytest.raises(PayPalTimeoutError):
        await client.capture_order(
            paypal_order_id="ORD-TIMEOUT",
            expected_amount_minor=3900,
            expected_currency="USD",
            request_id="cap-timeout-1",
        )
    await async_client.aclose()

