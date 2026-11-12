"""Canonical Pydantic v2 domain contracts for AgentPay Nexus."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from contracts.enums import (
    ApprovalStatus,
    DecisionOutcome,
    DecisionReasonCode,
    DisputeRecommendation,
    DisputeSourceType,
    DisputeStatus,
    EvidenceSourceType,
    FinancialEventType,
    PassportStatus,
    PaymentState,
    ReservationStatus,
)
from contracts.hashing import compute_quote_hash

SCHEMA_VERSION = "1.0.0"


def utc_now() -> datetime:
    return datetime.now(UTC)


def _normalize_utc(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    return dt.astimezone(UTC) if dt.tzinfo else dt.replace(tzinfo=UTC)


class NexusBaseModel(BaseModel):
    """Base contract with strict defaults, schema_version, and UTC timestamp normalization."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    schema_version: str = Field(default=SCHEMA_VERSION)


class Tenant(NexusBaseModel):
    id: UUID = Field(default_factory=uuid4)
    name: str = Field(min_length=1, max_length=120)
    slug: str = Field(min_length=1, max_length=64)
    created_at: datetime = Field(default_factory=utc_now)

    @field_validator("created_at")
    @classmethod
    def _utc_created(cls, v: datetime) -> datetime:
        return _normalize_utc(v)  # type: ignore[return-value]


class AgentIdentity(NexusBaseModel):
    id: UUID = Field(default_factory=uuid4)
    tenant_id: UUID
    name: str = Field(min_length=1, max_length=120)
    purpose: str = Field(default="autonomous-purchasing", max_length=255)
    framework: str = Field(default="langgraph", max_length=64)
    status: str = Field(default="ACTIVE", pattern=r"^(ACTIVE|SUSPENDED|REVOKED)$")
    public_fingerprint: str = Field(min_length=8, max_length=128)
    created_at: datetime = Field(default_factory=utc_now)

    @field_validator("created_at")
    @classmethod
    def _utc_created(cls, v: datetime) -> datetime:
        return _normalize_utc(v)  # type: ignore[return-value]


class Merchant(NexusBaseModel):
    id: UUID = Field(default_factory=uuid4)
    tenant_id: UUID
    name: str = Field(min_length=1, max_length=160)
    domain: str = Field(min_length=1, max_length=255)
    category: str = Field(default="SOFTWARE", max_length=64)
    paypal_merchant_id: str | None = Field(default=None, max_length=128)
    is_allowlisted: bool = False
    is_sandbox_verified: bool = False
    created_at: datetime = Field(default_factory=utc_now)

    @field_validator("created_at")
    @classmethod
    def _utc_created(cls, v: datetime) -> datetime:
        return _normalize_utc(v)  # type: ignore[return-value]


class SpendingPassport(NexusBaseModel):
    id: UUID = Field(default_factory=uuid4)
    tenant_id: UUID
    agent_id: UUID
    policy_version: str = Field(default="policy-v1", max_length=64)
    currency: str = Field(default="USD", min_length=3, max_length=3)
    total_budget_minor: int = Field(ge=0)
    spent_minor: int = Field(default=0, ge=0)
    reserved_minor: int = Field(default=0, ge=0)
    per_tx_limit_minor: int = Field(ge=0)
    daily_limit_minor: int = Field(ge=0)
    monthly_limit_minor: int | None = Field(default=None, ge=0)
    human_approval_threshold_minor: int = Field(default=5000, ge=0)
    allowed_currencies: list[str] = Field(default_factory=list)
    allowed_merchant_ids: list[UUID] = Field(default_factory=list)
    allowed_categories: list[str] = Field(default_factory=list)
    allow_unknown_merchants: bool = False
    status: PassportStatus = PassportStatus.ACTIVE
    expires_at: datetime
    created_at: datetime = Field(default_factory=utc_now)

    @field_validator("currency")
    @classmethod
    def _upper_currency(cls, v: str) -> str:
        return v.upper()

    @field_validator("allowed_currencies")
    @classmethod
    def _upper_allowed_currencies(cls, v: list[str]) -> list[str]:
        return [c.upper() for c in v]

    @field_validator("expires_at", "created_at")
    @classmethod
    def _utc_dates(cls, v: datetime) -> datetime:
        return _normalize_utc(v)  # type: ignore[return-value]

    @property
    def available_budget_minor(self) -> int:
        return max(0, self.total_budget_minor - self.spent_minor - self.reserved_minor)

    @property
    def approval_threshold_minor(self) -> int:
        return self.human_approval_threshold_minor


