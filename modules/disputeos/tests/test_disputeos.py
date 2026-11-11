"""Mandatory domain and safety test suite for DisputeOS."""

from __future__ import annotations

from uuid import UUID, uuid4

import pytest
from contracts import (
    DisputeCase,
    DisputeRecommendation,
    DisputeSourceType,
    DisputeStatus,
    EvidenceRecord,
    EvidenceSourceType,
)
from contracts.fixtures import (
    TENANT_ALPHA_ID,
    TENANT_BETA_ID,
    build_authorized_39_purchase_fixture,
    build_synthetic_dispute_fixture,
)
from disputeos.analysis.analyzer import SYNTHETIC_BANNER, DisputeAnalyzer
from disputeos.analysis.citations import CandidateClaim, CitationValidator
from disputeos.cases.service import (
    ApprovalGateError,
    CaseNotFoundError,
    DisputeCaseService,
    SyntheticSubmissionError,
)
from disputeos.evidence.detector import detect_contradictions, detect_missing_evidence
from disputeos.evidence.graph import build_evidence_graph
from disputeos.ingestion.normalizer import DocumentIngestionService
from disputeos.paypal.adapter import PayPalDisputeAdapter
from disputeos.reports.generator import DisputeReport, generate_case_report
from paypal import PayPalDisputesDisabledError
from security import NexusSettings, TenantIsolationError


class _HallucinatingLLMReviewer:
    """Test double proposing unsupported citations alongside a real one."""

    def __init__(self, *, fake_evidence_id: UUID, real_evidence_id: UUID) -> None:
        self.fake_evidence_id = fake_evidence_id
        self.real_evidence_id = real_evidence_id

    def review(
        self,
        *,
        case: DisputeCase,
        evidence: list[EvidenceRecord],
        missing: list[str],
        contradictions: list[str],
    ) -> tuple[str, list[CandidateClaim]]:
        return (
            "AI summary referencing verified and hallucinated claims.",
            [
                CandidateClaim(
                    claim="Verified carrier log shows status DELIVERED.",
                    evidence_id=self.real_evidence_id,
                    verbatim_excerpt="DELIVERED",
                ),
                CandidateClaim(
                    claim="Buyer signed biometric courier tablet at 09:00 UTC.",
                    evidence_id=self.fake_evidence_id,
                    verbatim_excerpt="biometric courier tablet",
                ),
                CandidateClaim(
                    claim="Carrier admitted package was stolen at depot.",
                    evidence_id=self.real_evidence_id,
                    verbatim_excerpt="stolen at depot",
                ),
            ],
        )


class _AllInvalidLLMReviewer:
    """Test double returning only fabricated claims."""

    def review(
        self,
        *,
        case: DisputeCase,
        evidence: list[EvidenceRecord],
        missing: list[str],
        contradictions: list[str],
    ) -> tuple[str, list[CandidateClaim]]:
        return (
            "Fabricated summary with no real evidence.",
            [
                CandidateClaim(
                    claim="Unverified external claim.",
                    evidence_id=uuid4(),
                    verbatim_excerpt="nonexistent excerpt",
                )
            ],
        )


class _FailingLLMReviewer:
    """Test double simulating an upstream LLM error or timeout."""

    def review(
        self,
        *,
        case: DisputeCase,
        evidence: list[EvidenceRecord],
        missing: list[str],
        contradictions: list[str],
    ) -> tuple[str, list[CandidateClaim]]:
        raise RuntimeError("Simulated LLM provider outage")


