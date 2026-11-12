"""PayPal Sandbox Orders API v2 client, webhook verifier, and reconciliation adapter.

This module is strictly isolated from LangGraph and AI reasoning modules.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Protocol

import httpx
from contracts import VerifiedPayPalCapture, compute_payload_hash
from contracts.policy_v1 import format_minor_to_major, parse_major_to_minor
from security import NexusSettings, get_settings


class PayPalConfigurationError(RuntimeError):
    """Raised when sandbox PayPal credentials or mode are missing/invalid."""


class PayPalTimeoutError(TimeoutError):
    """Raised when a PayPal capture or order call times out (triggers PENDING_PROVIDER)."""


class PayPalAPIError(RuntimeError):
    """Raised when PayPal returns a non-success response."""

    def __init__(self, message: str, *, status_code: int = 502, debug_id: str | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.debug_id = debug_id


class PayPalDisputesDisabledError(PermissionError):
    """Raised when PayPal Disputes API is invoked while feature-flagged off."""


def minor_to_paypal_value(amount_minor: int, currency: str = "USD") -> str:
    """Format minor currency units to PayPal string using ISO 4217 exponents."""
    return format_minor_to_major(amount_minor, currency)


def paypal_value_to_minor(value_str: str, currency: str = "USD") -> int:
    """Parse PayPal decimal string to integer minor units using ISO 4217 exponents."""
    return parse_major_to_minor(value_str, currency)


@dataclass(frozen=True)
class PayPalOrderCreationResult:
    paypal_order_id: str
    status: str
    approval_url: str | None
    raw_response: dict[str, Any]


@dataclass(frozen=True)
class PayPalCaptureResult:
    verified_capture: VerifiedPayPalCapture
    raw_response: dict[str, Any]


@dataclass(frozen=True)
class PayPalRefundResult:
    refund_id: str
    status: str
    amount_minor: int
    currency: str
    raw_response: dict[str, Any]


@dataclass(frozen=True)
class PayPalReconciliationResult:
    paypal_order_id: str
    order_status: str
    verified_capture: VerifiedPayPalCapture | None
    raw_response: dict[str, Any]


class PayPalExecutorProtocol(Protocol):
    async def create_order(
        self,
        *,
        amount_minor: int,
        currency: str,
        reference_id: str,
        description: str,
        request_id: str,
        return_url: str | None = None,
        cancel_url: str | None = None,
    ) -> PayPalOrderCreationResult: ...

    async def get_order(self, *, paypal_order_id: str) -> dict[str, Any]: ...

    async def capture_order(
        self,
        *,
        paypal_order_id: str,
        expected_amount_minor: int,
        expected_currency: str,
        request_id: str,
    ) -> PayPalCaptureResult: ...

    async def reconcile_order(
        self,
        *,
        paypal_order_id: str,
        expected_amount_minor: int,
        expected_currency: str,
    ) -> PayPalReconciliationResult: ...

    async def verify_webhook_signature(
        self,
        *,
        headers: dict[str, str],
        webhook_event: dict[str, Any],
    ) -> bool: ...


class PayPalSandboxClient:
    """Official PayPal REST API v2 Sandbox client (never uses live endpoints by default)."""

    def __init__(
        self,
        settings: NexusSettings | None = None,
        *,
        http_client: httpx.AsyncClient | None = None,
        timeout_seconds: float = 15.0,
    ) -> None:
        self.settings = settings or get_settings()
        self._external_client = http_client
        self._timeout_seconds = timeout_seconds
        self._cached_token: str | None = None
        self._token_expires_at: datetime = datetime.min.replace(tzinfo=UTC)

        if self.settings.paypal_mode.lower() != "sandbox":
            raise PayPalConfigurationError(
                f"Refusing to initialize non-sandbox PayPal mode: {self.settings.paypal_mode}"
            )

    def _require_credentials(self) -> None:
        if not self.settings.paypal_client_id or not self.settings.paypal_client_secret:
            raise PayPalConfigurationError(
                "PAYPAL_CLIENT_ID and PAYPAL_CLIENT_SECRET must be configured for PayPal sandbox calls."
            )

    def _client(self) -> httpx.AsyncClient:
        if self._external_client is not None:
            return self._external_client
        return httpx.AsyncClient(base_url=self.settings.paypal_base_url, timeout=self._timeout_seconds)

    async def get_access_token(self) -> str:
        self._require_credentials()
        now = datetime.now(UTC)
        if self._cached_token and now < self._token_expires_at:
            return self._cached_token

        close_after = self._external_client is None
        client = self._client()
        try:
            resp = await client.post(
                "/v1/oauth2/token",
                auth=(self.settings.paypal_client_id, self.settings.paypal_client_secret),
                data={"grant_type": "client_credentials"},
                headers={"Accept": "application/json"},
            )
        except httpx.TimeoutException as exc:
            raise PayPalTimeoutError("Timed out obtaining PayPal OAuth token") from exc
        finally:
            if close_after:
                await client.aclose()

        if resp.status_code >= 400:
            raise PayPalAPIError(
                f"PayPal OAuth failed ({resp.status_code}): {resp.text}",
                status_code=resp.status_code,
            )
        data = resp.json()
        token = data["access_token"]
        expires_in = int(data.get("expires_in", 300))
        self._cached_token = token
        self._token_expires_at = now + timedelta(seconds=max(30, expires_in - 60))
        return token

    async def create_order(
        self,
        *,
        amount_minor: int,
        currency: str,
        reference_id: str,
        description: str,
        request_id: str,
        return_url: str | None = None,
        cancel_url: str | None = None,
    ) -> PayPalOrderCreationResult:
        token = await self.get_access_token()
        payload: dict[str, Any] = {
            "intent": "CAPTURE",
            "purchase_units": [
                {
                    "reference_id": reference_id,
                    "description": description[:127],
                    "amount": {
                        "currency_code": currency.upper(),
                        "value": minor_to_paypal_value(amount_minor, currency),
                    },
                }
            ],
        }
        if return_url and cancel_url:
            payload["payment_source"] = {
                "paypal": {
                    "experience_context": {
                        "return_url": return_url,
                        "cancel_url": cancel_url,
                        "user_action": "PAY_NOW",
                    }
                }
            }

        close_after = self._external_client is None
        client = self._client()
        try:
            resp = await client.post(
                "/v2/checkout/orders",
                json=payload,
                headers={
                    "Authorization": f"Bearer {token}",
                    "Content-Type": "application/json",
                    "PayPal-Request-Id": request_id,
                },
            )
        except httpx.TimeoutException as exc:
            raise PayPalTimeoutError("Timed out creating PayPal sandbox order") from exc
        finally:
            if close_after:
                await client.aclose()

        if resp.status_code >= 400:
            raise PayPalAPIError(
                f"PayPal create order failed ({resp.status_code}): {resp.text}",
                status_code=resp.status_code,
                debug_id=resp.headers.get("PayPal-Debug-Id"),
            )
        data = resp.json()
        approval_url = next(
            (link["href"] for link in data.get("links", []) if link.get("rel") in ("approve", "payer-action")),
            None,
        )
        return PayPalOrderCreationResult(
            paypal_order_id=data["id"],
            status=data["status"],
            approval_url=approval_url,
            raw_response=data,
        )

    async def get_order(self, *, paypal_order_id: str) -> dict[str, Any]:
        token = await self.get_access_token()
        close_after = self._external_client is None
        client = self._client()
        try:
            resp = await client.get(
                f"/v2/checkout/orders/{paypal_order_id}",
                headers={"Authorization": f"Bearer {token}"},
            )
        except httpx.TimeoutException as exc:
            raise PayPalTimeoutError(f"Timed out fetching PayPal order {paypal_order_id}") from exc
        finally:
            if close_after:
                await client.aclose()

        if resp.status_code >= 400:
            raise PayPalAPIError(
                f"PayPal get order failed ({resp.status_code}): {resp.text}",
                status_code=resp.status_code,
                debug_id=resp.headers.get("PayPal-Debug-Id"),
            )
        return resp.json()

    async def capture_order(
        self,
        *,
        paypal_order_id: str,
        expected_amount_minor: int,
        expected_currency: str,
        request_id: str,
    ) -> PayPalCaptureResult:
        """Capture an approved PayPal order and verify status + amount against PayPal."""
        order_data = await self.get_order(paypal_order_id=paypal_order_id)
        order_status = order_data.get("status")
        if order_status not in ("APPROVED", "COMPLETED"):
            raise PayPalAPIError(
                f"Order {paypal_order_id} is not buyer-approved (status={order_status})",
                status_code=409,
            )

        if order_status == "COMPLETED":
            verified = self._extract_verified_capture(
                order_data,
                paypal_order_id=paypal_order_id,
                expected_amount_minor=expected_amount_minor,
                expected_currency=expected_currency,
            )
            return PayPalCaptureResult(verified_capture=verified, raw_response=order_data)

        token = await self.get_access_token()
        close_after = self._external_client is None
        client = self._client()
        try:
            resp = await client.post(
                f"/v2/checkout/orders/{paypal_order_id}/capture",
                json={},
                headers={
                    "Authorization": f"Bearer {token}",
                    "Content-Type": "application/json",
                    "PayPal-Request-Id": request_id,
                },
            )
        except httpx.TimeoutException as exc:
            raise PayPalTimeoutError(
                f"PayPal capture timed out for order {paypal_order_id}; status unresolved"
            ) from exc
        finally:
            if close_after:
                await client.aclose()

        if resp.status_code >= 400:
            raise PayPalAPIError(
                f"PayPal capture failed ({resp.status_code}): {resp.text}",
                status_code=resp.status_code,
                debug_id=resp.headers.get("PayPal-Debug-Id"),
            )

        cap_data = resp.json()
        # Verify against PayPal GET order before final settlement
        verified_order = await self.get_order(paypal_order_id=paypal_order_id)
        verified = self._extract_verified_capture(
            verified_order,
            paypal_order_id=paypal_order_id,
            expected_amount_minor=expected_amount_minor,
            expected_currency=expected_currency,
        )
        return PayPalCaptureResult(verified_capture=verified, raw_response=cap_data)

    async def reconcile_order(
        self,
        *,
        paypal_order_id: str,
        expected_amount_minor: int,
        expected_currency: str,
    ) -> PayPalReconciliationResult:
        order_data = await self.get_order(paypal_order_id=paypal_order_id)
        status = order_data.get("status", "UNKNOWN")
        verified: VerifiedPayPalCapture | None = None
        if status == "COMPLETED":
            verified = self._extract_verified_capture(
                order_data,
                paypal_order_id=paypal_order_id,
                expected_amount_minor=expected_amount_minor,
                expected_currency=expected_currency,
            )
        return PayPalReconciliationResult(
            paypal_order_id=paypal_order_id,
            order_status=status,
            verified_capture=verified,
            raw_response=order_data,
        )

    async def verify_webhook_signature(
        self,
        *,
        headers: dict[str, str],
        webhook_event: dict[str, Any],
    ) -> bool:
        if not self.settings.paypal_webhook_id:
            raise PayPalConfigurationError("PAYPAL_WEBHOOK_ID is not configured")
        normalized = {k.lower(): v for k, v in headers.items()}
        required_keys = [
            "paypal-auth-algo",
            "paypal-cert-url",
            "paypal-transmission-id",
            "paypal-transmission-sig",
            "paypal-transmission-time",
        ]
        if any(not normalized.get(k) for k in required_keys):
            return False

        token = await self.get_access_token()
        body = {
            "auth_algo": normalized["paypal-auth-algo"],
            "cert_url": normalized["paypal-cert-url"],
            "transmission_id": normalized["paypal-transmission-id"],
            "transmission_sig": normalized["paypal-transmission-sig"],
            "transmission_time": normalized["paypal-transmission-time"],
            "webhook_id": self.settings.paypal_webhook_id,
            "webhook_event": webhook_event,
        }
        close_after = self._external_client is None
        client = self._client()
        try:
            resp = await client.post(
                "/v1/notifications/verify-webhook-signature",
                json=body,
                headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
            )
        except httpx.TimeoutException as exc:
            raise PayPalTimeoutError("Timed out verifying PayPal webhook signature") from exc
        finally:
            if close_after:
                await client.aclose()

        if resp.status_code >= 400:
            return False
        return resp.json().get("verification_status") == "SUCCESS"

    async def list_disputes(
        self,
        *,
        page_size: int = 10,
        next_page_token: str | None = None,
        dispute_state: str | None = None,
    ) -> dict[str, Any]:
        """Feature-flagged PayPal Customer Disputes API v1 read-only listing with pagination."""
        if not self.settings.paypal_disputes_api_enabled:
            raise PayPalDisputesDisabledError(
                "PAYPAL_DISPUTES_API_ENABLED is false; confirm sandbox Disputes permissions before enabling."
            )
        token = await self.get_access_token()
        close_after = self._external_client is None
        client = self._client()
        params: dict[str, Any] = {"page_size": min(max(1, page_size), 50)}
        if next_page_token:
            params["next_page_token"] = next_page_token
        if dispute_state:
            params["dispute_state"] = dispute_state
        try:
            resp = await client.get(
                "/v1/customer/disputes",
                params=params,
                headers={"Authorization": f"Bearer {token}"},
            )
        except httpx.TimeoutException as exc:
            raise PayPalTimeoutError("Timed out querying PayPal Customer Disputes API") from exc
        finally:
            if close_after:
                await client.aclose()
        if resp.status_code >= 400:
            raise PayPalAPIError(
                f"PayPal list disputes failed ({resp.status_code}): {resp.text}",
                status_code=resp.status_code,
            )
        return resp.json()

    async def provide_evidence(
        self,
        *,
        dispute_id: str,
        evidence_type: str = "PROOF_OF_FULFILLMENT",
        evidence_info: dict[str, Any] | None = None,
        notes: str | None = None,
        files: list[Any] | None = None,
    ) -> dict[str, Any]:
        """Submit evidence to PayPal for an open customer dispute (GAP-009)."""
        if not self.settings.paypal_disputes_api_enabled:
            raise PayPalDisputesDisabledError(
                "PAYPAL_DISPUTES_API_ENABLED is false; confirm sandbox Disputes permissions before enabling."
            )
        token = await self.get_access_token()
        close_after = self._external_client is None
        client = self._client()

        payload: dict[str, Any] = {
            "evidence_type": evidence_type,
            "evidence_info": evidence_info or {},
            "notes": notes or "Evidence submitted via AgentPay Nexus DisputeOS",
        }

        try:
            resp = await client.post(
                f"/v1/customer/disputes/{dispute_id}/provide-evidence",
                json=payload,
                headers={
                    "Authorization": f"Bearer {token}",
                    "Content-Type": "application/json",
                },
            )
        except httpx.TimeoutException as exc:
            raise PayPalTimeoutError(f"Timed out providing evidence for dispute {dispute_id}") from exc
        finally:
            if close_after:
                await client.aclose()

        if resp.status_code >= 400:
            raise PayPalAPIError(
                f"PayPal provide evidence failed ({resp.status_code}): {resp.text}",
                status_code=resp.status_code,
            )
        return resp.json() if resp.text else {"status": "SUCCESS", "dispute_id": dispute_id}

    async def accept_claim(
        self,
        *,
        dispute_id: str,
        note: str | None = None,
        accept_claim_type: str = "REFUND",
    ) -> dict[str, Any]:
        """Accept dispute claim and issue refund via PayPal Disputes API (GAP-009)."""
        if not self.settings.paypal_disputes_api_enabled:
            raise PayPalDisputesDisabledError(
                "PAYPAL_DISPUTES_API_ENABLED is false; confirm sandbox Disputes permissions before enabling."
            )
        token = await self.get_access_token()
        close_after = self._external_client is None
        client = self._client()
        payload = {"accept_claim_type": accept_claim_type, "note_to_dispute": note or "Accepted claim"}
        try:
            resp = await client.post(
                f"/v1/customer/disputes/{dispute_id}/accept-claim",
                json=payload,
                headers={
                    "Authorization": f"Bearer {token}",
                    "Content-Type": "application/json",
                },
            )
        except httpx.TimeoutException as exc:
            raise PayPalTimeoutError(f"Timed out accepting claim for dispute {dispute_id}") from exc
        finally:
            if close_after:
                await client.aclose()

        if resp.status_code >= 400:
            raise PayPalAPIError(
                f"PayPal accept claim failed ({resp.status_code}): {resp.text}",
                status_code=resp.status_code,
            )
        return resp.json() if resp.text else {"status": "ACCEPTED", "dispute_id": dispute_id}

    async def refund_capture(
        self,
        *,
        capture_id: str,
        amount_minor: int | None = None,
        currency: str = "USD",
        note: str | None = None,
    ) -> PayPalRefundResult:
        """Issue full or partial refund for a captured payment (GAP-012)."""
        token = await self.get_access_token()
        payload: dict[str, Any] = {}
        if amount_minor is not None:
            payload["amount"] = {
                "value": minor_to_paypal_value(amount_minor, currency),
                "currency_code": currency.upper(),
            }
        if note:
            payload["note_to_payer"] = note[:255]

        close_after = self._external_client is None
        client = self._client()
        try:
            resp = await client.post(
                f"/v2/payments/captures/{capture_id}/refund",
                json=payload,
                headers={
                    "Authorization": f"Bearer {token}",
                    "Content-Type": "application/json",
                },
            )
        except httpx.TimeoutException as exc:
            raise PayPalTimeoutError(f"Timed out refunding capture {capture_id}") from exc
        finally:
            if close_after:
                await client.aclose()

        if resp.status_code >= 400:
            raise PayPalAPIError(
                f"PayPal refund failed ({resp.status_code}): {resp.text}",
                status_code=resp.status_code,
            )
        data = resp.json()
        refund_amt_minor = (
            paypal_value_to_minor(data["amount"]["value"], data["amount"].get("currency_code", currency))
            if "amount" in data
            else (amount_minor or 0)
        )
        return PayPalRefundResult(
            refund_id=data["id"],
            status=data.get("status", "COMPLETED"),
            amount_minor=refund_amt_minor,
            currency=currency.upper(),
            raw_response=data,
        )

    async def void_authorization(
        self,
        *,
        authorization_id: str,
        note: str | None = None,
    ) -> dict[str, Any]:
        """Void an uncaptured PayPal authorization hold (GAP-012)."""
        token = await self.get_access_token()
        close_after = self._external_client is None
        client = self._client()
        try:
            resp = await client.post(
                f"/v2/payments/authorizations/{authorization_id}/void",
                headers={
                    "Authorization": f"Bearer {token}",
                    "Content-Type": "application/json",
                },
            )
        except httpx.TimeoutException as exc:
            raise PayPalTimeoutError(f"Timed out voiding authorization {authorization_id}") from exc
        finally:
            if close_after:
                await client.aclose()

        if resp.status_code not in (200, 204):
            raise PayPalAPIError(
                f"PayPal void authorization failed ({resp.status_code}): {resp.text}",
                status_code=resp.status_code,
            )
        return resp.json() if resp.text else {"status": "VOIDED", "authorization_id": authorization_id}

    @staticmethod
    def _extract_verified_capture(
        order_data: dict[str, Any],
        *,
        paypal_order_id: str,
        expected_amount_minor: int,
        expected_currency: str,
    ) -> VerifiedPayPalCapture:
        if order_data.get("status") != "COMPLETED":
            raise PayPalAPIError(
                f"PayPal verification failed: order status is {order_data.get('status')}",
                status_code=409,
            )
        purchase_units = order_data.get("purchase_units") or []
        captures = []
        for pu in purchase_units:
            captures.extend((pu.get("payments") or {}).get("captures") or [])
        completed_capture = next((c for c in captures if c.get("status") == "COMPLETED"), None)
        if completed_capture is None:
            raise PayPalAPIError("No COMPLETED capture found on verified PayPal order", status_code=409)

        amt = completed_capture.get("amount") or {}
        actual_currency = str(amt.get("currency_code", "")).upper()
        actual_minor = paypal_value_to_minor(str(amt.get("value", "0.00")), actual_currency)
        if actual_currency != expected_currency.upper() or actual_minor != expected_amount_minor:
            raise PayPalAPIError(
                f"Captured amount mismatch: expected {expected_amount_minor} {expected_currency}, "
                f"got {actual_minor} {actual_currency}",
                status_code=409,
            )

        return VerifiedPayPalCapture(
            paypal_order_id=paypal_order_id,
            paypal_capture_id=completed_capture["id"],
            paypal_status=completed_capture["status"],
            verified_amount_minor=actual_minor,
            verified_currency=actual_currency,
            verification_hash=compute_payload_hash({
                "paypal_order_id": paypal_order_id,
                "capture_id": completed_capture["id"],
                "status": completed_capture["status"],
                "amount_minor": actual_minor,
                "currency": actual_currency,
            }),
        )