class PurchaseProposal(NexusBaseModel):
    """Non-authoritative AI agent proposal to buy an item or service."""

    id: UUID = Field(default_factory=uuid4)
    tenant_id: UUID
    correlation_id: UUID = Field(default_factory=uuid4)
    agent_id: UUID
    passport_id: UUID
    merchant_id: UUID
    merchant_name: str = Field(min_length=1, max_length=160)
    merchant_category: str = Field(default="SOFTWARE", max_length=64)
    amount_minor: int = Field(gt=0)
    currency: str = Field(default="USD", min_length=3, max_length=3)
    item_summary: str = Field(min_length=1, max_length=500)
    line_items: list[dict[str, Any]] = Field(default_factory=list)
    rationale: str = Field(min_length=1, max_length=1000)
    idempotency_key: str = Field(min_length=8, max_length=128)
    proposed_by_model: str = Field(default="deterministic-planner", max_length=128)
    created_at: datetime = Field(default_factory=utc_now)

    @field_validator("currency")
    @classmethod
    def _upper_currency(cls, v: str) -> str:
        return v.upper()

    @field_validator("created_at")
    @classmethod
    def _utc_created(cls, v: datetime) -> datetime:
        return _normalize_utc(v)  # type: ignore[return-value]


class QuoteSnapshot(NexusBaseModel):
    """Immutable snapshot of merchant, amount, and line items bound to authorization."""

    id: UUID = Field(default_factory=uuid4)
    tenant_id: UUID
    correlation_id: UUID
    proposal_id: UUID
    merchant_id: UUID
    amount_minor: int = Field(gt=0)
    currency: str = Field(default="USD", min_length=3, max_length=3)
    line_items: list[dict[str, Any]] = Field(default_factory=list)
    quote_hash: str = ""
    expires_at: datetime
    created_at: datetime = Field(default_factory=utc_now)

    @field_validator("currency")
    @classmethod
    def _upper_currency(cls, v: str) -> str:
        return v.upper()

    @field_validator("expires_at", "created_at")
    @classmethod
    def _utc_dates(cls, v: datetime) -> datetime:
        return _normalize_utc(v)  # type: ignore[return-value]

    @model_validator(mode="after")
    def _populate_and_verify_hash(self) -> QuoteSnapshot:
        computed = compute_quote_hash(
            merchant_id=self.merchant_id,
            amount_minor=self.amount_minor,
            currency=self.currency,
            line_items=self.line_items,
        )
        if not self.quote_hash:
            self.quote_hash = computed
        elif self.quote_hash != computed:
            raise ValueError(
                f"quote_hash mismatch: provided {self.quote_hash} != computed {computed}"
            )
        return self


class AuthorizationDecision(NexusBaseModel):
    """Deterministic internal policy engine output (never produced by an LLM)."""

    id: UUID = Field(default_factory=uuid4)
    tenant_id: UUID
    correlation_id: UUID
    payment_intent_id: UUID
    proposal_id: UUID
    passport_id: UUID
    quote_snapshot_id: UUID
    quote_hash: str
    policy_version: str = Field(default="policy-v1", max_length=64)
    outcome: DecisionOutcome
    reason_codes: list[DecisionReasonCode] = Field(min_length=1)
    violated_constraints: list[str] = Field(default_factory=list)
    requires_human_approval: bool = False
    explanation: str = Field(min_length=1, max_length=1000)
    policy_inputs: dict[str, Any] = Field(default_factory=dict)
    decided_at: datetime = Field(default_factory=utc_now)

    @field_validator("decided_at")
    @classmethod
    def _utc_decided(cls, v: datetime) -> datetime:
        return _normalize_utc(v)  # type: ignore[return-value]


