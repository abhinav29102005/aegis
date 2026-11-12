"""PayPal Sandbox Orders API v2 client, webhook verifier, and reconciliation adapter.

This module is strictly isolated from LangGraph and AI reasoning modules.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Protocol
from uuid import uuid4

import httpx
from contracts import (
    VerifiedPayPalCapture,
    compute_payload_hash,
    decimal_str_to_minor,
    minor_to_decimal_str,
)
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
    """Format integer minor units as an ISO-4217 decimal string for PayPal."""
    return minor_to_decimal_str(amount_minor, currency)


def paypal_value_to_minor(value_str: str, currency: str = "USD") -> int:
    """Parse a PayPal decimal amount string into integer minor units for currency."""
    return decimal_str_to_minor(value_str, currency)


@dataclass(frozen=True)
class PayPalOrderCreationResult:
    paypal_order_id: str
    status: str
    approval_url: str | None
    raw_response: dict[str, Any]


class PayPalRefundResult(dict):
    """Refund result supporting both dictionary and attribute access."""

    def __init__(
        self,
        refund_id: str,
        status: str,
        amount_minor: int,
        currency: str,
        raw_response: dict[str, Any] | None = None,
    ) -> None:
        raw = raw_response or {}
        super().__init__(raw)
        self.refund_id = refund_id
        self.status = status
        self.amount_minor = amount_minor
        self.currency = currency
        self.raw_response = raw
        self["id"] = refund_id
        self["status"] = status
        self["amount"] = {
            "value": minor_to_paypal_value(amount_minor, currency),
            "currency_code": currency,
        }


@dataclass(frozen=True)
class PayPalCaptureResult:
    verified_capture: VerifiedPayPalCapture
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

    async def refund_capture(
        self,
        capture_id: str,
        amount_minor: int,
        currency: str,
        idempotency_key: str | None = None,
        note: str | None = None,
    ) -> dict[str, Any]: ...

    async def void_authorization(
        self,
        authorization_id: str,
        idempotency_key: str | None = None,
    ) -> dict[str, Any]: ...

    async def verify_webhook_signature(
        self,
        *,
        headers: dict[str, str],
        webhook_event: dict[str, Any],
    ) -> bool: ...

    async def list_disputes(
        self,
        *,
        page_size: int = 20,
        next_page_token: str | None = None,
        start_time: str | None = None,
        dispute_state: str | None = None,
        timeout_seconds: float | None = None,
    ) -> dict[str, Any]: ...

    async def provide_evidence(
        self,
        dispute_id: str,
        evidence_payload: dict[str, Any],
        files: Sequence[tuple[str, bytes] | tuple[str, bytes, str]]
        | dict[str, tuple[str, bytes, str] | tuple[str, bytes] | bytes]
        | None = None,
    ) -> dict[str, Any]: ...

    async def accept_claim(
        self,
        dispute_id: str,
        note: str | None = None,
    ) -> dict[str, Any]: ...


class PayPalSandboxClient:
    """Official PayPal REST API v2 Sandbox client (never uses live endpoints by default)."""

    def __init__(
        self,
        settings: NexusSettings | None = None,
        *,
        http_client: httpx.AsyncClient | None = None,
        timeout_seconds: float = 15.0,
        max_retries: int = 3,
        retry_base_delay: float = 0.1,
        retry_max_delay: float = 2.0,
    ) -> None:
        self.settings = settings or get_settings()
        self._external_client = http_client
        self._timeout_seconds = timeout_seconds
        self._max_retries = max(0, max_retries)
        self._retry_base_delay = max(0.0, retry_base_delay)
        self._retry_max_delay = max(0.0, retry_max_delay)
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

    def _require_disputes_enabled(self) -> None:
        if not self.settings.paypal_disputes_api_enabled:
            raise PayPalDisputesDisabledError(
                "PAYPAL_DISPUTES_API_ENABLED is false; confirm sandbox Disputes permissions before enabling."
            )

    def _client(self) -> httpx.AsyncClient:
        if self._external_client is not None:
            return self._external_client
        return httpx.AsyncClient(base_url=self.settings.paypal_base_url, timeout=self._timeout_seconds)

    def _compute_retry_delay(self, attempt: int, response: httpx.Response | None = None) -> float:
        if response is not None:
            retry_after = response.headers.get("Retry-After")
            if retry_after:
                try:
                    parsed = float(retry_after.strip())
                    if parsed >= 0:
                        return min(self._retry_max_delay, parsed)
                except ValueError:
                    pass
        return min(self._retry_max_delay, self._retry_base_delay * (2**attempt))

    @staticmethod
    def _is_transient_status(status_code: int) -> bool:
        return status_code == 429 or 500 <= status_code < 600

    async def _request(
        self,
        method: str,
        path: str,
        *,
        timeout_seconds: float | None = None,
        timeout_message: str = "PayPal request timed out",
        **kwargs: Any,
    ) -> httpx.Response:
        """Execute an HTTP request with exponential-backoff retries on transient failures."""
        close_after = self._external_client is None
        client = self._client()
        if timeout_seconds is not None:
            kwargs["timeout"] = timeout_seconds

        try:
            for attempt in range(self._max_retries + 1):
                try:
                    resp = await client.request(method, path, **kwargs)
                except httpx.TimeoutException as exc:
                    if attempt < self._max_retries:
                        await asyncio.sleep(self._compute_retry_delay(attempt))
                        continue
                    raise PayPalTimeoutError(timeout_message) from exc
                except httpx.TransportError as exc:
                    if attempt < self._max_retries:
                        await asyncio.sleep(self._compute_retry_delay(attempt))
                        continue
                    raise PayPalAPIError(
                        f"PayPal transport error: {exc}",
                        status_code=502,
                    ) from exc

                if self._is_transient_status(resp.status_code) and attempt < self._max_retries:
                    await asyncio.sleep(self._compute_retry_delay(attempt, resp))
                    continue
                return resp
        finally:
            if close_after:
                await client.aclose()

        raise PayPalAPIError("PayPal request failed after retries", status_code=502)

    async def get_access_token(self) -> str:
        self._require_credentials()
        now = datetime.now(UTC)
        if self._cached_token and now < self._token_expires_at:
            return self._cached_token

        resp = await self._request(
            "POST",
            "/v1/oauth2/token",
            timeout_message="Timed out obtaining PayPal OAuth token",
            auth=(self.settings.paypal_client_id, self.settings.paypal_client_secret),
            data={"grant_type": "client_credentials"},
            headers={"Accept": "application/json"},
        )

        if resp.status_code >= 400:
            raise PayPalAPIError(
                f"PayPal OAuth failed ({resp.status_code}): {resp.text}",
                status_code=resp.status_code,
                debug_id=resp.headers.get("PayPal-Debug-Id"),
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
        upper_currency = currency.upper()
        payload: dict[str, Any] = {
            "intent": "CAPTURE",
            "purchase_units": [
                {
                    "reference_id": reference_id,
                    "description": description[:127],
                    "amount": {
                        "currency_code": upper_currency,
                        "value": minor_to_paypal_value(amount_minor, upper_currency),
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

        resp = await self._request(
            "POST",
            "/v2/checkout/orders",
            timeout_message="Timed out creating PayPal sandbox order",
            json=payload,
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
                "PayPal-Request-Id": request_id,
            },
        )

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
        resp = await self._request(
            "GET",
            f"/v2/checkout/orders/{paypal_order_id}",
            timeout_message=f"Timed out fetching PayPal order {paypal_order_id}",
            headers={"Authorization": f"Bearer {token}"},
        )

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
        resp = await self._request(
            "POST",
            f"/v2/checkout/orders/{paypal_order_id}/capture",
            timeout_message=f"PayPal capture timed out for order {paypal_order_id}; status unresolved",
            json={},
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
                "PayPal-Request-Id": request_id,
            },
        )

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

    async def refund_capture(
        self,
        capture_id: str,
        amount_minor: int,
        currency: str,
        idempotency_key: str | None = None,
        note: str | None = None,
    ) -> dict[str, Any]:
        """Refund a captured PayPal payment in exact ISO-4217 minor units."""
        if not capture_id.strip():
            raise ValueError("capture_id must not be empty")
        if amount_minor <= 0:
            raise ValueError("amount_minor must be positive")

        token = await self.get_access_token()
        upper_currency = currency.upper()
        request_id = idempotency_key or str(uuid4())
        payload: dict[str, Any] = {
            "amount": {
                "currency_code": upper_currency,
                "value": minor_to_paypal_value(amount_minor, upper_currency),
            }
        }
        if note:
            payload["note_to_payer"] = note[:255]

        resp = await self._request(
            "POST",
            f"/v2/payments/captures/{capture_id}/refund",
            timeout_message=f"Timed out refunding PayPal capture {capture_id}",
            json=payload,
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
                "PayPal-Request-Id": request_id,
            },
        )
        if resp.status_code >= 400:
            raise PayPalAPIError(
                f"PayPal refund capture failed ({resp.status_code}): {resp.text}",
                status_code=resp.status_code,
                debug_id=resp.headers.get("PayPal-Debug-Id"),
            )
        data = resp.json() if resp.text else {}
        refund_id = data.get("id", f"REF-{uuid4().hex[:8]}")
        status = data.get("status", "COMPLETED")
        return PayPalRefundResult(
            refund_id=refund_id,
            status=status,
            amount_minor=amount_minor,
            currency=upper_currency,
            raw_response=data,
        )

    async def void_authorization(
        self,
        authorization_id: str,
        idempotency_key: str | None = None,
    ) -> dict[str, Any]:
        """Void an open PayPal payment authorization."""
        if not authorization_id.strip():
            raise ValueError("authorization_id must not be empty")

        token = await self.get_access_token()
        request_id = idempotency_key or str(uuid4())
        resp = await self._request(
            "POST",
            f"/v2/payments/authorizations/{authorization_id}/void",
            timeout_message=f"Timed out voiding PayPal authorization {authorization_id}",
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
                "PayPal-Request-Id": request_id,
            },
        )
        if resp.status_code >= 400:
            raise PayPalAPIError(
                f"PayPal void authorization failed ({resp.status_code}): {resp.text}",
                status_code=resp.status_code,
                debug_id=resp.headers.get("PayPal-Debug-Id"),
            )
        if resp.status_code == 204 or not resp.content:
            return {"id": authorization_id, "status": "VOIDED"}
        data = resp.json()
        if "status" not in data:
            data["status"] = "VOIDED"
        return data

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
        resp = await self._request(
            "POST",
            "/v1/notifications/verify-webhook-signature",
            timeout_message="Timed out verifying PayPal webhook signature",
            json=body,
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        )

        if resp.status_code >= 400:
            return False
        return resp.json().get("verification_status") == "SUCCESS"

    async def list_disputes(
        self,
        *,
        page_size: int = 20,
        next_page_token: str | None = None,
        start_time: str | None = None,
        dispute_state: str | None = None,
        timeout_seconds: float | None = None,
    ) -> dict[str, Any]:
        """Feature-flagged PayPal Customer Disputes API v1 listing with pagination and strict timeouts."""
        self._require_disputes_enabled()
        if page_size < 1 or page_size > 50:
            raise ValueError("page_size must be between 1 and 50")

        token = await self.get_access_token()
        params: dict[str, Any] = {"page_size": page_size}
        if next_page_token:
            params["next_page_token"] = next_page_token
        if start_time:
            params["start_time"] = start_time
        if dispute_state:
            params["dispute_state"] = dispute_state

        effective_timeout = timeout_seconds if timeout_seconds is not None else min(self._timeout_seconds, 10.0)
        resp = await self._request(
            "GET",
            "/v1/customer/disputes",
            timeout_seconds=effective_timeout,
            timeout_message="Timed out listing PayPal disputes",
            params=params,
            headers={"Authorization": f"Bearer {token}"},
        )
        if resp.status_code >= 400:
            raise PayPalAPIError(
                f"PayPal list disputes failed ({resp.status_code}): {resp.text}",
                status_code=resp.status_code,
                debug_id=resp.headers.get("PayPal-Debug-Id"),
            )
        return resp.json()

    async def provide_evidence(
        self,
        dispute_id: str,
        evidence_payload: dict[str, Any] | None = None,
        files: Sequence[tuple[str, bytes] | tuple[str, bytes, str]]
        | dict[str, tuple[str, bytes, str] | tuple[str, bytes] | bytes]
        | None = None,
        *,
        evidence_type: str = "PROOF_OF_FULFILLMENT",
        evidence_info: dict[str, Any] | None = None,
        notes: str | None = None,
    ) -> dict[str, Any]:
        """Feature-flagged PayPal Disputes API v1 evidence submission."""
        self._require_disputes_enabled()
        if not dispute_id.strip():
            raise ValueError("dispute_id must not be empty")

        if evidence_payload is None:
            evidence_payload = {"evidence_type": evidence_type}
            if notes:
                evidence_payload["notes"] = notes
            if evidence_info:
                evidence_payload["evidence_info"] = evidence_info

        token = await self.get_access_token()
        path = f"/v1/customer/disputes/{dispute_id}/provide-evidence"

        if files:
            multipart_files: list[tuple[str, tuple[str | None, bytes, str]]] = [
                (
                    "input",
                    ("input.json", json.dumps(evidence_payload).encode("utf-8"), "application/json"),
                )
            ]
            if isinstance(files, dict):
                for idx, (field_name, spec) in enumerate(files.items(), start=1):
                    if isinstance(spec, bytes):
                        multipart_files.append((field_name, (f"document-{idx}.bin", spec, "application/octet-stream")))
                    elif len(spec) == 2:
                        fname, data = spec
                        multipart_files.append((field_name, (fname, data, "application/octet-stream")))
                    else:
                        fname, data, mime = spec
                        multipart_files.append((field_name, (fname, data, mime)))
            else:
                for idx, item in enumerate(files, start=1):
                    if len(item) == 2:
                        fname, data = item
                        mime = "application/octet-stream"
                    else:
                        fname, data, mime = item
                    multipart_files.append((f"file{idx}", (fname, data, mime)))

            resp = await self._request(
                "POST",
                path,
                timeout_message=f"Timed out submitting evidence for PayPal dispute {dispute_id}",
                files=multipart_files,
                headers={"Authorization": f"Bearer {token}"},
            )
        else:
            resp = await self._request(
                "POST",
                path,
                timeout_message=f"Timed out submitting evidence for PayPal dispute {dispute_id}",
                json=evidence_payload,
                headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
            )

        if resp.status_code >= 400:
            raise PayPalAPIError(
                f"PayPal provide evidence failed ({resp.status_code}): {resp.text}",
                status_code=resp.status_code,
                debug_id=resp.headers.get("PayPal-Debug-Id"),
            )
        if resp.status_code == 204 or not resp.content:
            return {"dispute_id": dispute_id, "status": "EVIDENCE_PROVIDED"}
        return resp.json()

    async def accept_claim(
        self,
        dispute_id: str,
        note: str | None = None,
    ) -> dict[str, Any]:
        """Feature-flagged PayPal Disputes API v1 claim acceptance."""
        self._require_disputes_enabled()
        if not dispute_id.strip():
            raise ValueError("dispute_id must not be empty")

        token = await self.get_access_token()
        payload: dict[str, Any] = {"note": note} if note else {}
        resp = await self._request(
            "POST",
            f"/v1/customer/disputes/{dispute_id}/accept-claim",
            timeout_message=f"Timed out accepting PayPal dispute claim {dispute_id}",
            json=payload,
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        )
        if resp.status_code >= 400:
            raise PayPalAPIError(
                f"PayPal accept claim failed ({resp.status_code}): {resp.text}",
                status_code=resp.status_code,
                debug_id=resp.headers.get("PayPal-Debug-Id"),
            )
        if resp.status_code == 204 or not resp.content:
            return {"dispute_id": dispute_id, "status": "ACCEPTED"}
        return resp.json()

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
        expected_upper = expected_currency.upper()
        if actual_currency != expected_upper:
            raise PayPalAPIError(
                f"Captured currency mismatch: expected {expected_upper}, got {actual_currency}",
                status_code=409,
            )

        try:
            actual_minor = paypal_value_to_minor(str(amt.get("value", "0")), actual_currency)
        except ValueError as exc:
            raise PayPalAPIError(
                f"Invalid captured amount value {amt.get('value')!r} for {actual_currency}: {exc}",
                status_code=409,
            ) from exc

        if actual_minor != expected_amount_minor:
            raise PayPalAPIError(
                f"Captured amount mismatch: expected {expected_amount_minor} {expected_upper}, "
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
