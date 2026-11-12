"""Deterministic canonical JSON serialization and SHA-256 hashing helpers."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from typing import Any
from uuid import UUID

CURRENCY_EXPONENTS: dict[str, int] = {
    "JPY": 0,
    "HUF": 0,
    "KRW": 0,
    "TWD": 0,
    "VND": 0,
    "CLP": 0,
    "ISK": 0,
    "BHD": 3,
    "JOD": 3,
    "KWD": 3,
    "OMR": 3,
    "TND": 3,
}


def get_currency_exponent(currency: str) -> int:
    """Return ISO 4217 minor-unit exponent for currency (default 2)."""
    return CURRENCY_EXPONENTS.get(currency.strip().upper(), 2)


def minor_to_decimal_str(amount_minor: int, currency: str) -> str:
    """Convert integer minor units to an exact fixed-precision decimal string."""
    exp = get_currency_exponent(currency)
    quant = Decimal(10) ** (-exp)
    value = (Decimal(amount_minor) * quant).quantize(quant)
    return format(value, "f")


def decimal_str_to_minor(value: str, currency: str) -> int:
    """Convert a decimal amount string to exact integer minor units for currency."""
    exp = get_currency_exponent(currency)
    try:
        dec = Decimal(str(value).strip())
    except InvalidOperation as exc:
        raise ValueError(f"Invalid decimal amount: {value!r}") from exc
    scale = Decimal(10) ** exp
    scaled = dec * scale
    if scaled != scaled.to_integral_value():
        raise ValueError(
            f"Amount {value!r} exceeds {exp} decimal places for currency {currency.upper()}"
        )
    return int(scaled)


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