class ApprovalRecord(NexusBaseModel):
    """Explicit human authorization bound to a specific merchant, amount, and quote hash."""

    id: UUID = Field(default_factory=uuid4)
    tenant_id: UUID
    correlation_id: UUID
    payment_intent_id: UUID
    decision_id: UUID
    approver_id: str = Field(min_length=1, max_length=128)
    status: ApprovalStatus = ApprovalStatus.PENDING
    bound_merchant_id: UUID
    bound_amount_minor: int = Field(gt=0)
    bound_currency: str = Field(default="USD", min_length=3, max_length=3)
    bound_quote_hash: str
    comment: str | None = Field(default=None, max_length=500)
    expires_at: datetime
    decided_at: datetime | None = None
    consumed_at: datetime | None = None
    created_at: datetime = Field(default_factory=utc_now)

    @field_validator("bound_currency")
    @classmethod
    def _upper_currency(cls, v: str) -> str:
        return v.upper()

    @field_validator("expires_at", "decided_at", "consumed_at", "created_at")
    @classmethod
    def _utc_dates(cls, v: datetime | None) -> datetime | None:
        return _normalize_utc(v)


class BudgetReservation(NexusBaseModel):
    id: UUID = Field(default_factory=uuid4)
    tenant_id: UUID
    correlation_id: UUID
    passport_id: UUID
    payment_intent_id: UUID
    amount_minor: int = Field(gt=0)
    currency: str = Field(default="USD", min_length=3, max_length=3)
    status: ReservationStatus = ReservationStatus.HELD
    expires_at: datetime
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)

    @field_validator("currency")
    @classmethod
    def _upper_currency(cls, v: str) -> str:
        return v.upper()

    @field_validator("expires_at", "created_at", "updated_at")
    @classmethod
    def _utc_dates(cls, v: datetime) -> datetime:
        return _normalize_utc(v)  # type: ignore[return-value]


class PayPalBuyerApproval(NexusBaseModel):
    """Distinguished stage: buyer approval inside PayPal sandbox JS SDK."""

    paypal_order_id: str = Field(min_length=3, max_length=128)
    payer_id: str | None = Field(default=None, max_length=128)
    buyer_status: str = Field(default="APPROVED", max_length=64)
    approved_at: datetime = Field(default_factory=utc_now)

    @field_validator("approved_at")
    @classmethod
    def _utc_approved(cls, v: datetime) -> datetime:
        return _normalize_utc(v)  # type: ignore[return-value]


class VerifiedPayPalCapture(NexusBaseModel):
    """Distinguished stage: server-verified PayPal capture before SUCCEEDED state."""

    paypal_order_id: str = Field(min_length=3, max_length=128)
    paypal_capture_id: str = Field(min_length=3, max_length=128)
    paypal_status: str = Field(min_length=1, max_length=64)
    verified_amount_minor: int = Field(gt=0)
    verified_currency: str = Field(min_length=3, max_length=3)
    verification_hash: str = Field(min_length=16, max_length=128)
    verified_at: datetime = Field(default_factory=utc_now)

    @field_validator("verified_currency")
    @classmethod
    def _upper_currency(cls, v: str) -> str:
        return v.upper()

    @field_validator("verified_at")
    @classmethod
    def _utc_verified(cls, v: datetime) -> datetime:
        return _normalize_utc(v)  # type: ignore[return-value]


class PaymentAttempt(NexusBaseModel):
    id: UUID = Field(default_factory=uuid4)
    tenant_id: UUID
    correlation_id: UUID
    payment_intent_id: UUID
    attempt_number: int = Field(default=1, ge=1)
    idempotency_key: str = Field(min_length=8, max_length=128)
    provider: str = Field(default="PAYPAL_SANDBOX", max_length=64)
    paypal_order_id: str | None = Field(default=None, max_length=128)
    paypal_approval_url: str | None = Field(default=None, max_length=1000)
    buyer_approval: PayPalBuyerApproval | None = None
    verified_capture: VerifiedPayPalCapture | None = None
    state: PaymentState = PaymentState.CHECKOUT_READY
    failure_code: str | None = Field(default=None, max_length=128)
    failure_reason: str | None = Field(default=None, max_length=500)
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)

    @field_validator("created_at", "updated_at")
    @classmethod
    def _utc_dates(cls, v: datetime) -> datetime:
        return _normalize_utc(v)  # type: ignore[return-value]


class PaymentIntent(NexusBaseModel):
    id: UUID = Field(default_factory=uuid4)
    tenant_id: UUID
    correlation_id: UUID
    proposal_id: UUID
    agent_id: UUID
    passport_id: UUID
    merchant_id: UUID
    quote_snapshot_id: UUID
    quote_hash: str
    amount_minor: int = Field(gt=0)
    currency: str = Field(default="USD", min_length=3, max_length=3)
    state: PaymentState = PaymentState.CREATED
    idempotency_key: str = Field(min_length=8, max_length=128)
    authorization_decision_id: UUID | None = None
    approval_record_id: UUID | None = None
    reservation_id: UUID | None = None
    active_attempt_id: UUID | None = None
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)

    @field_validator("currency")
    @classmethod
    def _upper_currency(cls, v: str) -> str:
        return v.upper()

    @field_validator("created_at", "updated_at")
    @classmethod
    def _utc_dates(cls, v: datetime) -> datetime:
        return _normalize_utc(v)  # type: ignore[return-value]


