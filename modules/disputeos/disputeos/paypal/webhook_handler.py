"""PayPal Disputes v1 webhook handler for DisputeOS (CUSTOMER.DISPUTE.*)."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import InvalidOperation
from typing import TYPE_CHECKING, Any
from uuid import UUID, uuid4

from contracts import (
    DisputeCase,
    DisputeSourceType,
    DisputeStatus,
    EvidenceSourceType,
    FinancialEventType,
    can_transition_dispute,
)
from contracts.models import utc_now
from paypal import paypal_value_to_minor

if TYPE_CHECKING:
    from database import LedgerRepository


class AwaitableDict(dict):
    """Dict that can also be awaited by asynchronous callers."""

    def __await__(self):
        async def _coro():
            return self

        return _coro().__await__()


def _parse_iso_datetime(raw: Any) -> datetime | None:
    if raw is None:
        return None
    if isinstance(raw, datetime):
        return raw.replace(tzinfo=UTC) if raw.tzinfo is None else raw.astimezone(UTC)
    if isinstance(raw, str) and raw.strip():
        cleaned = raw.strip()
        if cleaned.endswith("Z"):
            cleaned = f"{cleaned[:-1]}+00:00"
        try:
            parsed = datetime.fromisoformat(cleaned)
        except ValueError:
            return None
        return parsed.replace(tzinfo=UTC) if parsed.tzinfo is None else parsed.astimezone(UTC)
    return None


def _extract_amount(resource: dict[str, Any]) -> tuple[int, str]:
    dispute_amount = resource.get("dispute_amount")
    if isinstance(dispute_amount, dict) and dispute_amount.get("value") is not None:
        try:
            minor = max(1, paypal_value_to_minor(str(dispute_amount["value"])))
            currency = str(dispute_amount.get("currency_code") or "USD").upper()[:3]
            return minor, currency
        except (ValueError, TypeError, InvalidOperation):
            return 1, "USD"
    return 1, "USD"


def _extract_outcome(resource: dict[str, Any]) -> str:
    outcome = resource.get("dispute_outcome")
    if isinstance(outcome, dict):
        code = str(outcome.get("outcome_code") or "").strip()
        if code:
            return code[:64]
    if isinstance(outcome, str) and outcome.strip():
        return outcome.strip()[:64]
    return "RESOLVED_BY_PAYPAL"


def _extract_buyer_claim(resource: dict[str, Any], reason: str) -> str:
    messages = resource.get("messages")
    if isinstance(messages, list):
        for msg in messages:
            if isinstance(msg, dict) and str(msg.get("posted_by", "")).upper() == "BUYER":
                content = str(msg.get("content") or "").strip()
                if content:
                    return content[:2000]
    summary = str(resource.get("dispute_life_cycle_stage") or reason or "PayPal dispute opened").strip()
    return summary[:2000]


def _find_case_by_paypal_dispute_id(repo: Any, paypal_dispute_id: str) -> DisputeCase | None:
    session = getattr(repo, "session", None)
    if session is not None:
        try:
            from database import DisputeCaseRow
            from sqlalchemy import select

            row = session.scalar(
                select(DisputeCaseRow)
                .where(DisputeCaseRow.paypal_dispute_id == paypal_dispute_id)
                .order_by(DisputeCaseRow.opened_at.desc())
                .limit(1)
            )
            if row is not None and hasattr(repo, "_to_dispute_case"):
                return repo._to_dispute_case(row)
        except Exception:
            pass

    finder = getattr(repo, "find_dispute_case_by_paypal_id", None)
    if callable(finder):
        res = finder(paypal_dispute_id)
        if res is not None:
            return res

    get_by_pp = getattr(repo, "get_dispute_case_by_paypal_id", None)
    if callable(get_by_pp):
        res = get_by_pp(paypal_dispute_id)
        if res is not None:
            return res

    cases_dict = getattr(repo, "_cases", None)
    if isinstance(cases_dict, dict):
        for c in cases_dict.values():
            if getattr(c, "paypal_dispute_id", None) == paypal_dispute_id:
                return c

    list_fn = getattr(repo, "list_dispute_cases", None) or getattr(repo, "list_cases", None)
    if callable(list_fn):
        try:
            cases = list_fn()
            for c in cases:
                if getattr(c, "paypal_dispute_id", None) == paypal_dispute_id:
                    return c
        except Exception:
            pass

    return None


def _find_matching_intent_context(
    repo: Any,
    resource: dict[str, Any],
) -> tuple[UUID, UUID, UUID, int, str] | None:
    """Resolve (tenant_id, correlation_id, payment_intent_id, amount_minor, currency) from ledger."""
    session = getattr(repo, "session", None)
    if session is None:
        return None

    try:
        from database import EvidenceRecordRow, PaymentAttemptRow
        from sqlalchemy import select

        candidate_order_ids: list[str] = []
        candidate_capture_ids: list[str] = []

        supp = resource.get("supplementary_data")
        if isinstance(supp, dict):
            rel = supp.get("related_ids")
            if isinstance(rel, dict) and rel.get("order_id"):
                candidate_order_ids.append(str(rel["order_id"]).strip())

        disputed_txs = resource.get("disputed_transactions")
        if isinstance(disputed_txs, list):
            for tx in disputed_txs:
                if not isinstance(tx, dict):
                    continue
                for key in ("seller_transaction_id", "buyer_transaction_id"):
                    val = tx.get(key)
                    if val:
                        candidate_capture_ids.append(str(val).strip())
                if tx.get("paypal_order_id"):
                    candidate_order_ids.append(str(tx["paypal_order_id"]).strip())

        for order_id in candidate_order_ids:
            attempt = session.scalar(
                select(PaymentAttemptRow)
                .where(PaymentAttemptRow.paypal_order_id == order_id)
                .limit(1)
            )
            if attempt is not None:
                intent = repo.get_intent(attempt.tenant_id, attempt.payment_intent_id)
                if intent is not None:
                    return (
                        intent.tenant_id,
                        intent.correlation_id,
                        intent.id,
                        intent.amount_minor,
                        intent.currency,
                    )

        for capture_id in candidate_capture_ids:
            ev_row = session.scalar(
                select(EvidenceRecordRow)
                .where(EvidenceRecordRow.source_ref == f"paypal:{capture_id}")
                .limit(1)
            )
            if ev_row is not None and ev_row.payment_intent_id is not None:
                intent = repo.get_intent(ev_row.tenant_id, ev_row.payment_intent_id)
                if intent is not None:
                    return (
                        intent.tenant_id,
                        intent.correlation_id,
                        intent.id,
                        intent.amount_minor,
                        intent.currency,
                    )

            attempts = session.scalars(
                select(PaymentAttemptRow).where(PaymentAttemptRow.verified_capture.is_not(None))
            ).all()
            for attempt in attempts:
                cap = attempt.verified_capture or {}
                if cap.get("paypal_capture_id") == capture_id:
                    intent = repo.get_intent(attempt.tenant_id, attempt.payment_intent_id)
                    if intent is not None:
                        return (
                            intent.tenant_id,
                            intent.correlation_id,
                            intent.id,
                            intent.amount_minor,
                            intent.currency,
                        )
    except Exception:
        pass

    return None


def _attach_webhook_evidence(
    repo: Any,
    *,
    case: DisputeCase,
    event_type: str,
    event_id: str,
    resource: dict[str, Any],
) -> DisputeCase:
    source_ref = f"paypal-webhook:{event_id}"
    list_ev_fn = getattr(repo, "list_evidence", None)
    if callable(list_ev_fn):
        try:
            existing_evidence = list_ev_fn(case.tenant_id, dispute_case_id=case.id)
            if any(ev.source_ref == source_ref for ev in existing_evidence):
                return case
        except Exception:
            pass

    try:
        from disputeos.ingestion.normalizer import DocumentIngestionService

        ingestor = DocumentIngestionService()
        record = ingestor.ingest_document(
            tenant_id=case.tenant_id,
            correlation_id=case.correlation_id,
            payment_intent_id=case.payment_intent_id,
            dispute_case_id=case.id,
            source_type=EvidenceSourceType.PAYPAL_WEBHOOK,
            source_ref=source_ref,
            title=f"PayPal Dispute Webhook ({event_type})",
            content={
                "event_id": event_id,
                "event_type": event_type,
                "dispute_id": case.paypal_dispute_id,
                "status": resource.get("status"),
                "seller_response_due_date": resource.get("seller_response_due_date"),
                "dispute_outcome": resource.get("dispute_outcome"),
                "reason": resource.get("reason"),
            },
            is_synthetic=case.is_synthetic,
        )
        save_ev = getattr(repo, "save_evidence", None)
        if callable(save_ev):
            save_ev(record)
        if record.id not in case.evidence_ids:
            return case.model_copy(update={"evidence_ids": [*case.evidence_ids, record.id]})
    except Exception:
        pass
    return case


def handle_paypal_dispute_webhook(
    repo: Any,
    event_type: str,
    resource: dict[str, Any],
    event_id: str = "WH-EV-DEFAULT",
    tenant_id: UUID | None = None,
) -> AwaitableDict:
    """Process a verified PayPal CUSTOMER.DISPUTE.* webhook idempotently against LedgerRepository or DisputeCaseService."""
    paypal_dispute_id = str(resource.get("dispute_id") or resource.get("id") or "").strip()[:128]
    if not paypal_dispute_id:
        return AwaitableDict({
            "handled": False,
            "reason": "missing_dispute_id",
            "event_type": event_type,
        })

    response_due_by = _parse_iso_datetime(
        resource.get("seller_response_due_date") or resource.get("response_due_date")
    )
    raw_status = str(resource.get("status") or "").strip()
    external_status = raw_status[:64] if raw_status else None
    is_resolved_event = event_type == "CUSTOMER.DISPUTE.RESOLVED" or (
        external_status is not None and external_status.upper() == "RESOLVED"
    )

    existing_case = _find_case_by_paypal_dispute_id(repo, paypal_dispute_id)

    if existing_case is None:
        if event_type not in ("CUSTOMER.DISPUTE.CREATED", "CUSTOMER.DISPUTE.RESOLVED"):
            return AwaitableDict({
                "handled": False,
                "reason": f"DisputeCase for {paypal_dispute_id} not found",
            })

        matched = _find_matching_intent_context(repo, resource)
        if matched is not None:
            resolved_tenant, correlation_id, payment_intent_id, intent_minor, intent_currency = matched
            parsed_minor, parsed_currency = _extract_amount(resource)
            amount_minor = parsed_minor if resource.get("dispute_amount") else intent_minor
            currency = parsed_currency if resource.get("dispute_amount") else intent_currency
        else:
            resolved_tenant = tenant_id or UUID("00000000-0000-0000-0000-000000000001")
            correlation_id = uuid4()
            payment_intent_id = uuid4()
            amount_minor, currency = _extract_amount(resource)

        reason = str(resource.get("reason") or "MERCHANDISE_OR_SERVICE_NOT_RECEIVED").strip()[:255]
        buyer_claim = _extract_buyer_claim(resource, reason)
        now = utc_now()

        initial_status = DisputeStatus.RESOLVED if is_resolved_event else DisputeStatus.OPEN
        new_case = DisputeCase(
            id=uuid4(),
            tenant_id=resolved_tenant,
            correlation_id=correlation_id,
            payment_intent_id=payment_intent_id,
            paypal_dispute_id=paypal_dispute_id,
            source_type=DisputeSourceType.PAYPAL_SANDBOX,
            is_synthetic=False,
            reason=reason,
            buyer_claim=buyer_claim,
            amount_minor=amount_minor,
            currency=currency,
            status=initial_status,
            response_due_by=response_due_by,
            external_status=external_status or ("RESOLVED" if is_resolved_event else "OPEN"),
            resolved_at=now if is_resolved_event else None,
            resolution_outcome=_extract_outcome(resource) if is_resolved_event else None,
            opened_at=now,
            updated_at=now,
        )

        save_fn = getattr(repo, "save_dispute_case", None)
        if callable(save_fn):
            saved_case = save_fn(new_case)
        elif hasattr(repo, "_cases"):
            repo._cases[new_case.id] = new_case
            saved_case = new_case
        else:
            saved_case = new_case

        saved_case = _attach_webhook_evidence(
            repo,
            case=saved_case,
            event_type=event_type,
            event_id=event_id,
            resource=resource,
        )
        if callable(save_fn):
            saved_case = save_fn(saved_case)

        append_fn = getattr(repo, "append_financial_event", None)
        if callable(append_fn):
            append_fn(
                tenant_id=resolved_tenant,
                correlation_id=correlation_id,
                payment_intent_id=payment_intent_id,
                event_type=(
                    FinancialEventType.DISPUTE_RESOLVED
                    if is_resolved_event
                    else FinancialEventType.DISPUTE_OPENED
                ),
                actor_type="PAYPAL_WEBHOOK",
                actor_id=event_id,
                payload={
                    "dispute_case_id": str(saved_case.id),
                    "paypal_dispute_id": paypal_dispute_id,
                    "paypal_event_type": event_type,
                    "external_status": saved_case.external_status,
                    "response_due_by": saved_case.response_due_by.isoformat()
                    if saved_case.response_due_by
                    else None,
                    "resolution_outcome": saved_case.resolution_outcome,
                },
            )
        return AwaitableDict({
            "handled": True,
            "action": "created",
            "event_type": event_type,
            "case_id": str(saved_case.id),
            "tenant_id": str(saved_case.tenant_id),
            "paypal_dispute_id": paypal_dispute_id,
            "status": saved_case.status.value,
            "external_status": saved_case.external_status,
            "response_due_by": saved_case.response_due_by.isoformat()
            if saved_case.response_due_by
            else None,
            "resolution_outcome": saved_case.resolution_outcome,
        })

    # Case exists
    if event_type == "CUSTOMER.DISPUTE.CREATED":
        return AwaitableDict({
            "handled": True,
            "action": "already_exists",
            "case_id": str(existing_case.id),
        })

    now = utc_now()
    updates: dict[str, Any] = {"updated_at": now}
    if response_due_by is not None:
        updates["response_due_by"] = response_due_by
    if external_status is not None:
        updates["external_status"] = external_status

    transitioned_to_resolved = False
    if is_resolved_event:
        outcome = _extract_outcome(resource)
        if existing_case.status != DisputeStatus.RESOLVED and can_transition_dispute(
            existing_case.status, DisputeStatus.RESOLVED
        ):
            updates["status"] = DisputeStatus.RESOLVED
            updates["resolved_at"] = now
            updates["resolution_outcome"] = outcome
            updates["external_status"] = external_status or "RESOLVED"
            transitioned_to_resolved = True
        elif existing_case.status == DisputeStatus.RESOLVED and not existing_case.resolution_outcome:
            updates["resolution_outcome"] = outcome

    updated_case = existing_case.model_copy(update=updates)
    updated_case = _attach_webhook_evidence(
        repo,
        case=updated_case,
        event_type=event_type,
        event_id=event_id,
        resource=resource,
    )
    save_fn = getattr(repo, "save_dispute_case", None)
    if callable(save_fn):
        saved_case = save_fn(updated_case)
    elif hasattr(repo, "_cases"):
        repo._cases[updated_case.id] = updated_case
        saved_case = updated_case
    else:
        saved_case = updated_case

    append_fn = getattr(repo, "append_financial_event", None)
    if callable(append_fn):
        append_fn(
            tenant_id=saved_case.tenant_id,
            correlation_id=saved_case.correlation_id,
            payment_intent_id=saved_case.payment_intent_id,
            event_type=(
                FinancialEventType.DISPUTE_RESOLVED
                if transitioned_to_resolved
                else FinancialEventType.PAYPAL_WEBHOOK_RECEIVED
            ),
            actor_type="PAYPAL_WEBHOOK",
            actor_id=event_id,
            payload={
                "dispute_case_id": str(saved_case.id),
                "paypal_dispute_id": paypal_dispute_id,
                "paypal_event_type": event_type,
                "external_status": saved_case.external_status,
                "response_due_by": saved_case.response_due_by.isoformat()
                if saved_case.response_due_by
                else None,
                "resolution_outcome": saved_case.resolution_outcome,
            },
        )

    return AwaitableDict({
        "handled": True,
        "action": "resolved" if transitioned_to_resolved else "updated",
        "event_type": event_type,
        "case_id": str(saved_case.id),
        "tenant_id": str(saved_case.tenant_id),
        "paypal_dispute_id": paypal_dispute_id,
        "status": saved_case.status.value,
        "external_status": saved_case.external_status,
        "response_due_by": saved_case.response_due_by.isoformat()
        if saved_case.response_due_by
        else None,
        "resolution_outcome": saved_case.resolution_outcome,
    })
