"""Authentication, organization management, RBAC memberships, invitations, SSO/MFA, and admin audits."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import secrets
import time
from collections import defaultdict, deque
from datetime import UTC, datetime, timedelta
from threading import Lock
from typing import Annotated, Any
from uuid import UUID

import httpx
from database import (
    ApiKeyRow,
    OrganizationMembershipRow,
    OrgInvitationRow,
    PlatformRepository,
    ServiceAccountRow,
)
from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from pydantic import BaseModel, ConfigDict, Field
from security import (
    AuthContext,
    AuthenticationError,
    NexusSettings,
    Permission,
    Role,
    build_otpauth_uri,
    create_access_token,
    decrypt_secret,
    encrypt_secret,
    generate_totp_secret,
    hash_password,
    resolve_permissions,
    validate_role_assignment,
    verify_oidc_claims,
    verify_password,
    verify_totp_code,
)
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from aegis_api.deps import (
    get_app_settings,
    get_auth_context,
    get_db_session,
    require_permission,
)

router = APIRouter(tags=["auth-orgs"])

_DISPOSABLE_EMAIL_DOMAINS = frozenset({
    "10minutemail.com",
    "dispostable.com",
    "guerrillamail.com",
    "maildrop.cc",
    "mailinator.com",
    "tempmail.com",
    "throwawaymail.com",
    "trashmail.com",
    "yopmail.com",
})

_RSA_SHA256_ASN1_PREFIX = bytes.fromhex("3031300d060960864801650304020105000420")


def _hash_token(raw_token: str) -> str:
    return hashlib.sha256(raw_token.strip().encode("utf-8")).hexdigest()


def _b64url_decode(data: str) -> bytes:
    padding = "=" * (-len(data) % 4)
    return base64.urlsafe_b64decode(data + padding)


class _RegistrationThrottleStore:
    """Thread-safe sliding-window registration throttle scoped per FastAPI app instance."""

    def __init__(self, *, window_seconds: float = 900.0) -> None:
        self.window_seconds = window_seconds
        self._buckets: dict[str, deque[float]] = defaultdict(deque)
        self._lock = Lock()

    def check_and_record(self, key: str, *, limit: int) -> bool:
        now = time.monotonic()
        cutoff = now - self.window_seconds
        with self._lock:
            bucket = self._buckets[key]
            while bucket and bucket[0] <= cutoff:
                bucket.popleft()
            if len(bucket) >= limit:
                return False
            bucket.append(now)
            return True


def _get_registration_throttle(request: Request) -> _RegistrationThrottleStore:
    store = getattr(request.app.state, "registration_throttle", None)
    if store is None:
        window = float(getattr(request.app.state, "registration_window_seconds", 900.0))
        store = _RegistrationThrottleStore(window_seconds=window)
        request.app.state.registration_throttle = store
    return store


def enforce_registration_anti_abuse(request: Request, email: str) -> None:
    """Reject disposable email domains and throttle abusive per-IP / per-email registrations."""
    clean_email = email.strip().lower()
    if "@" not in clean_email:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"error_code": "INVALID_EMAIL", "message": "Provide a valid email address."},
        )
    domain = clean_email.rsplit("@", 1)[-1]
    if domain in _DISPOSABLE_EMAIL_DOMAINS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "error_code": "DISPOSABLE_EMAIL_REJECTED",
                "message": "Disposable email domains are not permitted for registration.",
            },
        )

    store = _get_registration_throttle(request)
    ip_limit = int(getattr(request.app.state, "registration_ip_limit", os.getenv("AEGIS_REGISTER_IP_LIMIT", "10")))
    email_limit = int(getattr(request.app.state, "registration_email_limit", os.getenv("AEGIS_REGISTER_EMAIL_LIMIT", "3")))
    client_ip = request.client.host if request.client else "unknown"

    if not store.check_and_record(f"ip:{client_ip}", limit=max(1, ip_limit)):
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail={
                "error_code": "REGISTRATION_RATE_LIMITED",
                "message": "Too many registration attempts from this IP address.",
            },
        )
    if not store.check_and_record(f"email:{clean_email}", limit=max(1, email_limit)):
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail={
                "error_code": "REGISTRATION_RATE_LIMITED",
                "message": "Too many registration attempts for this email address.",
            },
        )


class RegisterRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    email: str = Field(min_length=3, max_length=255)
    password: str = Field(min_length=8, max_length=128)
    full_name: str = Field(min_length=1, max_length=160)
    organization_name: str = Field(min_length=2, max_length=120)
    organization_slug: str = Field(min_length=2, max_length=64, pattern=r"^[a-z0-9-]+$")


class LoginRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    email: str = Field(min_length=3, max_length=255)
    password: str = Field(min_length=1, max_length=128)
    organization_id: UUID | None = None
    mfa_code: str | None = Field(default=None, min_length=6, max_length=12)


class VerifyEmailRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    token: str = Field(min_length=8, max_length=512)


class ResendVerificationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    email: str = Field(min_length=3, max_length=255)


class VerifyMfaRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: str = Field(min_length=6, max_length=12)


class OidcExchangeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id_token: str = Field(min_length=10, max_length=8192)
    nonce: str | None = Field(default=None, max_length=256)
    organization_id: UUID | None = None


class OrganizationSummary(BaseModel):
    id: UUID
    name: str
    slug: str
    role: str
    created_at: datetime


class AuthTokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user_id: UUID
    email: str
    full_name: str
    email_verified: bool = False
    mfa_enabled: bool = False
    verification_token: str | None = None
    active_tenant_id: UUID
    active_role: str
    permissions: list[str]
    organizations: list[OrganizationSummary]


class CreateOrganizationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=2, max_length=120)
    slug: str = Field(min_length=2, max_length=64, pattern=r"^[a-z0-9-]+$")


class UpdateOrganizationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=2, max_length=120)


class AddMemberRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    email: str = Field(min_length=3, max_length=255)
    full_name: str = Field(default="Workspace Member", min_length=1, max_length=160)
    password: str | None = Field(default=None, min_length=8, max_length=128)
    role: Role = Role.OPERATOR


class CreateInvitationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    email: str = Field(min_length=3, max_length=255)
    role: Role = Role.OPERATOR
    expires_in_hours: int = Field(default=72, ge=1, le=720)


class UpdateMemberRoleRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    role: Role


class CreateServiceAccountRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=2, max_length=120)
    description: str = Field(default="", max_length=500)
    role: Role = Role.AGENT_SERVICE


class CreateApiKeyRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=2, max_length=120)
    service_account_id: UUID | None = None
    role: Role = Role.AGENT_SERVICE
    scopes: list[str] = Field(default_factory=list)
    expires_at: datetime | None = None


def _build_org_list(platform: PlatformRepository, user_id: UUID) -> list[OrganizationSummary]:
    return [
        OrganizationSummary(
            id=tenant.id,
            name=tenant.name,
            slug=tenant.slug,
            role=membership.role,
            created_at=tenant.created_at,
        )
        for membership, tenant in platform.list_user_memberships(user_id)
    ]


def _issue_auth_response(
    *,
    platform: PlatformRepository,
    settings: NexusSettings,
    user: Any,
    tenant_id: UUID,
    role: Role,
    verification_token: str | None = None,
) -> AuthTokenResponse:
    token = create_access_token(
        user_id=user.id,
        tenant_id=tenant_id,
        role=role,
        secret=settings.jwt_secret,
        email=user.email,
        ttl_minutes=settings.session_ttl_minutes,
    )
    return AuthTokenResponse(
        access_token=token,
        user_id=user.id,
        email=user.email,
        full_name=user.full_name,
        email_verified=bool(getattr(user, "email_verified", False)),
        mfa_enabled=bool(getattr(user, "mfa_enabled", False)),
        verification_token=verification_token,
        active_tenant_id=tenant_id,
        active_role=role.value,
        permissions=sorted(p.value for p in resolve_permissions(role)),
        organizations=_build_org_list(platform, user.id),
    )


def _verify_rs256_signature(signing_input: bytes, signature: bytes, jwk: dict[str, Any]) -> bool:
    if jwk.get("kty") != "RSA" or "n" not in jwk or "e" not in jwk:
        return False
    n_bytes = _b64url_decode(str(jwk["n"]))
    e_bytes = _b64url_decode(str(jwk["e"]))
    modulus = int.from_bytes(n_bytes, "big")
    exponent = int.from_bytes(e_bytes, "big")
    k = (modulus.bit_length() + 7) // 8
    if len(signature) != k or k < len(_RSA_SHA256_ASN1_PREFIX) + 32 + 11:
        return False
    em_int = pow(int.from_bytes(signature, "big"), exponent, modulus)
    em_actual = em_int.to_bytes(k, "big")
    digest_info = _RSA_SHA256_ASN1_PREFIX + hashlib.sha256(signing_input).digest()
    ps_len = k - len(digest_info) - 3
    if ps_len < 8:
        return False
    em_expected = b"\x00\x01" + (b"\xff" * ps_len) + b"\x00" + digest_info
    return hmac.compare_digest(em_actual, em_expected)


async def _load_jwks(request: Request, jwks_url: str) -> dict[str, Any]:
    in_memory = getattr(request.app.state, "oidc_jwks", None)
    if isinstance(in_memory, dict):
        return in_memory
    http_client = getattr(request.app.state, "oidc_http_client", None)
    if http_client is not None:
        resp = await http_client.get(jwks_url)
    else:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(jwks_url)
    resp.raise_for_status()
    data = resp.json()
    if not isinstance(data, dict) or not isinstance(data.get("keys"), list):
        raise AuthenticationError("Invalid OIDC JWKS payload")
    return data


async def _decode_and_verify_oidc_token(
    request: Request,
    id_token: str,
    *,
    hs256_secret: str,
    jwks_url: str,
) -> dict[str, Any]:
    custom_verifier = getattr(request.app.state, "oidc_token_verifier", None)
    if callable(custom_verifier):
        claims = custom_verifier(id_token)
        if not isinstance(claims, dict):
            raise AuthenticationError("Invalid OIDC claims returned by verifier")
        return claims

    parts = id_token.strip().split(".")
    if len(parts) != 3:
        raise AuthenticationError("Malformed OIDC ID token")
    encoded_header, encoded_payload, encoded_sig = parts
    try:
        header = json.loads(_b64url_decode(encoded_header).decode("utf-8"))
        claims = json.loads(_b64url_decode(encoded_payload).decode("utf-8"))
        signature = _b64url_decode(encoded_sig)
    except Exception as exc:
        raise AuthenticationError("Corrupted OIDC ID token encoding") from exc

    alg = header.get("alg")
    signing_input = f"{encoded_header}.{encoded_payload}".encode("ascii")

    if alg == "HS256":
        if not hs256_secret:
            raise AuthenticationError("HS256 OIDC verification is not configured")
        expected_sig = hmac.new(hs256_secret.encode("utf-8"), signing_input, hashlib.sha256).digest()
        if not hmac.compare_digest(signature, expected_sig):
            raise AuthenticationError("Invalid OIDC ID token signature")
        return claims

    if alg == "RS256":
        in_memory_jwks = getattr(request.app.state, "oidc_jwks", None)
        if not jwks_url and not in_memory_jwks:
            raise AuthenticationError("RS256 OIDC JWKS verification is not configured")
        jwks = await _load_jwks(request, jwks_url)
        kid = header.get("kid")
        keys = jwks.get("keys", [])
        candidates = [k for k in keys if isinstance(k, dict) and (kid is None or k.get("kid") == kid)]
        if not any(_verify_rs256_signature(signing_input, signature, k) for k in candidates):
            raise AuthenticationError("Invalid OIDC ID token signature")
        return claims

    raise AuthenticationError(f"Unsupported OIDC ID token algorithm '{alg}'")


@router.post("/auth/register", response_model=AuthTokenResponse, status_code=status.HTTP_201_CREATED)
def register_account(
    payload: RegisterRequest,
    request: Request,
    session: Annotated[Session, Depends(get_db_session)],
    settings: Annotated[NexusSettings, Depends(get_app_settings)],
) -> AuthTokenResponse:
    enforce_registration_anti_abuse(request, payload.email)
    platform = PlatformRepository(session)
    raw_verification_token = secrets.token_urlsafe(32)
    try:
        org = platform.create_organization(
            name=payload.organization_name,
            slug=payload.organization_slug,
        )
        user = platform.create_user(
            email=payload.email,
            full_name=payload.full_name,
            password_hash=hash_password(payload.password),
        )
        platform.add_membership(tenant_id=org.id, user_id=user.id, role=Role.OWNER)
        platform.create_email_verification(
            user_id=user.id,
            email=user.email,
            token_hash=_hash_token(raw_verification_token),
            expires_at=datetime.now(UTC) + timedelta(hours=24),
        )
        platform.record_admin_audit(
            tenant_id=org.id,
            actor_type="USER",
            actor_id=str(user.id),
            action="ORG_REGISTERED",
            resource_type="tenant",
            resource_id=str(org.id),
            details={"email": user.email, "slug": org.slug},
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"error_code": "REGISTRATION_CONFLICT", "message": str(exc)},
        ) from exc

    return _issue_auth_response(
        platform=platform,
        settings=settings,
        user=user,
        tenant_id=org.id,
        role=Role.OWNER,
        verification_token=raw_verification_token if not settings.is_production_like else None,
    )


@router.post("/auth/login", response_model=AuthTokenResponse)
def login_account(
    payload: LoginRequest,
    session: Annotated[Session, Depends(get_db_session)],
    settings: Annotated[NexusSettings, Depends(get_app_settings)],
) -> AuthTokenResponse:
    platform = PlatformRepository(session)
    user = platform.get_user_by_email(payload.email)
    if user is None or not user.is_active or not verify_password(payload.password, user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"error_code": "INVALID_CREDENTIALS", "message": "Invalid email or password."},
        )

    if settings.email_verification_required and not user.email_verified:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "error_code": "EMAIL_NOT_VERIFIED",
                "message": "Verify your email address before logging in.",
            },
        )

    if user.mfa_enabled:
        if not payload.mfa_code:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail={"error_code": "MFA_REQUIRED", "message": "TOTP MFA code is required."},
            )
        if not user.mfa_secret_encrypted:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail={"error_code": "MFA_MISCONFIGURED", "message": "MFA secret missing."},
            )
        secret = decrypt_secret(
            user.mfa_secret_encrypted,
            master_secret=settings.signing_secret,
            context={"user_id": str(user.id), "purpose": "totp_mfa"},
        )
        if not verify_totp_code(secret, payload.mfa_code):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail={"error_code": "INVALID_MFA_CODE", "message": "Invalid TOTP MFA code."},
            )

    memberships = platform.list_user_memberships(user.id)
    if not memberships:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"error_code": "NO_ORGANIZATION", "message": "User belongs to no active organizations."},
        )

    selected_membership, selected_tenant = memberships[0]
    if payload.organization_id is not None:
        match = next(((m, t) for m, t in memberships if t.id == payload.organization_id), None)
        if match is None:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail={"error_code": "TENANT_MEMBERSHIP_DENIED", "message": "User is not a member of requested organization."},
            )
        selected_membership, selected_tenant = match

    role = Role(selected_membership.role)
    platform.record_admin_audit(
        tenant_id=selected_tenant.id,
        actor_type="USER",
        actor_id=str(user.id),
        action="USER_LOGIN",
        resource_type="user",
        resource_id=str(user.id),
        details={"email": user.email},
    )
    return _issue_auth_response(
        platform=platform,
        settings=settings,
        user=user,
        tenant_id=selected_tenant.id,
        role=role,
    )


@router.post("/auth/verify-email")
def verify_email(
    payload: VerifyEmailRequest,
    session: Annotated[Session, Depends(get_db_session)],
) -> dict[str, Any]:
    platform = PlatformRepository(session)
    try:
        row = platform.verify_email_token(_hash_token(payload.token))
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"error_code": "INVALID_VERIFICATION_TOKEN", "message": str(exc)},
        ) from exc

    memberships = platform.list_user_memberships(row.user_id)
    if memberships:
        platform.record_admin_audit(
            tenant_id=memberships[0][1].id,
            actor_type="USER",
            actor_id=str(row.user_id),
            action="EMAIL_VERIFIED",
            resource_type="user",
            resource_id=str(row.user_id),
            details={"email": row.email},
        )
    return {
        "verified": True,
        "email": row.email,
        "email_verified": True,
        "verified_at": row.verified_at.isoformat() if row.verified_at else None,
    }


@router.post("/auth/resend-verification")
def resend_verification(
    payload: ResendVerificationRequest,
    request: Request,
    session: Annotated[Session, Depends(get_db_session)],
    settings: Annotated[NexusSettings, Depends(get_app_settings)],
) -> dict[str, Any]:
    store = _get_registration_throttle(request)
    clean_email = payload.email.strip().lower()
    if not store.check_and_record(f"resend:{clean_email}", limit=5):
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail={
                "error_code": "VERIFICATION_RATE_LIMITED",
                "message": "Too many verification resend requests for this email.",
            },
        )

    platform = PlatformRepository(session)
    user = platform.get_user_by_email(clean_email)
    if user is None or not user.is_active:
        return {"sent": True, "email_verified": False}
    if user.email_verified:
        return {"sent": False, "email_verified": True, "message": "Email is already verified."}

    raw_token = secrets.token_urlsafe(32)
    platform.create_email_verification(
        user_id=user.id,
        email=user.email,
        token_hash=_hash_token(raw_token),
        expires_at=datetime.now(UTC) + timedelta(hours=24),
    )
    resp: dict[str, Any] = {"sent": True, "email_verified": False}
    if not settings.is_production_like:
        resp["verification_token"] = raw_token
    return resp


@router.post("/auth/mfa/enroll")
def enroll_mfa(
    auth: Annotated[AuthContext, Depends(get_auth_context)],
    session: Annotated[Session, Depends(get_db_session)],
    settings: Annotated[NexusSettings, Depends(get_app_settings)],
) -> dict[str, Any]:
    if auth.user_id is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"error_code": "USER_TOKEN_REQUIRED", "message": "Only human user accounts can enroll TOTP MFA."},
        )
    platform = PlatformRepository(session)
    user = platform.get_user(auth.user_id)
    if user is None or not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error_code": "USER_NOT_FOUND", "message": "User not found."},
        )
    secret = generate_totp_secret()
    encrypted = encrypt_secret(
        secret,
        master_secret=settings.signing_secret,
        context={"user_id": str(user.id), "purpose": "totp_mfa"},
    )
    user.mfa_secret_encrypted = encrypted
    user.mfa_enabled = False
    session.flush()
    platform.record_admin_audit(
        tenant_id=auth.tenant_id,
        actor_type=auth.actor_type,
        actor_id=auth.actor_id,
        action="MFA_ENROLLMENT_STARTED",
        resource_type="user",
        resource_id=str(user.id),
    )
    return {
        "secret": secret,
        "otpauth_uri": build_otpauth_uri(secret, account_name=user.email, issuer="AEGIS"),
        "mfa_enabled": False,
    }


@router.post("/auth/mfa/verify")
def verify_mfa_enrollment(
    payload: VerifyMfaRequest,
    auth: Annotated[AuthContext, Depends(get_auth_context)],
    session: Annotated[Session, Depends(get_db_session)],
    settings: Annotated[NexusSettings, Depends(get_app_settings)],
) -> dict[str, Any]:
    if auth.user_id is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"error_code": "USER_TOKEN_REQUIRED", "message": "Only human user accounts can verify TOTP MFA."},
        )
    platform = PlatformRepository(session)
    user = platform.get_user(auth.user_id)
    if user is None or not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error_code": "USER_NOT_FOUND", "message": "User not found."},
        )
    if not user.mfa_secret_encrypted:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"error_code": "MFA_NOT_ENROLLED", "message": "Call POST /auth/mfa/enroll before verifying."},
        )
    secret = decrypt_secret(
        user.mfa_secret_encrypted,
        master_secret=settings.signing_secret,
        context={"user_id": str(user.id), "purpose": "totp_mfa"},
    )
    if not verify_totp_code(secret, payload.code):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"error_code": "INVALID_MFA_CODE", "message": "Invalid TOTP verification code."},
        )
    platform.set_user_mfa(user.id, enabled=True, mfa_secret_encrypted=user.mfa_secret_encrypted)
    platform.record_admin_audit(
        tenant_id=auth.tenant_id,
        actor_type=auth.actor_type,
        actor_id=auth.actor_id,
        action="MFA_ENABLED",
        resource_type="user",
        resource_id=str(user.id),
    )
    return {"user_id": str(user.id), "mfa_enabled": True}


@router.post("/auth/sso/oidc/exchange", response_model=AuthTokenResponse)
async def oidc_sso_exchange(
    payload: OidcExchangeRequest,
    request: Request,
    session: Annotated[Session, Depends(get_db_session)],
    settings: Annotated[NexusSettings, Depends(get_app_settings)],
) -> AuthTokenResponse:
    expected_issuer = getattr(request.app.state, "oidc_issuer", None) or os.getenv("OIDC_ISSUER", "")
    expected_audience = getattr(request.app.state, "oidc_audience", None) or os.getenv("OIDC_AUDIENCE", "")
    hs256_secret = getattr(request.app.state, "oidc_hs256_secret", None) or os.getenv("OIDC_HS256_SECRET", "")
    jwks_url = getattr(request.app.state, "oidc_jwks_url", None) or os.getenv("OIDC_JWKS_URL", "")
    has_verifier = bool(
        hs256_secret
        or jwks_url
        or getattr(request.app.state, "oidc_jwks", None)
        or getattr(request.app.state, "oidc_token_verifier", None)
    )
    if not expected_issuer or not expected_audience or not has_verifier:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"error_code": "OIDC_NOT_CONFIGURED", "message": "OIDC SSO is not configured."},
        )

    raw_claims = await _decode_and_verify_oidc_token(
        request,
        payload.id_token,
        hs256_secret=hs256_secret,
        jwks_url=jwks_url,
    )
    claims = verify_oidc_claims(
        raw_claims,
        expected_issuer=expected_issuer,
        expected_audience=expected_audience,
        expected_nonce=payload.nonce,
    )

    email = claims.get("email")
    if not isinstance(email, str) or not email.strip():
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"error_code": "OIDC_EMAIL_MISSING", "message": "OIDC token must include a valid email claim."},
        )
    if claims.get("email_verified") is False:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"error_code": "OIDC_EMAIL_UNVERIFIED", "message": "OIDC email claim is not verified."},
        )

    platform = PlatformRepository(session)
    user = platform.get_user_by_email(email)
    if user is None or not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"error_code": "OIDC_USER_NOT_PROVISIONED", "message": "No active user exists for OIDC identity."},
        )

    memberships = platform.list_user_memberships(user.id)
    if not memberships:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"error_code": "NO_ORGANIZATION", "message": "User belongs to no active organizations."},
        )

    selected_membership, selected_tenant = memberships[0]
    if payload.organization_id is not None:
        match = next(((m, t) for m, t in memberships if t.id == payload.organization_id), None)
        if match is None:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail={"error_code": "TENANT_MEMBERSHIP_DENIED", "message": "User is not a member of requested organization."},
            )
        selected_membership, selected_tenant = match

    role = Role(selected_membership.role)
    platform.record_admin_audit(
        tenant_id=selected_tenant.id,
        actor_type="USER",
        actor_id=str(user.id),
        action="OIDC_SSO_LOGIN",
        resource_type="user",
        resource_id=str(user.id),
        details={"email": user.email, "issuer": expected_issuer, "sub": claims.get("sub")},
    )
    return _issue_auth_response(
        platform=platform,
        settings=settings,
        user=user,
        tenant_id=selected_tenant.id,
        role=role,
    )


@router.get("/auth/me")
def get_me(
    auth: Annotated[AuthContext, Depends(get_auth_context)],
    session: Annotated[Session, Depends(get_db_session)],
) -> dict[str, Any]:
    platform = PlatformRepository(session)
    org = platform.get_organization(auth.tenant_id)
    orgs = _build_org_list(platform, auth.user_id) if auth.user_id else []
    user = platform.get_user(auth.user_id) if auth.user_id else None
    return {
        "actor_type": auth.actor_type,
        "actor_id": auth.actor_id,
        "user_id": str(auth.user_id) if auth.user_id else None,
        "email": auth.email,
        "email_verified": bool(user.email_verified) if user is not None else False,
        "mfa_enabled": bool(user.mfa_enabled) if user is not None else False,
        "active_tenant_id": str(auth.tenant_id),
        "active_organization": org.model_dump(mode="json") if org else None,
        "role": auth.role.value,
        "permissions": sorted(p.value for p in auth.permissions),
        "organizations": [o.model_dump(mode="json") for o in orgs],
    }


@router.post("/orgs", response_model=OrganizationSummary, status_code=status.HTTP_201_CREATED)
def create_organization(
    payload: CreateOrganizationRequest,
    auth: Annotated[AuthContext, Depends(get_auth_context)],
    session: Annotated[Session, Depends(get_db_session)],
) -> OrganizationSummary:
    if auth.user_id is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"error_code": "USER_TOKEN_REQUIRED", "message": "API keys cannot create new organizations."},
        )
    platform = PlatformRepository(session)
    try:
        org = platform.create_organization(name=payload.name, slug=payload.slug)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    platform.add_membership(tenant_id=org.id, user_id=auth.user_id, role=Role.OWNER)
    platform.record_admin_audit(
        tenant_id=org.id,
        actor_type=auth.actor_type,
        actor_id=auth.actor_id,
        action="ORG_CREATED",
        resource_type="tenant",
        resource_id=str(org.id),
        details={"name": org.name, "slug": org.slug},
    )
    return OrganizationSummary(id=org.id, name=org.name, slug=org.slug, role=Role.OWNER.value, created_at=org.created_at)


@router.patch("/orgs/current")
def update_current_org(
    payload: UpdateOrganizationRequest,
    auth: Annotated[AuthContext, Depends(require_permission(Permission.ORG_MANAGE))],
    session: Annotated[Session, Depends(get_db_session)],
) -> dict[str, Any]:
    platform = PlatformRepository(session)
    org = platform.update_organization_name(auth.tenant_id, payload.name)
    platform.record_admin_audit(
        tenant_id=auth.tenant_id,
        actor_type=auth.actor_type,
        actor_id=auth.actor_id,
        action="ORG_UPDATED",
        resource_type="tenant",
        resource_id=str(org.id),
        details={"name": org.name},
    )
    return org.model_dump(mode="json")


@router.get("/orgs/members")
def list_org_members(
    response: Response,
    auth: Annotated[AuthContext, Depends(require_permission(Permission.AUDIT_READ))],
    session: Annotated[Session, Depends(get_db_session)],
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[dict[str, Any]]:
    platform = PlatformRepository(session)
    total = int(
        session.scalar(
            select(func.count())
            .select_from(OrganizationMembershipRow)
            .where(OrganizationMembershipRow.tenant_id == auth.tenant_id)
        )
        or 0
    )
    response.headers["X-Total-Count"] = str(total)
    rows = platform.list_org_members(auth.tenant_id, limit=limit, offset=offset)
    return [
        {
            "membership_id": str(m.id),
            "user_id": str(u.id),
            "email": u.email,
            "full_name": u.full_name,
            "role": m.role,
            "status": m.status,
            "created_at": m.created_at.isoformat(),
        }
        for m, u in rows
    ]


@router.post("/orgs/members", status_code=status.HTTP_201_CREATED)
def add_org_member(
    payload: AddMemberRequest,
    auth: Annotated[AuthContext, Depends(require_permission(Permission.MEMBERS_MANAGE))],
    session: Annotated[Session, Depends(get_db_session)],
) -> dict[str, Any]:
    validate_role_assignment(auth.role, payload.role)
    platform = PlatformRepository(session)
    user = platform.get_user_by_email(payload.email)
    if user is None:
        if payload.password is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={"error_code": "PASSWORD_REQUIRED", "message": "Provide an initial password for a new user."},
            )
        user = platform.create_user(
            email=payload.email,
            full_name=payload.full_name,
            password_hash=hash_password(payload.password),
        )
    else:
        existing_membership = platform.get_membership(auth.tenant_id, user.id)
        if existing_membership is None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={
                    "error_code": "INVITATION_REQUIRED",
                    "message": "Existing user does not belong to this organization; send an invitation via POST /orgs/invitations.",
                },
            )
        if existing_membership.status == "ERASED":
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={"error_code": "USER_ERASED", "message": "Erased user membership cannot be reactivated."},
            )

    membership = platform.add_membership(tenant_id=auth.tenant_id, user_id=user.id, role=payload.role)
    platform.record_admin_audit(
        tenant_id=auth.tenant_id,
        actor_type=auth.actor_type,
        actor_id=auth.actor_id,
        action="MEMBER_ADDED",
        resource_type="membership",
        resource_id=str(membership.id),
        details={"email": user.email, "role": payload.role.value},
    )
    return {
        "membership_id": str(membership.id),
        "user_id": str(user.id),
        "email": user.email,
        "full_name": user.full_name,
        "role": membership.role,
        "status": membership.status,
    }


@router.patch("/orgs/members/{user_id}/role")
def update_member_role(
    user_id: UUID,
    payload: UpdateMemberRoleRequest,
    auth: Annotated[AuthContext, Depends(require_permission(Permission.MEMBERS_MANAGE))],
    session: Annotated[Session, Depends(get_db_session)],
) -> dict[str, Any]:
    validate_role_assignment(auth.role, payload.role)
    platform = PlatformRepository(session)
    try:
        membership = platform.update_member_role(auth.tenant_id, user_id, payload.role)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    platform.record_admin_audit(
        tenant_id=auth.tenant_id,
        actor_type=auth.actor_type,
        actor_id=auth.actor_id,
        action="MEMBER_ROLE_UPDATED",
        resource_type="membership",
        resource_id=str(membership.id),
        details={"user_id": str(user_id), "role": payload.role.value},
    )
    return {"user_id": str(user_id), "role": membership.role, "status": membership.status}


@router.post("/orgs/invitations", status_code=status.HTTP_201_CREATED)
def invite_org_member(
    payload: CreateInvitationRequest,
    auth: Annotated[AuthContext, Depends(require_permission(Permission.MEMBERS_MANAGE))],
    session: Annotated[Session, Depends(get_db_session)],
    settings: Annotated[NexusSettings, Depends(get_app_settings)],
) -> dict[str, Any]:
    validate_role_assignment(auth.role, payload.role)
    platform = PlatformRepository(session)
    existing_user = platform.get_user_by_email(payload.email)
    if existing_user is not None:
        existing_mem = platform.get_membership(auth.tenant_id, existing_user.id)
        if existing_mem is not None and existing_mem.status == "ACTIVE":
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={"error_code": "ALREADY_MEMBER", "message": "User is already an active member of this organization."},
            )

    raw_token = secrets.token_urlsafe(32)
    inv = platform.create_org_invitation(
        tenant_id=auth.tenant_id,
        email=payload.email,
        role=payload.role,
        token_hash=_hash_token(raw_token),
        expires_at=datetime.now(UTC) + timedelta(hours=payload.expires_in_hours),
        invited_by_user_id=auth.user_id,
    )
    platform.record_admin_audit(
        tenant_id=auth.tenant_id,
        actor_type=auth.actor_type,
        actor_id=auth.actor_id,
        action="ORG_INVITATION_CREATED",
        resource_type="org_invitation",
        resource_id=str(inv.id),
        details={"email": inv.email, "role": inv.role},
    )
    return {
        "id": str(inv.id),
        "tenant_id": str(inv.tenant_id),
        "email": inv.email,
        "role": inv.role,
        "status": inv.status,
        "expires_at": inv.expires_at.isoformat(),
        "created_at": inv.created_at.isoformat(),
        "token": raw_token if not settings.is_production_like else None,
    }


@router.get("/orgs/invitations")
def list_org_invitations(
    response: Response,
    auth: Annotated[AuthContext, Depends(require_permission(Permission.AUDIT_READ))],
    session: Annotated[Session, Depends(get_db_session)],
    status_filter: Annotated[str | None, Query(alias="status")] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[dict[str, Any]]:
    platform = PlatformRepository(session)
    count_stmt = (
        select(func.count())
        .select_from(OrgInvitationRow)
        .where(OrgInvitationRow.tenant_id == auth.tenant_id)
    )
    if status_filter is not None:
        count_stmt = count_stmt.where(OrgInvitationRow.status == status_filter)
    total = int(session.scalar(count_stmt) or 0)
    response.headers["X-Total-Count"] = str(total)

    rows = platform.list_org_invitations(
        auth.tenant_id,
        status=status_filter,
        limit=limit,
        offset=offset,
    )
    return [
        {
            "id": str(inv.id),
            "tenant_id": str(inv.tenant_id),
            "email": inv.email,
            "role": inv.role,
            "status": inv.status,
            "expires_at": inv.expires_at.isoformat(),
            "accepted_at": inv.accepted_at.isoformat() if inv.accepted_at else None,
            "created_at": inv.created_at.isoformat(),
        }
        for inv in rows
    ]


@router.post("/orgs/invitations/{token}/accept")
def accept_org_invitation(
    token: str,
    auth: Annotated[AuthContext, Depends(get_auth_context)],
    session: Annotated[Session, Depends(get_db_session)],
) -> dict[str, Any]:
    if auth.user_id is None or auth.email is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"error_code": "USER_TOKEN_REQUIRED", "message": "Only authenticated human users may accept invitations."},
        )
    platform = PlatformRepository(session)
    token_hash = _hash_token(token)
    inv = platform.get_org_invitation_by_token_hash(token_hash)
    if inv is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error_code": "INVITATION_NOT_FOUND", "message": "Invitation not found."},
        )
    if inv.email.strip().lower() != auth.email.strip().lower():
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "error_code": "INVITATION_EMAIL_MISMATCH",
                "message": "Authenticated user email does not match this invitation.",
            },
        )
    try:
        accepted = platform.accept_org_invitation(token_hash, user_id=auth.user_id)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"error_code": "INVITATION_INVALID", "message": str(exc)},
        ) from exc

    platform.record_admin_audit(
        tenant_id=accepted.tenant_id,
        actor_type=auth.actor_type,
        actor_id=auth.actor_id,
        action="ORG_INVITATION_ACCEPTED",
        resource_type="org_invitation",
        resource_id=str(accepted.id),
        details={"email": accepted.email, "role": accepted.role},
    )
    return {
        "invitation_id": str(accepted.id),
        "tenant_id": str(accepted.tenant_id),
        "email": accepted.email,
        "role": accepted.role,
        "status": accepted.status,
        "accepted_at": accepted.accepted_at.isoformat() if accepted.accepted_at else None,
    }


@router.delete("/orgs/invitations/{invitation_id}")
def revoke_org_invitation(
    invitation_id: UUID,
    auth: Annotated[AuthContext, Depends(require_permission(Permission.MEMBERS_MANAGE))],
    session: Annotated[Session, Depends(get_db_session)],
) -> dict[str, Any]:
    platform = PlatformRepository(session)
    try:
        inv = platform.revoke_org_invitation(auth.tenant_id, invitation_id)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    platform.record_admin_audit(
        tenant_id=auth.tenant_id,
        actor_type=auth.actor_type,
        actor_id=auth.actor_id,
        action="ORG_INVITATION_REVOKED",
        resource_type="org_invitation",
        resource_id=str(inv.id),
        details={"email": inv.email},
    )
    return {"id": str(inv.id), "status": inv.status}


@router.get("/orgs/service-accounts")
def list_service_accounts(
    response: Response,
    auth: Annotated[AuthContext, Depends(require_permission(Permission.KEYS_MANAGE))],
    session: Annotated[Session, Depends(get_db_session)],
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[dict[str, Any]]:
    platform = PlatformRepository(session)
    total = int(
        session.scalar(
            select(func.count())
            .select_from(ServiceAccountRow)
            .where(ServiceAccountRow.tenant_id == auth.tenant_id)
        )
        or 0
    )
    response.headers["X-Total-Count"] = str(total)
    return [
        {
            "id": str(sa.id),
            "tenant_id": str(sa.tenant_id),
            "name": sa.name,
            "description": sa.description,
            "role": sa.role,
            "status": sa.status,
            "created_at": sa.created_at.isoformat(),
        }
        for sa in platform.list_service_accounts(auth.tenant_id, limit=limit, offset=offset)
    ]


@router.post("/orgs/service-accounts", status_code=status.HTTP_201_CREATED)
def create_service_account(
    payload: CreateServiceAccountRequest,
    auth: Annotated[AuthContext, Depends(require_permission(Permission.KEYS_MANAGE))],
    session: Annotated[Session, Depends(get_db_session)],
) -> dict[str, Any]:
    validate_role_assignment(auth.role, payload.role)
    platform = PlatformRepository(session)
    try:
        sa = platform.create_service_account(
            tenant_id=auth.tenant_id,
            name=payload.name,
            description=payload.description,
            role=payload.role,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    platform.record_admin_audit(
        tenant_id=auth.tenant_id,
        actor_type=auth.actor_type,
        actor_id=auth.actor_id,
        action="SERVICE_ACCOUNT_CREATED",
        resource_type="service_account",
        resource_id=str(sa.id),
        details={"name": sa.name, "role": sa.role},
    )
    return {
        "id": str(sa.id),
        "tenant_id": str(sa.tenant_id),
        "name": sa.name,
        "description": sa.description,
        "role": sa.role,
        "status": sa.status,
        "created_at": sa.created_at.isoformat(),
    }


@router.get("/orgs/api-keys")
def list_api_keys(
    response: Response,
    auth: Annotated[AuthContext, Depends(require_permission(Permission.KEYS_MANAGE))],
    session: Annotated[Session, Depends(get_db_session)],
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[dict[str, Any]]:
    platform = PlatformRepository(session)
    total = int(
        session.scalar(
            select(func.count())
            .select_from(ApiKeyRow)
            .where(ApiKeyRow.tenant_id == auth.tenant_id)
        )
        or 0
    )
    response.headers["X-Total-Count"] = str(total)
    return [
        {
            "id": str(k.id),
            "name": k.name,
            "key_prefix": k.key_prefix,
            "role": k.role,
            "scopes": k.scopes,
            "status": k.status,
            "service_account_id": str(k.service_account_id) if k.service_account_id else None,
            "expires_at": k.expires_at.isoformat() if k.expires_at else None,
            "last_used_at": k.last_used_at.isoformat() if k.last_used_at else None,
            "revoked_at": k.revoked_at.isoformat() if k.revoked_at else None,
            "created_at": k.created_at.isoformat(),
        }
        for k in platform.list_api_keys(auth.tenant_id, limit=limit, offset=offset)
    ]


@router.post("/orgs/api-keys", status_code=status.HTTP_201_CREATED)
def issue_api_key(
    payload: CreateApiKeyRequest,
    auth: Annotated[AuthContext, Depends(require_permission(Permission.KEYS_MANAGE))],
    session: Annotated[Session, Depends(get_db_session)],
    settings: Annotated[NexusSettings, Depends(get_app_settings)],
) -> dict[str, Any]:
    validate_role_assignment(auth.role, payload.role)
    platform = PlatformRepository(session)
    try:
        key_row, raw_key = platform.create_api_key(
            tenant_id=auth.tenant_id,
            name=payload.name,
            pepper=settings.signing_secret,
            environment=settings.app_env,
            role=payload.role,
            scopes=payload.scopes,
            service_account_id=payload.service_account_id,
            user_id=auth.user_id,
            expires_at=payload.expires_at,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    platform.record_admin_audit(
        tenant_id=auth.tenant_id,
        actor_type=auth.actor_type,
        actor_id=auth.actor_id,
        action="API_KEY_ISSUED",
        resource_type="api_key",
        resource_id=str(key_row.id),
        details={"name": key_row.name, "key_prefix": key_row.key_prefix, "role": key_row.role},
    )
    return {
        "id": str(key_row.id),
        "name": key_row.name,
        "key_prefix": key_row.key_prefix,
        "plaintext_key": raw_key,
        "role": key_row.role,
        "scopes": key_row.scopes,
        "status": key_row.status,
        "created_at": key_row.created_at.isoformat(),
    }


@router.post("/orgs/api-keys/{key_id}/rotate")
def rotate_api_key(
    key_id: UUID,
    auth: Annotated[AuthContext, Depends(require_permission(Permission.KEYS_MANAGE))],
    session: Annotated[Session, Depends(get_db_session)],
    settings: Annotated[NexusSettings, Depends(get_app_settings)],
) -> dict[str, Any]:
    platform = PlatformRepository(session)
    try:
        new_row, raw_key = platform.rotate_api_key(
            tenant_id=auth.tenant_id,
            api_key_id=key_id,
            pepper=settings.signing_secret,
            environment=settings.app_env,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    platform.record_admin_audit(
        tenant_id=auth.tenant_id,
        actor_type=auth.actor_type,
        actor_id=auth.actor_id,
        action="API_KEY_ROTATED",
        resource_type="api_key",
        resource_id=str(new_row.id),
        details={"replaced_key_id": str(key_id), "key_prefix": new_row.key_prefix},
    )
    return {
        "id": str(new_row.id),
        "replaced_key_id": str(key_id),
        "name": new_row.name,
        "key_prefix": new_row.key_prefix,
        "plaintext_key": raw_key,
        "role": new_row.role,
        "status": new_row.status,
        "created_at": new_row.created_at.isoformat(),
    }


@router.post("/orgs/api-keys/{key_id}/revoke")
def revoke_api_key(
    key_id: UUID,
    auth: Annotated[AuthContext, Depends(require_permission(Permission.KEYS_MANAGE))],
    session: Annotated[Session, Depends(get_db_session)],
) -> dict[str, Any]:
    platform = PlatformRepository(session)
    try:
        row = platform.revoke_api_key(auth.tenant_id, key_id)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    platform.record_admin_audit(
        tenant_id=auth.tenant_id,
        actor_type=auth.actor_type,
        actor_id=auth.actor_id,
        action="API_KEY_REVOKED",
        resource_type="api_key",
        resource_id=str(row.id),
        details={"key_prefix": row.key_prefix},
    )
    return {"id": str(row.id), "status": row.status, "revoked_at": row.revoked_at.isoformat() if row.revoked_at else None}


@router.get("/orgs/audit-logs")
def list_admin_audit_logs(
    auth: Annotated[AuthContext, Depends(require_permission(Permission.AUDIT_READ))],
    session: Annotated[Session, Depends(get_db_session)],
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> dict[str, Any]:
    platform = PlatformRepository(session)
    rows, total = platform.list_admin_audits(auth.tenant_id, limit=limit, offset=offset)
    return {
        "items": [
            {
                "id": str(r.id),
                "actor_type": r.actor_type,
                "actor_id": r.actor_id,
                "action": r.action,
                "resource_type": r.resource_type,
                "resource_id": r.resource_id,
                "correlation_id": r.correlation_id,
                "details": r.details,
                "occurred_at": r.occurred_at.isoformat(),
            }
            for r in rows
        ],
        "total": total,
        "limit": limit,
        "offset": offset,
    }
