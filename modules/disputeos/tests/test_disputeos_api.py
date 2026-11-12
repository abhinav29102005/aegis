"""FastAPI TestClient integration tests for the DisputeOS router."""

from __future__ import annotations

from uuid import uuid4

import httpx
from contracts import (
    DisputeCase,
    DisputeSourceType,
    EvidenceRecord,
    EvidenceSourceType,
)
from contracts.fixtures import (
    TENANT_ALPHA_ID,
    TENANT_BETA_ID,
    build_authorized_39_purchase_fixture,
)
from disputeos.analysis.analyzer import SYNTHETIC_BANNER, DisputeAnalyzer
from disputeos.analysis.citations import CandidateClaim
from disputeos.api.router import create_disputeos_router
from disputeos.cases.service import DisputeCaseService
from disputeos.ingestion.normalizer import DocumentIngestionService
from disputeos.paypal.adapter import PayPalDisputeAdapter
from fastapi import FastAPI
from fastapi.testclient import TestClient
from paypal import PayPalSandboxClient
from security import NexusSettings


class _FailingLLMReviewer:
    def review(
        self,
        *,
        case: DisputeCase,
        evidence: list[EvidenceRecord],
        missing: list[str],
        contradictions: list[str],
    ) -> tuple[str, list[CandidateClaim]]:
        raise RuntimeError("LLM service unavailable")


def _build_test_client(
    *,
    disputes_api_enabled: bool = False,
    analyzer: DisputeAnalyzer | None = None,
) -> TestClient:
    app = FastAPI()
    settings = NexusSettings(
        paypal_mode="sandbox",
        paypal_disputes_api_enabled=disputes_api_enabled,
        paypal_client_id="sb-client-id" if disputes_api_enabled else "",
        paypal_client_secret="sb-client-secret" if disputes_api_enabled else "",
    )
    paypal_client: PayPalSandboxClient | None = None
    if disputes_api_enabled:
        def _mock_handler(request: httpx.Request) -> httpx.Response:
            if request.url.path == "/v1/oauth2/token":
                return httpx.Response(200, json={"access_token": "tok_api_test", "expires_in": 300})
            if request.url.path.endswith("/provide-evidence"):
                return httpx.Response(200, json={"dispute_id": "PP-D-REAL-001", "status": "UNDER_REVIEW"})
            return httpx.Response(404, json={"error": "unexpected"})

        paypal_client = PayPalSandboxClient(
            settings=settings,
            http_client=httpx.AsyncClient(
                base_url="https://api-m.sandbox.paypal.com",
                transport=httpx.MockTransport(_mock_handler),
            ),
        )

    router = create_disputeos_router(
        case_service=DisputeCaseService(),
        analyzer=analyzer or DisputeAnalyzer(),
        ingestion_service=DocumentIngestionService(),
        paypal_adapter=PayPalDisputeAdapter(
            settings=settings,
            paypal_client=paypal_client,
        ),
    )
    app.include_router(router)
    return TestClient(app)


def _seed_non_synthetic_case(client: TestClient) -> str:
    demo_a = build_authorized_39_purchase_fixture()
    intent = demo_a["payment_intent"]
    create_resp = client.post(
        "/disputeos/cases",
        json={
            "correlation_id": str(intent.correlation_id),
            "payment_intent_id": str(intent.id),
            "reason": "MERCHANDISE_OR_SERVICE_NOT_RECEIVED",
            "buyer_claim": "Buyer asks for delivery proof.",
            "amount_minor": 3900,
            "currency": "USD",
            "source_type": DisputeSourceType.PAYPAL_SANDBOX.value,
            "is_synthetic": False,
            "paypal_dispute_id": "PP-D-REAL-001",
        },
    )
    assert create_resp.status_code == 201
    case_id = create_resp.json()["id"]

    evidence_payloads = [
        {
            "source_type": EvidenceSourceType.QUOTE.value,
            "source_ref": "quote:real-1",
            "title": "Bound Quote Snapshot ($39.00)",
            "content": {"amount_minor": 3900, "currency": "USD"},
        },
        {
            "source_type": EvidenceSourceType.POLICY_DECISION.value,
            "source_ref": "decision:real-1",
            "title": "Authorization Decision (ALLOW)",
            "content": {"outcome": "ALLOW"},
        },
        {
            "source_type": EvidenceSourceType.PAYPAL_CAPTURE.value,
            "source_ref": "paypal:CAP-REAL-1",
            "title": "Verified PayPal Capture",
            "content": {"capture_id": "CAP-REAL-1", "status": "COMPLETED", "amount_minor": 3900},
        },
        {
            "source_type": EvidenceSourceType.CARRIER_TRACKING.value,
            "source_ref": "carrier:FEDEX-REAL-1",
            "title": "Carrier Tracking Log",
            "content": {"carrier": "FEDEX", "status": "DELIVERED"},
        },
        {
            "source_type": EvidenceSourceType.DELIVERY_RECEIPT.value,
            "source_ref": "receipt:FEDEX-REAL-1",
            "title": "Signed Delivery Receipt",
            "content": {"status": "DELIVERED", "signed_by": "RECEPTION"},
        },
    ]
    for item in evidence_payloads:
        ev_resp = client.post(f"/disputeos/cases/{case_id}/evidence", json=item)
        assert ev_resp.status_code == 200
    return case_id


