"""Concurrency and multi-worker contention test harness.

Verifies:
1. Budget reservation race condition prevention (atomic balance check):
   Zero double-spending under concurrent contention; total held cannot exceed total budget.
2. Outbox lease claim & reap concurrency (SKIP LOCKED / lease claim semantics):
   Disjoint worker partition claims; no event claimed by more than one worker.
3. Parallel payment proposal idempotency test:
   Multiple simultaneous threads with the same idempotency key return identical intent IDs
   and create exactly one intent in the database.
"""

from __future__ import annotations

import concurrent.futures
import sqlite3
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from contracts import (
    PassportStatus,
    PaymentIntent,
    PaymentState,
    PurchaseProposal,
    QuoteSnapshot,
    compute_quote_hash,
)
from database import (
    LedgerRepository,
    OutboxEventRow,
    PlatformRepository,
    SpendingPassportRow,
    create_db_engine,
    create_session_factory,
    init_db,
)
from database.repository import InsufficientBudgetError
from fastapi.testclient import TestClient
from security import NexusSettings, Role
from sqlalchemy import select
from aegis_api.app import create_app


def _init_sqlite_wal(db_path: Path) -> None:
    conn = sqlite3.connect(str(db_path))
    conn.execute("PRAGMA journal_mode = WAL;")
    conn.execute("PRAGMA busy_timeout = 30000;")
    conn.close()


@pytest.fixture()
def concurrency_env(tmp_path: Path):
    db_path = tmp_path / "concurrency.db"
    _init_sqlite_wal(db_path)

    settings = NexusSettings(
        database_url=f"sqlite:///{db_path}?timeout=30",
        jwt_secret="concurrency-jwt-secret-key-32b-min",
        signing_secret="concurrency-signing-secret",
        evidence_storage_dir=str(tmp_path / "evidence"),
        rate_limit_rpm=20000,
    )
    engine = create_db_engine(f"sqlite:///{db_path}?timeout=30")
    init_db(engine)
    session_factory = create_session_factory(engine)
    app = create_app(settings=settings, engine=engine)

    with TestClient(app) as client:
        # Register owner and organization
        reg = client.post(
            "/v1/auth/register",
            json={
                "email": "concurrency-admin@aegis-conc.test",
                "password": "StrongPassword!123",
                "full_name": "Concurrency Admin",
                "organization_name": "Concurrency Lab",
                "organization_slug": "concurrency-lab",
            },
        )
        assert reg.status_code == 201
        token = reg.json()["access_token"]
        org_id = UUID(reg.json()["active_tenant_id"])

        yield {
            "client": client,
            "token": token,
            "org_id": org_id,
            "session_factory": session_factory,
            "db_path": db_path,
        }