class FinancialEvent(NexusBaseModel):
    id: UUID = Field(default_factory=uuid4)
    tenant_id: UUID
    correlation_id: UUID
    payment_intent_id: UUID | None = None
    sequence_number: int = Field(ge=1)
    event_type: FinancialEventType
    actor_type: str = Field(min_length=1, max_length=64)
    actor_id: str = Field(min_length=1, max_length=128)
    payload: dict[str, Any] = Field(default_factory=dict)
    previous_event_hash: str | None = Field(default=None, max_length=128)
    event_hash: str = Field(min_length=16, max_length=128)
    occurred_at: datetime = Field(default_factory=utc_now)

    @field_validator("occurred_at")
    @classmethod
    def _utc_occurred(cls, v: datetime) -> datetime:
        return _normalize_utc(v)  # type: ignore[return-value]


class EvidenceRecord(NexusBaseModel):
    id: UUID = Field(default_factory=uuid4)
    tenant_id: UUID
    correlation_id: UUID
    payment_intent_id: UUID | None = None
    dispute_case_id: UUID | None = None
    source_type: EvidenceSourceType
    source_ref: str = Field(min_length=1, max_length=255)
    title: str = Field(min_length=1, max_length=255)
    content: dict[str, Any] = Field(default_factory=dict)
    content_hash: str = Field(min_length=16, max_length=128)
    is_synthetic: bool = False
    collected_at: datetime = Field(default_factory=utc_now)

    @field_validator("collected_at")
    @classmethod
    def _utc_collected(cls, v: datetime) -> datetime:
        return _normalize_utc(v)  # type: ignore[return-value]


class ReplayTimelineEntry(NexusBaseModel):
    sequence_number: int = Field(ge=1)
    event_id: UUID
    event_type: FinancialEventType
    actor_type: str
    actor_id: str
    occurred_at: datetime
    summary: str
    evidence_ids: list[UUID] = Field(default_factory=list)
    previous_event_hash: str | None = Field(default=None, max_length=128)
    event_hash: str | None = Field(default=None, max_length=128)
    integrity_verified: bool = True

    @field_validator("occurred_at")
    @classmethod
    def _utc_occurred(cls, v: datetime) -> datetime:
        return _normalize_utc(v)  # type: ignore[return-value]


class ReplayRequest(NexusBaseModel):
    tenant_id: UUID
    correlation_id: UUID
    payment_intent: PaymentIntent
    proposal: PurchaseProposal
    quote_snapshot: QuoteSnapshot
    recorded_passport: SpendingPassport
    recorded_merchant: Merchant
    recorded_decision: AuthorizationDecision
    approval_record: ApprovalRecord | None = None
    policy_version: str = Field(default="policy-v1", max_length=64)
    events: list[FinancialEvent] = Field(default_factory=list)
    evidence_records: list[EvidenceRecord] = Field(default_factory=list)
    counterfactual_overrides: dict[str, Any] = Field(default_factory=dict)
    evaluation_time: datetime | None = None

    @field_validator("evaluation_time")
    @classmethod
    def _utc_eval(cls, v: datetime | None) -> datetime | None:
        return _normalize_utc(v)


class ReplayResult(NexusBaseModel):
    replay_id: UUID = Field(default_factory=uuid4)
    tenant_id: UUID
    correlation_id: UUID
    payment_intent_id: UUID
    policy_version: str
    timeline: list[ReplayTimelineEntry] = Field(default_factory=list)
    original_outcome: DecisionOutcome
    recomputed_outcome: DecisionOutcome
    original_reason_codes: list[DecisionReasonCode] = Field(default_factory=list)
    recomputed_reason_codes: list[DecisionReasonCode] = Field(default_factory=list)
    changed_constraints: list[str] = Field(default_factory=list)
    drift_detected: bool = False
    explanation: str = Field(min_length=1, max_length=2000)
    evidence_references: list[UUID] = Field(default_factory=list)
    missing_evidence: list[str] = Field(default_factory=list)
    anomalies: list[str] = Field(default_factory=list)
    integrity_valid: bool = True
    consistency_status: str = Field(
        pattern=r"^(CONSISTENT|DRIFT_DETECTED|INTEGRITY_FAILURE|INCOMPLETE_EVIDENCE)$"
    )
    executed_payment: bool = False
    replayed_at: datetime = Field(default_factory=utc_now)

    @field_validator("replayed_at")
    @classmethod
    def _utc_replayed(cls, v: datetime) -> datetime:
        return _normalize_utc(v)  # type: ignore[return-value]