def test_seed_demo_list_detail_analyze_and_synthetic_submit_block() -> None:
    client = _build_test_client(disputes_api_enabled=True)

    seed_resp = client.post("/disputeos/cases/seed-demo")
    assert seed_resp.status_code == 200
    seeded = seed_resp.json()
    case_id = seeded["case"]["id"]
    assert seeded["case"]["is_synthetic"] is True
    assert seeded["case"]["source_type"] == "SYNTHETIC_DEMO"
    assert len(seeded["evidence"]) == 4

    # Idempotent re-seed returns same synthetic case
    reseed_resp = client.post("/disputeos/cases/seed-demo")
    assert reseed_resp.status_code == 200
    assert reseed_resp.json()["case"]["id"] == case_id

    # List cases for default tenant
    list_resp = client.get("/disputeos/cases")
    assert list_resp.status_code == 200
    assert any(item["id"] == case_id for item in list_resp.json())

    # Analyze seeded synthetic case
    analyze_resp = client.post(f"/disputeos/cases/{case_id}/analyze")
    assert analyze_resp.status_code == 200
    analyzed = analyze_resp.json()
    assert analyzed["case"]["status"] == "DRAFT_READY"
    assert analyzed["analysis"]["is_synthetic"] is True
    assert analyzed["analysis"]["recommendation"] == "ACCEPT_AND_REFUND"
    assert len(analyzed["analysis"]["contradictions"]) >= 1
    assert len(analyzed["analysis"]["citations"]) == 4
    assert SYNTHETIC_BANNER in analyzed["analysis"]["grounded_summary"]
    assert len(analyzed["evidence_graph"]["nodes"]) == 4
    assert SYNTHETIC_BANNER in analyzed["report"]["markdown_report"]

    # Detail endpoint includes latest_analysis
    detail_resp = client.get(f"/disputeos/cases/{case_id}")
    assert detail_resp.status_code == 200
    detail = detail_resp.json()
    assert detail["latest_analysis"]["id"] == analyzed["analysis"]["id"]

    # Approve synthetic case, then verify external submission is still blocked (HTTP 403)
    draft_text = analyzed["analysis"]["draft_response_text"]
    approve_resp = client.post(
        f"/disputeos/cases/{case_id}/approve",
        json={"approver_id": "ops-reviewer-1", "draft_response_text": draft_text},
    )
    assert approve_resp.status_code == 200
    assert approve_resp.json()["status"] == "APPROVED_FOR_SUBMISSION"

    submit_resp = client.post(
        f"/disputeos/cases/{case_id}/submit",
        json={"draft_response_text": draft_text},
    )
    assert submit_resp.status_code == 403


