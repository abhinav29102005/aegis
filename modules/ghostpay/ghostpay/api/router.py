"""FastAPI router for GhostPay replay, counterfactual simulation, Agent DNA, investigations, and timelines."""

from collections.abc import Callable
from typing import Annotated, Any
from uuid import UUID

from contracts import (
    EvidenceRecord,
    FinancialEvent,
    ReplayRequest,
    ReplayResult,
    ReplayTimelineEntry,
)
from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, status
from pydantic import BaseModel, ConfigDict, Field
from security import TenantIsolationError, assert_same_tenant, get_settings
from security.settings import DEFAULT_TENANT_UUID

from ghostpay.agentdna.detector import AgentDNAAnomalyResult
from ghostpay.agentdna.profiles import AgentBehaviorProfile
from ghostpay.api.models import (
    AnalyzeAgentRequest,
    CreateInvestigationRequest,
    IngestTraceRequest,
    ReplayCompareRequest,
)
from ghostpay.counterfactual.simulator import simulate_counterfactual
from ghostpay.domain.exceptions import (
    CrossTenantAccessError,
    GhostPayError,
    InvestigationNotFoundError,
    TraceNotFoundError,
)
from ghostpay.domain.models import InvestigationReport, PaymentTrace
from ghostpay.domain.service import GhostPayService
from ghostpay.errors import (
    OverrideValidationError,
    ReplayExecutionForbiddenError,
    UnsupportedPolicyVersionError,
)
from ghostpay.integrations.disputeos import DisputeOSEvidenceBundle, export_to_disputeos
from ghostpay.replay.engine import ReplayEngine
from ghostpay.repository import (
    GhostPayReplayRepository,
    InvestigationListResponse,
    PersistedInvestigation,
)
from ghostpay.timelines.builder import build_timeline
from ghostpay.timemachine.comparison import PolicyComparisonReport

_DEV_TEST_ENVS = frozenset({"development", "dev", "test", "testing", "local"})
_UNPROCESSABLE_STATUS = getattr(status, "HTTP_422_UNPROCESSABLE_CONTENT", 422)


class SimulateRequest(BaseModel):
    """Payload for counterfactual policy simulation."""

    model_config = ConfigDict(extra="forbid")

    request: ReplayRequest
    overrides: dict[str, Any] = Field(default_factory=dict)


class SimulateByPaymentRequest(BaseModel):
    """Payload for DB-backed counterfactual simulation by payment_intent_id."""

    model_config = ConfigDict(extra="forbid")

    overrides: dict[str, Any] = Field(default_factory=dict)
    policy_version: str | None = None
    persist_investigation: bool = True


class ReplayByPaymentRequest(BaseModel):
    """Optional options for DB-backed deterministic replay by payment_intent_id."""

    model_config = ConfigDict(extra="forbid")

    policy_version: str | None = None
    persist_investigation: bool = True


class TimelineRequest(BaseModel):
    """Payload for reconstructing an event timeline."""

    model_config = ConfigDict(extra="forbid")

    events: list[FinancialEvent] = Field(default_factory=list)
    evidence_records: list[EvidenceRecord] = Field(default_factory=list)


def get_dev_tenant_id(
    http_request: Request,
    x_tenant_id: Annotated[str | None, Header(alias="X-Tenant-Id")] = None,
) -> UUID:
    """Resolve tenant context from trusted request state, or X-Tenant-Id in dev/test only."""
    auth_tenant = getattr(http_request.state, "authenticated_tenant_id", None)
    if auth_tenant is not None:
        if isinstance(auth_tenant, UUID):
            return auth_tenant
        try:
            return UUID(str(auth_tenant))
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid authenticated tenant context.",
            ) from exc

    app_env = get_settings().app_env.strip().lower()
    if app_env not in _DEV_TEST_ENVS:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authenticated tenant identity from trusted middleware is required.",
        )

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
    if isinstance(exc, (TenantIsolationError, CrossTenantAccessError, PermissionError)):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=str(exc),
        ) from exc
    if isinstance(exc, OverrideValidationError):
        raise HTTPException(
            status_code=_UNPROCESSABLE_STATUS,
            detail={
                "error_code": "INVALID_COUNTERFACTUAL_OVERRIDES",
                "message": str(exc),
                "errors": exc.errors,
            },
        ) from exc
    if isinstance(exc, UnsupportedPolicyVersionError):
        raise HTTPException(
            status_code=_UNPROCESSABLE_STATUS,
            detail={
                "error_code": "UNSUPPORTED_POLICY_VERSION",
                "message": str(exc),
                "requested_version": exc.requested_version,
                "supported_versions": list(exc.supported_versions),
            },
        ) from exc
    if isinstance(exc, (TraceNotFoundError, InvestigationNotFoundError)):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc
    if isinstance(exc, ReplayExecutionForbiddenError):
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Forensic read-only invariant violation.",
        ) from exc
    if isinstance(exc, (ValueError, GhostPayError)):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc
    raise exc


