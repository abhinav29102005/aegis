"""HMAC signing and append-only financial event hash-chain verification."""

from __future__ import annotations

import hashlib
import hmac
import time
from collections.abc import Sequence
from typing import Any
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


def sign_webhook_payload(
    secret: str,
    raw_body: bytes | str,
    timestamp: int | None = None,
) -> tuple[int, str]:
    """Compute replay-protected ``(timestamp, hmac_sha256_hex)`` for an outbound webhook body."""
    ts = int(time.time()) if timestamp is None else int(timestamp)
    body_str = raw_body.decode("utf-8") if isinstance(raw_body, bytes) else raw_body
    signed_message = f"{ts}.{body_str}".encode()
    sig = hmac.new(secret.encode("utf-8"), signed_message, hashlib.sha256).hexdigest()
    return ts, sig


def format_aegis_signature(
    secret: str,
    raw_body: bytes | str,
    timestamp: int | None = None,
) -> str:
    """Format canonical ``X-Aegis-Signature`` header value ``t=<ts>,v1=<hex>``."""
    ts, sig = sign_webhook_payload(secret, raw_body, timestamp=timestamp)
    return f"t={ts},v1={sig}"


def verify_aegis_signature(
    secret: str,
    raw_body: bytes | str,
    header_value: str,
    tolerance_seconds: int = 300,
    now_ts: int | None = None,
) -> bool:
    """Verify a replay-protected ``t=<ts>,v1=<hex>`` webhook signature in constant time."""
    if not header_value or not secret:
        return False

    ts: int | None = None
    signatures: list[str] = []
    for part in header_value.split(","):
        item = part.strip()
        if "=" not in item:
            continue
        key, value = item.split("=", 1)
        key = key.strip()
        value = value.strip()
        if key == "t":
            if ts is not None:
                return False
            try:
                ts = int(value)
            except ValueError:
                return False
        elif key == "v1" and value:
            signatures.append(value)

    if ts is None or not signatures:
        return False

    current = int(time.time()) if now_ts is None else int(now_ts)
    if tolerance_seconds >= 0 and abs(current - ts) > tolerance_seconds:
        return False

    _, expected_sig = sign_webhook_payload(secret, raw_body, timestamp=ts)
    matched = False
    for provided in signatures:
        if hmac.compare_digest(expected_sig, provided):
            matched = True
    return matched

