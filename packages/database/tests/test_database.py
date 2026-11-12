"""Tests for nexus-database atomic budget reservation, tenant isolation, and hash-chained events."""

import os
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import pytest
from contracts import (
    AuthorizationDecision,
    DecisionOutcome,
    DecisionReasonCode,
    DisputeCase,
    DisputeSourceType,
    DisputeStatus,
    EvidenceRecord,
    EvidenceSourceType,
    FinancialEventType,
    PassportStatus,
    PaymentIntent,
    PaymentState,
    compute_payload_hash,
)
from contracts.fixtures import (
    TENANT_ALPHA_ID,
    TENANT_BETA_ID,
    build_authorized_39_purchase_fixture,
)
from database import (
    AuthorizationDecisionRow,
    DisputeCaseRow,
    InsufficientBudgetError,
    LedgerRepository,
    create_db_engine,
    create_session_factory,
    ensure_pg_audit_triggers,
    init_db,
)
from security import TenantIsolationError, verify_financial_event_chain
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError


def _seed_base(session_factory):
    fx = build_authorized_39_purchase_fixture()
    with session_factory() as session:
        repo = LedgerRepository(session)
        repo.upsert_tenant(fx["tenant"])
        repo.create_agent(fx["agent"])
        repo.create_merchant(fx["approved_merchant"])
        repo.create_passport(fx["passport"])
        session.commit()
    return fx


def test_concurrent_70_dollar_reservations_against_100_dollar_budget(tmp_path: Path) -> None:
    db_file = tmp_path / "concurrent.db"
    engine = create_db_engine(f"sqlite:///{db_file}")
    init_db(engine)
    session_factory = create_session_factory(engine)
    fx = _seed_base(session_factory)

    # Pre-create two separate intents so FK constraints are satisfied
    intent_ids = []
    with session_factory() as session:
        repo = LedgerRepository(session)
        for idx in range(2):
            p = fx["proposal"].model_copy(update={"id": uuid4(), "correlation_id": uuid4(), "idempotency_key": f"idem-conc-{idx}"})
            repo.save_proposal(p)
            q = fx["quote_snapshot"].model_copy(update={"id": uuid4(), "proposal_id": p.id, "correlation_id": p.correlation_id})
            repo.save_quote(q)
            intent = PaymentIntent(
                id=uuid4(),
                tenant_id=TENANT_ALPHA_ID,
                correlation_id=p.correlation_id,
                proposal_id=p.id,
                agent_id=p.agent_id,
                passport_id=p.passport_id,
                merchant_id=p.merchant_id,
                quote_snapshot_id=q.id,
                quote_hash=q.quote_hash,
                amount_minor=7000,
                currency="USD",
                state=PaymentState.POLICY_CHECK,
                idempotency_key=p.idempotency_key,
            )
            repo.save_intent(intent)
            intent_ids.append((intent.id, intent.correlation_id))
        session.commit()

    def attempt_reserve(pair):
        i_id, c_id = pair
        with session_factory() as session:
            repo = LedgerRepository(session)
            try:
                repo.reserve_budget_atomic(
                    tenant_id=TENANT_ALPHA_ID,
                    correlation_id=c_id,
                    passport_id=fx["passport"].id,
                    payment_intent_id=i_id,
                    amount_minor=7000,
                    currency="USD",
                    expires_at=fx["passport"].expires_at,
                )
                session.commit()
                return "RESERVED"
            except InsufficientBudgetError:
                session.rollback()
                return "REJECTED"

    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(attempt_reserve, intent_ids))

    assert sorted(outcomes) == ["REJECTED", "RESERVED"]

    with session_factory() as session:
        repo = LedgerRepository(session)
        passport = repo.get_passport(TENANT_ALPHA_ID, fx["passport"].id)
        assert passport is not None
        assert passport.reserved_minor == 7000
        assert passport.available_budget_minor == 3000


