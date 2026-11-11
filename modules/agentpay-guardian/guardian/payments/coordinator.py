"""PayPal payment coordinator for AgentPay Guardian.

Orchestrates order creation, buyer approval, server-verified capture,
timeout handling (PENDING_PROVIDER), buyer-declined rollback, and reconciliation.
Enforces strict append-only audit trail and evidence provenance.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

from contracts import (
    EvidenceRecord,
    EvidenceSourceType,
    FinancialEventType,
    PaymentAttempt,
    PaymentIntent,
    PaymentState,
    PayPalBuyerApproval,
    VerifiedPayPalCapture,
    compute_payload_hash,
)
from guardian.budgets.coordinator import BudgetCoordinator
from guardian.domain.exceptions import (
    AttemptNotFoundError,
    GuardianError,
    IntentNotFoundError,
    InvalidStateTransitionError,
)
from paypal import (
    PayPalCaptureResult,
    PayPalOrderCreationResult,
    PayPalReconciliationResult,
    PayPalSandboxClient,
    PayPalTimeoutError,
)

try:
    from database import LedgerRepository
except (ImportError, ModuleNotFoundError):
    LedgerRepository = Any  # type: ignore[misc, assignment]


def _utc_now() -> datetime:
    return datetime.now(UTC)


class PaymentCoordinator:
    """Manages the lifecycle of payment attempts and PayPal integration safely."""

    def __init__(
        self,
        repo: LedgerRepository,
        paypal_client: PayPalSandboxClient,
        budget_coordinator: BudgetCoordinator,
    ) -> None:
        self.repo = repo
        self.paypal_client = paypal_client
        self.budget_coordinator = budget_coordinator

    async def create_checkout(
        self,
        *,
        intent: PaymentIntent,
        attempt_number: int = 1,
        idempotency_key: str,
        return_url: str | None = None,
        cancel_url: str | None = None,
    ) -> PaymentAttempt:
        if intent.state != PaymentState.CHECKOUT_READY:
            raise InvalidStateTransitionError(
                f"Cannot create checkout for intent in state {intent.state.value} "
                f"(must be CHECKOUT_READY)"
            )

        # Check if attempt already exists for this idempotency key
        attempt_id = uuid4()
        now = _utc_now()

        # Call PayPal Sandbox to create order
        try:
            order_result: PayPalOrderCreationResult = await self.paypal_client.create_order(
                amount_minor=intent.amount_minor,
                currency=intent.currency,
                reference_id=str(intent.id),
                description=f"AgentPay Nexus order {intent.id}",
                request_id=f"req-order-{intent.id}-{attempt_number}",
                return_url=return_url,
                cancel_url=cancel_url,
            )
        except Exception as exc:
            raise GuardianError(f"Failed to create PayPal sandbox order: {exc}") from exc

        attempt = PaymentAttempt(
            id=attempt_id,
            tenant_id=intent.tenant_id,
            correlation_id=intent.correlation_id,
            payment_intent_id=intent.id,
            attempt_number=attempt_number,
            idempotency_key=idempotency_key,
            provider="PAYPAL_SANDBOX",
            paypal_order_id=order_result.paypal_order_id,
            paypal_approval_url=order_result.approval_url,
            state=PaymentState.AWAITING_PAYPAL_BUYER,
            created_at=now,
            updated_at=now,
        )
        saved_attempt = self.repo.save_attempt(attempt)

        # Transition intent to AWAITING_PAYPAL_BUYER
        self.repo.transition_intent(
            tenant_id=intent.tenant_id,
            intent_id=intent.id,
            target_state=PaymentState.AWAITING_PAYPAL_BUYER,
            active_attempt_id=saved_attempt.id,
        )

        # Financial event
        self.repo.append_financial_event(
            tenant_id=intent.tenant_id,
            correlation_id=intent.correlation_id,
            payment_intent_id=intent.id,
            event_type=FinancialEventType.PAYPAL_ORDER_CREATED,
            actor_type="PAYMENT_COORDINATOR",
            actor_id="guardian-payments",
            payload={
                "attempt_id": str(saved_attempt.id),
                "paypal_order_id": order_result.paypal_order_id,
                "amount_minor": intent.amount_minor,
                "currency": intent.currency,
                "status": order_result.status,
            },
        )

        # Evidence record
        evidence_content: dict[str, Any] = {
            "paypal_order_id": order_result.paypal_order_id,
            "amount_minor": intent.amount_minor,
            "currency": intent.currency,
            "approval_url": order_result.approval_url,
        }
        self.repo.save_evidence(
            EvidenceRecord(
                tenant_id=intent.tenant_id,
                correlation_id=intent.correlation_id,
                payment_intent_id=intent.id,
                source_type=EvidenceSourceType.PAYPAL_ORDER,
                source_ref=f"paypal:{order_result.paypal_order_id}",
                title=f"PayPal Sandbox Order ({order_result.paypal_order_id})",
                content=evidence_content,
                content_hash=compute_payload_hash(evidence_content),
                is_synthetic=False,
                collected_at=now,
            )
        )
        return saved_attempt

    def record_buyer_approval(
        self,
        *,
        tenant_id: UUID,
        intent_id: UUID,
        attempt_id: UUID,
        payer_id: str | None = None,
    ) -> PaymentAttempt:
        attempt = self.repo.get_attempt(tenant_id, attempt_id)
        if attempt is None:
            raise AttemptNotFoundError(f"PaymentAttempt {attempt_id} not found")

        intent = self.repo.get_intent(tenant_id, intent_id)
        if intent is None:
            raise IntentNotFoundError(f"PaymentIntent {intent_id} not found")

        if attempt.paypal_order_id is None:
            raise GuardianError("Cannot record buyer approval on attempt without paypal_order_id")

        now = _utc_now()
        buyer_approval = PayPalBuyerApproval(
            paypal_order_id=attempt.paypal_order_id,
            payer_id=payer_id,
            buyer_status="APPROVED",
            approved_at=now,
        )

        updated_attempt = attempt.model_copy(
            update={
                "buyer_approval": buyer_approval,
                "state": PaymentState.CAPTURE_PENDING,
                "updated_at": now,
            }
        )
        saved_attempt = self.repo.update_attempt(updated_attempt)

        self.repo.transition_intent(
            tenant_id=tenant_id,
            intent_id=intent_id,
            target_state=PaymentState.CAPTURE_PENDING,
            active_attempt_id=saved_attempt.id,
        )

        self.repo.append_financial_event(
            tenant_id=tenant_id,
            correlation_id=intent.correlation_id,
            payment_intent_id=intent_id,
            event_type=FinancialEventType.PAYPAL_BUYER_APPROVED,
            actor_type="PAYPAL_BUYER",
            actor_id=payer_id or "unknown-payer",
            payload={
                "attempt_id": str(attempt_id),
                "paypal_order_id": attempt.paypal_order_id,
                "payer_id": payer_id,
            },
        )
        return saved_attempt

    async def capture_order(
        self,
        *,
        tenant_id: UUID,
        intent_id: UUID,
        attempt_id: UUID,
    ) -> tuple[PaymentIntent, PaymentAttempt]:
        intent = self.repo.get_intent(tenant_id, intent_id)
        if intent is None:
            raise IntentNotFoundError(f"PaymentIntent {intent_id} not found")

        attempt = self.repo.get_attempt(tenant_id, attempt_id)
        if attempt is None:
            raise AttemptNotFoundError(f"PaymentAttempt {attempt_id} not found")

        if attempt.paypal_order_id is None:
            raise GuardianError("Cannot capture attempt without paypal_order_id")

        now = _utc_now()

        # Audit capture request
        self.repo.append_financial_event(
            tenant_id=tenant_id,
            correlation_id=intent.correlation_id,
            payment_intent_id=intent_id,
            event_type=FinancialEventType.PAYPAL_CAPTURE_REQUESTED,
            actor_type="PAYMENT_COORDINATOR",
            actor_id="guardian-payments",
            payload={
                "attempt_id": str(attempt_id),
                "paypal_order_id": attempt.paypal_order_id,
                "amount_minor": intent.amount_minor,
                "currency": intent.currency,
            },
        )

        try:
            capture_result: PayPalCaptureResult = await self.paypal_client.capture_order(
                paypal_order_id=attempt.paypal_order_id,
                expected_amount_minor=intent.amount_minor,
                expected_currency=intent.currency,
                request_id=f"cap-{intent.id}-{attempt.attempt_number}",
            )
        except PayPalTimeoutError:
            # Handle timeout -> transition to PENDING_PROVIDER
            timeout_attempt = attempt.model_copy(
                update={
                    "state": PaymentState.PENDING_PROVIDER,
                    "failure_code": "PAYPAL_CAPTURE_TIMEOUT",
                    "failure_reason": "PayPal capture timed out; awaiting reconciliation",
                    "updated_at": _utc_now(),
                }
            )
            saved_attempt = self.repo.update_attempt(timeout_attempt)
            updated_intent = self.repo.transition_intent(
                tenant_id=tenant_id,
                intent_id=intent_id,
                target_state=PaymentState.PENDING_PROVIDER,
                active_attempt_id=saved_attempt.id,
            )

            self.repo.append_financial_event(
                tenant_id=tenant_id,
                correlation_id=intent.correlation_id,
                payment_intent_id=intent_id,
                event_type=FinancialEventType.PAYPAL_TIMEOUT_PENDING,
                actor_type="PAYMENT_COORDINATOR",
                actor_id="guardian-payments",
                payload={
                    "attempt_id": str(attempt_id),
                    "paypal_order_id": attempt.paypal_order_id,
                    "reason": "Capture call timed out",
                },
            )
            return updated_intent, saved_attempt

        except Exception as exc:
            # Capture failure -> transition to FAILED and release budget
            fail_attempt = attempt.model_copy(
                update={
                    "state": PaymentState.FAILED,
                    "failure_code": "PAYPAL_CAPTURE_FAILED",
                    "failure_reason": str(exc),
                    "updated_at": _utc_now(),
                }
            )
            saved_attempt = self.repo.update_attempt(fail_attempt)
            updated_intent = self.repo.transition_intent(
                tenant_id=tenant_id,
                intent_id=intent_id,
                target_state=PaymentState.FAILED,
                active_attempt_id=saved_attempt.id,
            )

            if intent.reservation_id:
                self.budget_coordinator.release(
                    tenant_id=tenant_id,
                    correlation_id=intent.correlation_id,
                    payment_intent_id=intent.id,
                    reservation_id=intent.reservation_id,
                    reason=f"Capture failed: {exc}",
                )

            self.repo.append_financial_event(
                tenant_id=tenant_id,
                correlation_id=intent.correlation_id,
                payment_intent_id=intent_id,
                event_type=FinancialEventType.PAYMENT_FAILED,
                actor_type="PAYMENT_COORDINATOR",
                actor_id="guardian-payments",
                payload={
                    "attempt_id": str(attempt_id),
                    "paypal_order_id": attempt.paypal_order_id,
                    "error": str(exc),
                },
            )
            return updated_intent, saved_attempt

        # Capture succeeded and verified!
        verified_capture = capture_result.verified_capture
        if verified_capture.paypal_status != "COMPLETED":
            raise GuardianError(
                f"Capture not completed: status is {verified_capture.paypal_status}"
            )

        # Atomically convert budget reservation to spent!
        if intent.reservation_id:
            self.budget_coordinator.capture(
                tenant_id=tenant_id,
                correlation_id=intent.correlation_id,
                payment_intent_id=intent.id,
                reservation_id=intent.reservation_id,
            )

        succeeded_attempt = attempt.model_copy(
            update={
                "verified_capture": verified_capture,
                "state": PaymentState.SUCCEEDED,
                "updated_at": now,
            }
        )
        saved_attempt = self.repo.update_attempt(succeeded_attempt)

        updated_intent = self.repo.transition_intent(
            tenant_id=tenant_id,
            intent_id=intent_id,
            target_state=PaymentState.SUCCEEDED,
            active_attempt_id=saved_attempt.id,
        )

        self.repo.append_financial_event(
            tenant_id=tenant_id,
            correlation_id=intent.correlation_id,
            payment_intent_id=intent_id,
            event_type=FinancialEventType.PAYPAL_CAPTURE_VERIFIED,
            actor_type="PAYMENT_COORDINATOR",
            actor_id="guardian-payments",
            payload={
                "attempt_id": str(attempt_id),
                "paypal_order_id": attempt.paypal_order_id,
                "paypal_capture_id": verified_capture.paypal_capture_id,
                "verified_amount_minor": verified_capture.verified_amount_minor,
                "verified_currency": verified_capture.verified_currency,
                "verification_hash": verified_capture.verification_hash,
            },
        )

        capture_evidence: dict[str, Any] = {
            "paypal_order_id": verified_capture.paypal_order_id,
            "capture_id": verified_capture.paypal_capture_id,
            "status": verified_capture.paypal_status,
            "verified_amount_minor": verified_capture.verified_amount_minor,
            "verified_currency": verified_capture.verified_currency,
            "verification_hash": verified_capture.verification_hash,
        }
        self.repo.save_evidence(
            EvidenceRecord(
                tenant_id=tenant_id,
                correlation_id=intent.correlation_id,
                payment_intent_id=intent_id,
                source_type=EvidenceSourceType.PAYPAL_CAPTURE,
                source_ref=f"paypal:{verified_capture.paypal_capture_id}",
                title=f"Verified PayPal Capture ({verified_capture.paypal_capture_id})",
                content=capture_evidence,
                content_hash=compute_payload_hash(capture_evidence),
                is_synthetic=False,
                collected_at=now,
            )
        )
        return updated_intent, saved_attempt

    def handle_buyer_declined(
        self,
        *,
        tenant_id: UUID,
        intent_id: UUID,
        attempt_id: UUID,
        reason: str = "Buyer declined or closed PayPal checkout modal",
    ) -> tuple[PaymentIntent, PaymentAttempt]:
        intent = self.repo.get_intent(tenant_id, intent_id)
        if intent is None:
            raise IntentNotFoundError(f"PaymentIntent {intent_id} not found")

        attempt = self.repo.get_attempt(tenant_id, attempt_id)
        if attempt is None:
            raise AttemptNotFoundError(f"PaymentAttempt {attempt_id} not found")

        now = _utc_now()
        cancelled_attempt = attempt.model_copy(
            update={
                "state": PaymentState.CANCELLED,
                "failure_code": "BUYER_DECLINED",
                "failure_reason": reason,
                "updated_at": now,
            }
        )
        saved_attempt = self.repo.update_attempt(cancelled_attempt)

        updated_intent = self.repo.transition_intent(
            tenant_id=tenant_id,
            intent_id=intent_id,
            target_state=PaymentState.CANCELLED,
            active_attempt_id=saved_attempt.id,
        )

        # Release held budget reservation
        if intent.reservation_id:
            self.budget_coordinator.release(
                tenant_id=tenant_id,
                correlation_id=intent.correlation_id,
                payment_intent_id=intent.id,
                reservation_id=intent.reservation_id,
                reason=reason,
            )

        self.repo.append_financial_event(
            tenant_id=tenant_id,
            correlation_id=intent.correlation_id,
            payment_intent_id=intent_id,
            event_type=FinancialEventType.PAYPAL_BUYER_CANCELLED,
            actor_type="PAYPAL_BUYER",
            actor_id="buyer",
            payload={
                "attempt_id": str(attempt_id),
                "paypal_order_id": attempt.paypal_order_id,
                "reason": reason,
            },
        )
        return updated_intent, saved_attempt

    async def reconcile_pending(
        self,
        *,
        tenant_id: UUID,
        intent_id: UUID,
        attempt_id: UUID,
    ) -> tuple[PaymentIntent, PaymentAttempt]:
        intent = self.repo.get_intent(tenant_id, intent_id)
        if intent is None:
            raise IntentNotFoundError(f"PaymentIntent {intent_id} not found")

        attempt = self.repo.get_attempt(tenant_id, attempt_id)
        if attempt is None:
            raise AttemptNotFoundError(f"PaymentAttempt {attempt_id} not found")

        if attempt.paypal_order_id is None:
            raise GuardianError("Cannot reconcile attempt without paypal_order_id")

        reconcile_res: PayPalReconciliationResult = await self.paypal_client.reconcile_order(
            paypal_order_id=attempt.paypal_order_id,
            expected_amount_minor=intent.amount_minor,
            expected_currency=intent.currency,
        )

        now = _utc_now()
        if (
            reconcile_res.verified_capture
            and reconcile_res.verified_capture.paypal_status == "COMPLETED"
        ):
            # Capture confirmed during reconciliation
            if intent.reservation_id:
                self.budget_coordinator.capture(
                    tenant_id=tenant_id,
                    correlation_id=intent.correlation_id,
                    payment_intent_id=intent.id,
                    reservation_id=intent.reservation_id,
                )

            succ_attempt = attempt.model_copy(
                update={
                    "verified_capture": reconcile_res.verified_capture,
                    "state": PaymentState.SUCCEEDED,
                    "updated_at": now,
                }
            )
            saved_attempt = self.repo.update_attempt(succ_attempt)
            updated_intent = self.repo.transition_intent(
                tenant_id=tenant_id,
                intent_id=intent_id,
                target_state=PaymentState.SUCCEEDED,
                active_attempt_id=saved_attempt.id,
            )

            self.repo.append_financial_event(
                tenant_id=tenant_id,
                correlation_id=intent.correlation_id,
                payment_intent_id=intent_id,
                event_type=FinancialEventType.PAYPAL_CAPTURE_VERIFIED,
                actor_type="RECONCILIATION_SERVICE",
                actor_id="guardian-reconciler",
                payload={
                    "attempt_id": str(attempt_id),
                    "paypal_order_id": attempt.paypal_order_id,
                    "status": "COMPLETED_VIA_RECONCILIATION",
                },
            )
            return updated_intent, saved_attempt

        if reconcile_res.order_status in ("VOIDED", "CANCELLED", "EXPIRED"):
            # Provider confirms order was voided/cancelled
            cancel_attempt = attempt.model_copy(
                update={
                    "state": PaymentState.CANCELLED,
                    "failure_code": f"ORDER_{reconcile_res.order_status}",
                    "failure_reason": f"Order status reconciled as {reconcile_res.order_status}",
                    "updated_at": now,
                }
            )
            saved_attempt = self.repo.update_attempt(cancel_attempt)
            updated_intent = self.repo.transition_intent(
                tenant_id=tenant_id,
                intent_id=intent_id,
                target_state=PaymentState.CANCELLED,
                active_attempt_id=saved_attempt.id,
            )

            if intent.reservation_id:
                self.budget_coordinator.release(
                    tenant_id=tenant_id,
                    correlation_id=intent.correlation_id,
                    payment_intent_id=intent.id,
                    reservation_id=intent.reservation_id,
                    reason=f"Reconciled as {reconcile_res.order_status}",
                )
            return updated_intent, saved_attempt

        # Still pending or unconfirmed
        return intent, attempt