# ==============================================================================
# 1. Budget Reservation Race Condition Prevention (Atomic Balance Check)
# ==============================================================================
def test_budget_reservation_race_condition_prevention(concurrency_env):
    """Verify concurrent budget reservations atomically prevent double-spend."""
    client: TestClient = concurrency_env["client"]
    token = concurrency_env["token"]
    session_factory = concurrency_env["session_factory"]
    org_id = concurrency_env["org_id"]
    headers = {"Authorization": f"Bearer {token}"}

    # Setup agent and merchant via API
    agent_resp = client.post(
        "/v1/guardian/agents",
        headers=headers,
        json={"name": "Contention Agent", "public_fingerprint": f"fp-{uuid4().hex[:8]}"},
    )
    assert agent_resp.status_code == 201
    agent_id = agent_resp.json()["id"]

    merchant_resp = client.post(
        "/v1/guardian/merchants",
        headers=headers,
        json={"name": "Contention Merchant", "domain": "contention.example", "category": "SOFTWARE", "is_allowlisted": True},
    )
    assert merchant_resp.status_code == 201
    merchant_id = merchant_resp.json()["id"]

    # Total budget = $100.00 (10,000 minor). Each worker tries to reserve $20.00 (2,000 minor).
    # Human approval threshold = $10.00 (1,000 minor), so proposals enter AWAITING_APPROVAL without holding budget.
    total_budget_minor = 10000
    tx_amount_minor = 2000
    num_workers = 10  # 10 workers * $20.00 = $200.00 requested. Exactly 5 must succeed!

    passport_resp = client.post(
        "/v1/guardian/passports",
        headers=headers,
        json={
            "agent_id": agent_id,
            "total_budget_minor": total_budget_minor,
            "per_tx_limit_minor": tx_amount_minor,
            "daily_limit_minor": total_budget_minor,
            "human_approval_threshold_minor": 1000,
            "allowed_categories": ["SOFTWARE"],
            "allowed_merchant_ids": [merchant_id],
        },
    )
    assert passport_resp.status_code == 201
    passport_id = UUID(passport_resp.json()["id"])
    now = datetime.now(UTC)

    # Create 10 proposals -> all enter AWAITING_APPROVAL with zero reserved budget initially
    payment_intent_ids: list[UUID] = []
    for i in range(num_workers):
        prop_resp = client.post(
            "/v1/guardian/proposals",
            headers=headers,
            json={
                "agent_id": agent_id,
                "passport_id": str(passport_id),
                "merchant_id": merchant_id,
                "merchant_name": "Contention Merchant",
                "merchant_category": "SOFTWARE",
                "amount_minor": tx_amount_minor,
                "currency": "USD",
                "item_summary": f"Contention Item {i}",
                "rationale": "Testing concurrent budget reservation",
                "idempotency_key": f"contention-prop-{i}-{uuid4()}",
            },
        )
        assert prop_resp.status_code == 201
        payment_intent_ids.append(UUID(prop_resp.json()["payment_intent"]["id"]))

    def attempt_reservation(worker_idx: int) -> bool:
        target_intent_id = payment_intent_ids[worker_idx]
        for attempt in range(8):
            with session_factory() as thread_session:
                thread_repo = LedgerRepository(thread_session)
                try:
                    thread_repo.reserve_budget_atomic(
                        tenant_id=org_id,
                        correlation_id=uuid4(),
                        passport_id=passport_id,
                        payment_intent_id=target_intent_id,
                        amount_minor=tx_amount_minor,
                        currency="USD",
                        expires_at=now + timedelta(hours=1),
                    )
                    thread_session.commit()
                    return True
                except InsufficientBudgetError:
                    thread_session.rollback()
                    return False
                except Exception as exc:
                    thread_session.rollback()
                    if "database is locked" in str(exc) or "locked" in str(exc):
                        time.sleep(0.05 * (attempt + 1))
                        continue
                    raise
        return False

    with concurrent.futures.ThreadPoolExecutor(max_workers=num_workers) as executor:
        futures = [executor.submit(attempt_reservation, i) for i in range(num_workers)]
        results = [f.result() for f in concurrent.futures.as_completed(futures)]

    success_count = sum(1 for r in results if r is True)
    failure_count = sum(1 for r in results if r is False)

    # Exactly 5 reservations must succeed ($20 * 5 = $100 budget exhausted)
    assert success_count == 5, f"Expected exactly 5 successful reservations, got {success_count}"
    assert failure_count == 5, f"Expected exactly 5 failed reservations, got {failure_count}"

    # Verify database state: total reserved must equal exactly 10,000 minor units
    with session_factory() as session:
        passport_row = session.scalar(
            select(SpendingPassportRow).where(SpendingPassportRow.id == passport_id)
        )
        assert passport_row is not None
        assert passport_row.reserved_minor == total_budget_minor
        assert passport_row.spent_minor == 0
        available = passport_row.total_budget_minor - passport_row.spent_minor - passport_row.reserved_minor
        assert available == 0, f"Available budget must be 0, got {available}"


# ==============================================================================
# 2. Outbox Lease Claim & Reap Concurrency (SKIP LOCKED / Lease Claim)
# ==============================================================================
def test_outbox_lease_claim_concurrency(concurrency_env):
    """Verify multiple concurrent workers claiming outbox events receive mutually disjoint batches."""
    session_factory = concurrency_env["session_factory"]
    org_id = concurrency_env["org_id"]
    now = datetime.now(UTC)

    total_events = 30
    with session_factory() as session:
        for i in range(total_events):
            event = OutboxEventRow(
                id=uuid4(),
                tenant_id=org_id,
                aggregate_type="payment_intent",
                aggregate_id=uuid4(),
                event_type="payment.proposed",
                payload={"index": i, "data": f"payload-{i}"},
                status="PENDING",
                attempts=0,
                created_at=now,
            )
            session.add(event)
        session.commit()

    num_workers = 6
    claimed_by_worker: list[list[UUID]] = []

    def claim_batch(worker_idx: int) -> list[UUID]:
        for attempt in range(8):
            try:
                with session_factory() as thread_session:
                    platform = PlatformRepository(thread_session)
                    claimed = platform.claim_due_outbox_events(limit=10, now=now)
                    ids = [row.id for row in claimed]
                    thread_session.commit()
                    return ids
            except Exception as exc:
                if "database is locked" in str(exc) or "locked" in str(exc):
                    time.sleep(0.05 * (attempt + 1))
                    continue
                raise
        return []

    with concurrent.futures.ThreadPoolExecutor(max_workers=num_workers) as executor:
        futures = [executor.submit(claim_batch, i) for i in range(num_workers)]
        claimed_by_worker = [f.result() for f in concurrent.futures.as_completed(futures)]

    # Flatten all claimed IDs
    all_claimed_ids = [eid for sublist in claimed_by_worker for eid in sublist]
    unique_claimed_ids = set(all_claimed_ids)

    # Crucial concurrency invariant: No event is claimed more than once across workers
    assert len(all_claimed_ids) == len(unique_claimed_ids), (
        f"Duplicate outbox claims detected! Total claimed: {len(all_claimed_ids)}, unique: {len(unique_claimed_ids)}"
    )

    # Verify all claimed events transitioned to PROCESSING status in the database
    with session_factory() as session:
        for eid in unique_claimed_ids:
            row = session.get(OutboxEventRow, eid)
            assert row is not None
            assert row.status == "PROCESSING"


