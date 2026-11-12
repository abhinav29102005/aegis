"""Visa TAP & Mastercard Agent Pay token provenance verifier and adapter."""

from __future__ import annotations

import hashlib
import hmac
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Literal

import httpx
from contracts import TAPTokenPayload, compute_payload_hash
from security import verify_hmac_sha256

from guardian.providers.base import (
    ProviderAPIError,
    ProviderConfigurationError,
    ProviderSignatureError,
    ProviderValidationError,
    RetryingHTTPClient,
)

TAPNetwork = Literal["VISA_TAP", "MASTERCARD_AGENT_PAY"]


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _normalize_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


@dataclass(frozen=True)
class TAPProvenanceResult:
    """Verified provenance output for Visa TAP or Mastercard Agent Pay tokens."""

    verified: bool
    network: TAPNetwork
    payload: TAPTokenPayload
    token_hash: str
    introspection_claims: dict[str, Any] | None = None


class TAPProvenanceAdapter:
    """Visa Trusted Agent Protocol (TAP) & Mastercard Agent Pay provenance verifier."""

    provider_name = "tap"

    def __init__(
        self,
        *,
        signing_secret: str | None = None,
        introspection_url: str | None = None,
        gateway_url: str | None = None,
        default_network: TAPNetwork = "VISA_TAP",
        http_client: httpx.AsyncClient | None = None,
        timeout_seconds: float = 15.0,
        max_retries: int = 2,
        retry_base_delay: float = 0.05,
    ) -> None:
        self.signing_secret = signing_secret
        self.introspection_url = introspection_url.rstrip("/") if introspection_url else None
        self.gateway_url = gateway_url.rstrip("/") if gateway_url else None
        self.default_network: TAPNetwork = default_network
        self._seen_nonces: set[str] = set()
        self._http = RetryingHTTPClient(
            provider_name=self.provider_name,
            base_url=self.gateway_url or self.introspection_url or "https://tap.local",
            http_client=http_client,
            timeout_seconds=timeout_seconds,
            max_retries=max_retries,
            retry_base_delay=retry_base_delay,
        )

    @staticmethod
    def token_signing_payload(token: TAPTokenPayload, *, network: TAPNetwork) -> dict[str, Any]:
        return {
            "network": network,
            "token_id": token.token_id,
            "tenant_id": str(token.tenant_id),
            "agent_id": str(token.agent_id),
            "merchant_domain": token.merchant_domain.lower(),
            "amount_minor": token.amount_minor,
            "currency": token.currency.upper(),
            "nonce": token.nonce,
            "expires_at": token.expires_at.isoformat(),
        }

    @staticmethod
    def _resolve_network(raw_data: dict[str, Any] | TAPTokenPayload, default: TAPNetwork) -> TAPNetwork:
        if isinstance(raw_data, dict):
            raw_net = str(raw_data.get("network") or raw_data.get("rail") or "").strip().upper()
            if raw_net in ("MASTERCARD_AGENT_PAY", "MASTERCARD", "MC_AGENT_PAY"):
                return "MASTERCARD_AGENT_PAY"
            if raw_net in ("VISA_TAP", "VISA", "TAP"):
                return "VISA_TAP"
        return default

    async def verify_token_provenance(
        self,
        token_data: TAPTokenPayload | dict[str, Any],
        *,
        network: TAPNetwork | None = None,
        shared_secret: str | None = None,
        expected_merchant_domain: str | None = None,
        expected_amount_minor: int | None = None,
        expected_currency: str | None = None,
        now: datetime | None = None,
    ) -> TAPProvenanceResult:
        """Verify TAP / Agent Pay token expiry, nonce freshness, bindings, and cryptographic signature."""
        resolved_network = network or self._resolve_network(token_data, self.default_network)
        if isinstance(token_data, TAPTokenPayload):
            payload = token_data
        else:
            cleaned = {k: v for k, v in token_data.items() if k not in ("network", "rail")}
            payload = TAPTokenPayload.model_validate(cleaned)

        current_time = _normalize_utc(now or _utc_now())
        if payload.expires_at <= current_time:
            raise ProviderValidationError(f"{resolved_network} token {payload.token_id} is expired")

        nonce_key = f"{payload.tenant_id}:{resolved_network}:{payload.nonce}"
        if nonce_key in self._seen_nonces:
            raise ProviderSignatureError(
                f"Replay detected: {resolved_network} nonce {payload.nonce!r} already consumed"
            )

        if (
            expected_merchant_domain is not None
            and payload.merchant_domain.lower() != expected_merchant_domain.strip().lower()
        ):
            raise ProviderValidationError(
                f"Merchant domain mismatch: expected {expected_merchant_domain!r}, "
                f"got {payload.merchant_domain!r}"
            )
        if expected_amount_minor is not None and payload.amount_minor != expected_amount_minor:
            raise ProviderValidationError(
                f"Amount mismatch: expected {expected_amount_minor}, got {payload.amount_minor}"
            )
        if expected_currency is not None and payload.currency != expected_currency.upper():
            raise ProviderValidationError(
                f"Currency mismatch: expected {expected_currency.upper()}, got {payload.currency}"
            )

        introspection_claims: dict[str, Any] | None = None
        secret = shared_secret or self.signing_secret

        if self.introspection_url:
            resp = await self._http.request(
                "POST",
                f"{self.introspection_url}/introspect",
                json={
                    "network": resolved_network,
                    "token_id": payload.token_id,
                    "signature": payload.signature,
                    "payload": self.token_signing_payload(payload, network=resolved_network),
                },
                headers={"Content-Type": "application/json"},
            )
            if resp.status_code >= 400:
                raise ProviderAPIError(
                    f"{resolved_network} introspection failed ({resp.status_code}): {resp.text}",
                    status_code=resp.status_code,
                    provider=self.provider_name,
                )
            introspection_claims = resp.json()
            if not introspection_claims.get("active"):
                raise ProviderSignatureError(
                    f"{resolved_network} token {payload.token_id} rejected by introspection"
                )
        elif secret:
            canonical = self.token_signing_payload(payload, network=resolved_network)
            if not verify_hmac_sha256(canonical, payload.signature, secret):
                raise ProviderSignatureError(
                    f"Invalid cryptographic signature on {resolved_network} token {payload.token_id}"
                )
        else:
            raise ProviderConfigurationError(
                "Either signing_secret or introspection_url must be configured to verify TAP provenance"
            )

        self._seen_nonces.add(nonce_key)
        token_hash = compute_payload_hash(self.token_signing_payload(payload, network=resolved_network))
        return TAPProvenanceResult(
            verified=True,
            network=resolved_network,
            payload=payload,
            token_hash=token_hash,
            introspection_claims=introspection_claims,
        )

    async def _post_gateway(
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
                f"TAP gateway error on {path} ({resp.status_code}): {resp.text}",
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
        provenance_result: TAPProvenanceResult | None = None
        if "tap_token" in meta:
            provenance_result = await self.verify_token_provenance(
                meta["tap_token"],
                expected_amount_minor=amount_minor,
                expected_currency=currency,
                expected_merchant_domain=meta.get("merchant_domain"),
            )

        if self.gateway_url:
            data = await self._post_gateway(
                "/v1/tap/orders",
                {
                    "amount_minor": amount_minor,
                    "currency": currency.upper(),
                    "idempotency_key": idempotency_key,
                    "metadata": meta,
                },
                idempotency_key=idempotency_key,
            )
            return {"provider": self.provider_name, **data}

        return {
            "provider": self.provider_name,
            "order_id": f"tap_ord_{idempotency_key[:16]}",
            "status": "PROVENANCE_VERIFIED" if provenance_result else "CREATED",
            "amount_minor": amount_minor,
            "currency": currency.upper(),
            "network": provenance_result.network if provenance_result else self.default_network,
            "token_hash": provenance_result.token_hash if provenance_result else None,
        }

    async def get_order_status(
        self,
        *,
        order_id: str,
    ) -> dict[str, Any]:
        if self.gateway_url:
            resp = await self._http.request("GET", f"/v1/tap/orders/{order_id}")
            return resp.json()
        return {
            "provider": self.provider_name,
            "order_id": order_id,
            "status": "CAPTURED",
        }

    async def capture_order(
        self,
        *,
        order_id: str,
        idempotency_key: str,
        amount_minor: int | None = None,
        currency: str | None = None,
    ) -> dict[str, Any]:
        if self.gateway_url:
            data = await self._post_gateway(
                f"/v1/tap/orders/{order_id}/capture",
                {"amount_minor": amount_minor, "currency": currency},
                idempotency_key=idempotency_key,
            )
            return {"provider": self.provider_name, **data}
        return {
            "provider": self.provider_name,
            "order_id": order_id,
            "capture_id": f"tap_cap_{order_id}",
            "status": "CAPTURED",
            "amount_minor": amount_minor,
            "currency": currency.upper() if currency else None,
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
        if self.gateway_url:
            data = await self._post_gateway(
                f"/v1/tap/captures/{capture_id}/refund",
                {"amount_minor": amount_minor, "currency": currency.upper(), "reason": reason},
                idempotency_key=idempotency_key,
            )
            return {"provider": self.provider_name, **data}
        return {
            "provider": self.provider_name,
            "refund_id": f"tap_ref_{idempotency_key[:16]}",
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
        if self.gateway_url:
            data = await self._post_gateway(
                f"/v1/tap/authorizations/{authorization_id}/void",
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
        if self.gateway_url:
            data = await self._post_gateway(
                f"/v1/tap/disputes/{dispute_id}/evidence",
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
        if self.gateway_url:
            data = await self._post_gateway(
                f"/v1/tap/disputes/{dispute_id}/accept",
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
        if not self.signing_secret:
            raise ProviderConfigurationError("signing_secret is required to verify TAP webhooks")
        normalized = {k.lower(): v for k, v in headers.items()}
        sig = normalized.get("x-tap-signature", "")
        if not sig:
            raise ProviderSignatureError("Missing X-TAP-Signature header")
        expected = hmac.new(self.signing_secret.encode("utf-8"), body, hashlib.sha256).hexdigest()
        if not hmac.compare_digest(expected, sig):
            raise ProviderSignatureError("Invalid X-TAP-Signature digest")
        try:
            event = json.loads(body.decode("utf-8"))
        except Exception as exc:
            raise ProviderValidationError("Invalid TAP webhook JSON payload") from exc
        return {
            "verified": True,
            "provider": self.provider_name,
            "payload_hash": compute_payload_hash(event),
            "event": event,
        }
