"""Tests for nexus-security primitives."""

from uuid import uuid4

import pytest
from contracts.fixtures import build_authorized_39_purchase_fixture
from security import (
    TenantIsolationError,
    assert_same_tenant,
    sign_hmac_sha256,
    verify_financial_event_chain,
    verify_hmac_sha256,
)


def test_hmac_sign_and_verify() -> None:
    secret = "test-secret-key"
    payload = {"intent_id": str(uuid4()), "amount_minor": 3900}
    sig = sign_hmac_sha256(payload, secret)
    assert verify_hmac_sha256(payload, sig, secret)
    assert not verify_hmac_sha256({"intent_id": payload["intent_id"], "amount_minor": 4000}, sig, secret)


def test_tenant_isolation_guard() -> None:
    t1 = uuid4()
    t2 = uuid4()
    assert_same_tenant(t1, t1, "payment_intent")
    with pytest.raises(TenantIsolationError) as exc_info:
        assert_same_tenant(t1, t2, "payment_intent")
    msg = str(exc_info.value)
    assert "Cross-tenant access denied" in msg
    assert str(t1) not in msg
    assert str(t2) not in msg
    assert exc_info.value.expected_tenant_id == t1
    assert exc_info.value.actual_tenant_id == t2


def test_financial_event_chain_verification_and_tamper_detection() -> None:
    fx = build_authorized_39_purchase_fixture()
    ok, errors = verify_financial_event_chain(fx["events"])
    assert ok and errors == []

    # Tamper with an event payload without updating hash
    tampered = fx["events"][1].model_copy(update={"payload": {"outcome": "DENY"}})
    ok_bad, bad_errors = verify_financial_event_chain([fx["events"][0], tampered, fx["events"][2]])
    assert not ok_bad
    assert len(bad_errors) >= 1


def test_password_hashing_and_api_key_generation() -> None:
    from security import DEFAULT_PBKDF2_ITERATIONS, generate_api_key, hash_api_key, hash_password, verify_password

    assert DEFAULT_PBKDF2_ITERATIONS == 600_000

    encoded = hash_password("StrongPass!2026", iterations=10_000)
    assert verify_password("StrongPass!2026", encoded)
    assert not verify_password("WrongPass", encoded)
    assert not verify_password("StrongPass!2026", "corrupt")

    plaintext, prefix, _ = generate_api_key("development")
    assert plaintext.startswith("aegis_test_")
    assert plaintext.startswith(prefix)
    digest1 = hash_api_key(plaintext, "pepper-1")
    digest2 = hash_api_key(plaintext, "pepper-2")
    assert digest1 != digest2
    assert digest1 != plaintext


