"""Tenant-scoped platform repository for auth, RBAC, GhostPay investigations, dispute artifacts, webhooks, and worker queues."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

from contracts import (
    PaymentState,
    Tenant,
)
from security import Role, assert_same_tenant, generate_api_key, hash_api_key
from sqlalchemy import and_, func, or_, select
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session

from database.orm import (
    AdminAuditLogRow,
    AgentRow,
    ApiKeyRow,
    ApprovalRecordRow,
    BillingSubscriptionRow,
    DisputeCaseMetadataRow,
    DisputeCaseRow,
    EmailVerificationRow,
    ErasureRequestRow,
    EvidenceArtifactRow,
    GhostPayAgentDnaProfileRow,
    GhostPayTraceRow,
    LlmInvocationLogRow,
    OrganizationMembershipRow,
    OrgInvitationRow,
    OutboxEventRow,
    PaymentAttemptRow,
    PaymentIntentRow,
    PayPalWebhookEventRow,
    ReplayInvestigationRow,
    ServiceAccountRow,
    SpendingPassportRow,
    TenantRow,
    UsageMeterRow,
    UserRow,
    WebhookDeliveryRow,
    WebhookEndpointRow,
)


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _ensure_utc(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    return dt.astimezone(UTC) if dt.tzinfo else dt.replace(tzinfo=UTC)


class PlatformRepository:
    """Tenant-scoped persistence for organizations, RBAC credentials, investigations, artifacts, webhooks, and workers."""

    def __init__(self, session: Session) -> None:
        self.session = session

    def _is_postgres(self) -> bool:
        try:
            bind = self.session.get_bind()
        except SQLAlchemyError:
            bind = self.session.bind
        return bind is not None and bind.dialect.name == "postgresql"

    # ------------------------------------------------------------------
    # Organizations, Users, Memberships
    # ------------------------------------------------------------------
    def create_organization(self, *, name: str, slug: str, org_id: UUID | None = None) -> Tenant:
        clean_slug = slug.strip().lower()
        existing = self.session.scalar(select(TenantRow).where(TenantRow.slug == clean_slug))
        if existing is not None:
            raise ValueError(f"Organization slug '{clean_slug}' already exists")
        now = _utc_now()
        row = TenantRow(id=org_id or uuid4(), name=name.strip(), slug=clean_slug, created_at=now)
        self.session.add(row)
        self.session.flush()
        return Tenant(id=row.id, name=row.name, slug=row.slug, created_at=_ensure_utc(row.created_at))  # type: ignore[arg-type]

    def get_organization(self, tenant_id: UUID) -> Tenant | None:
        row = self.session.get(TenantRow, tenant_id)
        if row is None:
            return None
        return Tenant(id=row.id, name=row.name, slug=row.slug, created_at=_ensure_utc(row.created_at))  # type: ignore[arg-type]

    def update_organization_name(self, tenant_id: UUID, name: str) -> Tenant:
        row = self.session.get(TenantRow, tenant_id)
        if row is None:
            raise ValueError(f"Organization {tenant_id} not found")
        row.name = name.strip()
        self.session.flush()
        return Tenant(id=row.id, name=row.name, slug=row.slug, created_at=_ensure_utc(row.created_at))  # type: ignore[arg-type]

    def create_user(self, *, email: str, full_name: str, password_hash: str, user_id: UUID | None = None) -> UserRow:
        clean_email = email.strip().lower()
        existing = self.get_user_by_email(clean_email)
        if existing is not None:
            raise ValueError(f"User with email '{clean_email}' already exists")
        row = UserRow(
            id=user_id or uuid4(),
            email=clean_email,
            full_name=full_name.strip(),
            password_hash=password_hash,
            is_active=True,
            created_at=_utc_now(),
        )
        self.session.add(row)
        self.session.flush()
        return row

    def get_user(self, user_id: UUID) -> UserRow | None:
        return self.session.get(UserRow, user_id)

    def get_user_by_email(self, email: str) -> UserRow | None:
        return self.session.scalar(select(UserRow).where(UserRow.email == email.strip().lower()))

    def add_membership(self, *, tenant_id: UUID, user_id: UUID, role: Role | str) -> OrganizationMembershipRow:
        role_val = role.value if isinstance(role, Role) else Role(role).value
        existing = self.get_membership(tenant_id, user_id)
        if existing is not None:
            existing.role = role_val
            existing.status = "ACTIVE"
            self.session.flush()
            return existing
        row = OrganizationMembershipRow(
            id=uuid4(),
            tenant_id=tenant_id,
            user_id=user_id,
            role=role_val,
            status="ACTIVE",
            created_at=_utc_now(),
        )
        self.session.add(row)
        self.session.flush()
        return row

    def get_membership(self, tenant_id: UUID, user_id: UUID) -> OrganizationMembershipRow | None:
        return self.session.scalar(
            select(OrganizationMembershipRow).where(
                OrganizationMembershipRow.tenant_id == tenant_id,
                OrganizationMembershipRow.user_id == user_id,
            )
        )

    def list_user_memberships(
        self, user_id: UUID, *, limit: int = 50, offset: int = 0
    ) -> list[tuple[OrganizationMembershipRow, TenantRow]]:
        stmt = (
            select(OrganizationMembershipRow, TenantRow)
            .join(TenantRow, TenantRow.id == OrganizationMembershipRow.tenant_id)
            .where(
                OrganizationMembershipRow.user_id == user_id,
                OrganizationMembershipRow.status == "ACTIVE",
            )
            .order_by(TenantRow.created_at.asc())
            .offset(offset)
            .limit(limit)
        )
        return list(self.session.execute(stmt).all())  # type: ignore[arg-type]

    def list_org_members(
        self, tenant_id: UUID, *, limit: int = 50, offset: int = 0
    ) -> list[tuple[OrganizationMembershipRow, UserRow]]:
        stmt = (
            select(OrganizationMembershipRow, UserRow)
            .join(UserRow, UserRow.id == OrganizationMembershipRow.user_id)
            .where(OrganizationMembershipRow.tenant_id == tenant_id)
            .order_by(OrganizationMembershipRow.created_at.asc())
            .offset(offset)
            .limit(limit)
        )
        return list(self.session.execute(stmt).all())  # type: ignore[arg-type]

    def update_member_role(self, tenant_id: UUID, user_id: UUID, role: Role) -> OrganizationMembershipRow:
        row = self.get_membership(tenant_id, user_id)
        if row is None:
            raise ValueError("Organization membership not found")
        row.role = role.value
        self.session.flush()
        return row

    # ------------------------------------------------------------------
    # Service Accounts & API Keys
    # ------------------------------------------------------------------
    def create_service_account(
        self,
        *,
        tenant_id: UUID,
        name: str,
        description: str = "",
        role: Role = Role.AGENT_SERVICE,
    ) -> ServiceAccountRow:
        existing = self.session.scalar(
            select(ServiceAccountRow).where(
                ServiceAccountRow.tenant_id == tenant_id,
                ServiceAccountRow.name == name.strip(),
            )
        )
        if existing is not None:
            raise ValueError(f"Service account '{name}' already exists")
        row = ServiceAccountRow(
            id=uuid4(),
            tenant_id=tenant_id,
            name=name.strip(),
            description=description.strip(),
            role=role.value,
            status="ACTIVE",
            created_at=_utc_now(),
        )
        self.session.add(row)
        self.session.flush()
        return row

    def list_service_accounts(
        self, tenant_id: UUID, *, limit: int = 50, offset: int = 0
    ) -> list[ServiceAccountRow]:
        return list(
            self.session.scalars(
                select(ServiceAccountRow)
                .where(ServiceAccountRow.tenant_id == tenant_id)
                .order_by(ServiceAccountRow.created_at.desc())
                .offset(offset)
                .limit(limit)
            ).all()
        )

    def create_api_key(
        self,
        *,
        tenant_id: UUID,
        name: str,
        pepper: str,
        environment: str = "live",
        role: Role = Role.AGENT_SERVICE,
        scopes: list[str] | None = None,
        service_account_id: UUID | None = None,
        user_id: UUID | None = None,
        expires_at: datetime | None = None,
    ) -> tuple[ApiKeyRow, str]:
        if service_account_id is not None:
            sa = self.session.get(ServiceAccountRow, service_account_id)
            if sa is None:
                raise ValueError("Service account not found")
            assert_same_tenant(tenant_id, sa.tenant_id, "service_account")

        plaintext, prefix, _ = generate_api_key(environment)
        digest = hash_api_key(plaintext, pepper)
        row = ApiKeyRow(
            id=uuid4(),
            tenant_id=tenant_id,
            service_account_id=service_account_id,
            user_id=user_id,
            name=name.strip(),
            key_prefix=prefix,
            key_hash=digest,
            role=role.value,
            scopes=list(scopes or []),
            status="ACTIVE",
            expires_at=_ensure_utc(expires_at),
            created_at=_utc_now(),
        )
        self.session.add(row)
        self.session.flush()
        return row, plaintext

    def list_api_keys(
        self, tenant_id: UUID, *, limit: int = 50, offset: int = 0
    ) -> list[ApiKeyRow]:
        return list(
            self.session.scalars(
                select(ApiKeyRow)
                .where(ApiKeyRow.tenant_id == tenant_id)
                .order_by(ApiKeyRow.created_at.desc())
                .offset(offset)
                .limit(limit)
            ).all()
        )

    def authenticate_api_key(self, raw_key: str, *, pepper: str) -> ApiKeyRow | None:
        digest = hash_api_key(raw_key.strip(), pepper)
        row = self.session.scalar(select(ApiKeyRow).where(ApiKeyRow.key_hash == digest))
        if row is None or row.status != "ACTIVE":
            return None
        exp = _ensure_utc(row.expires_at)
        if exp is not None and exp <= _utc_now():
            return None
        row.last_used_at = _utc_now()
        self.session.flush()
        return row

    def revoke_api_key(self, tenant_id: UUID, api_key_id: UUID, *, rotated: bool = False) -> ApiKeyRow:
        row = self.session.get(ApiKeyRow, api_key_id)
        if row is None:
            raise ValueError(f"API key {api_key_id} not found")
        assert_same_tenant(tenant_id, row.tenant_id, "api_key")
        if row.status == "ACTIVE":
            row.status = "ROTATED" if rotated else "REVOKED"
            row.revoked_at = _utc_now()
            self.session.flush()
        return row

    def rotate_api_key(
        self,
        *,
        tenant_id: UUID,
        api_key_id: UUID,
        pepper: str,
        environment: str = "live",
    ) -> tuple[ApiKeyRow, str]:
        old = self.session.get(ApiKeyRow, api_key_id)
        if old is None:
            raise ValueError(f"API key {api_key_id} not found")
        assert_same_tenant(tenant_id, old.tenant_id, "api_key")
        self.revoke_api_key(tenant_id, api_key_id, rotated=True)
        return self.create_api_key(
            tenant_id=tenant_id,
            name=old.name,
            pepper=pepper,
            environment=environment,
            role=Role(old.role),
            scopes=list(old.scopes),
            service_account_id=old.service_account_id,
            user_id=old.user_id,
            expires_at=old.expires_at,
        )

    # ------------------------------------------------------------------
    # Admin Audit Logs
    # ------------------------------------------------------------------
    def record_admin_audit(
        self,
        *,
        tenant_id: UUID,
        actor_type: str,
        actor_id: str,
        action: str,
        resource_type: str,
        resource_id: str,
        details: dict[str, Any] | None = None,
        correlation_id: str | None = None,
    ) -> AdminAuditLogRow:
        row = AdminAuditLogRow(
            id=uuid4(),
            tenant_id=tenant_id,
            actor_type=actor_type,
            actor_id=actor_id,
            action=action,
            resource_type=resource_type,
            resource_id=resource_id,
            correlation_id=correlation_id,
            details=details or {},
            occurred_at=_utc_now(),
        )
        self.session.add(row)
        self.session.flush()
        return row

    def list_admin_audits(
        self,
        tenant_id: UUID,
        *,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[AdminAuditLogRow], int]:
        total = self.session.scalar(
            select(func.count()).select_from(AdminAuditLogRow).where(AdminAuditLogRow.tenant_id == tenant_id)
        ) or 0
        rows = list(
            self.session.scalars(
                select(AdminAuditLogRow)
                .where(AdminAuditLogRow.tenant_id == tenant_id)
                .order_by(AdminAuditLogRow.occurred_at.desc())
                .offset(offset)
                .limit(limit)
            ).all()
        )
        return rows, int(total)

    # ------------------------------------------------------------------
    # GhostPay Persisted Investigations
    # ------------------------------------------------------------------
    def save_replay_investigation(
        self,
        *,
        investigation_id: UUID,
        tenant_id: UUID,
        correlation_id: UUID,
        payment_intent_id: UUID,
        policy_version: str,
        mode: str,
        overrides: dict[str, Any],
        result_payload: dict[str, Any],
        consistency_status: str,
        drift_detected: bool,
        integrity_valid: bool,
        created_by: str,
    ) -> ReplayInvestigationRow:
        row = ReplayInvestigationRow(
            id=investigation_id,
            tenant_id=tenant_id,
            correlation_id=correlation_id,
            payment_intent_id=payment_intent_id,
            policy_version=policy_version,
            mode=mode,
            overrides=overrides,
            result_payload=result_payload,
            consistency_status=consistency_status,
            drift_detected=drift_detected,
            integrity_valid=integrity_valid,
            created_by=created_by,
            created_at=_utc_now(),
        )
        self.session.add(row)
        self.session.flush()
        return row

    def get_replay_investigation(self, tenant_id: UUID, investigation_id: UUID) -> ReplayInvestigationRow | None:
        row = self.session.get(ReplayInvestigationRow, investigation_id)
        if row is None:
            return None
        assert_same_tenant(tenant_id, row.tenant_id, "replay_investigation")
        return row

    def list_replay_investigations(
        self,
        tenant_id: UUID,
        *,
        payment_intent_id: UUID | None = None,
        consistency_status: str | None = None,
        drift_detected: bool | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[ReplayInvestigationRow], int]:
        stmt = select(ReplayInvestigationRow).where(ReplayInvestigationRow.tenant_id == tenant_id)
        count_stmt = select(func.count()).select_from(ReplayInvestigationRow).where(
            ReplayInvestigationRow.tenant_id == tenant_id
        )
        if payment_intent_id is not None:
            stmt = stmt.where(ReplayInvestigationRow.payment_intent_id == payment_intent_id)
            count_stmt = count_stmt.where(ReplayInvestigationRow.payment_intent_id == payment_intent_id)
        if consistency_status:
            stmt = stmt.where(ReplayInvestigationRow.consistency_status == consistency_status)
            count_stmt = count_stmt.where(ReplayInvestigationRow.consistency_status == consistency_status)
        if drift_detected is not None:
            stmt = stmt.where(ReplayInvestigationRow.drift_detected == drift_detected)
            count_stmt = count_stmt.where(ReplayInvestigationRow.drift_detected == drift_detected)

        total = int(self.session.scalar(count_stmt) or 0)
        rows = list(
            self.session.scalars(
                stmt.order_by(ReplayInvestigationRow.created_at.desc()).offset(offset).limit(limit)
            ).all()
        )
        return rows, total

    # ------------------------------------------------------------------
    # DisputeOS Metadata, Notes & Binary Artifact Registry
    # ------------------------------------------------------------------
    def _get_or_create_dispute_meta(self, tenant_id: UUID, case_id: UUID) -> DisputeCaseMetadataRow:
        case = self.session.get(DisputeCaseRow, case_id)
        if case is None:
            raise KeyError(f"Dispute case {case_id} not found")
        assert_same_tenant(tenant_id, case.tenant_id, "dispute_case")
        meta = self.session.get(DisputeCaseMetadataRow, case_id)
        if meta is None:
            meta = DisputeCaseMetadataRow(
                dispute_case_id=case_id,
                tenant_id=tenant_id,
                assigned_to=None,
                notes=[],
                retention_until=_utc_now() + timedelta(days=2555),
                updated_at=_utc_now(),
            )
            self.session.add(meta)
            self.session.flush()
        return meta

    def get_dispute_metadata(self, tenant_id: UUID, case_id: UUID) -> DisputeCaseMetadataRow | None:
        meta = self.session.get(DisputeCaseMetadataRow, case_id)
        if meta is None:
            return None
        assert_same_tenant(tenant_id, meta.tenant_id, "dispute_case_metadata")
        return meta

    def assign_dispute_case(self, tenant_id: UUID, case_id: UUID, assignee: str) -> DisputeCaseMetadataRow:
        meta = self._get_or_create_dispute_meta(tenant_id, case_id)
        meta.assigned_to = assignee.strip() or None
        meta.updated_at = _utc_now()
        self.session.flush()
        return meta

    def add_dispute_note(
        self,
        *,
        tenant_id: UUID,
        case_id: UUID,
        author: str,
        body: str,
    ) -> DisputeCaseMetadataRow:
        meta = self._get_or_create_dispute_meta(tenant_id, case_id)
        notes = list(meta.notes or [])
        notes.append({
            "id": str(uuid4()),
            "author": author,
            "body": body.strip(),
            "created_at": _utc_now().isoformat(),
        })
        meta.notes = notes
        meta.updated_at = _utc_now()
        self.session.flush()
        return meta

    def save_evidence_artifact(
        self,
        *,
        artifact_id: UUID,
        tenant_id: UUID,
        evidence_record_id: UUID,
        storage_backend: str,
        object_key: str,
        filename: str,
        content_type: str,
        byte_size: int,
        sha256: str,
    ) -> EvidenceArtifactRow:
        row = EvidenceArtifactRow(
            id=artifact_id,
            tenant_id=tenant_id,
            evidence_record_id=evidence_record_id,
            storage_backend=storage_backend,
            object_key=object_key,
            filename=filename,
            content_type=content_type,
            byte_size=byte_size,
            sha256=sha256,
            created_at=_utc_now(),
        )
        self.session.add(row)
        self.session.flush()
        return row

    def list_evidence_artifacts(
        self,
        tenant_id: UUID,
        evidence_ids: list[UUID] | None = None,
        *,
        limit: int = 50,
        offset: int = 0,
    ) -> list[EvidenceArtifactRow]:
        stmt = select(EvidenceArtifactRow).where(EvidenceArtifactRow.tenant_id == tenant_id)
        if evidence_ids is not None:
            if not evidence_ids:
                return []
            stmt = stmt.where(EvidenceArtifactRow.evidence_record_id.in_(evidence_ids))
        return list(
            self.session.scalars(
                stmt.order_by(EvidenceArtifactRow.created_at.asc()).offset(offset).limit(limit)
            ).all()
        )

    def get_evidence_artifact(self, tenant_id: UUID, artifact_id: UUID) -> EvidenceArtifactRow | None:
        row = self.session.get(EvidenceArtifactRow, artifact_id)
        if row is None:
            return None
        assert_same_tenant(tenant_id, row.tenant_id, "evidence_artifact")
        return row

    # ------------------------------------------------------------------
    # Webhooks & Deliveries
    # ------------------------------------------------------------------
    def create_webhook_endpoint(
        self,
        *,
        tenant_id: UUID,
        url: str,
        description: str,
        signing_secret: str,
        event_types: list[str],
    ) -> WebhookEndpointRow:
        row = WebhookEndpointRow(
            id=uuid4(),
            tenant_id=tenant_id,
            url=url.strip(),
            description=description.strip(),
            signing_secret=signing_secret,
            event_types=list(event_types),
            status="ACTIVE",
            created_at=_utc_now(),
        )
        self.session.add(row)
        self.session.flush()
        return row

    def list_webhook_endpoints(
        self, tenant_id: UUID, *, limit: int = 50, offset: int = 0
    ) -> list[WebhookEndpointRow]:
        return list(
            self.session.scalars(
                select(WebhookEndpointRow)
                .where(WebhookEndpointRow.tenant_id == tenant_id)
                .order_by(WebhookEndpointRow.created_at.desc())
                .offset(offset)
                .limit(limit)
            ).all()
        )

    def revoke_webhook_endpoint(self, tenant_id: UUID, endpoint_id: UUID) -> WebhookEndpointRow:
        row = self.session.get(WebhookEndpointRow, endpoint_id)
        if row is None:
            raise ValueError(f"Webhook endpoint {endpoint_id} not found")
        assert_same_tenant(tenant_id, row.tenant_id, "webhook_endpoint")
        row.status = "DISABLED"
        self.session.flush()
        return row

    def list_webhook_deliveries(
        self, tenant_id: UUID, *, limit: int = 50, offset: int = 0
    ) -> list[WebhookDeliveryRow]:
        return list(
            self.session.scalars(
                select(WebhookDeliveryRow)
                .where(WebhookDeliveryRow.tenant_id == tenant_id)
                .order_by(WebhookDeliveryRow.created_at.desc())
                .offset(offset)
                .limit(limit)
            ).all()
        )

    # ------------------------------------------------------------------
    # Durable Worker Outbox & Overview Queries
    # ------------------------------------------------------------------
    def claim_due_outbox_events(
        self,
        *,
        limit: int = 25,
        now: datetime | None = None,
        worker_id: str = "worker",
        lease_seconds: int = 60,
    ) -> list[OutboxEventRow]:
        ts = _ensure_utc(now) or _utc_now()
        due_pending_or_retry = and_(
            OutboxEventRow.status.in_(["PENDING", "RETRY"]),
            or_(OutboxEventRow.next_retry_at.is_(None), OutboxEventRow.next_retry_at <= ts),
        )
        expired_processing = and_(
            OutboxEventRow.status == "PROCESSING",
            OutboxEventRow.lease_expires_at.is_not(None),
            OutboxEventRow.lease_expires_at < ts,
        )
        stmt = (
            select(OutboxEventRow)
            .where(or_(due_pending_or_retry, expired_processing))
            .order_by(OutboxEventRow.created_at.asc())
            .limit(limit)
        )
        if self._is_postgres():
            stmt = stmt.with_for_update(skip_locked=True)
        rows = list(self.session.scalars(stmt).all())
        lease_exp = ts + timedelta(seconds=lease_seconds)
        for row in rows:
            row.status = "PROCESSING"
            row.locked_at = ts
            row.locked_by = worker_id
            row.lease_expires_at = lease_exp
        self.session.flush()
        return rows

    def mark_outbox_published(self, outbox_id: UUID, *, now: datetime | None = None) -> OutboxEventRow:
        row = self.session.get(OutboxEventRow, outbox_id)
        if row is None:
            raise ValueError(f"Outbox event {outbox_id} not found")
        row.status = "PUBLISHED"
        row.published_at = _ensure_utc(now) or _utc_now()
        row.last_error = None
        row.locked_at = None
        row.lease_expires_at = None
        row.locked_by = None
        self.session.flush()
        return row

    def mark_outbox_delivered(self, outbox_id: UUID, *, now: datetime | None = None) -> OutboxEventRow:
        return self.mark_outbox_published(outbox_id, now=now)

    def mark_outbox_failed(
        self,
        outbox_id: UUID,
        *,
        error_message: str,
        max_attempts: int = 5,
        base_delay_seconds: int = 5,
        now: datetime | None = None,
    ) -> OutboxEventRow:
        row = self.session.get(OutboxEventRow, outbox_id)
        if row is None:
            raise ValueError(f"Outbox event {outbox_id} not found")
        ts = _ensure_utc(now) or _utc_now()
        row.attempts = row.attempts + 1
        row.last_error = error_message[:1000]
        row.locked_at = None
        row.lease_expires_at = None
        row.locked_by = None
        if row.attempts >= max_attempts:
            row.status = "DEAD_LETTER"
            row.dead_lettered_at = ts
            row.next_retry_at = None
        else:
            delay = min(300, base_delay_seconds * (2 ** (row.attempts - 1)))
            row.status = "RETRY"
            row.next_retry_at = ts + timedelta(seconds=delay)
        self.session.flush()
        return row

    def list_outbox_events(
        self,
        tenant_id: UUID,
        *,
        status: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[OutboxEventRow]:
        stmt = select(OutboxEventRow).where(OutboxEventRow.tenant_id == tenant_id)
        if status:
            stmt = stmt.where(OutboxEventRow.status == status)
        return list(
            self.session.scalars(
                stmt.order_by(OutboxEventRow.created_at.desc()).offset(offset).limit(limit)
            ).all()
        )

    def requeue_dead_letter_outbox(
        self, tenant_id: UUID, outbox_id: UUID, *, now: datetime | None = None
    ) -> OutboxEventRow:
        row = self.session.get(OutboxEventRow, outbox_id)
        if row is None:
            raise ValueError(f"Outbox event {outbox_id} not found")
        assert_same_tenant(tenant_id, row.tenant_id, "outbox_event")
        ts = _ensure_utc(now) or _utc_now()
        row.status = "PENDING"
        row.attempts = 0
        row.dead_lettered_at = None
        row.next_retry_at = ts
        row.last_error = None
        row.locked_at = None
        row.lease_expires_at = None
        row.locked_by = None
        self.session.flush()
        return row

    def list_pending_provider_attempts(
        self, *, limit: int = 50, for_update_skip_locked: bool = True
    ) -> list[PaymentAttemptRow]:
        stmt = (
            select(PaymentAttemptRow)
            .where(
                PaymentAttemptRow.state == PaymentState.PENDING_PROVIDER.value,
                PaymentAttemptRow.paypal_order_id.is_not(None),
            )
            .order_by(PaymentAttemptRow.updated_at.asc())
            .limit(limit)
        )
        if for_update_skip_locked and self._is_postgres():
            stmt = stmt.with_for_update(skip_locked=True)
        return list(self.session.scalars(stmt).all())

    def list_pending_capture_attempts(
        self, *, limit: int = 50, for_update_skip_locked: bool = True
    ) -> list[PaymentAttemptRow]:
        return self.list_pending_provider_attempts(
            limit=limit,
            for_update_skip_locked=for_update_skip_locked,
        )

    def get_overview_metrics(self, tenant_id: UUID) -> dict[str, Any]:
        """Compute strictly real tenant-scoped operational metrics from database tables."""
        total_agents = int(
            self.session.scalar(
                select(func.count()).select_from(AgentRow).where(AgentRow.tenant_id == tenant_id)
            )
            or 0
        )
        active_agents = int(
            self.session.scalar(
                select(func.count())
                .select_from(AgentRow)
                .where(AgentRow.tenant_id == tenant_id, AgentRow.status == "ACTIVE")
            )
            or 0
        )
        passports = list(
            self.session.scalars(
                select(SpendingPassportRow).where(SpendingPassportRow.tenant_id == tenant_id)
            ).all()
        )
        total_budget_minor = sum(p.total_budget_minor for p in passports)
        spent_minor = sum(p.spent_minor for p in passports)
        reserved_minor = sum(p.reserved_minor for p in passports)

        state_rows = self.session.execute(
            select(PaymentIntentRow.state, func.count())
            .where(PaymentIntentRow.tenant_id == tenant_id)
            .group_by(PaymentIntentRow.state)
        ).all()
        payments_by_state = {str(state): int(cnt) for state, cnt in state_rows}
        total_payments = sum(payments_by_state.values())

        pending_approvals = int(
            self.session.scalar(
                select(func.count())
                .select_from(ApprovalRecordRow)
                .where(ApprovalRecordRow.tenant_id == tenant_id, ApprovalRecordRow.status == "PENDING")
            )
            or 0
        )
        open_disputes = int(
            self.session.scalar(
                select(func.count())
                .select_from(DisputeCaseRow)
                .where(
                    DisputeCaseRow.tenant_id == tenant_id,
                    DisputeCaseRow.status.notin_(["RESOLVED"]),
                )
            )
            or 0
        )
        drift_or_integrity_alerts = int(
            self.session.scalar(
                select(func.count())
                .select_from(ReplayInvestigationRow)
                .where(
                    ReplayInvestigationRow.tenant_id == tenant_id,
                    or_(
                        ReplayInvestigationRow.drift_detected.is_(True),
                        ReplayInvestigationRow.integrity_valid.is_(False),
                    ),
                )
            )
            or 0
        )
        dead_letter_count = int(
            self.session.scalar(
                select(func.count())
                .select_from(OutboxEventRow)
                .where(OutboxEventRow.tenant_id == tenant_id, OutboxEventRow.status == "DEAD_LETTER")
            )
            or 0
        )

        return {
            "tenant_id": str(tenant_id),
            "agents": {"total": total_agents, "active": active_agents},
            "budget": {
                "total_budget_minor": total_budget_minor,
                "spent_minor": spent_minor,
                "reserved_minor": reserved_minor,
                "available_minor": max(0, total_budget_minor - spent_minor - reserved_minor),
            },
            "payments": {
                "total": total_payments,
                "by_state": payments_by_state,
            },
            "pending_approvals": pending_approvals,
            "open_disputes": open_disputes,
            "risk_alerts": drift_or_integrity_alerts + dead_letter_count,
            "dead_letter_outbox": dead_letter_count,
        }

    # ------------------------------------------------------------------
    # GhostPay Traces, Agent DNA Profiles & LLM Invocation Logs
    # ------------------------------------------------------------------
    def save_ghostpay_trace(
        self,
        tenant_id: UUID,
        trace_id: str,
        agent_id: str | UUID,
        payload_json: dict[str, Any],
        recorded_decision_json: dict[str, Any] | None = None,
        correlation_id: str | UUID = "",
    ) -> GhostPayTraceRow:
        row = self.session.scalar(
            select(GhostPayTraceRow).where(
                GhostPayTraceRow.tenant_id == tenant_id,
                GhostPayTraceRow.trace_id == trace_id,
            )
        )
        if row is None:
            row = GhostPayTraceRow(
                id=uuid4(),
                tenant_id=tenant_id,
                trace_id=trace_id,
                agent_id=str(agent_id),
                correlation_id=str(correlation_id or ""),
                payload_json=dict(payload_json),
                recorded_decision_json=dict(recorded_decision_json) if recorded_decision_json is not None else None,
                created_at=_utc_now(),
            )
            self.session.add(row)
        else:
            row.agent_id = str(agent_id)
            row.correlation_id = str(correlation_id or "")
            row.payload_json = dict(payload_json)
            row.recorded_decision_json = (
                dict(recorded_decision_json) if recorded_decision_json is not None else None
            )
        self.session.flush()
        return row

    def list_ghostpay_traces(
        self,
        tenant_id: UUID,
        agent_id: str | UUID | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[GhostPayTraceRow]:
        stmt = select(GhostPayTraceRow).where(GhostPayTraceRow.tenant_id == tenant_id)
        if agent_id is not None:
            stmt = stmt.where(GhostPayTraceRow.agent_id == str(agent_id))
        return list(
            self.session.scalars(
                stmt.order_by(GhostPayTraceRow.created_at.desc()).offset(offset).limit(limit)
            ).all()
        )

    def get_ghostpay_trace(self, tenant_id: UUID, trace_id: str) -> GhostPayTraceRow | None:
        return self.session.scalar(
            select(GhostPayTraceRow).where(
                GhostPayTraceRow.tenant_id == tenant_id,
                GhostPayTraceRow.trace_id == trace_id,
            )
        )

    def save_agent_dna_profile(
        self,
        tenant_id: UUID,
        agent_id: str | UUID,
        profile_json: dict[str, Any],
    ) -> GhostPayAgentDnaProfileRow:
        agent_key = str(agent_id)
        row = self.session.scalar(
            select(GhostPayAgentDnaProfileRow).where(
                GhostPayAgentDnaProfileRow.tenant_id == tenant_id,
                GhostPayAgentDnaProfileRow.agent_id == agent_key,
            )
        )
        now = _utc_now()
        if row is None:
            row = GhostPayAgentDnaProfileRow(
                id=uuid4(),
                tenant_id=tenant_id,
                agent_id=agent_key,
                profile_json=dict(profile_json),
                updated_at=now,
            )
            self.session.add(row)
        else:
            row.profile_json = dict(profile_json)
            row.updated_at = now
        self.session.flush()
        return row

    def get_agent_dna_profile(
        self, tenant_id: UUID, agent_id: str | UUID
    ) -> GhostPayAgentDnaProfileRow | None:
        return self.session.scalar(
            select(GhostPayAgentDnaProfileRow).where(
                GhostPayAgentDnaProfileRow.tenant_id == tenant_id,
                GhostPayAgentDnaProfileRow.agent_id == str(agent_id),
            )
        )

    def log_llm_invocation(
        self,
        tenant_id: UUID,
        correlation_id: str | UUID,
        module: str,
        provider: str,
        model: str,
        prompt_tokens: int,
        completion_tokens: int,
        estimated_cost_usd_micros: int,
    ) -> LlmInvocationLogRow:
        row = LlmInvocationLogRow(
            id=uuid4(),
            tenant_id=tenant_id,
            correlation_id=str(correlation_id),
            module=module,
            provider=provider,
            model=model,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            estimated_cost_usd_micros=estimated_cost_usd_micros,
            created_at=_utc_now(),
        )
        self.session.add(row)
        self.session.flush()
        return row

    def list_llm_invocations(
        self,
        tenant_id: UUID,
        *,
        correlation_id: str | UUID | None = None,
        module: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[LlmInvocationLogRow]:
        stmt = select(LlmInvocationLogRow).where(LlmInvocationLogRow.tenant_id == tenant_id)
        if correlation_id is not None:
            stmt = stmt.where(LlmInvocationLogRow.correlation_id == str(correlation_id))
        if module is not None:
            stmt = stmt.where(LlmInvocationLogRow.module == module)
        return list(
            self.session.scalars(
                stmt.order_by(LlmInvocationLogRow.created_at.desc()).offset(offset).limit(limit)
            ).all()
        )

    # ------------------------------------------------------------------
    # PayPal Webhook Idempotent Deduplication
    # ------------------------------------------------------------------
    def record_paypal_webhook_once(
        self,
        event_id: str,
        event_type: str,
        resource_id: str | None,
        payload_hash: str,
    ) -> bool:
        """Atomically record a PayPal webhook event_id; returns True if new, False if duplicate."""
        existing = self.session.scalar(
            select(PayPalWebhookEventRow.id).where(PayPalWebhookEventRow.event_id == event_id)
        )
        if existing is not None:
            return False
        row = PayPalWebhookEventRow(
            id=uuid4(),
            event_id=event_id,
            event_type=event_type,
            resource_id=resource_id,
            payload_hash=payload_hash,
            received_at=_utc_now(),
        )
        try:
            with self.session.begin_nested():
                self.session.add(row)
                self.session.flush()
            return True
        except IntegrityError:
            return False

    # ------------------------------------------------------------------
    # Invitations, Email Verifications & MFA Helpers
    # ------------------------------------------------------------------
    def create_org_invitation(
        self,
        *,
        tenant_id: UUID,
        email: str,
        role: Role | str,
        token_hash: str,
        expires_at: datetime,
        invited_by_user_id: UUID | None = None,
    ) -> OrgInvitationRow:
        role_val = role.value if isinstance(role, Role) else Role(role).value
        row = OrgInvitationRow(
            id=uuid4(),
            tenant_id=tenant_id,
            email=email.strip().lower(),
            role=role_val,
            token_hash=token_hash,
            invited_by_user_id=invited_by_user_id,
            status="PENDING",
            expires_at=_ensure_utc(expires_at) or _utc_now(),
            accepted_at=None,
            created_at=_utc_now(),
        )
        self.session.add(row)
        self.session.flush()
        return row

    def list_org_invitations(
        self,
        tenant_id: UUID,
        *,
        status: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[OrgInvitationRow]:
        stmt = select(OrgInvitationRow).where(OrgInvitationRow.tenant_id == tenant_id)
        if status is not None:
            stmt = stmt.where(OrgInvitationRow.status == status)
        return list(
            self.session.scalars(
                stmt.order_by(OrgInvitationRow.created_at.desc()).offset(offset).limit(limit)
            ).all()
        )

    def get_org_invitation_by_token_hash(self, token_hash: str) -> OrgInvitationRow | None:
        return self.session.scalar(
            select(OrgInvitationRow).where(OrgInvitationRow.token_hash == token_hash)
        )

    def accept_org_invitation(
        self, token_hash: str, *, user_id: UUID, now: datetime | None = None
    ) -> OrgInvitationRow:
        row = self.get_org_invitation_by_token_hash(token_hash)
        if row is None:
            raise ValueError("Invitation not found")
        if row.status != "PENDING":
            raise ValueError(f"Invitation is not pending (status={row.status})")
        ts = _ensure_utc(now) or _utc_now()
        exp = _ensure_utc(row.expires_at)
        if exp is not None and exp <= ts:
            row.status = "EXPIRED"
            self.session.flush()
            raise ValueError("Invitation has expired")
        row.status = "ACCEPTED"
        row.accepted_at = ts
        self.add_membership(tenant_id=row.tenant_id, user_id=user_id, role=row.role)
        self.session.flush()
        return row

    def revoke_org_invitation(self, tenant_id: UUID, invitation_id: UUID) -> OrgInvitationRow:
        row = self.session.get(OrgInvitationRow, invitation_id)
        if row is None:
            raise ValueError(f"Invitation {invitation_id} not found")
        assert_same_tenant(tenant_id, row.tenant_id, "org_invitation")
        if row.status == "PENDING":
            row.status = "REVOKED"
            self.session.flush()
        return row

    def create_email_verification(
        self,
        *,
        user_id: UUID,
        email: str,
        token_hash: str,
        expires_at: datetime,
    ) -> EmailVerificationRow:
        row = EmailVerificationRow(
            id=uuid4(),
            user_id=user_id,
            email=email.strip().lower(),
            token_hash=token_hash,
            expires_at=_ensure_utc(expires_at) or _utc_now(),
            verified_at=None,
            created_at=_utc_now(),
        )
        self.session.add(row)
        self.session.flush()
        return row

    def verify_email_token(
        self, token_hash: str, *, now: datetime | None = None
    ) -> EmailVerificationRow:
        row = self.session.scalar(
            select(EmailVerificationRow).where(EmailVerificationRow.token_hash == token_hash)
        )
        if row is None:
            raise ValueError("Email verification token not found")
        if row.verified_at is not None:
            return row
        ts = _ensure_utc(now) or _utc_now()
        exp = _ensure_utc(row.expires_at)
        if exp is not None and exp <= ts:
            raise ValueError("Email verification token has expired")
        row.verified_at = ts
        user = self.session.get(UserRow, row.user_id)
        if user is not None:
            user.email_verified = True
        self.session.flush()
        return row

    def set_user_mfa(
        self, user_id: UUID, *, enabled: bool, mfa_secret_encrypted: str | None = None
    ) -> UserRow:
        user = self.session.get(UserRow, user_id)
        if user is None:
            raise ValueError(f"User {user_id} not found")
        user.mfa_enabled = enabled
        if mfa_secret_encrypted is not None or not enabled:
            user.mfa_secret_encrypted = mfa_secret_encrypted if enabled else None
        self.session.flush()
        return user

    # ------------------------------------------------------------------
    # Billing Subscriptions & Usage Metering
    # ------------------------------------------------------------------
    def get_billing_subscription(self, tenant_id: UUID) -> BillingSubscriptionRow | None:
        return self.session.scalar(
            select(BillingSubscriptionRow).where(BillingSubscriptionRow.tenant_id == tenant_id)
        )

    def upsert_billing_subscription(
        self,
        *,
        tenant_id: UUID,
        plan: str = "FREE",
        status: str = "ACTIVE",
        stripe_customer_id: str | None = None,
        stripe_subscription_id: str | None = None,
        monthly_tx_quota: int = 100,
    ) -> BillingSubscriptionRow:
        clean_plan = plan.strip().upper()
        if clean_plan not in {"FREE", "PRO", "ENTERPRISE"}:
            raise ValueError(f"Unsupported billing plan: {plan}")
        now = _utc_now()
        row = self.get_billing_subscription(tenant_id)
        if row is None:
            row = BillingSubscriptionRow(
                id=uuid4(),
                tenant_id=tenant_id,
                plan=clean_plan,
                status=status.strip().upper(),
                stripe_customer_id=stripe_customer_id,
                stripe_subscription_id=stripe_subscription_id,
                monthly_tx_quota=monthly_tx_quota,
                updated_at=now,
                created_at=now,
            )
            self.session.add(row)
        else:
            row.plan = clean_plan
            row.status = status.strip().upper()
            if stripe_customer_id is not None:
                row.stripe_customer_id = stripe_customer_id
            if stripe_subscription_id is not None:
                row.stripe_subscription_id = stripe_subscription_id
            row.monthly_tx_quota = monthly_tx_quota
            row.updated_at = now
        self.session.flush()
        return row

    def increment_usage_meter(
        self, *, tenant_id: UUID, period_ym: str, metric: str, amount: int = 1
    ) -> UsageMeterRow:
        if amount < 0:
            raise ValueError("Usage meter increment amount must be non-negative")
        now = _utc_now()
        stmt = select(UsageMeterRow).where(
            UsageMeterRow.tenant_id == tenant_id,
            UsageMeterRow.period_ym == period_ym,
            UsageMeterRow.metric == metric,
        )
        if self._is_postgres():
            stmt = stmt.with_for_update()
        row = self.session.scalar(stmt)
        if row is None:
            row = UsageMeterRow(
                id=uuid4(),
                tenant_id=tenant_id,
                period_ym=period_ym,
                metric=metric,
                count=amount,
                updated_at=now,
            )
            self.session.add(row)
        else:
            row.count = row.count + amount
            row.updated_at = now
        self.session.flush()
        return row

    def get_usage_meter(self, tenant_id: UUID, *, period_ym: str, metric: str) -> int:
        row = self.session.scalar(
            select(UsageMeterRow).where(
                UsageMeterRow.tenant_id == tenant_id,
                UsageMeterRow.period_ym == period_ym,
                UsageMeterRow.metric == metric,
            )
        )
        return int(row.count) if row is not None else 0

    def list_usage_meters(
        self,
        tenant_id: UUID,
        *,
        period_ym: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[UsageMeterRow]:
        stmt = select(UsageMeterRow).where(UsageMeterRow.tenant_id == tenant_id)
        if period_ym is not None:
            stmt = stmt.where(UsageMeterRow.period_ym == period_ym)
        return list(
            self.session.scalars(
                stmt.order_by(UsageMeterRow.period_ym.desc(), UsageMeterRow.metric.asc())
                .offset(offset)
                .limit(limit)
            ).all()
        )

    # ------------------------------------------------------------------
    # GDPR Erasure Requests & PII Anonymization (Preserves Financial Ledger)
    # ------------------------------------------------------------------
    def create_erasure_request(
        self,
        *,
        tenant_id: UUID,
        subject_type: str,
        subject_id: str,
        requested_by: str | None = None,
        details_json: dict[str, Any] | None = None,
    ) -> ErasureRequestRow:
        row = ErasureRequestRow(
            id=uuid4(),
            tenant_id=tenant_id,
            subject_type=subject_type,
            subject_id=subject_id,
            requested_by=requested_by,
            status="PENDING",
            details_json=dict(details_json or {}),
            created_at=_utc_now(),
            completed_at=None,
        )
        self.session.add(row)
        self.session.flush()
        return row

    def list_erasure_requests(
        self,
        tenant_id: UUID,
        *,
        status: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[ErasureRequestRow]:
        stmt = select(ErasureRequestRow).where(ErasureRequestRow.tenant_id == tenant_id)
        if status is not None:
            stmt = stmt.where(ErasureRequestRow.status == status)
        return list(
            self.session.scalars(
                stmt.order_by(ErasureRequestRow.created_at.desc()).offset(offset).limit(limit)
            ).all()
        )

    def execute_user_erasure(
        self,
        *,
        tenant_id: UUID,
        user_id: UUID,
        requested_by: str | None = None,
    ) -> ErasureRequestRow:
        """Redact UserRow PII & revoke tenant credentials while keeping immutable financial_events intact."""
        now = _utc_now()
        user = self.session.get(UserRow, user_id)
        if user is None:
            raise ValueError(f"User {user_id} not found")
        membership = self.get_membership(tenant_id, user_id)
        if membership is None:
            raise ValueError(f"User {user_id} is not a member of tenant {tenant_id}")

        original_email = user.email
        user.email = f"erased-{user.id}@redacted.local"
        user.full_name = "ERASED_USER"
        user.password_hash = "ERASED"
        user.is_active = False
        user.email_verified = False
        user.mfa_enabled = False
        user.mfa_secret_encrypted = None
        user.erased_at = now

        membership.status = "ERASED"

        user_keys = list(
            self.session.scalars(
                select(ApiKeyRow).where(
                    ApiKeyRow.tenant_id == tenant_id,
                    ApiKeyRow.user_id == user_id,
                    ApiKeyRow.status == "ACTIVE",
                )
            ).all()
        )
        for key in user_keys:
            key.status = "REVOKED"
            key.revoked_at = now

        pending_invites = list(
            self.session.scalars(
                select(OrgInvitationRow).where(
                    OrgInvitationRow.tenant_id == tenant_id,
                    OrgInvitationRow.email == original_email,
                    OrgInvitationRow.status == "PENDING",
                )
            ).all()
        )
        for inv in pending_invites:
            inv.status = "REVOKED"

        req = ErasureRequestRow(
            id=uuid4(),
            tenant_id=tenant_id,
            subject_type="USER",
            subject_id=str(user_id),
            requested_by=requested_by,
            status="COMPLETED",
            details_json={
                "redacted_fields": ["email", "full_name", "password_hash", "mfa_secret_encrypted"],
                "revoked_api_keys": len(user_keys),
                "revoked_invitations": len(pending_invites),
                "ledger_preserved": True,
            },
            created_at=now,
            completed_at=now,
        )
        self.session.add(req)
        self.session.flush()
        return req
