"""Environment-backed settings (no hardcoded production credentials)."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from functools import lru_cache
from urllib.parse import unquote, urlparse
from uuid import UUID

DEFAULT_TENANT_UUID = UUID("00000000-0000-4000-8000-000000000001")

_INSECURE_DEV_SECRETS = frozenset({
    "",
    "changeme",
    "change-me",
    "secret",
    "dev-secret",
    "test-secret",
    "dev-insecure-signing-secret",
    "dev-insecure-jwt-secret",
    "dev-only-change-in-production-signing-secret",
    "dev-only-change-in-production-jwt-secret",
})

_INSECURE_API_KEYS = frozenset({
    "",
    "changeme",
    "change-me",
    "secret",
    "dev-nexus-api-key",
    "aegis-dev-api-key",
    "dev-api-key",
    "test-api-key",
    "dev-only-change-in-production-api-key",
})

_INSECURE_DB_PASSWORDS = frozenset({
    "",
    "aegis",
    "postgres",
    "password",
    "aegis_dev_password",
    "agentpay_dev",
    "changeme",
    "secret",
    "dev",
    "admin",
    "root",
})

_DEFAULT_DEV_SIGNING_SECRET = "dev-insecure-signing-secret"
_DEFAULT_DEV_JWT_SECRET = "dev-insecure-jwt-secret"


def _env_str(*names: str, default: str = "") -> str:
    """Return the first non-empty environment variable among ``names``, or ``default``."""
    for name in names:
        val = os.getenv(name)
        if val is not None and val != "":
            return val
    for name in names:
        if name in os.environ:
            return os.environ[name]
    return default


def _env_int(*names: str, default: int) -> int:
    raw = _env_str(*names, default="")
    return int(raw) if raw else default


def _env_float(*names: str, default: float) -> float:
    raw = _env_str(*names, default="")
    return float(raw) if raw else default


def _env_bool(*names: str, default: bool) -> bool:
    raw = _env_str(*names, default="")
    if not raw:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _env_opt_bool(*names: str) -> bool | None:
    raw = _env_str(*names, default="")
    if not raw:
        return None
    return raw.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class NexusSettings:
    app_env: str = field(default_factory=lambda: os.getenv("APP_ENV", "development"))
    log_level: str = field(default_factory=lambda: os.getenv("LOG_LEVEL", "INFO"))
    database_url: str = field(
        default_factory=lambda: os.getenv(
            "DATABASE_URL",
            "postgresql+psycopg://agentpay:agentpay_dev@localhost:5432/agentpay_nexus",
        )
    )
    signing_secret: str = field(
        default_factory=lambda: _env_str("NEXUS_SIGNING_SECRET", default=_DEFAULT_DEV_SIGNING_SECRET)
    )
    # Never silently alias signing_secret; read JWT_SECRET or NEXUS_JWT_SECRET explicitly.
    jwt_secret: str = field(
        default_factory=lambda: _env_str("JWT_SECRET", "NEXUS_JWT_SECRET", default=_DEFAULT_DEV_JWT_SECRET)
    )
    api_key: str = field(
        default_factory=lambda: _env_str("NEXUS_API_KEY", default="dev-nexus-api-key")
    )
    default_tenant_id: UUID = field(
        default_factory=lambda: UUID(os.getenv("DEFAULT_TENANT_ID", str(DEFAULT_TENANT_UUID)))
    )
    session_ttl_minutes: int = field(
        default_factory=lambda: _env_int("JWT_ACCESS_TTL_MINUTES", "AEGIS_SESSION_TTL_MINUTES", default=480)
    )
    rate_limit_rpm: int = field(
        default_factory=lambda: _env_int("RATE_LIMIT_RPM", "AEGIS_RATE_LIMIT_RPM", default=240)
    )
    evidence_storage_dir: str = field(
        default_factory=lambda: _env_str(
            "EVIDENCE_STORAGE_DIR",
            "AEGIS_EVIDENCE_STORAGE_DIR",
            default="./var/aegis-evidence",
        )
    )
    redis_url: str = field(default_factory=lambda: os.getenv("REDIS_URL", ""))
    storage_backend: str = field(
        default_factory=lambda: os.getenv("AEGIS_STORAGE_BACKEND", "local").strip().lower() or "local"
    )
    s3_bucket: str = field(default_factory=lambda: os.getenv("AEGIS_S3_BUCKET", ""))
    s3_endpoint_url: str = field(default_factory=lambda: os.getenv("AEGIS_S3_ENDPOINT_URL", ""))
    s3_region: str = field(default_factory=lambda: os.getenv("AEGIS_S3_REGION", ""))
    worker_poll_interval_seconds: float = field(
        default_factory=lambda: _env_float("WORKER_POLL_INTERVAL_SECONDS", default=2.0)
    )
    worker_max_attempts: int = field(
        default_factory=lambda: _env_int("WORKER_MAX_ATTEMPTS", default=5)
    )
    worker_max_concurrent_webhooks: int = field(
        default_factory=lambda: _env_int("WORKER_MAX_CONCURRENT_WEBHOOKS", default=10)
    )
    paypal_mode: str = field(default_factory=lambda: os.getenv("PAYPAL_MODE", "sandbox"))
    paypal_base_url: str = field(
        default_factory=lambda: os.getenv("PAYPAL_BASE_URL", "https://api-m.sandbox.paypal.com")
    )
    paypal_client_id: str = field(default_factory=lambda: os.getenv("PAYPAL_CLIENT_ID", ""))
    paypal_client_secret: str = field(default_factory=lambda: os.getenv("PAYPAL_CLIENT_SECRET", ""))
    paypal_webhook_id: str = field(default_factory=lambda: os.getenv("PAYPAL_WEBHOOK_ID", ""))
    paypal_disputes_api_enabled: bool = field(
        default_factory=lambda: _env_bool("PAYPAL_DISPUTES_API_ENABLED", default=False)
    )
    llm_provider: str = field(default_factory=lambda: os.getenv("LLM_PROVIDER", "deterministic"))
    openai_api_key: str = field(default_factory=lambda: os.getenv("OPENAI_API_KEY", ""))
    google_api_key: str = field(default_factory=lambda: os.getenv("GOOGLE_API_KEY", ""))
    anthropic_api_key: str = field(default_factory=lambda: os.getenv("ANTHROPIC_API_KEY", ""))
    stripe_api_key: str = field(default_factory=lambda: os.getenv("STRIPE_API_KEY", ""))
    stripe_webhook_secret: str = field(default_factory=lambda: os.getenv("STRIPE_WEBHOOK_SECRET", ""))
    webhook_legacy_signature_fallback: bool = field(
        default_factory=lambda: _env_bool("WEBHOOK_LEGACY_SIGNATURE_FALLBACK", default=False)
    )
    webhook_require_https: bool | None = field(
        default_factory=lambda: _env_opt_bool("WEBHOOK_REQUIRE_HTTPS", "AEGIS_WEBHOOK_REQUIRE_HTTPS")
    )
    data_residency: str = field(
        default_factory=lambda: os.getenv("AEGIS_DATA_RESIDENCY", "US").strip().upper() or "US"
    )
    email_verification_required: bool = field(
        default_factory=lambda: _env_bool("EMAIL_VERIFICATION_REQUIRED", default=False)
    )
    cors_origins: tuple[str, ...] = field(
        default_factory=lambda: tuple(
            o.strip() for o in os.getenv("CORS_ORIGINS", "http://localhost:3000").split(",") if o.strip()
        )
    )

    def __post_init__(self) -> None:
        if self.webhook_require_https is None:
            object.__setattr__(self, "webhook_require_https", self.is_production_like)

    @property
    def jwt_access_ttl_minutes(self) -> int:
        return self.session_ttl_minutes

    @property
    def aegis_storage_backend(self) -> str:
        return self.storage_backend

    @property
    def aegis_s3_bucket(self) -> str:
        return self.s3_bucket

    @property
    def aegis_s3_endpoint_url(self) -> str:
        return self.s3_endpoint_url

    @property
    def aegis_s3_region(self) -> str:
        return self.s3_region

    @property
    def aegis_data_residency(self) -> str:
        return self.data_residency

    @property
    def paypal_configured(self) -> bool:
        return bool(self.paypal_client_id and self.paypal_client_secret)

    @property
    def is_production_like(self) -> bool:
        return self.app_env.strip().lower() in {"production", "prod", "staging"}

    def validate_security_posture(self) -> None:
        """Fail closed when running in staging/production with weak or default configuration."""
        if self.storage_backend not in {"local", "s3"}:
            raise RuntimeError(f"Unsupported AEGIS_STORAGE_BACKEND '{self.storage_backend}'; expected 'local' or 's3'.")

        if not self.is_production_like:
            return

        if self.signing_secret.strip().lower() in _INSECURE_DEV_SECRETS or len(self.signing_secret.strip()) < 24:
            raise RuntimeError("NEXUS_SIGNING_SECRET must be a strong secret (>=24 chars) in production/staging.")

        if self.jwt_secret.strip().lower() in _INSECURE_DEV_SECRETS or len(self.jwt_secret.strip()) < 24:
            raise RuntimeError("JWT_SECRET / NEXUS_JWT_SECRET must be a strong secret (>=24 chars) in production/staging.")

        if self.jwt_secret == self.signing_secret:
            raise RuntimeError("JWT_SECRET must be distinct from NEXUS_SIGNING_SECRET in production/staging.")

        if self.api_key.strip().lower() in _INSECURE_API_KEYS or len(self.api_key.strip()) < 16:
            raise RuntimeError("NEXUS_API_KEY must be a non-default strong key (>=16 chars) in production/staging.")

        parsed_db = urlparse(self.database_url)
        if parsed_db.scheme and not parsed_db.scheme.startswith("sqlite"):
            db_password = unquote(parsed_db.password or "")
            if db_password.strip().lower() in _INSECURE_DB_PASSWORDS:
                raise RuntimeError("DATABASE_URL must not use an empty or default password in production/staging.")

        if any(origin.strip() == "*" for origin in self.cors_origins):
            raise RuntimeError("CORS_ORIGINS must not contain wildcard '*' in production/staging.")

        if not self.webhook_require_https:
            raise RuntimeError("WEBHOOK_REQUIRE_HTTPS must be enabled in production/staging.")

        if self.paypal_base_url and not self.paypal_base_url.strip().lower().startswith("https://"):
            raise RuntimeError("PAYPAL_BASE_URL must use HTTPS in production/staging.")

        if self.s3_endpoint_url and not self.s3_endpoint_url.strip().lower().startswith("https://"):
            raise RuntimeError("AEGIS_S3_ENDPOINT_URL must use HTTPS in production/staging.")

        if self.storage_backend == "s3" and not self.s3_bucket.strip():
            raise RuntimeError("AEGIS_S3_BUCKET must be configured when AEGIS_STORAGE_BACKEND='s3' in production/staging.")


@lru_cache(maxsize=1)
def get_settings() -> NexusSettings:
    return NexusSettings()
