"""FastAPI router for GhostPay forensic intelligence, replay, and Agent DNA services."""

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
from ghostpay.forensics.timeline import build_timeline
from ghostpay.integrations.disputeos import DisputeOSEvidenceBundle, export_to_disputeos
from ghostpay.timemachine.comparison import PolicyComparisonReport
from ghostpay.timemachine.replay import PolicyTimeMachine
from pydantic import BaseModel, Field
from security import TenantIsolationError, assert_same_tenant
from security.settings import DEFAULT_TENANT_UUID


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
    if isinstance(exc, (TenantIsolationError, CrossTenantAccessError, PermissionError)):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
    if isinstance(exc, (TraceNotFoundError, InvestigationNotFoundError)):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    if isinstance(exc, ValueError):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    if isinstance(exc, GhostPayError):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    raise exc


def create_ghostpay_router(service: GhostPayService | None = None) -> APIRouter:
    """Create and configure FastAPI APIRouter for GhostPay forensic services."""
    api_router = APIRouter(prefix="/ghostpay", tags=["ghostpay"])
    svc = service or GhostPayService()

    @api_router.get("/health")
    def health_check() -> dict[str, str]:
        return {"status": "ok", "service": "ghostpay"}

    # -------------------------------------------------------------------------
    # Traces & Timelines
    # -------------------------------------------------------------------------
    @api_router.post("/traces/ingest", response_model=PaymentTrace)
    def ingest_trace(
        req: IngestTraceRequest,
        tenant_id: Annotated[UUID, Depends(_resolve_tenant_id)],
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
        tenant_id: Annotated[UUID, Depends(_resolve_tenant_id)],
    ) -> PaymentTrace:
        try:
            return svc.get_trace(tenant_id, trace_id)
        except Exception as exc:
            _raise_http_for_domain_error(exc)
            raise

    @api_router.get("/traces/{trace_id}/timeline", response_model=list[ReplayTimelineEntry])
    def get_trace_timeline(
        trace_id: UUID,
        tenant_id: Annotated[UUID, Depends(_resolve_tenant_id)],
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
        tenant_id: Annotated[UUID, Depends(_resolve_tenant_id)],
    ) -> ReplayResult:
        try:
            assert_same_tenant(tenant_id, request.tenant_id, "replay_request")
            return svc.replay(request)
        except Exception as exc:
            _raise_http_for_domain_error(exc)
            raise

    @api_router.post("/replay/compare", response_model=PolicyComparisonReport)
    def compare_policies_endpoint(
        req: ReplayCompareRequest,
        tenant_id: Annotated[UUID, Depends(_resolve_tenant_id)],
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

    # -------------------------------------------------------------------------
    # Agent DNA Endpoints
    # -------------------------------------------------------------------------
    @api_router.get("/agents/{agent_id}/profile", response_model=AgentBehaviorProfile)
    def get_agent_profile(
        agent_id: UUID,
        tenant_id: Annotated[UUID, Depends(_resolve_tenant_id)],
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
        tenant_id: Annotated[UUID, Depends(_resolve_tenant_id)],
    ) -> AgentDNAAnomalyResult:
        try:
            return svc.analyze_agent(tenant_id, agent_id, req.target_trace_id)
        except Exception as exc:
            _raise_http_for_domain_error(exc)
            raise

    # -------------------------------------------------------------------------
    # Investigation Endpoints
    # -------------------------------------------------------------------------
    @api_router.post("/investigations", response_model=InvestigationReport)
    def create_investigation(
        req: CreateInvestigationRequest,
        tenant_id: Annotated[UUID, Depends(_resolve_tenant_id)],
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

    @api_router.get("/investigations/{investigation_id}", response_model=InvestigationReport)
    def get_investigation(
        investigation_id: UUID,
        tenant_id: Annotated[UUID, Depends(_resolve_tenant_id)],
    ) -> InvestigationReport:
        try:
            return svc.get_investigation(tenant_id, investigation_id)
        except Exception as exc:
            _raise_http_for_domain_error(exc)
            raise

    @api_router.get("/investigations/{investigation_id}/evidence", response_model=DisputeOSEvidenceBundle)
    def get_investigation_evidence_bundle(
        investigation_id: UUID,
        tenant_id: Annotated[UUID, Depends(_resolve_tenant_id)],
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
