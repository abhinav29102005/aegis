"""FastAPI router for GhostPay replay, counterfactual simulation, Agent DNA, investigations, and timelines."""

from collections.abc import Callable
from typing import Annotated, Any, Protocol, runtime_checkable
from uuid import UUID, uuid4

from contracts import (
    DecisionOutcome,
    EvidenceRecord,
    FinancialEvent,
    ReplayRequest,
    ReplayResult,
    ReplayTimelineEntry,
)
from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, status
from pydantic import BaseModel, ConfigDict, Field
from security import (
    AuthContext,
    AuthenticationError,
    AuthorizationError,
    Permission,
    Role,
    TenantIsolationError,
    assert_same_tenant,
    get_settings,
    resolve_permissions,
    verify_access_token,
)
from security.settings import DEFAULT_TENANT_UUID

from ghostpay.agentdna.detector import AgentDNAAnomalyResult
from ghostpay.agentdna.explanations import format_agent_dna_explanation
from ghostpay.agentdna.profiles import AgentBehaviorProfile, build_agent_profile
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
    MissingEvidenceError,
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
from ghostpay.timemachine.comparison import PolicyComparisonEntry, PolicyComparisonReport
from ghostpay.timemachine.policies import CounterfactualPolicy
from ghostpay.timemachine.recommendations import generate_safeguard_recommendations

_DEV_TEST_ENVS = frozenset({"development", "dev", "test", "testing", "local"})
_UNPROCESSABLE_STATUS = getattr(status, "HTTP_422_UNPROCESSABLE_CONTENT", 422)


@runtime_checkable
class GhostPayTraceAndDnaRepository(Protocol):
    """Optional repository extension protocol for persisted traces and Agent DNA profiles."""

    def save_ghostpay_trace(self, tenant_id: UUID, trace: PaymentTrace) -> PaymentTrace: ...

    def list_ghostpay_traces(
        self,
        tenant_id: UUID,
        *,
        agent_id: UUID | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[PaymentTrace]: ...

    def get_ghostpay_trace(self, tenant_id: UUID, trace_id: UUID) -> PaymentTrace | None: ...

    def save_agent_dna_profile(
        self, tenant_id: UUID, profile: AgentBehaviorProfile
    ) -> AgentBehaviorProfile: ...

    def get_agent_dna_profile(
        self, tenant_id: UUID, agent_id: UUID
    ) -> AgentBehaviorProfile | None: ...


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


def _policy_to_overrides(policy: CounterfactualPolicy) -> dict[str, Any]:
    """Translate CounterfactualPolicy fields into strict validator override keys."""
    overrides = policy.to_overrides_dict()
    if "currency" in overrides:
        overrides["currency_override"] = overrides.pop("currency")
    return overrides


def _trace_from_replay_request(trace_id: UUID, replay_req: ReplayRequest) -> PaymentTrace:
    """Reconstruct a canonical PaymentTrace from a DB-loaded ReplayRequest."""
    return PaymentTrace(
        trace_id=trace_id,
        tenant_id=replay_req.tenant_id,
        agent_id=replay_req.proposal.agent_id,
        payment_intent_id=replay_req.payment_intent.id,
        ordered_events=replay_req.events,
        quote_snapshot=replay_req.quote_snapshot,
        authorization_evidence=replay_req.evidence_records,
        recorded_decision=replay_req.recorded_decision,
        recorded_passport=replay_req.recorded_passport,
        recorded_merchant=replay_req.recorded_merchant,
        approval_record=replay_req.approval_record,
        payment_intent=replay_req.payment_intent,
        proposal=replay_req.proposal,
        policy_version=replay_req.policy_version,
        integrity_status="VALID",
    )


def _resolve_request_auth_context(
    http_request: Request | None,
    tenant_id: UUID,
    repo: GhostPayReplayRepository | None,
    injected_auth: AuthContext | None,
) -> AuthContext | None:
    """Resolve verified AuthContext from injected dependency, request.state, or headers."""
    if injected_auth is not None:
        return injected_auth
    if http_request is None:
        return None

    state_auth = getattr(http_request.state, "auth_context", None)
    if isinstance(state_auth, AuthContext):
        return state_auth

    auth_header = http_request.headers.get("authorization")
    if auth_header and auth_header.strip().lower().startswith("bearer "):
        raw_token = auth_header.strip()[7:].strip()
        app_state = getattr(http_request.app, "state", None)
        settings = getattr(app_state, "settings", None) or get_settings()
        try:
            claims = verify_access_token(raw_token, secret=settings.jwt_secret)
        except AuthenticationError as exc:
            handlers = getattr(http_request.app, "exception_handlers", {})
            if AuthenticationError in handlers:
                raise
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail={"error_code": "INVALID_TOKEN", "message": str(exc)},
            ) from exc

        role = claims.role
        platform = getattr(repo, "platform", None)
        get_membership = getattr(platform, "get_membership", None)
        if callable(get_membership):
            membership = get_membership(tenant_id, claims.sub)
            if membership is not None and getattr(membership, "status", "ACTIVE") == "ACTIVE":
                role = Role(membership.role)

        return AuthContext(
            tenant_id=tenant_id,
            actor_type="USER",
            actor_id=str(claims.sub),
            user_id=claims.sub,
            email=claims.email,
            role=role,
            permissions=resolve_permissions(role),
            token_id=claims.token_id,
        )

    api_key = http_request.headers.get("x-api-key")
    if api_key and api_key.strip():
        platform = getattr(repo, "platform", None)
        authenticate_api_key = getattr(platform, "authenticate_api_key", None)
        if callable(authenticate_api_key):
            app_state = getattr(http_request.app, "state", None)
            settings = getattr(app_state, "settings", None) or get_settings()
            key_row = authenticate_api_key(api_key.strip(), pepper=settings.signing_secret)
            if key_row is not None:
                role = Role(key_row.role)
                scopes = list(getattr(key_row, "scopes", None) or [])
                return AuthContext(
                    tenant_id=key_row.tenant_id,
                    actor_type="API_KEY",
                    actor_id=f"key:{key_row.key_prefix}",
                    service_account_id=key_row.service_account_id,
                    user_id=key_row.user_id,
                    api_key_id=key_row.id,
                    role=role,
                    permissions=resolve_permissions(role, scopes),
                )

    return None