# ==============================================================================
# 3. Parallel Payment Proposal Idempotency Test
# ==============================================================================
def test_parallel_payment_proposal_idempotency(concurrency_env):
    """Verify concurrent proposal submissions with identical idempotency key yield identical intent."""
    client: TestClient = concurrency_env["client"]
    token = concurrency_env["token"]
    headers = {"Authorization": f"Bearer {token}"}

    # Setup agent, merchant, and passport
    agent_resp = client.post(
        "/v1/guardian/agents",
        headers=headers,
        json={"name": "Idempotent Agent", "public_fingerprint": f"fp-{uuid4().hex[:8]}"},
    )
    assert agent_resp.status_code == 201
    agent_id = agent_resp.json()["id"]

    merchant_resp = client.post(
        "/v1/guardian/merchants",
        headers=headers,
        json={"name": "Cloud Vendor", "domain": "cloud.example", "category": "SOFTWARE", "is_allowlisted": True},
    )
    assert merchant_resp.status_code == 201
    merchant_id = merchant_resp.json()["id"]

    passport_resp = client.post(
        "/v1/guardian/passports",
        headers=headers,
        json={
            "agent_id": agent_id,
            "total_budget_minor": 100000,
            "per_tx_limit_minor": 50000,
            "daily_limit_minor": 100000,
            "human_approval_threshold_minor": 20000,
            "allowed_categories": ["SOFTWARE"],
            "allowed_merchant_ids": [merchant_id],
        },
    )
    assert passport_resp.status_code == 201
    passport_id = passport_resp.json()["id"]

    shared_idempotency_key = f"concurrent-idempotent-key-{uuid4().hex[:12]}"
    proposal_body = {
        "agent_id": agent_id,
        "passport_id": passport_id,
        "merchant_id": merchant_id,
        "merchant_name": "Cloud Vendor",
        "merchant_category": "SOFTWARE",
        "amount_minor": 3500,
        "currency": "USD",
        "item_summary": "Compute instance reservation",
        "rationale": "High-concurrency batch execution",
        "idempotency_key": shared_idempotency_key,
    }

    num_concurrent_requests = 8

    def send_proposal(worker_idx: int) -> dict:
        for attempt in range(12):
            try:
                resp = client.post(
                    "/v1/guardian/proposals",
                    headers=headers,
                    json=proposal_body,
                )
                if resp.status_code in (200, 201):
                    return resp.json()
                if resp.status_code >= 500:
                    time.sleep(0.08 * (attempt + 1))
                    continue
                assert resp.status_code in (200, 201), f"Worker {worker_idx} got unexpected status {resp.status_code}: {resp.text}"
            except Exception as exc:
                # If Starlette TestClient re-raises the unhandled 500 / IntegrityError from in-process ASGI app
                if "IntegrityError" in str(type(exc)) or "UNIQUE constraint" in str(exc) or "database is locked" in str(exc):
                    time.sleep(0.08 * (attempt + 1))
                    continue
                raise
        # Final retry attempt to fetch the result once committed
        final_resp = client.post(
            "/v1/guardian/proposals",
            headers=headers,
            json=proposal_body,
        )
        assert final_resp.status_code in (200, 201), f"Worker {worker_idx} failed after retries: {final_resp.status_code} {final_resp.text}"
        return final_resp.json()

    with concurrent.futures.ThreadPoolExecutor(max_workers=num_concurrent_requests) as executor:
        futures = [executor.submit(send_proposal, i) for i in range(num_concurrent_requests)]
        results = [f.result() for f in concurrent.futures.as_completed(futures)]

    assert len(results) == num_concurrent_requests

    # All returned payment intents must have the EXACT SAME ID
    intent_ids = {r["payment_intent"]["id"] for r in results}
    assert len(intent_ids) == 1, f"Idempotency violation! Multiple intent IDs returned: {intent_ids}"

    chosen_intent_id = list(intent_ids)[0]

    # Verify exactly one intent exists in the DB for this idempotency key
    payments_resp = client.get("/v1/guardian/payments", headers=headers)
    matching_intents = [
        p for p in payments_resp.json()
        if p["idempotency_key"] == shared_idempotency_key
    ]
    assert len(matching_intents) == 1
    assert matching_intents[0]["id"] == chosen_intent_id
