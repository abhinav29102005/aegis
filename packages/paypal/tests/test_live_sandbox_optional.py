"""Optional live PayPal Sandbox integration test (skipped when credentials are absent)."""

from __future__ import annotations

import os
from uuid import uuid4

import pytest
from paypal import PayPalSandboxClient
from security import NexusSettings

_HAS_PAYPAL_SANDBOX_CREDS = bool(
    os.getenv("PAYPAL_CLIENT_ID", "").strip() and os.getenv("PAYPAL_CLIENT_SECRET", "").strip()
)

pytestmark = pytest.mark.skipif(
    not _HAS_PAYPAL_SANDBOX_CREDS,
    reason="PAYPAL_CLIENT_ID and PAYPAL_CLIENT_SECRET are not set; skipping live PayPal Sandbox test.",
)


@pytest.mark.asyncio
async def test_live_paypal_sandbox_oauth_and_order_roundtrip() -> None:
    settings = NexusSettings(
        paypal_mode="sandbox",
        paypal_base_url=os.getenv("PAYPAL_BASE_URL", "https://api-m.sandbox.paypal.com"),
        paypal_client_id=os.environ["PAYPAL_CLIENT_ID"],
        paypal_client_secret=os.environ["PAYPAL_CLIENT_SECRET"],
    )
    client = PayPalSandboxClient(settings=settings)
    token = await client.get_access_token()
    assert isinstance(token, str) and len(token) > 10

    created = await client.create_order(
        amount_minor=1500,
        currency="USD",
        reference_id=f"live-test-{uuid4()}",
        description="AEGIS optional live sandbox verification order",
        request_id=str(uuid4()),
    )
    assert created.paypal_order_id
    fetched = await client.get_order(paypal_order_id=created.paypal_order_id)
    assert fetched["id"] == created.paypal_order_id
