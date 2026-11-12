"""Session-per-request persistent DisputeOS router with artifact storage, assignments, and reports."""

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
from database import LedgerRepository, LocalObjectStorage, PlatformRepository
from disputeos.analysis.analyzer import DisputeAnalyzer
from disputeos.api.router import (
    AnalyzeCaseResponse,
    ApproveDisputeRequest,
    AttachEvidenceRequest,
    AttachEvidenceResponse,
    CreateDisputeCaseRequest,
    DisputeCaseDetailResponse,
    SubmitDisputeRequest,
    SubmitDisputeResponse,
    _raise_http_for_domain_error,
)
from disputeos.cases.service import (
    ApprovalGateError,
    CaseNotFoundError,
    DisputeCaseService,
    SyntheticSubmissionError,
)
from disputeos.evidence.graph import build_evidence_graph
from disputeos.ingestion.normalizer import DocumentIngestionService
from disputeos.paypal.adapter import PayPalDisputeAdapter
from disputeos.reports.generator import DisputeReport, generate_case_report
from fastapi import (
    APIRouter,
    Body,
    Depends,
    File,
    Form,
    HTTPException,
    Response,
    UploadFile,
    status,
)
from pydantic import BaseModel, ConfigDict, Field
from security import AuthContext, Permission, assert_same_tenant
from sqlalchemy.orm import Session

from aegis_api.adapters import ensure_synthetic_sandbox_payment_chain
from aegis_api.deps import get_db_session, get_object_storage, require_permission

router = APIRouter(prefix="/disputeos", tags=["disputeos"])


class AssignDisputeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    assigned_to: str = Field(max_length=160)


class AddDisputeNoteRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    body: str = Field(min_length=1, max_length=2000)


class ResolveDisputeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    resolution_outcome: str = Field(min_length=1, max_length=128)
    notes: str | None = Field(default=None, max_length=4000)


def _build_services(session: Session) -> tuple[LedgerRepository, PlatformRepository, DisputeCaseService]:
    ledger = LedgerRepository(session)
    platform = PlatformRepository(session)
    svc = DisputeCaseService(repo=ledger)
    return ledger, platform, svc


@router.get("/cases", response_model=list[DisputeCase])
def list_cases(
    auth: Annotated[AuthContext, Depends(require_permission(Permission.DISPUTES_READ))],
    session: Annotated[Session, Depends(get_db_session)],
    status_filter: DisputeStatus | None = None,
    is_synthetic: bool | None = None,
    limit: int = 50,
    offset: int = 0,
) -> list[DisputeCase]:
    _, _, svc = _build_services(session)
    cases = svc.list_cases(auth.tenant_id, limit=limit, offset=offset)
    if status_filter is not None:
        cases = [c for c in cases if c.status == status_filter]
    if is_synthetic is not None:
        cases = [c for c in cases if c.is_synthetic == is_synthetic]
    return cases


@router.post("/cases", response_model=DisputeCase, status_code=status.HTTP_201_CREATED)
def create_case(
    payload: CreateDisputeCaseRequest,
    auth: Annotated[AuthContext, Depends(require_permission(Permission.DISPUTES_WRITE))],
    session: Annotated[Session, Depends(get_db_session)],
) -> DisputeCase:
    _, _, svc = _build_services(session)
    try:
        return svc.create_case(
            tenant_id=auth.tenant_id,
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
            actor_id=auth.actor_id,
        )
    except Exception as exc:
        _raise_http_for_domain_error(exc)
        raise


