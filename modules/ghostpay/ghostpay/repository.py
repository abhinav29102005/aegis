"""Read-only forensic repository protocol for database-backed GhostPay replay & investigations."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Protocol, runtime_checkable
from uuid import UUID

from contracts import EvidenceRecord, FinancialEvent, ReplayRequest, ReplayResult
from pydantic import BaseModel, ConfigDict, Field


class PersistedInvestigation(BaseModel):
    """Summary/detail contract for a persisted forensic replay or counterfactual investigation."""

    model_config = ConfigDict(extra="forbid")

    investigation_id: UUID
    tenant_id: UUID
    correlation_id: UUID
    payment_intent_id: UUID
    policy_version: str
    mode: str  # REPLAY | COUNTERFACTUAL
    overrides: dict[str, Any] = Field(default_factory=dict)
    consistency_status: str
    drift_detected: bool
    integrity_valid: bool
    created_by: str
    created_at: datetime
    result: ReplayResult


class InvestigationListResponse(BaseModel):
    """Paginated investigation list response."""

    model_config = ConfigDict(extra="forbid")

    items: list[PersistedInvestigation] = Field(default_factory=list)
    total: int
    limit: int
    offset: int


@runtime_checkable
class GhostPayReplayRepository(Protocol):
    """Interface required to reconstruct canonical forensic state from persistent storage."""

    def load_replay_request(
        self,
        tenant_id: UUID,
        correlation_id: UUID,
    ) -> ReplayRequest | None:
        """Load tenant-scoped persisted records for ``correlation_id`` or return None if absent."""
        ...

    def load_replay_request_by_payment(
        self,
        tenant_id: UUID,
        payment_intent_id: UUID,
    ) -> ReplayRequest | None:
        """Load tenant-scoped persisted records for ``payment_intent_id`` or return None if absent."""
        ...

    def load_timeline_records_by_payment(
        self,
        tenant_id: UUID,
        payment_intent_id: UUID,
    ) -> tuple[list[FinancialEvent], list[EvidenceRecord]] | None:
        """Load persisted events and evidence records for a payment intent."""
        ...

    def save_investigation(
        self,
        *,
        tenant_id: UUID,
        result: ReplayResult,
        mode: str,
        overrides: dict[str, Any],
        created_by: str,
    ) -> PersistedInvestigation:
        """Persist an immutable investigation audit snapshot (never mutates source ledger rows)."""
        ...

    def get_investigation(
        self,
        tenant_id: UUID,
        investigation_id: UUID,
    ) -> PersistedInvestigation | None:
        """Fetch a persisted investigation by ID for the given tenant."""
        ...

    def list_investigations(
        self,
        tenant_id: UUID,
        *,
        payment_intent_id: UUID | None = None,
        consistency_status: str | None = None,
        drift_detected: bool | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> InvestigationListResponse:
        """List persisted investigations with filtering and pagination."""
        ...
