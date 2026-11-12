"""Verifi (CDRN/RDR) & Ethoca pre-dispute chargeback deflection alert handler for AgentPay Guardian."""

from __future__ import annotations

import hashlib
import hmac
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, Literal
from uuid import UUID, uuid4

import httpx
from contracts import DeflectionAlert, compute_payload_hash, decimal_str_to_minor
from contracts.models import NexusBaseModel
from pydantic import Field
from security import DEFAULT_TENANT_UUID

from guardian.providers.base import (
    ProviderAPIError,
    ProviderConfigurationError,
    ProviderSignatureError,
    ProviderValidationError,
    RetryingHTTPClient,
)


class DeflectionNetwork(StrEnum):
    VISA_VERIFI = "VISA_VERIFI"
    MASTERCARD_ETHOCA = "MASTERCARD_ETHOCA"
    AMEX = "AMEX"


class DeflectionStatus(StrEnum):
    RECEIVED = "RECEIVED"
    RESOLVED_REFUNDED = "RESOLVED_REFUNDED"
    RESOLVED_INFO_PROVIDED = "RESOLVED_INFO_PROVIDED"
    EXPIRED = "EXPIRED"
    REJECTED = "REJECTED"


class DeflectionAction(StrEnum):
    AUTO_REFUND = "AUTO_REFUND"
    PROVIDE_INFO = "PROVIDE_INFO"
    REJECT = "REJECT"


class DeflectionInquiry(NexusBaseModel):
    """Pre-dispute deflection alert received from issuer networks (Verifi CDRN / Ethoca)."""

    inquiry_id: str = Field(min_length=4, max_length=128)
    tenant_id: UUID
    network: DeflectionNetwork
    transaction_reference: str = Field(min_length=4, max_length=128)
    amount_minor: int = Field(gt=0)
    currency: str = Field(default="USD", min_length=3, max_length=3)
    reason_code: str = Field(min_length=2, max_length=64)
    alert_timestamp: datetime = Field(default_factory=lambda: datetime.now(UTC))
    sla_expires_at: datetime
    status: DeflectionStatus = DeflectionStatus.RECEIVED
    metadata: dict[str, Any] = Field(default_factory=dict)


class DeflectionResolution(NexusBaseModel):
    """Result of evaluating a deflection inquiry."""

    inquiry_id: str
    tenant_id: UUID
    action: DeflectionAction
    refund_reference: str | None = None
    notes: str
    resolved_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class DeflectionHandler:
    """Evaluates issuer pre-dispute alerts and determines whether to auto-refund or defend.

    Acts within the 24-72 hour issuer SLA window to prevent formal chargebacks and fees.
    """

    FRAUD_REASON_CODES = {
        "10.4",  # Visa: Other Fraud - Card-Absent
        "4837",  # Mastercard: No Cardholder Authorization
        "4863",  # Mastercard: Cardholder Does Not Recognize
        "10.1",  # Visa: EMV Liability Shift Counterfeit
        "FRAUD_UNRECOGNIZED",
        "UNAUTHORIZED",
    }

    @classmethod
    def evaluate_inquiry(
        cls,
        inquiry: DeflectionInquiry,
        *,
        auto_refund_limit_minor: int = 15000,  # $150.00
        now: datetime | None = None,
    ) -> DeflectionResolution:
        """Evaluate pre-dispute alert.

        If inquiry has exceeded its SLA window, return REJECT (expired).
        If inquiry reason is fraud/unrecognized and amount is below threshold, auto-refund.
        Otherwise recommend providing purchase/evidence info to issuer.
        """
        current_time = now or datetime.now(UTC)

        if current_time > inquiry.sla_expires_at:
            return DeflectionResolution(
                inquiry_id=inquiry.inquiry_id,
                tenant_id=inquiry.tenant_id,
                action=DeflectionAction.REJECT,
                notes=f"Inquiry SLA expired at {inquiry.sla_expires_at.isoformat()}",
                resolved_at=current_time,
            )

        is_fraud = (
            inquiry.reason_code.upper() in cls.FRAUD_REASON_CODES
            or "FRAUD" in inquiry.reason_code.upper()
            or "UNRECOGNIZED" in inquiry.reason_code.upper()
        )

        if is_fraud and inquiry.amount_minor <= auto_refund_limit_minor:
            refund_id = f"deflect-rf-{uuid4().hex[:12]}"
            return DeflectionResolution(
                inquiry_id=inquiry.inquiry_id,
                tenant_id=inquiry.tenant_id,
                action=DeflectionAction.AUTO_REFUND,
                refund_reference=refund_id,
                notes=f"Pre-emptive refund triggered for {inquiry.network.value} fraud alert {inquiry.reason_code} ({inquiry.amount_minor} {inquiry.currency})",
                resolved_at=current_time,
            )

        return DeflectionResolution(
            inquiry_id=inquiry.inquiry_id,
            tenant_id=inquiry.tenant_id,
            action=DeflectionAction.PROVIDE_INFO,
            notes=f"Issuer deflection inquiry queued for evidence compilation; amount {inquiry.amount_minor} > threshold or non-fraud",
            resolved_at=current_time,
        )


