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
from security import (
    Role,
    TenantIsolationError,
    hash_password,
    verify_financial_event_chain,
)


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

    requeued = platform.requeue_dead_letter_outbox(org.id, outbox_id, now=t0 + timedelta(seconds=16))
    assert requeued.status == "PENDING"
    assert requeued.attempts == 0
    assert requeued.locked_at is None
    assert requeued.lease_expires_at is None
    assert requeued.locked_by is None
    assert requeued.last_error is None

    published = platform.mark_outbox_delivered(outbox_id, now=t0 + timedelta(seconds=20))
    assert published.status == "PUBLISHED"
    assert published.locked_at is None
    assert published.lease_expires_at is None
    assert published.locked_by is None


def test_outbox_lease_reclamation_and_pending_capture_attempts(tmp_path: Path) -> None:
    session = _make_session(tmp_path)
    ledger = LedgerRepository(session)
    platform = PlatformRepository(session)
    org = platform.create_organization(name="Lease Org", slug="lease-org")

    ledger.append_financial_event(
        tenant_id=org.id,
        correlation_id=uuid4(),
        payment_intent_id=None,
        event_type=FinancialEventType.PROPOSAL_CREATED,
        actor_type="SYSTEM",
        actor_id="test",
        payload={"step": 1},
        also_enqueue_outbox=True,
    )
    session.commit()

    t0 = datetime(2026, 11, 12, 12, 0, tzinfo=UTC)
    claimed_a = platform.claim_due_outbox_events(limit=10, now=t0, worker_id="worker-a", lease_seconds=30)
    assert len(claimed_a) == 1
    assert claimed_a[0].status == "PROCESSING"
    assert claimed_a[0].locked_by == "worker-a"
    assert claimed_a[0].locked_at is not None
    assert claimed_a[0].lease_expires_at is not None

    # Active lease is NOT reclaimed before expiry
    assert (
        platform.claim_due_outbox_events(
            limit=10, now=t0 + timedelta(seconds=20), worker_id="worker-b", lease_seconds=30
        )
        == []
    )

    # Expired lease IS reclaimed by worker-b
    reclaimed_b = platform.claim_due_outbox_events(
        limit=10, now=t0 + timedelta(seconds=31), worker_id="worker-b", lease_seconds=45
    )
    assert len(reclaimed_b) == 1
    assert reclaimed_b[0].id == claimed_a[0].id
    assert reclaimed_b[0].locked_by == "worker-b"

    # list_pending_capture_attempts returns empty cleanly when none exist
    assert platform.list_pending_capture_attempts(limit=10, for_update_skip_locked=True) == []


def test_ghostpay_traces_agent_dna_llm_logs_and_paypal_webhook_dedup(tmp_path: Path) -> None:
    session = _make_session(tmp_path)
    platform = PlatformRepository(session)
    org = platform.create_organization(name="GhostPay Org", slug="ghostpay-org")

    t1 = platform.save_ghostpay_trace(
        tenant_id=org.id,
        trace_id="trace-1",
        agent_id="agent-alpha",
        payload_json={"amount_minor": 1500, "merchant": "aws"},
        recorded_decision_json={"outcome": "ALLOW"},
        correlation_id="corr-1",
    )
    platform.save_ghostpay_trace(
        tenant_id=org.id,
        trace_id="trace-2",
        agent_id="agent-beta",
        payload_json={"amount_minor": 9900, "merchant": "stripe"},
        recorded_decision_json=None,
        correlation_id="corr-2",
    )
    assert t1.trace_id == "trace-1"
    loaded = platform.get_ghostpay_trace(org.id, "trace-1")
    assert loaded is not None
    assert loaded.recorded_decision_json == {"outcome": "ALLOW"}
    assert len(platform.list_ghostpay_traces(org.id, agent_id="agent-alpha")) == 1
    assert len(platform.list_ghostpay_traces(org.id, limit=1, offset=1)) == 1

    dna = platform.save_agent_dna_profile(
        org.id, "agent-alpha", {"avg_amount_minor": 1500, "risk_score": 0.12}
    )
    assert dna.profile_json["risk_score"] == 0.12
    dna_updated = platform.save_agent_dna_profile(
        org.id, "agent-alpha", {"avg_amount_minor": 2000, "risk_score": 0.15}
    )
    assert dna_updated.id == dna.id
    got_dna = platform.get_agent_dna_profile(org.id, "agent-alpha")
    assert got_dna is not None and got_dna.profile_json["avg_amount_minor"] == 2000

    log = platform.log_llm_invocation(
        tenant_id=org.id,
        correlation_id="corr-1",
        module="disputeos",
        provider="openai",
        model="gpt-4o-mini",
        prompt_tokens=300,
        completion_tokens=120,
        estimated_cost_usd_micros=420,
    )
    assert log.estimated_cost_usd_micros == 420
    assert len(platform.list_llm_invocations(org.id, module="disputeos")) == 1

    assert platform.record_paypal_webhook_once("WH-EVT-1", "PAYMENT.CAPTURE.COMPLETED", "CAP-1", "h1") is True
    assert platform.record_paypal_webhook_once("WH-EVT-1", "PAYMENT.CAPTURE.COMPLETED", "CAP-1", "h1") is False


