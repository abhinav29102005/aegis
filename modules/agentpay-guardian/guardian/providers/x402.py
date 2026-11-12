"""HTTP 402 / x402 micro-payment settlement proof verifier and adapter."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import re
from dataclasses import dataclass
from typing import Any

import httpx
from contracts import X402SettlementProof, compute_payload_hash

from guardian.providers.base import (
    ProviderAPIError,
    ProviderConfigurationError,
    ProviderSignatureError,
    ProviderValidationError,
    RetryingHTTPClient,
)

_HEX_TX_RE = re.compile(r"^0x[0-9a-fA-F]{8,128}$")


@dataclass(frozen=True)
class X402VerificationResult:
    """Verified x402 micro-payment settlement receipt."""

    verified: bool
    proof: X402SettlementProof
    proof_hash: str
    facilitator_receipt: dict[str, Any] | None = None


class X402SettlementAdapter:
    """Verifier and PaymentProviderAdapter for x402 HTTP micro-payment settlements."""

    provider_name = "x402"

    def __init__(
        self,
        *,
        facilitator_url: str | None = None,
        webhook_secret: str | None = None,
        http_client: httpx.AsyncClient | None = None,
        timeout_seconds: float = 15.0,
        max_retries: int = 2,
        retry_base_delay: float = 0.05,
    ) -> None:
        self.facilitator_url = facilitator_url.rstrip("/") if facilitator_url else None
        self.webhook_secret = webhook_secret
        self._http = RetryingHTTPClient(
            provider_name=self.provider_name,
            base_url=self.facilitator_url or "https://x402.local",
            http_client=http_client,
            timeout_seconds=timeout_seconds,
            max_retries=max_retries,
            retry_base_delay=retry_base_delay,
        )

    @staticmethod
    def parse_payment_required_header(header_value: str) -> dict[str, Any]:
        """Decode an HTTP 402 PAYMENT-REQUIRED header (raw JSON or base64-encoded JSON)."""
        raw = header_value.strip()
        if not raw:
            raise ProviderValidationError("Empty PAYMENT-REQUIRED header")
        if raw.startswith("{"):
            try:
                parsed = json.loads(raw)
                if isinstance(parsed, dict):
                    return parsed
            except Exception as exc:
                raise ProviderValidationError("Malformed JSON in PAYMENT-REQUIRED header") from exc

        padded = raw + ("=" * ((4 - len(raw) % 4) % 4))
        try:
            decoded = base64.b64decode(padded, validate=True).decode("utf-8")
            parsed = json.loads(decoded)
        except Exception as exc:
            raise ProviderValidationError("Malformed base64 JSON in PAYMENT-REQUIRED header") from exc
        if not isinstance(parsed, dict):
            raise ProviderValidationError("PAYMENT-REQUIRED payload must be a JSON object")
        return parsed

    async def verify_settlement_proof(
        self,
        proof_data: X402SettlementProof | dict[str, Any],
        *,
        expected_amount_minor: int | None = None,
        expected_network: str | None = None,
        expected_asset: str | None = None,
        expected_payee: str | None = None,
        verify_with_facilitator: bool = True,
    ) -> X402VerificationResult:
        """Verify an x402 on-chain settlement proof deterministically and via facilitator if configured."""
        proof = (
            proof_data
            if isinstance(proof_data, X402SettlementProof)
            else X402SettlementProof.model_validate(proof_data)
        )

        if proof.payer_address.strip().lower() == proof.payee_address.strip().lower():
            raise ProviderValidationError("x402 payer_address and payee_address cannot be identical")

        if proof.tx_hash.startswith("0x") and not _HEX_TX_RE.match(proof.tx_hash):
            raise ProviderValidationError(f"Malformed EVM tx_hash: {proof.tx_hash!r}")

        if expected_amount_minor is not None and proof.amount_minor < expected_amount_minor:
            raise ProviderValidationError(
                f"x402 settlement amount {proof.amount_minor} is below expected {expected_amount_minor}"
            )
        if expected_network is not None and proof.network.lower() != expected_network.strip().lower():
            raise ProviderValidationError(
                f"x402 network mismatch: expected {expected_network!r}, got {proof.network!r}"
            )
        if expected_asset is not None and proof.asset.upper() != expected_asset.strip().upper():
            raise ProviderValidationError(
                f"x402 asset mismatch: expected {expected_asset!r}, got {proof.asset!r}"
            )
        if expected_payee is not None and proof.payee_address.strip().lower() != expected_payee.strip().lower():
            raise ProviderValidationError(
                f"x402 payee mismatch: expected {expected_payee!r}, got {proof.payee_address!r}"
            )

        facilitator_receipt: dict[str, Any] | None = None
        if self.facilitator_url and verify_with_facilitator:
            resp = await self._http.request(
                "POST",
                f"{self.facilitator_url}/verify",
                json=proof.model_dump(mode="json"),
                headers={"Content-Type": "application/json"},
            )
            if resp.status_code >= 400:
                raise ProviderAPIError(
                    f"x402 facilitator verification failed ({resp.status_code}): {resp.text}",
                    status_code=resp.status_code,
                    provider=self.provider_name,
                )
            facilitator_receipt = resp.json()
            is_valid = bool(
                facilitator_receipt.get("isValid")
                or facilitator_receipt.get("verified")
                or facilitator_receipt.get("settled")
            )
            if not is_valid:
                raise ProviderValidationError(
                    f"x402 facilitator rejected proof {proof.proof_id}: "
                    f"{facilitator_receipt.get('invalidReason', 'unverified')}"
                )
            remote_tx = facilitator_receipt.get("tx_hash") or facilitator_receipt.get("transaction")
            if remote_tx and str(remote_tx).lower() != proof.tx_hash.lower():
                raise ProviderValidationError("x402 facilitator tx_hash mismatch")

        proof_hash = compute_payload_hash(proof.model_dump(mode="json"))
        return X402VerificationResult(
            verified=True,
            proof=proof,
            proof_hash=proof_hash,
            facilitator_receipt=facilitator_receipt,
        )

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
        resp = await self._http.request(
            "POST",
            f"{self.facilitator_url}{path}",
            json=payload,
            headers=headers,
        )
        if resp.status_code >= 400:
            raise ProviderAPIError(
                f"x402 facilitator error on {path} ({resp.status_code}): {resp.text}",
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
                "/orders",
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
            "order_id": f"x402_ord_{idempotency_key[:16]}",
            "status": "PAYMENT_REQUIRED",
            "amount_minor": amount_minor,
            "currency": currency.upper(),
            "network": meta.get("network", "base-sepolia"),
            "asset": meta.get("asset", "USDC"),
            "payee_address": meta.get("payee_address"),
        }

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
                "/settle",
                {
                    "order_id": order_id,
                    "amount_minor": amount_minor,
                    "currency": currency.upper() if currency else None,
                },
                idempotency_key=idempotency_key,
            )
            return {"provider": self.provider_name, **data}
        return {
            "provider": self.provider_name,
            "order_id": order_id,
            "capture_id": f"x402_settle_{order_id}",
            "status": "SETTLED",
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
        if self.facilitator_url:
            data = await self._post_facilitator(
                "/refunds",
                {
                    "capture_id": capture_id,
                    "amount_minor": amount_minor,
                    "currency": currency.upper(),
                    "reason": reason,
                },
                idempotency_key=idempotency_key,
            )
            return {"provider": self.provider_name, **data}
        return {
            "provider": self.provider_name,
            "refund_id": f"x402_ref_{idempotency_key[:16]}",
            "capture_id": capture_id,
            "status": "REFUND_SUBMITTED",
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
                f"/authorizations/{authorization_id}/void",
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
        return {
            "provider": self.provider_name,
            "dispute_id": dispute_id,
            "status": "ONCHAIN_PROOF_ATTACHED",
            "evidence_type": evidence_type,
            "notes": notes,
            "documents": documents or [],
        }

    async def accept_dispute_claim(
        self,
        *,
        dispute_id: str,
        reason: str,
    ) -> dict[str, Any]:
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
        if not self.webhook_secret:
            raise ProviderConfigurationError("webhook_secret is required to verify x402 webhooks")
        normalized = {k.lower(): v for k, v in headers.items()}
        sig = normalized.get("x-x402-signature", "")
        if not sig:
            raise ProviderSignatureError("Missing X-X402-Signature header")
        expected = hmac.new(self.webhook_secret.encode("utf-8"), body, hashlib.sha256).hexdigest()
        if not hmac.compare_digest(expected, sig):
            raise ProviderSignatureError("Invalid X-X402-Signature digest")
        try:
            event = json.loads(body.decode("utf-8"))
        except Exception as exc:
            raise ProviderValidationError("Invalid x402 webhook JSON payload") from exc
        return {
            "verified": True,
            "provider": self.provider_name,
            "payload_hash": compute_payload_hash(event),
            "event": event,
        }
