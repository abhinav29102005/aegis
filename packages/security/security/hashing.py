"""HMAC signing and append-only financial event hash-chain verification."""

from __future__ import annotations

import hashlib
import hmac
from typing import Any, Sequence
from uuid import UUID

from contracts import FinancialEvent, canonical_json, compute_payload_hash


def sign_hmac_sha256(payload: Any, secret: str) -> str:
    """Sign canonical JSON representation with HMAC-SHA256."""
    msg = canonical_json(payload).encode("utf-8")
    return hmac.new(secret.encode("utf-8"), msg, hashlib.sha256).hexdigest()


def verify_hmac_sha256(payload: Any, signature: str, secret: str) -> bool:
    """Constant-time verification of HMAC-SHA256 signature."""
    expected = sign_hmac_sha256(payload, secret)
    return hmac.compare_digest(expected, signature)


def compute_financial_event_hash(
    *,
    event_id: UUID,
    tenant_id: UUID,
    correlation_id: UUID,
    payment_intent_id: UUID | None,
    sequence_number: int,
    event_type: str,
    actor_type: str,
    actor_id: str,
    payload: dict[str, Any],
    previous_event_hash: str | None,
    occurred_at_iso: str,
) -> str:
    """Compute canonical SHA-256 hash linking an event to its predecessor."""
    return compute_payload_hash({
        "id": str(event_id),
        "tenant_id": str(tenant_id),
        "correlation_id": str(correlation_id),
        "payment_intent_id": str(payment_intent_id) if payment_intent_id else None,
        "sequence_number": sequence_number,
        "event_type": event_type,
        "actor_type": actor_type,
        "actor_id": actor_id,
        "payload": payload,
        "previous_event_hash": previous_event_hash,
        "occurred_at": occurred_at_iso,
    })


def verify_financial_event_chain(events: Sequence[FinancialEvent]) -> tuple[bool, list[str]]:
    """Verify hash-chain continuity and per-event SHA-256 digests across ordered events."""
    if not events:
        return True, []

    ordered = sorted(events, key=lambda e: (e.sequence_number, e.occurred_at, str(e.id)))
    errors: list[str] = []
    expected_prev: str | None = None

    for idx, ev in enumerate(ordered):
        if idx > 0 and ev.sequence_number <= ordered[idx - 1].sequence_number:
            errors.append(
                f"Non-monotonic sequence_number at event {ev.id}: {ev.sequence_number}"
            )
        if ev.previous_event_hash != expected_prev:
            errors.append(
                f"Broken previous_event_hash at sequence {ev.sequence_number} ({ev.id}): "
                f"expected {expected_prev}, got {ev.previous_event_hash}"
            )
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
        if not hmac.compare_digest(recomputed, ev.event_hash):
            errors.append(
                f"Tampered event_hash at sequence {ev.sequence_number} ({ev.id}): "
                f"recomputed {recomputed} != stored {ev.event_hash}"
            )
        expected_prev = ev.event_hash

    return len(errors) == 0, errors
