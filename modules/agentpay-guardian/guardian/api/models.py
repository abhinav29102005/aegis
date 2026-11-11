"""Pydantic API models for the Guardian FastAPI endpoints."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

from contracts import (
    ApprovalRecord,
    AuthorizationDecision,
    PaymentAttempt,
    PaymentIntent,
    PurchaseProposal,
    QuoteSnapshot,
    compute_quote_hash,
)
from pydantic import BaseModel, Field


def _utc_now() -> datetime:
    return datetime.now(UTC)


class SubmitProposalRequest(BaseModel):
    tenant_id: UUID
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
    quote_expires_in_seconds: int = Field(default=1800, ge=60, le=86400)

    def to_proposal_and_quote(
        self,
        correlation_id: UUID | None = None,
    ) -> tuple[PurchaseProposal, QuoteSnapshot]:
        corr_id = correlation_id or uuid4()
        prop_id = uuid4()
        now = _utc_now()
        q_hash = compute_quote_hash(
            merchant_id=self.merchant_id,
            amount_minor=self.amount_minor,
            currency=self.currency.upper(),
            line_items=self.line_items,
        )
        quote = QuoteSnapshot(
            id=uuid4(),
            tenant_id=self.tenant_id,
            correlation_id=corr_id,
            proposal_id=prop_id,
            merchant_id=self.merchant_id,
            amount_minor=self.amount_minor,
            currency=self.currency.upper(),
            line_items=self.line_items,
            quote_hash=q_hash,
            expires_at=now + timedelta(seconds=self.quote_expires_in_seconds),
            created_at=now,
        )
        proposal = PurchaseProposal(
            id=prop_id,
            tenant_id=self.tenant_id,
            correlation_id=corr_id,
            agent_id=self.agent_id,
            passport_id=self.passport_id,
            merchant_id=self.merchant_id,
            merchant_name=self.merchant_name,
            merchant_category=self.merchant_category,
            amount_minor=self.amount_minor,
            currency=self.currency.upper(),
            item_summary=self.item_summary,
            line_items=self.line_items,
            rationale=self.rationale,
            idempotency_key=self.idempotency_key,
            created_at=now,
        )
        return proposal, quote


class HumanApprovalRequest(BaseModel):
    approver_id: str = Field(min_length=1, max_length=128)
    approved: bool = True
    comment: str | None = Field(default=None, max_length=500)


class InitiateCheckoutRequest(BaseModel):
    attempt_number: int = Field(default=1, ge=1)
    idempotency_key: str | None = None
    return_url: str | None = None
    cancel_url: str | None = None


class BuyerApprovedRequest(BaseModel):
    attempt_id: UUID
    payer_id: str | None = None


class BuyerDeclinedRequest(BaseModel):
    attempt_id: UUID
    reason: str = Field(default="Buyer cancelled checkout", max_length=500)


class ReconcileRequest(BaseModel):
    attempt_id: UUID


class CaptureRequest(BaseModel):
    attempt_id: UUID


class ProposalSubmissionResponse(BaseModel):
    payment_intent: PaymentIntent
    decision: AuthorizationDecision


class CheckoutResponse(BaseModel):
    payment_intent: PaymentIntent
    attempt: PaymentAttempt
    approval_url: str | None = None


class ApprovalActionResponse(BaseModel):
    payment_intent: PaymentIntent
    approval: ApprovalRecord
