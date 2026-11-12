"""Google AP2 (Agent Payments Protocol) CheckoutMandate & PaymentMandate adapter."""

from __future__ import annotations

import hashlib
import hmac
import json
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

import httpx
from contracts import (
    AP2MandatePayload,
    PurchaseProposal,
    QuoteSnapshot,
    compute_payload_hash,
)
from pydantic import BaseModel, Field, field_validator
from security import verify_hmac_sha256

from guardian.providers.base import (
    ProviderAPIError,
    ProviderConfigurationError,
    ProviderSignatureError,
    ProviderValidationError,
    RetryingHTTPClient,
)


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _normalize_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


class AP2CheckoutMandate(BaseModel):
    """Google AP2 CheckoutMandate representation."""

    mandate_id: str = Field(min_length=1, max_length=128)
    merchant_name: str = Field(min_length=1, max_length=160)
    merchant_category: str = Field(default="SOFTWARE", max_length=64)
    amount_minor: int = Field(gt=0)
    currency: str = Field(default="USD", min_length=3, max_length=3)
    item_summary: str = Field(min_length=1, max_length=500)
    line_items: list[dict[str, Any]] = Field(default_factory=list)
    idempotency_key: str = Field(min_length=8, max_length=128)
    expires_at: datetime
    signature: str = Field(min_length=8, max_length=512)
    issued_at: datetime = Field(default_factory=_utc_now)
    scope: str = Field(default="checkout", max_length=64)

    @field_validator("currency")
    @classmethod
    def _upper_currency(cls, value: str) -> str:
        return value.upper()

    @field_validator("expires_at", "issued_at")
    @classmethod
    def _utc_dates(cls, value: datetime) -> datetime:
        return _normalize_utc(value)


class AP2PaymentMandate(BaseModel):
    """Google AP2 PaymentMandate representation."""

    mandate_id: str = Field(min_length=1, max_length=128)
    tenant_id: UUID
    agent_id: UUID
    passport_id: UUID | None = None
    merchant_id: UUID | None = None
    max_amount_minor: int = Field(gt=0)
    currency: str = Field(default="USD", min_length=3, max_length=3)
    scope: list[str] = Field(default_factory=list)
    expires_at: datetime
    signature: str = Field(min_length=8, max_length=512)
    issued_at: datetime = Field(default_factory=_utc_now)

    @field_validator("currency")
    @classmethod
    def _upper_currency(cls, value: str) -> str:
        return value.upper()

    @field_validator("expires_at", "issued_at")
    @classmethod
    def _utc_dates(cls, value: datetime) -> datetime:
        return _normalize_utc(value)


