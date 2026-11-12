"""FastAPI router for DisputeOS case management, evidence ingestion, analysis, and guarded submission."""

from __future__ import annotations

from typing import Annotated, Any
from uuid import UUID, uuid4

from contracts import (
    DisputeAnalysis,
    DisputeCase,
    DisputeSourceType,
    DisputeStatus,
    EvidenceRecord,
    EvidenceSourceType,
)
from contracts.fixtures import build_synthetic_dispute_fixture
from fastapi import APIRouter, Body, Depends, Header, HTTPException, status
from paypal import PayPalDisputesDisabledError
from pydantic import BaseModel, Field
from security import TenantIsolationError, assert_same_tenant
from security.settings import DEFAULT_TENANT_UUID

from disputeos.analysis.analyzer import DisputeAnalyzer
from disputeos.cases.service import (
    ApprovalGateError,
    CaseNotFoundError,
    DisputeCaseService,
    DisputeTransitionError,
    SyntheticSubmissionError,
)
from disputeos.evidence.graph import EvidenceGraph, build_evidence_graph
from disputeos.ingestion.normalizer import DocumentIngestionService
from disputeos.paypal.adapter import PayPalDisputeAdapter
from disputeos.reports.generator import DisputeReport, generate_case_report


class CreateDisputeCaseRequest(BaseModel):
    """Request payload for creating a dispute case."""

    correlation_id: UUID = Field(default_factory=uuid4)
    payment_intent_id: UUID = Field(default_factory=uuid4)
    reason: str = Field(min_length=1, max_length=255)
    buyer_claim: str = Field(min_length=1, max_length=2000)
    amount_minor: int = Field(gt=0)
    currency: str = Field(default="USD", min_length=3, max_length=3)
    source_type: DisputeSourceType = DisputeSourceType.SYNTHETIC_DEMO
    is_synthetic: bool = True
    paypal_dispute_id: str | None = Field(default=None, max_length=128)
    case_id: UUID | None = None
    evidence_records: list[EvidenceRecord] | None = None


class AttachEvidenceRequest(BaseModel):
    """Request payload for ingesting and attaching evidence to a dispute case."""

    tenant_id: UUID | None = None
    correlation_id: UUID | None = None
    payment_intent_id: UUID | None = None
    source_type: EvidenceSourceType
    source_ref: str = Field(min_length=1, max_length=255)
    title: str = Field(min_length=1, max_length=255)
    content: dict[str, Any] = Field(default_factory=dict)
    is_synthetic: bool = False


class ApproveDisputeRequest(BaseModel):
    """Human approval payload binding approver identity and draft response hash."""

    approver_id: str = Field(min_length=1, max_length=128)
    draft_response_text: str = Field(min_length=1, max_length=4000)


class SubmitDisputeRequest(BaseModel):
    """Optional submission payload containing the approved draft response text."""

    draft_response_text: str | None = Field(default=None, max_length=4000)


class ResolveDisputeRequest(BaseModel):
    """Request payload for marking a dispute case resolved."""

    resolution_outcome: str = Field(min_length=1, max_length=128)
    notes: str | None = Field(default=None, max_length=4000)


class DisputeCaseDetailResponse(BaseModel):
    """Combined dispute case, attached evidence, and latest analysis."""

    case: DisputeCase
    evidence: list[EvidenceRecord] = Field(default_factory=list)
    latest_analysis: DisputeAnalysis | None = None


class AttachEvidenceResponse(BaseModel):
    """Response after attaching a normalized evidence record to a case."""

    case: DisputeCase
    evidence: EvidenceRecord


class AnalyzeCaseResponse(BaseModel):
    """Response from running analysis, evidence graph, and deterministic report generation."""

    case: DisputeCase
    analysis: DisputeAnalysis
    evidence_graph: EvidenceGraph
    report: DisputeReport


