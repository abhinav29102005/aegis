"""Human approval service for AgentPay Guardian.

Enforces cryptographic quote binding and strict expiration verification.
Any post-approval alteration to merchant, amount, currency, or line-items
triggers immediate revocation and rejection.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

from contracts import (
    ApprovalRecord,
    ApprovalStatus,
    DecisionReasonCode,
    FinancialEventType,
    PassportStatus,
    QuoteSnapshot,
    SpendingPassport,
    compute_quote_hash,
)

from guardian.domain.exceptions import (
    ApprovalExpiredError,
    ApprovalMismatchError,
    ApprovalNotFoundError,
    GuardianError,
    InvalidStateTransitionError,
    PolicyDeniedError,
)

try:
    from database import LedgerRepository
except (ImportError, ModuleNotFoundError):
    LedgerRepository = Any  # type: ignore[misc, assignment]


def _utc_now() -> datetime:
    return datetime.now(UTC)


class ApprovalService:
    """Manages human approval lifecycle with deterministic cryptographic bindings."""

    def __init__(self, repo: LedgerRepository) -> None:
        self.repo = repo

    def create_approval_request(
        self,
        *,
        tenant_id: UUID,
        correlation_id: UUID,
        payment_intent_id: UUID,
        decision_id: UUID,
        approver_id: str,
        bound_merchant_id: UUID,
        bound_amount_minor: int,
        bound_currency: str,
        bound_quote_hash: str,
        expires_at: datetime | None = None,
        comment: str | None = None,
        auto_approve: bool = False,
    ) -> ApprovalRecord:
        now = _utc_now()
        exp = expires_at or (now + timedelta(hours=1))
        initial_status = ApprovalStatus.APPROVED if auto_approve else ApprovalStatus.PENDING

        record = ApprovalRecord(
            id=uuid4(),
            tenant_id=tenant_id,
            correlation_id=correlation_id,
            payment_intent_id=payment_intent_id,
            decision_id=decision_id,
            approver_id=approver_id,
            status=initial_status,
            bound_merchant_id=bound_merchant_id,
            bound_amount_minor=bound_amount_minor,
            bound_currency=bound_currency.upper(),
            bound_quote_hash=bound_quote_hash,
            comment=comment,
            expires_at=exp,
            decided_at=now if auto_approve else None,
            created_at=now,
        )
        saved = self.repo.save_approval(record)

        # Audit event
        event_type = (
            FinancialEventType.HUMAN_APPROVED
            if auto_approve
            else FinancialEventType.APPROVAL_REQUESTED
        )
        self.repo.append_financial_event(
            tenant_id=tenant_id,
            correlation_id=correlation_id,
            payment_intent_id=payment_intent_id,
            event_type=event_type,
            actor_type="HUMAN_APPROVER",
            actor_id=approver_id,
            payload={
                "approval_id": str(saved.id),
                "decision_id": str(decision_id),
                "status": saved.status.value,
                "bound_amount_minor": bound_amount_minor,
                "bound_quote_hash": bound_quote_hash,
                "expires_at": exp.isoformat(),
            },
        )
        return saved

    def decide_approval(
        self,
        *,
        tenant_id: UUID,
        approval_id: UUID,
        approver_id: str,
        approved: bool,
        comment: str | None = None,
        now: datetime | None = None,
    ) -> ApprovalRecord:
        current_time = now or _utc_now()
        record = self.repo.get_approval(tenant_id, approval_id)
        if record is None:
            raise ApprovalNotFoundError(f"ApprovalRecord {approval_id} not found")

        if record.status != ApprovalStatus.PENDING:
            raise GuardianError(f"Cannot decide approval in {record.status.value} status")

        if record.expires_at < current_time:
            record = record.model_copy(
                update={"status": ApprovalStatus.EXPIRED, "decided_at": current_time}
            )
            self.repo.update_approval(record)
            raise ApprovalExpiredError(f"ApprovalRecord {approval_id} has expired")

        new_status = ApprovalStatus.APPROVED if approved else ApprovalStatus.REJECTED
        event_type = (
            FinancialEventType.HUMAN_APPROVED if approved else FinancialEventType.HUMAN_REJECTED
        )

        record = record.model_copy(
            update={
                "status": new_status,
                "approver_id": approver_id,
                "comment": comment,
                "decided_at": current_time,
            }
        )
        updated = self.repo.update_approval(record)

        self.repo.append_financial_event(
            tenant_id=tenant_id,
            correlation_id=record.correlation_id,
            payment_intent_id=record.payment_intent_id,
            event_type=event_type,
            actor_type="HUMAN_APPROVER",
            actor_id=approver_id,
            payload={
                "approval_id": str(approval_id),
                "status": new_status.value,
                "comment": comment,
            },
        )
        return updated

    def consume_approval(
        self,
        *,
        tenant_id: UUID,
        approval_id: UUID,
        current_merchant_id: UUID,
        current_amount_minor: int,
        current_currency: str,
        current_quote_hash: str,
        payment_intent_id: UUID | None = None,
        quote: QuoteSnapshot | None = None,
        passport: SpendingPassport | None = None,
        now: datetime | None = None,
    ) -> ApprovalRecord:
        current_time = now or _utc_now()
        record = self.repo.get_approval(tenant_id, approval_id)
        if record is None:
            raise ApprovalNotFoundError(f"ApprovalRecord {approval_id} not found")

        if payment_intent_id is not None and record.payment_intent_id != payment_intent_id:
            raise ApprovalMismatchError(
                f"Approval {approval_id} is bound to intent {record.payment_intent_id}, "
                f"attempted for {payment_intent_id}"
            )

        if record.status == ApprovalStatus.EXPIRED or record.expires_at <= current_time:
            if record.status != ApprovalStatus.EXPIRED:
                record = record.model_copy(update={"status": ApprovalStatus.EXPIRED})
                self.repo.update_approval(record)
            raise ApprovalExpiredError(
                f"Approval {approval_id} expired at {record.expires_at.isoformat()}"
            )

        if record.status == ApprovalStatus.CONSUMED:
            raise InvalidStateTransitionError(
                f"Approval {approval_id} has already been consumed"
            )

        if record.status != ApprovalStatus.APPROVED:
            raise InvalidStateTransitionError(
                f"Approval {approval_id} cannot be consumed in status {record.status.value}"
            )

        # Cryptographic quote and scope binding validation
        if record.bound_merchant_id != current_merchant_id:
            raise ApprovalMismatchError(
                f"Merchant mismatch: approved for {record.bound_merchant_id}, "
                f"attempted for {current_merchant_id}"
            )

        if record.bound_amount_minor != current_amount_minor:
            raise ApprovalMismatchError(
                f"Amount mismatch: approved for {record.bound_amount_minor}, "
                f"attempted for {current_amount_minor}"
            )

        if record.bound_currency != current_currency.upper():
            raise ApprovalMismatchError(
                f"Currency mismatch: approved for {record.bound_currency}, "
                f"attempted for {current_currency}"
            )

        if record.bound_quote_hash != current_quote_hash:
            raise ApprovalMismatchError(
                f"Quote hash mismatch: approved for {record.bound_quote_hash}, "
                f"attempted for {current_quote_hash}"
            )

        target_intent_id = payment_intent_id or record.payment_intent_id
        intent = None
        if quote is None or passport is None:
            get_intent_fn = getattr(self.repo, "get_intent", None)
            if callable(get_intent_fn):
                intent = get_intent_fn(tenant_id, target_intent_id)

        quote_obj = quote
        if quote_obj is None and intent is not None:
            get_quote_fn = getattr(self.repo, "get_quote", None)
            if callable(get_quote_fn):
                quote_obj = get_quote_fn(tenant_id, intent.quote_snapshot_id)

        if quote_obj is not None:
            if quote_obj.expires_at <= current_time:
                raise ApprovalExpiredError(
                    f"Quote {quote_obj.id} expired at {quote_obj.expires_at.isoformat()}"
                )
            recomputed_hash = compute_quote_hash(
                merchant_id=quote_obj.merchant_id,
                amount_minor=quote_obj.amount_minor,
                currency=quote_obj.currency,
                line_items=quote_obj.line_items,
            )
            if (
                recomputed_hash != current_quote_hash
                or quote_obj.quote_hash != current_quote_hash
                or recomputed_hash != record.bound_quote_hash
            ):
                raise ApprovalMismatchError(
                    "Quote hash re-verification failed at approval consumption time"
                )
            if (
                quote_obj.merchant_id != current_merchant_id
                or quote_obj.amount_minor != current_amount_minor
                or quote_obj.currency.upper() != current_currency.upper()
            ):
                raise ApprovalMismatchError(
                    "Quote snapshot parameters no longer match bound approval"
                )

        passport_obj = passport
        if passport_obj is None and intent is not None:
            get_passport_fn = getattr(self.repo, "get_passport", None)
            if callable(get_passport_fn):
                passport_obj = get_passport_fn(tenant_id, intent.passport_id)

        if passport_obj is not None:
            if passport_obj.status == PassportStatus.REVOKED:
                raise PolicyDeniedError(
                    f"SpendingPassport {passport_obj.id} is REVOKED",
                    reason_codes=[DecisionReasonCode.DENIED_PASSPORT_REVOKED.value],
                )
            if passport_obj.status == PassportStatus.PAUSED:
                raise PolicyDeniedError(
                    f"SpendingPassport {passport_obj.id} is PAUSED",
                    reason_codes=[DecisionReasonCode.DENIED_PASSPORT_PAUSED.value],
                )
            if (
                passport_obj.status == PassportStatus.EXPIRED
                or passport_obj.expires_at <= current_time
            ):
                raise PolicyDeniedError(
                    f"SpendingPassport {passport_obj.id} has expired",
                    reason_codes=[DecisionReasonCode.DENIED_PASSPORT_EXPIRED.value],
                )

        # Mark as consumed
        consumed_record = record.model_copy(
            update={
                "status": ApprovalStatus.CONSUMED,
                "consumed_at": current_time,
            }
        )
        return self.repo.update_approval(consumed_record)

    def get_approval(self, tenant_id: UUID, approval_id: UUID) -> ApprovalRecord | None:
        return self.repo.get_approval(tenant_id, approval_id)
