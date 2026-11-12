"""RC1 Financial Invariants & Concurrency Verification Suite.

Verifies the five core RC1 financial safety invariants against PostgreSQL 16
(or SQLite fallback when ``DATABASE_URL`` is unset):
1. Parallel budget reservations under race + idempotent reservation retry.
2. Single-use ApprovalRecord consumption (replay rejection).
3. Quote hash mismatch, scope mismatch, and expiry rejection.
4. FinancialEvent hash-chain monotonicity under concurrent appends + tamper detection.
5. Transactional outbox atomicity (commit persists both; rollback persists neither).
"""

from __future__ import annotations

import concurrent.futures
import os
import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from contracts import (
    AgentIdentity,
    ApprovalStatus,
    AuthorizationDecision,
    DecisionOutcome,
    FinancialEventType,
    Merchant,
    PassportStatus,
    PaymentIntent,
    PaymentState,
    PurchaseProposal,
    QuoteSnapshot,
    SpendingPassport,
    compute_quote_hash,
)
from database import (
    FinancialEventRow,
    LedgerRepository,
    OutboxEventRow,
    PlatformRepository,
    SpendingPassportRow,
    create_db_engine,
    create_session_factory,
    init_db,
)
from database.repository import InsufficientBudgetError
from guardian.approvals.service import ApprovalService
from guardian.domain.exceptions import (
    ApprovalExpiredError,
    ApprovalMismatchError,
    InvalidStateTransitionError,
)
from security import verify_financial_event_chain
from sqlalchemy import select


@pytest.fixture()
def pg_or_sqlite_session_factory(tmp_path: Path):
    """Provide a SQLAlchemy session factory backed by DATABASE_URL (PG16) or SQLite."""
    env_url = os.getenv("DATABASE_URL", "").strip()
    if env_url.startswith("postgresql"):
        db_url = env_url
    else:
        db_path = tmp_path / "rc1_invariants.db"
        conn = sqlite3.connect(str(db_path))
        conn.execute("PRAGMA journal_mode = WAL;")
        conn.execute("PRAGMA busy_timeout = 30000;")
        conn.close()
        db_url = f"sqlite:///{db_path}?timeout=30"

    engine = create_db_engine(db_url)
    init_db(engine)
    session_factory = create_session_factory(engine)
    try:
        yield session_factory
    finally:
        engine.dispose()


def _seed_tenant_actor_graph(session_factory, *, total_budget_minor: int = 10000):
    """Create an isolated tenant, agent, merchant, and active spending passport."""
    with session_factory() as session:
        platform = PlatformRepository(session)
        ledger = LedgerRepository(session)
        org = platform.create_organization(
            name=f"RC1 Invariant Org {uuid4().hex[:6]}",
            slug=f"rc1-inv-{uuid4().hex[:8]}",
        )
        agent = ledger.create_agent(
            AgentIdentity(
                tenant_id=org.id,
                name="RC1 Verifier Agent",
                purpose="RC1 financial invariant verification",
                framework="custom",
                public_fingerprint=f"fp-{uuid4().hex[:10]}",
            )
        )
        merchant = ledger.create_merchant(
            Merchant(
                tenant_id=org.id,
                name="RC1 Verified Merchant",
                domain="rc1-merchant.example",
                category="SOFTWARE",
                is_allowlisted=True,
            )
        )
        passport = ledger.create_passport(
            SpendingPassport(
                tenant_id=org.id,
                agent_id=agent.id,
                total_budget_minor=total_budget_minor,
                per_tx_limit_minor=total_budget_minor,
                daily_limit_minor=total_budget_minor,
                human_approval_threshold_minor=1000,
                allowed_categories=["SOFTWARE"],
                allowed_merchant_ids=[merchant.id],
                status=PassportStatus.ACTIVE,
                expires_at=datetime.now(UTC) + timedelta(days=30),
            )
        )
        session.commit()
        return org.id, agent.id, merchant.id, passport.id