def test_cross_tenant_access_denied_and_event_chain_persisted(tmp_path: Path) -> None:
    db_file = tmp_path / "tenant.db"
    engine = create_db_engine(f"sqlite:///{db_file}")
    init_db(engine)
    session_factory = create_session_factory(engine)
    fx = _seed_base(session_factory)

    with session_factory() as session:
        repo = LedgerRepository(session)
        with pytest.raises(TenantIsolationError):
            repo.get_passport(TENANT_BETA_ID, fx["passport"].id)

        corr = uuid4()
        repo.append_financial_event(
            tenant_id=TENANT_ALPHA_ID,
            correlation_id=corr,
            payment_intent_id=None,
            event_type=FinancialEventType.PROPOSAL_CREATED,
            actor_type="AGENT",
            actor_id=str(fx["agent"].id),
            payload={"amount_minor": 3900},
        )
        repo.append_financial_event(
            tenant_id=TENANT_ALPHA_ID,
            correlation_id=corr,
            payment_intent_id=None,
            event_type=FinancialEventType.POLICY_EVALUATED,
            actor_type="POLICY_ENGINE",
            actor_id="policy-v1",
            payload={"outcome": "ALLOW"},
        )
        session.commit()

        events = repo.list_events(TENANT_ALPHA_ID, correlation_id=corr)
        ok, errs = verify_financial_event_chain(events)
        assert ok and errs == []
        assert len(repo.list_pending_outbox()) == 2


def test_save_dispute_case_and_save_evidence_update_all_fields(tmp_path: Path) -> None:
    db_file = tmp_path / "dispute_updates.db"
    engine = create_db_engine(f"sqlite:///{db_file}")
    init_db(engine)
    session_factory = create_session_factory(engine)
    fx = _seed_base(session_factory)

    with session_factory() as session:
        repo = LedgerRepository(session)
        p = fx["proposal"]
        repo.save_proposal(p)
        q = fx["quote_snapshot"]
        repo.save_quote(q)
        intent = PaymentIntent(
            id=uuid4(),
            tenant_id=TENANT_ALPHA_ID,
            correlation_id=p.correlation_id,
            proposal_id=p.id,
            agent_id=p.agent_id,
            passport_id=p.passport_id,
            merchant_id=p.merchant_id,
            quote_snapshot_id=q.id,
            quote_hash=q.quote_hash,
            amount_minor=p.amount_minor,
            currency="USD",
            state=PaymentState.SUCCEEDED,
            idempotency_key="idem-disp-1",
        )
        repo.save_intent(intent)

        ev = EvidenceRecord(
            tenant_id=TENANT_ALPHA_ID,
            correlation_id=p.correlation_id,
            payment_intent_id=intent.id,
            source_type=EvidenceSourceType.CARRIER_TRACKING,
            source_ref="track-1",
            title="Initial tracking",
            content={"carrier": "UPS", "status": "IN_TRANSIT"},
            content_hash=compute_payload_hash({"carrier": "UPS", "status": "IN_TRANSIT"}),
            is_synthetic=True,
        )
        repo.save_evidence(ev)
        updated_ev = ev.model_copy(
            update={
                "source_ref": "track-2",
                "title": "Delivered tracking",
                "content": {"carrier": "UPS", "status": "DELIVERED"},
                "content_hash": compute_payload_hash({"carrier": "UPS", "status": "DELIVERED"}),
                "is_synthetic": False,
            }
        )
        persisted_ev = repo.save_evidence(updated_ev)
        assert persisted_ev.source_ref == "track-2"
        assert persisted_ev.title == "Delivered tracking"
        assert persisted_ev.content == {"carrier": "UPS", "status": "DELIVERED"}
        assert persisted_ev.content_hash == updated_ev.content_hash
        assert persisted_ev.is_synthetic is False

        case = DisputeCase(
            tenant_id=TENANT_ALPHA_ID,
            correlation_id=p.correlation_id,
            payment_intent_id=intent.id,
            paypal_dispute_id=None,
            source_type=DisputeSourceType.SYNTHETIC_DEMO,
            is_synthetic=True,
            reason="MERCHANDISE_OR_SERVICE_NOT_RECEIVED",
            buyer_claim="Initial claim",
            amount_minor=3900,
            currency="USD",
            status=DisputeStatus.OPEN,
        )
        repo.save_dispute_case(case)

        updated_case = case.model_copy(
            update={
                "paypal_dispute_id": "PP-DISP-999",
                "source_type": DisputeSourceType.PAYPAL_SANDBOX,
                "is_synthetic": False,
                "reason": "UNAUTHORIZED",
                "buyer_claim": "Updated buyer claim from PayPal sync",
                "amount_minor": 4200,
                "currency": "EUR",
                "status": DisputeStatus.RESOLVED,
                "evidence_ids": [ev.id],
            }
        )
        saved = repo.save_dispute_case(updated_case)
        assert saved.paypal_dispute_id == "PP-DISP-999"
        assert saved.source_type == DisputeSourceType.PAYPAL_SANDBOX
        assert saved.is_synthetic is False
        assert saved.reason == "UNAUTHORIZED"
        assert saved.buyer_claim == "Updated buyer claim from PayPal sync"
        assert saved.amount_minor == 4200
        assert saved.currency == "EUR"
        assert saved.status == DisputeStatus.RESOLVED

        # Verify extended DB columns also persist via save_dispute_case when present on row
        row = session.get(DisputeCaseRow, case.id)
        assert row is not None
        due = datetime(2026, 11, 20, 12, 0, tzinfo=UTC)
        resolved = datetime(2026, 11, 15, 12, 0, tzinfo=UTC)
        row.response_due_by = due
        row.resolved_at = resolved
        row.resolution_outcome = "RESOLVED_BUYER_FAVOUR"
        row.external_status = "WAITING_FOR_BUYER_RESPONSE"
        session.commit()