def test_invitations_verification_billing_metering_and_gdpr_erasure(tmp_path: Path) -> None:
    session = _make_session(tmp_path)
    ledger = LedgerRepository(session)
    platform = PlatformRepository(session)
    org = platform.create_organization(name="SaaS Org", slug="saas-org")

    owner = platform.create_user(
        email="owner@saas.ai",
        full_name="Owner User",
        password_hash=hash_password("Pass123!Strong", iterations=10_000),
    )
    platform.add_membership(tenant_id=org.id, user_id=owner.id, role=Role.OWNER)

    # Email verification + MFA
    t0 = datetime(2026, 11, 12, 12, 0, tzinfo=UTC)
    platform.create_email_verification(
        user_id=owner.id,
        email=owner.email,
        token_hash="verif-hash-1",
        expires_at=t0 + timedelta(hours=24),
    )
    platform.verify_email_token("verif-hash-1", now=t0 + timedelta(hours=1))
    assert platform.get_user(owner.id).email_verified is True  # type: ignore[union-attr]

    platform.set_user_mfa(owner.id, enabled=True, mfa_secret_encrypted="enc-totp-secret")
    assert platform.get_user(owner.id).mfa_enabled is True  # type: ignore[union-attr]

    # Org invitation + acceptance
    invitee = platform.create_user(
        email="alice@saas.ai",
        full_name="Alice Analyst",
        password_hash=hash_password("AlicePass!2026", iterations=10_000),
    )
    inv = platform.create_org_invitation(
        tenant_id=org.id,
        email="alice@saas.ai",
        role=Role.AUDITOR,
        token_hash="inv-hash-1",
        expires_at=t0 + timedelta(days=7),
        invited_by_user_id=owner.id,
    )
    assert inv.status == "PENDING"
    accepted = platform.accept_org_invitation("inv-hash-1", user_id=invitee.id, now=t0 + timedelta(hours=2))
    assert accepted.status == "ACCEPTED"
    assert platform.get_membership(org.id, invitee.id) is not None

    # Billing & usage metering
    sub = platform.upsert_billing_subscription(
        tenant_id=org.id,
        plan="PRO",
        status="ACTIVE",
        stripe_customer_id="cus_123",
        stripe_subscription_id="sub_123",
        monthly_tx_quota=5000,
    )
    assert sub.plan == "PRO"
    assert sub.monthly_tx_quota == 5000
    assert platform.get_billing_subscription(org.id) is not None

    platform.increment_usage_meter(tenant_id=org.id, period_ym="2026-11", metric="payments_authorized", amount=3)
    platform.increment_usage_meter(tenant_id=org.id, period_ym="2026-11", metric="payments_authorized", amount=2)
    assert platform.get_usage_meter(org.id, period_ym="2026-11", metric="payments_authorized") == 5
    assert len(platform.list_usage_meters(org.id, period_ym="2026-11")) == 1

    # Seed immutable financial event & API key for Alice, then execute GDPR erasure
    corr = uuid4()
    ledger.append_financial_event(
        tenant_id=org.id,
        correlation_id=corr,
        payment_intent_id=None,
        event_type=FinancialEventType.PROPOSAL_CREATED,
        actor_type="USER",
        actor_id=str(invitee.id),
        payload={"amount_minor": 1200},
    )
    key_row, _ = platform.create_api_key(
        tenant_id=org.id,
        name="alice-key",
        pepper="pepper-1",
        user_id=invitee.id,
        role=Role.AUDITOR,
    )
    platform.create_org_invitation(
        tenant_id=org.id,
        email="alice@saas.ai",
        role=Role.OPERATOR,
        token_hash="inv-hash-pending-alice",
        expires_at=t0 + timedelta(days=7),
        invited_by_user_id=owner.id,
    )

    erasure = platform.execute_user_erasure(
        tenant_id=org.id,
        user_id=invitee.id,
        requested_by=str(owner.id),
    )
    assert erasure.status == "COMPLETED"
    assert erasure.details_json["ledger_preserved"] is True

    erased_user = platform.get_user(invitee.id)
    assert erased_user is not None
    assert erased_user.erased_at is not None
    assert erased_user.full_name == "ERASED_USER"
    assert erased_user.email.startswith("erased-")
    assert erased_user.is_active is False

    # Financial ledger remains intact and hash-chain valid!
    events = ledger.list_events(org.id, correlation_id=corr)
    ok, errs = verify_financial_event_chain(events)
    assert ok and errs == []
    assert session.get(type(key_row), key_row.id).status == "REVOKED"  # type: ignore[union-attr]
