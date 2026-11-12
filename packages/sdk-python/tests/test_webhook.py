"""Tests for GAP-014 canonical AEGIS webhook signature verification."""

from __future__ import annotations

import hashlib
import hmac
import time

from aegis_sdk.webhook import verify_aegis_signature, verify_webhook_signature


def _sign(t: int, body: str, secret: str) -> str:
    payload = f"{t}.{body}".encode()
    return hmac.new(secret.encode("utf-8"), payload, hashlib.sha256).hexdigest()


def test_canonical_aegis_signature_success() -> None:
    secret = "whsec_live_test_secret_key"
    body = '{"event":"payment.captured","amount_minor":2500}'
    now = int(time.time())
    sig = _sign(now, body, secret)
    header = f"AEGIS-Signature: t={now},v1={sig}"

    # As str body
    assert verify_aegis_signature(body, header, secret) is True
    # As bytes body
    assert verify_aegis_signature(body.encode("utf-8"), header, secret) is True
    # Without AEGIS-Signature prefix
    assert verify_aegis_signature(body, f"t={now},v1={sig}", secret) is True


def test_canonical_aegis_signature_tolerance_expiration() -> None:
    secret = "whsec_test"
    body = '{"event":"passport.revoked"}'
    old_time = int(time.time()) - 400  # 400 seconds ago (> 300 default)
    sig = _sign(old_time, body, secret)
    header = f"t={old_time},v1={sig}"

    # Should fail due to tolerance
    assert verify_aegis_signature(body, header, secret, tolerance_seconds=300) is False

    # Should pass if tolerance is wide enough
    assert verify_aegis_signature(body, header, secret, tolerance_seconds=500) is True


def test_canonical_aegis_signature_tampered_payload() -> None:
    secret = "whsec_test"
    body = '{"event":"payment.approved"}'
    tampered_body = '{"event":"payment.denied"}'
    now = int(time.time())
    sig = _sign(now, body, secret)
    header = f"t={now},v1={sig}"

    assert verify_aegis_signature(tampered_body, header, secret) is False


def test_canonical_aegis_signature_wrong_secret() -> None:
    body = '{"event":"payment.created"}'
    now = int(time.time())
    sig = _sign(now, body, "secret_a")
    header = f"t={now},v1={sig}"

    assert verify_aegis_signature(body, header, "secret_b") is False


def test_canonical_aegis_signature_malformed_headers() -> None:
    secret = "whsec_test"
    body = '{"test": true}'

    # Empty
    assert verify_aegis_signature(body, "", secret) is False
    assert verify_aegis_signature(body, "t=12345", secret) is False
    assert verify_aegis_signature(body, "v1=abcde", secret) is False
    assert verify_aegis_signature(body, "t=invalid_num,v1=abcde", secret) is False
    assert verify_aegis_signature(body, "invalid_header", secret) is False
    assert verify_aegis_signature(body, "t=123,v1=abc", "") is False


def test_legacy_webhook_signature() -> None:
    secret = "whsec_legacy"
    payload = {"action": "DISPUTE_OPENED", "case_id": "123"}
    import json

    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    sig = hmac.new(secret.encode("utf-8"), canonical, hashlib.sha256).hexdigest()

    assert verify_webhook_signature(payload_body=payload, signature_header=f"sha256={sig}", signing_secret=secret) is True
    assert verify_webhook_signature(payload_body=payload, signature_header="sha256=wrong", signing_secret=secret) is False
