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
    compute_payload_hash,
)
from paypal import (
    PayPalAPIError,
    PayPalCaptureResult,
    PayPalOrderCreationResult,
    PayPalReconciliationResult,
    PayPalSandboxClient,
    PayPalTimeoutError,
)

from guardian.budgets.coordinator import BudgetCoordinator
from guardian.domain.exceptions import (
    AttemptNotFoundError,
    DuplicateIntentError,
    GuardianError,
    IntentNotFoundError,
    InvalidStateTransitionError,
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

    def prepare_checkout(
        self,
        *,
        intent: PaymentIntent,
        attempt_number: int = 1,
        idempotency_key: str,
    ) -> tuple[PaymentIntent, PaymentAttempt | None]:
        """Validate checkout state and check idempotent attempt reuse before PayPal I/O."""
        list_attempts = getattr(self.repo, "list_attempts_for_intent", None)
        attempts: list[PaymentAttempt] = []
        if callable(list_attempts):
            attempts = list_attempts(intent.tenant_id, intent.id)
        elif intent.active_attempt_id is not None:
            active_attempt = self.repo.get_attempt(intent.tenant_id, intent.active_attempt_id)
            if active_attempt is not None:
                attempts = [active_attempt]

        for existing in attempts:
            if existing.idempotency_key == idempotency_key:
                if existing.attempt_number != attempt_number:
                    raise DuplicateIntentError(
                        f"Attempt idempotency key '{idempotency_key}' already bound to attempt {existing.attempt_number}"
                    )
                return intent, existing

        if intent.state != PaymentState.CHECKOUT_READY:
            raise InvalidStateTransitionError(
                f"Cannot create checkout for intent in state {intent.state.value} "
                f"(must be CHECKOUT_READY)"
            )
        return intent, None

    def finalize_checkout(
        self,
        *,
        intent: PaymentIntent,
        attempt_number: int,
        idempotency_key: str,
        order_result: PayPalOrderCreationResult,
    ) -> PaymentAttempt:
        """Persist created PayPal order attempt, intent transition, audit event, and evidence."""
        now = _utc_now()
        attempt = PaymentAttempt(
            id=uuid4(),
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

        self.repo.transition_intent(
            tenant_id=intent.tenant_id,
            intent_id=intent.id,
            target_state=PaymentState.AWAITING_PAYPAL_BUYER,
            active_attempt_id=saved_attempt.id,
        )

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

    def record_checkout_failure(
        self,
        *,
        intent: PaymentIntent,
        reason: str,
    ) -> PaymentIntent:
        """Release held budget reservation and mark intent FAILED when order creation fails."""
        if intent.reservation_id:
            self.budget_coordinator.release(
                tenant_id=intent.tenant_id,
                correlation_id=intent.correlation_id,
                payment_intent_id=intent.id,
                reservation_id=intent.reservation_id,
                actor_type="PAYMENT_COORDINATOR",
                actor_id="guardian-payments",
                reason=f"Checkout order creation failed: {reason}",
            )

        current_intent = self.repo.get_intent(intent.tenant_id, intent.id) or intent
        if current_intent.state == PaymentState.CHECKOUT_READY:
            current_intent = self.repo.transition_intent(
                tenant_id=intent.tenant_id,
                intent_id=intent.id,
                target_state=PaymentState.FAILED,
            )

        self.repo.append_financial_event(
            tenant_id=intent.tenant_id,
            correlation_id=intent.correlation_id,
            payment_intent_id=intent.id,
            event_type=FinancialEventType.PAYMENT_FAILED,
            actor_type="PAYMENT_COORDINATOR",
            actor_id="guardian-payments",
            payload={
                "stage": "create_checkout",
                "error": reason,
            },
        )
        return current_intent

    async def create_checkout(
        self,
        *,
        intent: PaymentIntent,
        attempt_number: int = 1,
        idempotency_key: str,
        return_url: str | None = None,
        cancel_url: str | None = None,
    ) -> PaymentAttempt:
        _, existing = self.prepare_checkout(
            intent=intent,
            attempt_number=attempt_number,
            idempotency_key=idempotency_key,
        )
        if existing is not None:
            return existing

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
        except (PayPalTimeoutError, PayPalAPIError) as exc:
            self.record_checkout_failure(intent=intent, reason=str(exc))
            raise
        except (ValueError, RuntimeError) as exc:
            self.record_checkout_failure(intent=intent, reason=str(exc))
            raise GuardianError(f"Failed to create PayPal sandbox order: {exc}") from exc

        return self.finalize_checkout(
            intent=intent,
            attempt_number=attempt_number,
            idempotency_key=idempotency_key,
            order_result=order_result,
        )

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

        if attempt.payment_intent_id != intent.id:
            raise InvalidStateTransitionError(
                f"PaymentAttempt {attempt_id} does not belong to PaymentIntent {intent_id}"
            )
        if intent.state != PaymentState.AWAITING_PAYPAL_BUYER:
            raise InvalidStateTransitionError(
                f"Cannot record buyer approval for intent in state {intent.state.value} "
                f"(must be AWAITING_PAYPAL_BUYER)"
            )
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

    def prepare_capture(
        self,
        *,
        tenant_id: UUID,
        intent_id: UUID,
        attempt_id: UUID,
    ) -> tuple[PaymentIntent, PaymentAttempt]:
        """Validate CAPTURE_PENDING state and log capture request prior to PayPal HTTP I/O."""
        intent = self.repo.get_intent(tenant_id, intent_id)
        if intent is None:
            raise IntentNotFoundError(f"PaymentIntent {intent_id} not found")

        if intent.state != PaymentState.CAPTURE_PENDING:
            raise InvalidStateTransitionError(
                f"Cannot capture PaymentIntent {intent_id} in state {intent.state.value} "
                f"(must be CAPTURE_PENDING)"
            )

        attempt = self.repo.get_attempt(tenant_id, attempt_id)
        if attempt is None:
            raise AttemptNotFoundError(f"PaymentAttempt {attempt_id} not found")

        if attempt.payment_intent_id != intent.id:
            raise InvalidStateTransitionError(
                f"PaymentAttempt {attempt_id} does not belong to PaymentIntent {intent_id}"
            )
        if attempt.state != PaymentState.CAPTURE_PENDING:
            raise InvalidStateTransitionError(
                f"Cannot capture PaymentAttempt {attempt_id} in state {attempt.state.value} "
                f"(must be CAPTURE_PENDING)"
            )
        if attempt.paypal_order_id is None:
            raise GuardianError("Cannot capture attempt without paypal_order_id")

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
        return intent, attempt

    def record_capture_timeout(
        self,
        *,
        tenant_id: UUID,
        intent: PaymentIntent,
        attempt: PaymentAttempt,
    ) -> tuple[PaymentIntent, PaymentAttempt]:
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
            intent_id=intent.id,
            target_state=PaymentState.PENDING_PROVIDER,
            active_attempt_id=saved_attempt.id,
        )

        self.repo.append_financial_event(
            tenant_id=tenant_id,
            correlation_id=intent.correlation_id,
            payment_intent_id=intent.id,
            event_type=FinancialEventType.PAYPAL_TIMEOUT_PENDING,
            actor_type="PAYMENT_COORDINATOR",
            actor_id="guardian-payments",
            payload={
                "attempt_id": str(attempt.id),
                "paypal_order_id": attempt.paypal_order_id,
                "reason": "Capture call timed out",
            },
        )
        return updated_intent, saved_attempt

    def record_capture_failure(
        self,
        *,
        tenant_id: UUID,
        intent: PaymentIntent,
        attempt: PaymentAttempt,
        error_message: str,
    ) -> tuple[PaymentIntent, PaymentAttempt]:
        fail_attempt = attempt.model_copy(
            update={
                "state": PaymentState.FAILED,
                "failure_code": "PAYPAL_CAPTURE_FAILED",
                "failure_reason": error_message[:500],
                "updated_at": _utc_now(),
            }
        )
        saved_attempt = self.repo.update_attempt(fail_attempt)
        updated_intent = self.repo.transition_intent(
            tenant_id=tenant_id,
            intent_id=intent.id,
            target_state=PaymentState.FAILED,
            active_attempt_id=saved_attempt.id,
        )

        if intent.reservation_id:
            self.budget_coordinator.release(
                tenant_id=tenant_id,
                correlation_id=intent.correlation_id,
                payment_intent_id=intent.id,
                reservation_id=intent.reservation_id,
                reason=f"Capture failed: {error_message}",
            )

        self.repo.append_financial_event(
            tenant_id=tenant_id,
            correlation_id=intent.correlation_id,
            payment_intent_id=intent.id,
            event_type=FinancialEventType.PAYMENT_FAILED,
            actor_type="PAYMENT_COORDINATOR",
            actor_id="guardian-payments",
            payload={
                "attempt_id": str(attempt.id),
                "paypal_order_id": attempt.paypal_order_id,
                "error": error_message,
            },
        )
        return updated_intent, saved_attempt

    def finalize_capture(
        self,
        *,
        tenant_id: UUID,
        intent: PaymentIntent,
        attempt: PaymentAttempt,
        capture_result: PayPalCaptureResult,
    ) -> tuple[PaymentIntent, PaymentAttempt]:
        now = _utc_now()
        verified_capture = capture_result.verified_capture
        if verified_capture.paypal_status != "COMPLETED":
            raise GuardianError(
                f"Capture not completed: status is {verified_capture.paypal_status}"
            )

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
            intent_id=intent.id,
            target_state=PaymentState.SUCCEEDED,
            active_attempt_id=saved_attempt.id,
        )

        self.repo.append_financial_event(
            tenant_id=tenant_id,
            correlation_id=intent.correlation_id,
            payment_intent_id=intent.id,
            event_type=FinancialEventType.PAYPAL_CAPTURE_VERIFIED,
            actor_type="PAYMENT_COORDINATOR",
            actor_id="guardian-payments",
            payload={
                "attempt_id": str(attempt.id),
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
                payment_intent_id=intent.id,
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

    async def capture_order(
        self,
        *,
        tenant_id: UUID,
        intent_id: UUID,
        attempt_id: UUID,
    ) -> tuple[PaymentIntent, PaymentAttempt]:
        intent, attempt = self.prepare_capture(
            tenant_id=tenant_id,
            intent_id=intent_id,
            attempt_id=attempt_id,
        )
        assert attempt.paypal_order_id is not None

        try:
            capture_result: PayPalCaptureResult = await self.paypal_client.capture_order(
                paypal_order_id=attempt.paypal_order_id,
                expected_amount_minor=intent.amount_minor,
                expected_currency=intent.currency,
                request_id=f"cap-{intent.id}-{attempt.attempt_number}",
            )
        except PayPalTimeoutError:
            return self.record_capture_timeout(
                tenant_id=tenant_id,
                intent=intent,
                attempt=attempt,
            )
        except (PayPalAPIError, ValueError, RuntimeError) as exc:
            return self.record_capture_failure(
                tenant_id=tenant_id,
                intent=intent,
                attempt=attempt,
                error_message=str(exc),
            )

        return self.finalize_capture(
            tenant_id=tenant_id,
            intent=intent,
            attempt=attempt,
            capture_result=capture_result,
        )

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

        if attempt.payment_intent_id != intent.id:
            raise InvalidStateTransitionError(
                f"PaymentAttempt {attempt_id} does not belong to PaymentIntent {intent_id}"
            )
        if intent.state not in (
            PaymentState.CHECKOUT_READY,
            PaymentState.AWAITING_PAYPAL_BUYER,
            PaymentState.PENDING_PROVIDER,
        ):
            raise InvalidStateTransitionError(
                f"Cannot mark buyer declined for intent in state {intent.state.value}"
            )

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

    def prepare_reconcile(
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

        if attempt.payment_intent_id != intent.id:
            raise InvalidStateTransitionError(
                f"PaymentAttempt {attempt_id} does not belong to PaymentIntent {intent_id}"
            )
        if intent.state not in (
            PaymentState.PENDING_PROVIDER,
            PaymentState.CAPTURE_PENDING,
            PaymentState.AWAITING_PAYPAL_BUYER,
        ):
            raise InvalidStateTransitionError(
                f"Cannot reconcile PaymentIntent {intent_id} in state {intent.state.value}"
            )
        if attempt.paypal_order_id is None:
            raise GuardianError("Cannot reconcile attempt without paypal_order_id")
        return intent, attempt

    def finalize_reconcile(
        self,
        *,
        tenant_id: UUID,
        intent: PaymentIntent,
        attempt: PaymentAttempt,
        reconcile_res: PayPalReconciliationResult,
    ) -> tuple[PaymentIntent, PaymentAttempt]:
        now = _utc_now()
        if (
            reconcile_res.verified_capture
            and reconcile_res.verified_capture.paypal_status == "COMPLETED"
        ):
            verified_capture = reconcile_res.verified_capture
            if intent.reservation_id:
                self.budget_coordinator.capture(
                    tenant_id=tenant_id,
                    correlation_id=intent.correlation_id,
                    payment_intent_id=intent.id,
                    reservation_id=intent.reservation_id,
                )

            succ_attempt = attempt.model_copy(
                update={
                    "verified_capture": verified_capture,
                    "state": PaymentState.SUCCEEDED,
                    "updated_at": now,
                }
            )
            saved_attempt = self.repo.update_attempt(succ_attempt)
            updated_intent = self.repo.transition_intent(
                tenant_id=tenant_id,
                intent_id=intent.id,
                target_state=PaymentState.SUCCEEDED,
                active_attempt_id=saved_attempt.id,
            )

            self.repo.append_financial_event(
                tenant_id=tenant_id,
                correlation_id=intent.correlation_id,
                payment_intent_id=intent.id,
                event_type=FinancialEventType.PAYPAL_CAPTURE_VERIFIED,
                actor_type="RECONCILIATION_SERVICE",
                actor_id="guardian-reconciler",
                payload={
                    "attempt_id": str(attempt.id),
                    "paypal_order_id": attempt.paypal_order_id,
                    "paypal_capture_id": verified_capture.paypal_capture_id,
                    "verified_amount_minor": verified_capture.verified_amount_minor,
                    "verified_currency": verified_capture.verified_currency,
                    "verification_hash": verified_capture.verification_hash,
                    "status": "COMPLETED_VIA_RECONCILIATION",
                },
            )

            capture_evidence: dict[str, Any] = {
                "paypal_order_id": verified_capture.paypal_order_id,
                "capture_id": verified_capture.paypal_capture_id,
                "status": verified_capture.paypal_status,
                "verified_amount_minor": verified_capture.verified_amount_minor,
                "verified_currency": verified_capture.verified_currency,
                "verification_hash": verified_capture.verification_hash,
                "reconciled": True,
            }
            self.repo.save_evidence(
                EvidenceRecord(
                    tenant_id=tenant_id,
                    correlation_id=intent.correlation_id,
                    payment_intent_id=intent.id,
                    source_type=EvidenceSourceType.PAYPAL_CAPTURE,
                    source_ref=f"paypal:{verified_capture.paypal_capture_id}",
                    title=f"Reconciled PayPal Capture ({verified_capture.paypal_capture_id})",
                    content=capture_evidence,
                    content_hash=compute_payload_hash(capture_evidence),
                    is_synthetic=False,
                    collected_at=now,
                )
            )
            return updated_intent, saved_attempt

        if reconcile_res.order_status in ("VOIDED", "CANCELLED", "EXPIRED"):
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
                intent_id=intent.id,
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

        return intent, attempt

    async def reconcile_pending(
        self,
        *,
        tenant_id: UUID,
        intent_id: UUID,
        attempt_id: UUID,
    ) -> tuple[PaymentIntent, PaymentAttempt]:
        intent, attempt = self.prepare_reconcile(
            tenant_id=tenant_id,
            intent_id=intent_id,
            attempt_id=attempt_id,
        )
        assert attempt.paypal_order_id is not None

        reconcile_res: PayPalReconciliationResult = await self.paypal_client.reconcile_order(
            paypal_order_id=attempt.paypal_order_id,
            expected_amount_minor=intent.amount_minor,
            expected_currency=intent.currency,
        )
        return self.finalize_reconcile(
            tenant_id=tenant_id,
            intent=intent,
            attempt=attempt,
            reconcile_res=reconcile_res,
        )

    def prepare_refund(
        self,
        *,
        tenant_id: UUID,
        intent_id: UUID,
        attempt_id: UUID | None = None,
        amount_minor: int | None = None,
    ) -> tuple[PaymentIntent, PaymentAttempt, int]:
        intent = self.repo.get_intent(tenant_id, intent_id)
        if intent is None:
            raise IntentNotFoundError(f"PaymentIntent {intent_id} not found")

        resolved_attempt_id = attempt_id or intent.active_attempt_id
        if resolved_attempt_id is None:
            raise AttemptNotFoundError(f"No payment attempt bound to PaymentIntent {intent_id}")

        attempt = self.repo.get_attempt(tenant_id, resolved_attempt_id)
        if attempt is None:
            raise AttemptNotFoundError(f"PaymentAttempt {resolved_attempt_id} not found")

        if attempt.payment_intent_id != intent.id:
            raise InvalidStateTransitionError(
                f"PaymentAttempt {resolved_attempt_id} does not belong to PaymentIntent {intent_id}"
            )
        if intent.state not in (PaymentState.SUCCEEDED, PaymentState.PARTIALLY_REFUNDED):
            raise InvalidStateTransitionError(
                f"Cannot refund PaymentIntent {intent_id} in state {intent.state.value} "
                f"(must be SUCCEEDED or PARTIALLY_REFUNDED)"
            )
        if attempt.verified_capture is None or not attempt.verified_capture.paypal_capture_id:
            raise GuardianError("Cannot refund payment without a verified PayPal capture")

        refund_amount = amount_minor if amount_minor is not None else intent.amount_minor
        if refund_amount <= 0 or refund_amount > intent.amount_minor:
            raise GuardianError(
                f"Refund amount {refund_amount} must be between 1 and {intent.amount_minor}"
            )
        return intent, attempt, refund_amount

    def finalize_refund(
        self,
        *,
        tenant_id: UUID,
        intent: PaymentIntent,
        attempt: PaymentAttempt,
        refund_amount: int,
        reason: str,
        refund_res: dict[str, Any],
    ) -> tuple[PaymentIntent, PaymentAttempt, dict[str, Any]]:
        now = _utc_now()
        is_partial = (refund_amount < intent.amount_minor) and (intent.state != PaymentState.PARTIALLY_REFUNDED)
        target_state = (
            PaymentState.PARTIALLY_REFUNDED
            if is_partial
            else PaymentState.REFUNDED
        )
        event_type = (
            FinancialEventType.PAYMENT_PARTIALLY_REFUNDED
            if target_state == PaymentState.PARTIALLY_REFUNDED
            else FinancialEventType.PAYMENT_REFUNDED
        )

        refunded_attempt = attempt.model_copy(
            update={
                "state": target_state,
                "updated_at": now,
            }
        )
        saved_attempt = self.repo.update_attempt(refunded_attempt)
        updated_intent = self.repo.transition_intent(
            tenant_id=tenant_id,
            intent_id=intent.id,
            target_state=target_state,
            active_attempt_id=saved_attempt.id,
        )

        capture_id = attempt.verified_capture.paypal_capture_id if attempt.verified_capture else ""
        refund_id = str(refund_res.get("id") or refund_res.get("refund_id") or capture_id)
        self.repo.append_financial_event(
            tenant_id=tenant_id,
            correlation_id=intent.correlation_id,
            payment_intent_id=intent.id,
            event_type=event_type,
            actor_type="PAYMENT_COORDINATOR",
            actor_id="guardian-payments",
            payload={
                "attempt_id": str(attempt.id),
                "paypal_capture_id": capture_id,
                "paypal_refund_id": refund_id,
                "refund_amount_minor": refund_amount,
                "currency": intent.currency,
                "status": str(refund_res.get("status", "COMPLETED")),
                "reason": reason,
            },
        )

        refund_evidence: dict[str, Any] = {
            "paypal_capture_id": capture_id,
            "paypal_refund_id": refund_id,
            "refund_amount_minor": refund_amount,
            "currency": intent.currency,
            "reason": reason,
            "provider_response": refund_res,
        }
        self.repo.save_evidence(
            EvidenceRecord(
                tenant_id=tenant_id,
                correlation_id=intent.correlation_id,
                payment_intent_id=intent.id,
                source_type=EvidenceSourceType.PAYPAL_CAPTURE,
                source_ref=f"paypal:refund:{refund_id}",
                title=f"PayPal Refund ({refund_id})",
                content=refund_evidence,
                content_hash=compute_payload_hash(refund_evidence),
                is_synthetic=False,
                collected_at=now,
            )
        )
        return updated_intent, saved_attempt, refund_res

    async def refund_payment(
        self,
        *,
        tenant_id: UUID,
        intent_id: UUID,
        attempt_id: UUID | None = None,
        amount_minor: int | None = None,
        reason: str = "Operator requested refund",
    ) -> tuple[PaymentIntent, PaymentAttempt, dict[str, Any]]:
        intent, attempt, refund_amount = self.prepare_refund(
            tenant_id=tenant_id,
            intent_id=intent_id,
            attempt_id=attempt_id,
            amount_minor=amount_minor,
        )
        assert attempt.verified_capture is not None
        refund_res = await self.paypal_client.refund_capture(
            capture_id=attempt.verified_capture.paypal_capture_id,
            amount_minor=refund_amount,
            currency=intent.currency,
            idempotency_key=f"ref-{intent.id}-{attempt.id}-{refund_amount}",
            note=reason,
        )
        return self.finalize_refund(
            tenant_id=tenant_id,
            intent=intent,
            attempt=attempt,
            refund_amount=refund_amount,
            reason=reason,
            refund_res=refund_res,
        )

    async def refund_order(
        self,
        *,
        tenant_id: UUID,
        intent_id: UUID,
        amount_minor: int | None = None,
        note: str | None = None,
    ) -> tuple[PaymentIntent, Any]:
        intent, attempt, res = await self.refund_payment(
            tenant_id=tenant_id,
            intent_id=intent_id,
            amount_minor=amount_minor,
            reason=note or "Operator requested refund",
        )
        return intent, res

    async def void_authorization(
        self,
        *,
        tenant_id: UUID,
        intent_id: UUID,
        note: str | None = None,
    ) -> PaymentIntent:
        intent = self.repo.get_intent(tenant_id, intent_id)
        if intent is None:
            raise IntentNotFoundError(f"PaymentIntent {intent_id} not found")

        if intent.state in (PaymentState.SUCCEEDED, PaymentState.REFUNDED, PaymentState.PARTIALLY_REFUNDED, PaymentState.CANCELLED, PaymentState.FAILED):
            raise InvalidStateTransitionError(
                f"Cannot void authorization for intent in terminal or captured state: {intent.state.value}"
            )

        if intent.reservation_id:
            self.budget_coordinator.release(
                tenant_id=tenant_id,
                correlation_id=intent.correlation_id,
                payment_intent_id=intent.id,
                reservation_id=intent.reservation_id,
                reason=note or "Authorization voided",
            )

        updated_intent = self.repo.transition_intent(
            tenant_id=tenant_id,
            intent_id=intent_id,
            target_state=PaymentState.CANCELLED,
        )

        self.repo.append_financial_event(
            tenant_id=tenant_id,
            correlation_id=intent.correlation_id,
            payment_intent_id=intent.id,
            event_type=FinancialEventType.AUTHORIZATION_VOIDED,
            actor_type="PAYMENT_COORDINATOR",
            actor_id="guardian-payments",
            payload={
                "intent_id": str(intent_id),
                "note": note,
            },
        )
        return updated_intent
