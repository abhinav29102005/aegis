"""HTTP client, webhook verifier, and non-privileged AI agent middleware for AEGIS."""

from __future__ import annotations

import hashlib
import hmac
import json
from typing import Any
from uuid import UUID, uuid4

import httpx


class AegisAPIError(RuntimeError):
    """Raised when the AEGIS API returns a structured error response."""

    def __init__(self, status_code: int, message: str, payload: Any = None) -> None:
        super().__init__(f"AEGIS API HTTP {status_code}: {message}")
        self.status_code = status_code
        self.payload = payload


def verify_webhook_signature(*, payload_body: dict[str, Any], signature_header: str, signing_secret: str) -> bool:
    """Verify an outbound AEGIS webhook ``X-AEGIS-Signature`` HMAC-SHA256 header."""
    canonical = json.dumps(payload_body, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    expected_hex = hmac.new(signing_secret.encode("utf-8"), canonical, hashlib.sha256).hexdigest()
    provided = signature_header.removeprefix("sha256=").strip()
    return hmac.compare_digest(expected_hex, provided)


class AegisClient:
    """Synchronous typed client for AEGIS REST APIs (`/v1/*`)."""

    def __init__(
        self,
        *,
        base_url: str = "http://localhost:8000",
        api_key: str | None = None,
        bearer_token: str | None = None,
        organization_id: str | UUID | None = None,
        timeout: float = 15.0,
        client: httpx.Client | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self._api_key = api_key
        self._bearer_token = bearer_token
        self._organization_id = str(organization_id) if organization_id else None
        self._client = client or httpx.Client(base_url=self.base_url, timeout=timeout)
        self._owns_client = client is None

    def close(self) -> None:
        if self._owns_client:
            self._client.close()

    def set_token(self, bearer_token: str | None) -> None:
        self._bearer_token = bearer_token

    def set_api_key(self, api_key: str | None) -> None:
        self._api_key = api_key

    def register(
        self,
        *,
        email: str,
        password: str,
        full_name: str,
        organization_name: str,
        organization_slug: str,
    ) -> dict[str, Any]:
        return self._request(
            "POST",
            "/v1/auth/register",
            json_body={
                "email": email,
                "password": password,
                "full_name": full_name,
                "organization_name": organization_name,
                "organization_slug": organization_slug,
            },
        )

    def login(self, *, email: str, password: str, organization_id: str | UUID | None = None) -> dict[str, Any]:
        body: dict[str, Any] = {"email": email, "password": password}
        if organization_id is not None:
            body["organization_id"] = str(organization_id)
        return self._request("POST", "/v1/auth/login", json_body=body)

    def _headers(self, extra: dict[str, str] | None = None) -> dict[str, str]:
        headers: dict[str, str] = {"X-Correlation-Id": str(uuid4())}
        if self._bearer_token:
            headers["Authorization"] = f"Bearer {self._bearer_token}"
        elif self._api_key:
            headers["X-API-Key"] = self._api_key
        if self._organization_id:
            headers["X-Org-Id"] = self._organization_id
        if extra:
            headers.update(extra)
        return headers

    def _request(
        self,
        method: str,
        path: str,
        *,
        json_body: dict[str, Any] | None = None,
        params: dict[str, Any] | None = None,
    ) -> Any:
        resp = self._client.request(
            method,
            path,
            json=json_body,
            params={k: v for k, v in (params or {}).items() if v is not None},
            headers=self._headers(),
        )
        if resp.status_code >= 400:
            try:
                err = resp.json()
            except ValueError:
                err = resp.text
            msg = err.get("message") if isinstance(err, dict) else str(err)
            if isinstance(err, dict) and isinstance(err.get("detail"), dict):
                msg = err["detail"].get("message", str(err["detail"]))
            raise AegisAPIError(resp.status_code, str(msg), payload=err)
        return resp.json()

    def submit_purchase_proposal(
        self,
        *,
        agent_id: str | UUID,
        passport_id: str | UUID,
        merchant_id: str | UUID,
        merchant_name: str,
        merchant_category: str,
        amount_minor: int,
        currency: str,
        item_summary: str,
        rationale: str,
        line_items: list[dict[str, Any]] | None = None,
        idempotency_key: str | None = None,
    ) -> dict[str, Any]:
        key = idempotency_key or f"sdk-{uuid4().hex[:16]}"
        return self._request(
            "POST",
            "/v1/guardian/proposals",
            json_body={
                "agent_id": str(agent_id),
                "passport_id": str(passport_id),
                "merchant_id": str(merchant_id),
                "merchant_name": merchant_name,
                "merchant_category": merchant_category,
                "amount_minor": amount_minor,
                "currency": currency.upper(),
                "item_summary": item_summary,
                "line_items": line_items or [],
                "rationale": rationale,
                "idempotency_key": key,
            },
        )

    def get_payment(self, intent_id: str | UUID) -> dict[str, Any]:
        return self._request("GET", f"/v1/guardian/payments/{intent_id}")

    def approve_proposal(
        self,
        intent_id: str | UUID,
        *,
        approver_id: str,
        comment: str | None = None,
    ) -> dict[str, Any]:
        return self._request(
            "POST",
            f"/v1/guardian/proposals/{intent_id}/approve",
            json_body={"approver_id": approver_id, "approved": True, "comment": comment},
        )

    def initiate_checkout(self, intent_id: str | UUID, *, idempotency_key: str | None = None) -> dict[str, Any]:
        return self._request(
            "POST",
            f"/v1/guardian/payments/{intent_id}/checkout",
            json_body={"attempt_number": 1, "idempotency_key": idempotency_key},
        )

    def replay_by_payment(self, intent_id: str | UUID) -> dict[str, Any]:
        return self._request("POST", f"/v1/ghostpay/replay/by-payment/{intent_id}", json_body={})

    def simulate_by_payment(self, intent_id: str | UUID, *, overrides: dict[str, Any]) -> dict[str, Any]:
        return self._request(
            "POST",
            f"/v1/ghostpay/simulate/by-payment/{intent_id}",
            json_body={"overrides": overrides, "persist_investigation": True},
        )

    def list_investigations(self, *, payment_intent_id: str | UUID | None = None, limit: int = 50) -> dict[str, Any]:
        return self._request(
            "GET",
            "/v1/ghostpay/investigations",
            params={"payment_intent_id": str(payment_intent_id) if payment_intent_id else None, "limit": limit},
        )

    def list_disputes(self) -> list[dict[str, Any]]:
        return self._request("GET", "/v1/disputeos/cases")


class AgentAuthorizationTool:
    """Middleware helper for external LLM/LangGraph purchasing agents.

    This tool submits deterministic authorization requests to AEGIS Guardian using
    an ``AGENT_SERVICE`` API key and returns whether the spend is ``CHECKOUT_READY``,
    ``AWAITING_APPROVAL``, or ``DENIED`` — without ever granting the agent direct
    PayPal credentials or approval authority.
    """

    def __init__(self, client: AegisClient, *, agent_id: str | UUID, passport_id: str | UUID) -> None:
        self.client = client
        self.agent_id = str(agent_id)
        self.passport_id = str(passport_id)

    def request_purchase_authorization(
        self,
        *,
        merchant_id: str | UUID,
        merchant_name: str,
        merchant_category: str,
        amount_minor: int,
        item_summary: str,
        rationale: str,
        currency: str = "USD",
        idempotency_key: str | None = None,
    ) -> dict[str, Any]:
        return self.client.submit_purchase_proposal(
            agent_id=self.agent_id,
            passport_id=self.passport_id,
            merchant_id=merchant_id,
            merchant_name=merchant_name,
            merchant_category=merchant_category,
            amount_minor=amount_minor,
            currency=currency,
            item_summary=item_summary,
            rationale=rationale,
            idempotency_key=idempotency_key,
        )