@router.post("/cases/seed-demo", response_model=DisputeCaseDetailResponse)
def seed_demo_case(
    auth: Annotated[AuthContext, Depends(require_permission(Permission.DISPUTES_WRITE))],
    session: Annotated[Session, Depends(get_db_session)],
) -> DisputeCaseDetailResponse:
    """Seed a clearly labeled synthetic demo purchase + dispute chain scoped to the caller's tenant."""
    ledger, _, svc = _build_services(session)
    try:
        seeded = ensure_synthetic_sandbox_payment_chain(ledger, auth.tenant_id)
        intent = seeded["payment_intent"]
        dispute_fx = seeded["dispute_fixture"]
        fixture_case: DisputeCase = dispute_fx["dispute_case"]
        fixture_evidence: list[EvidenceRecord] = dispute_fx["all_evidence"]

        if auth.tenant_id == fixture_case.tenant_id:
            try:
                existing = svc.get_case(auth.tenant_id, fixture_case.id)
                return DisputeCaseDetailResponse(
                    case=existing,
                    evidence=svc.get_case_evidence(auth.tenant_id, existing.id),
                    latest_analysis=svc.get_latest_analysis(auth.tenant_id, existing.id),
                )
            except CaseNotFoundError:
                target_case_id = fixture_case.id
        else:
            existing_list = [c for c in svc.list_cases(auth.tenant_id) if c.is_synthetic and c.payment_intent_id == intent.id]
            if existing_list:
                existing = existing_list[0]
                return DisputeCaseDetailResponse(
                    case=existing,
                    evidence=svc.get_case_evidence(auth.tenant_id, existing.id),
                    latest_analysis=svc.get_latest_analysis(auth.tenant_id, existing.id),
                )
            target_case_id = uuid4()

        scoped_evidence = [
            ev.model_copy(
                update={
                    "id": ev.id if auth.tenant_id == fixture_case.tenant_id else uuid4(),
                    "tenant_id": auth.tenant_id,
                    "correlation_id": intent.correlation_id,
                    "payment_intent_id": intent.id,
                    "dispute_case_id": target_case_id,
                    "is_synthetic": True,
                }
            )
            for ev in fixture_evidence
        ]
        created = svc.create_case(
            tenant_id=auth.tenant_id,
            correlation_id=intent.correlation_id,
            payment_intent_id=intent.id,
            reason=fixture_case.reason,
            buyer_claim=fixture_case.buyer_claim,
            amount_minor=fixture_case.amount_minor,
            currency=fixture_case.currency,
            source_type=DisputeSourceType.SYNTHETIC_DEMO,
            is_synthetic=True,
            evidence_records=scoped_evidence,
            paypal_dispute_id=None,
            case_id=target_case_id,
            actor_id=auth.actor_id,
        )
        return DisputeCaseDetailResponse(
            case=created,
            evidence=svc.get_case_evidence(auth.tenant_id, created.id),
            latest_analysis=None,
        )
    except Exception as exc:
        _raise_http_for_domain_error(exc)
        raise


@router.get("/cases/{case_id}")
def get_case_detail(
    case_id: UUID,
    auth: Annotated[AuthContext, Depends(require_permission(Permission.DISPUTES_READ))],
    session: Annotated[Session, Depends(get_db_session)],
) -> dict[str, Any]:
    _, platform, svc = _build_services(session)
    try:
        case = svc.get_case(auth.tenant_id, case_id)
        evidence = svc.get_case_evidence(auth.tenant_id, case_id)
        latest_analysis = svc.get_latest_analysis(auth.tenant_id, case_id)
        meta = platform.get_dispute_metadata(auth.tenant_id, case_id)
        artifacts = platform.list_evidence_artifacts(auth.tenant_id, [ev.id for ev in evidence])
        graph = build_evidence_graph(case, evidence)
        return {
            "case": case.model_dump(mode="json"),
            "evidence": [ev.model_dump(mode="json") for ev in evidence],
            "latest_analysis": latest_analysis.model_dump(mode="json") if latest_analysis else None,
            "evidence_graph": graph.model_dump(mode="json"),
            "assigned_to": meta.assigned_to if meta else None,
            "notes": meta.notes if meta else [],
            "artifacts": [
                {
                    "id": str(a.id),
                    "evidence_record_id": str(a.evidence_record_id),
                    "filename": a.filename,
                    "content_type": a.content_type,
                    "byte_size": a.byte_size,
                    "sha256": a.sha256,
                    "storage_backend": a.storage_backend,
                    "created_at": a.created_at.isoformat(),
                }
                for a in artifacts
            ],
        }
    except Exception as exc:
        _raise_http_for_domain_error(exc)
        raise


