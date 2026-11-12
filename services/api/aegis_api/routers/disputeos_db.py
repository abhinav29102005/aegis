"""Session-per-request persistent DisputeOS router with artifact storage, assignments, and reports."""

from __future__ import annotations

from datetime import datetime
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
from database import (
    DisputeCaseRow,
    EvidenceRecordRow,
    LedgerRepository,
    PlatformRepository,
)
from database.storage import ObjectSizeLimitExceededError, ObjectStorage
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
    InvalidDisputeTransitionError,
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
    Query,
    Response,
    UploadFile,
    status,
)
from paypal import (
    PayPalAPIError,
    PayPalConfigurationError,
    PayPalSandboxClient,
    PayPalTimeoutError,
)
from pydantic import BaseModel, ConfigDict, Field
from security import AuthContext, NexusSettings, Permission, assert_same_tenant
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from aegis_api.adapters import ensure_synthetic_sandbox_payment_chain
from aegis_api.deps import (
    get_app_settings,
    get_db_session,
    get_object_storage,
    get_paypal_client,
    require_permission,
)

router = APIRouter(prefix="/disputeos", tags=["disputeos"])


class CreateDisputeCaseDBRequest(CreateDisputeCaseRequest):
    response_due_by: datetime | None = None
    external_status: str | None = Field(default=None, max_length=64)


class AttachEvidenceDBRequest(AttachEvidenceRequest):
    content_hash: str | None = Field(default=None, max_length=128)


class ResolveDisputeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    resolution_outcome: str | None = Field(default=None, min_length=1, max_length=128)
    reason: str | None = Field(default=None, min_length=1, max_length=500)
    notes: str | None = Field(default=None, max_length=2000)


class AssignDisputeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    assigned_to: str = Field(max_length=160)


class AddDisputeNoteRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    body: str = Field(min_length=1, max_length=2000)


def _raise_db_http_error(exc: Exception) -> None:
    if isinstance(exc, InvalidDisputeTransitionError):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"error_code": "INVALID_DISPUTE_TRANSITION", "message": str(exc)},
        ) from exc
    if isinstance(exc, PayPalTimeoutError):
        raise HTTPException(
            status_code=status.HTTP_504_GATEWAY_TIMEOUT,
            detail={"error_code": "PAYPAL_TIMEOUT", "message": "PayPal Disputes API request timed out."},
        ) from exc
    if isinstance(exc, PayPalAPIError):
        mapped_status = (
            status.HTTP_504_GATEWAY_TIMEOUT
            if exc.status_code == 504
            else status.HTTP_502_BAD_GATEWAY
        )
        raise HTTPException(
            status_code=mapped_status,
            detail={
                "error_code": "PAYPAL_UPSTREAM_ERROR",
                "message": "PayPal Disputes API returned an error.",
                "upstream_status": exc.status_code,
            },
        ) from exc
    if isinstance(exc, PayPalConfigurationError):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"error_code": "PAYPAL_NOT_CONFIGURED", "message": "PayPal sandbox credentials are not configured."},
        ) from exc
    if isinstance(exc, ObjectSizeLimitExceededError):
        raise HTTPException(
            status_code=status.HTTP_413_CONTENT_TOO_LARGE,
            detail={"error_code": "ARTIFACT_TOO_LARGE", "message": "Artifact exceeds 10 MB size limit."},
        ) from exc
    _raise_http_for_domain_error(exc)


def _build_services(session: Session) -> tuple[LedgerRepository, PlatformRepository, DisputeCaseService]:
    ledger = LedgerRepository(session)
    platform = PlatformRepository(session)
    svc = DisputeCaseService(repo=ledger)
    return ledger, platform, svc


