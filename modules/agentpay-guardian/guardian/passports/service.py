"""Spending passport service for AgentPay Guardian."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from contracts import Merchant, PassportStatus, SpendingPassport

from guardian.domain.exceptions import GuardianError, PolicyDeniedError

try:
    from database import LedgerRepository
except (ImportError, ModuleNotFoundError):
    LedgerRepository = Any  # type: ignore[misc, assignment]


class PassportService:
    """Manages spending passports and merchant allowlists via LedgerRepository."""

    def __init__(self, repo: LedgerRepository) -> None:
        self.repo = repo

    def get_passport(self, tenant_id: UUID, passport_id: UUID) -> SpendingPassport:
        passport = self.repo.get_passport(tenant_id, passport_id)
        if passport is None:
            raise GuardianError(f"SpendingPassport {passport_id} not found for tenant {tenant_id}")
        return passport

    def get_merchant(self, tenant_id: UUID, merchant_id: UUID) -> Merchant:
        merchant = self.repo.get_merchant(tenant_id, merchant_id)
        if merchant is None:
            raise GuardianError(f"Merchant {merchant_id} not found for tenant {tenant_id}")
        return merchant

    def validate_passport_active(
        self,
        passport: SpendingPassport,
        *,
        now: datetime | None = None,
    ) -> None:
        current_time = now or datetime.now(UTC)
        if passport.status != PassportStatus.ACTIVE:
            raise PolicyDeniedError(
                f"SpendingPassport {passport.id} is not active ({passport.status.value})"
            )
        if passport.expires_at < current_time:
            raise PolicyDeniedError(
                f"SpendingPassport {passport.id} expired at {passport.expires_at.isoformat()}"
            )

    def list_passports(self, tenant_id: UUID) -> list[SpendingPassport]:
        return self.repo.list_passports(tenant_id)

    def list_merchants(self, tenant_id: UUID) -> list[Merchant]:
        return self.repo.list_merchants(tenant_id)

    def create_passport(self, passport: SpendingPassport) -> SpendingPassport:
        return self.repo.create_passport(passport)

    def create_merchant(self, merchant: Merchant) -> Merchant:
        return self.repo.create_merchant(merchant)
