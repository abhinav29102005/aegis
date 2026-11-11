"""Shared security primitives for AgentPay Nexus."""

from security.auth import (
    ROLE_PERMISSIONS,
    AuthContext,
    AuthenticationError,
    AuthorizationError,
    Permission,
    Role,
    TokenClaims,
    create_access_token,
    generate_api_key,
    hash_api_key,
    hash_password,
    resolve_permissions,
    verify_access_token,
    verify_password,
)
from security.hashing import (
    compute_financial_event_hash,
    sign_hmac_sha256,
    verify_financial_event_chain,
    verify_hmac_sha256,
)
from security.settings import NexusSettings, get_settings
from security.tenant import TenantIsolationError, assert_same_tenant

__all__ = [
    "ROLE_PERMISSIONS",
    "AuthContext",
    "AuthenticationError",
    "AuthorizationError",
    "NexusSettings",
    "Permission",
    "Role",
    "TenantIsolationError",
    "TokenClaims",
    "assert_same_tenant",
    "compute_financial_event_hash",
    "create_access_token",
    "generate_api_key",
    "get_settings",
    "hash_api_key",
    "hash_password",
    "resolve_permissions",
    "sign_hmac_sha256",
    "verify_access_token",
    "verify_financial_event_chain",
    "verify_hmac_sha256",
    "verify_password",
]