def _create_intent_with_quote(
    session,
    *,
    tenant_id: UUID,
    agent_id: UUID,
    passport_id: UUID,
    merchant_id: UUID,
    amount_minor: int,
    currency: str = "USD",
    quote_expires_at: datetime | None = None,
) -> tuple[QuoteSnapshot, PaymentIntent, AuthorizationDecision]:
    """Persist a QuoteSnapshot, PaymentIntent, and AuthorizationDecision."""
    ledger = LedgerRepository(session)
    now = datetime.now(UTC)
    corr_id = uuid4()
    idem_key = f"rc1-idem-{uuid4().hex}"
    line_items = [{"sku": "rc1-compute", "qty": 1, "unit_price_minor": amount_minor}]
    proposal = PurchaseProposal(
        tenant_id=tenant_id,
        correlation_id=corr_id,
        agent_id=agent_id,
        passport_id=passport_id,
        merchant_id=merchant_id,
        merchant_name="RC1 Verified Merchant",
        merchant_category="SOFTWARE",
        amount_minor=amount_minor,
        currency=currency,
        item_summary="RC1 invariant test item",
        line_items=line_items,
        rationale="RC1 invariant verification",
        idempotency_key=idem_key,
    )
    ledger.save_proposal(proposal)
    proposal_id = proposal.id
    q_hash = compute_quote_hash(
        merchant_id=merchant_id,
        amount_minor=amount_minor,
        currency=currency,
        line_items=line_items,
    )
    quote = QuoteSnapshot(
        tenant_id=tenant_id,
        correlation_id=corr_id,
        proposal_id=proposal_id,
        merchant_id=merchant_id,
        amount_minor=amount_minor,
        currency=currency,
        line_items=line_items,
        quote_hash=q_hash,
        expires_at=quote_expires_at or (now + timedelta(hours=1)),
    )
    ledger.save_quote(quote)

    intent = PaymentIntent(
        tenant_id=tenant_id,
        correlation_id=corr_id,
        proposal_id=proposal_id,
        agent_id=agent_id,
        passport_id=passport_id,
        merchant_id=merchant_id,
        quote_snapshot_id=quote.id,
        quote_hash=q_hash,
        amount_minor=amount_minor,
        currency=currency,
        state=PaymentState.AWAITING_APPROVAL,
        idempotency_key=f"rc1-idem-{uuid4().hex}",
    )
    ledger.save_intent(intent)

    decision = AuthorizationDecision(
        tenant_id=tenant_id,
        correlation_id=corr_id,
        proposal_id=proposal_id,
        payment_intent_id=intent.id,
        passport_id=passport_id,
        quote_snapshot_id=quote.id,
        outcome=DecisionOutcome.ESCALATE,
        reason_codes=["ESCALATED_REQUIRES_HUMAN_APPROVAL"],
        explanation="Requires human approval for RC1 verification",
        quote_hash=q_hash,
    )
    ledger.save_decision(decision)
    return quote, intent, decision


