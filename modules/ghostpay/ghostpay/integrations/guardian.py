"""Adapter consuming AgentPay Guardian financial evidence safely and read-only."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from contracts import (
    ApprovalRecord,
    AuthorizationDecision,
    EvidenceRecord,
    FinancialEvent,
    Merchant,
    PaymentIntent,
    QuoteSnapshot,
    SpendingPassport,
)
from ghostpay.domain.models import PaymentTrace
from ghostpay.ingestion.adapter import TraceIngestionAdapter


class GuardianTraceAdapter:
    """Consumes Guardian records and builds normalized PaymentTrace objects."""

    def __init__(self, adapter: TraceIngestionAdapter | None = None) -> None:
        self.adapter = adapter or TraceIngestionAdapter()

    def from_guardian_records(
        self,
        *,
        intent: PaymentIntent,
        proposal_quote: QuoteSnapshot,
        passport: SpendingPassport,
        merchant: Merchant,
        events: list[FinancialEvent],
        evidence_records: list[EvidenceRecord] | None = None,
        decision: AuthorizationDecision | None = None,
        approval: ApprovalRecord | None = None,
        policy_version: str = "policy-v1",
    ) -> PaymentTrace:
        """Create a validated PaymentTrace from Guardian domain objects."""
        return self.adapter.build_trace(
            tenant_id=intent.tenant_id,
            agent_id=intent.agent_id,
            payment_intent_id=intent.id,
            events=events,
            quote_snapshot=proposal_quote,
            evidence_records=evidence_records or [],
            recorded_decision=decision,
            recorded_passport=passport,
            recorded_merchant=merchant,
            approval_record=approval,
            payment_intent=intent,
            policy_version=policy_version,
        )

