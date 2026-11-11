"""SQLAlchemy 2.0 ORM schema for AgentPay Nexus canonical financial ledger."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


class TenantRow(Base):
    __tablename__ = "tenants"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    slug: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utc_now, nullable=False)


class AgentRow(Base):
    __tablename__ = "agents"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    tenant_id: Mapped[UUID] = mapped_column(Uuid, ForeignKey("tenants.id"), index=True, nullable=False)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    purpose: Mapped[str] = mapped_column(String(255), nullable=False)
    framework: Mapped[str] = mapped_column(String(64), nullable=False, default="langgraph")
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="ACTIVE")
    public_fingerprint: Mapped[str] = mapped_column(String(128), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utc_now, nullable=False)


class MerchantRow(Base):
    __tablename__ = "merchants"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    tenant_id: Mapped[UUID] = mapped_column(Uuid, ForeignKey("tenants.id"), index=True, nullable=False)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    domain: Mapped[str] = mapped_column(String(255), nullable=False)
    category: Mapped[str] = mapped_column(String(64), nullable=False)
    paypal_merchant_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    is_allowlisted: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    is_sandbox_verified: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utc_now, nullable=False)


class SpendingPassportRow(Base):
    __tablename__ = "spending_passports"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    tenant_id: Mapped[UUID] = mapped_column(Uuid, ForeignKey("tenants.id"), index=True, nullable=False)
    agent_id: Mapped[UUID] = mapped_column(Uuid, ForeignKey("agents.id"), index=True, nullable=False)
    policy_version: Mapped[str] = mapped_column(String(64), nullable=False, default="policy-v1")
    currency: Mapped[str] = mapped_column(String(3), nullable=False, default="USD")
    total_budget_minor: Mapped[int] = mapped_column(Integer, nullable=False)
    spent_minor: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    reserved_minor: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    per_tx_limit_minor: Mapped[int] = mapped_column(Integer, nullable=False)
    daily_limit_minor: Mapped[int] = mapped_column(Integer, nullable=False)
    human_approval_threshold_minor: Mapped[int] = mapped_column(Integer, nullable=False, default=5000)
    allowed_merchant_ids: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    allowed_categories: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    allow_unknown_merchants: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="ACTIVE")
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utc_now, nullable=False)


class PurchaseProposalRow(Base):
    __tablename__ = "purchase_proposals"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    tenant_id: Mapped[UUID] = mapped_column(Uuid, ForeignKey("tenants.id"), index=True, nullable=False)
    correlation_id: Mapped[UUID] = mapped_column(Uuid, index=True, nullable=False)
    agent_id: Mapped[UUID] = mapped_column(Uuid, ForeignKey("agents.id"), nullable=False)
    passport_id: Mapped[UUID] = mapped_column(Uuid, ForeignKey("spending_passports.id"), nullable=False)
    merchant_id: Mapped[UUID] = mapped_column(Uuid, ForeignKey("merchants.id"), nullable=False)
    merchant_name: Mapped[str] = mapped_column(String(160), nullable=False)
    merchant_category: Mapped[str] = mapped_column(String(64), nullable=False)
    amount_minor: Mapped[int] = mapped_column(Integer, nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False, default="USD")
    item_summary: Mapped[str] = mapped_column(String(500), nullable=False)
    line_items: Mapped[list[dict[str, Any]]] = mapped_column(JSON, nullable=False, default=list)
    rationale: Mapped[str] = mapped_column(Text, nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(128), nullable=False)
    proposed_by_model: Mapped[str] = mapped_column(String(128), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utc_now, nullable=False)


class QuoteSnapshotRow(Base):
    __tablename__ = "quote_snapshots"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    tenant_id: Mapped[UUID] = mapped_column(Uuid, ForeignKey("tenants.id"), index=True, nullable=False)
    correlation_id: Mapped[UUID] = mapped_column(Uuid, index=True, nullable=False)
    proposal_id: Mapped[UUID] = mapped_column(Uuid, ForeignKey("purchase_proposals.id"), nullable=False)
    merchant_id: Mapped[UUID] = mapped_column(Uuid, ForeignKey("merchants.id"), nullable=False)
    amount_minor: Mapped[int] = mapped_column(Integer, nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False, default="USD")
    line_items: Mapped[list[dict[str, Any]]] = mapped_column(JSON, nullable=False, default=list)
    quote_hash: Mapped[str] = mapped_column(String(128), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utc_now, nullable=False)


class PaymentIntentRow(Base):
    __tablename__ = "payment_intents"
    __table_args__ = (
        UniqueConstraint("tenant_id", "idempotency_key", name="uq_payment_intent_tenant_idemp"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    tenant_id: Mapped[UUID] = mapped_column(Uuid, ForeignKey("tenants.id"), index=True, nullable=False)
    correlation_id: Mapped[UUID] = mapped_column(Uuid, index=True, nullable=False)
    proposal_id: Mapped[UUID] = mapped_column(Uuid, ForeignKey("purchase_proposals.id"), nullable=False)
    agent_id: Mapped[UUID] = mapped_column(Uuid, ForeignKey("agents.id"), nullable=False)
    passport_id: Mapped[UUID] = mapped_column(Uuid, ForeignKey("spending_passports.id"), nullable=False)
    merchant_id: Mapped[UUID] = mapped_column(Uuid, ForeignKey("merchants.id"), nullable=False)
    quote_snapshot_id: Mapped[UUID] = mapped_column(Uuid, ForeignKey("quote_snapshots.id"), nullable=False)
    quote_hash: Mapped[str] = mapped_column(String(128), nullable=False)
    amount_minor: Mapped[int] = mapped_column(Integer, nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    state: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    idempotency_key: Mapped[str] = mapped_column(String(128), nullable=False)
    authorization_decision_id: Mapped[UUID | None] = mapped_column(Uuid, nullable=True)
    approval_record_id: Mapped[UUID | None] = mapped_column(Uuid, nullable=True)
    reservation_id: Mapped[UUID | None] = mapped_column(Uuid, nullable=True)
    active_attempt_id: Mapped[UUID | None] = mapped_column(Uuid, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utc_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utc_now, nullable=False)


class AuthorizationDecisionRow(Base):
    __tablename__ = "authorization_decisions"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    tenant_id: Mapped[UUID] = mapped_column(Uuid, ForeignKey("tenants.id"), index=True, nullable=False)
    correlation_id: Mapped[UUID] = mapped_column(Uuid, index=True, nullable=False)
    payment_intent_id: Mapped[UUID] = mapped_column(Uuid, ForeignKey("payment_intents.id"), index=True, nullable=False)
    proposal_id: Mapped[UUID] = mapped_column(Uuid, nullable=False)
    passport_id: Mapped[UUID] = mapped_column(Uuid, nullable=False)
    quote_snapshot_id: Mapped[UUID] = mapped_column(Uuid, nullable=False)
    quote_hash: Mapped[str] = mapped_column(String(128), nullable=False)
    policy_version: Mapped[str] = mapped_column(String(64), nullable=False)
    outcome: Mapped[str] = mapped_column(String(32), nullable=False)
    reason_codes: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    violated_constraints: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    requires_human_approval: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    explanation: Mapped[str] = mapped_column(Text, nullable=False)
    policy_inputs: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    decided_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utc_now, nullable=False)


class ApprovalRecordRow(Base):
    __tablename__ = "approval_records"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    tenant_id: Mapped[UUID] = mapped_column(Uuid, ForeignKey("tenants.id"), index=True, nullable=False)
    correlation_id: Mapped[UUID] = mapped_column(Uuid, index=True, nullable=False)
    payment_intent_id: Mapped[UUID] = mapped_column(Uuid, ForeignKey("payment_intents.id"), index=True, nullable=False)
    decision_id: Mapped[UUID] = mapped_column(Uuid, ForeignKey("authorization_decisions.id"), nullable=False)
    approver_id: Mapped[str] = mapped_column(String(128), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    bound_merchant_id: Mapped[UUID] = mapped_column(Uuid, nullable=False)
    bound_amount_minor: Mapped[int] = mapped_column(Integer, nullable=False)
    bound_currency: Mapped[str] = mapped_column(String(3), nullable=False)
    bound_quote_hash: Mapped[str] = mapped_column(String(128), nullable=False)
    comment: Mapped[str | None] = mapped_column(String(500), nullable=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utc_now, nullable=False)


class BudgetReservationRow(Base):
    __tablename__ = "budget_reservations"
    __table_args__ = (
        UniqueConstraint("payment_intent_id", name="uq_budget_reservation_intent"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    tenant_id: Mapped[UUID] = mapped_column(Uuid, ForeignKey("tenants.id"), index=True, nullable=False)
    correlation_id: Mapped[UUID] = mapped_column(Uuid, index=True, nullable=False)
    passport_id: Mapped[UUID] = mapped_column(Uuid, ForeignKey("spending_passports.id"), index=True, nullable=False)
    payment_intent_id: Mapped[UUID] = mapped_column(Uuid, ForeignKey("payment_intents.id"), nullable=False)
    amount_minor: Mapped[int] = mapped_column(Integer, nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utc_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utc_now, nullable=False)


class PaymentAttemptRow(Base):
    __tablename__ = "payment_attempts"
    __table_args__ = (
        UniqueConstraint("tenant_id", "idempotency_key", "attempt_number", name="uq_attempt_tenant_idemp_num"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    tenant_id: Mapped[UUID] = mapped_column(Uuid, ForeignKey("tenants.id"), index=True, nullable=False)
    correlation_id: Mapped[UUID] = mapped_column(Uuid, index=True, nullable=False)
    payment_intent_id: Mapped[UUID] = mapped_column(Uuid, ForeignKey("payment_intents.id"), index=True, nullable=False)
    attempt_number: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    idempotency_key: Mapped[str] = mapped_column(String(128), nullable=False)
    provider: Mapped[str] = mapped_column(String(64), nullable=False, default="PAYPAL_SANDBOX")
    paypal_order_id: Mapped[str | None] = mapped_column(String(128), index=True, nullable=True)
    paypal_approval_url: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    buyer_approval: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    verified_capture: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    state: Mapped[str] = mapped_column(String(32), nullable=False)
    failure_code: Mapped[str | None] = mapped_column(String(128), nullable=True)
    failure_reason: Mapped[str | None] = mapped_column(String(500), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utc_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utc_now, nullable=False)


class FinancialEventRow(Base):
    __tablename__ = "financial_events"
    __table_args__ = (
        UniqueConstraint("correlation_id", "sequence_number", name="uq_financial_event_corr_seq"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    tenant_id: Mapped[UUID] = mapped_column(Uuid, ForeignKey("tenants.id"), index=True, nullable=False)
    correlation_id: Mapped[UUID] = mapped_column(Uuid, index=True, nullable=False)
    payment_intent_id: Mapped[UUID | None] = mapped_column(Uuid, index=True, nullable=True)
    sequence_number: Mapped[int] = mapped_column(Integer, nullable=False)
    event_type: Mapped[str] = mapped_column(String(64), nullable=False)
    actor_type: Mapped[str] = mapped_column(String(64), nullable=False)
    actor_id: Mapped[str] = mapped_column(String(128), nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    previous_event_hash: Mapped[str | None] = mapped_column(String(128), nullable=True)
    event_hash: Mapped[str] = mapped_column(String(128), nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utc_now, nullable=False)


class EvidenceRecordRow(Base):
    __tablename__ = "evidence_records"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    tenant_id: Mapped[UUID] = mapped_column(Uuid, ForeignKey("tenants.id"), index=True, nullable=False)
    correlation_id: Mapped[UUID] = mapped_column(Uuid, index=True, nullable=False)
    payment_intent_id: Mapped[UUID | None] = mapped_column(Uuid, index=True, nullable=True)
    dispute_case_id: Mapped[UUID | None] = mapped_column(Uuid, index=True, nullable=True)
    source_type: Mapped[str] = mapped_column(String(64), nullable=False)
    source_ref: Mapped[str] = mapped_column(String(255), nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    content: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    content_hash: Mapped[str] = mapped_column(String(128), nullable=False)
    is_synthetic: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    collected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utc_now, nullable=False)


class DisputeCaseRow(Base):
    __tablename__ = "dispute_cases"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    tenant_id: Mapped[UUID] = mapped_column(Uuid, ForeignKey("tenants.id"), index=True, nullable=False)
    correlation_id: Mapped[UUID] = mapped_column(Uuid, index=True, nullable=False)
    payment_intent_id: Mapped[UUID] = mapped_column(Uuid, ForeignKey("payment_intents.id"), index=True, nullable=False)
    paypal_dispute_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    source_type: Mapped[str] = mapped_column(String(32), nullable=False)
    is_synthetic: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    reason: Mapped[str] = mapped_column(String(255), nullable=False)
    buyer_claim: Mapped[str] = mapped_column(Text, nullable=False)
    amount_minor: Mapped[int] = mapped_column(Integer, nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    evidence_ids: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    human_approved_for_submission: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    approved_by: Mapped[str | None] = mapped_column(String(128), nullable=True)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    response_payload_hash: Mapped[str | None] = mapped_column(String(128), nullable=True)
    opened_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utc_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utc_now, nullable=False)


class DisputeAnalysisRow(Base):
    __tablename__ = "dispute_analyses"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    tenant_id: Mapped[UUID] = mapped_column(Uuid, ForeignKey("tenants.id"), index=True, nullable=False)
    correlation_id: Mapped[UUID] = mapped_column(Uuid, index=True, nullable=False)
    dispute_case_id: Mapped[UUID] = mapped_column(Uuid, ForeignKey("dispute_cases.id"), index=True, nullable=False)
    is_synthetic: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    recommendation: Mapped[str] = mapped_column(String(64), nullable=False)
    confidence_score: Mapped[float] = mapped_column(Float, nullable=False)
    agent_authorized: Mapped[bool] = mapped_column(Boolean, nullable=False)
    agent_followed_policy: Mapped[bool] = mapped_column(Boolean, nullable=False)
    merchant_fulfilled_order: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    contradictions: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    missing_evidence: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    citations: Mapped[list[dict[str, Any]]] = mapped_column(JSON, nullable=False, default=list)
    rejected_claims: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    grounded_summary: Mapped[str] = mapped_column(Text, nullable=False)
    draft_response_text: Mapped[str] = mapped_column(Text, nullable=False)
    requires_human_approval: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    generated_with_llm: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    analyzed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utc_now, nullable=False)


class OutboxEventRow(Base):
    __tablename__ = "outbox_events"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    tenant_id: Mapped[UUID] = mapped_column(Uuid, index=True, nullable=False)
    aggregate_type: Mapped[str] = mapped_column(String(64), nullable=False)
    aggregate_id: Mapped[UUID] = mapped_column(Uuid, nullable=False)
    event_type: Mapped[str] = mapped_column(String(64), nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="PENDING", index=True)
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utc_now, nullable=False)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class IdempotencyRecordRow(Base):
    __tablename__ = "idempotency_records"
    __table_args__ = (
        UniqueConstraint("tenant_id", "operation", "idempotency_key", name="uq_idemp_tenant_op_key"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    tenant_id: Mapped[UUID] = mapped_column(Uuid, index=True, nullable=False)
    operation: Mapped[str] = mapped_column(String(64), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(128), nullable=False)
    request_hash: Mapped[str] = mapped_column(String(128), nullable=False)
    response_payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    status_code: Mapped[int] = mapped_column(Integer, nullable=False, default=200)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utc_now, nullable=False)

