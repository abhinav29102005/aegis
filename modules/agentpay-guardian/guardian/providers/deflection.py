"""Verifi / Ethoca pre-dispute deflection alert handler for AgentPay Guardian."""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Any
from uuid import UUID, uuid4

from contracts.models import NexusBaseModel
from pydantic import Field


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
