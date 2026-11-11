"""Add multi-tenant auth, RBAC, GhostPay investigations, dispute metadata, artifacts, webhooks, and worker retry fields.

Revision ID: 0002_aegis_platform_extensions
Revises: 0001_initial_schema
Create Date: 2026-11-12
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from database.orm import (
    AdminAuditLogRow,
    ApiKeyRow,
    DisputeCaseMetadataRow,
    EvidenceArtifactRow,
    OrganizationMembershipRow,
    ReplayInvestigationRow,
    ServiceAccountRow,
    UserRow,
    WebhookDeliveryRow,
    WebhookEndpointRow,
)

revision = "0002_aegis_platform_extensions"
down_revision = "0001_initial_schema"
branch_labels = None
depends_on = None

_NEW_TABLES = [
    UserRow.__table__,
    OrganizationMembershipRow.__table__,
    ServiceAccountRow.__table__,
    ApiKeyRow.__table__,
    AdminAuditLogRow.__table__,
    ReplayInvestigationRow.__table__,
    DisputeCaseMetadataRow.__table__,
    EvidenceArtifactRow.__table__,
    WebhookEndpointRow.__table__,
    WebhookDeliveryRow.__table__,
]


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing_tables = set(inspector.get_table_names())

    for table in _NEW_TABLES:
        if table.name not in existing_tables:
            table.create(bind=bind)

    if "outbox_events" in existing_tables:
        existing_cols = {col["name"] for col in inspector.get_columns("outbox_events")}
        if "next_retry_at" not in existing_cols:
            op.add_column("outbox_events", sa.Column("next_retry_at", sa.DateTime(timezone=True), nullable=True))
            op.create_index("ix_outbox_events_next_retry_at", "outbox_events", ["next_retry_at"])
        if "last_error" not in existing_cols:
            op.add_column("outbox_events", sa.Column("last_error", sa.Text(), nullable=True))
        if "dead_lettered_at" not in existing_cols:
            op.add_column("outbox_events", sa.Column("dead_lettered_at", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing_tables = set(inspector.get_table_names())

    if "outbox_events" in existing_tables:
        existing_cols = {col["name"] for col in inspector.get_columns("outbox_events")}
        if "dead_lettered_at" in existing_cols:
            op.drop_column("outbox_events", "dead_lettered_at")
        if "last_error" in existing_cols:
            op.drop_column("outbox_events", "last_error")
        if "next_retry_at" in existing_cols:
            op.drop_index("ix_outbox_events_next_retry_at", table_name="outbox_events")
            op.drop_column("outbox_events", "next_retry_at")

    for table in reversed(_NEW_TABLES):
        if table.name in existing_tables:
            table.drop(bind=bind)
