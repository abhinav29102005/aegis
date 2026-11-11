"""Authentication, organization management, RBAC memberships, service accounts, API keys, and admin audits."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any
from uuid import UUID

from database import PlatformRepository
from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, ConfigDict, Field
from security import (
    AuthContext,
    NexusSettings,
    Permission,
    Role,
    create_access_token,
    hash_password,
    verify_password,
)
from sqlalchemy.orm import Session

from aegis_api.deps import (
    get_app_settings,
    get_auth_context,
    get_db_session,
    require_permission,
)

router = APIRouter(tags=["auth-orgs"])


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


@router.post("/auth/register", response_model=AuthTokenResponse, status_code=status.HTTP_201_CREATED)
def register_account(
    payload: RegisterRequest,
    session: Annotated[Session, Depends(get_db_session)],
    settings: Annotated[NexusSettings, Depends(get_app_settings)],
) -> AuthTokenResponse:
    platform = PlatformRepository(session)
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

    from security import resolve_permissions

    token = create_access_token(
        user_id=user.id,
        tenant_id=org.id,
        role=Role.OWNER,
        secret=settings.jwt_secret,
        email=user.email,
        ttl_minutes=settings.session_ttl_minutes,
    )
    orgs = _build_org_list(platform, user.id)
    return AuthTokenResponse(
        access_token=token,
        user_id=user.id,
        email=user.email,
        full_name=user.full_name,
        active_tenant_id=org.id,
        active_role=Role.OWNER.value,
        permissions=sorted(p.value for p in resolve_permissions(Role.OWNER)),
        organizations=orgs,
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
    from security import resolve_permissions

    token = create_access_token(
        user_id=user.id,
        tenant_id=selected_tenant.id,
        role=role,
        secret=settings.jwt_secret,
        email=user.email,
        ttl_minutes=settings.session_ttl_minutes,
    )
    platform.record_admin_audit(
        tenant_id=selected_tenant.id,
        actor_type="USER",
        actor_id=str(user.id),
        action="USER_LOGIN",
        resource_type="user",
        resource_id=str(user.id),
        details={"email": user.email},
    )
    return AuthTokenResponse(
        access_token=token,
        user_id=user.id,
        email=user.email,
        full_name=user.full_name,
        active_tenant_id=selected_tenant.id,
        active_role=role.value,
        permissions=sorted(p.value for p in resolve_permissions(role)),
        organizations=_build_org_list(platform, user.id),
    )


@router.get("/auth/me")
def get_me(
    auth: Annotated[AuthContext, Depends(get_auth_context)],
    session: Annotated[Session, Depends(get_db_session)],
) -> dict[str, Any]:
    platform = PlatformRepository(session)
    org = platform.get_organization(auth.tenant_id)
    orgs = _build_org_list(platform, auth.user_id) if auth.user_id else []
    return {
        "actor_type": auth.actor_type,
        "actor_id": auth.actor_id,
        "user_id": str(auth.user_id) if auth.user_id else None,
        "email": auth.email,
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
    auth: Annotated[AuthContext, Depends(require_permission(Permission.AUDIT_READ))],
    session: Annotated[Session, Depends(get_db_session)],
) -> list[dict[str, Any]]:
    platform = PlatformRepository(session)
    rows = platform.list_org_members(auth.tenant_id)
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


@router.get("/orgs/service-accounts")
def list_service_accounts(
    auth: Annotated[AuthContext, Depends(require_permission(Permission.KEYS_MANAGE))],
    session: Annotated[Session, Depends(get_db_session)],
) -> list[dict[str, Any]]:
    platform = PlatformRepository(session)
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
        for sa in platform.list_service_accounts(auth.tenant_id)
    ]


@router.post("/orgs/service-accounts", status_code=status.HTTP_201_CREATED)
def create_service_account(
    payload: CreateServiceAccountRequest,
    auth: Annotated[AuthContext, Depends(require_permission(Permission.KEYS_MANAGE))],
    session: Annotated[Session, Depends(get_db_session)],
) -> dict[str, Any]:
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
    auth: Annotated[AuthContext, Depends(require_permission(Permission.KEYS_MANAGE))],
    session: Annotated[Session, Depends(get_db_session)],
) -> list[dict[str, Any]]:
    platform = PlatformRepository(session)
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
        for k in platform.list_api_keys(auth.tenant_id)
    ]


@router.post("/orgs/api-keys", status_code=status.HTTP_201_CREATED)
def issue_api_key(
    payload: CreateApiKeyRequest,
    auth: Annotated[AuthContext, Depends(require_permission(Permission.KEYS_MANAGE))],
    session: Annotated[Session, Depends(get_db_session)],
    settings: Annotated[NexusSettings, Depends(get_app_settings)],
) -> dict[str, Any]:
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