class DisputeCase(NexusBaseModel):
    id: UUID = Field(default_factory=uuid4)
    tenant_id: UUID
    correlation_id: UUID
    payment_intent_id: UUID
    paypal_dispute_id: str | None = Field(default=None, max_length=128)
    source_type: DisputeSourceType = DisputeSourceType.SYNTHETIC_DEMO
    is_synthetic: bool = True
    reason: str = Field(min_length=1, max_length=255)
    buyer_claim: str = Field(min_length=1, max_length=2000)
    amount_minor: int = Field(gt=0)
    currency: str = Field(default="USD", min_length=3, max_length=3)
    status: DisputeStatus = DisputeStatus.OPEN
    evidence_ids: list[UUID] = Field(default_factory=list)
    human_approved_for_submission: bool = False
    approved_by: str | None = Field(default=None, max_length=128)
    approved_at: datetime | None = None
    response_payload_hash: str | None = Field(default=None, max_length=128)
    response_due_by: datetime | None = None
    resolved_at: datetime | None = None
    resolution_outcome: str | None = Field(default=None, max_length=128)
    external_status: str | None = Field(default=None, max_length=128)
    opened_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)

    @field_validator("currency")
    @classmethod
    def _upper_currency(cls, v: str) -> str:
        return v.upper()

    @field_validator("approved_at", "response_due_by", "resolved_at", "opened_at", "updated_at")
    @classmethod
    def _utc_dates(cls, v: datetime | None) -> datetime | None:
        return _normalize_utc(v)


class DisputeEvidenceCitation(NexusBaseModel):
    claim: str = Field(min_length=1, max_length=500)
    evidence_id: UUID
    verbatim_excerpt: str = Field(min_length=1, max_length=500)
    verified: bool = True


class DisputeAnalysis(NexusBaseModel):
    id: UUID = Field(default_factory=uuid4)
    tenant_id: UUID
    correlation_id: UUID
    dispute_case_id: UUID
    is_synthetic: bool = True
    recommendation: DisputeRecommendation
    confidence_score: float = Field(ge=0.0, le=1.0)
    agent_authorized: bool
    agent_followed_policy: bool
    merchant_fulfilled_order: bool | None = None
    contradictions: list[str] = Field(default_factory=list)
    missing_evidence: list[str] = Field(default_factory=list)
    citations: list[DisputeEvidenceCitation] = Field(default_factory=list)
    rejected_claims: list[str] = Field(default_factory=list)
    recommended_actions: list[str] = Field(default_factory=list)
    grounded_summary: str = Field(min_length=1, max_length=4000)
    draft_response_text: str = Field(min_length=1, max_length=4000)
    requires_human_approval: bool = True
    generated_with_llm: bool = False
    llm_provider: str | None = Field(default=None, max_length=64)
    llm_model: str | None = Field(default=None, max_length=128)
    analyzed_at: datetime = Field(default_factory=utc_now)

    @field_validator("analyzed_at")
    @classmethod
    def _utc_analyzed(cls, v: datetime) -> datetime:
        return _normalize_utc(v)  # type: ignore[return-value]


# ---------------------------------------------------------------------------
# Multi-Rail, Protocol & Token Provenance Models (AP2 / TAP / x402 / Stripe)
# ---------------------------------------------------------------------------

class AP2CheckoutMandate(NexusBaseModel):
    """Google AP2 Checkout Mandate specification for autonomous agent purchasing."""

    mandate_id: UUID = Field(default_factory=uuid4)
    tenant_id: UUID
    correlation_id: UUID
    agent_id: UUID
    merchant_id: UUID
    amount_minor: int = Field(gt=0)
    currency: str = Field(default="USD", min_length=3, max_length=3)
    line_items: list[dict[str, Any]] = Field(default_factory=list)
    signature: str = Field(min_length=8, max_length=512)
    expires_at: datetime
    created_at: datetime = Field(default_factory=utc_now)


