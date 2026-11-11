"""Test fixtures for GhostPay Milestone G1 test suite."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

import pytest
from contracts import (
    AuthorizationDecision,
    DecisionOutcome,
    DecisionReasonCode,
    EvidenceRecord,
    EvidenceSourceType,
    FinancialEvent,
    FinancialEventType,
    Merchant,
    PassportStatus,
    PaymentIntent,
    PaymentState,
    QuoteSnapshot,
    SpendingPassport,
    compute_payload_hash,
    compute_quote_hash,
)
from contracts.fixtures import (
    AGENT_PROCUREMENT_ID,
    MERCHANT_SANDBOX_CLOUD_ID,
    PASSPORT_DEFAULT_ID,
    TENANT_ALPHA_ID,
    build_authorized_39_purchase_fixture,
    build_base_entities,
)
from security import compute_financial_event_hash

from ghostpay.domain.models import PaymentTrace
from ghostpay.domain.service import GhostPayService
from ghostpay.ingestion.adapter import TraceIngestionAdapter
from ghostpay.integrations.guardian import GuardianTraceAdapter
from ghostpay.testing import build_baseline_history


@pytest.fixture
def base_entities() -> dict[str, Any]:
    return build_base_entities()


@pytest.fixture
def authorized_39_fixture() -> dict[str, Any]:
    return build_authorized_39_purchase_fixture()


@pytest.fixture
def service() -> GhostPayService:
    return GhostPayService()


@pytest.fixture
def ingestion_adapter() -> TraceIngestionAdapter:
    return TraceIngestionAdapter()


@pytest.fixture
def guardian_adapter() -> GuardianTraceAdapter:
    return GuardianTraceAdapter()


def make_test_trace(
    *,
    tenant_id: UUID = TENANT_ALPHA_ID,
    agent_id: UUID = AGENT_PROCUREMENT_ID,
    amount_minor: int = 3900,
    merchant_id: UUID = MERCHANT_SANDBOX_CLOUD_ID,
    created_at: datetime | None = None,
    outcome: DecisionOutcome = DecisionOutcome.ALLOW,
    state: PaymentState = PaymentState.SUCCEEDED,
    with_events: bool = True,
    tampered_event: bool = False,
    missing_sequence: bool = False,
) -> PaymentTrace:
    t_time = created_at or datetime.now(UTC)
    intent_id = uuid4()
    corr_id = uuid4()

    proposal_id = uuid4()
    line_items = [{"sku": "SKU-001", "name": "Cloud VM", "amount_minor": amount_minor, "quantity": 1}]
    q_hash = compute_quote_hash(
        merchant_id=merchant_id,
        amount_minor=amount_minor,
        currency="USD",
        line_items=line_items,
    )

    quote = QuoteSnapshot(
        id=uuid4(),
        tenant_id=tenant_id,
        correlation_id=corr_id,
        proposal_id=proposal_id,
        merchant_id=merchant_id,
        amount_minor=amount_minor,
        currency="USD",
        line_items=line_items,
        quote_hash=q_hash,
        expires_at=t_time + timedelta(hours=1),
        created_at=t_time,
    )

    decision = AuthorizationDecision(
        id=uuid4(),
        tenant_id=tenant_id,
        correlation_id=corr_id,
        payment_intent_id=intent_id,
        proposal_id=proposal_id,
        passport_id=PASSPORT_DEFAULT_ID,
        quote_snapshot_id=quote.id,
        quote_hash=q_hash,
        outcome=outcome,
        reason_codes=[DecisionReasonCode.OK_WITHIN_POLICY] if outcome == DecisionOutcome.ALLOW else [DecisionReasonCode.DENIED_EXCEEDS_PER_TX_LIMIT],
        explanation="Test decision",
        decided_at=t_time,
    )

    passport = SpendingPassport(
        id=PASSPORT_DEFAULT_ID,
        tenant_id=tenant_id,
        agent_id=agent_id,
        currency="USD",
        total_budget_minor=10000,
        spent_minor=0,
        reserved_minor=0,
        per_tx_limit_minor=7500,
        daily_limit_minor=10000,
        human_approval_threshold_minor=5000,
        allowed_merchant_ids=[MERCHANT_SANDBOX_CLOUD_ID],
        allowed_categories=["SOFTWARE", "CLOUD_INFRA"],
        status=PassportStatus.ACTIVE,
        expires_at=t_time + timedelta(days=30),
        created_at=t_time,
    )

    merchant = Merchant(
        id=merchant_id,
        tenant_id=tenant_id,
        name="CloudCompute Sandbox Store",
        domain="sandbox.example.com",
        category="SOFTWARE",
        is_allowlisted=True,
        created_at=t_time,
    )

    intent = PaymentIntent(
        id=intent_id,
        tenant_id=tenant_id,
        correlation_id=corr_id,
        proposal_id=proposal_id,
        agent_id=agent_id,
        passport_id=passport.id,
        merchant_id=merchant.id,
        quote_snapshot_id=quote.id,
        quote_hash=q_hash,
        amount_minor=amount_minor,
        currency="USD",
        state=state,
        idempotency_key=f"idem-{uuid4().hex[:12]}",
        created_at=t_time,
        updated_at=t_time,
    )

    events: list[FinancialEvent] = []
    if with_events:
        # Event 1: PROPOSAL_CREATED
        ev1_id = uuid4()
        ev1_time = t_time
        ev1_payload = {"amount_minor": amount_minor, "merchant_id": str(merchant_id)}
        ev1_hash = compute_financial_event_hash(
            event_id=ev1_id,
            tenant_id=tenant_id,
            correlation_id=corr_id,
            payment_intent_id=intent_id,
            sequence_number=1,
            event_type=FinancialEventType.PROPOSAL_CREATED.value,
            actor_type="AGENT",
            actor_id=str(agent_id),
            payload=ev1_payload,
            previous_event_hash=None,
            occurred_at_iso=ev1_time.isoformat(),
        )
        events.append(
            FinancialEvent(
                id=ev1_id,
                tenant_id=tenant_id,
                correlation_id=corr_id,
                payment_intent_id=intent_id,
                sequence_number=1,
                event_type=FinancialEventType.PROPOSAL_CREATED,
                actor_type="AGENT",
                actor_id=str(agent_id),
                payload=ev1_payload,
                previous_event_hash=None,
                event_hash=ev1_hash,
                occurred_at=ev1_time,
            )
        )

        # Event 2: POLICY_EVALUATED (or sequence 3 if missing_sequence is True)
        seq2 = 3 if missing_sequence else 2
        ev2_id = uuid4()
        ev2_time = t_time + timedelta(seconds=1)
        ev2_payload = {"outcome": outcome.value, "quote_hash": q_hash}
        ev2_hash = compute_financial_event_hash(
            event_id=ev2_id,
            tenant_id=tenant_id,
            correlation_id=corr_id,
            payment_intent_id=intent_id,
            sequence_number=seq2,
            event_type=FinancialEventType.POLICY_EVALUATED.value,
            actor_type="POLICY_ENGINE",
            actor_id="policy-v1",
            payload=ev2_payload,
            previous_event_hash=ev1_hash,
            occurred_at_iso=ev2_time.isoformat(),
        )
        if tampered_event:
            ev2_hash = "tampered-hash-00000000000000000000"

        events.append(
            FinancialEvent(
                id=ev2_id,
                tenant_id=tenant_id,
                correlation_id=corr_id,
                payment_intent_id=intent_id,
                sequence_number=seq2,
                event_type=FinancialEventType.POLICY_EVALUATED,
                actor_type="POLICY_ENGINE",
                actor_id="policy-v1",
                payload=ev2_payload,
                previous_event_hash=ev1_hash,
                event_hash=ev2_hash,
                occurred_at=ev2_time,
            )
        )

    ev_record = EvidenceRecord(
        id=uuid4(),
        tenant_id=tenant_id,
        correlation_id=corr_id,
        payment_intent_id=intent_id,
        source_type=EvidenceSourceType.QUOTE,
        source_ref=f"quote:{quote.id}",
        title="Quote Snapshot Evidence",
        content={"amount_minor": amount_minor, "merchant_id": str(merchant_id)},
        content_hash=compute_payload_hash({"amount_minor": amount_minor, "merchant_id": str(merchant_id)}),
        collected_at=t_time,
    )

    integrity_status = "TAMPERED" if tampered_event else ("INCOMPLETE" if missing_sequence else "VALID")

    return PaymentTrace(
        trace_id=uuid4(),
        tenant_id=tenant_id,
        agent_id=agent_id,
        payment_intent_id=intent_id,
        ordered_events=events,
        quote_snapshot=quote,
        authorization_evidence=[ev_record],
        recorded_decision=decision,
        recorded_passport=passport,
        recorded_merchant=merchant,
        payment_intent=intent,
        integrity_status=integrity_status,
        created_at=t_time,
    )


@pytest.fixture
def agent_baseline_history() -> list[PaymentTrace]:
    """10 chronological legitimate traces for AGENT_PROCUREMENT_ID on MERCHANT_SANDBOX_CLOUD_ID."""
    return build_baseline_history()
