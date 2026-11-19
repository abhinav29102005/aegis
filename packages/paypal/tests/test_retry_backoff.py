"""Comprehensive verification suite for HTTP retry logic and exponential backoff in packages/paypal."""

from unittest.mock import AsyncMock, patch

import httpx
import pytest
from paypal import (
    PayPalAPIError,
    PayPalSandboxClient,
    PayPalTimeoutError,
)
from security import NexusSettings


def _sandbox_settings(**overrides) -> NexusSettings:
    defaults = {
        "paypal_mode": "sandbox",
        "paypal_base_url": "https://api-m.sandbox.paypal.com",
        "paypal_client_id": "sb-test-client",
        "paypal_client_secret": "sb-test-secret",
        "paypal_webhook_id": "WH-TEST",
        "paypal_disputes_api_enabled": True,
    }
    defaults.update(overrides)
    return NexusSettings(**defaults)


# ---------------------------------------------------------------------------
# 1. Delay computation and backoff tests
# ---------------------------------------------------------------------------


def test_exponential_backoff_formula() -> None:
    client = PayPalSandboxClient(
        _sandbox_settings(),
        max_retries=5,
        retry_base_delay=0.1,
        retry_max_delay=1.0,
    )
    # 0.1 * 2^0 = 0.1
    assert client._compute_retry_delay(0) == pytest.approx(0.1)
    # 0.1 * 2^1 = 0.2
    assert client._compute_retry_delay(1) == pytest.approx(0.2)
    # 0.1 * 2^2 = 0.4
    assert client._compute_retry_delay(2) == pytest.approx(0.4)
    # 0.1 * 2^3 = 0.8
    assert client._compute_retry_delay(3) == pytest.approx(0.8)
    # 0.1 * 2^4 = 1.6, but capped at retry_max_delay=1.0
    assert client._compute_retry_delay(4) == pytest.approx(1.0)
    # 0.1 * 2^5 = 3.2 -> capped at 1.0
    assert client._compute_retry_delay(5) == pytest.approx(1.0)


@pytest.mark.parametrize(
    ("header_val", "expected_delay"),
    [
        ("0", 0.0),
        ("0.5", 0.5),
        ("1.25", 1.25),
        ("2.0", 2.0),
        ("10.0", 2.0),  # Capped at retry_max_delay (2.0)
        ("  1.5  ", 1.5),  # Strips whitespace
    ],
)
def test_retry_after_header_parsing(header_val: str, expected_delay: float) -> None:
    client = PayPalSandboxClient(
        _sandbox_settings(),
        retry_base_delay=0.1,
        retry_max_delay=2.0,
    )
    resp = httpx.Response(429, headers={"Retry-After": header_val})
    delay = client._compute_retry_delay(attempt=0, response=resp)
    assert delay == pytest.approx(expected_delay)


@pytest.mark.parametrize(
    "invalid_header",
    [
        "-1",  # Negative seconds
        "-10.5",
        "invalid_seconds",
        "Wed, 21 Oct 2026 07:28:00 GMT",  # HTTP-date format
        "",  # Empty string
        "nan",  # NaN
    ],
)
def test_retry_after_invalid_falls_back_to_exponential(invalid_header: str) -> None:
    client = PayPalSandboxClient(
        _sandbox_settings(),
        retry_base_delay=0.2,
        retry_max_delay=2.0,
    )
    resp = httpx.Response(429, headers={"Retry-After": invalid_header})
    # Fallback for attempt 1: 0.2 * 2^1 = 0.4
    delay = client._compute_retry_delay(attempt=1, response=resp)
    assert delay == pytest.approx(0.4)


def test_retry_after_infinity_capped() -> None:
    client = PayPalSandboxClient(
        _sandbox_settings(),
        retry_base_delay=0.1,
        retry_max_delay=2.0,
    )
    resp = httpx.Response(429, headers={"Retry-After": "inf"})
    delay = client._compute_retry_delay(attempt=0, response=resp)
    assert delay == pytest.approx(2.0)


def test_retry_after_honored_on_503() -> None:
    client = PayPalSandboxClient(
        _sandbox_settings(),
        retry_base_delay=0.1,
        retry_max_delay=5.0,
    )
    resp = httpx.Response(503, headers={"Retry-After": "3.5"})
    delay = client._compute_retry_delay(attempt=0, response=resp)
    assert delay == pytest.approx(3.5)


# ---------------------------------------------------------------------------
# 2. Status code classification tests
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("status", "is_transient"),
    [
        (200, False),
        (201, False),
        (204, False),
        (400, False),
        (401, False),
        (403, False),
        (404, False),
        (409, False),
        (422, False),
        (429, True),   # Rate limit is transient
        (500, True),   # Internal Server Error is transient
        (502, True),   # Bad Gateway is transient
        (503, True),   # Service Unavailable is transient
        (504, True),   # Gateway Timeout is transient
        (599, True),   # 5xx boundary is transient
    ],
)
def test_transient_status_classification(status: int, is_transient: bool) -> None:
    assert PayPalSandboxClient._is_transient_status(status) is is_transient


