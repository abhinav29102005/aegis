"""SQLAlchemy 2.0 ORM schema for AgentPay Nexus canonical financial ledger."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    event,
    false,
    text,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

PG_AUDIT_TRIGGER_FUNCTION_SQL = """
CREATE OR REPLACE FUNCTION aegis_prevent_financial_event_mutation()
RETURNS TRIGGER AS $$
BEGIN
    RAISE EXCEPTION 'financial_events is append-only; % is prohibited', TG_OP;
END;
$$ LANGUAGE plpgsql;
""".strip()

PG_AUDIT_TRIGGER_DROP_SQL = (
    "DROP TRIGGER IF EXISTS trg_aegis_prevent_financial_event_mutation ON financial_events;"
)

PG_AUDIT_TRIGGER_CREATE_SQL = """
CREATE TRIGGER trg_aegis_prevent_financial_event_mutation
BEFORE UPDATE OR DELETE ON financial_events
FOR EACH ROW EXECUTE FUNCTION aegis_prevent_financial_event_mutation();
""".strip()


def _utc_now() -> datetime:
    return datetime.now(UTC)


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
    passport_snapshot_id: Mapped[str | None] = mapped_column(String(64), index=True, nullable=True)
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
    response_due_by: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    resolution_outcome: Mapped[str | None] = mapped_column(String(64), nullable=True)
    external_status: Mapped[str | None] = mapped_column(String(64), nullable=True)
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
    __table_args__ = (
        Index("ix_outbox_events_status_lease_expires_at", "status", "lease_expires_at"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    tenant_id: Mapped[UUID] = mapped_column(Uuid, index=True, nullable=False)
    aggregate_type: Mapped[str] = mapped_column(String(64), nullable=False)
    aggregate_id: Mapped[UUID] = mapped_column(Uuid, nullable=False)
    event_type: Mapped[str] = mapped_column(String(64), nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="PENDING", index=True)
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    next_retry_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    dead_lettered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    locked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    locked_by: Mapped[str | None] = mapped_column(String(128), nullable=True)
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


# ----------------------------------------------------------------------
# AEGIS Multi-Tenant Auth, RBAC, Investigations, Artifacts & Webhooks
# ----------------------------------------------------------------------
class UserRow(Base):
    __tablename__ = "users"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True, nullable=False)
    full_name: Mapped[str] = mapped_column(String(160), nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    email_verified: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    mfa_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    mfa_secret_encrypted: Mapped[str | None] = mapped_column(Text, nullable=True)
    erased_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utc_now, nullable=False)


class OrganizationMembershipRow(Base):
    __tablename__ = "organization_memberships"
    __table_args__ = (
        UniqueConstraint("tenant_id", "user_id", name="uq_org_membership_tenant_user"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    tenant_id: Mapped[UUID] = mapped_column(Uuid, ForeignKey("tenants.id"), index=True, nullable=False)
    user_id: Mapped[UUID] = mapped_column(Uuid, ForeignKey("users.id"), index=True, nullable=False)
    role: Mapped[str] = mapped_column(String(32), nullable=False, default="OPERATOR")
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="ACTIVE")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utc_now, nullable=False)


class ServiceAccountRow(Base):
    __tablename__ = "service_accounts"
    __table_args__ = (
        UniqueConstraint("tenant_id", "name", name="uq_service_account_tenant_name"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    tenant_id: Mapped[UUID] = mapped_column(Uuid, ForeignKey("tenants.id"), index=True, nullable=False)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    description: Mapped[str] = mapped_column(String(500), nullable=False, default="")
    role: Mapped[str] = mapped_column(String(32), nullable=False, default="AGENT_SERVICE")
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="ACTIVE")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utc_now, nullable=False)


class ApiKeyRow(Base):
    __tablename__ = "api_keys"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    tenant_id: Mapped[UUID] = mapped_column(Uuid, ForeignKey("tenants.id"), index=True, nullable=False)
    service_account_id: Mapped[UUID | None] = mapped_column(
        Uuid, ForeignKey("service_accounts.id"), index=True, nullable=True
    )
    user_id: Mapped[UUID | None] = mapped_column(Uuid, ForeignKey("users.id"), index=True, nullable=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    key_prefix: Mapped[str] = mapped_column(String(32), index=True, nullable=False)
    key_hash: Mapped[str] = mapped_column(String(128), unique=True, index=True, nullable=False)
    role: Mapped[str] = mapped_column(String(32), nullable=False, default="AGENT_SERVICE")
    scopes: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="ACTIVE", index=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utc_now, nullable=False)


class AdminAuditLogRow(Base):
    __tablename__ = "admin_audit_logs"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    tenant_id: Mapped[UUID] = mapped_column(Uuid, ForeignKey("tenants.id"), index=True, nullable=False)
    actor_type: Mapped[str] = mapped_column(String(64), nullable=False)
    actor_id: Mapped[str] = mapped_column(String(128), nullable=False)
    action: Mapped[str] = mapped_column(String(128), index=True, nullable=False)
    resource_type: Mapped[str] = mapped_column(String(64), nullable=False)
    resource_id: Mapped[str] = mapped_column(String(128), nullable=False)
    correlation_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    details: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utc_now, index=True, nullable=False)


class ReplayInvestigationRow(Base):
    __tablename__ = "replay_investigations"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    tenant_id: Mapped[UUID] = mapped_column(Uuid, ForeignKey("tenants.id"), index=True, nullable=False)
    correlation_id: Mapped[UUID] = mapped_column(Uuid, index=True, nullable=False)
    payment_intent_id: Mapped[UUID] = mapped_column(Uuid, ForeignKey("payment_intents.id"), index=True, nullable=False)
    policy_version: Mapped[str] = mapped_column(String(64), nullable=False)
    mode: Mapped[str] = mapped_column(String(32), nullable=False, default="REPLAY")
    overrides: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    result_payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    consistency_status: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    drift_detected: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    integrity_valid: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_by: Mapped[str] = mapped_column(String(128), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utc_now, index=True, nullable=False)


class DisputeCaseMetadataRow(Base):
    __tablename__ = "dispute_case_metadata"

    dispute_case_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("dispute_cases.id"), primary_key=True
    )
    tenant_id: Mapped[UUID] = mapped_column(Uuid, ForeignKey("tenants.id"), index=True, nullable=False)
    assigned_to: Mapped[str | None] = mapped_column(String(160), nullable=True)
    notes: Mapped[list[dict[str, Any]]] = mapped_column(JSON, nullable=False, default=list)
    retention_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utc_now, nullable=False)


class EvidenceArtifactRow(Base):
    __tablename__ = "evidence_artifacts"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    tenant_id: Mapped[UUID] = mapped_column(Uuid, ForeignKey("tenants.id"), index=True, nullable=False)
    evidence_record_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("evidence_records.id"), index=True, nullable=False
    )
    storage_backend: Mapped[str] = mapped_column(String(64), nullable=False, default="LOCAL_OBJECT_STORE")
    object_key: Mapped[str] = mapped_column(String(500), unique=True, nullable=False)
    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    content_type: Mapped[str] = mapped_column(String(128), nullable=False, default="application/octet-stream")
    byte_size: Mapped[int] = mapped_column(Integer, nullable=False)
    sha256: Mapped[str] = mapped_column(String(128), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utc_now, nullable=False)


class WebhookEndpointRow(Base):
    __tablename__ = "webhook_endpoints"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    tenant_id: Mapped[UUID] = mapped_column(Uuid, ForeignKey("tenants.id"), index=True, nullable=False)
    url: Mapped[str] = mapped_column(String(500), nullable=False)
    description: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    signing_secret: Mapped[str] = mapped_column(String(128), nullable=False)
    event_types: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="ACTIVE", index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utc_now, nullable=False)


class WebhookDeliveryRow(Base):
    __tablename__ = "webhook_deliveries"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    tenant_id: Mapped[UUID] = mapped_column(Uuid, ForeignKey("tenants.id"), index=True, nullable=False)
    endpoint_id: Mapped[UUID] = mapped_column(Uuid, ForeignKey("webhook_endpoints.id"), index=True, nullable=False)
    outbox_event_id: Mapped[UUID | None] = mapped_column(Uuid, index=True, nullable=True)
    event_type: Mapped[str] = mapped_column(String(64), nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="PENDING", index=True)
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    response_status: Mapped[int | None] = mapped_column(Integer, nullable=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    next_retry_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utc_now, nullable=False)


# ----------------------------------------------------------------------
# Production Hardening & Extensions (0003)
# ----------------------------------------------------------------------
class SpendingPassportSnapshotRow(Base):
    __tablename__ = "spending_passport_snapshots"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(Uuid, index=True, nullable=False)
    passport_id: Mapped[UUID] = mapped_column(Uuid, index=True, nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    policy_version: Mapped[str] = mapped_column(String(64), nullable=False)
    snapshot_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utc_now, nullable=False)
    created_by: Mapped[str | None] = mapped_column(String(128), nullable=True)


class GhostPayTraceRow(Base):
    __tablename__ = "ghostpay_traces"
    __table_args__ = (
        UniqueConstraint("tenant_id", "trace_id", name="uq_ghostpay_trace_tenant_trace"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(Uuid, index=True, nullable=False)
    trace_id: Mapped[str] = mapped_column(String(128), nullable=False)
    agent_id: Mapped[str] = mapped_column(String(128), index=True, nullable=False)
    correlation_id: Mapped[str] = mapped_column(String(128), index=True, nullable=False, default="")
    payload_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    recorded_decision_json: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utc_now, nullable=False)


class GhostPayAgentDnaProfileRow(Base):
    __tablename__ = "ghostpay_agent_dna_profiles"
    __table_args__ = (
        UniqueConstraint("tenant_id", "agent_id", name="uq_ghostpay_dna_tenant_agent"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(Uuid, index=True, nullable=False)
    agent_id: Mapped[str] = mapped_column(String(128), nullable=False)
    profile_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utc_now, nullable=False)


class LlmInvocationLogRow(Base):
    __tablename__ = "llm_invocation_logs"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(Uuid, index=True, nullable=False)
    correlation_id: Mapped[str] = mapped_column(String(128), index=True, nullable=False)
    module: Mapped[str] = mapped_column(String(64), nullable=False)
    provider: Mapped[str] = mapped_column(String(64), nullable=False)
    model: Mapped[str] = mapped_column(String(128), nullable=False)
    prompt_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    completion_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    estimated_cost_usd_micros: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utc_now, nullable=False)


class PayPalWebhookEventRow(Base):
    __tablename__ = "paypal_webhook_events"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    event_id: Mapped[str] = mapped_column(String(128), unique=True, nullable=False)
    event_type: Mapped[str] = mapped_column(String(128), nullable=False)
    resource_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    payload_hash: Mapped[str] = mapped_column(String(128), nullable=False)
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utc_now, nullable=False)


class OrgInvitationRow(Base):
    __tablename__ = "org_invitations"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(Uuid, index=True, nullable=False)
    email: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[str] = mapped_column(String(32), nullable=False)
    token_hash: Mapped[str] = mapped_column(String(128), unique=True, nullable=False)
    invited_by_user_id: Mapped[UUID | None] = mapped_column(Uuid, nullable=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="PENDING")
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    accepted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utc_now, nullable=False)


class EmailVerificationRow(Base):
    __tablename__ = "email_verifications"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(Uuid, index=True, nullable=False)
    email: Mapped[str] = mapped_column(String(255), nullable=False)
    token_hash: Mapped[str] = mapped_column(String(128), unique=True, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utc_now, nullable=False)


class BillingSubscriptionRow(Base):
    __tablename__ = "billing_subscriptions"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(Uuid, unique=True, nullable=False)
    plan: Mapped[str] = mapped_column(String(32), nullable=False, default="FREE")
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="ACTIVE")
    stripe_customer_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    stripe_subscription_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    monthly_tx_quota: Mapped[int] = mapped_column(Integer, nullable=False, default=100)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utc_now, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utc_now, nullable=False)


class UsageMeterRow(Base):
    __tablename__ = "usage_meters"
    __table_args__ = (
        UniqueConstraint("tenant_id", "period_ym", "metric", name="uq_usage_meter_tenant_period_metric"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(Uuid, index=True, nullable=False)
    period_ym: Mapped[str] = mapped_column(String(7), nullable=False)
    metric: Mapped[str] = mapped_column(String(64), nullable=False)
    count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utc_now, nullable=False)


class ErasureRequestRow(Base):
    __tablename__ = "erasure_requests"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(Uuid, index=True, nullable=False)
    subject_type: Mapped[str] = mapped_column(String(64), nullable=False)
    subject_id: Mapped[str] = mapped_column(String(128), nullable=False)
    requested_by: Mapped[str | None] = mapped_column(String(128), nullable=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="PENDING")
    details_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utc_now, nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


@event.listens_for(FinancialEventRow.__table__, "after_create")
def _install_pg_financial_event_trigger(target: Any, connection: Any, **kw: Any) -> None:
    """Install append-only immutability trigger on PostgreSQL when financial_events is created."""
    if connection.dialect.name == "postgresql":
        connection.execute(text(PG_AUDIT_TRIGGER_FUNCTION_SQL))
        connection.execute(text(PG_AUDIT_TRIGGER_DROP_SQL))
        connection.execute(text(PG_AUDIT_TRIGGER_CREATE_SQL))


