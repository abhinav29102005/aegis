"""Tests for PlatformRepository, LocalObjectStorage, API key lifecycle, and outbox retries."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import pytest
from contracts import (
    EvidenceRecord,
    EvidenceSourceType,
    FinancialEventType,
    compute_payload_hash,
)
from database import (
    LedgerRepository,
    LocalObjectStorage,
    PlatformRepository,
    create_db_engine,
    create_session_factory,
    init_db,
)
from security import Role, TenantIsolationError, hash_password


def _make_session(tmp_path: Path):
    engine = create_db_engine(f"sqlite:///{tmp_path / 'platform.db'}")
    init_db(engine)
    factory = create_session_factory(engine)
    return factory()


def test_org_membership_service_account_and_api_key_rotation(tmp_path: Path) -> None:
    session = _make_session(tmp_path)
    repo = PlatformRepository(session)
    org1 = repo.create_organization(name="Acme AI", slug="acme-ai")
    org2 = repo.create_organization(name="Other Org", slug="other-org")

    user = repo.create_user(
        email="founder@acme.ai",
        full_name="Founder",
        password_hash=hash_password("StrongPass!2026", iterations=10_000),
    )
    repo.add_membership(tenant_id=org1.id, user_id=user.id, role=Role.OWNER)
    memberships = repo.list_user_memberships(user.id)
    assert len(memberships) == 1
    assert memberships[0][0].role == "OWNER"

    sa = repo.create_service_account(tenant_id=org1.id, name="purchasing-bot", role=Role.AGENT_SERVICE)
    pepper = "test-pepper-secret"
    key_row, raw_key = repo.create_api_key(
        tenant_id=org1.id,
        name="bot-primary",
        pepper=pepper,
        service_account_id=sa.id,
        role=Role.AGENT_SERVICE,
    )
    authed = repo.authenticate_api_key(raw_key, pepper=pepper)
    assert authed is not None
    assert authed.id == key_row.id

    with pytest.raises(TenantIsolationError):
        repo.revoke_api_key(org2.id, key_row.id)

    new_row, new_raw = repo.rotate_api_key(tenant_id=org1.id, api_key_id=key_row.id, pepper=pepper)
    assert new_row.id != key_row.id
    assert repo.authenticate_api_key(raw_key, pepper=pepper) is None
    assert repo.authenticate_api_key(new_raw, pepper=pepper) is not None


def test_local_object_storage_and_integrity_checks(tmp_path: Path) -> None:
    session = _make_session(tmp_path)
    ledger = LedgerRepository(session)
    platform = PlatformRepository(session)
    org = platform.create_organization(name="Evidence Org", slug="ev-org")
    tenant_b = uuid4()

    ev = ledger.save_evidence(
        EvidenceRecord(
            tenant_id=org.id,
            correlation_id=uuid4(),
            source_type=EvidenceSourceType.CARRIER_TRACKING,
            source_ref="pod-123.pdf",
            title="Delivery proof",
            content={"tracking": "1Z999"},
            content_hash=compute_payload_hash({"tracking": "1Z999"}),
        )
    )
    storage = LocalObjectStorage(tmp_path / "obj")
    art_id = uuid4()
    meta = storage.put_bytes(
        tenant_id=org.id,
        artifact_id=art_id,
        filename="../../pod-123.pdf",
        data=b"%PDF-1.4 signed proof",
        content_type="application/pdf",
    )
    assert ".." not in meta.object_key
    row = platform.save_evidence_artifact(
        artifact_id=art_id,
        tenant_id=org.id,
        evidence_record_id=ev.id,
        storage_backend=meta.storage_backend,
        object_key=meta.object_key,
        filename=meta.filename,
        content_type=meta.content_type,
        byte_size=meta.byte_size,
        sha256=meta.sha256,
    )
    loaded = storage.get_bytes(tenant_id=org.id, object_key=row.object_key, expected_sha256=row.sha256)
    assert loaded == b"%PDF-1.4 signed proof"

    with pytest.raises(PermissionError):
        storage.get_bytes(tenant_id=tenant_b, object_key=row.object_key)


def test_outbox_backoff_and_dead_letter_requeue(tmp_path: Path) -> None:
    session = _make_session(tmp_path)
    ledger = LedgerRepository(session)
    platform = PlatformRepository(session)
    org = platform.create_organization(name="Worker Org", slug="worker-org")

    ledger.append_financial_event(
        tenant_id=org.id,
        correlation_id=uuid4(),
        payment_intent_id=None,
        event_type=FinancialEventType.DISPUTE_OPENED,
        actor_type="SYSTEM",
        actor_id="test",
        payload={"case": "c1"},
        also_enqueue_outbox=True,
    )
    session.commit()

    t0 = datetime(2026, 11, 12, 12, 0, tzinfo=UTC)
    claimed = platform.claim_due_outbox_events(limit=10, now=t0)
    assert len(claimed) == 1
    outbox_id = claimed[0].id

    row = platform.mark_outbox_failed(outbox_id, error_message="timeout", max_attempts=2, base_delay_seconds=10, now=t0)
    assert row.status == "RETRY"
    assert platform.claim_due_outbox_events(limit=10, now=t0 + timedelta(seconds=5)) == []

    reclaimed = platform.claim_due_outbox_events(limit=10, now=t0 + timedelta(seconds=15))
    assert len(reclaimed) == 1

    dead = platform.mark_outbox_failed(outbox_id, error_message="still down", max_attempts=2, base_delay_seconds=10, now=t0 + timedelta(seconds=15))
    assert dead.status == "DEAD_LETTER"
    assert dead.dead_lettered_at is not None

    requeued = platform.requeue_dead_letter_outbox(org.id, outbox_id)
    assert requeued.status == "PENDING"
    published = platform.mark_outbox_published(outbox_id, now=t0 + timedelta(seconds=20))
    assert published.status == "PUBLISHED"