def create_ghostpay_router(
    service: GhostPayService | None = None,
    *,
    tenant_resolver: Callable[..., UUID] | None = None,
    repo_resolver: Callable[..., GhostPayReplayRepository | None] | None = None,
) -> APIRouter:
    """Create and configure FastAPI APIRouter for GhostPay forensic services."""
    api_router = APIRouter(prefix="/ghostpay", tags=["ghostpay"])
    svc = service or GhostPayService()
    resolve_tenant = tenant_resolver or get_dev_tenant_id

    def resolve_repo() -> GhostPayReplayRepository | None:
        return None

    repo_dep = repo_resolver or resolve_repo

    def _require_repo(repo: GhostPayReplayRepository | None) -> GhostPayReplayRepository:
        if repo is None:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Database-backed GhostPay repository is not configured.",
            )
        return repo

    @api_router.get("/health")
    def health_check() -> dict[str, str]:
        return {"status": "ok", "service": "ghostpay"}

    # -------------------------------------------------------------------------
    # Traces & Timelines
    # -------------------------------------------------------------------------
    @api_router.post("/traces/ingest", response_model=PaymentTrace)
    def ingest_trace(
        req: IngestTraceRequest,
        tenant_id: Annotated[UUID, Depends(resolve_tenant)],
    ) -> PaymentTrace:
        try:
            assert_same_tenant(tenant_id, req.tenant_id, "ingest_trace_request")
            return svc.ingest_trace(
                tenant_id=req.tenant_id,
                agent_id=req.agent_id,
                payment_intent_id=req.payment_intent_id,
                events=req.events,
                quote_snapshot=req.quote_snapshot,
                evidence_records=req.evidence_records,
                recorded_decision=req.recorded_decision,
                recorded_passport=req.recorded_passport,
                recorded_merchant=req.recorded_merchant,
                approval_record=req.approval_record,
                payment_intent=req.payment_intent,
                policy_version=req.policy_version,
                strict_integrity=req.strict_integrity,
            )
        except Exception as exc:
            _raise_http_for_domain_error(exc)
            raise

    @api_router.get("/traces/{trace_id}", response_model=PaymentTrace)
    def get_trace(
        trace_id: UUID,
        tenant_id: Annotated[UUID, Depends(resolve_tenant)],
    ) -> PaymentTrace:
        try:
            return svc.get_trace(tenant_id, trace_id)
        except Exception as exc:
            _raise_http_for_domain_error(exc)
            raise

    @api_router.get("/traces/{trace_id}/timeline", response_model=list[ReplayTimelineEntry])
    def get_trace_timeline(
        trace_id: UUID,
        tenant_id: Annotated[UUID, Depends(resolve_tenant)],
    ) -> list[ReplayTimelineEntry]:
        try:
            return svc.get_timeline(tenant_id, trace_id)
        except Exception as exc:
            _raise_http_for_domain_error(exc)
            raise

    # -------------------------------------------------------------------------
    # Replay & Counterfactual Simulation
    # -------------------------------------------------------------------------
    @api_router.post("/replay", response_model=ReplayResult)
    def replay_transaction(
        request: ReplayRequest,
        tenant_id: Annotated[UUID, Depends(resolve_tenant)],
    ) -> ReplayResult:
        try:
            assert_same_tenant(tenant_id, request.tenant_id, "replay_request")
            return ReplayEngine.replay(request)
        except Exception as exc:
            _raise_http_for_domain_error(exc)
            raise

    @api_router.post("/replay/by-payment/{payment_intent_id}", response_model=ReplayResult)
    def replay_by_payment(
        payment_intent_id: UUID,
        http_request: Request,
        tenant_id: Annotated[UUID, Depends(resolve_tenant)],
        repo: Annotated[GhostPayReplayRepository | None, Depends(repo_dep)],
        payload: ReplayByPaymentRequest | None = None,
    ) -> ReplayResult:
        active_repo = _require_repo(repo)
        try:
            replay_req = active_repo.load_replay_request_by_payment(tenant_id, payment_intent_id)
            if replay_req is None:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=f"PaymentIntent {payment_intent_id} not found for replay.",
                )
            if payload and payload.policy_version:
                replay_req = replay_req.model_copy(update={"policy_version": payload.policy_version})
            result = ReplayEngine.replay(replay_req)
            if payload is None or payload.persist_investigation:
                actor = getattr(http_request.state, "authenticated_actor_id", str(tenant_id))
                active_repo.save_investigation(
                    tenant_id=tenant_id,
                    result=result,
                    mode="REPLAY",
                    overrides={},
                    created_by=str(actor),
                )
            return result
        except HTTPException:
            raise
        except Exception as exc:
            _raise_http_for_domain_error(exc)
            raise

    @api_router.post("/replay/compare", response_model=PolicyComparisonReport)
    def compare_policies_endpoint(
        req: ReplayCompareRequest,
        tenant_id: Annotated[UUID, Depends(resolve_tenant)],
    ) -> PolicyComparisonReport:
        try:
            assert_same_tenant(tenant_id, req.replay_request.tenant_id, "replay_compare_request")
            return svc.compare_policies(req.replay_request, req.policies)
        except Exception as exc:
            _raise_http_for_domain_error(exc)
            raise

    @api_router.post("/simulate", response_model=ReplayResult)
    def simulate_policy(
        payload: SimulateRequest,
        tenant_id: Annotated[UUID, Depends(resolve_tenant)],
    ) -> ReplayResult:
        try:
            assert_same_tenant(tenant_id, payload.request.tenant_id, "simulation_request")
            return simulate_counterfactual(payload.request, payload.overrides)
        except Exception as exc:
            _raise_http_for_domain_error(exc)
            raise

    @api_router.post("/simulate/by-payment/{payment_intent_id}", response_model=ReplayResult)
    def simulate_by_payment(
        payment_intent_id: UUID,
        payload: SimulateByPaymentRequest,
        http_request: Request,
        tenant_id: Annotated[UUID, Depends(resolve_tenant)],
        repo: Annotated[GhostPayReplayRepository | None, Depends(repo_dep)],
    ) -> ReplayResult:
        active_repo = _require_repo(repo)
        try:
            replay_req = active_repo.load_replay_request_by_payment(tenant_id, payment_intent_id)
            if replay_req is None:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=f"PaymentIntent {payment_intent_id} not found for simulation.",
                )
            if payload.policy_version:
                replay_req = replay_req.model_copy(update={"policy_version": payload.policy_version})
            result = simulate_counterfactual(replay_req, payload.overrides)
            if payload.persist_investigation:
                actor = getattr(http_request.state, "authenticated_actor_id", str(tenant_id))
                active_repo.save_investigation(
                    tenant_id=tenant_id,
                    result=result,
                    mode="COUNTERFACTUAL",
                    overrides=dict(payload.overrides),
                    created_by=str(actor),
                )
            return result
        except HTTPException:
            raise
        except Exception as exc:
            _raise_http_for_domain_error(exc)
            raise

    @api_router.post("/counterfactual", response_model=ReplayResult)
    def simulate_counterfactual_alias(
        payload: SimulateRequest,
        tenant_id: Annotated[UUID, Depends(resolve_tenant)],
    ) -> ReplayResult:
        try:
            assert_same_tenant(tenant_id, payload.request.tenant_id, "counterfactual_request")
            return simulate_counterfactual(payload.request, payload.overrides)
        except Exception as exc:
            _raise_http_for_domain_error(exc)
            raise

    @api_router.post("/timeline", response_model=list[ReplayTimelineEntry])
    def reconstruct_timeline(
        payload: TimelineRequest,
        tenant_id: Annotated[UUID, Depends(resolve_tenant)],
    ) -> list[ReplayTimelineEntry]:
        try:
            for ev in payload.events:
                assert_same_tenant(tenant_id, ev.tenant_id, f"financial_event_{ev.id}")
            for rec in payload.evidence_records:
                assert_same_tenant(tenant_id, rec.tenant_id, f"evidence_record_{rec.id}")
            return build_timeline(payload.events, payload.evidence_records)
        except Exception as exc:
            _raise_http_for_domain_error(exc)
            raise

    @api_router.get("/timeline/by-payment/{payment_intent_id}", response_model=list[ReplayTimelineEntry])
    def timeline_by_payment(
        payment_intent_id: UUID,
        tenant_id: Annotated[UUID, Depends(resolve_tenant)],
        repo: Annotated[GhostPayReplayRepository | None, Depends(repo_dep)],
    ) -> list[ReplayTimelineEntry]:
        active_repo = _require_repo(repo)
        try:
            loaded = active_repo.load_timeline_records_by_payment(tenant_id, payment_intent_id)
            if loaded is None:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=f"PaymentIntent {payment_intent_id} not found.",
                )
            events, evidence_records = loaded
            return build_timeline(events, evidence_records)
        except HTTPException:
            raise
        except Exception as exc:
            _raise_http_for_domain_error(exc)
            raise

    # -------------------------------------------------------------------------
    # Agent DNA Endpoints
    # -------------------------------------------------------------------------
    @api_router.get("/agents/{agent_id}/profile", response_model=AgentBehaviorProfile)
    def get_agent_profile(
        agent_id: UUID,
        tenant_id: Annotated[UUID, Depends(resolve_tenant)],
    ) -> AgentBehaviorProfile:
        try:
            return svc.get_agent_profile(tenant_id, agent_id)
        except Exception as exc:
            _raise_http_for_domain_error(exc)
            raise

    @api_router.post("/agents/{agent_id}/analyze", response_model=AgentDNAAnomalyResult)
    def analyze_agent_dna(
        agent_id: UUID,
        req: AnalyzeAgentRequest,
        tenant_id: Annotated[UUID, Depends(resolve_tenant)],
    ) -> AgentDNAAnomalyResult:
        try:
            return svc.analyze_agent(tenant_id, agent_id, req.target_trace_id)
        except Exception as exc:
            _raise_http_for_domain_error(exc)
            raise

    # -------------------------------------------------------------------------
    # Investigation Endpoints
    # -------------------------------------------------------------------------
    @api_router.get("/investigations", response_model=InvestigationListResponse)
    def list_investigations(
        tenant_id: Annotated[UUID, Depends(resolve_tenant)],
        repo: Annotated[GhostPayReplayRepository | None, Depends(repo_dep)],
        payment_intent_id: UUID | None = None,
        consistency_status: str | None = None,
        drift_detected: bool | None = None,
        limit: Annotated[int, Query(ge=1, le=100)] = 50,
        offset: Annotated[int, Query(ge=0)] = 0,
    ) -> InvestigationListResponse:
        active_repo = _require_repo(repo)
        return active_repo.list_investigations(
            tenant_id,
            payment_intent_id=payment_intent_id,
            consistency_status=consistency_status,
            drift_detected=drift_detected,
            limit=limit,
            offset=offset,
        )

    @api_router.post("/investigations", response_model=InvestigationReport)
    def create_investigation(
        req: CreateInvestigationRequest,
        tenant_id: Annotated[UUID, Depends(resolve_tenant)],
    ) -> InvestigationReport:
        try:
            return svc.create_investigation(
                tenant_id=tenant_id,
                trace_id=req.trace_id,
                counterfactual_policies=req.counterfactual_policies,
            )
        except Exception as exc:
            _raise_http_for_domain_error(exc)
            raise

    @api_router.get(
        "/investigations/{investigation_id}",
        response_model=PersistedInvestigation | InvestigationReport,
    )
    def get_investigation(
        investigation_id: UUID,
        tenant_id: Annotated[UUID, Depends(resolve_tenant)],
        repo: Annotated[GhostPayReplayRepository | None, Depends(repo_dep)] = None,
    ) -> PersistedInvestigation | InvestigationReport:
        if repo is not None:
            item = repo.get_investigation(tenant_id, investigation_id)
            if item is not None:
                return item
            if investigation_id not in svc.investigations:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=f"Investigation {investigation_id} not found.",
                )
        try:
            return svc.get_investigation(tenant_id, investigation_id)
        except Exception as exc:
            _raise_http_for_domain_error(exc)
            raise

    @api_router.get("/investigations/{investigation_id}/evidence", response_model=DisputeOSEvidenceBundle)
    def get_investigation_evidence_bundle(
        investigation_id: UUID,
        tenant_id: Annotated[UUID, Depends(resolve_tenant)],
    ) -> DisputeOSEvidenceBundle:
        try:
            inv = svc.get_investigation(tenant_id, investigation_id)
            trace_id = inv.trace_id if inv.trace_id is not None else inv.payment_intent_id
            trace = svc.get_trace(tenant_id, trace_id)
            return export_to_disputeos(trace, inv)
        except Exception as exc:
            _raise_http_for_domain_error(exc)
            raise

    return api_router


# Default router instance
router = create_ghostpay_router()