class AP2MandateAdapter:
    """AP2 CheckoutMandate / PaymentMandate verifier, Guardian importer, and rail adapter."""

    provider_name = "ap2"

    def __init__(
        self,
        *,
        signing_secret: str | None = None,
        facilitator_url: str | None = None,
        http_client: httpx.AsyncClient | None = None,
        timeout_seconds: float = 15.0,
        max_retries: int = 2,
        retry_base_delay: float = 0.05,
    ) -> None:
        self.signing_secret = signing_secret
        self.facilitator_url = facilitator_url.rstrip("/") if facilitator_url else None
        self._http = RetryingHTTPClient(
            provider_name=self.provider_name,
            base_url=self.facilitator_url or "https://ap2.local",
            http_client=http_client,
            timeout_seconds=timeout_seconds,
            max_retries=max_retries,
            retry_base_delay=retry_base_delay,
        )
        self._mandate_orders: dict[str, dict[str, Any]] = {}

    @staticmethod
    def payment_mandate_signing_payload(mandate: AP2MandatePayload | AP2PaymentMandate) -> dict[str, Any]:
        return {
            "mandate_id": mandate.mandate_id,
            "tenant_id": str(mandate.tenant_id),
            "agent_id": str(mandate.agent_id),
            "passport_id": str(mandate.passport_id) if mandate.passport_id else None,
            "merchant_id": str(mandate.merchant_id) if mandate.merchant_id else None,
            "max_amount_minor": mandate.max_amount_minor,
            "currency": mandate.currency.upper(),
            "scope": list(mandate.scope),
            "expires_at": mandate.expires_at.isoformat(),
        }

    @staticmethod
    def checkout_mandate_signing_payload(mandate: AP2CheckoutMandate) -> dict[str, Any]:
        return {
            "mandate_id": mandate.mandate_id,
            "merchant_name": mandate.merchant_name,
            "merchant_category": mandate.merchant_category,
            "amount_minor": mandate.amount_minor,
            "currency": mandate.currency.upper(),
            "line_items": mandate.line_items,
            "idempotency_key": mandate.idempotency_key,
            "expires_at": mandate.expires_at.isoformat(),
            "scope": mandate.scope,
        }

    def _resolve_secret(self, shared_secret: str | None) -> str:
        secret = shared_secret or self.signing_secret
        if not secret:
            raise ProviderConfigurationError("AP2 mandate signing secret is required for verification")
        return secret

    def verify_payment_mandate(
        self,
        mandate_data: AP2MandatePayload | AP2PaymentMandate | dict[str, Any],
        *,
        shared_secret: str | None = None,
        now: datetime | None = None,
    ) -> AP2MandatePayload:
        """Verify AP2 PaymentMandate expiry and HMAC-SHA256 signature fail-closed."""
        if isinstance(mandate_data, AP2MandatePayload):
            normalized = mandate_data
        elif isinstance(mandate_data, AP2PaymentMandate):
            normalized = AP2MandatePayload(**mandate_data.model_dump())
        else:
            normalized = AP2MandatePayload.model_validate(mandate_data)

        current_time = _normalize_utc(now or _utc_now())
        if normalized.expires_at <= current_time:
            raise ProviderValidationError(f"AP2 PaymentMandate {normalized.mandate_id} is expired")

        secret = self._resolve_secret(shared_secret)
        canonical = self.payment_mandate_signing_payload(normalized)
        if not verify_hmac_sha256(canonical, normalized.signature, secret):
            raise ProviderSignatureError(
                f"Invalid signature on AP2 PaymentMandate {normalized.mandate_id}"
            )
        return normalized

    def verify_checkout_mandate(
        self,
        checkout_data: AP2CheckoutMandate | dict[str, Any],
        *,
        shared_secret: str | None = None,
        now: datetime | None = None,
    ) -> AP2CheckoutMandate:
        """Verify AP2 CheckoutMandate expiry and HMAC-SHA256 signature fail-closed."""
        checkout = (
            checkout_data
            if isinstance(checkout_data, AP2CheckoutMandate)
            else AP2CheckoutMandate.model_validate(checkout_data)
        )
        current_time = _normalize_utc(now or _utc_now())
        if checkout.expires_at <= current_time:
            raise ProviderValidationError(f"AP2 CheckoutMandate {checkout.mandate_id} is expired")

        secret = self._resolve_secret(shared_secret)
        canonical = self.checkout_mandate_signing_payload(checkout)
        if not verify_hmac_sha256(canonical, checkout.signature, secret):
            raise ProviderSignatureError(
                f"Invalid signature on AP2 CheckoutMandate {checkout.mandate_id}"
            )
        return checkout

    def import_checkout_mandate(
        self,
        *,
        checkout_mandate: AP2CheckoutMandate | dict[str, Any],
        payment_mandate: AP2MandatePayload | AP2PaymentMandate | dict[str, Any],
        passport_id: UUID | None = None,
        merchant_id: UUID | None = None,
        correlation_id: UUID | None = None,
        shared_secret: str | None = None,
        now: datetime | None = None,
    ) -> tuple[PurchaseProposal, QuoteSnapshot]:
        """Verify AP2 mandates and convert them into non-authoritative Guardian models."""
        verified_payment = self.verify_payment_mandate(
            payment_mandate,
            shared_secret=shared_secret,
            now=now,
        )
        verified_checkout = self.verify_checkout_mandate(
            checkout_mandate,
            shared_secret=shared_secret,
            now=now,
        )

        if verified_checkout.currency != verified_payment.currency:
            raise ProviderValidationError(
                f"AP2 currency mismatch: checkout={verified_checkout.currency}, "
                f"payment_mandate={verified_payment.currency}"
            )
        if verified_checkout.amount_minor > verified_payment.max_amount_minor:
            raise ProviderValidationError(
                f"AP2 checkout amount {verified_checkout.amount_minor} exceeds "
                f"PaymentMandate ceiling {verified_payment.max_amount_minor}"
            )
        if verified_payment.scope and verified_checkout.scope not in verified_payment.scope:
            raise ProviderValidationError(
                f"AP2 checkout scope {verified_checkout.scope!r} is not authorized by PaymentMandate"
            )

        resolved_passport_id = passport_id or verified_payment.passport_id
        resolved_merchant_id = merchant_id or verified_payment.merchant_id
        if resolved_passport_id is None or resolved_merchant_id is None:
            raise ProviderValidationError(
                "passport_id and merchant_id must be provided or bound on AP2 PaymentMandate"
            )
        if (
            verified_payment.merchant_id is not None
            and resolved_merchant_id != verified_payment.merchant_id
        ):
            raise ProviderValidationError("AP2 PaymentMandate merchant_id binding mismatch")

        corr_id = correlation_id or uuid4()
        mandate_hash = compute_payload_hash({
            "payment_mandate": self.payment_mandate_signing_payload(verified_payment),
            "checkout_mandate": self.checkout_mandate_signing_payload(verified_checkout),
        })
        proposal = PurchaseProposal(
            tenant_id=verified_payment.tenant_id,
            correlation_id=corr_id,
            agent_id=verified_payment.agent_id,
            passport_id=resolved_passport_id,
            merchant_id=resolved_merchant_id,
            merchant_name=verified_checkout.merchant_name,
            merchant_category=verified_checkout.merchant_category,
            amount_minor=verified_checkout.amount_minor,
            currency=verified_checkout.currency,
            item_summary=verified_checkout.item_summary,
            line_items=verified_checkout.line_items,
            rationale=(
                f"Imported from verified AP2 CheckoutMandate={verified_checkout.mandate_id} "
                f"and PaymentMandate={verified_payment.mandate_id} (hash={mandate_hash[:16]})"
            ),
            idempotency_key=verified_checkout.idempotency_key,
            proposed_by_model="ap2-mandate-importer",
        )
        quote = QuoteSnapshot(
            tenant_id=verified_payment.tenant_id,
            correlation_id=corr_id,
            proposal_id=proposal.id,
            merchant_id=resolved_merchant_id,
            amount_minor=verified_checkout.amount_minor,
            currency=verified_checkout.currency,
            line_items=verified_checkout.line_items,
            expires_at=min(verified_checkout.expires_at, verified_payment.expires_at),
        )
        return proposal, quote

    async def _post_facilitator(
        self,
        path: str,
        payload: dict[str, Any],
        *,
        idempotency_key: str | None = None,
    ) -> dict[str, Any]:
        headers = {"Content-Type": "application/json"}
        if idempotency_key:
            headers["Idempotency-Key"] = idempotency_key
        resp = await self._http.request("POST", path, json=payload, headers=headers)
        if resp.status_code >= 400:
            raise ProviderAPIError(
                f"AP2 facilitator error on {path} ({resp.status_code}): {resp.text}",
                status_code=resp.status_code,
                provider=self.provider_name,
            )
        return resp.json()

    async def create_order(
        self,
        *,
        amount_minor: int,
        currency: str,
        idempotency_key: str,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        if amount_minor <= 0:
            raise ProviderValidationError("amount_minor must be positive")
        meta = dict(metadata or {})
        if self.facilitator_url:
            data = await self._post_facilitator(
                "/v1/ap2/orders",
                {
                    "amount_minor": amount_minor,
                    "currency": currency.upper(),
                    "idempotency_key": idempotency_key,
                    "metadata": meta,
                },
                idempotency_key=idempotency_key,
            )
            return {"provider": self.provider_name, **data}

        order_id = f"ap2_ord_{idempotency_key[:16]}"
        record = {
            "provider": self.provider_name,
            "order_id": order_id,
            "status": "MANDATE_AUTHORIZED",
            "amount_minor": amount_minor,
            "currency": currency.upper(),
            "mandate_id": meta.get("mandate_id"),
            "expires_at": (_utc_now() + timedelta(minutes=15)).isoformat(),
        }
        self._mandate_orders[order_id] = record
        return record

    async def capture_order(
        self,
        *,
        order_id: str,
        idempotency_key: str,
        amount_minor: int | None = None,
        currency: str | None = None,
    ) -> dict[str, Any]:
        if self.facilitator_url:
            data = await self._post_facilitator(
                f"/v1/ap2/orders/{order_id}/capture",
                {"amount_minor": amount_minor, "currency": currency},
                idempotency_key=idempotency_key,
            )
            return {"provider": self.provider_name, **data}

        order = self._mandate_orders.get(order_id)
        resolved_amount = amount_minor if amount_minor is not None else (order or {}).get("amount_minor")
        resolved_currency = (currency or (order or {}).get("currency") or "USD").upper()
        return {
            "provider": self.provider_name,
            "order_id": order_id,
            "capture_id": f"ap2_cap_{order_id}",
            "status": "CAPTURED",
            "amount_minor": resolved_amount,
            "currency": resolved_currency,
        }

    async def refund_capture(
        self,
        *,
        capture_id: str,
        amount_minor: int,
        currency: str,
        idempotency_key: str,
        reason: str | None = None,
    ) -> dict[str, Any]:
        if amount_minor <= 0:
            raise ProviderValidationError("amount_minor must be positive")
        if self.facilitator_url:
            data = await self._post_facilitator(
                f"/v1/ap2/captures/{capture_id}/refund",
                {"amount_minor": amount_minor, "currency": currency.upper(), "reason": reason},
                idempotency_key=idempotency_key,
            )
            return {"provider": self.provider_name, **data}

        return {
            "provider": self.provider_name,
            "refund_id": f"ap2_ref_{idempotency_key[:16]}",
            "capture_id": capture_id,
            "status": "REFUNDED",
            "amount_minor": amount_minor,
            "currency": currency.upper(),
            "reason": reason,
        }

    async def void_authorization(
        self,
        *,
        authorization_id: str,
        idempotency_key: str,
    ) -> dict[str, Any]:
        if self.facilitator_url:
            data = await self._post_facilitator(
                f"/v1/ap2/authorizations/{authorization_id}/void",
                {},
                idempotency_key=idempotency_key,
            )
            return {"provider": self.provider_name, **data}

        return {
            "provider": self.provider_name,
            "authorization_id": authorization_id,
            "status": "VOIDED",
        }

    async def provide_dispute_evidence(
        self,
        *,
        dispute_id: str,
        evidence_type: str,
        notes: str,
        documents: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        payload = {
            "dispute_id": dispute_id,
            "evidence_type": evidence_type,
            "notes": notes,
            "documents": documents or [],
        }
        if self.facilitator_url:
            data = await self._post_facilitator(
                f"/v1/ap2/disputes/{dispute_id}/evidence",
                payload,
            )
            return {"provider": self.provider_name, **data}
        return {"provider": self.provider_name, "status": "EVIDENCE_RECORDED", **payload}

    async def accept_dispute_claim(
        self,
        *,
        dispute_id: str,
        reason: str,
    ) -> dict[str, Any]:
        if self.facilitator_url:
            data = await self._post_facilitator(
                f"/v1/ap2/disputes/{dispute_id}/accept",
                {"reason": reason},
            )
            return {"provider": self.provider_name, **data}
        return {
            "provider": self.provider_name,
            "dispute_id": dispute_id,
            "status": "ACCEPTED",
            "reason": reason,
        }

    async def verify_webhook(
        self,
        *,
        headers: dict[str, str],
        body: bytes,
    ) -> dict[str, Any]:
        secret = self._resolve_secret(None)
        normalized = {k.lower(): v for k, v in headers.items()}
        sig = normalized.get("x-ap2-signature", "")
        if not sig:
            raise ProviderSignatureError("Missing X-AP2-Signature header")
        expected = hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()
        if not hmac.compare_digest(expected, sig):
            raise ProviderSignatureError("Invalid X-AP2-Signature digest")
        try:
            payload = json.loads(body.decode("utf-8"))
        except Exception as exc:
            raise ProviderValidationError("Invalid AP2 webhook JSON payload") from exc
        return {
            "verified": True,
            "provider": self.provider_name,
            "payload_hash": compute_payload_hash(payload),
            "event": payload,
        }
