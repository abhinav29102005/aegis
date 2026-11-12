"""Stripe REST provider adapter for AgentPay Guardian."""

from __future__ import annotations

import hmac
from typing import Any

import httpx
from contracts.providers import PaymentProviderAdapter


class StripeProviderAdapter(PaymentProviderAdapter):
    """Production-ready Stripe REST adapter using httpx without third-party stripe SDK dependency."""

    provider_name: str = "STRIPE"

    def __init__(
        self,
        api_key: str = "sk_test_placeholder",
        base_url: str = "https://api.stripe.com/v1",
        webhook_secret: str | None = None,
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.webhook_secret = webhook_secret
        self._external_client = http_client

    def _client(self) -> httpx.AsyncClient:
        if self._external_client is not None:
            return self._external_client
        return httpx.AsyncClient(
            base_url=self.base_url,
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/x-www-form-urlencoded",
            },
            timeout=10.0,
        )

    async def create_order(
        self,
        *,
        amount_minor: int,
        currency: str,
        reference_id: str,
        description: str | None = None,
        return_url: str | None = None,
        cancel_url: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Create a Stripe PaymentIntent."""
        client = self._client()
        close_after = self._external_client is None
        data = {
            "amount": str(amount_minor),
            "currency": currency.lower(),
            "capture_method": "manual",
            "description": description or f"AgentPay Nexus Intent {reference_id}",
        }
        if metadata:
            for k, v in metadata.items():
                data[f"metadata[{k}]"] = str(v)
        data["metadata[reference_id]"] = reference_id

        try:
            resp = await client.post("/payment_intents", data=data)
        finally:
            if close_after:
                await client.aclose()

        if resp.status_code >= 400:
            raise RuntimeError(f"Stripe PaymentIntent creation failed ({resp.status_code}): {resp.text}")
        payload = resp.json()
        return {
            "order_id": payload["id"],
            "status": payload.get("status", "requires_payment_method"),
            "client_secret": payload.get("client_secret"),
            "raw_response": payload,
        }

    async def capture_order(
        self,
        *,
        order_id: str,
        amount_minor: int | None = None,
        currency: str = "USD",
        request_id: str | None = None,
    ) -> dict[str, Any]:
        """Capture an authorized Stripe PaymentIntent."""
        client = self._client()
        close_after = self._external_client is None
        data = {}
        if amount_minor is not None:
            data["amount_to_capture"] = str(amount_minor)

        try:
            resp = await client.post(f"/payment_intents/{order_id}/capture", data=data)
        finally:
            if close_after:
                await client.aclose()

        if resp.status_code >= 400:
            raise RuntimeError(f"Stripe capture failed ({resp.status_code}): {resp.text}")
        payload = resp.json()
        return {
            "order_id": payload["id"],
            "capture_id": (payload.get("charges", {}).get("data") or [{}])[0].get("id", order_id),
            "status": payload.get("status", "succeeded"),
            "raw_response": payload,
        }

    async def refund_capture(
        self,
        *,
        capture_id: str,
        amount_minor: int | None = None,
        currency: str = "USD",
        note: str | None = None,
    ) -> dict[str, Any]:
        """Issue full or partial refund for a Stripe charge or payment intent."""
        client = self._client()
        close_after = self._external_client is None
        data: dict[str, str] = {}
        if capture_id.startswith("pi_"):
            data["payment_intent"] = capture_id
        else:
            data["charge"] = capture_id
        if amount_minor is not None:
            data["amount"] = str(amount_minor)
        if note:
            data["reason"] = "requested_by_customer"

        try:
            resp = await client.post("/refunds", data=data)
        finally:
            if close_after:
                await client.aclose()

        if resp.status_code >= 400:
            raise RuntimeError(f"Stripe refund failed ({resp.status_code}): {resp.text}")
        payload = resp.json()
        return {
            "refund_id": payload["id"],
            "status": payload.get("status", "succeeded"),
            "amount_minor": payload.get("amount", amount_minor or 0),
            "raw_response": payload,
        }

    async def void_authorization(
        self,
        *,
        authorization_id: str,
        note: str | None = None,
    ) -> dict[str, Any]:
        """Cancel an uncaptured Stripe PaymentIntent."""
        client = self._client()
        close_after = self._external_client is None
        data = {}
        if note:
            data["cancellation_reason"] = "abandoned"

        try:
            resp = await client.post(f"/payment_intents/{authorization_id}/cancel", data=data)
        finally:
            if close_after:
                await client.aclose()

        if resp.status_code >= 400:
            raise RuntimeError(f"Stripe void failed ({resp.status_code}): {resp.text}")
        payload = resp.json()
        return {
            "order_id": payload["id"],
            "status": payload.get("status", "canceled"),
            "raw_response": payload,
        }

    async def get_order_status(
        self,
        *,
        order_id: str,
    ) -> dict[str, Any]:
        """Get canonical Stripe PaymentIntent status."""
        client = self._client()
        close_after = self._external_client is None
        try:
            resp = await client.get(f"/payment_intents/{order_id}")
        finally:
            if close_after:
                await client.aclose()

        if resp.status_code >= 400:
            raise RuntimeError(f"Stripe get_order_status failed ({resp.status_code}): {resp.text}")
        payload = resp.json()
        return {
            "order_id": payload["id"],
            "status": payload.get("status"),
            "amount_minor": payload.get("amount"),
            "currency": payload.get("currency", "").upper(),
            "raw_response": payload,
        }

    def verify_webhook_signature(
        self,
        payload_bytes: bytes,
        signature_header: str,
    ) -> bool:
        """Verify Stripe webhook signature (v1 scheme)."""
        if not self.webhook_secret:
            return False
        parts = dict(pair.split("=", 1) for pair in signature_header.split(",") if "=" in pair)
        t = parts.get("t")
        v1 = parts.get("v1")
        if not t or not v1:
            return False
        signed_payload = f"{t}.".encode() + payload_bytes
        expected_sig = hmac.new(
            self.webhook_secret.encode("utf-8"),
            signed_payload,
            "sha256",
        ).hexdigest()
        return hmac.compare_digest(expected_sig, v1)