DeflectionSource = Literal["VERIFI", "ETHOCA"]


@dataclass(frozen=True)
class DeflectionHandlingResult:
    """Normalized pre-dispute deflection alert and recommended non-authoritative action."""

    alert: DeflectionAlert
    source: DeflectionSource
    external_alert_id: str
    auto_refund_executed: bool
    requires_human_approval: bool
    alert_hash: str


class DeflectionAlertAdapter:
    """Handler for Verifi & Ethoca pre-dispute alerts implementing PaymentProviderAdapter."""

    provider_name = "deflection"

    def __init__(
        self,
        *,
        api_base_url: str | None = None,
        api_key: str | None = None,
        webhook_secret: str | None = None,
        high_value_threshold_minor: int = 25000,
        http_client: httpx.AsyncClient | None = None,
        timeout_seconds: float = 15.0,
        max_retries: int = 2,
        retry_base_delay: float = 0.05,
    ) -> None:
        self.api_base_url = api_base_url.rstrip("/") if api_base_url else None
        self.api_key = api_key
        self.webhook_secret = webhook_secret
        self.high_value_threshold_minor = high_value_threshold_minor
        self._http = RetryingHTTPClient(
            provider_name=self.provider_name,
            base_url=self.api_base_url or "https://deflection.local",
            http_client=http_client,
            timeout_seconds=timeout_seconds,
            max_retries=max_retries,
            retry_base_delay=retry_base_delay,
        )

    @staticmethod
    def _detect_source(raw_alert: dict[str, Any]) -> DeflectionSource:
        raw_source = str(raw_alert.get("source") or raw_alert.get("network") or "").strip().upper()
        if raw_source in ("ETHOCA", "MASTERCARD_ETHOCA"):
            return "ETHOCA"
        if raw_source in ("VERIFI", "VISA_VERIFI", "CDRN", "RDR"):
            return "VERIFI"
        if "ethoca_alert_id" in raw_alert or "ethoca_id" in raw_alert:
            return "ETHOCA"
        if "verifi_alert_id" in raw_alert or "case_id" in raw_alert:
            return "VERIFI"
        raise ProviderValidationError("Unable to identify deflection alert source (expected VERIFI or ETHOCA)")

    @staticmethod
    def _extract_amount_minor(raw_alert: dict[str, Any]) -> int | None:
        if isinstance(raw_alert.get("amount_minor"), int):
            return int(raw_alert["amount_minor"])
        if raw_alert.get("amount") is not None:
            currency = str(raw_alert.get("currency") or "USD").upper()
            try:
                return decimal_str_to_minor(str(raw_alert["amount"]), currency)
            except ValueError as exc:
                raise ProviderValidationError(f"Invalid alert amount: {raw_alert['amount']!r}") from exc
        return None

    def _classify_alert(
        self,
        *,
        source: DeflectionSource,
        reason_code: str,
        amount_minor: int | None,
    ) -> tuple[str, str, str]:
        code_upper = reason_code.strip().upper()
        is_high_value = amount_minor is not None and amount_minor >= self.high_value_threshold_minor

        if any(tok in code_upper for tok in ("FRAUD", "10.4", "4837", "UNAUTHORIZED")):
            severity = "CRITICAL" if is_high_value else "HIGH"
            alert_type = f"{source}_FRAUD_DEFLECTION"
            action = "HALT_FULFILLMENT_AND_HUMAN_REFUND_REVIEW"
        elif any(tok in code_upper for tok in ("NOT_RECEIVED", "13.1", "4855", "ITEM_NOT_RECEIVED")):
            severity = "HIGH" if is_high_value else "MEDIUM"
            alert_type = f"{source}_DELIVERY_DEFLECTION"
            action = "PROACTIVELY_SHARE_TRACKING_AND_NOTIFY_BUYER"
        else:
            severity = "HIGH" if is_high_value else "MEDIUM"
            alert_type = f"{source}_DISPUTE_DEFLECTION"
            action = "ESCALATE_PRE_DISPUTE_REVIEW"
        return alert_type, severity, action

    def ingest_alert(
        self,
        raw_alert: dict[str, Any],
        *,
        tenant_id: UUID | None = None,
        correlation_id: UUID | None = None,
        payment_intent_id: UUID | None = None,
        dispute_case_id: UUID | None = None,
    ) -> DeflectionHandlingResult:
        """Normalize a Verifi or Ethoca alert into a DeflectionAlert without auto-refunding."""
        source = self._detect_source(raw_alert)
        external_id = str(
            raw_alert.get("alert_id")
            or raw_alert.get("ethoca_alert_id")
            or raw_alert.get("verifi_alert_id")
            or raw_alert.get("id")
            or ""
        ).strip()
        if not external_id:
            raise ProviderValidationError("Deflection alert missing external alert_id")

        reason_code = str(raw_alert.get("reason_code") or raw_alert.get("reason") or "UNSPECIFIED").strip()
        amount_minor = self._extract_amount_minor(raw_alert)
        alert_type, severity, recommended_action = self._classify_alert(
            source=source,
            reason_code=reason_code,
            amount_minor=amount_minor,
        )

        resolved_tenant = tenant_id
        if resolved_tenant is None:
            raw_tid = raw_alert.get("tenant_id")
            resolved_tenant = UUID(str(raw_tid)) if raw_tid else DEFAULT_TENANT_UUID
        resolved_corr = correlation_id or uuid4()

        reason_desc = (
            f"{source} pre-dispute alert {external_id} (reason_code={reason_code}"
            + (f", arn={raw_alert['arn']}" if raw_alert.get("arn") else "")
            + (f", amount_minor={amount_minor}" if amount_minor is not None else "")
            + ")"
        )
        alert = DeflectionAlert(
            tenant_id=resolved_tenant,
            correlation_id=resolved_corr,
            payment_intent_id=payment_intent_id,
            dispute_case_id=dispute_case_id,
            alert_type=alert_type,
            severity=severity,
            reason=reason_desc,
            recommended_action=recommended_action,
            acknowledged=False,
        )
        return DeflectionHandlingResult(
            alert=alert,
            source=source,
            external_alert_id=external_id,
            auto_refund_executed=False,
            requires_human_approval=True,
            alert_hash=compute_payload_hash(alert.model_dump(mode="json")),
        )

    async def acknowledge_alert(
        self,
        *,
        alert_id: str,
        source: DeflectionSource,
        outcome: str,
        notes: str | None = None,
    ) -> dict[str, Any]:
        """Acknowledge or report deflection outcome back to Verifi / Ethoca."""
        if not alert_id.strip():
            raise ProviderValidationError("alert_id must not be empty")
        payload = {
            "alert_id": alert_id,
            "source": source,
            "outcome": outcome,
            "notes": notes or "",
        }
        if not self.api_base_url:
            return {"provider": self.provider_name, "acknowledged": True, **payload}

        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        resp = await self._http.request(
            "POST",
            f"{self.api_base_url}/v1/alerts/{alert_id}/acknowledge",
            json=payload,
            headers=headers,
        )
        if resp.status_code >= 400:
            raise ProviderAPIError(
                f"{source} acknowledge failed ({resp.status_code}): {resp.text}",
                status_code=resp.status_code,
                provider=self.provider_name,
            )
        return {"provider": self.provider_name, "acknowledged": True, **resp.json()}

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
        return {
            "provider": self.provider_name,
            "order_id": f"defl_watch_{idempotency_key[:16]}",
            "status": "MONITORING_ACTIVE",
            "amount_minor": amount_minor,
            "currency": currency.upper(),
            "metadata": metadata or {},
        }

    async def capture_order(
        self,
        *,
        order_id: str,
        idempotency_key: str,
        amount_minor: int | None = None,
        currency: str | None = None,
    ) -> dict[str, Any]:
        return {
            "provider": self.provider_name,
            "order_id": order_id,
            "capture_id": f"defl_enrolled_{order_id}",
            "status": "ENROLLED",
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
        return {
            "provider": self.provider_name,
            "refund_id": f"defl_ref_{idempotency_key[:16]}",
            "capture_id": capture_id,
            "status": "DEFLECTION_OUTCOME_RECORDED",
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
        return {
            "provider": self.provider_name,
            "authorization_id": authorization_id,
            "status": "WATCH_CANCELLED",
        }

    async def provide_dispute_evidence(
        self,
        *,
        dispute_id: str,
        evidence_type: str,
        notes: str,
        documents: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        return await self.acknowledge_alert(
            alert_id=dispute_id,
            source="VERIFI",
            outcome=f"EVIDENCE_PROVIDED:{evidence_type}",
            notes=notes,
        )

    async def accept_dispute_claim(
        self,
        *,
        dispute_id: str,
        reason: str,
    ) -> dict[str, Any]:
        return await self.acknowledge_alert(
            alert_id=dispute_id,
            source="ETHOCA",
            outcome="PRE_DISPUTE_ACCEPTED",
            notes=reason,
        )

    async def verify_webhook(
        self,
        *,
        headers: dict[str, str],
        body: bytes,
    ) -> dict[str, Any]:
        if not self.webhook_secret:
            raise ProviderConfigurationError("webhook_secret is required to verify deflection webhooks")
        normalized = {k.lower(): v for k, v in headers.items()}
        sig = (
            normalized.get("x-deflection-signature")
            or normalized.get("x-verifi-signature")
            or normalized.get("x-ethoca-signature")
            or ""
        )
        if not sig:
            raise ProviderSignatureError("Missing deflection webhook signature header")
        expected = hmac.new(self.webhook_secret.encode("utf-8"), body, hashlib.sha256).hexdigest()
        if not hmac.compare_digest(expected, sig):
            raise ProviderSignatureError("Invalid deflection webhook signature")
        try:
            raw_alert = json.loads(body.decode("utf-8"))
        except Exception as exc:
            raise ProviderValidationError("Invalid deflection webhook JSON payload") from exc
        handled = self.ingest_alert(raw_alert)
        return {
            "verified": True,
            "provider": self.provider_name,
            "source": handled.source,
            "external_alert_id": handled.external_alert_id,
            "alert": handled.alert.model_dump(mode="json"),
            "alert_hash": handled.alert_hash,
            "auto_refund_executed": handled.auto_refund_executed,
        }