def _build_complete_fulfilled_case(
    service: DisputeCaseService,
    ingestor: DocumentIngestionService,
    *,
    is_synthetic: bool = False,
    source_type: DisputeSourceType = DisputeSourceType.PAYPAL_SANDBOX,
) -> tuple[DisputeCase, list[EvidenceRecord]]:
    demo_a = build_authorized_39_purchase_fixture()
    intent = demo_a["payment_intent"]

    case = service.create_case(
        tenant_id=TENANT_ALPHA_ID,
        correlation_id=intent.correlation_id,
        payment_intent_id=intent.id,
        reason="MERCHANDISE_OR_SERVICE_NOT_RECEIVED",
        buyer_claim="Buyer requests delivery verification.",
        amount_minor=intent.amount_minor,
        currency=intent.currency,
        source_type=source_type,
        is_synthetic=is_synthetic,
        paypal_dispute_id="PP-D-1001" if not is_synthetic else None,
    )
    bundle = ingestor.ingest_transaction_bundle(
        tenant_id=TENANT_ALPHA_ID,
        payment_intent=intent,
        proposal=demo_a["proposal"],
        quote=demo_a["quote_snapshot"],
        decision=demo_a["decision"],
        attempt=demo_a["attempt"],
        existing_evidence=demo_a["evidence_records"],
        dispute_case_id=case.id,
        is_synthetic=is_synthetic,
    )
    tracking = ingestor.ingest_document(
        tenant_id=TENANT_ALPHA_ID,
        correlation_id=intent.correlation_id,
        payment_intent_id=intent.id,
        dispute_case_id=case.id,
        source_type=EvidenceSourceType.CARRIER_TRACKING,
        source_ref="carrier:UPS-998877",
        title="Carrier Tracking Log (UPS-998877)",
        content={"carrier": "UPS", "tracking_number": "998877", "status": "DELIVERED"},
        is_synthetic=is_synthetic,
    )
    receipt = ingestor.ingest_document(
        tenant_id=TENANT_ALPHA_ID,
        correlation_id=intent.correlation_id,
        payment_intent_id=intent.id,
        dispute_case_id=case.id,
        source_type=EvidenceSourceType.DELIVERY_RECEIPT,
        source_ref="receipt:UPS-998877",
        title="Signed Delivery Receipt (UPS-998877)",
        content={"status": "DELIVERED", "signed_by": "FRONT_DESK"},
        is_synthetic=is_synthetic,
    )
    all_evidence = [*bundle, tracking, receipt]
    updated_case = service.attach_evidence(TENANT_ALPHA_ID, case.id, all_evidence)
    return updated_case, service.get_case_evidence(TENANT_ALPHA_ID, updated_case.id)


def test_1_evidence_citations_are_valid_and_match_existing_evidence_ids() -> None:
    """Scenario 1: All citations reference existing evidence_id records on the case."""
    fixture = build_synthetic_dispute_fixture()
    case: DisputeCase = fixture["dispute_case"]
    evidence: list[EvidenceRecord] = fixture["all_evidence"]
    valid_ids = {rec.id for rec in evidence}

    analysis = DisputeAnalyzer().analyze(case=case, evidence=evidence)

    assert len(analysis.citations) == len(evidence)
    for citation in analysis.citations:
        assert citation.verified is True
        assert citation.evidence_id in valid_ids
        assert len(citation.verbatim_excerpt.strip()) > 0


def test_2_missing_evidence_is_reported_when_artifacts_absent() -> None:
    """Scenario 2: Missing tracking, delivery receipt, and capture are explicitly reported."""
    service = DisputeCaseService()
    ingestor = DocumentIngestionService()
    demo_a = build_authorized_39_purchase_fixture()
    intent = demo_a["payment_intent"]

    case = service.create_case(
        tenant_id=TENANT_ALPHA_ID,
        correlation_id=intent.correlation_id,
        payment_intent_id=intent.id,
        reason="MERCHANDISE_OR_SERVICE_NOT_RECEIVED",
        buyer_claim="Item never arrived and no shipping proof exists.",
        amount_minor=3900,
        currency="USD",
        source_type=DisputeSourceType.PAYPAL_SANDBOX,
        is_synthetic=False,
    )
    quote_only = ingestor.ingest_document(
        tenant_id=TENANT_ALPHA_ID,
        correlation_id=intent.correlation_id,
        payment_intent_id=intent.id,
        dispute_case_id=case.id,
        source_type=EvidenceSourceType.QUOTE,
        source_ref="quote:only-1",
        title="Bound Quote Snapshot",
        content={"amount_minor": 3900, "currency": "USD"},
    )
    case = service.attach_evidence(TENANT_ALPHA_ID, case.id, [quote_only])
    evidence = service.get_case_evidence(TENANT_ALPHA_ID, case.id)

    missing = detect_missing_evidence(case, evidence)
    analysis = DisputeAnalyzer().analyze(case=case, evidence=evidence)

    joined = " | ".join(missing)
    assert "POLICY_DECISION" in joined
    assert "PAYPAL_CAPTURE" in joined
    assert "CARRIER_TRACKING" in joined
    assert "DELIVERY_RECEIPT" in joined
    assert analysis.missing_evidence == missing
    assert analysis.recommendation == DisputeRecommendation.NEED_MORE_EVIDENCE


