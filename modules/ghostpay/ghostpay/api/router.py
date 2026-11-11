"""FastAPI router for GhostPay replay, counterfactual simulation, and timelines."""

from __future__ import annotations

from typing import Annotated, Any
from uuid import UUID

from contracts import (
    EvidenceRecord,
    FinancialEvent,
    ReplayRequest,
    ReplayResult,
    ReplayTimelineEntry,
)
from fastapi import APIRouter, Depends, Header, HTTPException, status
from pydantic import BaseModel, Field
from security import TenantIsolationError, assert_same_tenant
from security.settings import DEFAULT_TENANT_UUID

from ghostpay.counterfactual.simulator import simulate_counterfactual
from ghostpay.replay.engine import ReplayEngine
from ghostpay.timelines.builder import build_timeline


class SimulateRequest(BaseModel):
    """Payload for counterfactual policy simulation."""

    request: ReplayRequest
    overrides: dict[str, Any] = Field(default_factory=dict)


class TimelineRequest(BaseModel):
    """Payload for reconstructing an event timeline."""

    events: list[FinancialEvent] = Field(default_factory=list)
    evidence_records: list[EvidenceRecord] = Field(default_factory=list)


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
    if isinstance(exc, (TenantIsolationError, PermissionError)):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
    if isinstance(exc, ValueError):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    raise exc


def create_ghostpay_router() -> APIRouter:
    """Create and configure FastAPI APIRouter for GhostPay forensic services."""
    api_router = APIRouter(prefix="/ghostpay", tags=["ghostpay"])

    @api_router.get("/health")
    def health_check() -> dict[str, str]:
        return {"status": "ok", "service": "ghostpay"}

    @api_router.post("/replay", response_model=ReplayResult)
    def replay_transaction(
        request: ReplayRequest,
        tenant_id: Annotated[UUID, Depends(_resolve_tenant_id)],
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
        tenant_id: Annotated[UUID, Depends(_resolve_tenant_id)],
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
        tenant_id: Annotated[UUID, Depends(_resolve_tenant_id)],
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
        tenant_id: Annotated[UUID, Depends(_resolve_tenant_id)],
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
