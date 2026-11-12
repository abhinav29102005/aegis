"""FastAPI router for AgentPay Guardian (module-level adapter).

NOTE: The unified AEGIS API mounts the session-per-request RBAC-authenticated
``aegis_api.routers.guardian_db.router``. When mounted standalone, this module
router requires a trusted ``tenant_resolver`` (or ``request.state.authenticated_tenant_id``)
and rejects unauthenticated ``X-Tenant-Id`` usage outside dev/test environments.
"""

from collections.abc import Callable
from typing import Annotated, Any
from uuid import UUID

from contracts import PaymentIntent
from fastapi import APIRouter, Depends, Header, HTTPException, Request, status
from paypal import PayPalAPIError, PayPalTimeoutError
from security import TenantIsolationError, assert_same_tenant, get_settings
from security.settings import DEFAULT_TENANT_UUID

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
    RefundRequest,
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
from guardian.domain.service import GuardianService

_DEV_TEST_ENVS = frozenset({"development", "dev", "test", "testing", "local"})


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


def _raise_http_for_guardian_error(exc: Exception) -> None:
    if isinstance(exc, TenantIsolationError):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"error": "TENANT_ISOLATION", "message": str(exc)},
        ) from exc
    if isinstance(exc, PolicyDeniedError):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"error": "POLICY_DENIED", "message": str(exc), "reason_codes": exc.reason_codes},
        ) from exc
    if isinstance(exc, ApprovalExpiredError):
        raise HTTPException(
            status_code=status.HTTP_410_GONE,
            detail={"error": "APPROVAL_EXPIRED", "message": str(exc)},
        ) from exc
    if isinstance(exc, ApprovalMismatchError):
        raise HTTPException(
            status_code=422,
            detail={"error": "APPROVAL_MISMATCH", "message": str(exc)},
        ) from exc
    if isinstance(exc, (IntentNotFoundError, AttemptNotFoundError, ApprovalNotFoundError)):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": "NOT_FOUND", "message": str(exc)},
        ) from exc
    if isinstance(exc, DuplicateIntentError):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"error": "DUPLICATE_INTENT", "message": str(exc)},
        ) from exc
    if isinstance(exc, InvalidStateTransitionError):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"error": "INVALID_STATE", "message": str(exc)},
        ) from exc
    if isinstance(exc, InsufficientBudgetError):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"error": "INSUFFICIENT_BUDGET", "message": str(exc)},
        ) from exc
    if isinstance(exc, PayPalTimeoutError):
        raise HTTPException(
            status_code=status.HTTP_504_GATEWAY_TIMEOUT,
            detail={"error": "PAYPAL_TIMEOUT", "message": str(exc)},
        ) from exc
    if isinstance(exc, PayPalAPIError):
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail={"error": "PAYPAL_API_ERROR", "message": str(exc), "debug_id": exc.debug_id},
        ) from exc
    if isinstance(exc, GuardianError):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"error": "GUARDIAN_ERROR", "message": str(exc)},
        ) from exc


