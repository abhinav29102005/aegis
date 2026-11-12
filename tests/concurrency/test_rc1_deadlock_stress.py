"""RC1 P0 Deadlock Elimination & Expanded Concurrency Stress Suite.

Validates concurrent Guardian proposal submissions across:
- 2, 10, 50, and 100 concurrent identical requests (idempotency convergence)
- Multiple distinct idempotency keys for the same tenant (zero deadlocks)
- Concurrent multi-tenant proposal submissions (strict tenant isolation)
- Conflicting payloads sharing an idempotency key (IdempotencyConflictError)
- Concurrent budget exhaustion (exact authorized ceiling never exceeded)
- Forced transaction rollback & PostgreSQL statement_timeout (zero partial state)
- Concurrent OutboxWorker processing during proposal submissions
"""

from __future__ import annotations

import asyncio
import concurrent.futures
import os
import threading
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID, uuid4

import httpx
import pytest
from aegis_worker.processor import OutboxWorker
from contracts import (
    AgentIdentity,
    Merchant,
    PassportStatus,
    PurchaseProposal,
    QuoteSnapshot,
    SpendingPassport,
    compute_quote_hash,
)
from database import (
    BudgetReservationRow,
    FinancialEventRow,
    LedgerRepository,
    OutboxEventRow,
    PaymentIntentRow,
    PlatformRepository,
    PurchaseProposalRow,
    QuoteSnapshotRow,
    SpendingPassportRow,
    create_db_engine,
    create_session_factory,
    init_db,
)
from database.repository import InsufficientBudgetError
from guardian.domain.exceptions import DuplicateIntentError
from guardian.domain.service import GuardianService
from paypal import PayPalSandboxClient
from security import verify_financial_event_chain
from sqlalchemy import select, text
from sqlalchemy.exc import OperationalError


@pytest.fixture()
def stress_session_factory(tmp_path: Path):
    """Provide a high-pool PG16 session factory when DATABASE_URL is set, else SQLite."""
    db_url = os.getenv("DATABASE_URL", "").strip()
    if db_url.startswith("postgresql"):
        engine = create_db_engine(db_url)
    else:
        db_url = f"sqlite+pysqlite:///{tmp_path / 'stress.db'}"
        engine = create_db_engine(db_url)
    init_db(engine)
    factory = create_session_factory(engine)
    try:
        yield factory, db_url.startswith("postgresql")
    finally:
        engine.dispose()


def _seed_guardian_actor(
    factory,
    *,
    total_budget_minor: int = 1_000_000_00,
    per_tx_limit_minor: int = 500_000,
    human_threshold_minor: int = 200_000,
) -> dict[str, UUID]:
    now = datetime.now(UTC)

    with factory() as session:
        platform = PlatformRepository(session)
        repo = LedgerRepository(session)
        org = platform.create_organization(
            name=f"Stress Tenant {uuid4().hex[:8]}",
            slug=f"stress-{uuid4().hex[:12]}",
        )
        agent = repo.create_agent(
            AgentIdentity(
                tenant_id=org.id,
                name="Stress Buyer Agent",
                purpose="RC1 deadlock stress verification",
                framework="custom",
                public_fingerprint=f"fp-{uuid4().hex[:12]}",
            )
        )
        merchant = repo.create_merchant(
            Merchant(
                tenant_id=org.id,
                name="Stress Cloud Vendor",
                domain="stress-vendor.example",
                category="SAAS",
                is_allowlisted=True,
            )
        )
        passport = repo.create_passport(
            SpendingPassport(
                tenant_id=org.id,
                agent_id=agent.id,
                total_budget_minor=total_budget_minor,
                per_tx_limit_minor=per_tx_limit_minor,
                daily_limit_minor=total_budget_minor,
                monthly_limit_minor=total_budget_minor,
                human_approval_threshold_minor=human_threshold_minor,
                allowed_categories=["SAAS"],
                allowed_merchant_ids=[merchant.id],
                currency="USD",
                status=PassportStatus.ACTIVE,
                expires_at=now + timedelta(days=30),
            )
        )
        session.commit()

    return {
        "tenant_id": org.id,
        "agent_id": agent.id,
        "merchant_id": merchant.id,
        "passport_id": passport.id,
    }


