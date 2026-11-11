"""Contract-compliant deterministic fixtures for Guardian, GhostPay, and DisputeOS."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import UUID

from contracts.enums import (
    ApprovalStatus,
    DecisionOutcome,
    DecisionReasonCode,
    DisputeSourceType,
    DisputeStatus,
    EvidenceSourceType,
    FinancialEventType,
    PassportStatus,
    PaymentState,
    ReservationStatus,
)
from contracts.hashing import compute_payload_hash, compute_quote_hash
from contracts.models import (
    AgentIdentity,
    ApprovalRecord,
    AuthorizationDecision,
    BudgetReservation,
    DisputeCase,
    EvidenceRecord,
    FinancialEvent,
    Merchant,
    PayPalBuyerApproval,
    PaymentAttempt,
    PaymentIntent,
    PurchaseProposal,
    QuoteSnapshot,
    ReplayRequest,
    SpendingPassport,
    Tenant,
    VerifiedPayPalCapture,
)

BASE_TIME = datetime(2026, 11, 10, 12, 0, 0, tzinfo=timezone.utc)

TENANT_ALPHA_ID = UUID("00000000-0000-4000-8000-000000000001")
TENANT_BETA_ID = UUID("00000000-0000-4000-8000-000000000002")
AGENT_PROCUREMENT_ID = UUID("11111111-1111-4000-8000-000000000001")
PASSPORT_DEFAULT_ID = UUID("22222222-2222-4000-8000-000000000001")
MERCHANT_SANDBOX_CLOUD_ID = UUID("33333333-3333-4000-8000-000000000001")
MERCHANT_UNKNOWN_ID = UUID("33333333-3333-4000-8000-000000000099")


def _chain_event(
    *,
    event_id: UUID,
    tenant_id: UUID,
    correlation_id: UUID,
    payment_intent_id: UUID,
    sequence_number: int,
    event_type: FinancialEventType,
    actor_type: str,
    actor_id: str,
    payload: dict[str, Any],
    previous_event_hash: str | None,
    occurred_at: datetime,
) -> FinancialEvent:
    event_hash = compute_payload_hash({
        "id": str(event_id),
        "tenant_id": str(tenant_id),
        "correlation_id": str(correlation_id),
        "payment_intent_id": str(payment_intent_id),
        "sequence_number": sequence_number,
        "event_type": event_type.value,
        "actor_type": actor_type,
        "actor_id": actor_id,
        "payload": payload,
        "previous_event_hash": previous_event_hash,
        "occurred_at": occurred_at.isoformat(),
    })
    return FinancialEvent(
        id=event_id,
        tenant_id=tenant_id,
        correlation_id=correlation_id,
        payment_intent_id=payment_intent_id,
        sequence_number=sequence_number,
        event_type=event_type,
        actor_type=actor_type,
        actor_id=actor_id,
        payload=payload,
        previous_event_hash=previous_event_hash,
        event_hash=event_hash,
        occurred_at=occurred_at,
    )


def build_base_entities() -> dict[str, Any]:
    tenant = Tenant(
        id=TENANT_ALPHA_ID,
        name="Acme Commerce Labs",
        slug="acme-commerce",
        created_at=BASE_TIME,
    )
    agent = AgentIdentity(
        id=AGENT_PROCUREMENT_ID,
        tenant_id=TENANT_ALPHA_ID,
        name="Nexus Procurement Copilot",
        purpose="Automated SaaS and developer supply procurement within deterministic budgets",
        framework="langgraph",
        status="ACTIVE",
        public_fingerprint="fp-agent-nexus-001",
        created_at=BASE_TIME,
    )
    approved_merchant = Merchant(
        id=MERCHANT_SANDBOX_CLOUD_ID,
        tenant_id=TENANT_ALPHA_ID,
        name="CloudCompute Sandbox Store",
        domain="sandbox-store.cloudcompute.example",
        category="SOFTWARE",
        paypal_merchant_id="SB_MERCHANT_001",
        is_allowlisted=True,
        is_sandbox_verified=True,
        created_at=BASE_TIME,
    )
    unknown_merchant = Merchant(
        id=MERCHANT_UNKNOWN_ID,
        tenant_id=TENANT_ALPHA_ID,
        name="Unverified Gadget Bazaar",
        domain="unverified-bazaar.example",
        category="HARDWARE",
        paypal_merchant_id=None,
        is_allowlisted=False,
        is_sandbox_verified=False,
        created_at=BASE_TIME,
    )
    passport = SpendingPassport(
        id=PASSPORT_DEFAULT_ID,
        tenant_id=TENANT_ALPHA_ID,
        agent_id=AGENT_PROCUREMENT_ID,
        policy_version="policy-v1",
        currency="USD",
        total_budget_minor=10000,  # $100.00
        spent_minor=0,
        reserved_minor=0,
        per_tx_limit_minor=7500,  # $75.00
        daily_limit_minor=10000,  # $100.00
        human_approval_threshold_minor=5000,  # $50.00
        allowed_merchant_ids=[MERCHANT_SANDBOX_CLOUD_ID],
        allowed_categories=["SOFTWARE", "CLOUD_INFRA"],
        allow_unknown_merchants=False,
        status=PassportStatus.ACTIVE,
        expires_at=BASE_TIME + timedelta(days=30),
        created_at=BASE_TIME,
    )
    return {
        "tenant": tenant,
        "agent": agent,
        "approved_merchant": approved_merchant,
        "unknown_merchant": unknown_merchant,
        "passport": passport,
    }


def build_authorized_39_purchase_fixture() -> dict[str, Any]:
    """Demo A / Contract Fixture: Authorized $39.00 purchase under $100.00 budget."""
    base = build_base_entities()
    corr_id = UUID("aaaa1111-1111-4000-8000-000000000001")
    proposal_id = UUID("aaaa2222-2222-4000-8000-000000000001")
    quote_id = UUID("aaaa3333-3333-4000-8000-000000000001")
    intent_id = UUID("aaaa4444-4444-4000-8000-000000000001")
    decision_id = UUID("aaaa5555-5555-4000-8000-000000000001")
    reservation_id = UUID("aaaa6666-6666-4000-8000-000000000001")
    attempt_id = UUID("aaaa7777-7777-4000-8000-000000000001")

    line_items = [{"sku": "API-PRO-MO", "name": "CloudCompute Monthly API Tier", "qty": 1, "unit_amount_minor": 3900}]
    q_hash = compute_quote_hash(
        merchant_id=MERCHANT_SANDBOX_CLOUD_ID,
        amount_minor=3900,
        currency="USD",
        line_items=line_items,
    )

    proposal = PurchaseProposal(
        id=proposal_id,
        tenant_id=TENANT_ALPHA_ID,
        correlation_id=corr_id,
        agent_id=AGENT_PROCUREMENT_ID,
        passport_id=PASSPORT_DEFAULT_ID,
        merchant_id=MERCHANT_SANDBOX_CLOUD_ID,
        merchant_name="CloudCompute Sandbox Store",
        merchant_category="SOFTWARE",
        amount_minor=3900,
        currency="USD",
        item_summary="CloudCompute Monthly API Tier ($39.00)",
        line_items=line_items,
        rationale="Renew monthly API tier required by analytics pipeline",
        idempotency_key="idem-demo-a-3900-001",
        created_at=BASE_TIME + timedelta(minutes=1),
    )
    quote = QuoteSnapshot(
        id=quote_id,
        tenant_id=TENANT_ALPHA_ID,
        correlation_id=corr_id,
        proposal_id=proposal_id,
        merchant_id=MERCHANT_SANDBOX_CLOUD_ID,
        amount_minor=3900,
        currency="USD",
        line_items=line_items,
        quote_hash=q_hash,
        expires_at=BASE_TIME + timedelta(minutes=31),
        created_at=BASE_TIME + timedelta(minutes=1),
    )
    decision = AuthorizationDecision(
        id=decision_id,
        tenant_id=TENANT_ALPHA_ID,
        correlation_id=corr_id,
        payment_intent_id=intent_id,
        proposal_id=proposal_id,
        passport_id=PASSPORT_DEFAULT_ID,
        quote_snapshot_id=quote_id,
        quote_hash=q_hash,
        policy_version="policy-v1",
        outcome=DecisionOutcome.ALLOW,
        reason_codes=[DecisionReasonCode.OK_WITHIN_POLICY],
        violated_constraints=[],
        requires_human_approval=False,
        explanation="Amount $39.00 is within $75.00 per-tx limit and $100.00 passport budget; merchant is allowlisted.",
        policy_inputs={
            "amount_minor": 3900,
            "available_budget_minor": 10000,
            "per_tx_limit_minor": 7500,
            "merchant_allowlisted": True,
        },
        decided_at=BASE_TIME + timedelta(minutes=1, seconds=2),
    )
    reservation = BudgetReservation(
        id=reservation_id,
        tenant_id=TENANT_ALPHA_ID,
        correlation_id=corr_id,
        passport_id=PASSPORT_DEFAULT_ID,
        payment_intent_id=intent_id,
        amount_minor=3900,
        currency="USD",
        status=ReservationStatus.CAPTURED,
        expires_at=BASE_TIME + timedelta(minutes=31),
        created_at=BASE_TIME + timedelta(minutes=1, seconds=3),
        updated_at=BASE_TIME + timedelta(minutes=2),
    )
    attempt = PaymentAttempt(
        id=attempt_id,
        tenant_id=TENANT_ALPHA_ID,
        correlation_id=corr_id,
        payment_intent_id=intent_id,
        attempt_number=1,
        idempotency_key="idem-demo-a-3900-001",
        provider="PAYPAL_SANDBOX",
        paypal_order_id="PAYPAL-ORDER-DEMO-A-001",
        buyer_approval=PayPalBuyerApproval(
            paypal_order_id="PAYPAL-ORDER-DEMO-A-001",
            payer_id="SB_BUYER_001",
            buyer_status="APPROVED",
            approved_at=BASE_TIME + timedelta(minutes=1, seconds=45),
        ),
        verified_capture=VerifiedPayPalCapture(
            paypal_order_id="PAYPAL-ORDER-DEMO-A-001",
            paypal_capture_id="PAYPAL-CAP-DEMO-A-001",
            paypal_status="COMPLETED",
            verified_amount_minor=3900,
            verified_currency="USD",
            verification_hash=compute_payload_hash({"capture_id": "PAYPAL-CAP-DEMO-A-001", "status": "COMPLETED", "amount_minor": 3900}),
            verified_at=BASE_TIME + timedelta(minutes=2),
        ),
        state=PaymentState.SUCCEEDED,
        created_at=BASE_TIME + timedelta(minutes=1, seconds=5),
        updated_at=BASE_TIME + timedelta(minutes=2),
    )
    intent = PaymentIntent(
        id=intent_id,
        tenant_id=TENANT_ALPHA_ID,
        correlation_id=corr_id,
        proposal_id=proposal_id,
        agent_id=AGENT_PROCUREMENT_ID,
        passport_id=PASSPORT_DEFAULT_ID,
        merchant_id=MERCHANT_SANDBOX_CLOUD_ID,
        quote_snapshot_id=quote_id,
        quote_hash=q_hash,
        amount_minor=3900,
        currency="USD",
        state=PaymentState.SUCCEEDED,
        idempotency_key="idem-demo-a-3900-001",
        authorization_decision_id=decision_id,
        reservation_id=reservation_id,
        active_attempt_id=attempt_id,
        created_at=BASE_TIME + timedelta(minutes=1),
        updated_at=BASE_TIME + timedelta(minutes=2),
    )

    e1 = _chain_event(
        event_id=UUID("aaaa8888-0001-4000-8000-000000000001"),
        tenant_id=TENANT_ALPHA_ID,
        correlation_id=corr_id,
        payment_intent_id=intent_id,
        sequence_number=1,
        event_type=FinancialEventType.PROPOSAL_CREATED,
        actor_type="AGENT",
        actor_id=str(AGENT_PROCUREMENT_ID),
        payload={"amount_minor": 3900, "merchant_id": str(MERCHANT_SANDBOX_CLOUD_ID)},
        previous_event_hash=None,
        occurred_at=BASE_TIME + timedelta(minutes=1),
    )
    e2 = _chain_event(
        event_id=UUID("aaaa8888-0002-4000-8000-000000000001"),
        tenant_id=TENANT_ALPHA_ID,
        correlation_id=corr_id,
        payment_intent_id=intent_id,
        sequence_number=2,
        event_type=FinancialEventType.POLICY_EVALUATED,
        actor_type="GUARDIAN_POLICY_ENGINE",
        actor_id="policy-v1",
        payload={"outcome": "ALLOW", "quote_hash": q_hash},
        previous_event_hash=e1.event_hash,
        occurred_at=BASE_TIME + timedelta(minutes=1, seconds=2),
    )
    e3 = _chain_event(
        event_id=UUID("aaaa8888-0003-4000-8000-000000000001"),
        tenant_id=TENANT_ALPHA_ID,
        correlation_id=corr_id,
        payment_intent_id=intent_id,
        sequence_number=3,
        event_type=FinancialEventType.BUDGET_RESERVED,
        actor_type="BUDGET_LEDGER",
        actor_id=str(PASSPORT_DEFAULT_ID),
        payload={"reservation_id": str(reservation_id), "amount_minor": 3900},
        previous_event_hash=e2.event_hash,
        occurred_at=BASE_TIME + timedelta(minutes=1, seconds=3),
    )
    e4 = _chain_event(
        event_id=UUID("aaaa8888-0004-4000-8000-000000000001"),
        tenant_id=TENANT_ALPHA_ID,
        correlation_id=corr_id,
        payment_intent_id=intent_id,
        sequence_number=4,
        event_type=FinancialEventType.PAYPAL_CAPTURE_VERIFIED,
        actor_type="PAYPAL_EXECUTOR",
        actor_id="PAYPAL-CAP-DEMO-A-001",
        payload={"paypal_order_id": "PAYPAL-ORDER-DEMO-A-001", "status": "COMPLETED", "amount_minor": 3900},
        previous_event_hash=e3.event_hash,
        occurred_at=BASE_TIME + timedelta(minutes=2),
    )

    ev_quote = EvidenceRecord(
        id=UUID("aaaa9999-0001-4000-8000-000000000001"),
        tenant_id=TENANT_ALPHA_ID,
        correlation_id=corr_id,
        payment_intent_id=intent_id,
        source_type=EvidenceSourceType.QUOTE,
        source_ref=f"quote:{quote_id}",
        title="Bound Quote Snapshot ($39.00)",
        content={"merchant_id": str(MERCHANT_SANDBOX_CLOUD_ID), "amount_minor": 3900, "quote_hash": q_hash},
        content_hash=compute_payload_hash({"quote_hash": q_hash, "amount_minor": 3900}),
        is_synthetic=False,
        collected_at=BASE_TIME + timedelta(minutes=1),
    )
    ev_capture = EvidenceRecord(
        id=UUID("aaaa9999-0002-4000-8000-000000000001"),
        tenant_id=TENANT_ALPHA_ID,
        correlation_id=corr_id,
        payment_intent_id=intent_id,
        source_type=EvidenceSourceType.PAYPAL_CAPTURE,
        source_ref="paypal:PAYPAL-CAP-DEMO-A-001",
        title="Verified PayPal Capture Receipt",
        content={"paypal_order_id": "PAYPAL-ORDER-DEMO-A-001", "capture_id": "PAYPAL-CAP-DEMO-A-001", "status": "COMPLETED"},
        content_hash=compute_payload_hash({"capture_id": "PAYPAL-CAP-DEMO-A-001", "status": "COMPLETED"}),
        is_synthetic=False,
        collected_at=BASE_TIME + timedelta(minutes=2),
    )

    replay_request = ReplayRequest(
        tenant_id=TENANT_ALPHA_ID,
        correlation_id=corr_id,
        payment_intent=intent,
        proposal=proposal,
        quote_snapshot=quote,
        recorded_passport=base["passport"],
        recorded_merchant=base["approved_merchant"],
        recorded_decision=decision,
        policy_version="policy-v1",
        events=[e1, e2, e3, e4],
        evidence_records=[ev_quote, ev_capture],
        evaluation_time=BASE_TIME + timedelta(minutes=2),
    )

    return {
        **base,
        "proposal": proposal,
        "quote_snapshot": quote,
        "decision": decision,
        "reservation": reservation,
        "attempt": attempt,
        "payment_intent": intent,
        "events": [e1, e2, e3, e4],
        "evidence_records": [ev_quote, ev_capture],
        "replay_request": replay_request,
    }


def build_synthetic_dispute_fixture() -> dict[str, Any]:
    """Demo C / Contract Fixture: Clearly labeled synthetic delivery dispute with contradictory evidence."""
    demo_a = build_authorized_39_purchase_fixture()
    case_id = UUID("cccc1111-1111-4000-8000-000000000001")
    corr_id = demo_a["payment_intent"].correlation_id
    intent_id = demo_a["payment_intent"].id

    ev_tracking = EvidenceRecord(
        id=UUID("cccc9999-0001-4000-8000-000000000001"),
        tenant_id=TENANT_ALPHA_ID,
        correlation_id=corr_id,
        payment_intent_id=intent_id,
        dispute_case_id=case_id,
        source_type=EvidenceSourceType.CARRIER_TRACKING,
        source_ref="carrier:FEDEX-77441122",
        title="Synthetic Carrier Tracking Log (FEDEX-77441122)",
        content={
            "carrier": "FEDEX",
            "tracking_number": "77441122",
            "status": "DELIVERED",
            "delivered_at": "2026-11-11T14:20:00Z",
            "signed_by": "RECEPTION",
        },
        content_hash=compute_payload_hash({"tracking_number": "77441122", "status": "DELIVERED"}),
        is_synthetic=True,
        collected_at=BASE_TIME + timedelta(days=1),
    )
    ev_chat = EvidenceRecord(
        id=UUID("cccc9999-0002-4000-8000-000000000001"),
        tenant_id=TENANT_ALPHA_ID,
        correlation_id=corr_id,
        payment_intent_id=intent_id,
        dispute_case_id=case_id,
        source_type=EvidenceSourceType.CUSTOMER_MESSAGE,
        source_ref="support:MSG-901",
        title="Synthetic Merchant Support Email Acknowledging Non-Delivery",
        content={
            "sender": "support@sandbox-store.cloudcompute.example",
            "message": "We confirmed warehouse dispatch was delayed and item was not delivered on Nov 11.",
        },
        content_hash=compute_payload_hash({"msg_id": "MSG-901", "status": "UNDELIVERED"}),
        is_synthetic=True,
        collected_at=BASE_TIME + timedelta(days=1, hours=2),
    )

    all_evidence = [*demo_a["evidence_records"], ev_tracking, ev_chat]
    dispute_case = DisputeCase(
        id=case_id,
        tenant_id=TENANT_ALPHA_ID,
        correlation_id=corr_id,
        payment_intent_id=intent_id,
        paypal_dispute_id=None,
        source_type=DisputeSourceType.SYNTHETIC_DEMO,
        is_synthetic=True,
        reason="MERCHANDISE_OR_SERVICE_NOT_RECEIVED",
        buyer_claim="Buyer states item never arrived despite tracking showing delivered.",
        amount_minor=3900,
        currency="USD",
        status=DisputeStatus.OPEN,
        evidence_ids=[ev.id for ev in all_evidence],
        opened_at=BASE_TIME + timedelta(days=2),
        updated_at=BASE_TIME + timedelta(days=2),
    )
    return {
        **demo_a,
        "dispute_case": dispute_case,
        "all_evidence": all_evidence,
    }

