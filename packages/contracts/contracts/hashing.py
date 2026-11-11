"""Deterministic canonical JSON serialization and SHA-256 hashing helpers."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from typing import Any
from uuid import UUID


def _json_default(value: Any) -> Any:
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, datetime):
        utc_val = value.astimezone(UTC) if value.tzinfo else value.replace(tzinfo=UTC)
        return utc_val.isoformat()
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")
    raise TypeError(f"Object of type {type(value).__name__} is not JSON serializable")


def canonical_json(payload: Any) -> str:
    """Serialize any JSON-like or Pydantic object into deterministic canonical JSON."""
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), default=_json_default)


def compute_payload_hash(payload: Any) -> str:
    """Compute SHA-256 hex digest of deterministic canonical JSON."""
    return hashlib.sha256(canonical_json(payload).encode("utf-8")).hexdigest()


def compute_quote_hash(
    *,
    merchant_id: UUID | str,
    amount_minor: int,
    currency: str,
    line_items: list[dict[str, Any]] | None = None,
) -> str:
    """Compute an immutable binding hash for a merchant, amount, currency, and line items."""
    return compute_payload_hash({
        "merchant_id": str(merchant_id),
        "amount_minor": amount_minor,
        "currency": currency.upper(),
        "line_items": line_items or [],
    })

