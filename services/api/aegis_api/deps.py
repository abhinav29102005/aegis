"""Request-scoped dependencies: SQLAlchemy sessions, verified AuthContext, RBAC guards, storage, PayPal client."""

from __future__ import annotations

from collections.abc import Generator
from typing import Annotated
from uuid import UUID

from database import LedgerRepository, PlatformRepository, ServiceAccountRow
from database.storage import ObjectStorage
from fastapi import Depends, Header, HTTPException, Request, status
from paypal import PayPalSandboxClient
from security import (
    AuthContext,
    AuthenticationError,
    NexusSettings,
    Permission,
    Role,
    resolve_permissions,
    verify_access_token,
)
from sqlalchemy.orm import Session

from aegis_api.adapters import SqlAlchemyGhostPayRepository


def get_app_settings(request: Request) -> NexusSettings:
    return request.app.state.settings


def get_db_session(request: Request) -> Generator[Session, None, None]:
    session_factory = request.app.state.session_factory
    session: Session = session_factory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def get_object_storage(request: Request) -> ObjectStorage:
    return request.app.state.object_storage


def get_paypal_client(request: Request) -> PayPalSandboxClient:
    return request.app.state.paypal_client


def get_auth_context(
    request: Request,
    session: Annotated[Session, Depends(get_db_session)],
    settings: Annotated[NexusSettings, Depends(get_app_settings)],
    authorization: Annotated[str | None, Header(alias="Authorization")] = None,
    x_api_key: Annotated[str | None, Header(alias="X-API-Key")] = None,
    x_org_id: Annotated[str | None, Header(alias="X-Org-Id")] = None,
) -> AuthContext:
    """Authenticate caller via verified Bearer JWT or hashed DB API Key.

    Never trusts raw X-Tenant-Id headers as proof of identity.
    If ``X-Org-Id`` is passed with a user session token, server-side membership MUST exist.
    """
    platform = PlatformRepository(session)
    auth_ctx: AuthContext | None = None

    if authorization and authorization.strip().lower().startswith("bearer "):
        raw_token = authorization.strip()[7:].strip()
        try:
            claims = verify_access_token(raw_token, secret=settings.jwt_secret)
        except AuthenticationError as exc:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail={"error_code": "INVALID_TOKEN", "message": str(exc)},
            ) from exc

        user = platform.get_user(claims.sub)
        if user is None or not user.is_active:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail={"error_code": "USER_INACTIVE", "message": "User account is inactive or missing."},
            )

        target_tenant_id = claims.tenant_id
        if x_org_id and x_org_id.strip():
            try:
                target_tenant_id = UUID(x_org_id.strip())
            except ValueError as exc:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail={"error_code": "INVALID_ORG_ID", "message": "Invalid X-Org-Id header."},
                ) from exc

        membership = platform.get_membership(target_tenant_id, user.id)
        if membership is None or membership.status != "ACTIVE":
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail={"error_code": "TENANT_MEMBERSHIP_DENIED", "message": "No active membership in requested organization."},
            )

        role = Role(membership.role)
        auth_ctx = AuthContext(
            tenant_id=target_tenant_id,
            actor_type="USER",
            actor_id=str(user.id),
            user_id=user.id,
            email=user.email,
            role=role,
            permissions=resolve_permissions(role),
            token_id=claims.token_id,
        )

    elif x_api_key and x_api_key.strip():
        key_row = platform.authenticate_api_key(x_api_key.strip(), pepper=settings.signing_secret)
        if key_row is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail={"error_code": "INVALID_API_KEY", "message": "API key is invalid, revoked, or expired."},
            )
        if x_org_id and x_org_id.strip():
            try:
                requested_org = UUID(x_org_id.strip())
            except ValueError as exc:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail={"error_code": "INVALID_ORG_ID", "message": "Invalid X-Org-Id header."},
                ) from exc
            if requested_org != key_row.tenant_id:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail={"error_code": "CROSS_TENANT_API_KEY", "message": "API key cannot access a different organization."},
                )
        if key_row.user_id is not None:
            user = platform.get_user(key_row.user_id)
            if user is None or not user.is_active:
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail={"error_code": "USER_INACTIVE", "message": "User account is inactive or missing."},
                )
            membership = platform.get_membership(key_row.tenant_id, key_row.user_id)
            if membership is None or membership.status != "ACTIVE":
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail={
                        "error_code": "MEMBERSHIP_INACTIVE",
                        "message": "Organization membership is inactive or missing.",
                    },
                )
        if key_row.service_account_id is not None:
            sa = session.get(ServiceAccountRow, key_row.service_account_id)
            if sa is None or sa.status != "ACTIVE":
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail={
                        "error_code": "SERVICE_ACCOUNT_INACTIVE",
                        "message": "Service account is inactive or missing.",
                    },
                )
        role = Role(key_row.role)
        auth_ctx = AuthContext(
            tenant_id=key_row.tenant_id,
            actor_type="API_KEY",
            actor_id=f"key:{key_row.key_prefix}",
            service_account_id=key_row.service_account_id,
            user_id=key_row.user_id,
            api_key_id=key_row.id,
            role=role,
            permissions=resolve_permissions(role, list(key_row.scopes)),
        )

    if auth_ctx is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={
                "error_code": "AUTHENTICATION_REQUIRED",
                "message": "Provide a valid Authorization: Bearer <token> or X-API-Key credential.",
            },
        )

    request.state.authenticated_tenant_id = auth_ctx.tenant_id
    request.state.authenticated_actor_id = auth_ctx.actor_id
    return auth_ctx


def require_tenant_id(auth: Annotated[AuthContext, Depends(get_auth_context)]) -> UUID:
    return auth.tenant_id


def require_ghostpay_read_tenant(
    auth: Annotated[AuthContext, Depends(require_permission(Permission.GHOSTPAY_READ))],
) -> UUID:
    return auth.tenant_id


def require_permission(permission: Permission):
    def _dependency(auth: Annotated[AuthContext, Depends(get_auth_context)]) -> AuthContext:
        auth.require_permission(permission)
        return auth

    return _dependency


def get_ghostpay_repo(
    session: Annotated[Session, Depends(get_db_session)],
) -> SqlAlchemyGhostPayRepository:
    return SqlAlchemyGhostPayRepository(LedgerRepository(session), PlatformRepository(session))
