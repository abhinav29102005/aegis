"""Tests for GAP-006 settings aliases/posture and GAP-008 RBAC/MFA/OIDC."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from security import (
    ROLE_PERMISSIONS,
    AuthenticationError,
    AuthorizationError,
    NexusSettings,
    Permission,
    Role,
    build_otpauth_uri,
    generate_totp_code,
    generate_totp_secret,
    is_privilege_escalation,
    validate_role_assignment,
    verify_oidc_claims,
    verify_totp_code,
)

_STRONG_SIGNING = "prod-signing-secret-at-least-32-chars!"
_STRONG_JWT = "prod-jwt-secret-distinct-at-least-32b!"
_STRONG_API_KEY = "aegis_live_strong_prod_api_key_value"
_STRONG_DB_URL = "postgresql+psycopg://aegis:StrongProdDbPass2026!@db.internal.example:5432/aegis"


def _valid_prod_settings(**overrides: object) -> NexusSettings:
    defaults: dict[str, object] = {
        "app_env": "production",
        "database_url": _STRONG_DB_URL,
        "signing_secret": _STRONG_SIGNING,
        "jwt_secret": _STRONG_JWT,
        "api_key": _STRONG_API_KEY,
        "cors_origins": ("https://app.aegis.example",),
        "webhook_require_https": True,
    }
    defaults.update(overrides)
    return NexusSettings(**defaults)  # type: ignore[arg-type]


def test_settings_env_aliases_and_optional_fields(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("JWT_SECRET", "env-jwt-secret-value-at-least-32-chars")
    monkeypatch.setenv("JWT_ACCESS_TTL_MINUTES", "120")
    monkeypatch.setenv("RATE_LIMIT_RPM", "500")
    monkeypatch.setenv("EVIDENCE_STORAGE_DIR", "/var/lib/aegis/evidence")
    monkeypatch.setenv("REDIS_URL", "redis://redis:6379/0")
    monkeypatch.setenv("AEGIS_STORAGE_BACKEND", "s3")
    monkeypatch.setenv("AEGIS_S3_BUCKET", "aegis-evidence-prod")
    monkeypatch.setenv("AEGIS_S3_ENDPOINT_URL", "https://s3.us-east-1.amazonaws.com")
    monkeypatch.setenv("AEGIS_S3_REGION", "us-east-1")
    monkeypatch.setenv("LLM_PROVIDER", "anthropic")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
    monkeypatch.setenv("STRIPE_API_KEY", "sk_test_123")
    monkeypatch.setenv("STRIPE_WEBHOOK_SECRET", "whsec_stripe")
    monkeypatch.setenv("WEBHOOK_LEGACY_SIGNATURE_FALLBACK", "true")
    monkeypatch.setenv("AEGIS_DATA_RESIDENCY", "eu")
    monkeypatch.setenv("EMAIL_VERIFICATION_REQUIRED", "true")
    monkeypatch.setenv("WORKER_MAX_CONCURRENT_WEBHOOKS", "25")

    cfg = NexusSettings()
    assert cfg.jwt_secret == "env-jwt-secret-value-at-least-32-chars"
    assert cfg.session_ttl_minutes == 120
    assert cfg.jwt_access_ttl_minutes == 120
    assert cfg.rate_limit_rpm == 500
    assert cfg.evidence_storage_dir == "/var/lib/aegis/evidence"
    assert cfg.redis_url == "redis://redis:6379/0"
    assert cfg.storage_backend == "s3"
    assert cfg.s3_bucket == "aegis-evidence-prod"
    assert cfg.s3_endpoint_url == "https://s3.us-east-1.amazonaws.com"
    assert cfg.s3_region == "us-east-1"
    assert cfg.llm_provider == "anthropic"
    assert cfg.anthropic_api_key == "sk-ant-test"
    assert cfg.stripe_api_key == "sk_test_123"
    assert cfg.stripe_webhook_secret == "whsec_stripe"
    assert cfg.webhook_legacy_signature_fallback is True
    assert cfg.data_residency == "EU"
    assert cfg.email_verification_required is True
    assert cfg.worker_max_concurrent_webhooks == 25


def test_settings_legacy_aegis_nexus_aliases(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("JWT_SECRET", raising=False)
    monkeypatch.delenv("JWT_ACCESS_TTL_MINUTES", raising=False)
    monkeypatch.delenv("RATE_LIMIT_RPM", raising=False)
    monkeypatch.delenv("EVIDENCE_STORAGE_DIR", raising=False)

    monkeypatch.setenv("NEXUS_SIGNING_SECRET", "only-signing-secret-32-chars-minimum")
    monkeypatch.setenv("NEXUS_JWT_SECRET", "legacy-nexus-jwt-secret-32-chars-min")
    monkeypatch.setenv("AEGIS_SESSION_TTL_MINUTES", "90")
    monkeypatch.setenv("AEGIS_RATE_LIMIT_RPM", "360")
    monkeypatch.setenv("AEGIS_EVIDENCE_STORAGE_DIR", "/tmp/aegis-legacy-ev")

    cfg = NexusSettings()
    assert cfg.jwt_secret == "legacy-nexus-jwt-secret-32-chars-min"
    assert cfg.session_ttl_minutes == 90
    assert cfg.rate_limit_rpm == 360
    assert cfg.evidence_storage_dir == "/tmp/aegis-legacy-ev"


def test_jwt_secret_never_aliases_signing_secret(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("JWT_SECRET", raising=False)
    monkeypatch.delenv("NEXUS_JWT_SECRET", raising=False)
    monkeypatch.setenv("APP_ENV", "staging")
    monkeypatch.setenv("NEXUS_SIGNING_SECRET", _STRONG_SIGNING)

    cfg = NexusSettings()
    assert cfg.jwt_secret != cfg.signing_secret
    with pytest.raises(RuntimeError, match="JWT_SECRET"):
        cfg.validate_security_posture()


@pytest.mark.parametrize("env_name", ["staging", "production"])
def test_validate_security_posture_rejects_weak_configs(env_name: str) -> None:
    _valid_prod_settings(app_env=env_name).validate_security_posture()

    # Default or weak API keys
    for bad_key in ("", "aegis-dev-api-key", "dev-api-key", "dev-nexus-api-key", "changeme"):
        with pytest.raises(RuntimeError, match="NEXUS_API_KEY"):
            _valid_prod_settings(app_env=env_name, api_key=bad_key).validate_security_posture()

    # Insecure signing secret
    with pytest.raises(RuntimeError, match="NEXUS_SIGNING_SECRET"):
        _valid_prod_settings(app_env=env_name, signing_secret="dev-only-change-in-production-signing-secret").validate_security_posture()

    # Insecure JWT secret or equal to signing secret
    with pytest.raises(RuntimeError, match="JWT_SECRET"):
        _valid_prod_settings(app_env=env_name, jwt_secret="dev-only-change-in-production-jwt-secret").validate_security_posture()
    with pytest.raises(RuntimeError, match="distinct"):
        _valid_prod_settings(app_env=env_name, jwt_secret=_STRONG_SIGNING).validate_security_posture()

    # Default database passwords
    for bad_pw in ("aegis", "postgres", "password", "aegis_dev_password", "agentpay_dev"):
        bad_url = f"postgresql+psycopg://aegis:{bad_pw}@db.example:5432/aegis"
        with pytest.raises(RuntimeError, match="DATABASE_URL"):
            _valid_prod_settings(app_env=env_name, database_url=bad_url).validate_security_posture()

    # Wildcard CORS
    with pytest.raises(RuntimeError, match="CORS_ORIGINS"):
        _valid_prod_settings(app_env=env_name, cors_origins=("*",)).validate_security_posture()

    # Disabled HTTPS webhook requirement or non-HTTPS endpoint URLs
    with pytest.raises(RuntimeError, match="WEBHOOK_REQUIRE_HTTPS"):
        _valid_prod_settings(app_env=env_name, webhook_require_https=False).validate_security_posture()
    with pytest.raises(RuntimeError, match="PAYPAL_BASE_URL"):
        _valid_prod_settings(app_env=env_name, paypal_base_url="http://api-m.sandbox.paypal.com").validate_security_posture()
    with pytest.raises(RuntimeError, match="AEGIS_S3_ENDPOINT_URL"):
        _valid_prod_settings(app_env=env_name, s3_endpoint_url="http://minio.local:9000").validate_security_posture()


def test_rbac_permissions_and_role_assignment_escalation() -> None:
    assert Permission.BILLING_MANAGE in ROLE_PERMISSIONS[Role.OWNER]
    assert Permission.PRIVACY_MANAGE in ROLE_PERMISSIONS[Role.OWNER]
    assert Permission.BILLING_MANAGE in ROLE_PERMISSIONS[Role.ADMIN]
    assert Permission.PRIVACY_MANAGE in ROLE_PERMISSIONS[Role.ADMIN]
    assert Permission.ORG_MANAGE not in ROLE_PERMISSIONS[Role.ADMIN]
    assert Permission.BILLING_MANAGE not in ROLE_PERMISSIONS[Role.OPERATOR]
    assert Permission.PRIVACY_MANAGE not in ROLE_PERMISSIONS[Role.OPERATOR]

    assert is_privilege_escalation(Role.ADMIN, Role.OWNER) is True
    assert is_privilege_escalation(Role.OPERATOR, Role.ADMIN) is True
    assert is_privilege_escalation(Role.OWNER, Role.OWNER) is False
    assert is_privilege_escalation(Role.ADMIN, Role.OPERATOR) is False

    assert validate_role_assignment(Role.OWNER, Role.OWNER) == Role.OWNER
    assert validate_role_assignment(Role.ADMIN, Role.OPERATOR) == Role.OPERATOR
    assert validate_role_assignment(Role.ADMIN, Role.ADMIN) == Role.ADMIN

    with pytest.raises(AuthorizationError):
        validate_role_assignment(Role.ADMIN, Role.OWNER)
    with pytest.raises(AuthorizationError):
        validate_role_assignment(Role.OPERATOR, Role.ADMIN)


def test_rbac_exhaustive_matrix_all_roles_and_invariants() -> None:
    from security.auth import _READ_PERMISSIONS

    # Exactly 6 platform roles and 23 fine-grained permissions
    assert len(Role) == 6
    assert len(Permission) == 23
    assert set(ROLE_PERMISSIONS.keys()) == set(Role)

    # 1. OWNER has full permission set
    assert ROLE_PERMISSIONS[Role.OWNER] == frozenset(Permission)
    assert len(ROLE_PERMISSIONS[Role.OWNER]) == 23

    # 2. ADMIN has all permissions except ORG_MANAGE
    assert ROLE_PERMISSIONS[Role.ADMIN] == frozenset(Permission) - frozenset({Permission.ORG_MANAGE})
    assert len(ROLE_PERMISSIONS[Role.ADMIN]) == 22

    # Invariant: Only OWNER has ORG_MANAGE
    for r in Role:
        if r != Role.OWNER:
            assert Permission.ORG_MANAGE not in ROLE_PERMISSIONS[r], f"Role {r} must not have org:manage"

    # 3. OPERATOR has read permissions + operational write/decision permissions (16 total)
    assert len(ROLE_PERMISSIONS[Role.OPERATOR]) == 16
    assert _READ_PERMISSIONS.issubset(ROLE_PERMISSIONS[Role.OPERATOR])
    assert Permission.APPROVALS_DECIDE in ROLE_PERMISSIONS[Role.OPERATOR]
    assert Permission.DISPUTES_APPROVE in ROLE_PERMISSIONS[Role.OPERATOR]
    for prohibited in (
        Permission.ORG_MANAGE,
        Permission.MEMBERS_MANAGE,
        Permission.KEYS_MANAGE,
        Permission.WEBHOOKS_MANAGE,
        Permission.WORKER_MANAGE,
        Permission.BILLING_MANAGE,
        Permission.PRIVACY_MANAGE,
    ):
        assert prohibited not in ROLE_PERMISSIONS[Role.OPERATOR], f"OPERATOR must not have {prohibited}"

    # 4. AUDITOR has read permissions + GHOSTPAY_SIMULATE (7 total), zero write/approval
    assert len(ROLE_PERMISSIONS[Role.AUDITOR]) == 7
    assert ROLE_PERMISSIONS[Role.AUDITOR] == _READ_PERMISSIONS | frozenset({Permission.GHOSTPAY_SIMULATE})
    for forbidden in (
        Permission.APPROVALS_DECIDE,
        Permission.DISPUTES_APPROVE,
        Permission.DISPUTES_WRITE,
        Permission.DISPUTES_SUBMIT,
        Permission.AGENTS_WRITE,
        Permission.PASSPORTS_WRITE,
        Permission.PROPOSALS_WRITE,
        Permission.PAYMENTS_CHECKOUT,
        Permission.PAYMENTS_CAPTURE,
    ):
        assert forbidden not in ROLE_PERMISSIONS[Role.AUDITOR], f"AUDITOR must not have {forbidden}"

    # 5. AGENT_SERVICE has purchase/checkout perms (6 total); strictly forbidden from approving or org administration
    assert len(ROLE_PERMISSIONS[Role.AGENT_SERVICE]) == 6
    assert ROLE_PERMISSIONS[Role.AGENT_SERVICE] == frozenset({
        Permission.AGENTS_READ,
        Permission.PASSPORTS_READ,
        Permission.PROPOSALS_WRITE,
        Permission.PAYMENTS_READ,
        Permission.PAYMENTS_CHECKOUT,
        Permission.PAYMENTS_CAPTURE,
    })
    for forbidden in (
        Permission.APPROVALS_DECIDE,
        Permission.DISPUTES_APPROVE,
        Permission.DISPUTES_WRITE,
        Permission.DISPUTES_SUBMIT,
        Permission.DISPUTES_READ,
        Permission.GHOSTPAY_READ,
        Permission.GHOSTPAY_SIMULATE,
        Permission.AUDIT_READ,
        Permission.AGENTS_WRITE,
        Permission.PASSPORTS_WRITE,
        Permission.ORG_MANAGE,
        Permission.MEMBERS_MANAGE,
        Permission.KEYS_MANAGE,
        Permission.BILLING_MANAGE,
        Permission.PRIVACY_MANAGE,
    ):
        assert forbidden not in ROLE_PERMISSIONS[Role.AGENT_SERVICE], f"AGENT_SERVICE must not have {forbidden}"

    # 6. VIEWER has exactly read permissions (6 total), zero write/simulate
    assert len(ROLE_PERMISSIONS[Role.VIEWER]) == 6
    assert ROLE_PERMISSIONS[Role.VIEWER] == _READ_PERMISSIONS


def test_resolve_permissions_scoping_and_edge_cases() -> None:
    from security import resolve_permissions
    from security.auth import _READ_PERMISSIONS

    # Enum and string roles resolve identically
    assert resolve_permissions(Role.OWNER) == resolve_permissions("OWNER")
    assert resolve_permissions(Role.VIEWER) == resolve_permissions("VIEWER")

    # None and empty scopes return base permissions
    assert resolve_permissions(Role.OPERATOR, None) == ROLE_PERMISSIONS[Role.OPERATOR]
    assert resolve_permissions(Role.OPERATOR, []) == ROLE_PERMISSIONS[Role.OPERATOR]

    # Wildcard "*" preserves base permissions without escalating
    assert resolve_permissions(Role.VIEWER, ["*"]) == _READ_PERMISSIONS
    assert resolve_permissions(Role.ADMIN, ["*"]) == ROLE_PERMISSIONS[Role.ADMIN]
    assert Permission.ORG_MANAGE not in resolve_permissions(Role.ADMIN, ["*"])

    # Narrowing down to valid subset
    scoped = resolve_permissions(Role.OPERATOR, ["payments:read", "payments:checkout"])
    assert scoped == frozenset({Permission.PAYMENTS_READ, Permission.PAYMENTS_CHECKOUT})

    # Scope escalation rejection: requesting permissions not in role base set yields empty/filtered
    escalate_attempt = resolve_permissions(Role.VIEWER, ["org:manage", "payments:capture"])
    assert escalate_attempt == frozenset()

    agent_escalate = resolve_permissions(Role.AGENT_SERVICE, ["approvals:decide", "payments:read"])
    assert agent_escalate == frozenset({Permission.PAYMENTS_READ})

    # Unknown or malformed scope strings are ignored gracefully
    mixed = resolve_permissions(Role.AUDITOR, ["audit:read", "unknown:permission", "", "random_str"])
    assert mixed == frozenset({Permission.AUDIT_READ})

    # Invalid role string raises ValueError
    with pytest.raises(ValueError):
        resolve_permissions("INVALID_ROLE")


def test_all_pairwise_role_escalations_and_assignments() -> None:
    from security.auth import _ROLE_RANK

    all_roles = list(Role)
    # Strictly monotonic rank ordering across all 6 roles
    assert _ROLE_RANK[Role.VIEWER] < _ROLE_RANK[Role.AGENT_SERVICE]
    assert _ROLE_RANK[Role.AGENT_SERVICE] < _ROLE_RANK[Role.AUDITOR]
    assert _ROLE_RANK[Role.AUDITOR] < _ROLE_RANK[Role.OPERATOR]
    assert _ROLE_RANK[Role.OPERATOR] < _ROLE_RANK[Role.ADMIN]
    assert _ROLE_RANK[Role.ADMIN] < _ROLE_RANK[Role.OWNER]

    # Exhaustive 6x6 pairwise escalation and assignment verification (36 combinations)
    for actor in all_roles:
        for target in all_roles:
            expected_escalation = _ROLE_RANK[target] > _ROLE_RANK[actor]
            assert is_privilege_escalation(actor, target) is expected_escalation
            assert is_privilege_escalation(actor.value, target.value) is expected_escalation

            is_allowed = (not expected_escalation) and (target != Role.OWNER or actor == Role.OWNER)

            if is_allowed:
                assert validate_role_assignment(actor, target) == target
                assert validate_role_assignment(actor.value, target.value) == target
            else:
                with pytest.raises(AuthorizationError):
                    validate_role_assignment(actor, target)
                with pytest.raises(AuthorizationError):
                    validate_role_assignment(actor.value, target.value)


def test_auth_context_permission_enforcement_and_immutability() -> None:
    from dataclasses import FrozenInstanceError
    from uuid import uuid4

    from security import AuthContext, resolve_permissions

    for role in Role:
        ctx = AuthContext(
            tenant_id=uuid4(),
            actor_type="USER",
            actor_id=f"user-{role.value.lower()}",
            role=role,
            permissions=resolve_permissions(role),
        )

        # Frozen immutability
        with pytest.raises(FrozenInstanceError):
            ctx.role = Role.OWNER  # type: ignore[misc]

        with pytest.raises(FrozenInstanceError):
            ctx.permissions = frozenset()  # type: ignore[misc]

        # Check all 23 permissions
        for perm in Permission:
            expected_allowed = perm in ROLE_PERMISSIONS[role]
            assert ctx.has_permission(perm) is expected_allowed

            if expected_allowed:
                ctx.require_permission(perm)  # Does not raise
            else:
                with pytest.raises(AuthorizationError) as exc_info:
                    ctx.require_permission(perm)
                assert f"Role {role.value} lacks required permission '{perm.value}'" in str(exc_info.value)


def test_totp_mfa_lifecycle() -> None:
    secret = generate_totp_secret()
    assert len(secret) >= 32
    uri = build_otpauth_uri(secret, "alice@aegis.example", issuer="AEGIS")
    assert uri.startswith("otpauth://totp/AEGIS:alice%40aegis.example?")
    assert f"secret={secret}" in uri

    ts = datetime(2026, 11, 12, 12, 0, 0, tzinfo=UTC)
    code = generate_totp_code(secret, now=ts)
    assert len(code) == 6
    assert verify_totp_code(secret, code, window=1, now=ts) is True
    # Adjacent 30-second window allowed when window=1
    assert verify_totp_code(secret, code, window=1, now=ts + timedelta(seconds=30)) is True
    # Outside window rejected
    assert verify_totp_code(secret, code, window=1, now=ts + timedelta(seconds=90)) is False
    # Wrong / malformed code rejected
    assert verify_totp_code(secret, "000000" if code != "000000" else "111111", now=ts) is False
    assert verify_totp_code(secret, "abc", now=ts) is False


def test_verify_oidc_claims() -> None:
    now = datetime(2026, 11, 12, 12, 0, 0, tzinfo=UTC)
    iat = int(now.timestamp())
    valid_claims = {
        "sub": "user-123",
        "iss": "https://accounts.example.com",
        "aud": "aegis-client-id",
        "iat": iat,
        "exp": iat + 300,
        "nonce": "nonce-xyz",
    }
    verified = verify_oidc_claims(
        valid_claims,
        expected_issuer="https://accounts.example.com",
        expected_audience="aegis-client-id",
        expected_nonce="nonce-xyz",
        now=now,
    )
    assert verified["sub"] == "user-123"

    # Multi-audience list
    multi_aud = {**valid_claims, "aud": ["other-client", "aegis-client-id"], "azp": "aegis-client-id"}
    assert verify_oidc_claims(
        multi_aud,
        expected_issuer="https://accounts.example.com",
        expected_audience="aegis-client-id",
        now=now,
    )["sub"] == "user-123"

    # Bad issuer
    with pytest.raises(AuthenticationError, match="issuer"):
        verify_oidc_claims(
            {**valid_claims, "iss": "https://evil.example.com"},
            expected_issuer="https://accounts.example.com",
            expected_audience="aegis-client-id",
            now=now,
        )

    # Bad audience
    with pytest.raises(AuthenticationError, match="audience"):
        verify_oidc_claims(
            {**valid_claims, "aud": "wrong-client"},
            expected_issuer="https://accounts.example.com",
            expected_audience="aegis-client-id",
            now=now,
        )

    # Expired
    with pytest.raises(AuthenticationError, match="expired"):
        verify_oidc_claims(
            valid_claims,
            expected_issuer="https://accounts.example.com",
            expected_audience="aegis-client-id",
            now=now + timedelta(minutes=10),
        )

    # Bad nonce
    with pytest.raises(AuthenticationError, match="nonce"):
        verify_oidc_claims(
            valid_claims,
            expected_issuer="https://accounts.example.com",
            expected_audience="aegis-client-id",
            expected_nonce="different-nonce",
            now=now,
        )