def _make_proposal_and_quote(
    ids: dict[str, UUID],
    *,
    idempotency_key: str,
    amount_minor: int = 5_000,
    summary: str = "Cloud compute license",
) -> tuple[PurchaseProposal, QuoteSnapshot]:
    now = datetime.now(UTC)
    proposal_id = uuid4()
    quote_id = uuid4()
    corr_id = uuid4()
    expires_at = now + timedelta(minutes=15)
    line_items = [
        {
            "sku": "SAAS-01",
            "title": summary,
            "quantity": 1,
            "unit_price_minor": amount_minor,
        }
    ]
    quote_hash = compute_quote_hash(
        merchant_id=ids["merchant_id"],
        amount_minor=amount_minor,
        currency="USD",
        line_items=line_items,
    )
    proposal = PurchaseProposal(
        id=proposal_id,
        tenant_id=ids["tenant_id"],
        correlation_id=corr_id,
        agent_id=ids["agent_id"],
        passport_id=ids["passport_id"],
        merchant_id=ids["merchant_id"],
        merchant_name="CloudCompute",
        merchant_category="SAAS",
        amount_minor=amount_minor,
        currency="USD",
        item_summary=summary,
        line_items=line_items,
        rationale="RC1 deadlock stress verification",
        idempotency_key=idempotency_key,
        created_at=now,
    )
    quote = QuoteSnapshot(
        id=quote_id,
        tenant_id=ids["tenant_id"],
        correlation_id=corr_id,
        proposal_id=proposal_id,
        merchant_id=ids["merchant_id"],
        amount_minor=amount_minor,
        currency="USD",
        line_items=line_items,
        quote_hash=quote_hash,
        expires_at=expires_at,
        created_at=now,
    )
    return proposal, quote


def _submit_in_thread(factory, ids: dict[str, UUID], idemp_key: str, amount_minor: int = 5_000):
    proposal, quote = _make_proposal_and_quote(
        ids, idempotency_key=idemp_key, amount_minor=amount_minor
    )
    with factory() as session:
        repo = LedgerRepository(session)
        svc = GuardianService(
            repo=repo,
            paypal_client=PayPalSandboxClient(),
        )
        try:
            intent, decision = svc.submit_proposal(proposal=proposal, quote=quote)
            session.commit()
            return ("ok", intent.id, intent.correlation_id, decision.outcome.value)
        except Exception as exc:  # noqa: BLE001
            session.rollback()
            return ("err", type(exc).__name__, str(exc), None)


@pytest.mark.parametrize("concurrency", [2, 10, 50, 100])
def test_concurrent_identical_proposals_tiers(stress_session_factory, concurrency: int) -> None:
    """2, 10, 50, and 100 concurrent identical requests must converge on 1 intent with 0 deadlocks."""
    factory, _ = stress_session_factory
    ids = _seed_guardian_actor(factory)
    idemp_key = f"tier-{concurrency}-{uuid4().hex}"
    workers = min(concurrency, 25)

    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as pool:
        futures = [
            pool.submit(_submit_in_thread, factory, ids, idemp_key, 5_000)
            for _ in range(concurrency)
        ]
        results = [f.result() for f in futures]

    errors = [r for r in results if r[0] != "ok"]
    assert errors == [], f"Unexpected errors at concurrency={concurrency}: {errors[:5]}"

    intent_ids = {r[1] for r in results}
    assert len(intent_ids) == 1
    sole_intent_id = next(iter(intent_ids))

    with factory() as session:
        intents = session.scalars(
            select(PaymentIntentRow).where(PaymentIntentRow.tenant_id == ids["tenant_id"])
        ).all()
        reservations = session.scalars(
            select(BudgetReservationRow).where(BudgetReservationRow.tenant_id == ids["tenant_id"])
        ).all()
        passport = session.get(SpendingPassportRow, ids["passport_id"])
        events = session.scalars(
            select(FinancialEventRow)
            .where(FinancialEventRow.payment_intent_id == sole_intent_id)
            .order_by(FinancialEventRow.sequence_number.asc())
        ).all()
        outbox_rows = session.scalars(
            select(OutboxEventRow).where(OutboxEventRow.tenant_id == ids["tenant_id"])
        ).all()

    assert len(intents) == 1
    assert len(reservations) == 1
    assert passport is not None and passport.reserved_minor == 5_000
    assert [e.sequence_number for e in events] == list(range(1, len(events) + 1))
    assert len(outbox_rows) == len(events)
    with factory() as verify_session:
        repo_events = LedgerRepository(verify_session).list_events(
            ids["tenant_id"], correlation_id=intents[0].correlation_id
        )
    valid, chain_errors = verify_financial_event_chain(repo_events)
    assert valid is True and chain_errors == []


