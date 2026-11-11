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
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from database.orm import (
    AdminAuditLogRow,
    AgentRow,
    ApiKeyRow,
    ApprovalRecordRow,
    DisputeCaseMetadataRow,
    DisputeCaseRow,
    EvidenceArtifactRow,
    OrganizationMembershipRow,
    OutboxEventRow,
    PaymentAttemptRow,
    PaymentIntentRow,
    ReplayInvestigationRow,
    ServiceAccountRow,
    SpendingPassportRow,
    TenantRow,
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

    def list_user_memberships(self, user_id: UUID) -> list[tuple[OrganizationMembershipRow, TenantRow]]:
        stmt = (
            select(OrganizationMembershipRow, TenantRow)
            .join(TenantRow, TenantRow.id == OrganizationMembershipRow.tenant_id)
            .where(
                OrganizationMembershipRow.user_id == user_id,
                OrganizationMembershipRow.status == "ACTIVE",
            )
            .order_by(TenantRow.created_at.asc())
        )
        return list(self.session.execute(stmt).all())  # type: ignore[arg-type]

    def list_org_members(self, tenant_id: UUID) -> list[tuple[OrganizationMembershipRow, UserRow]]:
        stmt = (
            select(OrganizationMembershipRow, UserRow)
            .join(UserRow, UserRow.id == OrganizationMembershipRow.user_id)
            .where(OrganizationMembershipRow.tenant_id == tenant_id)
            .order_by(OrganizationMembershipRow.created_at.asc())
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

    def list_service_accounts(self, tenant_id: UUID) -> list[ServiceAccountRow]:
        return list(
            self.session.scalars(
                select(ServiceAccountRow)
                .where(ServiceAccountRow.tenant_id == tenant_id)
                .order_by(ServiceAccountRow.created_at.desc())
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

    def list_api_keys(self, tenant_id: UUID) -> list[ApiKeyRow]:
        return list(
            self.session.scalars(
                select(ApiKeyRow)
                .where(ApiKeyRow.tenant_id == tenant_id)
                .order_by(ApiKeyRow.created_at.desc())
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

    def list_evidence_artifacts(self, tenant_id: UUID, evidence_ids: list[UUID] | None = None) -> list[EvidenceArtifactRow]:
        stmt = select(EvidenceArtifactRow).where(EvidenceArtifactRow.tenant_id == tenant_id)
        if evidence_ids is not None:
            if not evidence_ids:
                return []
            stmt = stmt.where(EvidenceArtifactRow.evidence_record_id.in_(evidence_ids))
        return list(self.session.scalars(stmt.order_by(EvidenceArtifactRow.created_at.asc())).all())

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

    def list_webhook_endpoints(self, tenant_id: UUID) -> list[WebhookEndpointRow]:
        return list(
            self.session.scalars(
                select(WebhookEndpointRow)
                .where(WebhookEndpointRow.tenant_id == tenant_id)
                .order_by(WebhookEndpointRow.created_at.desc())
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

    def list_webhook_deliveries(self, tenant_id: UUID, *, limit: int = 50) -> list[WebhookDeliveryRow]:
        return list(
            self.session.scalars(
                select(WebhookDeliveryRow)
                .where(WebhookDeliveryRow.tenant_id == tenant_id)
                .order_by(WebhookDeliveryRow.created_at.desc())
                .limit(limit)
            ).all()
        )

    # ------------------------------------------------------------------
    # Durable Worker Outbox & Overview Queries
    # ------------------------------------------------------------------
    def claim_due_outbox_events(self, *, limit: int = 25, now: datetime | None = None) -> list[OutboxEventRow]:
        ts = now or _utc_now()
        stmt = (
            select(OutboxEventRow)
            .where(
                OutboxEventRow.status.in_(["PENDING", "RETRY"]),
                or_(OutboxEventRow.next_retry_at.is_(None), OutboxEventRow.next_retry_at <= ts),
            )
            .order_by(OutboxEventRow.created_at.asc())
            .limit(limit)
        )
        if self.session.bind is not None and self.session.bind.dialect.name == "postgresql":
            stmt = stmt.with_for_update(skip_locked=True)
        rows = list(self.session.scalars(stmt).all())
        for row in rows:
            row.status = "PROCESSING"
        self.session.flush()
        return rows

    def mark_outbox_published(self, outbox_id: UUID, *, now: datetime | None = None) -> OutboxEventRow:
        row = self.session.get(OutboxEventRow, outbox_id)
        if row is None:
            raise ValueError(f"Outbox event {outbox_id} not found")
        row.status = "PUBLISHED"
        row.published_at = now or _utc_now()
        row.last_error = None
        self.session.flush()
        return row

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
        ts = now or _utc_now()
        row.attempts = row.attempts + 1
        row.last_error = error_message[:1000]
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
    ) -> list[OutboxEventRow]:
        stmt = select(OutboxEventRow).where(OutboxEventRow.tenant_id == tenant_id)
        if status:
            stmt = stmt.where(OutboxEventRow.status == status)
        return list(
            self.session.scalars(stmt.order_by(OutboxEventRow.created_at.desc()).limit(limit)).all()
        )

    def requeue_dead_letter_outbox(self, tenant_id: UUID, outbox_id: UUID) -> OutboxEventRow:
        row = self.session.get(OutboxEventRow, outbox_id)
        if row is None:
            raise ValueError(f"Outbox event {outbox_id} not found")
        assert_same_tenant(tenant_id, row.tenant_id, "outbox_event")
        row.status = "PENDING"
        row.dead_lettered_at = None
        row.next_retry_at = None
        row.last_error = None
        self.session.flush()
        return row

    def list_pending_provider_attempts(self, *, limit: int = 50) -> list[PaymentAttemptRow]:
        return list(
            self.session.scalars(
                select(PaymentAttemptRow)
                .where(
                    PaymentAttemptRow.state == PaymentState.PENDING_PROVIDER.value,
                    PaymentAttemptRow.paypal_order_id.is_not(None),
                )
                .order_by(PaymentAttemptRow.updated_at.asc())
                .limit(limit)
            ).all()
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
