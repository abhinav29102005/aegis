"""Budget coordinator for AgentPay Guardian.

Enforces atomic budget reservation, capture, and release via LedgerRepository.
Appends hash-chained FinancialEvents for all budget lifecycle transitions.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

from contracts import BudgetReservation, FinancialEventType

from guardian.domain.exceptions import GuardianError, InsufficientBudgetError

try:
    from database import InsufficientBudgetError as RepoInsufficientBudgetError
    from database import LedgerRepository
except (ImportError, ModuleNotFoundError):
    LedgerRepository = Any  # type: ignore[misc, assignment]

    class RepoInsufficientBudgetError(Exception):  # type: ignore[no-redef]
        pass


class BudgetCoordinator:
    """Coordinates atomic budget holds, captures, and releases with full audit trail."""

    def __init__(self, repo: LedgerRepository) -> None:
        self.repo = repo

    def reserve(
        self,
        *,
        tenant_id: UUID,
        correlation_id: UUID,
        passport_id: UUID,
        payment_intent_id: UUID,
        amount_minor: int,
        currency: str,
        expires_at: datetime | None = None,
        actor_type: str = "GUARDIAN_SERVICE",
        actor_id: str = "guardian",
    ) -> BudgetReservation:
        res_expires_at = expires_at or (datetime.now(UTC) + timedelta(minutes=30))
        try:
            reservation = self.repo.reserve_budget_atomic(
                tenant_id=tenant_id,
                correlation_id=correlation_id,
                passport_id=passport_id,
                payment_intent_id=payment_intent_id,
                amount_minor=amount_minor,
                currency=currency,
                expires_at=res_expires_at,
            )
        except RepoInsufficientBudgetError as exc:
            raise InsufficientBudgetError(str(exc)) from exc

        self.repo.append_financial_event(
            tenant_id=tenant_id,
            correlation_id=correlation_id,
            payment_intent_id=payment_intent_id,
            event_type=FinancialEventType.BUDGET_RESERVED,
            actor_type=actor_type,
            actor_id=actor_id,
            payload={
                "reservation_id": str(reservation.id),
                "passport_id": str(passport_id),
                "amount_minor": amount_minor,
                "currency": currency,
                "expires_at": res_expires_at.isoformat(),
            },
        )
        return reservation

    def capture(
        self,
        *,
        tenant_id: UUID,
        correlation_id: UUID,
        payment_intent_id: UUID,
        reservation_id: UUID,
        actor_type: str = "GUARDIAN_SERVICE",
        actor_id: str = "guardian",
    ) -> BudgetReservation:
        try:
            reservation = self.repo.capture_reservation_atomic(tenant_id, reservation_id)
        except RepoInsufficientBudgetError as exc:
            raise InsufficientBudgetError(str(exc)) from exc
        except ValueError as exc:
            raise GuardianError(str(exc)) from exc

        self.repo.append_financial_event(
            tenant_id=tenant_id,
            correlation_id=correlation_id,
            payment_intent_id=payment_intent_id,
            event_type=FinancialEventType.BUDGET_CAPTURED,
            actor_type=actor_type,
            actor_id=actor_id,
            payload={
                "reservation_id": str(reservation.id),
                "amount_minor": reservation.amount_minor,
                "currency": reservation.currency,
                "status": reservation.status.value,
            },
        )
        return reservation

    def release(
        self,
        *,
        tenant_id: UUID,
        correlation_id: UUID,
        payment_intent_id: UUID,
        reservation_id: UUID,
        actor_type: str = "GUARDIAN_SERVICE",
        actor_id: str = "guardian",
        reason: str = "BUYER_DECLINED_OR_CANCELLED",
    ) -> BudgetReservation:
        try:
            reservation = self.repo.release_reservation_atomic(tenant_id, reservation_id)
        except ValueError as exc:
            raise GuardianError(str(exc)) from exc

        self.repo.append_financial_event(
            tenant_id=tenant_id,
            correlation_id=correlation_id,
            payment_intent_id=payment_intent_id,
            event_type=FinancialEventType.BUDGET_RELEASED,
            actor_type=actor_type,
            actor_id=actor_id,
            payload={
                "reservation_id": str(reservation.id),
                "amount_minor": reservation.amount_minor,
                "currency": reservation.currency,
                "reason": reason,
                "status": reservation.status.value,
            },
        )
        return reservation
