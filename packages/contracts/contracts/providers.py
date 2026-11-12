"""Canonical payment provider adapter protocol for AgentPay Nexus."""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class PaymentProviderAdapter(Protocol):
    """Unified async payment rail / provider adapter protocol."""

    provider_name: str = ""

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
    ) -> dict[str, Any]: ...

    async def capture_order(
        self,
        *,
        order_id: str,
        idempotency_key: str = "",
        amount_minor: int | None = None,
        currency: str | None = None,
        request_id: str | None = None,
    ) -> dict[str, Any]: ...

    async def refund_capture(
        self,
        *,
        capture_id: str,
        amount_minor: int,
        currency: str = "USD",
        idempotency_key: str = "",
        reason: str | None = None,
        note: str | None = None,
    ) -> dict[str, Any]: ...

    async def void_authorization(
        self,
        *,
        authorization_id: str,
        idempotency_key: str = "",
        note: str | None = None,
    ) -> dict[str, Any]: ...

    async def get_order_status(
        self,
        *,
        order_id: str,
    ) -> dict[str, Any]: ...

    async def provide_dispute_evidence(
        self,
        *,
        dispute_id: str,
        evidence_type: str,
        notes: str = "",
        documents: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]: ...

    async def accept_dispute_claim(
        self,
        *,
        dispute_id: str,
        reason: str = "",
    ) -> dict[str, Any]: ...

    async def verify_webhook(
        self,
        *,
        headers: dict[str, str],
        body: bytes,
    ) -> dict[str, Any]: ...