def test_pbkdf2_iterations_salt_entropy_and_edge_cases() -> None:
    from security import DEFAULT_PBKDF2_ITERATIONS, hash_password, verify_password

    # 1. Iterations: verify default is 600k (OWASP recommendation for PBKDF2-HMAC-SHA256)
    assert DEFAULT_PBKDF2_ITERATIONS == 600_000

    # 2. Salt entropy: 128 bits (16 bytes = 32 hex chars), generated with CSPRNG per invocation
    hash1 = hash_password("SecurePassword!123", iterations=1_000)
    hash2 = hash_password("SecurePassword!123", iterations=1_000)
    assert hash1 != hash2  # Unique salt per hash

    parts1 = hash1.split("$")
    assert len(parts1) == 4
    scheme, iter_str, salt_hex, digest_hex = parts1
    assert scheme == "pbkdf2_sha256"
    assert iter_str == "1000"
    assert len(salt_hex) == 32  # 16 bytes = 128-bit entropy
    assert len(digest_hex) == 64  # 32 bytes = SHA-256 digest
    assert bytes.fromhex(salt_hex) != bytes.fromhex(hash2.split("$")[2])

    # 3. Input validation invariants for hash_password
    with pytest.raises(ValueError, match="at least 8 characters"):
        hash_password("short")
    with pytest.raises(TypeError, match="Password must be a string"):
        hash_password(None)  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="exceeds maximum"):
        hash_password("A" * 4097)
    with pytest.raises(ValueError, match="positive integer"):
        hash_password("SecurePassword!123", iterations=0)
    with pytest.raises(ValueError, match="positive integer"):
        hash_password("SecurePassword!123", iterations=-100)

    # 4. verify_password edge cases & resilience
    valid_hash = hash_password("SecurePassword!123", iterations=1_000)
    assert verify_password("SecurePassword!123", valid_hash) is True
    assert verify_password("WrongPassword!123", valid_hash) is False

    # None and non-string types must fail gracefully (no AttributeError / TypeError)
    assert verify_password(None, valid_hash) is False  # type: ignore[arg-type]
    assert verify_password("SecurePassword!123", None) is False  # type: ignore[arg-type]
    assert verify_password(12345, valid_hash) is False  # type: ignore[arg-type]

    # Empty, corrupted, or erased hashes
    assert verify_password("SecurePassword!123", "") is False
    assert verify_password("SecurePassword!123", "ERASED") is False
    assert verify_password("SecurePassword!123", "corrupt_hash_string") is False
    assert verify_password("SecurePassword!123", "argon2$600000$deadbeef$feedface") is False
    assert verify_password("SecurePassword!123", "pbkdf2_sha256$1000$short$1234") is False

    # Iteration boundaries (negative, 0, or excessive for DoS protection)
    assert verify_password("SecurePassword!123", f"pbkdf2_sha256$-1${salt_hex}${digest_hex}") is False
    assert verify_password("SecurePassword!123", f"pbkdf2_sha256$0${salt_hex}${digest_hex}") is False
    assert verify_password("SecurePassword!123", f"pbkdf2_sha256$10000000${salt_hex}${digest_hex}") is False

    # Low-entropy salt rejection (< 16 bytes = 128 bits)
    low_entropy_salt = "00" * 8  # only 8 bytes / 64 bits
    assert verify_password("SecurePassword!123", f"pbkdf2_sha256$1000${low_entropy_salt}${digest_hex}") is False

    # Truncated or malformed digest rejection (!= 32 bytes)
    truncated_digest = "00" * 16  # only 16 bytes instead of 32 bytes
    assert verify_password("SecurePassword!123", f"pbkdf2_sha256$1000${salt_hex}${truncated_digest}") is False


def test_jwt_token_verification_expiry_and_rbac() -> None:
    from datetime import UTC, datetime, timedelta

    from security import (
        AuthContext,
        AuthenticationError,
        AuthorizationError,
        NexusSettings,
        Permission,
        Role,
        create_access_token,
        resolve_permissions,
        verify_access_token,
    )

    uid = uuid4()
    tid = uuid4()
    now = datetime(2026, 11, 12, 12, 0, tzinfo=UTC)
    token = create_access_token(
        user_id=uid,
        tenant_id=tid,
        role=Role.OPERATOR,
        secret="unit-test-secret-value-at-least-24",
        email="ops@aegis.example",
        ttl_minutes=15,
        now=now,
    )
    claims = verify_access_token(token, secret="unit-test-secret-value-at-least-24", now=now)
    assert claims.sub == uid
    assert claims.tenant_id == tid
    assert claims.role == Role.OPERATOR

    with pytest.raises(AuthenticationError):
        verify_access_token(token, secret="wrong-secret", now=now)
    with pytest.raises(AuthenticationError):
        verify_access_token(token, secret="unit-test-secret-value-at-least-24", now=now + timedelta(minutes=20))

    agent_perms = resolve_permissions(Role.AGENT_SERVICE)
    assert Permission.PROPOSALS_WRITE in agent_perms
    assert Permission.APPROVALS_DECIDE not in agent_perms

    ctx = AuthContext(tenant_id=tid, actor_type="SERVICE_ACCOUNT", actor_id="sa-1", role=Role.AGENT_SERVICE, permissions=agent_perms)
    with pytest.raises(AuthorizationError):
        ctx.require_permission(Permission.APPROVALS_DECIDE)

    prod = NexusSettings(app_env="production", signing_secret="dev-insecure-signing-secret")
    with pytest.raises(RuntimeError):
        prod.validate_security_posture()