def test_passport_snapshots_auto_recorded_and_linked_to_decision(tmp_path: Path) -> None:
    db_file = tmp_path / "snapshots.db"
    engine = create_db_engine(f"sqlite:///{db_file}")
    init_db(engine)
    session_factory = create_session_factory(engine)
    fx = _seed_base(session_factory)

    with session_factory() as session:
        repo = LedgerRepository(session)
        passport = fx["passport"]

        snap1 = repo.get_latest_passport_snapshot(TENANT_ALPHA_ID, passport.id)
        assert snap1 is not None
        assert snap1["version"] == 1
        assert snap1["snapshot_json"]["per_tx_limit_minor"] == passport.per_tx_limit_minor

        # Update policy -> auto-records version 2
        repo.update_passport_policy(
            TENANT_ALPHA_ID,
            passport.id,
            per_tx_limit_minor=8000,
            created_by="admin@acme.ai",
        )
        snap2 = repo.get_latest_passport_snapshot(TENANT_ALPHA_ID, passport.id)
        assert snap2 is not None
        assert snap2["version"] == 2
        assert snap2["snapshot_json"]["per_tx_limit_minor"] == 8000
        assert snap2["created_by"] == "admin@acme.ai"

        # Revoke passport -> auto-records version 3
        repo.update_passport_policy(
            TENANT_ALPHA_ID,
            passport.id,
            status=PassportStatus.REVOKED,
            created_by="secops@acme.ai",
        )
        snap3 = repo.get_latest_passport_snapshot(TENANT_ALPHA_ID, passport.id)
        assert snap3 is not None
        assert snap3["version"] == 3
        assert snap3["snapshot_json"]["status"] == "REVOKED"

        # Link an explicit snapshot to an authorization decision
        p = fx["proposal"]
        repo.save_proposal(p)
        q = fx["quote_snapshot"]
        repo.save_quote(q)
        intent = PaymentIntent(
            id=uuid4(),
            tenant_id=TENANT_ALPHA_ID,
            correlation_id=p.correlation_id,
            proposal_id=p.id,
            agent_id=p.agent_id,
            passport_id=p.passport_id,
            merchant_id=p.merchant_id,
            quote_snapshot_id=q.id,
            quote_hash=q.quote_hash,
            amount_minor=p.amount_minor,
            currency="USD",
            state=PaymentState.CHECKOUT_READY,
            idempotency_key="idem-snap-1",
        )
        repo.save_intent(intent)
        dec = AuthorizationDecision(
            tenant_id=TENANT_ALPHA_ID,
            correlation_id=p.correlation_id,
            payment_intent_id=intent.id,
            proposal_id=p.id,
            passport_id=passport.id,
            quote_snapshot_id=q.id,
            quote_hash=q.quote_hash,
            policy_version=passport.policy_version,
            outcome=DecisionOutcome.ALLOW,
            reason_codes=[DecisionReasonCode.OK_WITHIN_POLICY],
            explanation="Allowed under v2 snapshot",
        )
        repo.save_decision(dec)
        dec_row = session.get(AuthorizationDecisionRow, dec.id)
        assert dec_row is not None
        dec_row.passport_snapshot_id = snap2["id"]
        session.commit()

        bound = repo.get_passport_snapshot_for_decision(TENANT_ALPHA_ID, dec.id)
        assert bound is not None
        assert bound["id"] == snap2["id"]
        assert bound["version"] == 2
        assert bound["snapshot_json"]["per_tx_limit_minor"] == 8000


