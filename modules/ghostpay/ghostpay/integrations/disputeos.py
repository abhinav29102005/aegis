"""Read-only evidence export adapter to DisputeOS."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from contracts import EvidenceRecord
from pydantic import BaseModel, Field

from ghostpay.domain.models import InvestigationReport, PaymentTrace


def _utc_now() -> datetime:
    return datetime.now(UTC)


class DisputeOSEvidenceBundle(BaseModel):
    """Structured evidence bundle for DisputeOS case preparation."""

    payment_intent_id: UUID
    tenant_id: UUID
    paypal_order_id: str | None = None
    paypal_capture_id: str | None = None
    timeline_summary: list[dict[str, Any]] = Field(default_factory=list)
    evidence_records: list[EvidenceRecord] = Field(default_factory=list)
    trace_integrity_status: str
    detected_anomalies: list[str] = Field(default_factory=list)
    counterfactual_summary: str = Field(default="No counterfactual analysis attached")
    missing_evidence_indicators: list[str] = Field(default_factory=list)
    exported_at: datetime = Field(default_factory=_utc_now)


def export_to_disputeos(
    trace: PaymentTrace,
    investigation: InvestigationReport | None = None,
) -> DisputeOSEvidenceBundle:
    """Prepare a structured, read-only evidence bundle for DisputeOS ingestion."""
    # Find paypal order and capture id if present in events or evidence
    order_id: str | None = None
    capture_id: str | None = None

    for ev in trace.ordered_events:
        if ev.payload:
            if "paypal_order_id" in ev.payload and not order_id:
                order_id = str(ev.payload["paypal_order_id"])
            if "capture_id" in ev.payload and not capture_id:
                capture_id = str(ev.payload["capture_id"])

    for rec in trace.authorization_evidence:
        if rec.content:
            if "paypal_order_id" in rec.content and not order_id:
                order_id = str(rec.content["paypal_order_id"])
            if "capture_id" in rec.content and not capture_id:
                capture_id = str(rec.content["capture_id"])

    t_summary: list[dict[str, Any]] = []
    if investigation:
        for entry in investigation.timeline:
            t_summary.append({
                "seq": entry.sequence_number,
                "type": entry.event_type.value,
                "summary": entry.summary,
                "occurred_at": entry.occurred_at.isoformat(),
                "integrity_verified": entry.integrity_verified,
            })

    anomalies = investigation.detected_anomalies if investigation else []
    counterfactual = (
        f"{len(investigation.counterfactual_replay_results)} counterfactual policies evaluated"
        if (investigation and investigation.counterfactual_replay_results)
        else "No counterfactual replay attached"
    )

    return DisputeOSEvidenceBundle(
        payment_intent_id=trace.payment_intent_id,
        tenant_id=trace.tenant_id,
        paypal_order_id=order_id,
        paypal_capture_id=capture_id,
        timeline_summary=t_summary,
        evidence_records=trace.authorization_evidence,
        trace_integrity_status=trace.integrity_status,
        detected_anomalies=anomalies,
        counterfactual_summary=counterfactual,
        missing_evidence_indicators=trace.missing_evidence,
    )
