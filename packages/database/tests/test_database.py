"""Tests for nexus-database atomic budget reservation, tenant isolation, and hash-chained events."""

from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from pathlib import Path
from uuid import uuid4

import pytest

from contracts import FinancialEventType, PaymentIntent, PaymentState
from contracts.fixtures import (
    TENANT_ALPHA_ID,
    TENANT_BETA_ID,
    build_authorized_39_purchase_fixture,
)
from database import (
    InsufficientBudgetError,
    LedgerRepository,
    create_db_engine,
    create_session_factory,
    init_db,
)
from security import TenantIsolationError, verify_financial_event_chain


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