@router.get("/cases", response_model=list[DisputeCase])
def list_cases(
    response: Response,
    auth: Annotated[AuthContext, Depends(require_permission(Permission.DISPUTES_READ))],
    session: Annotated[Session, Depends(get_db_session)],
    status_filter: DisputeStatus | None = None,
    is_synthetic: bool | None = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[DisputeCase]:
    base_stmt = select(DisputeCaseRow).where(DisputeCaseRow.tenant_id == auth.tenant_id)
    count_stmt = select(func.count()).select_from(DisputeCaseRow).where(DisputeCaseRow.tenant_id == auth.tenant_id)
    if status_filter is not None:
        base_stmt = base_stmt.where(DisputeCaseRow.status == status_filter.value)
        count_stmt = count_stmt.where(DisputeCaseRow.status == status_filter.value)
    if is_synthetic is not None:
        base_stmt = base_stmt.where(DisputeCaseRow.is_synthetic.is_(is_synthetic))
        count_stmt = count_stmt.where(DisputeCaseRow.is_synthetic.is_(is_synthetic))

    total = int(session.scalar(count_stmt) or 0)
    response.headers["X-Total-Count"] = str(total)
    rows = session.scalars(
        base_stmt.order_by(DisputeCaseRow.opened_at.desc()).offset(offset).limit(limit)
    ).all()
    return [LedgerRepository._to_dispute_case(row) for row in rows]


@router.post("/cases", response_model=DisputeCase, status_code=status.HTTP_201_CREATED)
def create_case(
    payload: CreateDisputeCaseDBRequest,
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
            response_due_by=payload.response_due_by,
            external_status=payload.external_status,
        )
    except Exception as exc:
        _raise_db_http_error(exc)
        raise


@router.post("/cases/seed-demo", response_model=DisputeCaseDetailResponse)
def seed_demo_case(
    auth: Annotated[AuthContext, Depends(require_permission(Permission.DISPUTES_WRITE))],
    session: Annotated[Session, Depends(get_db_session)],
) -> DisputeCaseDetailResponse:
    """Seed a clearly labeled synthetic demo purchase + dispute chain scoped to the caller's tenant."""
    ledger, _, svc = _build_services(session)
    ingestor = DocumentIngestionService()
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
            ingestor.ingest_document(
                tenant_id=auth.tenant_id,
                correlation_id=intent.correlation_id,
                payment_intent_id=intent.id,
                dispute_case_id=target_case_id,
                source_type=ev.source_type,
                source_ref=ev.source_ref,
                title=ev.title,
                content=ev.content,
                is_synthetic=True,
                collected_at=ev.collected_at,
                evidence_id=ev.id if auth.tenant_id == fixture_case.tenant_id else uuid4(),
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
        _raise_db_http_error(exc)
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
        _raise_db_http_error(exc)
        raise


@router.post("/cases/{case_id}/evidence", response_model=AttachEvidenceResponse)
def attach_evidence(
    case_id: UUID,
    payload: AttachEvidenceDBRequest,
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
            content_hash=payload.content_hash,
            is_synthetic=payload.is_synthetic,
        )
        updated_case = svc.attach_evidence(
            auth.tenant_id,
            case_id,
            [record],
            actor_id=auth.actor_id,
            actor_type=auth.actor_type,
        )
        session.commit()
        return AttachEvidenceResponse(case=updated_case, evidence=record)
    except Exception as exc:
        _raise_db_http_error(exc)
        raise


@router.post("/cases/{case_id}/artifacts", status_code=status.HTTP_201_CREATED)
async def upload_evidence_artifact(
    case_id: UUID,
    auth: Annotated[AuthContext, Depends(require_permission(Permission.DISPUTES_WRITE))],
    session: Annotated[Session, Depends(get_db_session)],
    storage: Annotated[ObjectStorage, Depends(get_object_storage)],
    file: Annotated[UploadFile, File(...)],
    title: Annotated[str, Form()] = "Uploaded Evidence Document",
    source_type: Annotated[EvidenceSourceType, Form()] = EvidenceSourceType.DELIVERY_RECEIPT,
) -> dict[str, Any]:
    _, platform, svc = _build_services(session)
    ingestor = DocumentIngestionService()
    try:
        case = svc.get_case(auth.tenant_id, case_id)
        if case.status == DisputeStatus.RESOLVED:
            raise InvalidDisputeTransitionError(
                f"Cannot upload artifacts to resolved dispute case {case_id}"
            )
        artifact_id = uuid4()
        meta = storage.put_stream(
            tenant_id=auth.tenant_id,
            key_prefix=f"disputes/{case_id}/{artifact_id}",
            stream=file.file,
            max_bytes=10 * 1024 * 1024,
            filename=file.filename or "evidence.bin",
            content_type=file.content_type or "application/octet-stream",
        )
        if meta.byte_size == 0:
            storage.delete(tenant_id=auth.tenant_id, object_key=meta.object_key)
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Uploaded file is empty")

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
        svc.attach_evidence(
            auth.tenant_id,
            case_id,
            [record],
            actor_id=auth.actor_id,
            actor_type=auth.actor_type,
        )
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
        session.commit()
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
        _raise_db_http_error(exc)
        raise


@router.get("/cases/{case_id}/artifacts/{artifact_id}")
def download_evidence_artifact(
    case_id: UUID,
    artifact_id: UUID,
    auth: Annotated[AuthContext, Depends(require_permission(Permission.DISPUTES_READ))],
    session: Annotated[Session, Depends(get_db_session)],
    storage: Annotated[ObjectStorage, Depends(get_object_storage)],
) -> Response:
    _, platform, svc = _build_services(session)
    try:
        case = svc.get_case(auth.tenant_id, case_id)
        art = platform.get_evidence_artifact(auth.tenant_id, artifact_id)
        if art is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Artifact not found")
        assert_same_tenant(auth.tenant_id, art.tenant_id, "evidence_artifact")

        ev_row = session.get(EvidenceRecordRow, art.evidence_record_id)
        if ev_row is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Artifact evidence record not found",
            )
        assert_same_tenant(auth.tenant_id, ev_row.tenant_id, "evidence_record")
        if ev_row.dispute_case_id != case_id and not (
            ev_row.dispute_case_id is None and art.evidence_record_id in set(case.evidence_ids)
        ):
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Artifact does not belong to this dispute case",
            )

        raw = storage.get_bytes(tenant_id=auth.tenant_id, object_key=art.object_key, expected_sha256=art.sha256)
        return Response(
            content=raw,
            media_type=art.content_type,
            headers={"Content-Disposition": f'attachment; filename="{art.filename}"'},
        )
    except HTTPException:
        raise
    except Exception as exc:
        _raise_db_http_error(exc)
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
        _raise_db_http_error(exc)
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
        _raise_db_http_error(exc)
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
        session.commit()
        return AnalyzeCaseResponse(
            case=updated_case,
            analysis=analysis,
            evidence_graph=evidence_graph,
            report=report,
        )
    except Exception as exc:
        _raise_db_http_error(exc)
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
        _raise_db_http_error(exc)
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
        approved = svc.approve_for_submission(
            tenant_id=auth.tenant_id,
            case_id=case_id,
            approver_id=approver,
            draft_response_text=payload.draft_response_text,
        )
        session.commit()
        return approved
    except Exception as exc:
        _raise_db_http_error(exc)
        raise


