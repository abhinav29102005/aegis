"""FastAPI router for GhostPay replay, counterfactual simulation, and timelines."""

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
from fastapi import APIRouter, Depends, Header, HTTPException, Request, status
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
from ghostpay.timelines.builder import build_timeline

_DEV_TEST_ENVS = frozenset({"development", "dev", "test", "testing", "local"})


class SimulateRequest(BaseModel):
    """Payload for counterfactual policy simulation."""

    model_config = ConfigDict(extra="forbid")

    request: ReplayRequest
    overrides: dict[str, Any] = Field(default_factory=dict)


class TimelineRequest(BaseModel):
    """Payload for reconstructing an event timeline."""

    model_config = ConfigDict(extra="forbid")

    events: list[FinancialEvent] = Field(default_factory=list)
    evidence_records: list[EvidenceRecord] = Field(default_factory=list)


def get_dev_tenant_id(
    http_request: Request,
    x_tenant_id: Annotated[str | None, Header(alias="X-Tenant-Id")] = None,
) -> UUID:
    """Resolve tenant context from trusted request state, or X-Tenant-Id in dev/test only.

    Production deployments MUST mount GhostPay behind authenticated middleware that sets
    ``request.state.authenticated_tenant_id`` or inject a custom ``tenant_resolver`` into
    ``create_ghostpay_router(tenant_resolver=...)``. Raw ``X-Tenant-Id`` headers are
    rejected outside development/test environments.
    """
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
) -> APIRouter:
    """Create and configure FastAPI APIRouter for GhostPay forensic services."""
    api_router = APIRouter(prefix="/ghostpay", tags=["ghostpay"])
    resolve_tenant = tenant_resolver or get_dev_tenant_id

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

    return api_router


router = create_ghostpay_router()