class SubmitDisputeResponse(BaseModel):
    """Response from guarded PayPal dispute submission handoff."""

    case: DisputeCase
    submission: dict[str, Any]


def _resolve_tenant_id(
    x_tenant_id: Annotated[str | None, Header(alias="X-Tenant-Id")] = None,
) -> UUID:
    if x_tenant_id is None or not x_tenant_id.strip():
        return DEFAULT_TENANT_UUID
    try:
        return UUID(x_tenant_id.strip())
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid X-Tenant-Id header: {x_tenant_id}",
        ) from exc


def _raise_http_for_domain_error(exc: Exception) -> None:
    if isinstance(exc, CaseNotFoundError):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    if isinstance(exc, DisputeTransitionError):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    if isinstance(
        exc,
        (
            TenantIsolationError,
            ApprovalGateError,
            SyntheticSubmissionError,
            PayPalDisputesDisabledError,
            PermissionError,
        ),
    ):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
    if isinstance(exc, ValueError):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    raise exc


def create_disputeos_router(
    case_service: DisputeCaseService | None = None,
    analyzer: DisputeAnalyzer | None = None,
    ingestion_service: DocumentIngestionService | None = None,
    paypal_adapter: PayPalDisputeAdapter | None = None,
) -> APIRouter:
    """Create a FastAPI APIRouter for DisputeOS with injectable services."""
    svc = case_service or DisputeCaseService()
    dispute_analyzer = analyzer or DisputeAnalyzer()
    ingestor = ingestion_service or DocumentIngestionService()
    adapter = paypal_adapter or PayPalDisputeAdapter()
    approved_drafts: dict[UUID, str] = {}

    api_router = APIRouter(prefix="/disputeos", tags=["disputeos"])

    @api_router.get("/cases", response_model=list[DisputeCase])
    def list_cases(
        tenant_id: Annotated[UUID, Depends(_resolve_tenant_id)],
        limit: int = 50,
        offset: int = 0,
    ) -> list[DisputeCase]:
        try:
            return svc.list_cases(tenant_id, limit=limit, offset=offset)
        except Exception as exc:
            _raise_http_for_domain_error(exc)
            raise

    @api_router.post("/cases", response_model=DisputeCase, status_code=status.HTTP_201_CREATED)
    def create_case(
        payload: CreateDisputeCaseRequest,
        tenant_id: Annotated[UUID, Depends(_resolve_tenant_id)],
    ) -> DisputeCase:
        try:
            return svc.create_case(
                tenant_id=tenant_id,
                correlation_id=payload.correlation_id,
                payment_intent_id=payload.payment_intent_id,
                reason=payload.reason,
                buyer_claim=payload.buyer_claim,
                amount_minor=payload.amount_minor,
                currency=payload.currency,
                source_type=payload.source_type,
                is_synthetic=payload.is_synthetic,
                evidence_records=payload.evidence_records,
                paypal_dispute_id=payload.paypal_dispute_id,
                case_id=payload.case_id,
            )
        except Exception as exc:
            _raise_http_for_domain_error(exc)
            raise

    @api_router.post("/cases/seed-demo", response_model=DisputeCaseDetailResponse)
    def seed_demo_case(
        tenant_id: Annotated[UUID, Depends(_resolve_tenant_id)],
    ) -> DisputeCaseDetailResponse:
        try:
            fixture = build_synthetic_dispute_fixture()
            fixture_case: DisputeCase = fixture["dispute_case"]
            fixture_evidence: list[EvidenceRecord] = fixture["all_evidence"]

            if tenant_id == fixture_case.tenant_id:
                try:
                    existing_case = svc.get_case(tenant_id, fixture_case.id)
                    return DisputeCaseDetailResponse(
                        case=existing_case,
                        evidence=svc.get_case_evidence(tenant_id, fixture_case.id),
                        latest_analysis=svc.get_latest_analysis(tenant_id, fixture_case.id),
                    )
                except CaseNotFoundError:
                    target_case_id = fixture_case.id
                    seeded_evidence = fixture_evidence
            else:
                target_case_id = uuid4()
                seeded_evidence = [
                    ev.model_copy(
                        update={
                            "id": uuid4(),
                            "tenant_id": tenant_id,
                            "dispute_case_id": target_case_id,
                            "is_synthetic": True,
                        }
                    )
                    for ev in fixture_evidence
                ]

            created_case = svc.create_case(
                tenant_id=tenant_id,
                correlation_id=fixture_case.correlation_id,
                payment_intent_id=fixture_case.payment_intent_id,
                reason=fixture_case.reason,
                buyer_claim=fixture_case.buyer_claim,
                amount_minor=fixture_case.amount_minor,
                currency=fixture_case.currency,
                source_type=DisputeSourceType.SYNTHETIC_DEMO,
                is_synthetic=True,
                evidence_records=seeded_evidence,
                paypal_dispute_id=fixture_case.paypal_dispute_id,
                case_id=target_case_id,
            )
            return DisputeCaseDetailResponse(
                case=created_case,
                evidence=svc.get_case_evidence(tenant_id, created_case.id),
                latest_analysis=None,
            )
        except Exception as exc:
            _raise_http_for_domain_error(exc)
            raise

    @api_router.get("/cases/{case_id}", response_model=DisputeCaseDetailResponse)
    def get_case_detail(
        case_id: UUID,
        tenant_id: Annotated[UUID, Depends(_resolve_tenant_id)],
    ) -> DisputeCaseDetailResponse:
        try:
            case = svc.get_case(tenant_id, case_id)
            evidence = svc.get_case_evidence(tenant_id, case_id)
            latest_analysis = svc.get_latest_analysis(tenant_id, case_id)
            return DisputeCaseDetailResponse(
                case=case,
                evidence=evidence,
                latest_analysis=latest_analysis,
            )
        except Exception as exc:
            _raise_http_for_domain_error(exc)
            raise

    @api_router.post("/cases/{case_id}/evidence", response_model=AttachEvidenceResponse)
    def attach_evidence(
        case_id: UUID,
        payload: AttachEvidenceRequest,
        tenant_id: Annotated[UUID, Depends(_resolve_tenant_id)],
    ) -> AttachEvidenceResponse:
        try:
            if payload.tenant_id is not None:
                assert_same_tenant(tenant_id, payload.tenant_id, "evidence_record")
            case = svc.get_case(tenant_id, case_id)
            record = ingestor.ingest_document(
                tenant_id=tenant_id,
                correlation_id=payload.correlation_id or case.correlation_id,
                payment_intent_id=payload.payment_intent_id or case.payment_intent_id,
                dispute_case_id=case.id,
                source_type=payload.source_type,
                source_ref=payload.source_ref,
                title=payload.title,
                content=payload.content,
                is_synthetic=payload.is_synthetic,
            )
            updated_case = svc.attach_evidence(tenant_id, case_id, [record])
            return AttachEvidenceResponse(case=updated_case, evidence=record)
        except Exception as exc:
            _raise_http_for_domain_error(exc)
            raise

    @api_router.post("/cases/{case_id}/analyze", response_model=AnalyzeCaseResponse)
    def analyze_case(
        case_id: UUID,
        tenant_id: Annotated[UUID, Depends(_resolve_tenant_id)],
    ) -> AnalyzeCaseResponse:
        try:
            case = svc.get_case(tenant_id, case_id)
            evidence = svc.get_case_evidence(tenant_id, case_id)
            analysis = dispute_analyzer.analyze(case=case, evidence=evidence)
            updated_case = svc.record_analysis(tenant_id, case_id, analysis)
            evidence_graph = build_evidence_graph(updated_case, evidence)
            report = generate_case_report(updated_case, analysis, evidence)
            return AnalyzeCaseResponse(
                case=updated_case,
                analysis=analysis,
                evidence_graph=evidence_graph,
                report=report,
            )
        except Exception as exc:
            _raise_http_for_domain_error(exc)
            raise

    @api_router.post("/cases/{case_id}/approve", response_model=DisputeCase)
    def approve_case(
        case_id: UUID,
        payload: ApproveDisputeRequest,
        tenant_id: Annotated[UUID, Depends(_resolve_tenant_id)],
    ) -> DisputeCase:
        try:
            updated_case = svc.approve_for_submission(
                tenant_id=tenant_id,
                case_id=case_id,
                approver_id=payload.approver_id,
                draft_response_text=payload.draft_response_text,
            )
            approved_drafts[case_id] = payload.draft_response_text
            return updated_case
        except Exception as exc:
            _raise_http_for_domain_error(exc)
            raise

    @api_router.post("/cases/{case_id}/submit", response_model=SubmitDisputeResponse)
    async def submit_case(
        case_id: UUID,
        tenant_id: Annotated[UUID, Depends(_resolve_tenant_id)],
        payload: Annotated[SubmitDisputeRequest | None, Body()] = None,
    ) -> SubmitDisputeResponse:
        try:
            case = svc.get_case(tenant_id, case_id)
            if (
                not case.human_approved_for_submission
                or case.status != DisputeStatus.APPROVED_FOR_SUBMISSION
                or not case.approved_by
                or not case.response_payload_hash
            ):
                raise ApprovalGateError(
                    f"Dispute case {case_id} requires explicit human approval before submission"
                )
            if case.is_synthetic or case.source_type == DisputeSourceType.SYNTHETIC_DEMO:
                raise SyntheticSubmissionError(
                    f"Synthetic dispute case {case_id} cannot be submitted externally"
                )

            if payload is not None and payload.draft_response_text is not None:
                draft_text = payload.draft_response_text
            elif case_id in approved_drafts:
                draft_text = approved_drafts[case_id]
            else:
                latest = svc.get_latest_analysis(tenant_id, case_id)
                draft_text = latest.draft_response_text if latest is not None else ""

            submission = await adapter.submit_dispute_response(
                case=case,
                draft_response_text=draft_text,
            )
            updated_case = svc.mark_submitted(tenant_id=tenant_id, case_id=case_id)
            return SubmitDisputeResponse(case=updated_case, submission=submission)
        except Exception as exc:
            _raise_http_for_domain_error(exc)
            raise

    @api_router.post("/cases/{case_id}/resolve", response_model=DisputeCase)
    def resolve_case(
        case_id: UUID,
        payload: ResolveDisputeRequest,
        tenant_id: Annotated[UUID, Depends(_resolve_tenant_id)],
    ) -> DisputeCase:
        try:
            return svc.mark_resolved(
                tenant_id=tenant_id,
                case_id=case_id,
                resolution_outcome=payload.resolution_outcome,
            )
        except Exception as exc:
            _raise_http_for_domain_error(exc)
            raise

    @api_router.get("/cases/{case_id}/artifacts/{artifact_id}")
    def download_evidence_artifact(
        case_id: UUID,
        artifact_id: UUID,
        tenant_id: Annotated[UUID, Depends(_resolve_tenant_id)],
    ) -> dict[str, Any]:
        try:
            svc.get_case(tenant_id, case_id)
            evidence_list = svc.get_case_evidence(tenant_id, case_id)
            matching = [ev for ev in evidence_list if ev.id == artifact_id]
            if not matching:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=f"Artifact {artifact_id} not found in case {case_id}",
                )
            art = matching[0]
            if art.dispute_case_id and art.dispute_case_id != case_id:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=f"Artifact {artifact_id} does not belong to case {case_id}",
                )
            return {"artifact_id": str(art.id), "content": art.content, "title": art.title}
        except Exception as exc:
            _raise_http_for_domain_error(exc)
            raise

    return api_router


router = create_disputeos_router()
