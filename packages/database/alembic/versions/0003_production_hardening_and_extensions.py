"""Production hardening extensions, outbox leasing, passport snapshots, GhostPay traces, billing/GDPR, and PG audit triggers.

Revision ID: 0003_prod_hardening
Revises: 0002_aegis_platform_extensions
Create Date: 2026-11-12
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from database.orm import (
    PG_AUDIT_TRIGGER_CREATE_SQL,
    PG_AUDIT_TRIGGER_DROP_SQL,
    PG_AUDIT_TRIGGER_FUNCTION_SQL,
    BillingSubscriptionRow,
    EmailVerificationRow,
    ErasureRequestRow,
    GhostPayAgentDnaProfileRow,
    GhostPayTraceRow,
    LlmInvocationLogRow,
    OrgInvitationRow,
    PayPalWebhookEventRow,
    SpendingPassportSnapshotRow,
    UsageMeterRow,
)

revision = "0003_prod_hardening"
down_revision = "0002_aegis_platform_extensions"
branch_labels = None
depends_on = None

_NEW_TABLES = [
    SpendingPassportSnapshotRow.__table__,
    GhostPayTraceRow.__table__,
    GhostPayAgentDnaProfileRow.__table__,
    LlmInvocationLogRow.__table__,
    PayPalWebhookEventRow.__table__,
    OrgInvitationRow.__table__,
    EmailVerificationRow.__table__,
    BillingSubscriptionRow.__table__,
    UsageMeterRow.__table__,
    ErasureRequestRow.__table__,
]


def _add_column_if_missing(
    table_name: str,
    col_name: str,
    column: sa.Column,
    existing_cols: set[str],
) -> None:
    if col_name not in existing_cols:
        op.add_column(table_name, column)


def _create_index_if_missing(
    index_name: str,
    table_name: str,
    columns: list[str],
    existing_indexes: set[str],
) -> None:
    if index_name not in existing_indexes:
        op.create_index(index_name, table_name, columns)


def _drop_index_if_exists(
    index_name: str,
    table_name: str,
    existing_indexes: set[str],
) -> None:
    if index_name in existing_indexes:
        op.drop_index(index_name, table_name=table_name)


def _drop_column_if_exists(
    table_name: str,
    col_name: str,
    existing_cols: set[str],
) -> None:
    if col_name in existing_cols:
        op.drop_column(table_name, col_name)


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing_tables = set(inspector.get_table_names())

    for table in _NEW_TABLES:
        if table.name not in existing_tables:
            table.create(bind=bind)

    if "outbox_events" in existing_tables:
        cols = {col["name"] for col in inspector.get_columns("outbox_events")}
        idxs = {idx["name"] for idx in inspector.get_indexes("outbox_events")}
        _add_column_if_missing(
            "outbox_events", "locked_at", sa.Column("locked_at", sa.DateTime(timezone=True), nullable=True), cols
        )
        _add_column_if_missing(
            "outbox_events",
            "lease_expires_at",
            sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True),
            cols,
        )
        _add_column_if_missing(
            "outbox_events", "locked_by", sa.Column("locked_by", sa.String(128), nullable=True), cols
        )
        _create_index_if_missing(
            "ix_outbox_events_status_lease_expires_at",
            "outbox_events",
            ["status", "lease_expires_at"],
            idxs,
        )

    if "authorization_decisions" in existing_tables:
        cols = {col["name"] for col in inspector.get_columns("authorization_decisions")}
        idxs = {idx["name"] for idx in inspector.get_indexes("authorization_decisions")}
        _add_column_if_missing(
            "authorization_decisions",
            "passport_snapshot_id",
            sa.Column("passport_snapshot_id", sa.String(64), nullable=True),
            cols,
        )
        _create_index_if_missing(
            "ix_authorization_decisions_passport_snapshot_id",
            "authorization_decisions",
            ["passport_snapshot_id"],
            idxs,
        )

    if "dispute_cases" in existing_tables:
        cols = {col["name"] for col in inspector.get_columns("dispute_cases")}
        _add_column_if_missing(
            "dispute_cases",
            "response_due_by",
            sa.Column("response_due_by", sa.DateTime(timezone=True), nullable=True),
            cols,
        )
        _add_column_if_missing(
            "dispute_cases",
            "resolved_at",
            sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
            cols,
        )
        _add_column_if_missing(
            "dispute_cases",
            "resolution_outcome",
            sa.Column("resolution_outcome", sa.String(64), nullable=True),
            cols,
        )
        _add_column_if_missing(
            "dispute_cases",
            "external_status",
            sa.Column("external_status", sa.String(64), nullable=True),
            cols,
        )

    if "users" in existing_tables:
        cols = {col["name"] for col in inspector.get_columns("users")}
        _add_column_if_missing(
            "users",
            "email_verified",
            sa.Column("email_verified", sa.Boolean(), nullable=False, server_default=sa.false()),
            cols,
        )
        _add_column_if_missing(
            "users",
            "mfa_enabled",
            sa.Column("mfa_enabled", sa.Boolean(), nullable=False, server_default=sa.false()),
            cols,
        )
        _add_column_if_missing(
            "users",
            "mfa_secret_encrypted",
            sa.Column("mfa_secret_encrypted", sa.Text(), nullable=True),
            cols,
        )
        _add_column_if_missing(
            "users",
            "erased_at",
            sa.Column("erased_at", sa.DateTime(timezone=True), nullable=True),
            cols,
        )

    if bind.dialect.name == "postgresql":
        op.execute(PG_AUDIT_TRIGGER_FUNCTION_SQL)
        op.execute(PG_AUDIT_TRIGGER_DROP_SQL)
        op.execute(PG_AUDIT_TRIGGER_CREATE_SQL)


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute("DROP TRIGGER IF EXISTS trg_aegis_prevent_financial_event_mutation ON financial_events;")
        op.execute("DROP FUNCTION IF EXISTS aegis_prevent_financial_event_mutation();")

    inspector = sa.inspect(bind)
    existing_tables = set(inspector.get_table_names())

    if "users" in existing_tables:
        cols = {col["name"] for col in inspector.get_columns("users")}
        for col_name in ("erased_at", "mfa_secret_encrypted", "mfa_enabled", "email_verified"):
            _drop_column_if_exists("users", col_name, cols)

    if "dispute_cases" in existing_tables:
        cols = {col["name"] for col in inspector.get_columns("dispute_cases")}
        for col_name in ("external_status", "resolution_outcome", "resolved_at", "response_due_by"):
            _drop_column_if_exists("dispute_cases", col_name, cols)

    if "authorization_decisions" in existing_tables:
        cols = {col["name"] for col in inspector.get_columns("authorization_decisions")}
        idxs = {idx["name"] for idx in inspector.get_indexes("authorization_decisions")}
        _drop_index_if_exists("ix_authorization_decisions_passport_snapshot_id", "authorization_decisions", idxs)
        _drop_column_if_exists("authorization_decisions", "passport_snapshot_id", cols)

    if "outbox_events" in existing_tables:
        cols = {col["name"] for col in inspector.get_columns("outbox_events")}
        idxs = {idx["name"] for idx in inspector.get_indexes("outbox_events")}
        _drop_index_if_exists("ix_outbox_events_status_lease_expires_at", "outbox_events", idxs)
        for col_name in ("locked_by", "lease_expires_at", "locked_at"):
            _drop_column_if_exists("outbox_events", col_name, cols)

    for table in reversed(_NEW_TABLES):
        if table.name in existing_tables:
            table.drop(bind=bind)