# ---------------------------------------------------------------------------
# 3. Non-transient errors fail immediately (zero retries)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize("status_code", [400, 401, 403, 404, 409, 422])
async def test_non_transient_4xx_fail_fast_without_retrying(status_code: int) -> None:
    call_count = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal call_count
        call_count += 1
        if request.url.path == "/v1/oauth2/token":
            return httpx.Response(200, json={"access_token": "tok-test", "expires_in": 3600})
        return httpx.Response(status_code, json={"error": "client_error"}, headers={"PayPal-Debug-Id": f"dbg-{status_code}"})

    async_client = httpx.AsyncClient(base_url="https://api-m.sandbox.paypal.com", transport=httpx.MockTransport(handler))
    client = PayPalSandboxClient(
        _sandbox_settings(),
        http_client=async_client,
        max_retries=3,
        retry_base_delay=0.0,
    )

    with pytest.raises(PayPalAPIError) as exc_info:
        await client.get_order(paypal_order_id="ORD-FAIL-FAST")

    assert exc_info.value.status_code == status_code
    assert exc_info.value.debug_id == f"dbg-{status_code}"
    # 1 call for OAuth token, exactly 1 call for get_order (no retries)
    assert call_count == 2
    await async_client.aclose()


# ---------------------------------------------------------------------------
# 4. Retries on 429 and 5xx recovery and sleep interval verification
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_retry_on_429_honors_retry_after_and_succeeds() -> None:
    attempts = 0
    sleep_calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        if request.url.path == "/v1/oauth2/token":
            return httpx.Response(200, json={"access_token": "tok-429", "expires_in": 3600})
        if attempts == 2:  # First order call
            return httpx.Response(429, headers={"Retry-After": "0.5"}, text="rate limited")
        if attempts == 3:  # Second order call
            return httpx.Response(200, json={"id": "ORD-429-OK", "status": "APPROVED"})
        return httpx.Response(404)

    async_client = httpx.AsyncClient(base_url="https://api-m.sandbox.paypal.com", transport=httpx.MockTransport(handler))
    client = PayPalSandboxClient(
        _sandbox_settings(),
        http_client=async_client,
        max_retries=3,
        retry_base_delay=0.1,
    )

    with patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
        mock_sleep.side_effect = lambda s: sleep_calls.append(s)
        order = await client.get_order(paypal_order_id="ORD-429-OK")

    assert order["id"] == "ORD-429-OK"
    assert attempts == 3
    assert len(sleep_calls) == 1
    assert sleep_calls[0] == pytest.approx(0.5)
    await async_client.aclose()


@pytest.mark.asyncio
async def test_retry_on_5xx_exponential_intervals() -> None:
    attempts = 0
    sleep_calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        if request.url.path == "/v1/oauth2/token":
            return httpx.Response(200, json={"access_token": "tok-5xx", "expires_in": 3600})
        if attempts in (2, 3):  # First two order calls fail with 503 and 500
            return httpx.Response(503 if attempts == 2 else 500, text="server glitch")
        return httpx.Response(200, json={"id": "ORD-5XX-OK", "status": "APPROVED"})

    async_client = httpx.AsyncClient(base_url="https://api-m.sandbox.paypal.com", transport=httpx.MockTransport(handler))
    client = PayPalSandboxClient(
        _sandbox_settings(),
        http_client=async_client,
        max_retries=3,
        retry_base_delay=0.1,
        retry_max_delay=1.0,
    )

    with patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
        mock_sleep.side_effect = lambda s: sleep_calls.append(s)
        order = await client.get_order(paypal_order_id="ORD-5XX-OK")

    assert order["id"] == "ORD-5XX-OK"
    assert attempts == 4
    # Attempt 0 slept 0.1 * 2^0 = 0.1
    # Attempt 1 slept 0.1 * 2^1 = 0.2
    assert len(sleep_calls) == 2
    assert sleep_calls[0] == pytest.approx(0.1)
    assert sleep_calls[1] == pytest.approx(0.2)
    await async_client.aclose()


# ---------------------------------------------------------------------------
# 5. Retry exhaustion preserves real status code and debug ID
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_exhaustion_on_503_raises_paypal_api_error_with_status_and_debug_id() -> None:
    order_attempts = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal order_attempts
        if request.url.path == "/v1/oauth2/token":
            return httpx.Response(200, json={"access_token": "tok-503", "expires_in": 3600})
        order_attempts += 1
        return httpx.Response(
            503,
            headers={"PayPal-Debug-Id": "dbg-persist-503"},
            text="paypal unavailable",
        )

    async_client = httpx.AsyncClient(base_url="https://api-m.sandbox.paypal.com", transport=httpx.MockTransport(handler))
    client = PayPalSandboxClient(
        _sandbox_settings(),
        http_client=async_client,
        max_retries=2,
        retry_base_delay=0.0,
    )

    with pytest.raises(PayPalAPIError) as exc_info:
        await client.get_order(paypal_order_id="ORD-EXHAUST")

    assert exc_info.value.status_code == 503
    assert exc_info.value.debug_id == "dbg-persist-503"
    # 1 initial attempt + 2 retries = 3 attempts total
    assert order_attempts == 3
    await async_client.aclose()


