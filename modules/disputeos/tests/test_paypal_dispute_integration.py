"""Tests for PayPal Dispute Adapter, Webhooks, and advanced contradiction heuristics."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest
from contracts import (
    DisputeCase,
    DisputeSourceType,
    DisputeStatus,
    EvidenceRecord,
    EvidenceSourceType,
    compute_payload_hash,
)
from contracts.fixtures import TENANT_ALPHA_ID
from disputeos.cases.service import DisputeCaseService
from disputeos.evidence.detector import detect_contradictions
from disputeos.paypal.adapter import PayPalDisputeAdapter
from disputeos.paypal.webhook_handler import handle_paypal_dispute_webhook
from security import NexusSettings


class MockPayPalClient:
    def __init__(self) -> None:
        self.evidence_calls: list[dict] = []
        self.accept_calls: list[dict] = []

    async def provide_evidence(self, dispute_id: str, evidence_type: str = "PROOF_OF_DELIVERY", notes: str = "", **kwargs) -> dict:
        self.evidence_calls.append({"dispute_id": dispute_id, "evidence_type": evidence_type, "notes": notes})
        return {"status": "SUCCESS", "dispute_id": dispute_id}

    async def accept_claim(self, dispute_id: str, note: str = "") -> dict:
        self.accept_calls.append({"dispute_id": dispute_id, "note": note})
        return {"status": "RESOLVED", "dispute_id": dispute_id}


@pytest.mark.asyncio
async def test_paypal_adapter_accept_claim_and_external_submit() -> None:
    settings = NexusSettings(paypal_mode="sandbox", paypal_disputes_api_enabled=True)
    mock_client = MockPayPalClient()
    adapter = PayPalDisputeAdapter(settings=settings, paypal_client=mock_client)

    case_id = uuid4()
    draft = "Valid draft response"
    h = compute_payload_hash({"case_id": str(case_id), "draft_response_text": draft})
    case = DisputeCase(
        id=case_id,
        tenant_id=TENANT_ALPHA_ID,
        correlation_id=uuid4(),
        payment_intent_id=uuid4(),
        status=DisputeStatus.APPROVED_FOR_SUBMISSION,
        source_type=DisputeSourceType.PAYPAL_SANDBOX,
        reason="MERCHANDISE_OR_SERVICE_NOT_RECEIVED",
        buyer_claim="Where is my order?",
        amount_minor=5000,
        currency="USD",
        is_synthetic=False,
        paypal_dispute_id="PP-DISPUTE-123",
        human_approved_for_submission=True,
        approved_by="analyst-1",
        response_payload_hash=h,
    )

    # External submission
    res = await adapter.submit_dispute_response(case=case, draft_response_text=draft, execute_external=True)
    assert res["submitted"] is True
    assert res["status"] == "SUBMITTED"
    assert len(mock_client.evidence_calls) == 1

    # Accept claim
    accept_res = await adapter.accept_dispute_claim(case=case, note="Refunding per policy")
    assert accept_res["status"] == "ACCEPTED"
    assert len(mock_client.accept_calls) == 1


@pytest.mark.asyncio
async def test_dispute_webhook_handler_lifecycle() -> None:
    svc = DisputeCaseService()
    tenant_id = TENANT_ALPHA_ID

    # 1. CUSTOMER.DISPUTE.CREATED
    created_res = await handle_paypal_dispute_webhook(
        repo=svc,
        event_type="CUSTOMER.DISPUTE.CREATED",
        resource={
            "dispute_id": "PP-WH-001",
            "dispute_amount": {"value": "45.00", "currency_code": "USD"},
            "reason": "UNAUTHORIZED_TRANSACTION",
            "seller_response_due_date": "2026-11-20T12:00:00Z",
        },
        tenant_id=tenant_id,
    )
    assert created_res["handled"] is True
    assert created_res["action"] == "created"
    case_id = created_res["case_id"]

    # Verify created
    case = svc.get_case(tenant_id, UUID(case_id))
    assert case.amount_minor == 4500
    assert case.paypal_dispute_id == "PP-WH-001"

    # Idempotent re-delivery
    recreated = await handle_paypal_dispute_webhook(
        repo=svc,
        event_type="CUSTOMER.DISPUTE.CREATED",
        resource={"dispute_id": "PP-WH-001"},
        tenant_id=tenant_id,
    )
    assert recreated["action"] == "already_exists"

    # 2. CUSTOMER.DISPUTE.RESOLVED
    res_webhook = await handle_paypal_dispute_webhook(
        repo=svc,
        event_type="CUSTOMER.DISPUTE.RESOLVED",
        resource={
            "dispute_id": "PP-WH-001",
            "dispute_outcome": {"outcome_code": "RESOLVED_BUYER_FAVOUR"},
        },
        tenant_id=tenant_id,
    )
    assert res_webhook["handled"] is True
    assert res_webhook["action"] == "resolved"


def test_contradiction_heuristics() -> None:
    tenant_id = TENANT_ALPHA_ID
    # Heuristic 1: Unauthorized claim vs 3DS pass
    case1 = DisputeCase(
        id=uuid4(),
        tenant_id=tenant_id,
        correlation_id=uuid4(),
        payment_intent_id=uuid4(),
        status=DisputeStatus.OPEN,
        source_type=DisputeSourceType.PAYPAL_SANDBOX,
        reason="UNAUTHORIZED_CHARGE",
        buyer_claim="I never made this transaction",
        amount_minor=1000,
        currency="USD",
        is_synthetic=False,
    )
    ev1 = EvidenceRecord(
        id=uuid4(),
        tenant_id=tenant_id,
        correlation_id=case1.correlation_id,
        source_type=EvidenceSourceType.PAYPAL_CAPTURE,
        source_ref="cap-1",
        title="Verified Capture with 3DS",
        content={"three_d_secure": "AUTHENTICATED", "liability_shift": True, "cvv_match": "MATCH"},
        content_hash="0123456789abcdef0123456789abcdef",
        is_synthetic=False,
        collected_at=datetime.now(UTC),
    )
    contra1 = detect_contradictions(case1, [ev1])
    assert any("3DS=" in c for c in contra1)

    # Heuristic 2: Non-access claim vs active session
    case2 = DisputeCase(
        id=uuid4(),
        tenant_id=tenant_id,
        correlation_id=uuid4(),
        payment_intent_id=uuid4(),
        status=DisputeStatus.OPEN,
        source_type=DisputeSourceType.PAYPAL_SANDBOX,
        reason="SERVICE_NOT_RECEIVED",
        buyer_claim="I never accessed or used this subscription",
        amount_minor=2000,
        currency="USD",
        is_synthetic=False,
    )
    ev2 = EvidenceRecord(
        id=uuid4(),
        tenant_id=tenant_id,
        correlation_id=case2.correlation_id,
        source_type=EvidenceSourceType.CUSTOMER_MESSAGE,
        source_ref="session-log-1",
        title="Access Telemetry",
        content={"last_login": "2026-11-10T14:00:00Z", "ip_address": "198.51.100.24"},
        content_hash="0123456789abcdef0123456789abcdef",
        is_synthetic=False,
        collected_at=datetime.now(UTC),
    )
    contra2 = detect_contradictions(case2, [ev2])
    assert any("shows verified active session" in c for c in contra2)

    # Heuristic 3: Cancellation after billing date
    case3 = DisputeCase(
        id=uuid4(),
        tenant_id=tenant_id,
        correlation_id=uuid4(),
        payment_intent_id=uuid4(),
        status=DisputeStatus.OPEN,
        source_type=DisputeSourceType.PAYPAL_SANDBOX,
        reason="CANCELLED_BEFORE_RENEWAL",
        buyer_claim="I cancelled prior to billing",
        amount_minor=3000,
        currency="USD",
        is_synthetic=False,
    )
    ev3 = EvidenceRecord(
        id=uuid4(),
        tenant_id=tenant_id,
        correlation_id=case3.correlation_id,
        source_type=EvidenceSourceType.CUSTOMER_MESSAGE,
        source_ref="email-cancel",
        title="Cancellation Request Email",
        content={"cancellation_requested_at": "2026-11-05", "renewal_date": "2026-11-01"},
        content_hash="0123456789abcdef0123456789abcdef",
        is_synthetic=False,
        collected_at=datetime.now(UTC),
    )
    contra3 = detect_contradictions(case3, [ev3])
    assert any("after billing date" in c for c in contra3)