@router.post("/cases/{case_id}/evidence", response_model=AttachEvidenceResponse)
def attach_evidence(
    case_id: UUID,
    payload: AttachEvidenceRequest,
    auth: Annotated[AuthContext, Depends(require_permission(Permission.DISPUTES_WRITE))],
    session: Annotated[Session, Depends(get_db_session)],
) -> AttachEvidenceResponse:
    _, _, svc = _build_services(session)
    ingestor = DocumentIngestionService()
    try:
        if payload.tenant_id is not None:
            assert_same_tenant(auth.tenant_id, payload.tenant_id, "evidence_record")
        case = svc.get_case(auth.tenant_id, case_id)
        record = ingestor.ingest_document(
            tenant_id=auth.tenant_id,
            correlation_id=payload.correlation_id or case.correlation_id,
            payment_intent_id=payload.payment_intent_id or case.payment_intent_id,
            dispute_case_id=case.id,
            source_type=payload.source_type,
            source_ref=payload.source_ref,
            title=payload.title,
            content=payload.content,
            is_synthetic=payload.is_synthetic,
        )
        updated_case = svc.attach_evidence(auth.tenant_id, case_id, [record])
        return AttachEvidenceResponse(case=updated_case, evidence=record)
    except Exception as exc:
        _raise_http_for_domain_error(exc)
        raise


@router.post("/cases/{case_id}/artifacts", status_code=status.HTTP_201_CREATED)
async def upload_evidence_artifact(
    case_id: UUID,
    auth: Annotated[AuthContext, Depends(require_permission(Permission.DISPUTES_WRITE))],
    session: Annotated[Session, Depends(get_db_session)],
    storage: Annotated[LocalObjectStorage, Depends(get_object_storage)],
    file: Annotated[UploadFile, File(...)],
    title: Annotated[str, Form()] = "Uploaded Evidence Document",
    source_type: Annotated[EvidenceSourceType, Form()] = EvidenceSourceType.DELIVERY_RECEIPT,
) -> dict[str, Any]:
    _, platform, svc = _build_services(session)
    ingestor = DocumentIngestionService()
    try:
        case = svc.get_case(auth.tenant_id, case_id)
        raw = await file.read()
        if not raw:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Uploaded file is empty")
        if len(raw) > 10 * 1024 * 1024:
            raise HTTPException(status_code=413, detail="Artifact exceeds 10 MB size limit")

        artifact_id = uuid4()
        meta = storage.put_bytes(
            tenant_id=auth.tenant_id,
            artifact_id=artifact_id,
            filename=file.filename or "evidence.bin",
            data=raw,
            content_type=file.content_type or "application/octet-stream",
        )
        record = ingestor.ingest_document(
            tenant_id=auth.tenant_id,
            correlation_id=case.correlation_id,
            payment_intent_id=case.payment_intent_id,
            dispute_case_id=case.id,
            source_type=source_type,
            source_ref=f"artifact:{meta.object_key}",
            title=title,
            content={
                "artifact_id": str(artifact_id),
                "filename": meta.filename,
                "content_type": meta.content_type,
                "byte_size": meta.byte_size,
                "sha256": meta.sha256,
            },
            is_synthetic=case.is_synthetic,
        )
        svc.attach_evidence(auth.tenant_id, case_id, [record])
        art_row = platform.save_evidence_artifact(
            artifact_id=artifact_id,
            tenant_id=auth.tenant_id,
            evidence_record_id=record.id,
            storage_backend=meta.storage_backend,
            object_key=meta.object_key,
            filename=meta.filename,
            content_type=meta.content_type,
            byte_size=meta.byte_size,
            sha256=meta.sha256,
        )
        return {
            "artifact_id": str(art_row.id),
            "evidence_record_id": str(record.id),
            "filename": art_row.filename,
            "byte_size": art_row.byte_size,
            "sha256": art_row.sha256,
        }
    except HTTPException:
        raise
    except Exception as exc:
        _raise_http_for_domain_error(exc)
        raise


