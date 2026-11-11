"""Deterministic event timeline reconstruction for GhostPay."""

from __future__ import annotations

import hmac
from collections.abc import Sequence
from uuid import UUID

from contracts import (
    EvidenceRecord,
    EvidenceSourceType,
    FinancialEvent,
    FinancialEventType,
    ReplayTimelineEntry,
)
from security.hashing import compute_financial_event_hash


def _format_event_summary(event: FinancialEvent) -> str:
    """Produce deterministic human-readable summary for a financial event."""
    t = event.event_type
    p = event.payload or {}
    actor_str = f"{event.actor_type}:{event.actor_id}"

    if t == FinancialEventType.PROPOSAL_CREATED:
        amount = p.get("amount_minor")
        merchant = p.get("merchant_id")
        return f"Purchase proposal created by {actor_str} for amount_minor={amount} (merchant={merchant})."
    if t == FinancialEventType.POLICY_EVALUATED:
        outcome = p.get("outcome")
        q_hash = p.get("quote_hash")
        return f"Guardian policy evaluated by {actor_str} with outcome={outcome} (quote_hash={q_hash})."
    if t == FinancialEventType.APPROVAL_REQUESTED:
        amount = p.get("amount_minor")
        return f"Human approval requested for amount_minor={amount}."
    if t == FinancialEventType.HUMAN_APPROVED:
        approver = p.get("approver_id", event.actor_id)
        return f"Human approval granted by {approver}."
    if t == FinancialEventType.HUMAN_REJECTED:
        approver = p.get("approver_id", event.actor_id)
        return f"Human approval rejected by {approver}."
    if t == FinancialEventType.BUDGET_RESERVED:
        res_id = p.get("reservation_id")
        amount = p.get("amount_minor")
        return f"Budget reservation held (id={res_id}, amount_minor={amount})."
    if t == FinancialEventType.BUDGET_CAPTURED:
        amount = p.get("amount_minor")
        return f"Budget reservation captured for amount_minor={amount}."
    if t == FinancialEventType.BUDGET_RELEASED:
        return f"Budget reservation released by {actor_str}."
    if t == FinancialEventType.PAYPAL_ORDER_CREATED:
        order_id = p.get("paypal_order_id")
        return f"PayPal order created with order_id={order_id}."
    if t == FinancialEventType.PAYPAL_BUYER_APPROVED:
        order_id = p.get("paypal_order_id")
        payer_id = p.get("payer_id")
        return f"PayPal buyer approval received for order_id={order_id} (payer={payer_id})."
    if t == FinancialEventType.PAYPAL_BUYER_CANCELLED:
        order_id = p.get("paypal_order_id")
        return f"PayPal buyer cancelled checkout for order_id={order_id}."
    if t == FinancialEventType.PAYPAL_CAPTURE_REQUESTED:
        order_id = p.get("paypal_order_id")
        return f"PayPal capture requested for order_id={order_id}."
    if t == FinancialEventType.PAYPAL_CAPTURE_VERIFIED:
        cap_id = p.get("capture_id", event.actor_id)
        status = p.get("status")
        amount = p.get("amount_minor")
        return f"PayPal capture verified: {cap_id} status={status} amount_minor={amount}."
    if t == FinancialEventType.PAYMENT_FAILED:
        code = p.get("failure_code")
        return f"Payment failed with code={code}."
    if t == FinancialEventType.DISPUTE_OPENED:
        return f"Dispute opened against payment intent {event.payment_intent_id}."

    return f"Event {t.value} recorded by {actor_str}."


def _correlate_evidence_ids(
    event: FinancialEvent,
    evidence_records: Sequence[EvidenceRecord],
) -> list[UUID]:
    """Map associated evidence records to a timeline entry."""
    matched: list[UUID] = []
    p = event.payload or {}

    for ev in evidence_records:
        # Match by direct payment intent association
        if event.payment_intent_id and ev.payment_intent_id and event.payment_intent_id != ev.payment_intent_id:
            continue

        # Match specific event types to corresponding evidence source types
        if (
            (event.event_type == FinancialEventType.PROPOSAL_CREATED and ev.source_type == EvidenceSourceType.PROPOSAL)
            or (
                event.event_type == FinancialEventType.POLICY_EVALUATED
                and ev.source_type in (EvidenceSourceType.POLICY_DECISION, EvidenceSourceType.QUOTE)
            )
            or (
                event.event_type in (
                    FinancialEventType.HUMAN_APPROVED,
                    FinancialEventType.HUMAN_REJECTED,
                    FinancialEventType.APPROVAL_REQUESTED,
                )
                and ev.source_type == EvidenceSourceType.HUMAN_APPROVAL
            )
            or (event.event_type == FinancialEventType.PAYPAL_ORDER_CREATED and ev.source_type == EvidenceSourceType.PAYPAL_ORDER)
            or (event.event_type == FinancialEventType.PAYPAL_CAPTURE_VERIFIED and ev.source_type == EvidenceSourceType.PAYPAL_CAPTURE)
            or (event.event_type == FinancialEventType.PAYPAL_WEBHOOK_RECEIVED and ev.source_type == EvidenceSourceType.PAYPAL_WEBHOOK)
            or ("quote_hash" in p and ev.source_type == EvidenceSourceType.QUOTE and ev.content.get("quote_hash") == p["quote_hash"])
        ):
            matched.append(ev.id)

    # Return deduplicated UUIDs preserving order
    return list(dict.fromkeys(matched))


def build_timeline(
    events: Sequence[FinancialEvent],
    evidence_records: Sequence[EvidenceRecord] | None = None,
) -> list[ReplayTimelineEntry]:
    """Deterministically reconstruct event timeline sorted by (sequence_number, occurred_at, str(id))."""
    if not events:
        return []

    ev_list = list(evidence_records or [])
    # Sort deterministically
    sorted_events = sorted(events, key=lambda e: (e.sequence_number, e.occurred_at, str(e.id)))

    timeline: list[ReplayTimelineEntry] = []
    expected_prev: str | None = None

    for idx, ev in enumerate(sorted_events):
        # Verify single event integrity against canonical hash calculation
        recomputed = compute_financial_event_hash(
            event_id=ev.id,
            tenant_id=ev.tenant_id,
            correlation_id=ev.correlation_id,
            payment_intent_id=ev.payment_intent_id,
            sequence_number=ev.sequence_number,
            event_type=ev.event_type.value,
            actor_type=ev.actor_type,
            actor_id=ev.actor_id,
            payload=ev.payload,
            previous_event_hash=ev.previous_event_hash,
            occurred_at_iso=ev.occurred_at.isoformat(),
        )
        hash_ok = hmac.compare_digest(recomputed, ev.event_hash)
        prev_ok = (ev.previous_event_hash == expected_prev)
        mono_ok = (idx == 0 or ev.sequence_number > sorted_events[idx - 1].sequence_number)
        entry_integrity = hash_ok and prev_ok and mono_ok

        expected_prev = ev.event_hash
        ev_ids = _correlate_evidence_ids(ev, ev_list)

        timeline.append(
            ReplayTimelineEntry(
                sequence_number=ev.sequence_number,
                event_id=ev.id,
                event_type=ev.event_type,
                actor_type=ev.actor_type,
                actor_id=ev.actor_id,
                occurred_at=ev.occurred_at,
                summary=_format_event_summary(ev),
                evidence_ids=ev_ids,
                integrity_verified=entry_integrity,
            )
        )

    return timeline
