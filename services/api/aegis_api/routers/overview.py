"""Overview metrics and hash-chained financial audit event explorer routes."""

from __future__ import annotations

import csv
import io
import json
from datetime import UTC, datetime
from typing import Annotated, Any, Literal
from uuid import UUID

from contracts import FinancialEvent, FinancialEventType
from database import (
    DisputeCaseRow,
    FinancialEventRow,
    LedgerRepository,
    PlatformRepository,
)
from fastapi import APIRouter, Depends, Query, Response
from security import AuthContext, Permission, verify_financial_event_chain
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from aegis_api.deps import get_db_session, require_permission

router = APIRouter(tags=["overview-audit"])


def _ensure_utc(dt: datetime) -> datetime:
    return dt.astimezone(UTC) if dt.tzinfo else dt.replace(tzinfo=UTC)


def _filter_audit_events(
    ledger: LedgerRepository,
    session: Session,
    tenant_id: UUID,
    *,
    correlation_id: UUID | None = None,
    payment_intent_id: UUID | None = None,
    event_type: FinancialEventType | None = None,
    actor_id: str | None = None,
    q: str | None = None,
    limit: int = 100,
    offset: int = 0,
) -> tuple[list[FinancialEvent], int]:
    clean_actor = actor_id.strip() if actor_id else None
    clean_q = q.strip().lower() if q else None

    if clean_actor is None and clean_q is None:
        count_stmt = select(func.count()).select_from(FinancialEventRow).where(FinancialEventRow.tenant_id == tenant_id)
        if correlation_id is not None:
            count_stmt = count_stmt.where(FinancialEventRow.correlation_id == correlation_id)
        if payment_intent_id is not None:
            count_stmt = count_stmt.where(FinancialEventRow.payment_intent_id == payment_intent_id)
        if event_type is not None:
            count_stmt = count_stmt.where(FinancialEventRow.event_type == event_type.value)
        total = int(session.scalar(count_stmt) or 0)
        events = ledger.list_events(
            tenant_id,
            correlation_id=correlation_id,
            payment_intent_id=payment_intent_id,
            event_type=event_type,
            limit=limit,
            offset=offset,
        )
        return events, total

    all_matching = ledger.list_events(
        tenant_id,
        correlation_id=correlation_id,
        payment_intent_id=payment_intent_id,
        event_type=event_type,
    )
    filtered: list[FinancialEvent] = []
    for ev in all_matching:
        if clean_actor is not None and ev.actor_id != clean_actor:
            continue
        if clean_q is not None:
            haystack = " ".join([
                ev.event_type.value,
                ev.actor_type,
                ev.actor_id,
                str(ev.correlation_id),
                str(ev.payment_intent_id or ""),
                json.dumps(ev.payload, sort_keys=True),
            ]).lower()
            if clean_q not in haystack:
                continue
        filtered.append(ev)

    total = len(filtered)
    return filtered[offset : offset + limit], total


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

    now = datetime.now(UTC)
    urgent_disputes = list(
        session.scalars(
            select(DisputeCaseRow)
            .where(
                DisputeCaseRow.tenant_id == auth.tenant_id,
                DisputeCaseRow.status.notin_(["RESOLVED"]),
                DisputeCaseRow.response_due_by.is_not(None),
            )
            .order_by(DisputeCaseRow.response_due_by.asc())
            .limit(10)
        ).all()
    )
    metrics["dispute_deadlines"] = [
        {
            "case_id": str(d.id),
            "correlation_id": str(d.correlation_id),
            "payment_intent_id": str(d.payment_intent_id),
            "reason": d.reason,
            "status": d.status,
            "amount_minor": d.amount_minor,
            "currency": d.currency,
            "response_due_by": _ensure_utc(d.response_due_by).isoformat() if d.response_due_by else None,
            "is_overdue": bool(d.response_due_by and _ensure_utc(d.response_due_by) <= now),
        }
        for d in urgent_disputes
    ]

    invocations = platform.list_llm_invocations(auth.tenant_id, limit=200)
    prompt_tokens = sum(i.prompt_tokens for i in invocations)
    completion_tokens = sum(i.completion_tokens for i in invocations)
    cost_micros = sum(i.estimated_cost_usd_micros for i in invocations)
    metrics["llm_usage"] = {
        "invocation_count": len(invocations),
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "total_tokens": prompt_tokens + completion_tokens,
        "estimated_cost_usd_micros": cost_micros,
        "recent": [
            {
                "id": str(i.id),
                "correlation_id": i.correlation_id,
                "module": i.module,
                "provider": i.provider,
                "model": i.model,
                "prompt_tokens": i.prompt_tokens,
                "completion_tokens": i.completion_tokens,
                "estimated_cost_usd_micros": i.estimated_cost_usd_micros,
                "created_at": _ensure_utc(i.created_at).isoformat(),
            }
            for i in invocations[:10]
        ],
    }
    return metrics


