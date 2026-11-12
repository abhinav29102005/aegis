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