# ==============================================================================
# 1. Parallel Budget Reservations Under Race + Idempotent Retry
# ==============================================================================
def test_parallel_budget_reservations_under_race(pg_or_sqlite_session_factory):
    """Verify atomic SQL reservation prevents double-spend under parallel contention."""
    tenant_id, agent_id, merchant_id, passport_id = _seed_tenant_actor_graph(
        pg_or_sqlite_session_factory,
        total_budget_minor=10000,
    )
    tx_amount_minor = 2500  # 10 workers x $25 = $250 requested against $100 -> 4 must win
    num_workers = 10
    now = datetime.now(UTC)

    intent_ids: list[UUID] = []
    with pg_or_sqlite_session_factory() as session:
        for _ in range(num_workers):
            _, intent, _ = _create_intent_with_quote(
                session,
                tenant_id=tenant_id,
                agent_id=agent_id,
                passport_id=passport_id,
                merchant_id=merchant_id,
                amount_minor=tx_amount_minor,
            )
            intent_ids.append(intent.id)
        session.commit()

    def reserve_worker(idx: int) -> tuple[UUID, UUID] | None:
        with pg_or_sqlite_session_factory() as thread_session:
            repo = LedgerRepository(thread_session)
            try:
                res = repo.reserve_budget_atomic(
                    tenant_id=tenant_id,
                    correlation_id=uuid4(),
                    passport_id=passport_id,
                    payment_intent_id=intent_ids[idx],
                    amount_minor=tx_amount_minor,
                    currency="USD",
                    expires_at=now + timedelta(hours=1),
                )
                thread_session.commit()
                return intent_ids[idx], res.id
            except InsufficientBudgetError:
                thread_session.rollback()
                return None

    with concurrent.futures.ThreadPoolExecutor(max_workers=num_workers) as pool:
        futures = [pool.submit(reserve_worker, i) for i in range(num_workers)]
        results = [f.result() for f in concurrent.futures.as_completed(futures)]

    winners = [r for r in results if r is not None]
    assert len(winners) == 4, f"Expected exactly 4 winners, got {len(winners)}"

    # Idempotent retry for a winning intent must return the same reservation without double-reserving
    winning_intent_id, winning_res_id = winners[0]
    with pg_or_sqlite_session_factory() as session:
        repo = LedgerRepository(session)
        retry_res = repo.reserve_budget_atomic(
            tenant_id=tenant_id,
            correlation_id=uuid4(),
            passport_id=passport_id,
            payment_intent_id=winning_intent_id,
            amount_minor=tx_amount_minor,
            currency="USD",
            expires_at=now + timedelta(hours=1),
        )
        session.commit()
        assert retry_res.id == winning_res_id

        passport_row = session.get(SpendingPassportRow, passport_id)
        assert passport_row is not None
        assert passport_row.reserved_minor == 10000
        assert passport_row.spent_minor == 0


# ==============================================================================
# 2. Single-Use ApprovalRecord Consumption
# ==============================================================================
def test_single_use_approval_record_consumption(pg_or_sqlite_session_factory):
    """Verify an ApprovalRecord can be consumed exactly once and replay is rejected."""
    tenant_id, agent_id, merchant_id, passport_id = _seed_tenant_actor_graph(
        pg_or_sqlite_session_factory
    )

    with pg_or_sqlite_session_factory() as session:
        quote, intent, decision = _create_intent_with_quote(
            session,
            tenant_id=tenant_id,
            agent_id=agent_id,
            passport_id=passport_id,
            merchant_id=merchant_id,
            amount_minor=3500,
        )
        ledger = LedgerRepository(session)
        approval_svc = ApprovalService(ledger)
        approval = approval_svc.create_approval_request(
            tenant_id=tenant_id,
            correlation_id=intent.correlation_id,
            payment_intent_id=intent.id,
            decision_id=decision.id,
            approver_id="cfo@rc1.example",
            bound_merchant_id=merchant_id,
            bound_amount_minor=3500,
            bound_currency="USD",
            bound_quote_hash=quote.quote_hash,
            auto_approve=True,
        )
        session.commit()
        approval_id = approval.id

    # First consumption succeeds
    with pg_or_sqlite_session_factory() as session:
        ledger = LedgerRepository(session)
        approval_svc = ApprovalService(ledger)
        consumed = approval_svc.consume_approval(
            tenant_id=tenant_id,
            approval_id=approval_id,
            current_merchant_id=merchant_id,
            current_amount_minor=3500,
            current_currency="USD",
            current_quote_hash=quote.quote_hash,
            payment_intent_id=intent.id,
        )
        session.commit()
        assert consumed.status == ApprovalStatus.CONSUMED
        assert consumed.consumed_at is not None

    # Second consumption (replay) must be rejected
    with pg_or_sqlite_session_factory() as session:
        ledger = LedgerRepository(session)
        approval_svc = ApprovalService(ledger)
        with pytest.raises(InvalidStateTransitionError, match="already been consumed"):
            approval_svc.consume_approval(
                tenant_id=tenant_id,
                approval_id=approval_id,
                current_merchant_id=merchant_id,
                current_amount_minor=3500,
                current_currency="USD",
                current_quote_hash=quote.quote_hash,
                payment_intent_id=intent.id,
            )


