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

    def to_replay_request(self) -> ReplayRequest | None:
        """Convert trace to a canonical ReplayRequest if minimal requirements are met."""
        if not (self.recorded_passport and self.recorded_decision and self.quote_snapshot and self.recorded_merchant):
            return None

        # Resolve proposal
        if self.proposal:
            prop = self.proposal
        else:
            prop = PurchaseProposal(
                id=self.quote_snapshot.proposal_id,
                tenant_id=self.tenant_id,
                correlation_id=self.quote_snapshot.correlation_id,
                agent_id=self.agent_id,
                passport_id=self.recorded_passport.id,
                merchant_id=self.recorded_merchant.id,
                merchant_name=self.recorded_merchant.name,
                amount_minor=self.quote_snapshot.amount_minor,
                currency=self.quote_snapshot.currency,
                line_items=self.quote_snapshot.line_items,
                item_summary="Reconstructed purchase proposal",
                rationale="Forensic trace replay",
                idempotency_key=f"reconstructed-{self.trace_id}",
                created_at=self.quote_snapshot.created_at,
            )

        # Resolve payment_intent
        if self.payment_intent:
            intent = self.payment_intent
        else:
            intent = PaymentIntent(
                id=self.payment_intent_id,
                tenant_id=self.tenant_id,
                correlation_id=self.quote_snapshot.correlation_id,
                proposal_id=self.quote_snapshot.proposal_id,
                agent_id=self.agent_id,
                passport_id=self.recorded_passport.id,
                merchant_id=self.recorded_merchant.id,
                quote_snapshot_id=self.quote_snapshot.id,
                quote_hash=self.quote_snapshot.quote_hash,
                amount_minor=self.quote_snapshot.amount_minor,
                currency=self.quote_snapshot.currency,
                idempotency_key=f"reconstructed-intent-{self.trace_id}",
                created_at=self.created_at,
                updated_at=self.created_at,
            )

        return ReplayRequest(
            tenant_id=self.tenant_id,
            correlation_id=self.quote_snapshot.correlation_id,
            payment_intent=intent,
            proposal=prop,
            quote_snapshot=self.quote_snapshot,
            recorded_passport=self.recorded_passport,
            recorded_merchant=self.recorded_merchant,
            recorded_decision=self.recorded_decision,
            approval_record=self.approval_record,
            policy_version=self.policy_version,
            events=self.ordered_events,
            evidence_records=self.authorization_evidence,
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