@router.get("/cases/{case_id}/artifacts/{artifact_id}")
def download_evidence_artifact(
    case_id: UUID,
    artifact_id: UUID,
    auth: Annotated[AuthContext, Depends(require_permission(Permission.DISPUTES_READ))],
    session: Annotated[Session, Depends(get_db_session)],
    storage: Annotated[LocalObjectStorage, Depends(get_object_storage)],
) -> Response:
    _, platform, svc = _build_services(session)
    try:
        svc.get_case(auth.tenant_id, case_id)
        evidence_list = svc.get_case_evidence(auth.tenant_id, case_id)
        case_ev_ids = {ev.id for ev in evidence_list}

        art = platform.get_evidence_artifact(auth.tenant_id, artifact_id)
        if art is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Artifact not found")

        # Anti-IDOR check: verify artifact belongs to this case's evidence records
        if art.evidence_record_id not in case_ev_ids and getattr(art, "dispute_case_id", None) != case_id:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Artifact does not belong to specified case")

        raw = storage.get_bytes(tenant_id=auth.tenant_id, object_key=art.object_key, expected_sha256=art.sha256)
        return Response(
            content=raw,
            media_type=art.content_type,
            headers={"Content-Disposition": f'attachment; filename="{art.filename}"'},
        )
    except HTTPException:
        raise
    except Exception as exc:
        _raise_http_for_domain_error(exc)
        raise


@router.post("/cases/{case_id}/resolve", response_model=DisputeCase)
def resolve_case(
    case_id: UUID,
    payload: ResolveDisputeRequest,
    auth: Annotated[AuthContext, Depends(require_permission(Permission.DISPUTES_WRITE))],
    session: Annotated[Session, Depends(get_db_session)],
) -> DisputeCase:
    _, _, svc = _build_services(session)
    try:
        return svc.mark_resolved(
            tenant_id=auth.tenant_id,
            case_id=case_id,
            resolution_outcome=payload.resolution_outcome,
            actor_id=auth.actor_id,
        )
    except Exception as exc:
        _raise_http_for_domain_error(exc)
        raise


@router.post("/cases/{case_id}/assign")
def assign_dispute(
    case_id: UUID,
    payload: AssignDisputeRequest,
    auth: Annotated[AuthContext, Depends(require_permission(Permission.DISPUTES_WRITE))],
    session: Annotated[Session, Depends(get_db_session)],
) -> dict[str, Any]:
    _, platform, svc = _build_services(session)
    try:
        svc.get_case(auth.tenant_id, case_id)
        meta = platform.assign_dispute_case(auth.tenant_id, case_id, payload.assigned_to)
        platform.record_admin_audit(
            tenant_id=auth.tenant_id,
            actor_type=auth.actor_type,
            actor_id=auth.actor_id,
            action="DISPUTE_ASSIGNED",
            resource_type="dispute_case",
            resource_id=str(case_id),
            details={"assigned_to": meta.assigned_to},
        )
        return {"case_id": str(case_id), "assigned_to": meta.assigned_to}
    except Exception as exc:
        _raise_http_for_domain_error(exc)
        raise


