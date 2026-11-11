"""Overview metrics and hash-chained financial audit event explorer routes."""

from __future__ import annotations

from typing import Annotated, Any
from uuid import UUID

from contracts import FinancialEventType
from database import LedgerRepository, PlatformRepository
from fastapi import APIRouter, Depends, Query
from security import AuthContext, Permission, verify_financial_event_chain
from sqlalchemy.orm import Session

from aegis_api.deps import get_db_session, require_permission

router = APIRouter(tags=["overview-audit"])


@router.get("/overview/metrics")
def overview_metrics(
    auth: Annotated[AuthContext, Depends(require_permission(Permission.AUDIT_READ))],
    session: Annotated[Session, Depends(get_db_session)],
) -> dict[str, Any]:
    platform = PlatformRepository(session)
    ledger = LedgerRepository(session)
    metrics = platform.get_overview_metrics(auth.tenant_id)
    recent_events = ledger.list_events(auth.tenant_id, limit=15)
    metrics["recent_events"] = [ev.model_dump(mode="json") for ev in reversed(recent_events)]
    return metrics


@router.get("/audit-events")
def list_audit_events(
    auth: Annotated[AuthContext, Depends(require_permission(Permission.AUDIT_READ))],
    session: Annotated[Session, Depends(get_db_session)],
    correlation_id: UUID | None = None,
    payment_intent_id: UUID | None = None,
    event_type: FinancialEventType | None = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> dict[str, Any]:
    ledger = LedgerRepository(session)
    events = ledger.list_events(
        auth.tenant_id,
        correlation_id=correlation_id,
        payment_intent_id=payment_intent_id,
        event_type=event_type,
        limit=limit,
        offset=offset,
    )
    chain_valid: bool | None = None
    chain_errors: list[str] = []
    if correlation_id is not None:
        full_chain = ledger.list_events(auth.tenant_id, correlation_id=correlation_id)
        chain_valid, chain_errors = verify_financial_event_chain(full_chain)

    return {
        "items": [ev.model_dump(mode="json") for ev in events],
        "count": len(events),
        "limit": limit,
        "offset": offset,
        "chain_verified": chain_valid,
        "chain_errors": chain_errors,
    }
