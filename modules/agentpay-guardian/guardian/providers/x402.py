"""HTTP 402 / x402 micro-payment settlement proof verifier and adapter for AgentPay Guardian."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import re
from dataclasses import dataclass
from datetime import UTC, datetime
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


class X402SettlementVerifier:
    """Verifies HTTP 402 payment required micro-settlement proofs for on-chain/L2 transactions."""

    SUPPORTED_CHAIN_IDS = {
        1: "Ethereum Mainnet",
        10: "Optimism",
        137: "Polygon",
        8453: "Base",
        42161: "Arbitrum One",
        11155111: "Sepolia Testnet",
    }

    HEX_ADDR_REGEX = re.compile(r"^0x[a-fA-F0-9]{40}$")
    TX_HASH_REGEX = re.compile(r"^0x[a-fA-F0-9]{64}$")

    @classmethod
    def compute_settlement_digest(cls, proof: X402SettlementProof) -> str:
        """Compute SHA-256 digest of normalized settlement proof."""
        raw = (
            f"{proof.proof_id}:{proof.tenant_id}:{proof.correlation_id}:"
            f"{proof.chain_id}:{proof.transaction_hash.lower()}:"
            f"{proof.token_address.lower()}:{proof.amount_units}:"
            f"{proof.payer_address.lower()}:{proof.recipient_address.lower()}:"
            f"{proof.block_number}"
        )
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    @classmethod
    def verify_settlement_proof(
        cls,
        proof: X402SettlementProof,
        *,
        expected_recipient: str | None = None,
        min_amount_units: int | None = None,
        max_age_seconds: int | None = 86400,
        now: datetime | None = None,
    ) -> tuple[bool, str | None]:
        """Verify on-chain settlement proof fields, address formats, recipient binding, and timing.

        Returns (is_valid, failure_reason).
        """
        if proof.chain_id not in cls.SUPPORTED_CHAIN_IDS:
            return False, f"Unsupported blockchain network chain_id: {proof.chain_id}"

        tx_hash = getattr(proof, "transaction_hash", None) or getattr(proof, "tx_hash", "")
        if not cls.TX_HASH_REGEX.match(tx_hash) and not _HEX_TX_RE.match(tx_hash):
            return False, f"Invalid transaction hash format: {tx_hash}"

        token_addr = getattr(proof, "token_address", "0x0000000000000000000000000000000000000000")
        payer_addr = getattr(proof, "payer_address", "")
        recip_addr = getattr(proof, "recipient_address", None) or getattr(proof, "payee_address", "")

        for addr_name, addr_val in [
            ("token_address", token_addr),
            ("payer_address", payer_addr),
            ("recipient_address", recip_addr),
        ]:
            if not cls.HEX_ADDR_REGEX.match(addr_val) and not addr_val.startswith("0x"):
                return False, f"Invalid {addr_name} hex format: {addr_val}"

        if payer_addr.lower() == recip_addr.lower():
            return False, "Payer address cannot be identical to recipient address"

        try:
            amt = getattr(proof, "amount_units", None) or getattr(proof, "amount_minor", 0)
            amount_val = int(amt)
            if amount_val <= 0:
                return False, f"Amount units must be strictly positive: {amt}"
            if min_amount_units is not None and amount_val < min_amount_units:
                return False, f"Settlement amount {amount_val} below required minimum {min_amount_units}"
        except ValueError:
            return False, f"Invalid non-integer amount: {amt}"

        block_num = getattr(proof, "block_number", 1)
        if block_num <= 0:
            return False, f"Invalid block number: {block_num}"

        if (
            expected_recipient is not None
            and recip_addr.lower() != expected_recipient.lower()
        ):
            return (
                False,
                f"Recipient address mismatch: got {recip_addr}, expected {expected_recipient}",
            )

        current_time = now or datetime.now(UTC)
        settled = getattr(proof, "settled_at", None)
        if settled is not None:
            if settled > current_time:
                return False, "Settlement timestamp is in the future"

            if max_age_seconds is not None:
                age = (current_time - settled).total_seconds()
                if age > max_age_seconds:
                    return False, f"Settlement proof expired: age {int(age)}s exceeds {max_age_seconds}s limit"

        return True, None


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

        payer_addr = getattr(proof, "payer_address", "")
        payee_addr = getattr(proof, "payee_address", None) or getattr(proof, "recipient_address", "")
        if payer_addr.strip().lower() == payee_addr.strip().lower():
            raise ProviderValidationError("x402 payer_address and payee_address cannot be identical")

        tx_hash = getattr(proof, "tx_hash", None) or getattr(proof, "transaction_hash", "")
        if tx_hash.startswith("0x") and not _HEX_TX_RE.match(tx_hash):
            raise ProviderValidationError(f"Malformed EVM tx_hash: {tx_hash!r}")

        amount = getattr(proof, "amount_minor", None) or getattr(proof, "amount_units", 0)
        if expected_amount_minor is not None and amount < expected_amount_minor:
            raise ProviderValidationError(
                f"x402 settlement amount {amount} is below expected {expected_amount_minor}"
            )
        network = getattr(proof, "network", None) or str(getattr(proof, "chain_id", ""))
        if expected_network is not None and network.lower() != expected_network.strip().lower():
            raise ProviderValidationError(
                f"x402 network mismatch: expected {expected_network!r}, got {network!r}"
            )
        asset = getattr(proof, "asset", None) or getattr(proof, "token_address", "")
        if expected_asset is not None and asset.upper() != expected_asset.strip().upper():
            raise ProviderValidationError(
                f"x402 asset mismatch: expected {expected_asset!r}, got {asset!r}"
            )
        if expected_payee is not None and payee_addr.strip().lower() != expected_payee.strip().lower():
            raise ProviderValidationError(
                f"x402 payee mismatch: expected {expected_payee!r}, got {payee_addr!r}"
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
            if remote_tx and str(remote_tx).lower() != tx_hash.lower():
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
