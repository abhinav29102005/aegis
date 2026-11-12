"""Tests for AegisAPIError parsing, configurable timeouts, and retry/exponential backoff."""

from __future__ import annotations

import httpx
import pytest
from aegis_sdk.client import AegisClient, AsyncAegisClient
from aegis_sdk.exceptions import AegisAPIError


def test_api_error_string_detail() -> None:
    payload = {"detail": "PaymentIntent not found"}
    err = AegisAPIError.from_response(404, payload)
    assert err.status_code == 404
    assert err.message == "PaymentIntent not found"
    assert err.detail == "PaymentIntent not found"
    assert "AEGIS API HTTP 404: PaymentIntent not found" in str(err)


def test_api_error_dict_detail() -> None:
    payload = {
        "detail": {
            "error_code": "POLICY_DENIED",
            "message": "Transaction exceeds daily limit of $100.00",
        }
    }
    err = AegisAPIError.from_response(403, payload)
    assert err.status_code == 403
    assert err.error_code == "POLICY_DENIED"
    assert err.message == "Transaction exceeds daily limit of $100.00"


def test_api_error_validation_list_detail() -> None:
    payload = {
        "detail": [
            {"loc": ["body", "email"], "msg": "value is not a valid email address", "type": "value_error"},
            {"loc": ["body", "amount_minor"], "msg": "Input should be greater than 0", "type": "greater_than"},
        ]
    }
    err = AegisAPIError.from_response(422, payload)
    assert err.status_code == 422
    assert err.error_code == "VALIDATION_ERROR"
    assert "email: value is not a valid email address" in err.message
    assert "amount_minor: Input should be greater than 0" in err.message


def test_api_error_plain_text() -> None:
    err = AegisAPIError.from_response(502, "Bad Gateway")
    assert err.status_code == 502
    assert err.message == "Bad Gateway"


def test_retry_on_429_eventually_succeeds() -> None:
    calls = 0

    def mock_handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if calls < 3:
            return httpx.Response(429, json={"detail": "Too many requests"})
        return httpx.Response(200, json={"status": "ok"})

    transport = httpx.MockTransport(mock_handler)
    with httpx.Client(transport=transport) as hc:
        client = AegisClient(client=hc, max_retries=3, backoff_factor=0.01)
        res = client._request("GET", "/health")
        assert res == {"status": "ok"}
        assert calls == 3


def test_retry_exhausted_raises_error() -> None:
    calls = 0

    def mock_handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(503, json={"detail": "Service Unavailable"})

    transport = httpx.MockTransport(mock_handler)
    with httpx.Client(transport=transport) as hc:
        client = AegisClient(client=hc, max_retries=2, backoff_factor=0.01)
        with pytest.raises(AegisAPIError) as exc_info:
            client._request("GET", "/health")
        assert exc_info.value.status_code == 503
        assert calls == 3  # Initial + 2 retries


@pytest.mark.asyncio
async def test_async_retry_on_502_eventually_succeeds() -> None:
    calls = 0

    def mock_handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if calls < 2:
            return httpx.Response(502, json={"detail": "Bad Gateway"})
        return httpx.Response(200, json={"status": "ready"})

    transport = httpx.MockTransport(mock_handler)
    async with httpx.AsyncClient(transport=transport) as hc:
        client = AsyncAegisClient(client=hc, max_retries=2, backoff_factor=0.01)
        res = await client._request("GET", "/ready")
        assert res == {"status": "ready"}
        assert calls == 2


def test_configurable_timeout() -> None:
    t = httpx.Timeout(45.0, connect=10.0)
    client = AegisClient(timeout=t)
    assert client._timeout.read == 45.0
    assert client._timeout.connect == 10.0
    client.close()
