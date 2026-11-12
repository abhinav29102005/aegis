"""Counterfactual policy specification for Policy Time Machine."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from contracts import Merchant, PassportStatus
from pydantic import BaseModel, Field


class CounterfactualPolicy(BaseModel):
    """Structured, validated counterfactual policy specification."""

    policy_id: UUID = Field(default_factory=uuid4)
    name: str = Field(min_length=1, max_length=120)
    description: str = Field(default="", max_length=500)
    per_tx_limit_minor: int | None = Field(default=None, ge=0)
    total_budget_minor: int | None = Field(default=None, ge=0)
    daily_limit_minor: int | None = Field(default=None, ge=0)
    human_approval_threshold_minor: int | None = Field(default=None, ge=0)
    allowed_merchant_ids: list[UUID] | None = None
    allowed_categories: list[str] | None = None
    allow_unknown_merchants: bool | None = None
    currency: str | None = Field(default=None, min_length=3, max_length=3)
    passport_status: PassportStatus | None = None
    expires_at: datetime | None = None
    merchant_override: Merchant | UUID | dict[str, Any] | None = None
    amount_override_minor: int | None = Field(default=None, gt=0)

    def to_overrides_dict(self) -> dict[str, Any]:
        """Convert specification into ReplayRequest counterfactual_overrides dictionary."""
        overrides: dict[str, Any] = {}
        if self.per_tx_limit_minor is not None:
            overrides["per_tx_limit_minor"] = self.per_tx_limit_minor
        if self.total_budget_minor is not None:
            overrides["total_budget_minor"] = self.total_budget_minor
        if self.daily_limit_minor is not None:
            overrides["daily_limit_minor"] = self.daily_limit_minor
        if self.human_approval_threshold_minor is not None:
            overrides["human_approval_threshold_minor"] = self.human_approval_threshold_minor
        if self.allowed_merchant_ids is not None:
            overrides["allowed_merchant_ids"] = self.allowed_merchant_ids
        if self.allowed_categories is not None:
            overrides["allowed_categories"] = self.allowed_categories
        if self.allow_unknown_merchants is not None:
            overrides["allow_unknown_merchants"] = self.allow_unknown_merchants
        if self.currency is not None:
            overrides["currency_override"] = self.currency.upper()
        if self.passport_status is not None:
            overrides["passport_status"] = self.passport_status
        if self.expires_at is not None:
            overrides["expires_at"] = self.expires_at
        if self.merchant_override is not None:
            overrides["merchant_override"] = self.merchant_override
        if self.amount_override_minor is not None:
            overrides["amount_override_minor"] = self.amount_override_minor
        return overrides
