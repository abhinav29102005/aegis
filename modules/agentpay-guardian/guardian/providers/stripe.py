"""Stripe REST adapter implementing PaymentProviderAdapter via httpx.

Supports PaymentIntents, Shared Payment Tokens, Stripe Connect destination/account
routing, Stripe Issuing webhook verification & parsing, and Smart Disputes evidence
submission.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import time
from typing import Any
from uuid import UUID

import httpx
from contracts import StripeEventEnvelope, compute_payload_hash
from contracts.providers import PaymentProviderAdapter
from security import DEFAULT_TENANT_UUID, NexusSettings, get_settings

from guardian.providers.base import (
    ProviderAPIError,
    ProviderConfigurationError,
    ProviderSignatureError,
    ProviderValidationError,
    RetryingHTTPClient,
)

_STRIPE_REFUND_REASONS = frozenset({"duplicate", "fraudulent", "requested_by_customer"})


def _flatten_form_fields(data: dict[str, Any], prefix: str = "") -> dict[str, str]:
    """Flatten nested dicts/lists into Stripe's bracketed x-www-form-urlencoded keys."""
    fields: dict[str, str] = {}
    for key, value in data.items():
        full_key = f"{prefix}[{key}]" if prefix else str(key)
        if value is None:
            continue
        if isinstance(value, dict):
            fields.update(_flatten_form_fields(value, prefix=full_key))
        elif isinstance(value, list):
            for idx, item in enumerate(value):
                item_key = f"{full_key}[{idx}]"
                if isinstance(item, dict):
                    fields.update(_flatten_form_fields(item, prefix=item_key))
                else:
                    fields[item_key] = str(item).lower() if isinstance(item, bool) else str(item)
        elif isinstance(value, bool):
            fields[full_key] = "true" if value else "false"
        else:
            fields[full_key] = str(value)
    return fields


