"""FastAPI router for AgentPay Guardian.

Provides HTTP endpoints for proposal submission, human approvals,
checkout initiation, PayPal buyer approval, verified capture, and reconciliation.
"""

from __future__ import annotations

from uuid import UUID

from contracts import PaymentAttempt, PaymentIntent
from fastapi import APIRouter, Depends, HTTPException, status
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
    GuardianError,
    InsufficientBudgetError,
    IntentNotFoundError,
    InvalidStateTransitionError,
    PolicyDeniedError,
)
from guardian.domain.service import GuardianService


def create_guardian_router(
    service: GuardianService | None = None,
) -> APIRouter:
    """Factory to create an APIRouter configured with GuardianService."""
    api_router = APIRouter(prefix="/guardian", tags=["guardian"])

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
        svc: GuardianService = Depends(get_service),
    ) -> ProposalSubmissionResponse:
        proposal, quote = request.to_proposal_and_quote()
        try:
            intent, decision = svc.submit_proposal(proposal=proposal, quote=quote)
            return ProposalSubmissionResponse(payment_intent=intent, decision=decision)
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

    @api_router.post(
        "/proposals/{intent_id}/approve",
        response_model=ApprovalActionResponse,
    )
    def approve_proposal(
        intent_id: UUID,
        request: HumanApprovalRequest,
        tenant_id: UUID,
        approval_id: UUID,
        svc: GuardianService = Depends(get_service),
    ) -> ApprovalActionResponse:
        try:
            intent, approval = svc.approve_and_consume(
                tenant_id=tenant_id,
                intent_id=intent_id,
                approval_id=approval_id,
                approver_id=request.approver_id,
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
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail={"error": "APPROVAL_MISMATCH", "message": str(exc)},
            ) from exc
        except ApprovalNotFoundError as exc:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={"error": "APPROVAL_NOT_FOUND", "message": str(exc)},
            ) from exc
        except IntentNotFoundError as exc:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={"error": "INTENT_NOT_FOUND", "message": str(exc)},
            ) from exc
        except GuardianError as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={"error": "GUARDIAN_ERROR", "message": str(exc)},
            ) from exc

    @api_router.post(
        "/payments/{intent_id}/checkout",
        response_model=CheckoutResponse,
    )
    async def initiate_checkout(
        intent_id: UUID,
        request: InitiateCheckoutRequest,
        tenant_id: UUID,
        svc: GuardianService = Depends(get_service),
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
        except IntentNotFoundError as exc:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={"error": "INTENT_NOT_FOUND", "message": str(exc)},
            ) from exc
        except InvalidStateTransitionError as exc:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={"error": "INVALID_STATE", "message": str(exc)},
            ) from exc
        except GuardianError as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={"error": "GUARDIAN_ERROR", "message": str(exc)},
            ) from exc

    @api_router.post("/payments/{intent_id}/buyer-approved")
    def handle_buyer_approved(
        intent_id: UUID,
        request: BuyerApprovedRequest,
        tenant_id: UUID,
        svc: GuardianService = Depends(get_service),
    ) -> dict[str, Any]:
        try:
            intent, attempt = svc.handle_buyer_approved(
                tenant_id=tenant_id,
                intent_id=intent_id,
                attempt_id=request.attempt_id,
                payer_id=request.payer_id,
            )
            return {"payment_intent": intent.model_dump(mode="json"), "attempt": attempt.model_dump(mode="json")}
        except (IntentNotFoundError, AttemptNotFoundError) as exc:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={"error": "NOT_FOUND", "message": str(exc)},
            ) from exc

    @api_router.post("/payments/{intent_id}/capture")
    async def execute_capture(
        intent_id: UUID,
        request: CaptureRequest,
        tenant_id: UUID,
        svc: GuardianService = Depends(get_service),
    ) -> dict[str, Any]:
        try:
            intent, attempt = await svc.execute_capture(
                tenant_id=tenant_id,
                intent_id=intent_id,
                attempt_id=request.attempt_id,
            )
            return {"payment_intent": intent.model_dump(mode="json"), "attempt": attempt.model_dump(mode="json")}
        except (IntentNotFoundError, AttemptNotFoundError) as exc:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={"error": "NOT_FOUND", "message": str(exc)},
            ) from exc

    @api_router.post("/payments/{intent_id}/buyer-declined")
    def handle_buyer_declined(
        intent_id: UUID,
        request: BuyerDeclinedRequest,
        tenant_id: UUID,
        svc: GuardianService = Depends(get_service),
    ) -> dict[str, Any]:
        try:
            intent, attempt = svc.handle_buyer_declined(
                tenant_id=tenant_id,
                intent_id=intent_id,
                attempt_id=request.attempt_id,
                reason=request.reason,
            )
            return {"payment_intent": intent.model_dump(mode="json"), "attempt": attempt.model_dump(mode="json")}
        except (IntentNotFoundError, AttemptNotFoundError) as exc:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={"error": "NOT_FOUND", "message": str(exc)},
            ) from exc

    @api_router.post("/payments/{intent_id}/reconcile")
    async def reconcile_pending(
        intent_id: UUID,
        request: ReconcileRequest,
        tenant_id: UUID,
        svc: GuardianService = Depends(get_service),
    ) -> dict[str, Any]:
        try:
            intent, attempt = await svc.reconcile_pending(
                tenant_id=tenant_id,
                intent_id=intent_id,
                attempt_id=request.attempt_id,
            )
            return {"payment_intent": intent.model_dump(mode="json"), "attempt": attempt.model_dump(mode="json")}
        except (IntentNotFoundError, AttemptNotFoundError) as exc:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={"error": "NOT_FOUND", "message": str(exc)},
            ) from exc

    @api_router.get("/payments/{intent_id}", response_model=PaymentIntent)
    def get_payment_intent(
        intent_id: UUID,
        tenant_id: UUID,
        svc: GuardianService = Depends(get_service),
    ) -> PaymentIntent:
        intent = svc.get_intent(tenant_id, intent_id)
        if intent is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"PaymentIntent {intent_id} not found",
            )
        return intent

    return api_router


# Default router instance
router = create_guardian_router(None)