@router.post("/cases/{case_id}/submit", response_model=SubmitDisputeResponse)
async def submit_case(
    case_id: UUID,
    auth: Annotated[AuthContext, Depends(require_permission(Permission.DISPUTES_SUBMIT))],
    session: Annotated[Session, Depends(get_db_session)],
    settings: Annotated[NexusSettings, Depends(get_app_settings)],
    paypal_client: Annotated[PayPalSandboxClient, Depends(get_paypal_client)],
    payload: Annotated[SubmitDisputeRequest | None, Body()] = None,
) -> SubmitDisputeResponse:
    _, _, svc = _build_services(session)
    adapter = PayPalDisputeAdapter(settings=settings, paypal_client=paypal_client)
    try:
        case = svc.get_case(auth.tenant_id, case_id)
        if case.status in (DisputeStatus.SUBMITTED, DisputeStatus.RESOLVED):
            raise InvalidDisputeTransitionError(
                f"Dispute case {case_id} cannot transition from {case.status.value} to SUBMITTED"
            )
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

        evidence = svc.get_case_evidence(auth.tenant_id, case_id)
        if payload is not None and payload.draft_response_text is not None:
            draft_text = payload.draft_response_text
        else:
            latest = svc.get_latest_analysis(auth.tenant_id, case_id)
            draft_text = latest.draft_response_text if latest is not None else ""

        # Release any read transaction before awaiting outbound PayPal HTTP I/O.
        session.rollback()

        submission = await adapter.submit_dispute_response(
            case=case,
            draft_response_text=draft_text,
            evidence_records=evidence,
        )
        updated_case = svc.mark_submitted(
            tenant_id=auth.tenant_id,
            case_id=case_id,
            actor_id=auth.actor_id,
            actor_type=auth.actor_type,
            external_status="UNDER_REVIEW",
            submission_details={"paypal_dispute_id": case.paypal_dispute_id},
        )
        return SubmitDisputeResponse(case=updated_case, submission=submission)
    except Exception as exc:
        _raise_db_http_error(exc)
        raise


@router.post("/cases/{case_id}/resolve", response_model=DisputeCase)
def resolve_case(
    case_id: UUID,
    auth: Annotated[AuthContext, Depends(require_permission(Permission.DISPUTES_WRITE))],
    session: Annotated[Session, Depends(get_db_session)],
    payload: Annotated[ResolveDisputeRequest | None, Body()] = None,
) -> DisputeCase:
    _, _, svc = _build_services(session)
    outcome = (
        payload.resolution_outcome
        if payload and payload.resolution_outcome
        else (payload.reason if payload and payload.reason else "RESOLVED")
    )
    try:
        resolved = svc.mark_resolved(
            tenant_id=auth.tenant_id,
            case_id=case_id,
            resolution_outcome=outcome,
            actor_id=auth.actor_id,
            actor_type=auth.actor_type,
            notes=payload.notes if payload else None,
        )
        session.commit()
        return resolved
    except Exception as exc:
        _raise_db_http_error(exc)
        raise