class StripeProviderAdapter(PaymentProviderAdapter):
    """Stripe REST API v1 multi-rail payment, Connect, Issuing, and Disputes adapter."""

    provider_name: str = "stripe"

    def __init__(
        self,
        *,
        api_key: str | None = None,
        webhook_secret: str | None = None,
        base_url: str = "https://api.stripe.com",
        stripe_account: str | None = None,
        settings: NexusSettings | None = None,
        http_client: httpx.AsyncClient | None = None,
        timeout_seconds: float = 15.0,
        max_retries: int = 2,
        retry_base_delay: float = 0.05,
        webhook_tolerance_seconds: int = 300,
    ) -> None:
        self.settings = settings or get_settings()
        self.api_key = api_key if api_key is not None else (self.settings.stripe_api_key or "sk_test_placeholder")
        self.webhook_secret = (
            webhook_secret if webhook_secret is not None else self.settings.stripe_webhook_secret
        )
        self.stripe_account = stripe_account
        self.webhook_tolerance_seconds = webhook_tolerance_seconds
        self.base_url = base_url.rstrip("/")
        self._http = RetryingHTTPClient(
            provider_name=self.provider_name,
            base_url=self.base_url,
            http_client=http_client,
            timeout_seconds=timeout_seconds,
            max_retries=max_retries,
            retry_base_delay=retry_base_delay,
        )

    def _require_api_key(self) -> str:
        if not self.api_key:
            return "sk_test_placeholder"
        return self.api_key

    def _build_headers(
        self,
        *,
        idempotency_key: str | None = None,
        stripe_account: str | None = None,
    ) -> dict[str, str]:
        headers = {
            "Authorization": f"Bearer {self._require_api_key()}",
            "Content-Type": "application/x-www-form-urlencoded",
        }
        if idempotency_key:
            headers["Idempotency-Key"] = idempotency_key
        acct = stripe_account or self.stripe_account
        if acct:
            headers["Stripe-Account"] = acct
        return headers

    async def _post_form(
        self,
        path: str,
        payload: dict[str, Any],
        *,
        idempotency_key: str | None = None,
        stripe_account: str | None = None,
    ) -> dict[str, Any]:
        resp = await self._http.request(
            "POST",
            path,
            data=_flatten_form_fields(payload),
            headers=self._build_headers(
                idempotency_key=idempotency_key,
                stripe_account=stripe_account,
            ),
        )
        if resp.status_code >= 400:
            raise ProviderAPIError(
                f"Stripe API error on {path} ({resp.status_code}): {resp.text}",
                status_code=resp.status_code,
                provider=self.provider_name,
            )
        return resp.json()

    async def create_order(
        self,
        *,
        amount_minor: int,
        currency: str,
        idempotency_key: str = "",
        reference_id: str | None = None,
        description: str | None = None,
        return_url: str | None = None,
        cancel_url: str | None = None,
        metadata: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        """Create a Stripe PaymentIntent (supports Shared Payment Tokens and Connect routing)."""
        if amount_minor <= 0:
            raise ProviderValidationError("amount_minor must be positive")
        meta = dict(metadata or {})
        if reference_id:
            meta["reference_id"] = reference_id
        if description and "description" not in meta:
            meta["description"] = description
        stripe_account = meta.pop("stripe_account", None)
        shared_payment_token = meta.pop("shared_payment_token", None)
        connect_destination = meta.pop("connect_destination", None)
        capture_method = meta.pop("capture_method", "automatic")

        payload: dict[str, Any] = {
            "amount": amount_minor,
            "currency": currency.lower(),
            "capture_method": capture_method,
            "metadata": {k: str(v) for k, v in meta.items()},
        }
        if description:
            payload["description"] = description
        if shared_payment_token:
            payload["shared_payment_granted_token"] = shared_payment_token
            payload["confirm"] = True
        if connect_destination:
            payload["transfer_data"] = {"destination": connect_destination}

        data = await self._post_form(
            "/v1/payment_intents",
            payload,
            idempotency_key=idempotency_key or None,
            stripe_account=stripe_account,
        )
        return {
            "provider": self.provider_name,
            "order_id": data["id"],
            "status": data.get("status"),
            "amount_minor": data.get("amount", amount_minor),
            "currency": str(data.get("currency", currency)).upper(),
            "client_secret": data.get("client_secret"),
            "raw_response": data,
        }

    async def create_shared_payment_token(
        self,
        *,
        payment_method_id: str,
        max_amount_minor: int,
        currency: str,
        expires_at_epoch: int,
        idempotency_key: str,
        merchant_id: str | None = None,
        metadata: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        """Issue a scoped Stripe Shared Payment Token for agent-delegated checkout."""
        if max_amount_minor <= 0:
            raise ProviderValidationError("max_amount_minor must be positive")
        payload: dict[str, Any] = {
            "payment_method": payment_method_id,
            "usage_limits": {
                "type": "currency",
                "currency_limit": {
                    "amount": max_amount_minor,
                    "currency": currency.lower(),
                },
                "expires_at": expires_at_epoch,
            },
        }
        if merchant_id:
            payload["seller_details"] = {"network_id": merchant_id}
        if metadata:
            payload["metadata"] = metadata
        return await self._post_form(
            "/v1/shared_payment/issued_tokens",
            payload,
            idempotency_key=idempotency_key,
        )

    async def create_connect_transfer(
        self,
        *,
        amount_minor: int,
        currency: str,
        destination_account: str,
        idempotency_key: str,
        transfer_group: str | None = None,
        metadata: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        """Create a Stripe Connect transfer to a connected merchant account."""
        if amount_minor <= 0:
            raise ProviderValidationError("amount_minor must be positive")
        payload: dict[str, Any] = {
            "amount": amount_minor,
            "currency": currency.lower(),
            "destination": destination_account,
        }
        if transfer_group:
            payload["transfer_group"] = transfer_group
        if metadata:
            payload["metadata"] = metadata
        return await self._post_form(
            "/v1/transfers",
            payload,
            idempotency_key=idempotency_key,
        )

    async def capture_order(
        self,
        *,
        order_id: str,
        idempotency_key: str = "",
        amount_minor: int | None = None,
        currency: str | None = "USD",
        request_id: str | None = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        """Capture an authorized Stripe PaymentIntent."""
        payload: dict[str, Any] = {}
        if amount_minor is not None:
            if amount_minor <= 0:
                raise ProviderValidationError("amount_minor must be positive")
            payload["amount_to_capture"] = amount_minor
        data = await self._post_form(
            f"/v1/payment_intents/{order_id}/capture",
            payload,
            idempotency_key=idempotency_key or None,
        )
        return {
            "provider": self.provider_name,
            "order_id": data.get("id", order_id),
            "capture_id": data.get("latest_charge") or (data.get("charges", {}).get("data") or [{}])[0].get("id", order_id),
            "status": data.get("status"),
            "amount_minor": data.get("amount_received", data.get("amount", amount_minor)),
            "currency": str(data.get("currency") or currency or "USD").upper(),
            "raw_response": data,
        }

    async def refund_capture(
        self,
        *,
        capture_id: str,
        amount_minor: int | None = None,
        currency: str = "USD",
        idempotency_key: str = "",
        reason: str | None = None,
        note: str | None = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        """Refund a Stripe Charge (ch_*) or PaymentIntent (pi_*)."""
        actual_reason = reason or ("requested_by_customer" if note else None)
        target_key = "charge" if capture_id.startswith("ch_") else "payment_intent"
        payload: dict[str, Any] = {
            target_key: capture_id,
            "metadata": {"requested_currency": currency.upper()},
        }
        if amount_minor is not None:
            if amount_minor <= 0:
                raise ProviderValidationError("amount_minor must be positive")
            payload["amount"] = amount_minor
        if actual_reason:
            normalized = actual_reason.strip().lower()
            if normalized in _STRIPE_REFUND_REASONS:
                payload["reason"] = normalized
            else:
                payload["metadata"]["nexus_reason"] = actual_reason[:500]
        data = await self._post_form(
            "/v1/refunds",
            payload,
            idempotency_key=idempotency_key or None,
        )
        return {
            "provider": self.provider_name,
            "refund_id": data["id"],
            "status": data.get("status", "succeeded"),
            "amount_minor": data.get("amount", amount_minor or 0),
            "currency": str(data.get("currency", currency)).upper(),
            "raw_response": data,
        }

    async def void_authorization(
        self,
        *,
        authorization_id: str,
        idempotency_key: str = "",
        note: str | None = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        """Cancel a PaymentIntent or decline a Stripe Issuing authorization."""
        if authorization_id.startswith("iauth_"):
            path = f"/v1/issuing/authorizations/{authorization_id}/decline"
        else:
            path = f"/v1/payment_intents/{authorization_id}/cancel"
        payload: dict[str, Any] = {}
        if note:
            payload["cancellation_reason"] = "abandoned"
        data = await self._post_form(path, payload, idempotency_key=idempotency_key or None)
        return {
            "provider": self.provider_name,
            "authorization_id": data.get("id", authorization_id),
            "status": data.get("status", "canceled"),
            "raw_response": data,
        }

    async def get_order_status(
        self,
        *,
        order_id: str,
    ) -> dict[str, Any]:
        """Get canonical Stripe PaymentIntent status."""
        resp = await self._http.request(
            "GET",
            f"/v1/payment_intents/{order_id}",
            headers=self._build_headers(),
        )
        if resp.status_code >= 400:
            raise ProviderAPIError(
                f"Stripe get_order_status failed ({resp.status_code}): {resp.text}",
                status_code=resp.status_code,
                provider=self.provider_name,
            )
        payload = resp.json()
        return {
            "provider": self.provider_name,
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
        now = int(time.time())
        try:
            if abs(now - int(t)) > self.webhook_tolerance_seconds:
                return False
        except ValueError:
            return False
        signed_payload = f"{t}.".encode() + payload_bytes
        expected_sig = hmac.new(
            self.webhook_secret.encode("utf-8"),
            signed_payload,
            hashlib.sha256,
        ).hexdigest()
        return hmac.compare_digest(expected_sig, v1)

    async def provide_dispute_evidence(
        self,
        *,
        dispute_id: str,
        evidence_type: str,
        notes: str,
        documents: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        """Submit evidence to Stripe Smart Disputes / Disputes v1."""
        evidence: dict[str, Any] = {"uncategorized_text": f"[{evidence_type}] {notes}".strip()}
        for doc in documents or []:
            field = str(doc.get("stripe_field") or "").strip()
            value = doc.get("file_id") or doc.get("value")
            if field and value is not None:
                evidence[field] = value
            elif doc.get("tracking_number"):
                evidence["shipping_tracking_number"] = str(doc["tracking_number"])
        return await self.submit_smart_dispute_evidence(
            dispute_id=dispute_id,
            evidence=evidence,
            submit=True,
        )

    async def submit_smart_dispute_evidence(
        self,
        *,
        dispute_id: str,
        evidence: dict[str, Any],
        submit: bool = True,
        idempotency_key: str | None = None,
    ) -> dict[str, Any]:
        """Submit structured Smart Disputes evidence fields to Stripe."""
        data = await self._post_form(
            f"/v1/disputes/{dispute_id}",
            {"evidence": evidence, "submit": submit},
            idempotency_key=idempotency_key,
        )
        return {
            "provider": self.provider_name,
            "dispute_id": data.get("id", dispute_id),
            "status": data.get("status"),
            "submitted": submit,
            "raw_response": data,
        }

    async def accept_dispute_claim(
        self,
        *,
        dispute_id: str,
        reason: str,
    ) -> dict[str, Any]:
        """Concede / close a Stripe dispute."""
        data = await self._post_form(
            f"/v1/disputes/{dispute_id}/close",
            {"metadata": {"accept_reason": reason[:500]}},
        )
        return {
            "provider": self.provider_name,
            "dispute_id": data.get("id", dispute_id),
            "status": data.get("status", "lost"),
            "raw_response": data,
        }

    def _verify_stripe_signature(self, *, headers: dict[str, str], body: bytes) -> int:
        if not self.webhook_secret:
            raise ProviderConfigurationError("STRIPE_WEBHOOK_SECRET is not configured")

        normalized = {k.lower(): v for k, v in headers.items()}
        sig_header = normalized.get("stripe-signature", "")
        if not sig_header:
            raise ProviderSignatureError("Missing Stripe-Signature header")

        timestamp: int | None = None
        v1_signatures: list[str] = []
        for part in sig_header.split(","):
            key, sep, val = part.strip().partition("=")
            if not sep:
                continue
            if key == "t":
                try:
                    timestamp = int(val)
                except ValueError as exc:
                    raise ProviderSignatureError("Invalid Stripe-Signature timestamp") from exc
            elif key == "v1":
                v1_signatures.append(val)

        if timestamp is None or not v1_signatures:
            raise ProviderSignatureError("Malformed Stripe-Signature header")

        now = int(time.time())
        if abs(now - timestamp) > self.webhook_tolerance_seconds:
            raise ProviderSignatureError("Stripe webhook timestamp outside replay tolerance window")

        signed_payload = f"{timestamp}.{body.decode('utf-8')}".encode()
        expected = hmac.new(
            self.webhook_secret.encode("utf-8"),
            signed_payload,
            hashlib.sha256,
        ).hexdigest()
        if not any(hmac.compare_digest(expected, sig) for sig in v1_signatures):
            raise ProviderSignatureError("Invalid Stripe-Signature HMAC digest")
        return timestamp

    async def verify_webhook(
        self,
        *,
        headers: dict[str, str],
        body: bytes,
    ) -> dict[str, Any]:
        """Verify Stripe webhook signature and normalize into StripeEventEnvelope."""
        timestamp = self._verify_stripe_signature(headers=headers, body=body)
        try:
            event = json.loads(body.decode("utf-8"))
        except Exception as exc:
            raise ProviderValidationError("Invalid JSON in Stripe webhook body") from exc

        obj = (event.get("data") or {}).get("object") or {}
        tenant_raw = (obj.get("metadata") or {}).get("tenant_id")
        try:
            tenant_id = UUID(str(tenant_raw)) if tenant_raw else DEFAULT_TENANT_UUID
        except ValueError:
            tenant_id = DEFAULT_TENANT_UUID

        raw_amount = obj.get("amount")
        amount_minor = int(raw_amount) if isinstance(raw_amount, int) and raw_amount >= 0 else None
        raw_currency = obj.get("currency")
        currency = str(raw_currency).upper() if isinstance(raw_currency, str) and len(raw_currency) == 3 else None

        envelope = StripeEventEnvelope(
            event_id=str(event["id"]),
            tenant_id=tenant_id,
            event_type=str(event["type"]),
            api_version=event.get("api_version"),
            payment_intent_ref=obj.get("payment_intent") or (obj.get("id") if str(obj.get("id", "")).startswith("pi_") else None),
            amount_minor=amount_minor,
            currency=currency,
            payload=event,
        )
        return {
            "verified": True,
            "provider": self.provider_name,
            "timestamp": timestamp,
            "is_issuing_event": envelope.event_type.startswith("issuing_"),
            "payload_hash": compute_payload_hash(event),
            "envelope": envelope.model_dump(mode="json"),
        }

    async def parse_issuing_webhook(
        self,
        *,
        headers: dict[str, str],
        body: bytes,
    ) -> dict[str, Any]:
        """Verify and extract structured Stripe Issuing authorization/transaction fields."""
        verified = await self.verify_webhook(headers=headers, body=body)
        envelope_data = verified["envelope"]
        event_type = envelope_data["event_type"]
        if not event_type.startswith("issuing_"):
            raise ProviderValidationError(f"Expected Stripe Issuing event, got {event_type!r}")

        obj = (envelope_data["payload"].get("data") or {}).get("object") or {}
        card = obj.get("card")
        card_id = card.get("id") if isinstance(card, dict) else card
        return {
            "verified": True,
            "event_id": envelope_data["event_id"],
            "event_type": event_type,
            "authorization_id": obj.get("authorization") or obj.get("id"),
            "card_id": card_id,
            "amount_minor": envelope_data["amount_minor"],
            "currency": envelope_data["currency"],
            "approved": obj.get("approved"),
            "merchant_data": obj.get("merchant_data") or {},
            "envelope": envelope_data,
        }