def create_guardian_router(
    service: GuardianService | None = None,
    *,
    tenant_resolver: Callable[..., UUID] | None = None,
) -> APIRouter:
    """Factory to create an APIRouter configured with GuardianService and tenant resolution."""
    api_router = APIRouter(prefix="/guardian", tags=["guardian"])
    resolve_tenant = tenant_resolver or get_dev_tenant_id

    def get_service() -> GuardianService:
        if service is None:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="GuardianService is not configured",
            )
        return service

    @api_router.post(
        "/proposals",
        response_model=ProposalSubmissionResponse,
        status_code=status.HTTP_201_CREATED,
    )
    def submit_proposal(
        request: SubmitProposalRequest,
        tenant_id: Annotated[UUID, Depends(resolve_tenant)],
        svc: Annotated[GuardianService, Depends(get_service)],
    ) -> ProposalSubmissionResponse:
        try:
            assert_same_tenant(tenant_id, request.tenant_id, "proposal_request")
            proposal, quote = request.to_proposal_and_quote()
            intent, decision = svc.submit_proposal(proposal=proposal, quote=quote)
            return ProposalSubmissionResponse(payment_intent=intent, decision=decision)
        except (TenantIsolationError, GuardianError) as exc:
            _raise_http_for_guardian_error(exc)
            raise

    @api_router.post(
        "/proposals/{intent_id}/approve",
        response_model=ApprovalActionResponse,
    )
    def approve_proposal(
        intent_id: UUID,
        request: HumanApprovalRequest,
        approval_id: UUID,
        tenant_id: Annotated[UUID, Depends(resolve_tenant)],
        svc: Annotated[GuardianService, Depends(get_service)],
    ) -> ApprovalActionResponse:
        try:
            intent, approval = svc.approve_and_consume(
                tenant_id=tenant_id,
                intent_id=intent_id,
                approval_id=approval_id,
                approver_id=request.approver_id,
                approved=request.approved,
                comment=request.comment,
            )
            return ApprovalActionResponse(payment_intent=intent, approval=approval)
        except GuardianError as exc:
            _raise_http_for_guardian_error(exc)
            raise

    @api_router.post(
        "/payments/{intent_id}/checkout",
        response_model=CheckoutResponse,
    )
    async def initiate_checkout(
        intent_id: UUID,
        request: InitiateCheckoutRequest,
        tenant_id: Annotated[UUID, Depends(resolve_tenant)],
        svc: Annotated[GuardianService, Depends(get_service)],
    ) -> CheckoutResponse:
        try:
            intent, attempt = await svc.initiate_checkout(
                tenant_id=tenant_id,
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
        except (GuardianError, PayPalTimeoutError, PayPalAPIError) as exc:
            _raise_http_for_guardian_error(exc)
            raise

    @api_router.post("/payments/{intent_id}/buyer-approved")
    def handle_buyer_approved(
        intent_id: UUID,
        request: BuyerApprovedRequest,
        tenant_id: Annotated[UUID, Depends(resolve_tenant)],
        svc: Annotated[GuardianService, Depends(get_service)],
    ) -> dict[str, Any]:
        try:
            intent, attempt = svc.handle_buyer_approved(
                tenant_id=tenant_id,
                intent_id=intent_id,
                attempt_id=request.attempt_id,
                payer_id=request.payer_id,
            )
            return {"payment_intent": intent.model_dump(mode="json"), "attempt": attempt.model_dump(mode="json")}
        except GuardianError as exc:
            _raise_http_for_guardian_error(exc)
            raise

    @api_router.post("/payments/{intent_id}/capture")
    async def execute_capture(
        intent_id: UUID,
        request: CaptureRequest,
        tenant_id: Annotated[UUID, Depends(resolve_tenant)],
        svc: Annotated[GuardianService, Depends(get_service)],
    ) -> dict[str, Any]:
        try:
            intent, attempt = await svc.execute_capture(
                tenant_id=tenant_id,
                intent_id=intent_id,
                attempt_id=request.attempt_id,
            )
            return {"payment_intent": intent.model_dump(mode="json"), "attempt": attempt.model_dump(mode="json")}
        except (GuardianError, PayPalTimeoutError, PayPalAPIError) as exc:
            _raise_http_for_guardian_error(exc)
            raise

    @api_router.post("/payments/{intent_id}/buyer-declined")
    def handle_buyer_declined(
        intent_id: UUID,
        request: BuyerDeclinedRequest,
        tenant_id: Annotated[UUID, Depends(resolve_tenant)],
        svc: Annotated[GuardianService, Depends(get_service)],
    ) -> dict[str, Any]:
        try:
            intent, attempt = svc.handle_buyer_declined(
                tenant_id=tenant_id,
                intent_id=intent_id,
                attempt_id=request.attempt_id,
                reason=request.reason,
            )
            return {"payment_intent": intent.model_dump(mode="json"), "attempt": attempt.model_dump(mode="json")}
        except GuardianError as exc:
            _raise_http_for_guardian_error(exc)
            raise

    @api_router.post("/payments/{intent_id}/reconcile")
    async def reconcile_pending(
        intent_id: UUID,
        request: ReconcileRequest,
        tenant_id: Annotated[UUID, Depends(resolve_tenant)],
        svc: Annotated[GuardianService, Depends(get_service)],
    ) -> dict[str, Any]:
        try:
            intent, attempt = await svc.reconcile_pending(
                tenant_id=tenant_id,
                intent_id=intent_id,
                attempt_id=request.attempt_id,
            )
            return {"payment_intent": intent.model_dump(mode="json"), "attempt": attempt.model_dump(mode="json")}
        except (GuardianError, PayPalTimeoutError, PayPalAPIError) as exc:
            _raise_http_for_guardian_error(exc)
            raise

    @api_router.post("/payments/{intent_id}/refund")
    async def refund_payment(
        intent_id: UUID,
        request: RefundRequest,
        tenant_id: Annotated[UUID, Depends(resolve_tenant)],
        svc: Annotated[GuardianService, Depends(get_service)],
    ) -> dict[str, Any]:
        try:
            intent, attempt, refund_res = await svc.refund_payment(
                tenant_id=tenant_id,
                intent_id=intent_id,
                attempt_id=request.attempt_id,
                amount_minor=request.amount_minor,
                reason=request.reason,
            )
            return {
                "payment_intent": intent.model_dump(mode="json"),
                "attempt": attempt.model_dump(mode="json"),
                "refund": refund_res,
            }
        except (GuardianError, PayPalTimeoutError, PayPalAPIError) as exc:
            _raise_http_for_guardian_error(exc)
            raise

    @api_router.get("/payments/{intent_id}", response_model=PaymentIntent)
    def get_payment_intent(
        intent_id: UUID,
        tenant_id: Annotated[UUID, Depends(resolve_tenant)],
        svc: Annotated[GuardianService, Depends(get_service)],
    ) -> PaymentIntent:
        intent = svc.get_intent(tenant_id, intent_id)
        if intent is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"PaymentIntent {intent_id} not found",
            )
        return intent

    return api_router


# Default router instance (gated by get_dev_tenant_id; rejected in non-dev/test without auth middleware)
router = create_guardian_router(None)