def test_alembic_migrations_upgrade_and_downgrade_sqlite(tmp_path: Path) -> None:
    from alembic import command
    from alembic.config import Config

    db_file = tmp_path / "alembic_test.db"
    alembic_cfg = Config(str(Path(__file__).resolve().parents[1] / "alembic.ini"))
    alembic_cfg.set_main_option(
        "script_location", str(Path(__file__).resolve().parents[1] / "alembic")
    )
    alembic_cfg.set_main_option("sqlalchemy.url", f"sqlite:///{db_file}")

    command.upgrade(alembic_cfg, "head")
    command.downgrade(alembic_cfg, "0002_aegis_platform_extensions")
    command.upgrade(alembic_cfg, "head")


def test_postgres_financial_event_immutability_trigger_and_concurrent_seq() -> None:
    pg_url = os.getenv("AEGIS_TEST_POSTGRES_URL")
    if not pg_url:
        pytest.skip("AEGIS_TEST_POSTGRES_URL not set; skipping PostgreSQL 16 trigger test")

    engine = create_db_engine(pg_url)
    init_db(engine)
    ensure_pg_audit_triggers(engine)
    session_factory = create_session_factory(engine)
    fx = _seed_base(session_factory)

    corr = uuid4()
    with session_factory() as session:
        repo = LedgerRepository(session)
        ev = repo.append_financial_event(
            tenant_id=TENANT_ALPHA_ID,
            correlation_id=corr,
            payment_intent_id=None,
            event_type=FinancialEventType.PROPOSAL_CREATED,
            actor_type="AGENT",
            actor_id=str(fx["agent"].id),
            payload={"amount_minor": 3900},
        )
        session.commit()
        ev_id = ev.id

    with session_factory() as session:
        with pytest.raises(DBAPIError, match="append-only"):
            session.execute(
                text("UPDATE financial_events SET actor_id = 'tampered' WHERE id = :id"),
                {"id": ev_id},
            )
            session.commit()
        session.rollback()

    with session_factory() as session:
        with pytest.raises(DBAPIError, match="append-only"):
            session.execute(
                text("DELETE FROM financial_events WHERE id = :id"),
                {"id": ev_id},
            )
            session.commit()
        session.rollback()

    def _append_concurrent(idx: int) -> int:
        with session_factory() as session:
            repo = LedgerRepository(session)
            ev_c = repo.append_financial_event(
                tenant_id=TENANT_ALPHA_ID,
                correlation_id=corr,
                payment_intent_id=None,
                event_type=FinancialEventType.POLICY_EVALUATED,
                actor_type="SYSTEM",
                actor_id=f"worker-{idx}",
                payload={"idx": idx},
            )
            session.commit()
            return ev_c.sequence_number

    with ThreadPoolExecutor(max_workers=4) as pool:
        seqs = list(pool.map(_append_concurrent, range(4)))

    assert sorted(seqs) == [2, 3, 4, 5]
    with session_factory() as session:
        repo = LedgerRepository(session)
        ok, errs = verify_financial_event_chain(repo.list_events(TENANT_ALPHA_ID, correlation_id=corr))
        assert ok and errs == []


