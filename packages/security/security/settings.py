"""Environment-backed settings (no hardcoded production credentials)."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from functools import lru_cache
from uuid import UUID


DEFAULT_TENANT_UUID = UUID("00000000-0000-4000-8000-000000000001")


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
        default_factory=lambda: os.getenv("NEXUS_SIGNING_SECRET", "dev-insecure-signing-secret")
    )
    api_key: str = field(
        default_factory=lambda: os.getenv("NEXUS_API_KEY", "dev-nexus-api-key")
    )
    default_tenant_id: UUID = field(
        default_factory=lambda: UUID(os.getenv("DEFAULT_TENANT_ID", str(DEFAULT_TENANT_UUID)))
    )
    paypal_mode: str = field(default_factory=lambda: os.getenv("PAYPAL_MODE", "sandbox"))
    paypal_base_url: str = field(
        default_factory=lambda: os.getenv("PAYPAL_BASE_URL", "https://api-m.sandbox.paypal.com")
    )
    paypal_client_id: str = field(default_factory=lambda: os.getenv("PAYPAL_CLIENT_ID", ""))
    paypal_client_secret: str = field(default_factory=lambda: os.getenv("PAYPAL_CLIENT_SECRET", ""))
    paypal_webhook_id: str = field(default_factory=lambda: os.getenv("PAYPAL_WEBHOOK_ID", ""))
    paypal_disputes_api_enabled: bool = field(
        default_factory=lambda: os.getenv("PAYPAL_DISPUTES_API_ENABLED", "false").lower() == "true"
    )
    llm_provider: str = field(default_factory=lambda: os.getenv("LLM_PROVIDER", "deterministic"))
    openai_api_key: str = field(default_factory=lambda: os.getenv("OPENAI_API_KEY", ""))
    google_api_key: str = field(default_factory=lambda: os.getenv("GOOGLE_API_KEY", ""))
    cors_origins: tuple[str, ...] = field(
        default_factory=lambda: tuple(
            o.strip() for o in os.getenv("CORS_ORIGINS", "http://localhost:3000").split(",") if o.strip()
        )
    )

    @property
    def paypal_configured(self) -> bool:
        return bool(self.paypal_client_id and self.paypal_client_secret)


@lru_cache(maxsize=1)
def get_settings() -> NexusSettings:
    return NexusSettings()