def test_3_contradictory_delivery_claims_are_identified() -> None:
    """Scenario 3: Carrier DELIVERED vs. merchant support non-delivery is detected."""
    fixture = build_synthetic_dispute_fixture()
    case: DisputeCase = fixture["dispute_case"]
    evidence: list[EvidenceRecord] = fixture["all_evidence"]

    contradictions = detect_contradictions(case, evidence)
    analysis = DisputeAnalyzer().analyze(case=case, evidence=evidence)

    assert len(contradictions) >= 1
    assert any(
        "CARRIER_TRACKING" in item and "CUSTOMER_MESSAGE" in item and "DELIVERED" in item
        for item in contradictions
    )
    assert analysis.contradictions == contradictions
    assert analysis.merchant_fulfilled_order is False
    assert analysis.recommendation == DisputeRecommendation.ACCEPT_AND_REFUND


def test_4_dispute_summaries_are_grounded_in_available_evidence() -> None:
    """Scenario 4: Grounded summaries accurately reflect verified case evidence."""
    service = DisputeCaseService()
    ingestor = DocumentIngestionService()
    case, evidence = _build_complete_fulfilled_case(service, ingestor, is_synthetic=False)

    analysis = DisputeAnalyzer().analyze(case=case, evidence=evidence)
    graph = build_evidence_graph(case, evidence)

    assert analysis.agent_authorized is True
    assert analysis.agent_followed_policy is True
    assert analysis.merchant_fulfilled_order is True
    assert analysis.recommendation == DisputeRecommendation.CHALLENGE_WITH_EVIDENCE
    assert analysis.missing_evidence == []
    assert analysis.contradictions == []
    assert str(case.id) in analysis.grounded_summary
    assert "CHALLENGE_WITH_EVIDENCE" in analysis.grounded_summary
    for rec in evidence:
        assert str(rec.id) in analysis.grounded_summary
    assert len(graph.nodes) == len(evidence)
    assert len(graph.edges) >= len(evidence)


def test_5_unsupported_ai_claims_are_rejected_and_flagged() -> None:
    """Scenario 5: Hallucinated evidence_ids and unverifiable excerpts are rejected."""
    fixture = build_synthetic_dispute_fixture()
    case: DisputeCase = fixture["dispute_case"]
    evidence: list[EvidenceRecord] = fixture["all_evidence"]
    tracking_rec = next(r for r in evidence if r.source_type == EvidenceSourceType.CARRIER_TRACKING)

    fake_id = uuid4()
    analyzer = DisputeAnalyzer(
        llm_reviewer=_HallucinatingLLMReviewer(
            fake_evidence_id=fake_id,
            real_evidence_id=tracking_rec.id,
        )
    )
    analysis = analyzer.analyze(case=case, evidence=evidence)

    assert len(analysis.citations) == 1
    assert analysis.citations[0].evidence_id == tracking_rec.id
    assert len(analysis.rejected_claims) == 2
    rejected_blob = " ".join(analysis.rejected_claims)
    assert str(fake_id) in rejected_blob
    assert "verbatim_excerpt not found" in rejected_blob

    # When an LLM produces only invalid claims, analyzer falls back to deterministic citations
    # while preserving the rejected claims in rejected_claims.
    all_bad_analysis = DisputeAnalyzer(llm_reviewer=_AllInvalidLLMReviewer()).analyze(
        case=case,
        evidence=evidence,
    )
    assert all_bad_analysis.generated_with_llm is False
    assert len(all_bad_analysis.citations) == len(evidence)
    assert len(all_bad_analysis.rejected_claims) == 1

    # Direct CitationValidator cross-tenant check
    foreign_rec = tracking_rec.model_copy(update={"tenant_id": TENANT_BETA_ID})
    verified, rejected = CitationValidator().validate_claims(
        [
            CandidateClaim(
                claim="Cross-tenant claim",
                evidence_id=foreign_rec.id,
                verbatim_excerpt="DELIVERED",
            )
        ],
        [foreign_rec],
        TENANT_ALPHA_ID,
    )
    assert verified == []
    assert len(rejected) == 1 and "belongs to another tenant" in rejected[0]


