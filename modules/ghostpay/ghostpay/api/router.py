"""FastAPI router for GhostPay replay, counterfactual simulation, investigations, and timelines."""

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

from ghostpay.counterfactual.simulator import simulate_counterfactual
from ghostpay.errors import (
    OverrideValidationError,
    ReplayExecutionForbiddenError,
    UnsupportedPolicyVersionError,
)
from ghostpay.replay.engine import ReplayEngine
from ghostpay.repository import (
    GhostPayReplayRepository,
    InvestigationListResponse,
    PersistedInvestigation,
)
from ghostpay.timelines.builder import build_timeline

_DEV_TEST_ENVS = frozenset({"development", "dev", "test", "testing", "local"})


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


_UNPROCESSABLE_STATUS = getattr(status, "HTTP_422_UNPROCESSABLE_CONTENT", 422)


def _raise_http_for_domain_error(exc: Exception) -> None:
    if isinstance(exc, (TenantIsolationError, PermissionError)):
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
    if isinstance(exc, ValueError):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc
    if isinstance(exc, ReplayExecutionForbiddenError):
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Forensic read-only invariant violation.",
        ) from exc
    raise exc


def create_ghostpay_router(
    tenant_resolver: Callable[..., UUID] | None = None,
    repo_resolver: Callable[..., GhostPayReplayRepository | None] | None = None,
) -> APIRouter:
    """Create and configure FastAPI APIRouter for GhostPay forensic services."""
    api_router = APIRouter(prefix="/ghostpay", tags=["ghostpay"])
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

    @api_router.get("/investigations/{investigation_id}", response_model=PersistedInvestigation)
    def get_investigation(
        investigation_id: UUID,
        tenant_id: Annotated[UUID, Depends(resolve_tenant)],
        repo: Annotated[GhostPayReplayRepository | None, Depends(repo_dep)],
    ) -> PersistedInvestigation:
        active_repo = _require_repo(repo)
        try:
            item = active_repo.get_investigation(tenant_id, investigation_id)
            if item is None:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=f"Investigation {investigation_id} not found.",
                )
            return item
        except HTTPException:
            raise
        except Exception as exc:
            _raise_http_for_domain_error(exc)
            raise

    return api_router


router = create_ghostpay_router()
