"""GDPR / DPDPA data-subject erasure, pseudonymization, and PII redaction helpers."""

from __future__ import annotations

import hashlib
import hmac
import secrets
from collections.abc import Iterable
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

from contracts import compute_payload_hash

_DEFAULT_PII_KEYS = frozenset({
    "email",
    "email_address",
    "full_name",
    "name",
    "first_name",
    "last_name",
    "phone",
    "phone_number",
    "address",
    "street",
    "city",
    "postal_code",
    "zip",
    "zip_code",
    "ssn",
    "tax_id",
    "ip",
    "ip_address",
    "user_agent",
    "password",
    "password_hash",
    "totp_secret",
    "mfa_secret",
    "dob",
    "date_of_birth",
})


def pseudonymize_email(
    email: str,
    *,
    salt: str = "",
    domain: str = "erased.aegis.invalid",
) -> str:
    """Deterministically pseudonymize an email address into an RFC 2606 ``.invalid`` placeholder."""
    normalized = email.strip().lower()
    if not normalized:
        raise ValueError("Email must not be empty")
    if salt:
        digest = hmac.new(salt.encode("utf-8"), normalized.encode("utf-8"), hashlib.sha256).hexdigest()[:24]
    else:
        digest = hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:24]
    return f"erased-{digest}@{domain}"


def _redact_all_values(value: Any, replacement: str) -> Any:
    if value is None:
        return None
    if isinstance(value, dict):
        return {k: _redact_all_values(v, replacement) for k, v in value.items()}
    if isinstance(value, list):
        return [_redact_all_values(item, replacement) for item in value]
    return replacement


def _redact_node(value: Any, pii_keys: frozenset[str], replacement: str) -> Any:
    if isinstance(value, dict):
        redacted: dict[str, Any] = {}
        for k, v in value.items():
            if str(k).strip().lower() in pii_keys:
                redacted[k] = _redact_all_values(v, replacement)
            else:
                redacted[k] = _redact_node(v, pii_keys, replacement)
        return redacted
    if isinstance(value, list):
        return [_redact_node(item, pii_keys, replacement) for item in value]
    return value


def redact_pii_dict(
    payload: dict[str, Any],
    *,
    extra_keys: Iterable[str] | None = None,
    replacement: str = "[REDACTED]",
) -> dict[str, Any]:
    """Return a deep copy of ``payload`` with PII keys redacted."""
    keys = _DEFAULT_PII_KEYS | frozenset(k.strip().lower() for k in (extra_keys or ()))
    return _redact_node(payload, keys, replacement)


def generate_crypto_shred_marker(
    subject_id: UUID | str,
    *,
    tenant_id: UUID | str | None = None,
    reason: str = "GDPR_ERASURE",
    now: datetime | None = None,
) -> dict[str, Any]:
    """Generate a tamper-evident crypto-shredding erasure tombstone without retaining PII."""
    marker_id = str(uuid4())
    shredded_at = (now or datetime.now(UTC)).astimezone(UTC).isoformat()
    key_erasure_nonce = secrets.token_hex(16)
    body = {
        "marker_id": marker_id,
        "subject_id": str(subject_id),
        "tenant_id": str(tenant_id) if tenant_id is not None else None,
        "reason": reason,
        "shredded_at": shredded_at,
        "key_erasure_nonce": key_erasure_nonce,
    }
    return {
        **body,
        "digest": compute_payload_hash(body),
    }
