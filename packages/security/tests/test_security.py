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
    with pytest.raises(TenantIsolationError):
        assert_same_tenant(t1, t2, "payment_intent")


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
    from security import generate_api_key, hash_api_key, hash_password, verify_password

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