@router.get("/audit-events")
def list_audit_events(
    response: Response,
    auth: Annotated[AuthContext, Depends(require_permission(Permission.AUDIT_READ))],
    session: Annotated[Session, Depends(get_db_session)],
    correlation_id: UUID | None = None,
    payment_intent_id: UUID | None = None,
    event_type: FinancialEventType | None = None,
    actor_id: str | None = None,
    q: str | None = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> dict[str, Any]:
    ledger = LedgerRepository(session)
    events, total = _filter_audit_events(
        ledger,
        session,
        auth.tenant_id,
        correlation_id=correlation_id,
        payment_intent_id=payment_intent_id,
        event_type=event_type,
        actor_id=actor_id,
        q=q,
        limit=limit,
        offset=offset,
    )
    response.headers["X-Total-Count"] = str(total)

    chain_valid: bool | None = None
    chain_errors: list[str] = []
    if correlation_id is not None:
        full_chain = ledger.list_events(auth.tenant_id, correlation_id=correlation_id)
        chain_valid, chain_errors = verify_financial_event_chain(full_chain)

    return {
        "items": [ev.model_dump(mode="json") for ev in events],
        "count": len(events),
        "total": total,
        "limit": limit,
        "offset": offset,
        "chain_verified": chain_valid,
        "chain_errors": chain_errors,
    }


@router.get("/audit-events/export")
def export_audit_events(
    auth: Annotated[AuthContext, Depends(require_permission(Permission.AUDIT_READ))],
    session: Annotated[Session, Depends(get_db_session)],
    format: Literal["json", "csv"] = "json",
    correlation_id: UUID | None = None,
    payment_intent_id: UUID | None = None,
    event_type: FinancialEventType | None = None,
    actor_id: str | None = None,
    q: str | None = None,
    limit: Annotated[int, Query(ge=1, le=2000)] = 500,
) -> Response:
    ledger = LedgerRepository(session)
    events, total = _filter_audit_events(
        ledger,
        session,
        auth.tenant_id,
        correlation_id=correlation_id,
        payment_intent_id=payment_intent_id,
        event_type=event_type,
        actor_id=actor_id,
        q=q,
        limit=limit,
        offset=0,
    )

    if format == "csv":
        buf = io.StringIO()
        writer = csv.writer(buf)
        writer.writerow([
            "id",
            "correlation_id",
            "payment_intent_id",
            "sequence_number",
            "event_type",
            "actor_type",
            "actor_id",
            "event_hash",
            "previous_event_hash",
            "occurred_at",
            "payload",
        ])
        for ev in events:
            writer.writerow([
                str(ev.id),
                str(ev.correlation_id),
                str(ev.payment_intent_id) if ev.payment_intent_id else "",
                ev.sequence_number,
                ev.event_type.value,
                ev.actor_type,
                ev.actor_id,
                ev.event_hash,
                ev.previous_event_hash or "",
                ev.occurred_at.isoformat(),
                json.dumps(ev.payload, sort_keys=True),
            ])
        return Response(
            content=buf.getvalue(),
            media_type="text/csv; charset=utf-8",
            headers={
                "Content-Disposition": 'attachment; filename="aegis-audit-events.csv"',
                "X-Total-Count": str(total),
            },
        )

    chain_valid: bool | None = None
    chain_errors: list[str] = []
    if correlation_id is not None:
        full_chain = ledger.list_events(auth.tenant_id, correlation_id=correlation_id)
        chain_valid, chain_errors = verify_financial_event_chain(full_chain)

    payload = json.dumps(
        {
            "tenant_id": str(auth.tenant_id),
            "exported_at": datetime.now(UTC).isoformat(),
            "total": total,
            "chain_verified": chain_valid,
            "chain_errors": chain_errors,
            "items": [ev.model_dump(mode="json") for ev in events],
        },
        indent=2,
    )
    return Response(
        content=payload,
        media_type="application/json",
        headers={
            "Content-Disposition": 'attachment; filename="aegis-audit-events.json"',
            "X-Total-Count": str(total),
        },
    )
