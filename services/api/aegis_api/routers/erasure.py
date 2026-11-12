"""GDPR / DPDPA data-subject export and crypto-shredding erasure routes."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated, Any
from uuid import UUID

from database import ErasureRequestRow, PlatformRepository
from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from pydantic import BaseModel, ConfigDict, Field
from security import AuthContext, Permission, generate_crypto_shred_marker
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from aegis_api.deps import get_auth_context, get_db_session, require_permission

router = APIRouter(tags=["privacy-erasure"])


class CreateErasureRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    user_id: UUID
    reason: str = Field(default="GDPR_ERASURE", min_length=2, max_length=120)


def _serialize_erasure_request(row: ErasureRequestRow) -> dict[str, Any]:
    return {
        "id": str(row.id),
        "tenant_id": str(row.tenant_id),
        "subject_type": row.subject_type,
        "subject_id": row.subject_id,
        "requested_by": row.requested_by,
        "status": row.status,
        "details": row.details_json,
        "created_at": row.created_at.isoformat(),
        "completed_at": row.completed_at.isoformat() if row.completed_at else None,
    }


@router.get("/privacy/export")
def export_personal_data(
    auth: Annotated[AuthContext, Depends(get_auth_context)],
    session: Annotated[Session, Depends(get_db_session)],
    user_id: UUID | None = None,
) -> dict[str, Any]:
    target_user_id = user_id or auth.user_id
    if target_user_id is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "error_code": "USER_ID_REQUIRED",
                "message": "Specify user_id when exporting data with a non-user credential.",
            },
        )
    if user_id is not None and user_id != auth.user_id:
        auth.require_permission(Permission.PRIVACY_MANAGE)

    platform = PlatformRepository(session)
    user = platform.get_user(target_user_id)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error_code": "USER_NOT_FOUND", "message": "User not found."},
        )

    tenant_membership = platform.get_membership(auth.tenant_id, target_user_id)
    if tenant_membership is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "error_code": "MEMBERSHIP_NOT_FOUND",
                "message": "User does not belong to this organization.",
            },
        )

    org = platform.get_organization(auth.tenant_id)
    erasure_rows = list(
        session.scalars(
            select(ErasureRequestRow)
            .where(
                ErasureRequestRow.tenant_id == auth.tenant_id,
                ErasureRequestRow.subject_id == str(target_user_id),
            )
            .order_by(ErasureRequestRow.created_at.desc())
        ).all()
    )

    memberships_payload: list[dict[str, Any]]
    if target_user_id == auth.user_id:
        memberships_payload = [
            {
                "membership_id": str(m.id),
                "tenant_id": str(t.id),
                "organization_name": t.name,
                "organization_slug": t.slug,
                "role": m.role,
                "status": m.status,
                "created_at": m.created_at.isoformat(),
            }
            for m, t in platform.list_user_memberships(target_user_id)
        ]
    else:
        memberships_payload = [
            {
                "membership_id": str(tenant_membership.id),
                "tenant_id": str(auth.tenant_id),
                "organization_name": org.name if org else None,
                "organization_slug": org.slug if org else None,
                "role": tenant_membership.role,
                "status": tenant_membership.status,
                "created_at": tenant_membership.created_at.isoformat(),
            }
        ]

    platform.record_admin_audit(
        tenant_id=auth.tenant_id,
        actor_type=auth.actor_type,
        actor_id=auth.actor_id,
        action="PRIVACY_DATA_EXPORTED",
        resource_type="user",
        resource_id=str(target_user_id),
    )

    return {
        "exported_at": datetime.now(UTC).isoformat(),
        "tenant_id": str(auth.tenant_id),
        "erasure_status": "ERASED" if user.erased_at is not None else "ACTIVE",
        "user": {
            "id": str(user.id),
            "email": user.email,
            "full_name": user.full_name,
            "is_active": user.is_active,
            "email_verified": user.email_verified,
            "mfa_enabled": user.mfa_enabled,
            "erased_at": user.erased_at.isoformat() if user.erased_at else None,
            "created_at": user.created_at.isoformat(),
        },
        "memberships": memberships_payload,
        "erasure_requests": [_serialize_erasure_request(r) for r in erasure_rows],
    }


@router.get("/privacy/erasure-requests")
def list_erasure_requests(
    response: Response,
    auth: Annotated[AuthContext, Depends(require_permission(Permission.PRIVACY_MANAGE))],
    session: Annotated[Session, Depends(get_db_session)],
    status_filter: Annotated[str | None, Query(alias="status")] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[dict[str, Any]]:
    platform = PlatformRepository(session)
    count_stmt = (
        select(func.count())
        .select_from(ErasureRequestRow)
        .where(ErasureRequestRow.tenant_id == auth.tenant_id)
    )
    if status_filter is not None:
        count_stmt = count_stmt.where(ErasureRequestRow.status == status_filter)
    total = int(session.scalar(count_stmt) or 0)
    response.headers["X-Total-Count"] = str(total)

    rows = platform.list_erasure_requests(
        auth.tenant_id,
        status=status_filter,
        limit=limit,
        offset=offset,
    )
    return [_serialize_erasure_request(row) for row in rows]


@router.post("/privacy/erasure-requests", status_code=status.HTTP_201_CREATED)
def execute_erasure_request(
    payload: CreateErasureRequest,
    auth: Annotated[AuthContext, Depends(require_permission(Permission.PRIVACY_MANAGE))],
    session: Annotated[Session, Depends(get_db_session)],
) -> dict[str, Any]:
    platform = PlatformRepository(session)
    try:
        req = platform.execute_user_erasure(
            tenant_id=auth.tenant_id,
            user_id=payload.user_id,
            requested_by=auth.actor_id,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error_code": "ERASURE_SUBJECT_NOT_FOUND", "message": str(exc)},
        ) from exc

    marker = generate_crypto_shred_marker(
        payload.user_id,
        tenant_id=auth.tenant_id,
        reason=payload.reason,
    )
    req.details_json = {
        **(req.details_json or {}),
        "reason": payload.reason,
        "crypto_shred_marker": marker,
    }
    session.flush()

    platform.record_admin_audit(
        tenant_id=auth.tenant_id,
        actor_type=auth.actor_type,
        actor_id=auth.actor_id,
        action="GDPR_ERASURE_EXECUTED",
        resource_type="erasure_request",
        resource_id=str(req.id),
        details={"subject_user_id": str(payload.user_id), "reason": payload.reason},
    )
    return _serialize_erasure_request(req)