# ==============================================================================
# 3. Quote Hash Mismatch & Expiry Rejection
# ==============================================================================
def test_quote_hash_mismatch_and_expiry_rejection(pg_or_sqlite_session_factory):
    """Verify tampered quote hashes, scope mismatches, and expired quotes/approvals are rejected."""
    tenant_id, agent_id, merchant_id, passport_id = _seed_tenant_actor_graph(
        pg_or_sqlite_session_factory
    )
    now = datetime.now(UTC)

    with pg_or_sqlite_session_factory() as session:
        quote, intent, decision = _create_intent_with_quote(
            session,
            tenant_id=tenant_id,
            agent_id=agent_id,
            passport_id=passport_id,
            merchant_id=merchant_id,
            amount_minor=4000,
        )
        ledger = LedgerRepository(session)
        approval_svc = ApprovalService(ledger)
        approval = approval_svc.create_approval_request(
            tenant_id=tenant_id,
            correlation_id=intent.correlation_id,
            payment_intent_id=intent.id,
            decision_id=decision.id,
            approver_id="cfo@rc1.example",
            bound_merchant_id=merchant_id,
            bound_amount_minor=4000,
            bound_currency="USD",
            bound_quote_hash=quote.quote_hash,
            expires_at=now + timedelta(minutes=30),
            auto_approve=True,
        )
        session.commit()
        approval_id = approval.id

    with pg_or_sqlite_session_factory() as session:
        ledger = LedgerRepository(session)
        approval_svc = ApprovalService(ledger)

        # (a) Quote hash mismatch
        with pytest.raises(ApprovalMismatchError, match="Quote hash mismatch"):
            approval_svc.consume_approval(
                tenant_id=tenant_id,
                approval_id=approval_id,
                current_merchant_id=merchant_id,
                current_amount_minor=4000,
                current_currency="USD",
                current_quote_hash="tampered-quote-hash-0000",
                payment_intent_id=intent.id,
            )

        # (b) Amount mismatch
        with pytest.raises(ApprovalMismatchError, match="Amount mismatch"):
            approval_svc.consume_approval(
                tenant_id=tenant_id,
                approval_id=approval_id,
                current_merchant_id=merchant_id,
                current_amount_minor=9999,
                current_currency="USD",
                current_quote_hash=quote.quote_hash,
                payment_intent_id=intent.id,
            )

        # (c) Expired quote rejection
        expired_quote = quote.model_copy(update={"expires_at": now - timedelta(seconds=5)})
        with pytest.raises(ApprovalExpiredError, match="expired"):
            approval_svc.consume_approval(
                tenant_id=tenant_id,
                approval_id=approval_id,
                current_merchant_id=merchant_id,
                current_amount_minor=4000,
                current_currency="USD",
                current_quote_hash=quote.quote_hash,
                payment_intent_id=intent.id,
                quote=expired_quote,
                now=now,
            )

        # (d) Expired approval rejection (advancing clock past approval.expires_at)
        with pytest.raises(ApprovalExpiredError, match="expired"):
            approval_svc.consume_approval(
                tenant_id=tenant_id,
                approval_id=approval_id,
                current_merchant_id=merchant_id,
                current_amount_minor=4000,
                current_currency="USD",
                current_quote_hash=quote.quote_hash,
                payment_intent_id=intent.id,
                now=now + timedelta(hours=2),
            )
        session.commit()

        refreshed = ledger.get_approval(tenant_id, approval_id)
        assert refreshed is not None
        assert refreshed.status == ApprovalStatus.EXPIRED


