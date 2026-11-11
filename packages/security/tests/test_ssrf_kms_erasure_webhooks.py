"""Tests for GAP-003 SSRF, GAP-014 replay-protected webhooks, Horizon 4 KMS, and GAP-024 erasure."""

from __future__ import annotations

import socket
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from security import (
    EnvelopeCipher,
    KMSError,
    LocalKMSProvider,
    SSRFValidationError,
    decrypt_secret,
    encrypt_secret,
    format_aegis_signature,
    generate_crypto_shred_marker,
    is_public_ip,
    pseudonymize_email,
    redact_pii_dict,
    sign_webhook_payload,
    unwrap_data_key,
    validate_webhook_url,
    verify_aegis_signature,
    wrap_data_key,
)


def test_is_public_ip_blocks_private_reserved_and_mapped_ranges() -> None:
    assert is_public_ip("93.184.216.34") is True
    assert is_public_ip("2606:4700:4700::1111") is True

    blocked = [
        "127.0.0.1",
        "127.255.0.1",
        "::1",
        "::ffff:127.0.0.1",
        "10.0.0.1",
        "172.16.0.1",
        "172.31.255.254",
        "192.168.1.1",
        "fc00::1",
        "fd12:3456::1",
        "169.254.169.254",
        "fe80::1",
        "100.64.0.1",
        "100.127.255.254",
        "224.0.0.1",
        "ff02::1",
        "0.0.0.0",
        "0.1.2.3",
        "::",
        "not-an-ip",
    ]
    for ip in blocked:
        assert is_public_ip(ip) is False, f"Expected {ip} to be rejected"


def test_validate_webhook_url_ssrf_controls(monkeypatch: pytest.MonkeyPatch) -> None:
    # Public IP literal passes
    assert validate_webhook_url("https://93.184.216.34/webhook", require_https=True) == ["93.184.216.34"]

    # Scheme enforcement
    with pytest.raises(SSRFValidationError, match="HTTPS"):
        validate_webhook_url("http://93.184.216.34/webhook", require_https=True)
    with pytest.raises(SSRFValidationError, match="scheme"):
        validate_webhook_url("ftp://93.184.216.34/webhook")

    # Userinfo credentials rejected
    with pytest.raises(SSRFValidationError, match="userinfo"):
        validate_webhook_url("https://user:pass@93.184.216.34/webhook", resolve_dns=False)

    # Blocked hostnames & suffixes
    for bad_url in (
        "https://localhost/hook",
        "https://api.internal/hook",
        "https://printer.local/hook",
        "https://metadata.google.internal/computeMetadata/v1/",
        "https://127.0.0.1/hook",
        "https://[::ffff:127.0.0.1]/hook",
        "https://169.254.169.254/latest/meta-data",
        "https://100.64.0.5/hook",
        "https://2130706433/hook",
    ):
        with pytest.raises(SSRFValidationError):
            validate_webhook_url(bad_url, resolve_dns=False)

    # DNS resolution returning public IP passes
    def fake_getaddrinfo_public(host: str, port: int, type: int = 0):
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", port))]

    monkeypatch.setattr(socket, "getaddrinfo", fake_getaddrinfo_public)
    assert validate_webhook_url("https://hooks.customer.example/events", require_https=True) == ["93.184.216.34"]

    # DNS rebinding / split-horizon returning private IP fails closed
    def fake_getaddrinfo_rebinding(host: str, port: int, type: int = 0):
        return [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", port)),
            (socket.AF_INET6, socket.SOCK_STREAM, 6, "", ("::ffff:10.0.0.5", port, 0, 0)),
        ]

    monkeypatch.setattr(socket, "getaddrinfo", fake_getaddrinfo_rebinding)
    with pytest.raises(SSRFValidationError, match="non-public"):
        validate_webhook_url("https://rebind.customer.example/events", require_https=True)


def test_replay_protected_aegis_webhook_signature() -> None:
    secret = "whsec_test_secret_123"
    body = b'{"event":"payment.captured","amount_minor":3900}'
    ts = 1_760_000_000

    signed_ts, sig = sign_webhook_payload(secret, body, timestamp=ts)
    assert signed_ts == ts

    header = format_aegis_signature(secret, body, timestamp=ts)
    assert header == f"t={ts},v1={sig}"

    assert verify_aegis_signature(secret, body, header, tolerance_seconds=300, now_ts=ts + 60) is True
    assert verify_aegis_signature(secret, body.decode("utf-8"), header, tolerance_seconds=300, now_ts=ts + 60) is True

    # Replay outside tolerance window rejected
    assert verify_aegis_signature(secret, body, header, tolerance_seconds=300, now_ts=ts + 301) is False
    # Tampered body rejected
    assert verify_aegis_signature(secret, b'{"event":"payment.captured","amount_minor":9999}', header, now_ts=ts) is False
    # Wrong secret rejected
    assert verify_aegis_signature("wrong-secret", body, header, now_ts=ts) is False
    # Malformed headers rejected
    assert verify_aegis_signature(secret, body, "v1=abc", now_ts=ts) is False
    assert verify_aegis_signature(secret, body, f"t={ts}", now_ts=ts) is False