def test_6_tenant_isolation_blocks_cross_tenant_case_and_evidence_access() -> None:
    """Scenario 6: Cross-tenant access to cases, evidence, and reports fails closed."""
    service = DisputeCaseService()
    ingestor = DocumentIngestionService()
    case, evidence = _build_complete_fulfilled_case(service, ingestor, is_synthetic=False)

    with pytest.raises(TenantIsolationError):
        service.get_case(TENANT_BETA_ID, case.id)

    with pytest.raises(TenantIsolationError):
        service.get_case_evidence(TENANT_BETA_ID, case.id)

    foreign_evidence = evidence[0].model_copy(update={"id": uuid4(), "tenant_id": TENANT_BETA_ID})
    with pytest.raises(TenantIsolationError):
        service.attach_evidence(TENANT_ALPHA_ID, case.id, [foreign_evidence])

    with pytest.raises(TenantIsolationError):
        detect_missing_evidence(case, [foreign_evidence])

    with pytest.raises(TenantIsolationError):
        build_evidence_graph(case, [foreign_evidence])

    with pytest.raises(TenantIsolationError):
        DisputeAnalyzer().analyze(case=case, evidence=[foreign_evidence])

    demo_a = build_authorized_39_purchase_fixture()
    with pytest.raises(TenantIsolationError):
        ingestor.ingest_transaction_bundle(
            tenant_id=TENANT_BETA_ID,
            payment_intent=demo_a["payment_intent"],
        )

    with pytest.raises(CaseNotFoundError):
        service.get_case(TENANT_ALPHA_ID, uuid4())


@pytest.mark.asyncio
async def test_7_human_approval_is_required_before_external_submission() -> None:
    """Scenario 7: Unapproved or tampered responses cannot be submitted externally."""
    service = DisputeCaseService()
    ingestor = DocumentIngestionService()
    case, evidence = _build_complete_fulfilled_case(service, ingestor, is_synthetic=False)
    analysis = DisputeAnalyzer().analyze(case=case, evidence=evidence)
    case = service.record_analysis(TENANT_ALPHA_ID, case.id, analysis)

    assert analysis.requires_human_approval is True
    assert case.human_approved_for_submission is False

    # Cannot mark submitted without human approval
    with pytest.raises(ApprovalGateError):
        service.mark_submitted(tenant_id=TENANT_ALPHA_ID, case_id=case.id)

    enabled_settings = NexusSettings(
        paypal_mode="sandbox",
        paypal_disputes_api_enabled=True,
    )
    adapter_enabled = PayPalDisputeAdapter(settings=enabled_settings)
    with pytest.raises(PermissionError):
        await adapter_enabled.submit_dispute_response(
            case=case,
            draft_response_text=analysis.draft_response_text,
        )

    # Approve response explicitly
    approved_case = service.approve_for_submission(
        tenant_id=TENANT_ALPHA_ID,
        case_id=case.id,
        approver_id="human-reviewer-42",
        draft_response_text=analysis.draft_response_text,
    )
    assert approved_case.human_approved_for_submission is True
    assert approved_case.approved_by == "human-reviewer-42"
    assert approved_case.status == DisputeStatus.APPROVED_FOR_SUBMISSION

    # Tampered response text is rejected by payload hash check
    with pytest.raises(PermissionError):
        await adapter_enabled.submit_dispute_response(
            case=approved_case,
            draft_response_text="Tampered response text",
        )

    # Feature flag disabled still blocks external submission even after approval
    disabled_adapter = PayPalDisputeAdapter(
        settings=NexusSettings(paypal_mode="sandbox", paypal_disputes_api_enabled=False)
    )
    with pytest.raises(PayPalDisputesDisabledError):
        await disabled_adapter.submit_dispute_response(
            case=approved_case,
            draft_response_text=analysis.draft_response_text,
        )

    # With approval + enabled flag + non-synthetic case, adapter prepares payload without auto-refund
    handoff = await adapter_enabled.submit_dispute_response(
        case=approved_case,
        draft_response_text=analysis.draft_response_text,
    )
    assert handoff["status"] == "APPROVED_PAYLOAD_READY"
    assert handoff["auto_submitted"] is False
    assert handoff["refund_issued"] is False
    submitted_case = service.mark_submitted(tenant_id=TENANT_ALPHA_ID, case_id=case.id)
    assert submitted_case.status == DisputeStatus.SUBMITTED


