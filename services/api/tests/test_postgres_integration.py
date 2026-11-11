"""Live PostgreSQL 16 integration tests (migrations, row-lock concurrency, API + worker durability).

Run only when ``AEGIS_TEST_POSTGRES_URL`` is configured (e.g. against disposable Docker PostgreSQL).
"""

from __future__ import annotations

import os
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import pytest
from aegis_api.app import create_app
from alembic import command
from alembic.config import Config
from contracts import (
    AgentIdentity,
    Merchant,
    PassportStatus,
    SpendingPassport,
)
from database import (
    LedgerRepository,
    PlatformRepository,
    create_db_engine,
    create_session_factory,
)
from fastapi.testclient import TestClient
from guardian.budgets.coordinator import BudgetCoordinator
from guardian.domain.exceptions import GuardianError
from security import NexusSettings
from sqlalchemy import inspect
from sqlalchemy.exc import SQLAlchemyError

PG_URL = os.getenv("AEGIS_TEST_POSTGRES_URL", "").strip()
REPO_ROOT = Path(__file__).resolve().parents[3]


@pytest.mark.skipif(not PG_URL, reason="AEGIS_TEST_POSTGRES_URL not set; skipping live PostgreSQL suite")
def test_postgres_migrations_concurrency_and_restart_persistence(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("DATABASE_URL", PG_URL)
    alembic_cfg = Config(str(REPO_ROOT / "packages/database/alembic.ini"))
    alembic_cfg.set_main_option("script_location", str(REPO_ROOT / "packages/database/alembic"))
    alembic_cfg.set_main_option("sqlalchemy.url", PG_URL)

    # 1. Clean downgrade -> upgrade -> repeatable upgrade verification
    command.downgrade(alembic_cfg, "base")
    command.upgrade(alembic_cfg, "head")
    command.upgrade(alembic_cfg, "head")

    engine = create_db_engine(PG_URL)
    try:
        tables = set(inspect(engine).get_table_names())
        assert {
            "tenants",
            "users",
            "organization_memberships",
            "service_accounts",
            "api_keys",
            "admin_audit_logs",
            "spending_passports",
            "payment_intents",
            "budget_reservations",
            "replay_investigations",
            "dispute_cases",
            "dispute_case_metadata",
            "evidence_artifacts",
            "webhook_endpoints",
            "webhook_deliveries",
            "outbox_events",
        }.issubset(tables)

        # 2. Real PostgreSQL SELECT FOR UPDATE concurrency check ($70 x2 against $100 budget)
        session_factory = create_session_factory(engine)
        with session_factory() as setup_session:
            platform = PlatformRepository(setup_session)
            ledger = LedgerRepository(setup_session)
            org = platform.create_organization(name="PG Concurrency", slug=f"pg-conc-{uuid4().hex[:6]}")
            agent = ledger.create_agent(
                AgentIdentity(
                    tenant_id=org.id,
                    name="Conc-Agent",
                    purpose="concurrency test",
                    framework="custom",
                    public_fingerprint=f"fp-{uuid4().hex[:8]}",
                )
            )
            merchant = ledger.create_merchant(
                Merchant(
                    tenant_id=org.id,
                    name="Conc Merchant",
                    domain="conc.example.com",
                    category="SOFTWARE",
                    is_allowlisted=True,
                )
            )
            passport = ledger.create_passport(
                SpendingPassport(
                    tenant_id=org.id,
                    agent_id=agent.id,
                    policy_version="policy-v1",
                    currency="USD",
                    total_budget_minor=10000,
                    per_tx_limit_minor=10000,
                    daily_limit_minor=10000,
                    human_approval_threshold_minor=10000,
                    allowed_merchant_ids=[merchant.id],
                    allowed_categories=["SOFTWARE"],
                    status=PassportStatus.ACTIVE,
                    expires_at=datetime.now(UTC) + timedelta(days=30),
                )
            )
            intent_ids = []
            for idx in range(2):
                from guardian.api.models import SubmitProposalRequest

                prop, quote = SubmitProposalRequest(
                    tenant_id=org.id,
                    agent_id=agent.id,
                    passport_id=passport.id,
                    merchant_id=merchant.id,
                    merchant_name="Conc Merchant",
                    merchant_category="SOFTWARE",
                    amount_minor=7000,
                    currency="USD",
                    item_summary=f"Concurrent item {idx}",
                    line_items=[{"description": "Item", "quantity": 1, "unit_price_minor": 7000}],
                    rationale="concurrent budget race test",
                    idempotency_key=f"pg-conc-{uuid4().hex[:8]}",
                ).to_proposal_and_quote()
                ledger.save_proposal(prop)
                ledger.save_quote(quote)
                from contracts import PaymentIntent, PaymentState

                pi = ledger.save_intent(
                    PaymentIntent(
                        tenant_id=org.id,
                        correlation_id=prop.correlation_id,
                        proposal_id=prop.id,
                        agent_id=agent.id,
                        passport_id=passport.id,
                        merchant_id=merchant.id,
                        quote_snapshot_id=quote.id,
                        quote_hash=quote.quote_hash,
                        amount_minor=7000,
                        currency="USD",
                        state=PaymentState.POLICY_CHECK,
                        idempotency_key=prop.idempotency_key,
                    )
                )
                intent_ids.append((pi.id, pi.correlation_id))
            setup_session.commit()
            tenant_id = org.id
            passport_id = passport.id

        def try_reserve(target: tuple) -> str:
            pi_id, corr_id = target
            with session_factory() as worker_session:
                worker_ledger = LedgerRepository(worker_session)
                coord = BudgetCoordinator(worker_ledger)
                try:
                    coord.reserve(
                        tenant_id=tenant_id,
                        correlation_id=corr_id,
                        passport_id=passport_id,
                        payment_intent_id=pi_id,
                        amount_minor=7000,
                        currency="USD",
                        expires_at=datetime.now(UTC) + timedelta(minutes=15),
                    )
                    worker_session.commit()
                    return "RESERVED"
                except (GuardianError, SQLAlchemyError, ValueError) as exc:
                    worker_session.rollback()
                    return f"REJECTED:{type(exc).__name__}"

        with ThreadPoolExecutor(max_workers=2) as pool:
            outcomes = list(pool.map(try_reserve, intent_ids))

        assert sorted(outcomes)[1] == "RESERVED"
        assert outcomes.count("RESERVED") == 1
        assert sum(1 for o in outcomes if o.startswith("REJECTED:")) == 1
    finally:
        engine.dispose()

    # 3. Unified FastAPI full persistence + server restart recovery against PostgreSQL
    settings = NexusSettings(
        database_url=PG_URL,
        jwt_secret="pg-integration-test-jwt-secret-32-bytes",
        evidence_storage_dir=str(tmp_path / "pg_evidence"),
        rate_limit_rpm=5000,
    )
    app1 = create_app(settings=settings, create_tables=False)
    with TestClient(app1) as c1:
        reg = c1.post(
            "/v1/auth/register",
            json={
                "email": f"pg-ops-{uuid4().hex[:6]}@example.com",
                "password": "PgPassword!123",
                "full_name": "PG Operator",
                "organization_name": "PG Org",
                "organization_slug": f"pg-org-{uuid4().hex[:6]}",
            },
        )
        assert reg.status_code == 201
        headers = {"Authorization": f"Bearer {reg.json()['access_token']}"}
        agent = c1.post(
            "/v1/guardian/agents",
            headers=headers,
            json={"name": "PG-Agent", "public_fingerprint": f"fp-{uuid4().hex[:8]}"},
        ).json()
        merchant = c1.post(
            "/v1/guardian/merchants",
            headers=headers,
            json={"name": "PG Vendor", "domain": "pg.example.com", "category": "SOFTWARE", "is_allowlisted": True},
        ).json()
        passport = c1.post(
            "/v1/guardian/passports",
            headers=headers,
            json={
                "agent_id": agent["id"],
                "total_budget_minor": 10000,
                "per_tx_limit_minor": 5000,
                "daily_limit_minor": 10000,
                "human_approval_threshold_minor": 4000,
                "allowed_merchant_ids": [merchant["id"]],
                "allowed_categories": ["SOFTWARE"],
            },
        ).json()
        prop = c1.post(
            "/v1/guardian/proposals",
            headers=headers,
            json={
                "agent_id": agent["id"],
                "passport_id": passport["id"],
                "merchant_id": merchant["id"],
                "merchant_name": "PG Vendor",
                "merchant_category": "SOFTWARE",
                "amount_minor": 2500,
                "currency": "USD",
                "item_summary": "PG Persistence License",
                "rationale": "live pg test",
                "idempotency_key": f"pg-idem-{uuid4().hex[:8]}",
            },
        ).json()
        intent_id = prop["payment_intent"]["id"]
        replay = c1.post(f"/v1/ghostpay/replay/by-payment/{intent_id}", headers=headers, json={})
        assert replay.status_code == 200
        assert replay.json()["integrity_valid"] is True

    app2 = create_app(settings=settings, create_tables=False)
    with TestClient(app2) as c2:
        detail = c2.get(f"/v1/guardian/payments/{intent_id}/detail", headers=headers)
        assert detail.status_code == 200
        invs = c2.get("/v1/ghostpay/investigations", headers=headers).json()
        assert invs["total"] >= 1
