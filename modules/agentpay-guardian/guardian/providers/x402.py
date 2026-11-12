"""HTTP 402 / Web3 autonomous agent micro-settlement proof verifier for AgentPay Guardian."""

from __future__ import annotations

import hashlib
import re
from datetime import UTC, datetime

from contracts.models import X402SettlementProof


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

        if not cls.TX_HASH_REGEX.match(proof.transaction_hash):
            return False, f"Invalid transaction hash format: {proof.transaction_hash}"

        for addr_name, addr_val in [
            ("token_address", proof.token_address),
            ("payer_address", proof.payer_address),
            ("recipient_address", proof.recipient_address),
        ]:
            if not cls.HEX_ADDR_REGEX.match(addr_val):
                return False, f"Invalid {addr_name} hex format: {addr_val}"

        if proof.payer_address.lower() == proof.recipient_address.lower():
            return False, "Payer address cannot be identical to recipient address"

        try:
            amount_val = int(proof.amount_units)
            if amount_val <= 0:
                return False, f"Amount units must be strictly positive: {proof.amount_units}"
            if min_amount_units is not None and amount_val < min_amount_units:
                return False, f"Settlement amount {amount_val} below required minimum {min_amount_units}"
        except ValueError:
            return False, f"Invalid non-integer amount_units: {proof.amount_units}"

        if proof.block_number <= 0:
            return False, f"Invalid block number: {proof.block_number}"

        if (
            expected_recipient is not None
            and proof.recipient_address.lower() != expected_recipient.lower()
        ):
            return (
                False,
                f"Recipient address mismatch: got {proof.recipient_address}, expected {expected_recipient}",
            )

        current_time = now or datetime.now(UTC)
        if proof.settled_at > current_time:
            return False, "Settlement timestamp is in the future"

        if max_age_seconds is not None:
            age = (current_time - proof.settled_at).total_seconds()
            if age > max_age_seconds:
                return False, f"Settlement proof expired: age {int(age)}s exceeds {max_age_seconds}s limit"

        return True, None