class AP2PaymentMandate(NexusBaseModel):
    """Google AP2 Payment Mandate executing authorized settlement."""

    mandate_id: UUID = Field(default_factory=uuid4)
    checkout_mandate_id: UUID
    tenant_id: UUID
    correlation_id: UUID
    payment_intent_id: UUID
    provider: str = Field(default="PAYPAL_SANDBOX", max_length=64)
    capture_mode: str = Field(default="AUTOMATIC", max_length=32)
    amount_minor: int = Field(gt=0)
    currency: str = Field(default="USD", min_length=3, max_length=3)
    signature: str = Field(min_length=8, max_length=512)
    authorized_at: datetime = Field(default_factory=utc_now)


class AP2MandatePayload(NexusBaseModel):
    """Normalized Agent Payments Protocol (AP2) mandate payload."""

    mandate_id: str = Field(min_length=1, max_length=128)
    tenant_id: UUID
    agent_id: UUID
    passport_id: UUID | None = None
    merchant_id: UUID | None = None
    max_amount_minor: int = Field(gt=0)
    currency: str = Field(default="USD", min_length=3, max_length=3)
    scope: list[str] = Field(default_factory=list)
    expires_at: datetime
    signature: str = Field(min_length=8, max_length=512)
    issued_at: datetime = Field(default_factory=utc_now)

    @field_validator("currency")
    @classmethod
    def _upper_currency(cls, v: str) -> str:
        return v.upper()

    @field_validator("expires_at", "issued_at")
    @classmethod
    def _utc_dates(cls, v: datetime) -> datetime:
        return _normalize_utc(v)  # type: ignore[return-value]


class TokenProvenanceProof(NexusBaseModel):
    """Visa TAP / Mastercard Agent Pay token provenance verification proof."""

    token_id: UUID = Field(default_factory=uuid4)
    tenant_id: UUID
    network: str = Field(pattern=r"^(VISA_TAP|MASTERCARD_AGENT_PAY|AMEX_EXPRESS|DISCOVER)$")
    token_reference: str = Field(min_length=4, max_length=128)
    assurance_level: str = Field(default="HIGH", max_length=32)
    agent_fingerprint: str = Field(min_length=8, max_length=128)
    device_fingerprint: str = Field(min_length=8, max_length=128)
    signature: str = Field(min_length=8, max_length=512)
    verified: bool = True
    created_at: datetime = Field(default_factory=utc_now)


class TAPTokenPayload(NexusBaseModel):
    """Normalized Trusted Agent Protocol (TAP) authorization token payload."""

    token_id: str = Field(min_length=1, max_length=128)
    tenant_id: UUID
    agent_id: UUID
    merchant_domain: str = Field(min_length=1, max_length=255)
    amount_minor: int = Field(gt=0)
    currency: str = Field(default="USD", min_length=3, max_length=3)
    nonce: str = Field(min_length=8, max_length=128)
    expires_at: datetime
    signature: str = Field(min_length=8, max_length=512)
    issued_at: datetime = Field(default_factory=utc_now)

    @field_validator("currency")
    @classmethod
    def _upper_currency(cls, v: str) -> str:
        return v.upper()

    @field_validator("expires_at", "issued_at")
    @classmethod
    def _utc_dates(cls, v: datetime) -> datetime:
        return _normalize_utc(v)  # type: ignore[return-value]


class X402SettlementProof(NexusBaseModel):
    """Normalized HTTP 402 / x402 on-chain settlement proof."""

    proof_id: str = Field(default_factory=lambda: str(uuid4()), min_length=1, max_length=128)
    tenant_id: UUID
    correlation_id: UUID | None = None
    payment_intent_id: UUID | None = None
    network: str = Field(default="base-sepolia", min_length=1, max_length=64)
    chain_id: int | None = None
    asset: str = Field(default="USDC", min_length=1, max_length=32)
    amount_minor: int = Field(default=0, ge=0)
    amount_units: str | None = None
    tx_hash: str = Field(default="", max_length=256)
    transaction_hash: str | None = None
    token_address: str | None = None
    payer_address: str = Field(default="", max_length=256)
    payee_address: str = Field(default="", max_length=256)
    recipient_address: str | None = None
    block_number: int | None = None
    verified: bool = True
    settled_at: datetime = Field(default_factory=utc_now)

    @field_validator("settled_at")
    @classmethod
    def _utc_settled(cls, v: datetime) -> datetime:
        return _normalize_utc(v)  # type: ignore[return-value]

    @model_validator(mode="after")
    def _sync_fields(self) -> X402SettlementProof:
        if self.transaction_hash and not self.tx_hash:
            self.tx_hash = self.transaction_hash
        elif self.tx_hash and not self.transaction_hash:
            self.transaction_hash = self.tx_hash
        if self.recipient_address and not self.payee_address:
            self.payee_address = self.recipient_address
        elif self.payee_address and not self.recipient_address:
            self.recipient_address = self.payee_address
        return self