# ==============================================================================
# 4. Hash-Chain Monotonicity Under Concurrent Appends
# ==============================================================================
def test_hash_chain_monotonicity_under_concurrent_appends(pg_or_sqlite_session_factory):
    """Verify concurrent FinancialEvent appends maintain strict sequence_number & hash-chain integrity."""
    tenant_id, _, _, _ = _seed_tenant_actor_graph(pg_or_sqlite_session_factory)
    correlation_id = uuid4()
    num_events = 12

    def append_worker(idx: int) -> int:
        with pg_or_sqlite_session_factory() as thread_session:
            repo = LedgerRepository(thread_session)
            ev = repo.append_financial_event(
                tenant_id=tenant_id,
                correlation_id=correlation_id,
                payment_intent_id=None,
                event_type=FinancialEventType.POLICY_EVALUATED,
                actor_type="SYSTEM",
                actor_id=f"worker-{idx}",
                payload={"worker_idx": idx},
                also_enqueue_outbox=False,
            )
            thread_session.commit()
            return ev.sequence_number

    with concurrent.futures.ThreadPoolExecutor(max_workers=6) as pool:
        futures = [pool.submit(append_worker, i) for i in range(num_events)]
        seqs = [f.result() for f in concurrent.futures.as_completed(futures)]

    assert sorted(seqs) == list(range(1, num_events + 1))

    with pg_or_sqlite_session_factory() as session:
        repo = LedgerRepository(session)
        events = repo.list_events(tenant_id, correlation_id=correlation_id)
        assert len(events) == num_events
        assert [e.sequence_number for e in events] == list(range(1, num_events + 1))

        ok, errors = verify_financial_event_chain(events)
        assert ok is True, f"Hash-chain verification failed: {errors}"
        assert errors == []

        # Tampering with any event payload must break verification
        tampered = list(events)
        tampered[4] = tampered[4].model_copy(update={"payload": {"worker_idx": 99999}})
        tampered_ok, tampered_errors = verify_financial_event_chain(tampered)
        assert tampered_ok is False
        assert len(tampered_errors) >= 1


# ==============================================================================
# 5. Transactional Outbox Atomicity (Commit & Rollback)
# ==============================================================================
def test_outbox_atomicity_commit_and_rollback(pg_or_sqlite_session_factory):
    """Verify FinancialEvent and OutboxEventRow are committed or rolled back atomically."""
    tenant_id, _, _, _ = _seed_tenant_actor_graph(pg_or_sqlite_session_factory)
    commit_corr = uuid4()
    rollback_corr = uuid4()

    # Commit path: both rows must exist
    with pg_or_sqlite_session_factory() as session:
        repo = LedgerRepository(session)
        ev = repo.append_financial_event(
            tenant_id=tenant_id,
            correlation_id=commit_corr,
            payment_intent_id=None,
            event_type=FinancialEventType.POLICY_EVALUATED,
            actor_type="AGENT",
            actor_id="agent-commit",
            payload={"step": "committed"},
            also_enqueue_outbox=True,
        )
        session.commit()
        committed_event_id = str(ev.id)

    # Rollback path: neither row may exist
    with pg_or_sqlite_session_factory() as session:
        repo = LedgerRepository(session)
        repo.append_financial_event(
            tenant_id=tenant_id,
            correlation_id=rollback_corr,
            payment_intent_id=None,
            event_type=FinancialEventType.POLICY_EVALUATED,
            actor_type="AGENT",
            actor_id="agent-rollback",
            payload={"step": "rolled_back"},
            also_enqueue_outbox=True,
        )
        session.rollback()

    with pg_or_sqlite_session_factory() as session:
        committed_events = session.scalars(
            select(FinancialEventRow).where(FinancialEventRow.correlation_id == commit_corr)
        ).all()
        committed_outbox = session.scalars(
            select(OutboxEventRow).where(
                OutboxEventRow.tenant_id == tenant_id,
                OutboxEventRow.aggregate_id == commit_corr,
            )
        ).all()
        assert len(committed_events) == 1
        assert len(committed_outbox) == 1
        assert committed_outbox[0].payload["event_id"] == committed_event_id
        assert committed_outbox[0].status == "PENDING"

        rolled_back_events = session.scalars(
            select(FinancialEventRow).where(FinancialEventRow.correlation_id == rollback_corr)
        ).all()
        rolled_back_outbox = session.scalars(
            select(OutboxEventRow).where(
                OutboxEventRow.tenant_id == tenant_id,
                OutboxEventRow.aggregate_id == rollback_corr,
            )
        ).all()
        assert len(rolled_back_events) == 0
        assert len(rolled_back_outbox) == 0
