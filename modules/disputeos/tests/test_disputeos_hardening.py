"""Hardening tests for DisputeOS cases, ingestion, causal evidence graph, detector, and PayPal adapter/webhooks."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID, uuid4

import httpx
import pytest
from aegis_api.adapters import ensure_synthetic_sandbox_payment_chain
from aegis_api.app import create_app
from contracts import (
    DisputeAnalysis,
    DisputeCase,
    DisputeRecommendation,
    DisputeSourceType,
    DisputeStatus,
    EvidenceRecord,
    EvidenceSourceType,
    FinancialEventType,
    compute_payload_hash,
)
from contracts.fixtures import TENANT_ALPHA_ID, TENANT_BETA_ID
from database import (
    LedgerRepository,
    PaymentAttemptRow,
    TenantRow,
    create_db_engine,
    create_session_factory,
    init_db,
)
from disputeos.cases.service import (
    ApprovalGateError,
    DisputeCaseService,
    InvalidDisputeTransitionError,
)
from disputeos.evidence.detector import detect_contradictions, detect_missing_evidence
from disputeos.evidence.graph import build_evidence_graph
from disputeos.ingestion.normalizer import (
    DocumentIngestionService,
    EvidenceIntegrityError,
    assert_evidence_digest,
    compute_evidence_hash,
    normalize_evidence_record,
    verify_evidence_digest,
)
from disputeos.paypal.adapter import PayPalDisputeAdapter
from disputeos.paypal.webhook_handler import handle_paypal_dispute_webhook
from fastapi.testclient import TestClient
from paypal import PayPalAPIError, PayPalSandboxClient, PayPalTimeoutError
from security import NexusSettings, verify_financial_event_chain

PAYPAL_SANDBOX_BASE_URL = "https://api-m.sandbox.paypal.com"


def _utc(offset_minutes: int = 0) -> datetime:
    return datetime(2026, 6, 1, 12, 0, 0, tzinfo=UTC) + timedelta(minutes=offset_minutes)


def _make_case(
    *,
    tenant_id: UUID | None = None,
    reason: str = "ITEM_NOT_RECEIVED",
    buyer_claim: str = "Item never arrived",
    is_synthetic: bool = False,
    paypal_dispute_id: str | None = "PP-D-9001",
    status: DisputeStatus = DisputeStatus.OPEN,
) -> DisputeCase:
    return DisputeCase(
        id=uuid4(),
        tenant_id=tenant_id or TENANT_ALPHA_ID,
        correlation_id=uuid4(),
        payment_intent_id=uuid4(),
        paypal_dispute_id=paypal_dispute_id,
        source_type=(
            DisputeSourceType.SYNTHETIC_DEMO if is_synthetic else DisputeSourceType.PAYPAL_SANDBOX
        ),
        is_synthetic=is_synthetic,
        reason=reason,
        buyer_claim=buyer_claim,
        amount_minor=4500,
        currency="USD",
        status=status,
    )


def _make_evidence(
    case: DisputeCase,
    *,
    source_type: EvidenceSourceType,
    source_ref: str,
    title: str,
    content: dict[str, object],
    collected_at: datetime | None = None,
    payment_intent_id: UUID | None = None,
    correlation_id: UUID | None = None,
) -> EvidenceRecord:
    ingestor = DocumentIngestionService()
    return ingestor.ingest_document(
        tenant_id=case.tenant_id,
        correlation_id=correlation_id or case.correlation_id,
        payment_intent_id=payment_intent_id or case.payment_intent_id,
        dispute_case_id=case.id,
        source_type=source_type,
        source_ref=source_ref,
        title=title,
        content=content,
        is_synthetic=case.is_synthetic,
        collected_at=collected_at or _utc(),
    )


def _seed_payment_intent_id(app: object, tenant_id: UUID) -> str:
    session_factory = app.state.session_factory  # type: ignore[attr-defined]
    with session_factory() as session:
        repo = LedgerRepository(session)
        seeded = ensure_synthetic_sandbox_payment_chain(repo, tenant_id)
        session.commit()
        return str(seeded["payment_intent"].id)


# ---------------------------------------------------------------------------
# 1. Ingestion Integrity & Full-Context Digest Verification
# ---------------------------------------------------------------------------


def test_evidence_hash_covers_full_context_and_rejects_mismatched_or_tampered_records() -> None:
    case = _make_case()
    base = _make_evidence(
        case,
        source_type=EvidenceSourceType.DELIVERY_RECEIPT,
        source_ref="carrier:1Z999",
        title="Delivered parcel",
        content={"tracking_number": "1Z999", "delivery_status": "DELIVERED"},
        collected_at=_utc(5),
    )
    assert verify_evidence_digest(base) is True

    mutations = [
        base.model_copy(update={"tenant_id": TENANT_BETA_ID}),
        base.model_copy(update={"dispute_case_id": uuid4()}),
        base.model_copy(update={"correlation_id": uuid4()}),
        base.model_copy(update={"is_synthetic": True}),
        base.model_copy(update={"collected_at": _utc(99)}),
        base.model_copy(update={"source_type": EvidenceSourceType.PAYPAL_CAPTURE}),
        base.model_copy(update={"source_ref": "carrier:OTHER"}),
        base.model_copy(update={"title": "Edited title"}),
        base.model_copy(update={"content": {"tracking_number": "1Z999", "delivery_status": "PENDING"}}),
    ]
    for mutated in mutations:
        assert verify_evidence_digest(mutated) is False
        recomputed = compute_evidence_hash(
            tenant_id=mutated.tenant_id,
            dispute_case_id=mutated.dispute_case_id,
            correlation_id=mutated.correlation_id,
            is_synthetic=mutated.is_synthetic,
            collected_at=mutated.collected_at,
            source_type=mutated.source_type,
            source_ref=mutated.source_ref,
            title=mutated.title,
            content=mutated.content,
        )
        assert recomputed != base.content_hash
        with pytest.raises(EvidenceIntegrityError):
            assert_evidence_digest(mutated)

    ingestor = DocumentIngestionService()
    with pytest.raises(EvidenceIntegrityError):
        ingestor.ingest_document(
            tenant_id=case.tenant_id,
            correlation_id=case.correlation_id,
            payment_intent_id=case.payment_intent_id,
            dispute_case_id=case.id,
            source_type=EvidenceSourceType.DELIVERY_RECEIPT,
            source_ref="carrier:1Z999",
            title="Delivered parcel",
            content={"tracking_number": "1Z999"},
            content_hash="0" * 64,
            is_synthetic=False,
            collected_at=_utc(5),
        )

    with pytest.raises(EvidenceIntegrityError):
        normalize_evidence_record(base.model_copy(update={"content_hash": "f" * 64}))

    svc = DisputeCaseService()
    svc.create_case(
        tenant_id=case.tenant_id,
        correlation_id=case.correlation_id,
        payment_intent_id=case.payment_intent_id,
        reason=case.reason,
        buyer_claim=case.buyer_claim,
        amount_minor=case.amount_minor,
        currency=case.currency,
        source_type=case.source_type,
        is_synthetic=False,
        case_id=case.id,
        paypal_dispute_id=case.paypal_dispute_id,
    )
    with pytest.raises(EvidenceIntegrityError):
        svc.attach_evidence(
            case.tenant_id,
            case.id,
            [base.model_copy(update={"content": {"tampered": True}})],
        )


# ---------------------------------------------------------------------------
# 2. Causal Evidence Graph
# ---------------------------------------------------------------------------


def test_evidence_graph_uses_causal_linkage_not_cartesian_product() -> None:
    case = _make_case()
    proposal_a = str(uuid4())
    proposal_b = str(uuid4())
    intent_b = uuid4()

    ev_prop_a = _make_evidence(
        case,
        source_type=EvidenceSourceType.PROPOSAL,
        source_ref="prop:A",
        title="Proposal A",
        content={"proposal_id": proposal_a},
        collected_at=_utc(0),
    )
    ev_quote_a = _make_evidence(
        case,
        source_type=EvidenceSourceType.QUOTE,
        source_ref="quote:A",
        title="Quote A",
        content={"proposal_id": proposal_a, "quote_snapshot_id": "q-a"},
        collected_at=_utc(1),
    )
    ev_dec_a = _make_evidence(
        case,
        source_type=EvidenceSourceType.POLICY_DECISION,
        source_ref="dec:A",
        title="Decision A",
        content={"proposal_id": proposal_a, "quote_snapshot_id": "q-a"},
        collected_at=_utc(2),
    )
    ev_pay_a = _make_evidence(
        case,
        source_type=EvidenceSourceType.PAYPAL_CAPTURE,
        source_ref="pay:A",
        title="Payment A",
        content={"paypal_order_id": "ORD-A", "paypal_capture_id": "CAP-A"},
        collected_at=_utc(3),
    )
    ev_del_a = _make_evidence(
        case,
        source_type=EvidenceSourceType.DELIVERY_RECEIPT,
        source_ref="del:A",
        title="Delivery A",
        content={"paypal_order_id": "ORD-A", "tracking_number": "TRK-A"},
        collected_at=_utc(4),
    )
    ev_prop_b = _make_evidence(
        case,
        source_type=EvidenceSourceType.PROPOSAL,
        source_ref="prop:B",
        title="Proposal B",
        content={"proposal_id": proposal_b},
        collected_at=_utc(0),
        payment_intent_id=intent_b,
        correlation_id=uuid4(),
    )
    ev_del_stale = _make_evidence(
        case,
        source_type=EvidenceSourceType.DELIVERY_RECEIPT,
        source_ref="del:stale",
        title="Stale delivery",
        content={"paypal_order_id": "ORD-A"},
        collected_at=_utc(1),
    )

    graph = build_evidence_graph(
        case,
        [ev_prop_a, ev_quote_a, ev_dec_a, ev_pay_a, ev_del_a, ev_prop_b, ev_del_stale],
    )
    edge_pairs = {(e.from_id, e.to_id) for e in graph.edges}

    assert (str(ev_prop_a.id), str(ev_quote_a.id)) in edge_pairs
    assert (str(ev_quote_a.id), str(ev_dec_a.id)) in edge_pairs
    assert (str(ev_dec_a.id), str(ev_pay_a.id)) in edge_pairs
    assert (str(ev_pay_a.id), str(ev_del_a.id)) in edge_pairs
    assert (str(ev_prop_b.id), str(ev_quote_a.id)) not in edge_pairs
    assert (str(ev_pay_a.id), str(ev_del_stale.id)) not in edge_pairs
    assert all(node.digest_verified is True for node in graph.nodes)


# ---------------------------------------------------------------------------
# 3. Expanded Detector Heuristics
# ---------------------------------------------------------------------------


def test_detector_covers_avs_cvv_3ds_device_subscription_and_snad() -> None:
    unauth_case = _make_case(
        reason="UNAUTHORIZED",
        buyer_claim="Unauthorized card transaction",
    )
    pay_fail = _make_evidence(
        unauth_case,
        source_type=EvidenceSourceType.PAYPAL_CAPTURE,
        source_ref="pay:card1",
        title="Card authorization telemetry",
        content={
            "avs_result": "N",
            "cvv_result": "N",
            "3ds_status": "FAILED",
            "ip_country": "RU",
            "billing_country": "US",
        },
    )
    unauth_contradictions = detect_contradictions(unauth_case, [pay_fail])
    joined = " | ".join(unauth_contradictions)
    assert "avs_result=N" in joined
    assert "cvv_result=N" in joined
    assert "3ds_status=FAILED" in joined
    assert "ip_country=RU differs from billing_country=US" in joined

    unauth_missing = detect_missing_evidence(
        unauth_case,
        [
            _make_evidence(
                unauth_case,
                source_type=EvidenceSourceType.PAYPAL_CAPTURE,
                source_ref="pay:bare",
                title="Bare attempt",
                content={"status": "CAPTURED"},
            )
        ],
    )
    missing_joined = " | ".join(unauth_missing)
    assert "Missing AVS/CVV/3DS card verification telemetry" in missing_joined
    assert "Missing IP/device telemetry" in missing_joined

    sub_case = _make_case(
        reason="SUBSCRIPTION_CANCELED",
        buyer_claim="I canceled my recurring subscription last week before being billed.",
    )
    sub_pay = _make_evidence(
        sub_case,
        source_type=EvidenceSourceType.PAYPAL_CAPTURE,
        source_ref="pay:sub1",
        title="Subscription renewal capture",
        content={"verified_at": "2026-06-05T10:00:00Z"},
    )
    sub_cancel = _make_evidence(
        sub_case,
        source_type=EvidenceSourceType.CUSTOMER_MESSAGE,
        source_ref="sub:cancel",
        title="Subscription cancellation confirmation",
        content={
            "cancelled_at": "2026-06-01T08:00:00Z",
            "cancellation_confirmed": True,
        },
    )
    sub_contradictions = detect_contradictions(sub_case, [sub_pay, sub_cancel])
    assert any("cancelled prior to charge" in item for item in sub_contradictions)

    snad_case = _make_case(
        reason="SIGNIFICANTLY_NOT_AS_DESCRIBED",
        buyer_claim="Widget arrived damaged and wrong model.",
    )
    snad_missing = detect_missing_evidence(snad_case, [])
    assert any("item specification packet" in item for item in snad_missing)
    assert any("inspection/RMA packet" in item for item in snad_missing)

    snad_ev = _make_evidence(
        snad_case,
        source_type=EvidenceSourceType.DELIVERY_RECEIPT,
        source_ref="rma:1",
        title="Inspection report",
        content={"defective": True, "rma_status": "RETURN_APPROVED"},
    )
    snad_contradictions = detect_contradictions(snad_case, [snad_ev])
    assert any("SIGNIFICANTLY_NOT_AS_DESCRIBED" in item for item in snad_contradictions)


# ---------------------------------------------------------------------------
# 4. Monotonic State Machine, Resolve, Hash-Chained Events, SEC-06, Pagination
# ---------------------------------------------------------------------------


def _build_persistent_app(
    tmp_path: Path,
    *,
    paypal_client: PayPalSandboxClient | None = None,
    disputes_api_enabled: bool = True,
) -> tuple[TestClient, object, NexusSettings]:
    db_file = tmp_path / "dispute_hardening.db"
    evidence_dir = tmp_path / "evidence"
    evidence_dir.mkdir(parents=True, exist_ok=True)
    settings = NexusSettings(
        database_url=f"sqlite:///{db_file}",
        jwt_secret="hardening-jwt-secret-at-least-32-chars",
        signing_secret="hardening-signing-secret-at-least-32",
        evidence_storage_dir=str(evidence_dir),
        rate_limit_rpm=10000,
        paypal_mode="sandbox",
        paypal_disputes_api_enabled=disputes_api_enabled,
        paypal_client_id="sb-client" if disputes_api_enabled else "",
        paypal_client_secret="sb-secret" if disputes_api_enabled else "",
    )
    app = create_app(settings=settings, paypal_client=paypal_client, create_tables=True)
    return TestClient(app), app, settings


def _register_org(client: TestClient, slug_suffix: str) -> tuple[dict[str, str], UUID]:
    resp = client.post(
        "/v1/auth/register",
        json={
            "email": f"admin-{slug_suffix}@hardening.test",
            "password": "StrongPassword!2026",
            "full_name": f"Admin {slug_suffix}",
            "organization_name": f"Org {slug_suffix}",
            "organization_slug": f"org-{slug_suffix}-{uuid4().hex[:6]}",
        },
    )
    assert resp.status_code == 201, resp.text
    data = resp.json()
    headers = {
        "Authorization": f"Bearer {data['access_token']}",
        "X-Org-Id": data["active_tenant_id"],
    }
    return headers, UUID(data["active_tenant_id"])


def test_db_monotonic_transitions_resolve_pagination_hash_chain_and_sec06(tmp_path: Path) -> None:
    def _mock_paypal(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v1/oauth2/token":
            return httpx.Response(200, json={"access_token": "tok_hardening", "expires_in": 300})
        if request.url.path.endswith("/provide-evidence"):
            return httpx.Response(
                200,
                json={"links": [{"rel": "self", "href": "https://api-m.sandbox.paypal.com/v1/customer/disputes/PP-D-LIVE-1"}]},
            )
        raise AssertionError(f"Unexpected PayPal call: {request.method} {request.url}")

    cfg = NexusSettings(
        paypal_mode="sandbox",
        paypal_disputes_api_enabled=True,
        paypal_client_id="sb-client",
        paypal_client_secret="sb-secret",
    )
    mock_pp = PayPalSandboxClient(
        settings=cfg,
        http_client=httpx.AsyncClient(
            base_url=PAYPAL_SANDBOX_BASE_URL,
            transport=httpx.MockTransport(_mock_paypal),
        ),
    )
    client, app, _ = _build_persistent_app(tmp_path, paypal_client=mock_pp)

    with client:
        headers_a, tenant_a = _register_org(client, "alpha")
        headers_b, _tenant_b = _register_org(client, "beta")
        intent_id = _seed_payment_intent_id(app, tenant_a)

        due_iso = "2026-07-01T18:00:00Z"
        corr_1 = uuid4()
        create_1 = client.post(
            "/v1/disputeos/cases",
            headers=headers_a,
            json={
                "correlation_id": str(corr_1),
                "payment_intent_id": intent_id,
                "reason": "ITEM_NOT_RECEIVED",
                "buyer_claim": "Buyer claims package did not arrive.",
                "amount_minor": 6500,
                "currency": "USD",
                "source_type": "PAYPAL_SANDBOX",
                "is_synthetic": False,
                "paypal_dispute_id": "PP-D-LIVE-1",
                "response_due_by": due_iso,
                "external_status": "WAITING_FOR_SELLER_RESPONSE",
            },
        )
        assert create_1.status_code == 201, create_1.text
        c1 = create_1.json()
        assert c1["response_due_by"].startswith("2026-07-01T18:00:00")
        assert c1["external_status"] == "WAITING_FOR_SELLER_RESPONSE"

        create_2 = client.post(
            "/v1/disputeos/cases",
            headers=headers_a,
            json={
                "correlation_id": str(uuid4()),
                "payment_intent_id": intent_id,
                "reason": "UNAUTHORIZED",
                "buyer_claim": "Second case",
                "amount_minor": 1200,
                "currency": "USD",
                "source_type": "PAYPAL_SANDBOX",
                "is_synthetic": False,
                "paypal_dispute_id": "PP-D-LIVE-2",
            },
        )
        assert create_2.status_code == 201, create_2.text
        c2 = create_2.json()

        up = client.post(
            f"/v1/disputeos/cases/{c1['id']}/artifacts",
            headers=headers_a,
            files={"file": ("receipt.txt", b"carrier delivery proof", "text/plain")},
            data={"title": "Carrier Proof", "source_type": "DELIVERY_RECEIPT"},
        )
        assert up.status_code == 201, up.text
        artifact_id = up.json()["artifact_id"]

        # SEC-06: Case 2 cannot download Case 1's artifact (404 same-tenant cross-case IDOR)
        idor_same_tenant = client.get(
            f"/v1/disputeos/cases/{c2['id']}/artifacts/{artifact_id}",
            headers=headers_a,
        )
        assert idor_same_tenant.status_code == 404

        # Cross-tenant artifact download blocked
        idor_cross_tenant = client.get(
            f"/v1/disputeos/cases/{c1['id']}/artifacts/{artifact_id}",
            headers=headers_b,
        )
        assert idor_cross_tenant.status_code in {403, 404}

        # Pagination: limit=1, offset=0/1 + X-Total-Count
        p1 = client.get("/v1/disputeos/cases?limit=1&offset=0", headers=headers_a)
        assert p1.status_code == 200
        assert p1.headers["X-Total-Count"] == "2"
        assert len(p1.json()) == 1
        p2 = client.get("/v1/disputeos/cases?limit=1&offset=1", headers=headers_a)
        assert p2.status_code == 200
        assert len(p2.json()) == 1
        assert p1.json()[0]["id"] != p2.json()[0]["id"]

        # Analyze -> Approve -> Attempt re-analyze (409!) -> Submit -> Re-submit (409!) -> Resolve
        an = client.post(f"/v1/disputeos/cases/{c1['id']}/analyze", headers=headers_a)
        assert an.status_code == 200, an.text
        assert an.json()["case"]["status"] == "DRAFT_READY"

        approved_draft = "Verified delivery."
        ap = client.post(
            f"/v1/disputeos/cases/{c1['id']}/approve",
            headers=headers_a,
            json={"approver_id": "ops@hardening.test", "draft_response_text": approved_draft},
        )
        assert ap.status_code == 200, ap.text
        assert ap.json()["status"] == "APPROVED_FOR_SUBMISSION"

        re_an = client.post(f"/v1/disputeos/cases/{c1['id']}/analyze", headers=headers_a)
        assert re_an.status_code == 409

        sub = client.post(
            f"/v1/disputeos/cases/{c1['id']}/submit",
            headers=headers_a,
            json={"draft_response_text": approved_draft},
        )
        assert sub.status_code == 200, sub.text
        assert sub.json()["case"]["status"] == "SUBMITTED"
        assert sub.json()["case"]["external_status"] == "UNDER_REVIEW"

        re_sub = client.post(
            f"/v1/disputeos/cases/{c1['id']}/submit",
            headers=headers_a,
            json={"draft_response_text": approved_draft},
        )
        assert re_sub.status_code == 409

        res = client.post(
            f"/v1/disputeos/cases/{c1['id']}/resolve",
            headers=headers_a,
            json={"reason": "MERCHANT_WON", "notes": "PayPal closed in seller favor"},
        )
        assert res.status_code == 200, res.text
        resolved = res.json()
        assert resolved["status"] == "RESOLVED"
        assert resolved["resolution_outcome"] == "MERCHANT_WON"
        assert resolved["resolved_at"] is not None

        re_res = client.post(
            f"/v1/disputeos/cases/{c1['id']}/resolve",
            headers=headers_a,
            json={"resolution_outcome": "AGAIN"},
        )
        assert re_res.status_code == 409
        up_after = client.post(
            f"/v1/disputeos/cases/{c1['id']}/artifacts",
            headers=headers_a,
            files={"file": ("late.txt", b"too late", "text/plain")},
        )
        assert up_after.status_code == 409

        with app.state.session_factory() as session:
            ledger = LedgerRepository(session)
            events = ledger.list_events(tenant_a, correlation_id=corr_1)
            event_types = [e.event_type for e in events]
            assert FinancialEventType.DISPUTE_OPENED in event_types
            assert FinancialEventType.DISPUTE_EVIDENCE_ATTACHED in event_types
            assert FinancialEventType.DISPUTE_ANALYZED in event_types
            assert FinancialEventType.DISPUTE_RESPONSE_APPROVED in event_types
            assert FinancialEventType.DISPUTE_SUBMITTED in event_types
            assert FinancialEventType.DISPUTE_RESOLVED in event_types
            ok, errs = verify_financial_event_chain(events)
            assert ok is True, errs


def test_service_blocks_backward_and_pre_approval_transitions() -> None:
    svc = DisputeCaseService()
    case = svc.create_case(
        tenant_id=TENANT_ALPHA_ID,
        correlation_id=uuid4(),
        payment_intent_id=uuid4(),
        reason="ITEM_NOT_RECEIVED",
        buyer_claim="Missing",
        amount_minor=1000,
        currency="USD",
        source_type=DisputeSourceType.PAYPAL_SANDBOX,
        is_synthetic=False,
        paypal_dispute_id="PP-D-MONOTONIC",
    )
    with pytest.raises(ApprovalGateError):
        svc.mark_submitted(tenant_id=TENANT_ALPHA_ID, case_id=case.id)

    analysis = DisputeAnalysis(
        dispute_case_id=case.id,
        tenant_id=TENANT_ALPHA_ID,
        correlation_id=case.correlation_id,
        is_synthetic=False,
        recommendation=DisputeRecommendation.CHALLENGE_WITH_EVIDENCE,
        confidence_score=0.9,
        agent_authorized=True,
        agent_followed_policy=True,
        grounded_summary="Grounded",
        draft_response_text="Response draft",
        citations=[],
        missing_evidence=[],
        contradictions=[],
    )
    svc.record_analysis(TENANT_ALPHA_ID, case.id, analysis)
    svc.approve_for_submission(
        tenant_id=TENANT_ALPHA_ID,
        case_id=case.id,
        approver_id="ops@example.com",
        draft_response_text="Response draft",
    )
    with pytest.raises(InvalidDisputeTransitionError):
        svc.record_analysis(TENANT_ALPHA_ID, case.id, analysis)


# ---------------------------------------------------------------------------
# 5. PayPal Adapter Failure Modes & Webhook Handler
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_paypal_submit_requires_dispute_id_and_preserves_state_on_upstream_errors(tmp_path: Path) -> None:
    svc = DisputeCaseService()
    no_id_case = svc.create_case(
        tenant_id=TENANT_ALPHA_ID,
        correlation_id=uuid4(),
        payment_intent_id=uuid4(),
        reason="ITEM_NOT_RECEIVED",
        buyer_claim="Missing",
        amount_minor=2000,
        currency="USD",
        source_type=DisputeSourceType.PAYPAL_SANDBOX,
        is_synthetic=False,
        paypal_dispute_id=None,
    )
    analysis = DisputeAnalysis(
        dispute_case_id=no_id_case.id,
        tenant_id=TENANT_ALPHA_ID,
        correlation_id=no_id_case.correlation_id,
        is_synthetic=False,
        recommendation=DisputeRecommendation.CHALLENGE_WITH_EVIDENCE,
        confidence_score=0.85,
        agent_authorized=True,
        agent_followed_policy=True,
        grounded_summary="Summary",
        draft_response_text="Draft",
    )
    svc.record_analysis(TENANT_ALPHA_ID, no_id_case.id, analysis)
    svc.approve_for_submission(
        tenant_id=TENANT_ALPHA_ID,
        case_id=no_id_case.id,
        approver_id="ops@example.com",
        draft_response_text="Draft",
    )
    cfg = NexusSettings(
        paypal_mode="sandbox",
        paypal_disputes_api_enabled=True,
        paypal_client_id="sb-id",
        paypal_client_secret="sb-secret",
    )
    ok_client = PayPalSandboxClient(
        settings=cfg,
        http_client=httpx.AsyncClient(
            base_url=PAYPAL_SANDBOX_BASE_URL,
            transport=httpx.MockTransport(
                lambda r: httpx.Response(200, json={"access_token": "tok", "expires_in": 300})
                if r.url.path == "/v1/oauth2/token"
                else httpx.Response(200, json={"status": "OK"})
            ),
        ),
    )
    adapter = PayPalDisputeAdapter(settings=cfg, paypal_client=ok_client)
    with pytest.raises(ValueError, match="paypal_dispute_id"):
        await adapter.submit_dispute_response(
            case=svc.get_case(TENANT_ALPHA_ID, no_id_case.id),
            draft_response_text="Draft",
            evidence_records=[],
        )
    assert svc.get_case(TENANT_ALPHA_ID, no_id_case.id).status == DisputeStatus.APPROVED_FOR_SUBMISSION

    mode = {"behavior": "500"}

    def _failing_pp(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v1/oauth2/token":
            return httpx.Response(200, json={"access_token": "tok", "expires_in": 300})
        if mode["behavior"] == "timeout":
            raise httpx.ReadTimeout("PayPal timed out", request=request)
        return httpx.Response(500, json={"name": "INTERNAL_SERVER_ERROR", "message": "upstream failure"})

    failing_client = PayPalSandboxClient(
        settings=cfg,
        http_client=httpx.AsyncClient(
            base_url=PAYPAL_SANDBOX_BASE_URL,
            transport=httpx.MockTransport(_failing_pp),
        ),
    )
    client, app, _ = _build_persistent_app(tmp_path, paypal_client=failing_client)
    with client:
        headers, tenant_id = _register_org(client, "ppfail")
        intent_id = _seed_payment_intent_id(app, tenant_id)
        c = client.post(
            "/v1/disputeos/cases",
            headers=headers,
            json={
                "correlation_id": str(uuid4()),
                "payment_intent_id": intent_id,
                "reason": "ITEM_NOT_RECEIVED",
                "buyer_claim": "Lost",
                "amount_minor": 3000,
                "currency": "USD",
                "source_type": "PAYPAL_SANDBOX",
                "is_synthetic": False,
                "paypal_dispute_id": "PP-D-ERR-1",
            },
        ).json()
        assert client.post(f"/v1/disputeos/cases/{c['id']}/analyze", headers=headers).status_code == 200
        approved_draft = "Proof attached."
        ap = client.post(
            f"/v1/disputeos/cases/{c['id']}/approve",
            headers=headers,
            json={"approver_id": "ops@test", "draft_response_text": approved_draft},
        )
        assert ap.status_code == 200, ap.text

        r_502 = client.post(
            f"/v1/disputeos/cases/{c['id']}/submit",
            headers=headers,
            json={"draft_response_text": approved_draft},
        )
        assert r_502.status_code == 502
        assert client.get(f"/v1/disputeos/cases/{c['id']}", headers=headers).json()["case"]["status"] == "APPROVED_FOR_SUBMISSION"

        mode["behavior"] = "timeout"
        r_504 = client.post(
            f"/v1/disputeos/cases/{c['id']}/submit",
            headers=headers,
            json={"draft_response_text": approved_draft},
        )
        assert r_504.status_code == 504
        assert client.get(f"/v1/disputeos/cases/{c['id']}", headers=headers).json()["case"]["status"] == "APPROVED_FOR_SUBMISSION"


@pytest.mark.asyncio
async def test_paypal_accept_claim_and_timeout_error() -> None:
    cfg = NexusSettings(
        paypal_mode="sandbox",
        paypal_disputes_api_enabled=True,
        paypal_client_id="sb-id",
        paypal_client_secret="sb-secret",
    )
    case = _make_case(status=DisputeStatus.APPROVED_FOR_SUBMISSION, paypal_dispute_id="PP-D-ACC-1")
    case = case.model_copy(
        update={
            "human_approved_for_submission": True,
            "approved_by": "ops@example.com",
            "response_payload_hash": compute_payload_hash({"draft_response_text": "Accepting claim"}),
        }
    )

    def _accept_handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v1/oauth2/token":
            return httpx.Response(200, json={"access_token": "tok", "expires_in": 300})
        if request.url.path.endswith("/accept-claim"):
            return httpx.Response(200, json={"status": "RESOLVED"})
        raise AssertionError(f"Unexpected path {request.url.path}")

    adapter = PayPalDisputeAdapter(
        settings=cfg,
        paypal_client=PayPalSandboxClient(
            settings=cfg,
            http_client=httpx.AsyncClient(
                base_url=PAYPAL_SANDBOX_BASE_URL,
                transport=httpx.MockTransport(_accept_handler),
            ),
        ),
    )
    res = await adapter.accept_dispute_claim(case=case, note="Accepting refund per policy")
    assert res["submitted"] is True
    assert res["status"] == "CLAIM_ACCEPTED"
    assert res["refund_issued"] is True
    assert res["paypal_dispute_id"] == "PP-D-ACC-1"

    err_adapter = PayPalDisputeAdapter(
        settings=cfg,
        paypal_client=PayPalSandboxClient(
            settings=cfg,
            http_client=httpx.AsyncClient(
                base_url=PAYPAL_SANDBOX_BASE_URL,
                transport=httpx.MockTransport(
                    lambda r: httpx.Response(200, json={"access_token": "tok", "expires_in": 300})
                    if r.url.path == "/v1/oauth2/token"
                    else httpx.Response(503, json={"message": "unavailable"})
                ),
            ),
        ),
    )
    with pytest.raises(PayPalAPIError):
        await err_adapter.accept_dispute_claim(case=case, note="Retry")

    timeout_adapter = PayPalDisputeAdapter(
        settings=cfg,
        paypal_client=PayPalSandboxClient(
            settings=cfg,
            http_client=httpx.AsyncClient(
                base_url=PAYPAL_SANDBOX_BASE_URL,
                transport=httpx.MockTransport(
                    lambda r: httpx.Response(200, json={"access_token": "tok", "expires_in": 300})
                    if r.url.path == "/v1/oauth2/token"
                    else (_ for _ in ()).throw(httpx.ReadTimeout("timeout", request=r))
                ),
            ),
        ),
    )
    with pytest.raises(PayPalTimeoutError):
        await timeout_adapter.accept_dispute_claim(case=case, note="Timeout")


def test_paypal_dispute_webhook_handler_created_updated_resolved(tmp_path: Path) -> None:
    db_file = tmp_path / "pp_webhook.db"
    engine = create_db_engine(f"sqlite:///{db_file}")
    init_db(engine)
    session_factory = create_session_factory(engine)

    with session_factory() as session:
        session.add(TenantRow(id=TENANT_ALPHA_ID, name="Alpha Org", slug="alpha-org"))
        session.flush()
        repo = LedgerRepository(session)
        seeded = ensure_synthetic_sandbox_payment_chain(repo, TENANT_ALPHA_ID)
        intent = seeded["payment_intent"]
        session.add(
            PaymentAttemptRow(
                id=uuid4(),
                tenant_id=TENANT_ALPHA_ID,
                correlation_id=intent.correlation_id,
                payment_intent_id=intent.id,
                idempotency_key=f"idem-{uuid4().hex[:8]}",
                paypal_order_id="ORD-PP-WH-1",
                verified_capture={"paypal_capture_id": "CAP-PP-WH-1"},
                state="CAPTURED",
                created_at=_utc(),
                updated_at=_utc(),
            )
        )
        session.flush()

        created_res = handle_paypal_dispute_webhook(
            repo,
            "CUSTOMER.DISPUTE.CREATED",
            {
                "dispute_id": "PP-D-WH-100",
                "reason": "MERCHANDISE_OR_SERVICE_NOT_RECEIVED",
                "status": "OPEN",
                "seller_response_due_date": "2026-07-10T23:59:59Z",
                "dispute_amount": {"value": "39.00", "currency_code": "USD"},
                "disputed_transactions": [
                    {"seller_transaction_id": "CAP-PP-WH-1", "buyer_transaction_id": "ORD-PP-WH-1"}
                ],
                "messages": [{"content": "Never received my order"}],
            },
            "WH-EV-1",
        )
        assert created_res["handled"] is True
        assert created_res["action"] == "created"
        case_id = UUID(created_res["case_id"])
        created_case = repo.get_dispute_case(TENANT_ALPHA_ID, case_id)
        assert created_case is not None
        assert created_case.paypal_dispute_id == "PP-D-WH-100"
        assert created_case.response_due_by is not None
        assert created_case.external_status == "OPEN"

        updated_res = handle_paypal_dispute_webhook(
            repo,
            "CUSTOMER.DISPUTE.UPDATED",
            {
                "dispute_id": "PP-D-WH-100",
                "status": "UNDER_REVIEW",
                "seller_response_due_date": "2026-07-12T23:59:59Z",
            },
            "WH-EV-2",
        )
        assert updated_res["handled"] is True
        assert updated_res["action"] == "updated"
        updated_case = repo.get_dispute_case(TENANT_ALPHA_ID, case_id)
        assert updated_case is not None
        assert updated_case.external_status == "UNDER_REVIEW"

        resolved_res = handle_paypal_dispute_webhook(
            repo,
            "CUSTOMER.DISPUTE.RESOLVED",
            {
                "dispute_id": "PP-D-WH-100",
                "status": "RESOLVED",
                "dispute_outcome": {"outcome_code": "RESOLVED_SELLER_FAVOUR"},
            },
            "WH-EV-3",
        )
        assert resolved_res["handled"] is True
        assert resolved_res["action"] == "resolved"
        final_case = repo.get_dispute_case(TENANT_ALPHA_ID, case_id)
        assert final_case is not None
        assert final_case.status == DisputeStatus.RESOLVED
        assert final_case.resolution_outcome == "RESOLVED_SELLER_FAVOUR"
        assert final_case.resolved_at is not None

        events = repo.list_events(TENANT_ALPHA_ID, correlation_id=intent.correlation_id)
        ok, errs = verify_financial_event_chain(events)
        assert ok is True, errs
