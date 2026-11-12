"""Canonical payment provider adapter interface protocols for multi-rail execution."""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class PaymentProviderAdapter(Protocol):
    """Provider-neutral payment execution protocol implemented by PayPal, Stripe, and rail adapters."""

    provider_name: str

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
        """Create a payment intent / order with the upstream provider."""
        ...

    async def capture_order(
        self,
        *,
        order_id: str,
        amount_minor: int | None = None,
        currency: str = "USD",
        request_id: str | None = None,
    ) -> dict[str, Any]:
        """Execute settlement / capture of an authorized order."""
        ...

    async def refund_capture(
        self,
        *,
        capture_id: str,
        amount_minor: int | None = None,
        currency: str = "USD",
        note: str | None = None,
    ) -> dict[str, Any]:
        """Issue full or partial refund for a captured payment."""
        ...

    async def void_authorization(
        self,
        *,
        authorization_id: str,
        note: str | None = None,
    ) -> dict[str, Any]:
        """Void an uncaptured authorization hold."""
        ...

    async def get_order_status(
        self,
        *,
        order_id: str,
    ) -> dict[str, Any]:
        """Query provider for canonical order status and capture details."""
        ...