class StripePaymentIntentPayload(NexusBaseModel):
    """Stripe PaymentIntent REST representation."""

    payment_intent_id: str = Field(min_length=4, max_length=128)
    tenant_id: UUID
    client_secret: str = Field(min_length=4, max_length=255)
    amount_minor: int = Field(gt=0)
    currency: str = Field(default="USD", min_length=3, max_length=3)
    status: str = Field(max_length=64)
    payment_method_types: list[str] = Field(default_factory=lambda: ["card"])
    capture_method: str = Field(default="automatic", max_length=32)
    metadata: dict[str, Any] = Field(default_factory=dict)


class StripeSharedPaymentToken(NexusBaseModel):
    """Stripe Shared Payment Token (SPT) for agent delegated payments."""

    token_id: UUID = Field(default_factory=uuid4)
    tenant_id: UUID
    customer_id: str = Field(min_length=4, max_length=128)
    merchant_account_id: str = Field(min_length=4, max_length=128)
    payment_intent_id: UUID | None = None
    token_hash: str = Field(min_length=8, max_length=128)
    status: str = Field(default="ACTIVE", pattern=r"^(ACTIVE|CONSUMED|REVOKED|EXPIRED)$")
    expires_at: datetime
    created_at: datetime = Field(default_factory=utc_now)


class StripeSmartDisputePayload(NexusBaseModel):
    """Stripe Smart Disputes integration model."""

    dispute_id: str = Field(min_length=4, max_length=128)
    tenant_id: UUID
    payment_intent_id: str = Field(min_length=4, max_length=128)
    amount_minor: int = Field(gt=0)
    currency: str = Field(default="USD", min_length=3, max_length=3)
    reason: str = Field(max_length=128)
    status: str = Field(max_length=64)
    evidence_due_by: datetime | None = None
    evidence_submitted: bool = False


class StripeEventEnvelope(NexusBaseModel):
    """Normalized Stripe webhook / Radar / Dispute event envelope."""

    event_id: str = Field(min_length=1, max_length=128)
    tenant_id: UUID
    event_type: str = Field(min_length=1, max_length=128)
    api_version: str | None = Field(default=None, max_length=32)
    payment_intent_ref: str | None = Field(default=None, max_length=128)
    amount_minor: int | None = Field(default=None, ge=0)
    currency: str | None = Field(default=None, min_length=3, max_length=3)
    payload: dict[str, Any] = Field(default_factory=dict)
    received_at: datetime = Field(default_factory=utc_now)

    @field_validator("currency")
    @classmethod
    def _upper_currency(cls, v: str | None) -> str | None:
        return v.upper() if v is not None else None

    @field_validator("received_at")
    @classmethod
    def _utc_received(cls, v: datetime) -> datetime:
        return _normalize_utc(v)  # type: ignore[return-value]


class DeflectionAlert(NexusBaseModel):
    """Pre-dispute / chargeback deflection alert emitted by risk or forensics checks."""

    id: UUID = Field(default_factory=uuid4)
    tenant_id: UUID
    correlation_id: UUID
    payment_intent_id: UUID | None = None
    dispute_case_id: UUID | None = None
    alert_type: str = Field(min_length=1, max_length=64)
    severity: str = Field(default="MEDIUM", pattern=r"^(LOW|MEDIUM|HIGH|CRITICAL)$")
    reason: str = Field(min_length=1, max_length=1000)
    recommended_action: str = Field(min_length=1, max_length=500)
    acknowledged: bool = False
    created_at: datetime = Field(default_factory=utc_now)

    @field_validator("created_at")
    @classmethod
    def _utc_created(cls, v: datetime) -> datetime:
        return _normalize_utc(v)  # type: ignore[return-value]

