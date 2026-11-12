"""Session-per-request authenticated Guardian router for the unified AEGIS API."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Annotated, Any
from uuid import UUID, uuid4

from contracts import (
    AgentIdentity,
    ApprovalStatus,
    Merchant,
    PassportStatus,
    PaymentIntent,
    PaymentState,
    SpendingPassport,
)
from database import LedgerRepository, PlatformRepository
from fastapi import APIRouter, Depends, HTTPException, Query, status
from guardian import GuardianService
from guardian.api.models import (
    ApprovalActionResponse,
    BuyerApprovedRequest,
    BuyerDeclinedRequest,
    CaptureRequest,
    CheckoutResponse,
    HumanApprovalRequest,
    InitiateCheckoutRequest,
    ProposalSubmissionResponse,
    ReconcileRequest,
    SubmitProposalRequest,
)
from guardian.domain.exceptions import (
    ApprovalExpiredError,
    ApprovalMismatchError,
    ApprovalNotFoundError,
    AttemptNotFoundError,
    DuplicateIntentError,
    GuardianError,
    InsufficientBudgetError,
    IntentNotFoundError,
    InvalidStateTransitionError,
    PolicyDeniedError,
)
from paypal import PayPalAPIError, PayPalSandboxClient, PayPalTimeoutError
from pydantic import BaseModel, ConfigDict, Field
from security import AuthContext, Permission, assert_same_tenant
from sqlalchemy.orm import Session

from aegis_api.deps import get_db_session, get_paypal_client, require_permission

router = APIRouter(prefix="/guardian", tags=["guardian"])


class CreateAgentRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=120)
    purpose: str = Field(default="autonomous-purchasing", max_length=255)
    framework: str = Field(default="langgraph", max_length=64)
    public_fingerprint: str = Field(min_length=8, max_length=128)


class UpdateAgentStatusRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: str = Field(pattern=r"^(ACTIVE|SUSPENDED|REVOKED)$")


class CreateMerchantRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=160)
    domain: str = Field(min_length=1, max_length=255)
    category: str = Field(default="SOFTWARE", max_length=64)
    paypal_merchant_id: str | None = Field(default=None, max_length=128)
    is_allowlisted: bool = True
    is_sandbox_verified: bool = True


class UpdateMerchantAllowlistRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    is_allowlisted: bool


class CreatePassportRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    agent_id: UUID
    policy_version: str = Field(default="policy-v1", max_length=64)
    currency: str = Field(default="USD", min_length=3, max_length=3)
    total_budget_minor: int = Field(ge=0)
    per_tx_limit_minor: int = Field(ge=0)
    daily_limit_minor: int = Field(ge=0)
    human_approval_threshold_minor: int = Field(default=5000, ge=0)
    allowed_merchant_ids: list[UUID] = Field(default_factory=list)
    allowed_categories: list[str] = Field(default_factory=list)
    allow_unknown_merchants: bool = False
    expires_in_days: int = Field(default=30, ge=1, le=3650)


class UpdatePassportRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    per_tx_limit_minor: int | None = Field(default=None, ge=0)
    daily_limit_minor: int | None = Field(default=None, ge=0)
    human_approval_threshold_minor: int | None = Field(default=None, ge=0)
    allowed_merchant_ids: list[UUID] | None = None
    allowed_categories: list[str] | None = None
    allow_unknown_merchants: bool | None = None


class AuthenticatedProposalRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tenant_id: UUID | None = None
    agent_id: UUID
    passport_id: UUID
    merchant_id: UUID
    merchant_name: str = Field(min_length=1, max_length=160)
    merchant_category: str = Field(default="SOFTWARE", max_length=64)
    amount_minor: int = Field(gt=0)
    currency: str = Field(default="USD", min_length=3, max_length=3)
    item_summary: str = Field(min_length=1, max_length=500)
    line_items: list[dict[str, Any]] = Field(default_factory=list)
    rationale: str = Field(min_length=1, max_length=1000)
    idempotency_key: str = Field(min_length=8, max_length=128)
    quote_expires_in_seconds: int = Field(default=1800, ge=60, le=86400)


def _guardian_service(session: Session, paypal_client: PayPalSandboxClient) -> GuardianService:
    return GuardianService(repo=LedgerRepository(session), paypal_client=paypal_client)


@router.get("/agents", response_model=list[AgentIdentity])
def list_agents(
    auth: Annotated[AuthContext, Depends(require_permission(Permission.AGENTS_READ))],
    session: Annotated[Session, Depends(get_db_session)],
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[AgentIdentity]:
    agents = LedgerRepository(session).list_agents(auth.tenant_id)
    return agents[offset : offset + limit]


@router.post("/agents", response_model=AgentIdentity, status_code=status.HTTP_201_CREATED)
def create_agent(
    payload: CreateAgentRequest,
    auth: Annotated[AuthContext, Depends(require_permission(Permission.AGENTS_WRITE))],
    session: Annotated[Session, Depends(get_db_session)],
) -> AgentIdentity:
    ledger = LedgerRepository(session)
    platform = PlatformRepository(session)
    agent = ledger.create_agent(
        AgentIdentity(
            id=uuid4(),
            tenant_id=auth.tenant_id,
            name=payload.name,
            purpose=payload.purpose,
            framework=payload.framework,
            status="ACTIVE",
            public_fingerprint=payload.public_fingerprint,
        )
    )
    platform.record_admin_audit(
        tenant_id=auth.tenant_id,
        actor_type=auth.actor_type,
        actor_id=auth.actor_id,
        action="AGENT_CREATED",
        resource_type="agent",
        resource_id=str(agent.id),
        details={"name": agent.name},
    )
    return agent


@router.patch("/agents/{agent_id}/status", response_model=AgentIdentity)
def update_agent_status(
    agent_id: UUID,
    payload: UpdateAgentStatusRequest,
    auth: Annotated[AuthContext, Depends(require_permission(Permission.AGENTS_WRITE))],
    session: Annotated[Session, Depends(get_db_session)],
) -> AgentIdentity:
    ledger = LedgerRepository(session)
    platform = PlatformRepository(session)
    try:
        updated = ledger.update_agent_status(auth.tenant_id, agent_id, payload.status)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    platform.record_admin_audit(
        tenant_id=auth.tenant_id,
        actor_type=auth.actor_type,
        actor_id=auth.actor_id,
        action="AGENT_STATUS_UPDATED",
        resource_type="agent",
        resource_id=str(agent_id),
        details={"status": payload.status},
    )
    return updated


@router.get("/merchants", response_model=list[Merchant])
def list_merchants(
    auth: Annotated[AuthContext, Depends(require_permission(Permission.PASSPORTS_READ))],
    session: Annotated[Session, Depends(get_db_session)],
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[Merchant]:
    merchants = LedgerRepository(session).list_merchants(auth.tenant_id)
    return merchants[offset : offset + limit]


@router.post("/merchants", response_model=Merchant, status_code=status.HTTP_201_CREATED)
def create_merchant(
    payload: CreateMerchantRequest,
    auth: Annotated[AuthContext, Depends(require_permission(Permission.PASSPORTS_WRITE))],
    session: Annotated[Session, Depends(get_db_session)],
) -> Merchant:
    ledger = LedgerRepository(session)
    return ledger.create_merchant(
        Merchant(
            id=uuid4(),
            tenant_id=auth.tenant_id,
            name=payload.name,
            domain=payload.domain,
            category=payload.category,
            paypal_merchant_id=payload.paypal_merchant_id,
            is_allowlisted=payload.is_allowlisted,
            is_sandbox_verified=payload.is_sandbox_verified,
        )
    )


@router.patch("/merchants/{merchant_id}/allowlist", response_model=Merchant)
def toggle_merchant_allowlist(
    merchant_id: UUID,
    payload: UpdateMerchantAllowlistRequest,
    auth: Annotated[AuthContext, Depends(require_permission(Permission.PASSPORTS_WRITE))],
    session: Annotated[Session, Depends(get_db_session)],
) -> Merchant:
    try:
        return LedgerRepository(session).update_merchant_allowlist(
            auth.tenant_id, merchant_id, is_allowlisted=payload.is_allowlisted
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.get("/passports", response_model=list[SpendingPassport])
def list_passports(
    auth: Annotated[AuthContext, Depends(require_permission(Permission.PASSPORTS_READ))],
    session: Annotated[Session, Depends(get_db_session)],
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[SpendingPassport]:
    passports = LedgerRepository(session).list_passports(auth.tenant_id)
    return passports[offset : offset + limit]


@router.post("/passports", response_model=SpendingPassport, status_code=status.HTTP_201_CREATED)
def issue_passport(
    payload: CreatePassportRequest,
    auth: Annotated[AuthContext, Depends(require_permission(Permission.PASSPORTS_WRITE))],
    session: Annotated[Session, Depends(get_db_session)],
) -> SpendingPassport:
    ledger = LedgerRepository(session)
    platform = PlatformRepository(session)
    agent = ledger.get_agent(auth.tenant_id, payload.agent_id)
    if agent is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Agent not found in organization.")
    passport = ledger.create_passport(
        SpendingPassport(
            id=uuid4(),
            tenant_id=auth.tenant_id,
            agent_id=payload.agent_id,
            policy_version=payload.policy_version,
            currency=payload.currency,
            total_budget_minor=payload.total_budget_minor,
            per_tx_limit_minor=payload.per_tx_limit_minor,
            daily_limit_minor=payload.daily_limit_minor,
            human_approval_threshold_minor=payload.human_approval_threshold_minor,
            allowed_merchant_ids=payload.allowed_merchant_ids,
            allowed_categories=payload.allowed_categories,
            allow_unknown_merchants=payload.allow_unknown_merchants,
            status=PassportStatus.ACTIVE,
            expires_at=datetime.now(UTC) + timedelta(days=payload.expires_in_days),
        )
    )
    platform.record_admin_audit(
        tenant_id=auth.tenant_id,
        actor_type=auth.actor_type,
        actor_id=auth.actor_id,
        action="PASSPORT_ISSUED",
        resource_type="spending_passport",
        resource_id=str(passport.id),
        details={"agent_id": str(payload.agent_id), "total_budget_minor": payload.total_budget_minor},
    )
    return passport


@router.patch("/passports/{passport_id}", response_model=SpendingPassport)
def update_passport_policy(
    passport_id: UUID,
    payload: UpdatePassportRequest,
    auth: Annotated[AuthContext, Depends(require_permission(Permission.PASSPORTS_WRITE))],
    session: Annotated[Session, Depends(get_db_session)],
) -> SpendingPassport:
    ledger = LedgerRepository(session)
    try:
        return ledger.update_passport_policy(
            auth.tenant_id,
            passport_id,
            per_tx_limit_minor=payload.per_tx_limit_minor,
            daily_limit_minor=payload.daily_limit_minor,
            human_approval_threshold_minor=payload.human_approval_threshold_minor,
            allowed_merchant_ids=payload.allowed_merchant_ids,
            allowed_categories=payload.allowed_categories,
            allow_unknown_merchants=payload.allow_unknown_merchants,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.post("/passports/{passport_id}/revoke", response_model=SpendingPassport)
def revoke_passport(
    passport_id: UUID,
    auth: Annotated[AuthContext, Depends(require_permission(Permission.PASSPORTS_WRITE))],
    session: Annotated[Session, Depends(get_db_session)],
) -> SpendingPassport:
    ledger = LedgerRepository(session)
    platform = PlatformRepository(session)
    try:
        passport = ledger.update_passport_policy(auth.tenant_id, passport_id, status=PassportStatus.REVOKED)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    platform.record_admin_audit(
        tenant_id=auth.tenant_id,
        actor_type=auth.actor_type,
        actor_id=auth.actor_id,
        action="PASSPORT_REVOKED",
        resource_type="spending_passport",
        resource_id=str(passport_id),
    )
    return passport


@router.get("/approvals")
def list_approvals(
    auth: Annotated[AuthContext, Depends(require_permission(Permission.PAYMENTS_READ))],
    session: Annotated[Session, Depends(get_db_session)],
    status_filter: ApprovalStatus | None = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[dict[str, Any]]:
    approvals = LedgerRepository(session).list_approvals(
        auth.tenant_id, status=status_filter, limit=limit, offset=offset
    )
    return [a.model_dump(mode="json") for a in approvals]


@router.get("/payments", response_model=list[PaymentIntent])
def list_payment_intents(
    auth: Annotated[AuthContext, Depends(require_permission(Permission.PAYMENTS_READ))],
    session: Annotated[Session, Depends(get_db_session)],
    state: PaymentState | None = None,
    agent_id: UUID | None = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[PaymentIntent]:
    return LedgerRepository(session).list_intents(
        auth.tenant_id, state=state, agent_id=agent_id, limit=limit, offset=offset
    )


@router.post("/proposals", response_model=ProposalSubmissionResponse, status_code=status.HTTP_201_CREATED)
def submit_proposal(
    request: AuthenticatedProposalRequest,
    auth: Annotated[AuthContext, Depends(require_permission(Permission.PROPOSALS_WRITE))],
    session: Annotated[Session, Depends(get_db_session)],
    paypal_client: Annotated[PayPalSandboxClient, Depends(get_paypal_client)],
) -> ProposalSubmissionResponse:
    if request.tenant_id is not None:
        assert_same_tenant(auth.tenant_id, request.tenant_id, "proposal_request")
    submit_req = SubmitProposalRequest(
        tenant_id=auth.tenant_id,
        agent_id=request.agent_id,
        passport_id=request.passport_id,
        merchant_id=request.merchant_id,
        merchant_name=request.merchant_name,
        merchant_category=request.merchant_category,
        amount_minor=request.amount_minor,
        currency=request.currency,
        item_summary=request.item_summary,
        line_items=request.line_items,
        rationale=request.rationale,
        idempotency_key=request.idempotency_key,
        quote_expires_in_seconds=request.quote_expires_in_seconds,
    )
    proposal, quote = submit_req.to_proposal_and_quote()
    svc = _guardian_service(session, paypal_client)
    try:
        intent, decision = svc.submit_proposal(proposal=proposal, quote=quote)
        return ProposalSubmissionResponse(payment_intent=intent, decision=decision)
    except DuplicateIntentError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"error": "DUPLICATE_INTENT", "message": str(exc)},
        ) from exc
    except PolicyDeniedError as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"error": "POLICY_DENIED", "message": str(exc), "reason_codes": exc.reason_codes},
        ) from exc
    except InsufficientBudgetError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"error": "INSUFFICIENT_BUDGET", "message": str(exc)},
        ) from exc
    except GuardianError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"error": "GUARDIAN_ERROR", "message": str(exc)},
        ) from exc


@router.post("/proposals/{intent_id}/approve", response_model=ApprovalActionResponse)
def approve_proposal(
    intent_id: UUID,
    request: HumanApprovalRequest,
    auth: Annotated[AuthContext, Depends(require_permission(Permission.APPROVALS_DECIDE))],
    session: Annotated[Session, Depends(get_db_session)],
    paypal_client: Annotated[PayPalSandboxClient, Depends(get_paypal_client)],
    approval_id: UUID | None = None,
) -> ApprovalActionResponse:
    svc = _guardian_service(session, paypal_client)
    resolved_approval_id = approval_id
    if resolved_approval_id is None:
        intent = svc.get_intent(auth.tenant_id, intent_id)
        if intent is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="PaymentIntent not found")
        resolved_approval_id = intent.approval_record_id
        if resolved_approval_id is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No pending approval bound to intent")

    approver = auth.email or auth.actor_id or request.approver_id
    try:
        if request.approved is False:
            intent, approval = svc.reject_approval(
                tenant_id=auth.tenant_id,
                intent_id=intent_id,
                approval_id=resolved_approval_id,
                approver_id=approver,
                comment=request.comment,
            )
            return ApprovalActionResponse(payment_intent=intent, approval=approval)

        intent, approval = svc.approve_and_consume(
            tenant_id=auth.tenant_id,
            intent_id=intent_id,
            approval_id=resolved_approval_id,
            approver_id=approver,
            comment=request.comment,
        )
        return ApprovalActionResponse(payment_intent=intent, approval=approval)
    except ApprovalExpiredError as exc:
        raise HTTPException(
            status_code=status.HTTP_410_GONE,
            detail={"error": "APPROVAL_EXPIRED", "message": str(exc)},
        ) from exc
    except ApprovalMismatchError as exc:
        raise HTTPException(
            status_code=422,
            detail={"error": "APPROVAL_MISMATCH", "message": str(exc)},
        ) from exc
    except (ApprovalNotFoundError, IntentNotFoundError) as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": "NOT_FOUND", "message": str(exc)},
        ) from exc
    except GuardianError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"error": "GUARDIAN_ERROR", "message": str(exc)},
        ) from exc


@router.post("/payments/{intent_id}/checkout", response_model=CheckoutResponse)
async def initiate_checkout(
    intent_id: UUID,
    request: InitiateCheckoutRequest,
    auth: Annotated[AuthContext, Depends(require_permission(Permission.PAYMENTS_CHECKOUT))],
    session: Annotated[Session, Depends(get_db_session)],
    paypal_client: Annotated[PayPalSandboxClient, Depends(get_paypal_client)],
) -> CheckoutResponse:
    svc = _guardian_service(session, paypal_client)
    try:
        intent, attempt = await svc.initiate_checkout(
            tenant_id=auth.tenant_id,
            intent_id=intent_id,
            attempt_number=request.attempt_number,
            idempotency_key=request.idempotency_key,
            return_url=request.return_url,
            cancel_url=request.cancel_url,
        )
        return CheckoutResponse(
            payment_intent=intent,
            attempt=attempt,
            approval_url=attempt.paypal_approval_url,
        )
    except IntentNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail={"error": "INTENT_NOT_FOUND", "message": str(exc)}) from exc
    except InvalidStateTransitionError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail={"error": "INVALID_STATE", "message": str(exc)}) from exc
    except PayPalTimeoutError as exc:
        raise HTTPException(status_code=status.HTTP_504_GATEWAY_TIMEOUT, detail={"error": "PAYPAL_TIMEOUT", "message": str(exc)}) from exc
    except PayPalAPIError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail={"error": "PAYPAL_API_ERROR", "message": str(exc)}) from exc
    except GuardianError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail={"error": "GUARDIAN_ERROR", "message": str(exc)}) from exc


@router.post("/payments/{intent_id}/buyer-approved")
def handle_buyer_approved(
    intent_id: UUID,
    request: BuyerApprovedRequest,
    auth: Annotated[AuthContext, Depends(require_permission(Permission.PAYMENTS_CHECKOUT))],
    session: Annotated[Session, Depends(get_db_session)],
    paypal_client: Annotated[PayPalSandboxClient, Depends(get_paypal_client)],
) -> dict[str, Any]:
    svc = _guardian_service(session, paypal_client)
    try:
        intent, attempt = svc.handle_buyer_approved(
            tenant_id=auth.tenant_id,
            intent_id=intent_id,
            attempt_id=request.attempt_id,
            payer_id=request.payer_id,
        )
        return {"payment_intent": intent.model_dump(mode="json"), "attempt": attempt.model_dump(mode="json")}
    except (IntentNotFoundError, AttemptNotFoundError) as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail={"error": "NOT_FOUND", "message": str(exc)}) from exc


@router.post("/payments/{intent_id}/capture")
async def execute_capture(
    intent_id: UUID,
    request: CaptureRequest,
    auth: Annotated[AuthContext, Depends(require_permission(Permission.PAYMENTS_CAPTURE))],
    session: Annotated[Session, Depends(get_db_session)],
    paypal_client: Annotated[PayPalSandboxClient, Depends(get_paypal_client)],
) -> dict[str, Any]:
    svc = _guardian_service(session, paypal_client)
    try:
        intent, attempt = await svc.execute_capture(
            tenant_id=auth.tenant_id,
            intent_id=intent_id,
            attempt_id=request.attempt_id,
        )
        return {"payment_intent": intent.model_dump(mode="json"), "attempt": attempt.model_dump(mode="json")}
    except (IntentNotFoundError, AttemptNotFoundError) as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail={"error": "NOT_FOUND", "message": str(exc)}) from exc
    except InvalidStateTransitionError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail={"error": "INVALID_STATE", "message": str(exc)}) from exc
    except PayPalTimeoutError as exc:
        raise HTTPException(status_code=status.HTTP_504_GATEWAY_TIMEOUT, detail={"error": "PAYPAL_TIMEOUT", "message": str(exc)}) from exc
    except PayPalAPIError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail={"error": "PAYPAL_API_ERROR", "message": str(exc)}) from exc
    except GuardianError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail={"error": "GUARDIAN_ERROR", "message": str(exc)}) from exc


@router.post("/payments/{intent_id}/buyer-declined")
def handle_buyer_declined(
    intent_id: UUID,
    request: BuyerDeclinedRequest,
    auth: Annotated[AuthContext, Depends(require_permission(Permission.PAYMENTS_CHECKOUT))],
    session: Annotated[Session, Depends(get_db_session)],
    paypal_client: Annotated[PayPalSandboxClient, Depends(get_paypal_client)],
) -> dict[str, Any]:
    svc = _guardian_service(session, paypal_client)
    try:
        intent, attempt = svc.handle_buyer_declined(
            tenant_id=auth.tenant_id,
            intent_id=intent_id,
            attempt_id=request.attempt_id,
            reason=request.reason,
        )
        return {"payment_intent": intent.model_dump(mode="json"), "attempt": attempt.model_dump(mode="json")}
    except (IntentNotFoundError, AttemptNotFoundError) as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail={"error": "NOT_FOUND", "message": str(exc)}) from exc


@router.post("/payments/{intent_id}/reconcile")
async def reconcile_pending(
    intent_id: UUID,
    request: ReconcileRequest,
    auth: Annotated[AuthContext, Depends(require_permission(Permission.PAYMENTS_CAPTURE))],
    session: Annotated[Session, Depends(get_db_session)],
    paypal_client: Annotated[PayPalSandboxClient, Depends(get_paypal_client)],
) -> dict[str, Any]:
    svc = _guardian_service(session, paypal_client)
    try:
        intent, attempt = await svc.reconcile_pending(
            tenant_id=auth.tenant_id,
            intent_id=intent_id,
            attempt_id=request.attempt_id,
        )
        return {"payment_intent": intent.model_dump(mode="json"), "attempt": attempt.model_dump(mode="json")}
    except (IntentNotFoundError, AttemptNotFoundError) as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail={"error": "NOT_FOUND", "message": str(exc)}) from exc
    except PayPalTimeoutError as exc:
        raise HTTPException(status_code=status.HTTP_504_GATEWAY_TIMEOUT, detail={"error": "PAYPAL_TIMEOUT", "message": str(exc)}) from exc
    except PayPalAPIError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail={"error": "PAYPAL_API_ERROR", "message": str(exc)}) from exc
    except GuardianError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail={"error": "GUARDIAN_ERROR", "message": str(exc)}) from exc


@router.post("/payments/{intent_id}/refund")
async def refund_payment(
    intent_id: UUID,
    auth: Annotated[AuthContext, Depends(require_permission(Permission.PAYMENTS_CAPTURE))],
    session: Annotated[Session, Depends(get_db_session)],
    paypal_client: Annotated[PayPalSandboxClient, Depends(get_paypal_client)],
    amount_minor: int | None = None,
    note: str | None = None,
) -> dict[str, Any]:
    svc = _guardian_service(session, paypal_client)
    try:
        intent, refund_res = await svc.refund_intent(
            tenant_id=auth.tenant_id,
            intent_id=intent_id,
            amount_minor=amount_minor,
            note=note,
        )
        return {
            "payment_intent": intent.model_dump(mode="json"),
            "refund": getattr(refund_res, "__dict__", str(refund_res)),
        }
    except IntentNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except InvalidStateTransitionError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except PayPalTimeoutError as exc:
        raise HTTPException(status_code=status.HTTP_504_GATEWAY_TIMEOUT, detail=str(exc)) from exc
    except PayPalAPIError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc
    except GuardianError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.post("/payments/{intent_id}/void")
async def void_payment(
    intent_id: UUID,
    auth: Annotated[AuthContext, Depends(require_permission(Permission.PAYMENTS_CAPTURE))],
    session: Annotated[Session, Depends(get_db_session)],
    paypal_client: Annotated[PayPalSandboxClient, Depends(get_paypal_client)],
    note: str | None = None,
) -> dict[str, Any]:
    svc = _guardian_service(session, paypal_client)
    try:
        intent = await svc.void_intent(
            tenant_id=auth.tenant_id,
            intent_id=intent_id,
            note=note,
        )
        return {"payment_intent": intent.model_dump(mode="json")}
    except IntentNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except InvalidStateTransitionError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except GuardianError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


class ReconcilePaymentRequest(BaseModel):
    attempt_id: UUID


@router.post("/payments/{intent_id}/reconcile")
async def reconcile_payment(
    intent_id: UUID,
    payload: ReconcilePaymentRequest,
    auth: Annotated[AuthContext, Depends(require_permission(Permission.PAYMENTS_CAPTURE))],
    session: Annotated[Session, Depends(get_db_session)],
    paypal_client: Annotated[PayPalSandboxClient, Depends(get_paypal_client)],
) -> dict[str, Any]:
    svc = _guardian_service(session, paypal_client)
    try:
        intent, attempt = await svc.reconcile_pending(
            tenant_id=auth.tenant_id,
            intent_id=intent_id,
            attempt_id=payload.attempt_id,
        )
        return {"payment_intent": intent.model_dump(mode="json"), "attempt": attempt.model_dump(mode="json")}
    except (IntentNotFoundError, AttemptNotFoundError) as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail={"error": "NOT_FOUND", "message": str(exc)}) from exc


@router.get("/payments/{intent_id}", response_model=PaymentIntent)
def get_payment_intent(
    intent_id: UUID,
    auth: Annotated[AuthContext, Depends(require_permission(Permission.PAYMENTS_READ))],
    session: Annotated[Session, Depends(get_db_session)],
) -> PaymentIntent:
    intent = LedgerRepository(session).get_intent(auth.tenant_id, intent_id)
    if intent is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"PaymentIntent {intent_id} not found")
    return intent


@router.get("/payments/{intent_id}/detail")
def get_payment_intent_detail(
    intent_id: UUID,
    auth: Annotated[AuthContext, Depends(require_permission(Permission.PAYMENTS_READ))],
    session: Annotated[Session, Depends(get_db_session)],
) -> dict[str, Any]:
    ledger = LedgerRepository(session)
    intent = ledger.get_intent(auth.tenant_id, intent_id)
    if intent is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"PaymentIntent {intent_id} not found")

    proposal = ledger.get_proposal(auth.tenant_id, intent.proposal_id)
    quote = ledger.get_quote(auth.tenant_id, intent.quote_snapshot_id)
    decision = ledger.get_decision(auth.tenant_id, intent.authorization_decision_id) if intent.authorization_decision_id else None
    approval = ledger.get_approval(auth.tenant_id, intent.approval_record_id) if intent.approval_record_id else None
    reservation = ledger.get_reservation(auth.tenant_id, intent.reservation_id) if intent.reservation_id else None
    attempts = ledger.list_attempts_for_intent(auth.tenant_id, intent.id)
    events = ledger.list_events(auth.tenant_id, payment_intent_id=intent.id)
    return {
        "payment_intent": intent.model_dump(mode="json"),
        "proposal": proposal.model_dump(mode="json") if proposal else None,
        "quote": quote.model_dump(mode="json") if quote else None,
        "decision": decision.model_dump(mode="json") if decision else None,
        "approval": approval.model_dump(mode="json") if approval else None,
        "reservation": reservation.model_dump(mode="json") if reservation else None,
        "attempts": [a.model_dump(mode="json") for a in attempts],
        "events": [e.model_dump(mode="json") for e in events],
    }