def test_concurrent_distinct_idempotency_keys_same_tenant(stress_session_factory) -> None:
    """25 concurrent distinct proposals for the same tenant must all succeed with 0 deadlocks."""
    factory, _ = stress_session_factory
    ids = _seed_guardian_actor(factory, total_budget_minor=5_000_000)
    keys = [f"distinct-{i}-{uuid4().hex[:8]}" for i in range(25)]

    with concurrent.futures.ThreadPoolExecutor(max_workers=20) as pool:
        results = list(
            pool.map(lambda k: _submit_in_thread(factory, ids, k, 5_000), keys)
        )

    errors = [r for r in results if r[0] != "ok"]
    assert errors == [], f"Errors on distinct same-tenant keys: {errors[:5]}"
    assert len({r[1] for r in results}) == 25

    with factory() as session:
        passport = session.get(SpendingPassportRow, ids["passport_id"])
        assert passport is not None
        assert passport.reserved_minor == 25 * 5_000


def test_concurrent_multi_tenant_isolation(stress_session_factory) -> None:
    """Two tenants submitting 15 proposals each concurrently maintain strict isolation."""
    factory, _ = stress_session_factory
    t1 = _seed_guardian_actor(factory)
    t2 = _seed_guardian_actor(factory)

    jobs: list[tuple[dict[str, UUID], str]] = []
    for i in range(15):
        jobs.append((t1, f"t1-{i}-{uuid4().hex[:6]}"))
        jobs.append((t2, f"t2-{i}-{uuid4().hex[:6]}"))

    with concurrent.futures.ThreadPoolExecutor(max_workers=20) as pool:
        results = list(pool.map(lambda j: _submit_in_thread(factory, j[0], j[1], 4_000), jobs))

    assert all(r[0] == "ok" for r in results), f"Multi-tenant errors: {results}"

    with factory() as session:
        t1_intents = session.scalars(
            select(PaymentIntentRow).where(PaymentIntentRow.tenant_id == t1["tenant_id"])
        ).all()
        t2_intents = session.scalars(
            select(PaymentIntentRow).where(PaymentIntentRow.tenant_id == t2["tenant_id"])
        ).all()
        assert len(t1_intents) == 15
        assert len(t2_intents) == 15
        assert {i.id for i in t1_intents}.isdisjoint({i.id for i in t2_intents})


def test_concurrent_conflicting_payload_same_idempotency_key(stress_session_factory) -> None:
    """Reusing an idempotency key with a conflicting amount must raise DuplicateIntentError."""
    factory, _ = stress_session_factory
    ids = _seed_guardian_actor(factory)
    idemp_key = f"conflict-{uuid4().hex}"

    # Seed first proposal deterministically
    first = _submit_in_thread(factory, ids, idemp_key, 5_000)
    assert first[0] == "ok"

    # Concurrent conflicting retries
    with concurrent.futures.ThreadPoolExecutor(max_workers=10) as pool:
        results = [
            f.result()
            for f in [
                pool.submit(_submit_in_thread, factory, ids, idemp_key, 9_999)
                for _ in range(10)
            ]
        ]

    assert all(r[0] == "err" and r[1] == DuplicateIntentError.__name__ for r in results)

    with factory() as session:
        intents = session.scalars(
            select(PaymentIntentRow).where(PaymentIntentRow.tenant_id == ids["tenant_id"])
        ).all()
        assert len(intents) == 1
        assert intents[0].amount_minor == 5_000


def test_concurrent_budget_exhaustion(stress_session_factory) -> None:
    """$300 budget with 15 concurrent $100 proposals must reserve exactly $300 and reject 12."""
    factory, _ = stress_session_factory
    ids = _seed_guardian_actor(
        factory,
        total_budget_minor=30_000,
        per_tx_limit_minor=30_000,
        human_threshold_minor=50_000,
    )
    keys = [f"exhaust-{i}-{uuid4().hex[:6]}" for i in range(15)]

    with concurrent.futures.ThreadPoolExecutor(max_workers=15) as pool:
        results = list(pool.map(lambda k: _submit_in_thread(factory, ids, k, 10_000), keys))

    ok = [r for r in results if r[0] == "ok"]
    insufficient = [r for r in results if r[0] == "err" and r[1] == InsufficientBudgetError.__name__]
    other = [r for r in results if r not in ok and r not in insufficient]

    assert other == [], f"Unexpected errors: {other}"
    assert len(ok) == 3
    assert len(insufficient) == 12

    with factory() as session:
        passport = session.get(SpendingPassportRow, ids["passport_id"])
        reservations = session.scalars(
            select(BudgetReservationRow).where(BudgetReservationRow.tenant_id == ids["tenant_id"])
        ).all()
        assert passport is not None and passport.reserved_minor == 30_000
        assert len(reservations) == 3