def test_kms_envelope_encryption_and_key_rotation() -> None:
    master = "master-kms-secret-value-for-tests"
    ctx = {"tenant_id": str(uuid4()), "purpose": "webhook_secret"}

    raw_dek = b"0123456789abcdef0123456789abcdef"
    wrapped = wrap_data_key(raw_dek, master_secret=master, key_id="kek-v1", context=ctx)
    assert unwrap_data_key(wrapped, master_secret=master, key_id="kek-v1", context=ctx) == raw_dek

    token = encrypt_secret("whsec_super_sensitive_value", master_secret=master, key_id="kek-v1", context=ctx)
    assert "whsec_super_sensitive_value" not in token
    assert decrypt_secret(token, master_secret=master, key_id="kek-v1", context=ctx) == "whsec_super_sensitive_value"

    # AAD context mismatch fails closed
    with pytest.raises(KMSError):
        decrypt_secret(token, master_secret=master, key_id="kek-v1", context={"tenant_id": "other"})

    # Tampering fails closed
    tampered = token[:-4] + ("AAAA" if not token.endswith("AAAA") else "BBBB")
    with pytest.raises(KMSError):
        decrypt_secret(tampered, master_secret=master, key_id="kek-v1", context=ctx)

    # Key rotation: old ciphertexts decrypt under rotated keyring while new wraps use kek-v2
    v1_provider = LocalKMSProvider(master_secret="old-kek-secret", key_id="kek-v1")
    v1_cipher = EnvelopeCipher(v1_provider)
    old_token = v1_cipher.encrypt_secret("legacy-secret", context=ctx)

    rotated_provider = LocalKMSProvider(
        key_id="kek-v2",
        keyring={"kek-v1": "old-kek-secret", "kek-v2": "new-kek-secret"},
    )
    rotated_cipher = EnvelopeCipher(rotated_provider)
    assert rotated_cipher.decrypt_secret(old_token, context=ctx) == "legacy-secret"
    new_token = rotated_cipher.encrypt_secret("new-secret", context=ctx)
    assert rotated_cipher.decrypt_secret(new_token, context=ctx) == "new-secret"


def test_erasure_pseudonymization_redaction_and_crypto_shred_marker() -> None:
    pseudo1 = pseudonymize_email("  Alice@Example.com ", salt="tenant-salt-1")
    pseudo2 = pseudonymize_email("alice@example.com", salt="tenant-salt-1")
    pseudo3 = pseudonymize_email("alice@example.com", salt="tenant-salt-2")
    assert pseudo1 == pseudo2
    assert pseudo1 != pseudo3
    assert pseudo1.endswith("@erased.aegis.invalid")
    assert "alice" not in pseudo1

    original = {
        "order_id": "ord_123",
        "email": "alice@example.com",
        "customer": {
            "full_name": "Alice Doe",
            "address": {"street": "123 Main St", "city": "NYC"},
            "custom_token": "secret-tok",
        },
        "events": [{"ip_address": "203.0.113.5", "status": "ok"}],
    }
    redacted = redact_pii_dict(original, extra_keys={"custom_token"})
    assert original["email"] == "alice@example.com"  # non-mutating
    assert redacted["order_id"] == "ord_123"
    assert redacted["email"] == "[REDACTED]"
    assert redacted["customer"]["full_name"] == "[REDACTED]"
    assert redacted["customer"]["address"] == {"street": "[REDACTED]", "city": "[REDACTED]"}
    assert redacted["customer"]["custom_token"] == "[REDACTED]"
    assert redacted["events"] == [{"ip_address": "[REDACTED]", "status": "ok"}]

    uid = uuid4()
    tid = uuid4()
    marker = generate_crypto_shred_marker(
        uid,
        tenant_id=tid,
        reason="DPDPA_ERASURE",
        now=datetime(2026, 11, 12, 12, 0, tzinfo=UTC),
    )
    assert marker["subject_id"] == str(uid)
    assert marker["tenant_id"] == str(tid)
    assert marker["reason"] == "DPDPA_ERASURE"
    assert len(marker["key_erasure_nonce"]) == 32
    assert len(marker["digest"]) == 64