@router.post("/cases/{case_id}/notes")
def add_dispute_note(
    case_id: UUID,
    payload: AddDisputeNoteRequest,
    auth: Annotated[AuthContext, Depends(require_permission(Permission.DISPUTES_WRITE))],
    session: Annotated[Session, Depends(get_db_session)],
) -> dict[str, Any]:
    _, platform, svc = _build_services(session)
    try:
        svc.get_case(auth.tenant_id, case_id)
        author = auth.email or auth.actor_id
        meta = platform.add_dispute_note(tenant_id=auth.tenant_id, case_id=case_id, author=author, body=payload.body)
        return {"case_id": str(case_id), "notes": meta.notes}
    except Exception as exc:
        _raise_http_for_domain_error(exc)
        raise


@router.post("/cases/{case_id}/analyze", response_model=AnalyzeCaseResponse)
def analyze_case(
    case_id: UUID,
    auth: Annotated[AuthContext, Depends(require_permission(Permission.DISPUTES_WRITE))],
    session: Annotated[Session, Depends(get_db_session)],
) -> AnalyzeCaseResponse:
    _, _, svc = _build_services(session)
    analyzer = DisputeAnalyzer()
    try:
        case = svc.get_case(auth.tenant_id, case_id)
        evidence = svc.get_case_evidence(auth.tenant_id, case_id)
        analysis: DisputeAnalysis = analyzer.analyze(case=case, evidence=evidence)
        updated_case = svc.record_analysis(auth.tenant_id, case_id, analysis, actor_id=auth.actor_id)
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


@router.get("/cases/{case_id}/report", response_model=DisputeReport)
def export_case_report(
    case_id: UUID,
    auth: Annotated[AuthContext, Depends(require_permission(Permission.DISPUTES_READ))],
    session: Annotated[Session, Depends(get_db_session)],
) -> DisputeReport:
    _, _, svc = _build_services(session)
    try:
        case = svc.get_case(auth.tenant_id, case_id)
        evidence = svc.get_case_evidence(auth.tenant_id, case_id)
        analysis = svc.get_latest_analysis(auth.tenant_id, case_id)
        if analysis is None:
            analysis = DisputeAnalyzer().analyze(case=case, evidence=evidence)
        return generate_case_report(case, analysis, evidence)
    except Exception as exc:
        _raise_http_for_domain_error(exc)
        raise


@router.post("/cases/{case_id}/approve", response_model=DisputeCase)
def approve_case(
    case_id: UUID,
    payload: ApproveDisputeRequest,
    auth: Annotated[AuthContext, Depends(require_permission(Permission.DISPUTES_APPROVE))],
    session: Annotated[Session, Depends(get_db_session)],
) -> DisputeCase:
    _, _, svc = _build_services(session)
    approver = auth.email or auth.actor_id or payload.approver_id
    try:
        return svc.approve_for_submission(
            tenant_id=auth.tenant_id,
            case_id=case_id,
            approver_id=approver,
            draft_response_text=payload.draft_response_text,
        )
    except Exception as exc:
        _raise_http_for_domain_error(exc)
        raise


@router.post("/cases/{case_id}/submit", response_model=SubmitDisputeResponse)
async def submit_case(
    case_id: UUID,
    auth: Annotated[AuthContext, Depends(require_permission(Permission.DISPUTES_SUBMIT))],
    session: Annotated[Session, Depends(get_db_session)],
    payload: Annotated[SubmitDisputeRequest | None, Body()] = None,
) -> SubmitDisputeResponse:
    _, _, svc = _build_services(session)
    adapter = PayPalDisputeAdapter()
    try:
        case = svc.get_case(auth.tenant_id, case_id)
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
        else:
            latest = svc.get_latest_analysis(auth.tenant_id, case_id)
            draft_text = latest.draft_response_text if latest is not None else ""

        submission = await adapter.submit_dispute_response(
            case=case,
            draft_response_text=draft_text,
        )
        updated_case = svc.mark_submitted(tenant_id=auth.tenant_id, case_id=case_id)
        return SubmitDisputeResponse(case=updated_case, submission=submission)
    except Exception as exc:
        _raise_http_for_domain_error(exc)
        raise
