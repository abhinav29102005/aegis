"""Authentication, RBAC permissions, password hashing, API keys, and JWT tokens."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import secrets
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import Any
from uuid import UUID, uuid4


class AuthenticationError(PermissionError):
    """Raised when credentials or session tokens are missing, malformed, revoked, or expired."""


class AuthorizationError(PermissionError):
    """Raised when an authenticated principal lacks required permissions."""


class Role(StrEnum):
    OWNER = "OWNER"
    ADMIN = "ADMIN"
    OPERATOR = "OPERATOR"
    AUDITOR = "AUDITOR"
    AGENT_SERVICE = "AGENT_SERVICE"
    VIEWER = "VIEWER"


class Permission(StrEnum):
    ORG_MANAGE = "org:manage"
    MEMBERS_MANAGE = "members:manage"
    KEYS_MANAGE = "keys:manage"
    AGENTS_READ = "agents:read"
    AGENTS_WRITE = "agents:write"
    PASSPORTS_READ = "passports:read"
    PASSPORTS_WRITE = "passports:write"
    PROPOSALS_WRITE = "proposals:write"
    APPROVALS_DECIDE = "approvals:decide"
    PAYMENTS_READ = "payments:read"
    PAYMENTS_CHECKOUT = "payments:checkout"
    PAYMENTS_CAPTURE = "payments:capture"
    GHOSTPAY_READ = "ghostpay:read"
    GHOSTPAY_SIMULATE = "ghostpay:simulate"
    DISPUTES_READ = "disputes:read"
    DISPUTES_WRITE = "disputes:write"
    DISPUTES_APPROVE = "disputes:approve"
    DISPUTES_SUBMIT = "disputes:submit"
    WEBHOOKS_MANAGE = "webhooks:manage"
    AUDIT_READ = "audit:read"
    WORKER_MANAGE = "worker:manage"


_READ_PERMISSIONS = frozenset({
    Permission.AGENTS_READ,
    Permission.PASSPORTS_READ,
    Permission.PAYMENTS_READ,
    Permission.GHOSTPAY_READ,
    Permission.DISPUTES_READ,
    Permission.AUDIT_READ,
})

ROLE_PERMISSIONS: dict[Role, frozenset[Permission]] = {
    Role.OWNER: frozenset(Permission),
    Role.ADMIN: frozenset(Permission) - frozenset({Permission.ORG_MANAGE}),
    Role.OPERATOR: _READ_PERMISSIONS
    | frozenset({
        Permission.AGENTS_WRITE,
        Permission.PASSPORTS_WRITE,
        Permission.PROPOSALS_WRITE,
        Permission.APPROVALS_DECIDE,
        Permission.PAYMENTS_CHECKOUT,
        Permission.PAYMENTS_CAPTURE,
        Permission.GHOSTPAY_SIMULATE,
        Permission.DISPUTES_WRITE,
        Permission.DISPUTES_APPROVE,
        Permission.DISPUTES_SUBMIT,
    }),
    Role.AUDITOR: _READ_PERMISSIONS | frozenset({Permission.GHOSTPAY_SIMULATE}),
    # External agent service accounts can propose purchases and initiate checkout only when
    # deterministic policy allows, and read payment/passport state. They NEVER approve human escalations
    # or manage org credentials.
    Role.AGENT_SERVICE: frozenset({
        Permission.AGENTS_READ,
        Permission.PASSPORTS_READ,
        Permission.PROPOSALS_WRITE,
        Permission.PAYMENTS_READ,
        Permission.PAYMENTS_CHECKOUT,
        Permission.PAYMENTS_CAPTURE,
    }),
    Role.VIEWER: _READ_PERMISSIONS,
}


def resolve_permissions(role: Role | str, explicit_scopes: list[str] | None = None) -> frozenset[Permission]:
    """Return effective permissions for a role, narrowed by explicit scopes if supplied."""
    resolved_role = role if isinstance(role, Role) else Role(role)
    base = ROLE_PERMISSIONS[resolved_role]
    if not explicit_scopes:
        return base
    allowed: set[Permission] = set()
    for scope in explicit_scopes:
        if scope == "*":
            return base
        try:
            perm = Permission(scope)
        except ValueError:
            continue
        if perm in base:
            allowed.add(perm)
    return frozenset(allowed)


# ------------------------------------------------------------------
# Password Hashing (PBKDF2-HMAC-SHA256)
# ------------------------------------------------------------------
_PBKDF2_ITERATIONS = 600_000


def hash_password(password: str, *, iterations: int = _PBKDF2_ITERATIONS) -> str:
    """Hash a password using PBKDF2-HMAC-SHA256 with a 128-bit random salt."""
    if len(password) < 8:
        raise ValueError("Password must be at least 8 characters")
    salt = os.urandom(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
    return f"pbkdf2_sha256${iterations}${salt.hex()}${digest.hex()}"


def verify_password(password: str, encoded_hash: str) -> bool:
    """Verify a plaintext password against a stored PBKDF2-HMAC-SHA256 hash."""
    try:
        scheme, iter_str, salt_hex, digest_hex = encoded_hash.split("$", 3)
        if scheme != "pbkdf2_sha256":
            return False
        iterations = int(iter_str)
        salt = bytes.fromhex(salt_hex)
        expected = bytes.fromhex(digest_hex)
    except (ValueError, TypeError):
        return False
    actual = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
    return hmac.compare_digest(actual, expected)


# ------------------------------------------------------------------
# API Key Issuance & Hashing
# ------------------------------------------------------------------
def generate_api_key(environment: str = "live") -> tuple[str, str, str]:
    """Generate (plaintext_key, key_prefix, key_digest_input) for storage.

    Note: callers should pass plaintext or salt+key to ``hash_api_key`` with the server secret.
    """
    env_tag = "test" if environment in {"development", "dev", "test", "testing", "sandbox"} else "live"
    token = secrets.token_urlsafe(32)
    plaintext = f"aegis_{env_tag}_{token}"
    prefix = plaintext[:18]
    return plaintext, prefix, token


def hash_api_key(raw_key: str, pepper: str) -> str:
    """Compute keyed SHA-256 HMAC digest of an API key so plaintext keys are never persisted."""
    return hmac.new(pepper.encode("utf-8"), raw_key.encode("utf-8"), hashlib.sha256).hexdigest()


# ------------------------------------------------------------------
# Standards-Compliant HS256 JWT Session Tokens
# ------------------------------------------------------------------
def _b64url_encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _b64url_decode(data: str) -> bytes:
    padding = "=" * (-len(data) % 4)
    return base64.urlsafe_b64decode(data + padding)


@dataclass(frozen=True)
class TokenClaims:
    sub: UUID
    tenant_id: UUID
    role: Role
    email: str | None
    token_id: UUID
    issued_at: datetime
    expires_at: datetime


@dataclass(frozen=True)
class AuthContext:
    """Server-verified authentication and authorization context for every API request."""

    tenant_id: UUID
    actor_type: str  # USER | API_KEY | SERVICE_ACCOUNT
    actor_id: str
    role: Role
    permissions: frozenset[Permission] = field(default_factory=frozenset)
    user_id: UUID | None = None
    service_account_id: UUID | None = None
    api_key_id: UUID | None = None
    email: str | None = None
    token_id: UUID | None = None

    def has_permission(self, permission: Permission) -> bool:
        return permission in self.permissions

    def require_permission(self, permission: Permission) -> None:
        if permission not in self.permissions:
            raise AuthorizationError(
                f"Role {self.role.value} lacks required permission '{permission.value}'"
            )


def create_access_token(
    *,
    user_id: UUID,
    tenant_id: UUID,
    role: Role,
    secret: str,
    email: str | None = None,
    ttl_minutes: int = 480,
    now: datetime | None = None,
) -> str:
    """Create a signed HS256 JWT token containing authenticated identity and default org claim."""
    issued = (now or datetime.now(UTC)).astimezone(UTC)
    expires = issued + timedelta(minutes=ttl_minutes)
    header = {"alg": "HS256", "typ": "JWT"}
    payload: dict[str, Any] = {
        "sub": str(user_id),
        "tid": str(tenant_id),
        "role": role.value,
        "email": email,
        "jti": str(uuid4()),
        "iat": int(issued.timestamp()),
        "exp": int(expires.timestamp()),
    }
    encoded_header = _b64url_encode(json.dumps(header, separators=(",", ":"), sort_keys=True).encode("utf-8"))
    encoded_payload = _b64url_encode(json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8"))
    signing_input = f"{encoded_header}.{encoded_payload}".encode("ascii")
    signature = hmac.new(secret.encode("utf-8"), signing_input, hashlib.sha256).digest()
    return f"{encoded_header}.{encoded_payload}.{_b64url_encode(signature)}"


def verify_access_token(
    token: str,
    *,
    secret: str,
    now: datetime | None = None,
) -> TokenClaims:
    """Verify HS256 JWT signature and expiration; fail closed on any anomaly."""
    parts = token.strip().split(".")
    if len(parts) != 3:
        raise AuthenticationError("Malformed bearer token")
    encoded_header, encoded_payload, encoded_sig = parts
    try:
        header = json.loads(_b64url_decode(encoded_header).decode("utf-8"))
        payload = json.loads(_b64url_decode(encoded_payload).decode("utf-8"))
        provided_sig = _b64url_decode(encoded_sig)
    except Exception as exc:
        raise AuthenticationError("Corrupted bearer token encoding") from exc

    if header.get("alg") != "HS256" or header.get("typ") != "JWT":
        raise AuthenticationError("Unsupported token algorithm or type")

    signing_input = f"{encoded_header}.{encoded_payload}".encode("ascii")
    expected_sig = hmac.new(secret.encode("utf-8"), signing_input, hashlib.sha256).digest()
    if not hmac.compare_digest(provided_sig, expected_sig):
        raise AuthenticationError("Invalid bearer token signature")

    current_ts = int((now or datetime.now(UTC)).astimezone(UTC).timestamp())
    exp = payload.get("exp")
    iat = payload.get("iat")
    if not isinstance(exp, int) or not isinstance(iat, int) or current_ts >= exp:
        raise AuthenticationError("Bearer token has expired")

    try:
        return TokenClaims(
            sub=UUID(str(payload["sub"])),
            tenant_id=UUID(str(payload["tid"])),
            role=Role(str(payload["role"])),
            email=payload.get("email"),
            token_id=UUID(str(payload["jti"])),
            issued_at=datetime.fromtimestamp(iat, tz=UTC),
            expires_at=datetime.fromtimestamp(exp, tz=UTC),
        )
    except (KeyError, ValueError) as exc:
        raise AuthenticationError("Bearer token missing valid claims") from exc