@pytest.mark.asyncio
async def test_8_synthetic_cases_are_labeled_and_cannot_be_submitted() -> None:
    """Scenario 8: Synthetic demo cases are clearly labeled and blocked from PayPal submission."""
    fixture = build_synthetic_dispute_fixture()
    fixture_case: DisputeCase = fixture["dispute_case"]
    evidence: list[EvidenceRecord] = fixture["all_evidence"]

    service = DisputeCaseService()
    case = service.create_case(
        tenant_id=fixture_case.tenant_id,
        correlation_id=fixture_case.correlation_id,
        payment_intent_id=fixture_case.payment_intent_id,
        reason=fixture_case.reason,
        buyer_claim=fixture_case.buyer_claim,
        amount_minor=fixture_case.amount_minor,
        currency=fixture_case.currency,
        source_type=DisputeSourceType.SYNTHETIC_DEMO,
        is_synthetic=True,
        evidence_records=evidence,
        case_id=fixture_case.id,
    )

    assert case.is_synthetic is True
    assert case.source_type == DisputeSourceType.SYNTHETIC_DEMO

    analysis = DisputeAnalyzer().analyze(case=case, evidence=evidence)
    case = service.record_analysis(case.tenant_id, case.id, analysis)
    report = generate_case_report(case, analysis, evidence)

    assert analysis.is_synthetic is True
    assert SYNTHETIC_BANNER in analysis.grounded_summary
    assert SYNTHETIC_BANNER in analysis.draft_response_text
    assert report.is_synthetic is True
    assert report.synthetic_banner == SYNTHETIC_BANNER
    assert SYNTHETIC_BANNER in report.markdown_report

    # Even if a human approves a synthetic case, submission remains strictly blocked
    approved_synthetic = service.approve_for_submission(
        tenant_id=case.tenant_id,
        case_id=case.id,
        approver_id="human-reviewer-42",
        draft_response_text=analysis.draft_response_text,
    )
    with pytest.raises(SyntheticSubmissionError):
        service.mark_submitted(tenant_id=case.tenant_id, case_id=approved_synthetic.id)

    adapter_enabled = PayPalDisputeAdapter(
        settings=NexusSettings(paypal_mode="sandbox", paypal_disputes_api_enabled=True)
    )
    with pytest.raises(ValueError, match="Synthetic"):
        await adapter_enabled.submit_dispute_response(
            case=approved_synthetic,
            draft_response_text=analysis.draft_response_text,
        )


def test_9_case_reports_generated_deterministically_without_ai_credentials(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Scenario 9: Reports and analyses succeed deterministically with no AI API keys."""
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    monkeypatch.setenv("LLM_PROVIDER", "deterministic")

    fixture = build_synthetic_dispute_fixture()
    case: DisputeCase = fixture["dispute_case"]
    evidence: list[EvidenceRecord] = fixture["all_evidence"]

    analysis = DisputeAnalyzer().analyze(case=case, evidence=evidence)
    report = generate_case_report(case, analysis, evidence)

    assert isinstance(report, DisputeReport)
    assert analysis.generated_with_llm is False
    assert report.case_id == case.id
    assert report.requires_human_approval is True
    assert len(report.citations) == len(evidence)
    assert "## Grounded Summary" in report.markdown_report
    assert "## Verified Citations" in report.markdown_report
    assert "## Contradictions Detected" in report.markdown_report
    assert "## Draft Response Text" in report.markdown_report


def test_10_failed_ai_calls_do_not_corrupt_case_state_and_fall_back_safely() -> None:
    """Scenario 10: Exceptions from an injected LLM reviewer fall back cleanly."""
    fixture = build_synthetic_dispute_fixture()
    fixture_case: DisputeCase = fixture["dispute_case"]
    evidence: list[EvidenceRecord] = fixture["all_evidence"]

    service = DisputeCaseService()
    case = service.create_case(
        tenant_id=fixture_case.tenant_id,
        correlation_id=fixture_case.correlation_id,
        payment_intent_id=fixture_case.payment_intent_id,
        reason=fixture_case.reason,
        buyer_claim=fixture_case.buyer_claim,
        amount_minor=fixture_case.amount_minor,
        currency=fixture_case.currency,
        source_type=DisputeSourceType.SYNTHETIC_DEMO,
        is_synthetic=True,
        evidence_records=evidence,
        case_id=fixture_case.id,
    )

    analysis = DisputeAnalyzer(llm_reviewer=_FailingLLMReviewer()).analyze(
        case=case,
        evidence=evidence,
    )
    updated_case = service.record_analysis(case.tenant_id, case.id, analysis)

    assert analysis.generated_with_llm is False
    assert len(analysis.citations) == len(evidence)
    assert len(analysis.contradictions) >= 1
    assert SYNTHETIC_BANNER in analysis.grounded_summary
    assert updated_case.status == DisputeStatus.DRAFT_READY
    assert updated_case.human_approved_for_submission is False
    assert updated_case.evidence_ids == [rec.id for rec in evidence]
    assert service.get_latest_analysis(case.tenant_id, case.id) == analysis
