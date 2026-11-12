"""Pydantic API models for GhostPay endpoints."""

from __future__ import annotations

from uuid import UUID

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
    SpendingPassport,
)
from pydantic import BaseModel, Field

from ghostpay.timemachine.policies import CounterfactualPolicy


class IngestTraceRequest(BaseModel):
    tenant_id: UUID
    agent_id: UUID
    payment_intent_id: UUID
    events: list[FinancialEvent] = Field(default_factory=list)
    quote_snapshot: QuoteSnapshot | None = None
    evidence_records: list[EvidenceRecord] = Field(default_factory=list)
    recorded_decision: AuthorizationDecision | None = None
    recorded_passport: SpendingPassport | None = None
    recorded_merchant: Merchant | None = None
    approval_record: ApprovalRecord | None = None
    payment_intent: PaymentIntent | None = None
    proposal: PurchaseProposal | None = None
    policy_version: str = Field(default="policy-v1", max_length=64)
    strict_integrity: bool = False


class ReplayCompareRequest(BaseModel):
    replay_request: ReplayRequest
    policies: list[CounterfactualPolicy] = Field(min_length=1)


class AnalyzeAgentRequest(BaseModel):
    target_trace_id: UUID


class CreateInvestigationRequest(BaseModel):
    trace_id: UUID
    counterfactual_policies: list[CounterfactualPolicy] | None = None
