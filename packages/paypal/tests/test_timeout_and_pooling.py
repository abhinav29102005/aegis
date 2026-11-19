"""Verification suite for Timeout configurations and connection pooling in packages/paypal."""

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


# ===========================================================================
# 1. Connection Pooling & Client Lifecycle Verification
# ===========================================================================


@pytest.mark.asyncio
async def test_mode_b_default_creates_and_closes_client_per_request() -> None:
    """When no external client is provided (Mode B), every request creates a new client and closes it."""
    client = PayPalSandboxClient(
        _sandbox_settings(),
        http_client=None,
        max_retries=0,
    )

    created_clients = []
    closed_clients = []

    original_client_factory = client._client

    def tracking_client_factory():
        c = original_client_factory()
        created_clients.append(c)
        original_aclose = c.aclose

        async def tracking_aclose():
            closed_clients.append(c)
            await original_aclose()

        c.aclose = tracking_aclose
        return c

    with patch.object(client, "_client", side_effect=tracking_client_factory):
        # Mock httpx.AsyncClient.request to avoid actual network
        with patch("httpx.AsyncClient.request", new_callable=AsyncMock) as mock_request:
            mock_request.return_value = httpx.Response(200, json={"id": "ORD-1", "status": "APPROVED"})
            # Pre-populate token to isolate order call
            client._cached_token = "tok-cached"
            from datetime import UTC, datetime, timedelta
            client._token_expires_at = datetime.now(UTC) + timedelta(hours=1)

            resp1 = await client.get_order(paypal_order_id="ORD-1")
            assert resp1["id"] == "ORD-1"

            resp2 = await client.get_order(paypal_order_id="ORD-1")
            assert resp2["id"] == "ORD-1"

    # Exactly 2 clients were created and both were closed (no pooling between calls)
    assert len(created_clients) == 2
    assert len(closed_clients) == 2
    assert created_clients[0] is not created_clients[1]


@pytest.mark.asyncio
async def test_mode_a_injected_client_persists_and_is_not_closed() -> None:
    """When an external client is injected (Mode A), the same client is reused and never closed by _request."""
    handler_calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal handler_calls
        handler_calls += 1
        return httpx.Response(200, json={"id": "ORD-SHARED", "status": "APPROVED"})

    shared_http = httpx.AsyncClient(
        base_url="https://api-m.sandbox.paypal.com",
        transport=httpx.MockTransport(handler),
    )
    client = PayPalSandboxClient(
        _sandbox_settings(),
        http_client=shared_http,
        max_retries=0,
    )
    client._cached_token = "tok-cached"
    from datetime import UTC, datetime, timedelta
    client._token_expires_at = datetime.now(UTC) + timedelta(hours=1)

    # Issue multiple requests through shared client
    await client.get_order(paypal_order_id="ORD-SHARED")
    await client.get_order(paypal_order_id="ORD-SHARED")

    assert handler_calls == 2
    assert not shared_http.is_closed  # Connection pool is kept open!

    await shared_http.aclose()
    assert shared_http.is_closed


# ===========================================================================
# 2. Timeout Configurations & Granularity Verification
# ===========================================================================


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "timeout_exception_cls",
    [
        httpx.ConnectTimeout,
        httpx.ReadTimeout,
        httpx.WriteTimeout,
        httpx.PoolTimeout,
    ],
)
async def test_all_httpx_timeout_types_map_to_paypal_timeout_error(timeout_exception_cls) -> None:
    """Verify that all subclasses of httpx.TimeoutException trigger retries and map to PayPalTimeoutError."""
    attempts = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        raise timeout_exception_cls(f"Simulated {timeout_exception_cls.__name__}", request=request)

    async_client = httpx.AsyncClient(
        base_url="https://api-m.sandbox.paypal.com",
        transport=httpx.MockTransport(handler),
    )
    client = PayPalSandboxClient(
        _sandbox_settings(),
        http_client=async_client,
        max_retries=2,
        retry_base_delay=0.0,
    )
    client._cached_token = "tok-cached"
    from datetime import UTC, datetime, timedelta
    client._token_expires_at = datetime.now(UTC) + timedelta(hours=1)

    with pytest.raises(PayPalTimeoutError) as exc_info:
        await client.get_order(paypal_order_id="ORD-TIMEOUT")

    # 1 initial attempt + 2 retries = 3 attempts
    assert attempts == 3
    # Original httpx exception chained via `from exc`
    assert isinstance(exc_info.value.__cause__, timeout_exception_cls)
    await async_client.aclose()


@pytest.mark.asyncio
async def test_list_disputes_timeout_override_respected() -> None:
    """Verify list_disputes passes effective_timeout directly in kwargs."""
    observed_timeouts = []

    async def mock_request(method, path, **kwargs):
        observed_timeouts.append(kwargs.get("timeout"))
        return httpx.Response(200, json={"items": []})

    client = PayPalSandboxClient(
        _sandbox_settings(paypal_disputes_api_enabled=True),
        timeout_seconds=15.0,
    )
    client._cached_token = "tok-disp"
    from datetime import UTC, datetime, timedelta
    client._token_expires_at = datetime.now(UTC) + timedelta(hours=1)

    with patch.object(client, "_client") as mock_c_factory:
        mock_c = AsyncMock()
        mock_c.request.side_effect = mock_request
        mock_c_factory.return_value = mock_c

        # Case 1: Custom timeout provided
        await client.list_disputes(timeout_seconds=4.5)
        assert observed_timeouts[-1] == 4.5

        # Case 2: No timeout provided -> capped at min(15.0, 10.0) = 10.0
        await client.list_disputes()
        assert observed_timeouts[-1] == 10.0


@pytest.mark.asyncio
async def test_timeout_on_token_retrieval_raises_paypal_timeout_error() -> None:
    """Verify timeout while fetching OAuth token raises PayPalTimeoutError with specific message."""
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("OAuth token timeout", request=request)

    async_client = httpx.AsyncClient(
        base_url="https://api-m.sandbox.paypal.com",
        transport=httpx.MockTransport(handler),
    )
    client = PayPalSandboxClient(
        _sandbox_settings(),
        http_client=async_client,
        max_retries=1,
        retry_base_delay=0.0,
    )

    with pytest.raises(PayPalTimeoutError, match="Timed out obtaining PayPal OAuth token"):
        await client.get_access_token()
    await async_client.aclose()