def test_api_tenant_isolation_and_error_mappings() -> None:
    client = _build_test_client()
    seed_resp = client.post("/disputeos/cases/seed-demo")
    case_id = seed_resp.json()["case"]["id"]

    other_headers = {"X-Tenant-Id": str(TENANT_BETA_ID)}

    # Cross-tenant list is empty
    assert client.get("/disputeos/cases", headers=other_headers).json() == []

    # Cross-tenant operations return 403
    assert client.get(f"/disputeos/cases/{case_id}", headers=other_headers).status_code == 403
    assert client.post(f"/disputeos/cases/{case_id}/analyze", headers=other_headers).status_code == 403
    assert (
        client.post(
            f"/disputeos/cases/{case_id}/approve",
            headers=other_headers,
            json={"approver_id": "attacker", "draft_response_text": "bad"},
        ).status_code
        == 403
    )
    assert client.post(f"/disputeos/cases/{case_id}/submit", headers=other_headers).status_code == 403

    # Cross-tenant evidence payload rejected with 403
    assert (
        client.post(
            f"/disputeos/cases/{case_id}/evidence",
            json={
                "tenant_id": str(TENANT_BETA_ID),
                "source_type": EvidenceSourceType.CUSTOMER_MESSAGE.value,
                "source_ref": "msg:cross-tenant",
                "title": "Cross-tenant message",
                "content": {"message": "forbidden"},
            },
        ).status_code
        == 403
    )

    # Missing case returns 404
    assert client.get(f"/disputeos/cases/{uuid4()}").status_code == 404

    # Invalid X-Tenant-Id header returns 400
    assert (
        client.get("/disputeos/cases", headers={"X-Tenant-Id": "not-a-uuid"}).status_code == 400
    )


def test_api_approval_gate_feature_flag_and_guarded_submit() -> None:
    # Feature-flag disabled blocks approved non-synthetic submission with 403
    disabled_client = _build_test_client(disputes_api_enabled=False)
    case_id = _seed_non_synthetic_case(disabled_client)
    analyze_resp = disabled_client.post(f"/disputeos/cases/{case_id}/analyze")
    assert analyze_resp.status_code == 200
    draft_text = analyze_resp.json()["analysis"]["draft_response_text"]

    # Unapproved submission fails with 403
    assert disabled_client.post(f"/disputeos/cases/{case_id}/submit").status_code == 403

    approve_resp = disabled_client.post(
        f"/disputeos/cases/{case_id}/approve",
        json={"approver_id": "lead-analyst", "draft_response_text": draft_text},
    )
    assert approve_resp.status_code == 200
    assert disabled_client.post(f"/disputeos/cases/{case_id}/submit").status_code == 403

    # Feature-flag enabled allows guarded submission handoff for approved non-synthetic case
    enabled_client = _build_test_client(disputes_api_enabled=True)
    case_id_2 = _seed_non_synthetic_case(enabled_client)
    analyze_resp_2 = enabled_client.post(f"/disputeos/cases/{case_id_2}/analyze")
    draft_text_2 = analyze_resp_2.json()["analysis"]["draft_response_text"]

    enabled_client.post(
        f"/disputeos/cases/{case_id_2}/approve",
        json={"approver_id": "lead-analyst", "draft_response_text": draft_text_2},
    )

    # Tampered draft fails with 403
    tamper_resp = enabled_client.post(
        f"/disputeos/cases/{case_id_2}/submit",
        json={"draft_response_text": "Tampered text"},
    )
    assert tamper_resp.status_code == 403

    # Exact approved draft succeeds
    submit_resp = enabled_client.post(f"/disputeos/cases/{case_id_2}/submit")
    assert submit_resp.status_code == 200
    body = submit_resp.json()
    assert body["case"]["status"] == "SUBMITTED"
    assert body["submission"]["status"] == "SUBMITTED_TO_PAYPAL"
    assert body["submission"]["submitted"] is True
    assert body["submission"]["auto_submitted"] is False
    assert body["submission"]["refund_issued"] is False


def test_api_failed_llm_reviewer_falls_back_cleanly() -> None:
    client = _build_test_client(
        analyzer=DisputeAnalyzer(llm_reviewer=_FailingLLMReviewer())
    )
    seed_resp = client.post(
        "/disputeos/cases/seed-demo",
        headers={"X-Tenant-Id": str(TENANT_ALPHA_ID)},
    )
    case_id = seed_resp.json()["case"]["id"]

    analyze_resp = client.post(f"/disputeos/cases/{case_id}/analyze")
    assert analyze_resp.status_code == 200
    payload = analyze_resp.json()
    assert payload["analysis"]["generated_with_llm"] is False
    assert payload["case"]["status"] == "DRAFT_READY"
    assert len(payload["analysis"]["citations"]) == 4
