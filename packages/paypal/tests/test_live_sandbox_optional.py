"""Optional credential-gated live PayPal sandbox verification test.

If live credentials are not set, skips safely without failing offline test suites.
"""

from __future__ import annotations

import os

import pytest
from paypal import PayPalSandboxClient
from security import NexusSettings


def test_live_sandbox_optional() -> None:
    client_id = os.environ.get("PAYPAL_CLIENT_ID", "").strip()
    client_secret = os.environ.get("PAYPAL_CLIENT_SECRET", "").strip()

    if not client_id or not client_secret or client_id.startswith("sb-") or "placeholder" in client_id.lower():
        pytest.skip("NOT VERIFIED: Live PayPal sandbox credentials not configured in environment.")

    import asyncio

    async def _run() -> None:
        settings = NexusSettings(
            paypal_mode="sandbox",
            paypal_client_id=client_id,
            paypal_client_secret=client_secret,
            paypal_base_url="https://api-m.sandbox.paypal.com",
        )
        client = PayPalSandboxClient(settings=settings)
        token = await client.get_access_token()
        assert token is not None and len(token) > 10

    asyncio.run(_run())
