"""Webhook signature verification helpers for inbound and outbound AEGIS events."""

from __future__ import annotations

import hashlib
import hmac
import json
import time
from typing import Any


def verify_aegis_signature(
    raw_body: bytes | str,
    signature_header: str,
    secret: str,
    tolerance_seconds: int = 300,
    current_time: float | None = None,
) -> bool:
    """Verify canonical AEGIS webhook signature header (GAP-014).

    Parses headers formatted as:
        ``AEGIS-Signature: t=<unix_seconds>,v1=<hex_hmac_sha256>``
    or comma-separated key=value pairs:
        ``t=1700000000,v1=9f86d081884c7d659a2feaa0c55ad015a3bf4f1b2b0b822cd15d6c15b0f00a08``

    Computes HMAC-SHA256 over:
        ``f"{t}.{raw_body if isinstance(raw_body, str) else raw_body.decode('utf-8')}"``

    Enforces constant-time comparison and:
        ``abs(now - t) <= tolerance_seconds``
    """
    if not signature_header or not secret:
        return False

    header_clean = signature_header.strip()
    if ":" in header_clean:
        prefix, remainder = header_clean.split(":", 1)
        if prefix.strip().lower() in ("aegis-signature", "x-aegis-signature"):
            header_clean = remainder.strip()

    parts: dict[str, str] = {}
    for segment in header_clean.split(","):
        kv = segment.strip().split("=", 1)
        if len(kv) == 2:
            parts[kv[0].strip()] = kv[1].strip()

    if "t" not in parts or "v1" not in parts:
        return False

    try:
        t = int(parts["t"])
    except (ValueError, TypeError):
        return False

    now = time.time() if current_time is None else current_time
    if abs(now - t) > tolerance_seconds:
        return False

    try:
        body_str = raw_body if isinstance(raw_body, str) else raw_body.decode("utf-8")
    except UnicodeDecodeError:
        return False

    payload_to_sign = f"{t}.{body_str}".encode("utf-8")
    expected_hex = hmac.new(secret.encode("utf-8"), payload_to_sign, hashlib.sha256).hexdigest()

    return hmac.compare_digest(expected_hex, parts["v1"])


def verify_webhook_signature(
    *,
    payload_body: dict[str, Any],
    signature_header: str,
    signing_secret: str,
) -> bool:
    """Verify an outbound AEGIS webhook ``X-AEGIS-Signature`` HMAC-SHA256 header (legacy format)."""
    canonical = json.dumps(payload_body, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    expected_hex = hmac.new(signing_secret.encode("utf-8"), canonical, hashlib.sha256).hexdigest()
    provided = signature_header.removeprefix("sha256=").strip()
    return hmac.compare_digest(expected_hex, provided)