@pytest.mark.asyncio
async def test_exhaustion_on_429_raises_paypal_api_error_with_429() -> None:
    order_attempts = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal order_attempts
        if request.url.path == "/v1/oauth2/token":
            return httpx.Response(200, json={"access_token": "tok-429", "expires_in": 3600})
        order_attempts += 1
        return httpx.Response(
            429,
            headers={"PayPal-Debug-Id": "dbg-rate-limited", "Retry-After": "0"},
            text="rate limited",
        )

    async_client = httpx.AsyncClient(base_url="https://api-m.sandbox.paypal.com", transport=httpx.MockTransport(handler))
    client = PayPalSandboxClient(
        _sandbox_settings(),
        http_client=async_client,
        max_retries=2,
        retry_base_delay=0.0,
    )

    with pytest.raises(PayPalAPIError) as exc_info:
        await client.get_order(paypal_order_id="ORD-EXHAUST-429")

    assert exc_info.value.status_code == 429
    assert exc_info.value.debug_id == "dbg-rate-limited"
    assert order_attempts == 3
    await async_client.aclose()


# ---------------------------------------------------------------------------
# 6. max_retries = 0 invariant
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_max_retries_zero_executes_single_attempt() -> None:
    attempts = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        if request.url.path == "/v1/oauth2/token":
            return httpx.Response(200, json={"access_token": "tok-zero", "expires_in": 3600})
        attempts += 1
        return httpx.Response(500, text="error")

    async_client = httpx.AsyncClient(base_url="https://api-m.sandbox.paypal.com", transport=httpx.MockTransport(handler))
    client = PayPalSandboxClient(
        _sandbox_settings(),
        http_client=async_client,
        max_retries=0,
    )

    with pytest.raises(PayPalAPIError) as exc_info:
        await client.get_order(paypal_order_id="ORD-ZERO")

    assert exc_info.value.status_code == 500
    assert attempts == 1
    await async_client.aclose()


# ---------------------------------------------------------------------------
# 7. OAuth token endpoint retry on 429/5xx
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_oauth_token_retries_on_transient_failure() -> None:
    oauth_attempts = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal oauth_attempts
        if request.url.path == "/v1/oauth2/token":
            oauth_attempts += 1
            if oauth_attempts == 1:
                return httpx.Response(503, text="auth service busy")
            return httpx.Response(200, json={"access_token": "tok-recovered", "expires_in": 3600})
        return httpx.Response(404)

    async_client = httpx.AsyncClient(base_url="https://api-m.sandbox.paypal.com", transport=httpx.MockTransport(handler))
    client = PayPalSandboxClient(
        _sandbox_settings(),
        http_client=async_client,
        max_retries=2,
        retry_base_delay=0.0,
    )

    token = await client.get_access_token()
    assert token == "tok-recovered"
    assert oauth_attempts == 2
    await async_client.aclose()


# ---------------------------------------------------------------------------
# 8. Idempotency key preservation across retries
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_idempotency_key_preserved_across_retries() -> None:
    seen_request_ids = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v1/oauth2/token":
            return httpx.Response(200, json={"access_token": "tok-idem", "expires_in": 3600})
        if request.url.path == "/v2/checkout/orders":
            seen_request_ids.append(request.headers.get("PayPal-Request-Id"))
            if len(seen_request_ids) < 3:
                return httpx.Response(503, text="temporary error")
            return httpx.Response(201, json={"id": "ORD-IDEM", "status": "CREATED", "links": []})
        return httpx.Response(404)

    async_client = httpx.AsyncClient(base_url="https://api-m.sandbox.paypal.com", transport=httpx.MockTransport(handler))
    client = PayPalSandboxClient(
        _sandbox_settings(),
        http_client=async_client,
        max_retries=3,
        retry_base_delay=0.0,
    )

    created = await client.create_order(
        amount_minor=1000,
        currency="USD",
        reference_id="ref-idem",
        description="idempotency check",
        request_id="my-fixed-uuid-12345",
    )
    assert created.paypal_order_id == "ORD-IDEM"
    assert len(seen_request_ids) == 3
    # All retries must have transmitted the exact same PayPal-Request-Id
    assert seen_request_ids == ["my-fixed-uuid-12345", "my-fixed-uuid-12345", "my-fixed-uuid-12345"]
    await async_client.aclose()


# ---------------------------------------------------------------------------
# 9. Client lifecycle / cleanup
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_internal_client_aclose_called_even_on_failure() -> None:
    client = PayPalSandboxClient(
        _sandbox_settings(),
        http_client=None,  # No external client passed
        max_retries=1,
        retry_base_delay=0.0,
    )

    mock_httpx_client = AsyncMock()
    mock_httpx_client.request.side_effect = httpx.ReadTimeout("simulated timeout")

    with (
        patch.object(client, "_client", return_value=mock_httpx_client),
        pytest.raises(PayPalTimeoutError),
    ):
        await client.get_order(paypal_order_id="ORD-LEAK-TEST")

    # Verify aclose() was called to release resources
    mock_httpx_client.aclose.assert_awaited_once()