def test_forced_rollback_and_timeout_leave_no_partial_state(stress_session_factory) -> None:
    """Forced rollback and PG statement_timeout must leave zero partial financial state."""
    factory, is_pg = stress_session_factory
    ids = _seed_guardian_actor(factory)
    proposal, quote = _make_proposal_and_quote(ids, idempotency_key=f"rollback-{uuid4().hex}")

    # 1. Forced rollback after submit_proposal inside uncommitted transaction
    with factory() as session:
        repo = LedgerRepository(session)
        svc = GuardianService(
            repo=repo,
            paypal_client=PayPalSandboxClient(),
        )
        svc.submit_proposal(proposal=proposal, quote=quote)
        session.rollback()

    # 2. PostgreSQL statement_timeout mid-transaction
    if is_pg:
        p2, q2 = _make_proposal_and_quote(ids, idempotency_key=f"timeout-{uuid4().hex}")
        with factory() as session:
            session.execute(text("SET LOCAL statement_timeout = '1ms'"))
            repo = LedgerRepository(session)
            svc = GuardianService(
                repo=repo,
                paypal_client=PayPalSandboxClient(),
            )
            try:
                session.execute(text("SELECT pg_sleep(0.05)"))
                svc.submit_proposal(proposal=p2, quote=q2)
            except OperationalError:
                session.rollback()

    with factory() as session:
        assert session.scalars(
            select(PurchaseProposalRow).where(PurchaseProposalRow.tenant_id == ids["tenant_id"])
        ).all() == []
        assert session.scalars(
            select(QuoteSnapshotRow).where(QuoteSnapshotRow.tenant_id == ids["tenant_id"])
        ).all() == []
        assert session.scalars(
            select(PaymentIntentRow).where(PaymentIntentRow.tenant_id == ids["tenant_id"])
        ).all() == []
        assert session.scalars(
            select(FinancialEventRow).where(FinancialEventRow.tenant_id == ids["tenant_id"])
        ).all() == []
        assert session.scalars(
            select(OutboxEventRow).where(OutboxEventRow.tenant_id == ids["tenant_id"])
        ).all() == []


def test_worker_processing_during_concurrent_proposals(stress_session_factory) -> None:
    """OutboxWorker polling concurrently during proposal bursts must cause zero deadlocks."""
    factory, _ = stress_session_factory
    ids = _seed_guardian_actor(factory, total_budget_minor=2_000_000)
    stop_event = threading.Event()
    worker_errors: list[str] = []

    def _run_worker() -> None:
        async def _poll() -> None:
            transport = httpx.MockTransport(lambda req: httpx.Response(200, json={"ok": True}))
            async with httpx.AsyncClient(transport=transport) as client:
                worker = OutboxWorker(
                    session_factory=factory,
                    http_client=client,
                    worker_id="stress-worker",
                )
                while not stop_event.is_set():
                    try:
                        await worker.process_outbox_batch(limit=10)
                    except Exception as exc:  # noqa: BLE001
                        worker_errors.append(f"{type(exc).__name__}: {exc}")
                    await asyncio.sleep(0.01)

        asyncio.run(_poll())

    worker_thread = threading.Thread(target=_run_worker, daemon=True)
    worker_thread.start()
    try:
        keys = [f"worker-mix-{i}-{uuid4().hex[:6]}" for i in range(20)]
        with concurrent.futures.ThreadPoolExecutor(max_workers=10) as pool:
            results = list(pool.map(lambda k: _submit_in_thread(factory, ids, k, 2_500), keys))
    finally:
        stop_event.set()
        worker_thread.join(timeout=5)

    assert worker_errors == [], f"Worker errors: {worker_errors}"
    assert all(r[0] == "ok" for r in results), f"Proposal errors: {results}"
