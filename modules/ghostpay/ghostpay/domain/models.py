"""Domain models for GhostPay."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

from contracts import (
    ApprovalRecord,
    AuthorizationDecision,
    EvidenceRecord,
    FinancialEvent,
    Merchant,
    PaymentIntent,
    PurchaseProposal,
    QuoteSnapshot,
    ReplayRequest,
    ReplayResult,
    ReplayTimelineEntry,
    SpendingPassport,
)
from pydantic import BaseModel, Field, field_validator

from ghostpay.domain.exceptions import InsufficientEvidenceError


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _normalize_utc(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    return dt.astimezone(UTC) if dt.tzinfo else dt.replace(tzinfo=UTC)


class PaymentTrace(BaseModel):
    """Normalized, versioned representation of an end-to-end payment lifecycle trace."""

    trace_id: UUID = Field(default_factory=uuid4)
    tenant_id: UUID
    agent_id: UUID
    payment_intent_id: UUID
    ordered_events: list[FinancialEvent] = Field(default_factory=list)
    quote_snapshot: QuoteSnapshot | None = None
    authorization_evidence: list[EvidenceRecord] = Field(default_factory=list)
    recorded_decision: AuthorizationDecision | None = None
    recorded_passport: SpendingPassport | None = None
    recorded_merchant: Merchant | None = None
    approval_record: ApprovalRecord | None = None
    payment_intent: PaymentIntent | None = None
    proposal: PurchaseProposal | None = None
    policy_version: str = Field(default="policy-v1", max_length=64)
    integrity_status: str = Field(
        default="VALID",
        pattern=r"^(VALID|TAMPERED|INCOMPLETE|CONFLICTING)$",
    )
    missing_evidence: list[str] = Field(default_factory=list)
    provenance_references: list[str] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=_utc_now)

    @field_validator("created_at")
    @classmethod
    def _utc_created(cls, v: datetime) -> datetime:
        return _normalize_utc(v)  # type: ignore[return-value]

    def to_replay_request(self) -> ReplayRequest:
        """Convert trace to a canonical ReplayRequest, failing closed on missing artifacts."""
        missing: list[str] = []
        if self.recorded_passport is None:
            missing.append("recorded_passport")
        if self.recorded_decision is None:
            missing.append("recorded_decision")
        if self.quote_snapshot is None:
            missing.append("quote_snapshot")
        if self.recorded_merchant is None:
            missing.append("recorded_merchant")
        if self.proposal is None:
            missing.append("proposal")
        if self.payment_intent is None:
            missing.append("payment_intent")

        if missing:
            raise InsufficientEvidenceError(
                f"Insufficient evidence to construct ReplayRequest for trace {self.trace_id}: "
                f"missing {', '.join(missing)}."
            )

        assert self.recorded_passport is not None
        assert self.recorded_decision is not None
        assert self.quote_snapshot is not None
        assert self.recorded_merchant is not None
        assert self.proposal is not None
        assert self.payment_intent is not None

        return ReplayRequest(
            tenant_id=self.tenant_id,
            correlation_id=self.quote_snapshot.correlation_id,
            payment_intent=self.payment_intent,
            proposal=self.proposal,
            quote_snapshot=self.quote_snapshot,
            recorded_passport=self.recorded_passport,
            recorded_merchant=self.recorded_merchant,
            recorded_decision=self.recorded_decision,
            approval_record=self.approval_record,
            policy_version=self.policy_version,
            events=self.ordered_events,
            evidence_records=self.authorization_evidence,
            evaluation_time=self.recorded_decision.decided_at,
        )


class InvestigationReport(BaseModel):
    """Complete evidence-backed forensic investigation report."""

    investigation_id: UUID = Field(default_factory=uuid4)
    tenant_id: UUID
    trace_id: UUID | None = None
    payment_intent_id: UUID
    trace_integrity_status: str
    timeline: list[ReplayTimelineEntry] = Field(default_factory=list)
    detected_anomalies: list[str] = Field(default_factory=list)
    agent_dna_signals: list[dict[str, Any]] = Field(default_factory=list)
    counterfactual_replay_results: list[ReplayResult] = Field(default_factory=list)
    suggested_safeguards: list[str] = Field(default_factory=list)
    evidence_references: list[UUID] = Field(default_factory=list)
    missing_evidence: list[str] = Field(default_factory=list)
    confidence_limitations: list[str] = Field(default_factory=list)

    # Strictly distinguished categories of findings
    verified_facts: list[str] = Field(default_factory=list)
    deterministic_policy_outcomes: list[str] = Field(default_factory=list)
    statistical_anomaly_signals: list[str] = Field(default_factory=list)
    ai_explanations: list[str] = Field(default_factory=list)

    created_at: datetime = Field(default_factory=_utc_now)

    @field_validator("created_at")
    @classmethod
    def _utc_created(cls, v: datetime) -> datetime:
        return _normalize_utc(v)  # type: ignore[return-value]