def _enforce_permission(
    http_request: Request | None,
    tenant_id: UUID,
    required_permission: Permission,
    repo: GhostPayReplayRepository | None,
    injected_auth: AuthContext | None,
) -> None:
    """Enforce GhostPay RBAC when an AuthContext is present, failing closed with HTTP 403."""
    auth_ctx = _resolve_request_auth_context(http_request, tenant_id, repo, injected_auth)
    if auth_ctx is None:
        return

    assert_same_tenant(tenant_id, auth_ctx.tenant_id, "auth_context")
    try:
        auth_ctx.require_permission(required_permission)
    except AuthorizationError as exc:
        handlers = getattr(http_request.app, "exception_handlers", {}) if http_request is not None else {}
        if AuthorizationError in handlers:
            raise
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"error_code": "PERMISSION_DENIED", "message": str(exc)},
        ) from exc


def create_ghostpay_router(
    service: GhostPayService | None = None,
    *,
    tenant_resolver: Callable[..., UUID] | None = None,
    repo_resolver: Callable[..., GhostPayReplayRepository | None] | None = None,
    auth_resolver: Callable[..., AuthContext | None] | None = None,
) -> APIRouter:
    """Create and configure FastAPI APIRouter for GhostPay forensic services."""
    api_router = APIRouter(prefix="/ghostpay", tags=["ghostpay"])
    svc = service or GhostPayService()

    def resolve_auth_none() -> AuthContext | None:
        return None

    auth_dep = auth_resolver or resolve_auth_none

    if tenant_resolver is not None:
        resolve_tenant = tenant_resolver
    elif auth_resolver is not None:

        def resolve_tenant_from_auth(
            http_request: Request,
            auth_ctx: Annotated[AuthContext | None, Depends(auth_dep)],
            x_tenant_id: Annotated[str | None, Header(alias="X-Tenant-Id")] = None,
        ) -> UUID:
            if auth_ctx is not None:
                http_request.state.auth_context = auth_ctx
                http_request.state.authenticated_tenant_id = auth_ctx.tenant_id
                http_request.state.authenticated_actor_id = auth_ctx.actor_id
                return auth_ctx.tenant_id
            return get_dev_tenant_id(http_request, x_tenant_id)

        resolve_tenant = resolve_tenant_from_auth
    else:
        resolve_tenant = get_dev_tenant_id

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

    def _load_trace(
        tenant_id: UUID,
        trace_id: UUID,
        repo: GhostPayReplayRepository | None,
    ) -> PaymentTrace:
        getter = getattr(repo, "get_ghostpay_trace", None) if repo is not None else None
        if callable(getter):
            trace = getter(tenant_id, trace_id)
            if trace is not None:
                if trace.tenant_id != tenant_id:
                    raise CrossTenantAccessError(
                        f"Tenant isolation breach: trace tenant {trace.tenant_id} != {tenant_id}"
                    )
                return trace
            raise TraceNotFoundError(f"PaymentTrace {trace_id} not found")
        return svc.get_trace(tenant_id, trace_id)

    def _load_agent_history(
        tenant_id: UUID,
        agent_id: UUID,
        repo: GhostPayReplayRepository | None,
    ) -> list[PaymentTrace]:
        lister = getattr(repo, "list_ghostpay_traces", None) if repo is not None else None
        if callable(lister):
            return list(lister(tenant_id, agent_id=agent_id, limit=500, offset=0))
        return list(svc.agent_history.get((tenant_id, agent_id), []))

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
        http_request: Request = None,  # type: ignore[assignment]
        repo: Annotated[GhostPayReplayRepository | None, Depends(repo_dep)] = None,
        auth: Annotated[AuthContext | None, Depends(auth_dep)] = None,
    ) -> PaymentTrace:
        _enforce_permission(http_request, tenant_id, Permission.GHOSTPAY_SIMULATE, repo, auth)
        try:
            assert_same_tenant(tenant_id, req.tenant_id, "ingest_trace_request")
            trace = svc.ingest_trace(
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
            saver = getattr(repo, "save_ghostpay_trace", None) if repo is not None else None
            if callable(saver):
                saver(tenant_id, trace)
                dna_saver = getattr(repo, "save_agent_dna_profile", None)
                lister = getattr(repo, "list_ghostpay_traces", None)
                if callable(dna_saver) and callable(lister):
                    history = list(lister(tenant_id, agent_id=req.agent_id, limit=500, offset=0))
                    profile = build_agent_profile(tenant_id, req.agent_id, history)
                    dna_saver(tenant_id, profile)
            return trace
        except Exception as exc:
            _raise_http_for_domain_error(exc)
            raise

    @api_router.get("/traces", response_model=list[PaymentTrace])
    def list_traces(
        tenant_id: Annotated[UUID, Depends(resolve_tenant)],
        agent_id: UUID | None = None,
        limit: Annotated[int, Query(ge=1, le=100)] = 50,
        offset: Annotated[int, Query(ge=0)] = 0,
        http_request: Request = None,  # type: ignore[assignment]
        repo: Annotated[GhostPayReplayRepository | None, Depends(repo_dep)] = None,
        auth: Annotated[AuthContext | None, Depends(auth_dep)] = None,
    ) -> list[PaymentTrace]:
        _enforce_permission(http_request, tenant_id, Permission.GHOSTPAY_READ, repo, auth)
        lister = getattr(repo, "list_ghostpay_traces", None) if repo is not None else None
        if callable(lister):
            return list(lister(tenant_id, agent_id=agent_id, limit=limit, offset=offset))
        traces = [
            t
            for t in svc.ingestion.traces.values()
            if t.tenant_id == tenant_id and (agent_id is None or t.agent_id == agent_id)
        ]
        traces.sort(key=lambda t: t.created_at, reverse=True)
        return traces[offset : offset + limit]

    @api_router.get("/traces/{trace_id}", response_model=PaymentTrace)
    def get_trace(
        trace_id: UUID,
        tenant_id: Annotated[UUID, Depends(resolve_tenant)],
        http_request: Request = None,  # type: ignore[assignment]
        repo: Annotated[GhostPayReplayRepository | None, Depends(repo_dep)] = None,
        auth: Annotated[AuthContext | None, Depends(auth_dep)] = None,
    ) -> PaymentTrace:
        _enforce_permission(http_request, tenant_id, Permission.GHOSTPAY_READ, repo, auth)
        try:
            return _load_trace(tenant_id, trace_id, repo)
        except Exception as exc:
            _raise_http_for_domain_error(exc)
            raise

    @api_router.get("/traces/{trace_id}/timeline", response_model=list[ReplayTimelineEntry])
    def get_trace_timeline(
        trace_id: UUID,
        tenant_id: Annotated[UUID, Depends(resolve_tenant)],
        http_request: Request = None,  # type: ignore[assignment]
        repo: Annotated[GhostPayReplayRepository | None, Depends(repo_dep)] = None,
        auth: Annotated[AuthContext | None, Depends(auth_dep)] = None,
    ) -> list[ReplayTimelineEntry]:
        _enforce_permission(http_request, tenant_id, Permission.GHOSTPAY_READ, repo, auth)
        try:
            trace = _load_trace(tenant_id, trace_id, repo)
            return build_timeline(trace.ordered_events, trace.authorization_evidence)
        except Exception as exc:
            _raise_http_for_domain_error(exc)
            raise

    # -------------------------------------------------------------------------
    # Replay & Counterfactual Simulation (Hardened ReplayEngine)
    # -------------------------------------------------------------------------
    @api_router.post("/replay", response_model=ReplayResult)
    def replay_transaction(
        request: ReplayRequest,
        tenant_id: Annotated[UUID, Depends(resolve_tenant)],
        http_request: Request = None,  # type: ignore[assignment]
        repo: Annotated[GhostPayReplayRepository | None, Depends(repo_dep)] = None,
        auth: Annotated[AuthContext | None, Depends(auth_dep)] = None,
    ) -> ReplayResult:
        _enforce_permission(http_request, tenant_id, Permission.GHOSTPAY_READ, repo, auth)
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
        auth: Annotated[AuthContext | None, Depends(auth_dep)] = None,
    ) -> ReplayResult:
        _enforce_permission(http_request, tenant_id, Permission.GHOSTPAY_READ, repo, auth)
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
        http_request: Request = None,  # type: ignore[assignment]
        repo: Annotated[GhostPayReplayRepository | None, Depends(repo_dep)] = None,
        auth: Annotated[AuthContext | None, Depends(auth_dep)] = None,
    ) -> PolicyComparisonReport:
        _enforce_permission(http_request, tenant_id, Permission.GHOSTPAY_SIMULATE, repo, auth)
        try:
            assert_same_tenant(tenant_id, req.replay_request.tenant_id, "replay_compare_request")
            orig_outcome = req.replay_request.recorded_decision.outcome
            entries: list[PolicyComparisonEntry] = []
            for policy in req.policies:
                overrides = _policy_to_overrides(policy)
                res = simulate_counterfactual(req.replay_request, overrides)
                entries.append(
                    PolicyComparisonEntry(
                        policy_name=policy.name,
                        outcome=res.recomputed_outcome,
                        outcome_changed=(res.recomputed_outcome != orig_outcome),
                        recomputed_reason_codes=[rc.value for rc in res.recomputed_reason_codes],
                        changed_constraints=res.changed_constraints,
                        applied_overrides=overrides,
                    )
                )
            return PolicyComparisonReport(
                tenant_id=req.replay_request.tenant_id,
                payment_intent_id=req.replay_request.payment_intent.id,
                original_outcome=orig_outcome,
                results=entries,
            )
        except Exception as exc:
            _raise_http_for_domain_error(exc)
            raise

    @api_router.post("/simulate", response_model=ReplayResult)
    def simulate_policy(
        payload: SimulateRequest,
        tenant_id: Annotated[UUID, Depends(resolve_tenant)],
        http_request: Request = None,  # type: ignore[assignment]
        repo: Annotated[GhostPayReplayRepository | None, Depends(repo_dep)] = None,
        auth: Annotated[AuthContext | None, Depends(auth_dep)] = None,
    ) -> ReplayResult:
        _enforce_permission(http_request, tenant_id, Permission.GHOSTPAY_SIMULATE, repo, auth)
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
        auth: Annotated[AuthContext | None, Depends(auth_dep)] = None,
    ) -> ReplayResult:
        _enforce_permission(http_request, tenant_id, Permission.GHOSTPAY_SIMULATE, repo, auth)
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
        http_request: Request = None,  # type: ignore[assignment]
        repo: Annotated[GhostPayReplayRepository | None, Depends(repo_dep)] = None,
        auth: Annotated[AuthContext | None, Depends(auth_dep)] = None,
    ) -> ReplayResult:
        _enforce_permission(http_request, tenant_id, Permission.GHOSTPAY_SIMULATE, repo, auth)
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
        http_request: Request = None,  # type: ignore[assignment]
        repo: Annotated[GhostPayReplayRepository | None, Depends(repo_dep)] = None,
        auth: Annotated[AuthContext | None, Depends(auth_dep)] = None,
    ) -> list[ReplayTimelineEntry]:
        _enforce_permission(http_request, tenant_id, Permission.GHOSTPAY_READ, repo, auth)
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
        http_request: Request = None,  # type: ignore[assignment]
        auth: Annotated[AuthContext | None, Depends(auth_dep)] = None,
    ) -> list[ReplayTimelineEntry]:
        _enforce_permission(http_request, tenant_id, Permission.GHOSTPAY_READ, repo, auth)
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
        http_request: Request = None,  # type: ignore[assignment]
        repo: Annotated[GhostPayReplayRepository | None, Depends(repo_dep)] = None,
        auth: Annotated[AuthContext | None, Depends(auth_dep)] = None,
    ) -> AgentBehaviorProfile:
        _enforce_permission(http_request, tenant_id, Permission.GHOSTPAY_READ, repo, auth)
        try:
            if repo is not None:
                lister = getattr(repo, "list_ghostpay_traces", None)
                dna_getter = getattr(repo, "get_agent_dna_profile", None)
                dna_saver = getattr(repo, "save_agent_dna_profile", None)
                if callable(lister):
                    history = list(lister(tenant_id, agent_id=agent_id, limit=500, offset=0))
                    if history:
                        profile = build_agent_profile(tenant_id, agent_id, history)
                        if callable(dna_saver):
                            dna_saver(tenant_id, profile)
                        return profile
                if callable(dna_getter):
                    persisted = dna_getter(tenant_id, agent_id)
                    if persisted is not None:
                        return persisted
                if callable(lister) or callable(dna_getter):
                    return build_agent_profile(tenant_id, agent_id, [])
            return svc.get_agent_profile(tenant_id, agent_id)
        except Exception as exc:
            _raise_http_for_domain_error(exc)
            raise

    @api_router.post("/agents/{agent_id}/analyze", response_model=AgentDNAAnomalyResult)
    def analyze_agent_dna(
        agent_id: UUID,
        req: AnalyzeAgentRequest,
        tenant_id: Annotated[UUID, Depends(resolve_tenant)],
        http_request: Request = None,  # type: ignore[assignment]
        repo: Annotated[GhostPayReplayRepository | None, Depends(repo_dep)] = None,
        auth: Annotated[AuthContext | None, Depends(auth_dep)] = None,
    ) -> AgentDNAAnomalyResult:
        _enforce_permission(http_request, tenant_id, Permission.GHOSTPAY_READ, repo, auth)
        try:
            target_trace = _load_trace(tenant_id, req.target_trace_id, repo)
            history = _load_agent_history(tenant_id, agent_id, repo)
            profile = build_agent_profile(
                tenant_id,
                agent_id,
                history,
                cutoff_time=target_trace.created_at,
                exclude_trace_id=target_trace.trace_id,
            )
            return svc.dna_detector.detect(profile, target_trace)
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
        http_request: Request = None,  # type: ignore[assignment]
        auth: Annotated[AuthContext | None, Depends(auth_dep)] = None,
    ) -> InvestigationListResponse:
        _enforce_permission(http_request, tenant_id, Permission.GHOSTPAY_READ, repo, auth)
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
        http_request: Request = None,  # type: ignore[assignment]
        repo: Annotated[GhostPayReplayRepository | None, Depends(repo_dep)] = None,
        auth: Annotated[AuthContext | None, Depends(auth_dep)] = None,
    ) -> InvestigationReport:
        _enforce_permission(http_request, tenant_id, Permission.GHOSTPAY_SIMULATE, repo, auth)
        try:
            trace: PaymentTrace | None = None
            try:
                trace = _load_trace(tenant_id, req.trace_id, repo)
            except TraceNotFoundError:
                if repo is not None:
                    replay_req_by_pi = repo.load_replay_request_by_payment(tenant_id, req.trace_id)
                    if replay_req_by_pi is not None:
                        trace = _trace_from_replay_request(req.trace_id, replay_req_by_pi)
                if trace is None:
                    raise

            timeline = build_timeline(trace.ordered_events, trace.authorization_evidence)

            replay_req: ReplayRequest | None = None
            try:
                replay_req = trace.to_replay_request()
            except (MissingEvidenceError, ValueError):
                replay_req = None

            baseline_result: ReplayResult | None = None
            trace_anomalies: list[str] = []
            if replay_req is not None:
                baseline_result = ReplayEngine.replay(replay_req)
                trace_anomalies = list(baseline_result.anomalies)

            history = _load_agent_history(tenant_id, trace.agent_id, repo)
            profile = build_agent_profile(
                tenant_id,
                trace.agent_id,
                history,
                cutoff_time=trace.created_at,
                exclude_trace_id=trace.trace_id,
            )
            dna_result = svc.dna_detector.detect(profile, trace)

            replay_results: list[ReplayResult] = []
            first_overrides: dict[str, Any] = {}
            if replay_req is not None and req.counterfactual_policies:
                for idx, pol in enumerate(req.counterfactual_policies):
                    overrides = _policy_to_overrides(pol)
                    if idx == 0:
                        first_overrides = overrides
                    replay_results.append(simulate_counterfactual(replay_req, overrides))

            suggested_safeguards: list[str] = []
            for r in replay_results:
                suggested_safeguards.extend(generate_safeguard_recommendations(r))
            suggested_safeguards = list(dict.fromkeys(suggested_safeguards))

            verified_facts: list[str] = [
                f"Event chain integrity: {trace.integrity_status}",
                f"Total events recorded: {len(trace.ordered_events)}",
                f"Timeline stages verified: {sum(1 for e in timeline if e.integrity_verified)}/{len(timeline)}",
            ]
            if trace.recorded_decision:
                verified_facts.append(
                    f"Recorded Guardian decision: {trace.recorded_decision.outcome.value}"
                )

            deterministic_outcomes: list[str] = [
                f"Policy {trace.policy_version} original evaluation outcome: "
                f"{trace.recorded_decision.outcome.value if trace.recorded_decision else 'UNKNOWN'}"
            ]
            for r in replay_results:
                deterministic_outcomes.append(
                    f"Counterfactual replay under policy: {r.recomputed_outcome.value} (Drift: {r.drift_detected})"
                )

            statistical_signals: list[str] = [
                f"Agent DNA status: {dna_result.status} (Score: {dna_result.anomaly_score})"
            ]
            for sig in dna_result.signals:
                statistical_signals.append(f"DNA Signal: {sig.get('signal_type')}")

            ai_explanations: list[str] = [format_agent_dna_explanation(dna_result)]

            inv_id = uuid4()
            evidence_refs = [e.id for e in trace.authorization_evidence]
            report = InvestigationReport(
                investigation_id=inv_id,
                tenant_id=tenant_id,
                trace_id=trace.trace_id,
                payment_intent_id=trace.payment_intent_id,
                trace_integrity_status=trace.integrity_status,
                timeline=timeline,
                detected_anomalies=trace_anomalies,
                agent_dna_signals=dna_result.signals,
                counterfactual_replay_results=replay_results,
                suggested_safeguards=suggested_safeguards,
                evidence_references=evidence_refs,
                missing_evidence=trace.missing_evidence,
                confidence_limitations=[
                    "Agent DNA anomaly signals are statistical indicators and do not constitute proof of fraud.",
                    "Guardian remains the authoritative spending policy governance boundary.",
                ],
                verified_facts=verified_facts,
                deterministic_policy_outcomes=deterministic_outcomes,
                statistical_anomaly_signals=statistical_signals,
                ai_explanations=ai_explanations,
            )

            if repo is not None:
                actor = (
                    getattr(http_request.state, "authenticated_actor_id", str(tenant_id))
                    if http_request is not None
                    else str(tenant_id)
                )
                if replay_results:
                    persisted_result = replay_results[0].model_copy(update={"replay_id": inv_id})
                    mode = "COUNTERFACTUAL"
                    overrides_payload = first_overrides
                elif baseline_result is not None:
                    persisted_result = baseline_result.model_copy(update={"replay_id": inv_id})
                    mode = "REPLAY"
                    overrides_payload = {}
                else:
                    corr_id = (
                        trace.ordered_events[0].correlation_id
                        if trace.ordered_events
                        else trace.payment_intent_id
                    )
                    fallback_outcome = (
                        trace.recorded_decision.outcome
                        if trace.recorded_decision is not None
                        else DecisionOutcome.DENY
                    )
                    persisted_result = ReplayResult(
                        replay_id=inv_id,
                        tenant_id=tenant_id,
                        correlation_id=corr_id,
                        payment_intent_id=trace.payment_intent_id,
                        policy_version=trace.policy_version,
                        timeline=timeline,
                        original_outcome=fallback_outcome,
                        recomputed_outcome=fallback_outcome,
                        missing_evidence=trace.missing_evidence,
                        anomalies=trace_anomalies,
                        integrity_valid=(trace.integrity_status == "VALID"),
                        consistency_status="INCOMPLETE_EVIDENCE",
                        explanation="Investigation recorded with incomplete trace evidence.",
                        evidence_references=evidence_refs,
                        executed_payment=False,
                    )
                    mode = "REPLAY"
                    overrides_payload = {}

                repo.save_investigation(
                    tenant_id=tenant_id,
                    result=persisted_result,
                    mode=mode,
                    overrides=overrides_payload,
                    created_by=str(actor),
                )
            else:
                svc.investigations[inv_id] = report

            return report
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
        http_request: Request = None,  # type: ignore[assignment]
        auth: Annotated[AuthContext | None, Depends(auth_dep)] = None,
    ) -> PersistedInvestigation | InvestigationReport:
        _enforce_permission(http_request, tenant_id, Permission.GHOSTPAY_READ, repo, auth)
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
        http_request: Request = None,  # type: ignore[assignment]
        repo: Annotated[GhostPayReplayRepository | None, Depends(repo_dep)] = None,
        auth: Annotated[AuthContext | None, Depends(auth_dep)] = None,
    ) -> DisputeOSEvidenceBundle:
        _enforce_permission(http_request, tenant_id, Permission.GHOSTPAY_READ, repo, auth)
        try:
            if repo is not None:
                persisted = repo.get_investigation(tenant_id, investigation_id)
                if persisted is not None:
                    trace: PaymentTrace | None = None
                    replay_req = repo.load_replay_request_by_payment(
                        tenant_id, persisted.payment_intent_id
                    )
                    if replay_req is not None:
                        trace = _trace_from_replay_request(persisted.payment_intent_id, replay_req)
                    else:
                        loaded = repo.load_timeline_records_by_payment(
                            tenant_id, persisted.payment_intent_id
                        )
                        if loaded is not None:
                            events, ev_recs = loaded
                            trace = PaymentTrace(
                                trace_id=persisted.payment_intent_id,
                                tenant_id=tenant_id,
                                agent_id=persisted.payment_intent_id,
                                payment_intent_id=persisted.payment_intent_id,
                                ordered_events=events,
                                authorization_evidence=ev_recs,
                                policy_version=persisted.policy_version,
                                integrity_status="VALID" if persisted.integrity_valid else "TAMPERED",
                            )
                        else:
                            lister = getattr(repo, "list_ghostpay_traces", None)
                            if callable(lister):
                                for candidate in lister(tenant_id, limit=200, offset=0):
                                    if candidate.payment_intent_id == persisted.payment_intent_id:
                                        trace = candidate
                                        break
                    if trace is None:
                        raise TraceNotFoundError(
                            f"Trace for payment_intent {persisted.payment_intent_id} not found"
                        )
                    inv_summary = InvestigationReport(
                        investigation_id=persisted.investigation_id,
                        tenant_id=persisted.tenant_id,
                        trace_id=trace.trace_id,
                        payment_intent_id=persisted.payment_intent_id,
                        trace_integrity_status=trace.integrity_status,
                        timeline=persisted.result.timeline,
                        detected_anomalies=persisted.result.anomalies,
                        counterfactual_replay_results=(
                            [persisted.result] if persisted.mode == "COUNTERFACTUAL" else []
                        ),
                        evidence_references=persisted.result.evidence_references,
                        missing_evidence=persisted.result.missing_evidence,
                        created_at=persisted.created_at,
                    )
                    return export_to_disputeos(trace, inv_summary)

            inv = svc.get_investigation(tenant_id, investigation_id)
            trace_id = inv.trace_id if inv.trace_id is not None else inv.payment_intent_id
            trace = _load_trace(tenant_id, trace_id, repo)
            return export_to_disputeos(trace, inv)
        except Exception as exc:
            _raise_http_for_domain_error(exc)
            raise

    return api_router


# Default router instance
router = create_ghostpay_router()
