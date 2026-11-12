"""Tests for GhostPay router RBAC, DB persistence bridge, snapshot reconstruction, and pagination."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import timedelta
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

from aegis_api.adapters import SqlAlchemyGhostPayRepository
from contracts import (
    AuthorizationDecision,
    DecisionOutcome,
    DecisionReasonCode,
    PassportStatus,
    PaymentState,
    ReplayRequest,
    compute_payload_hash,
)
from contracts.fixtures import (
    AGENT_PROCUREMENT_ID,
    BASE_TIME,
    TENANT_ALPHA_ID,
    build_authorized_39_purchase_fixture,
)
from database import (
    AuthorizationDecisionRow,
    LedgerRepository,
    PlatformRepository,
    create_db_engine,
    create_session_factory,
    init_db,
)
from fastapi import FastAPI
from fastapi.testclient import TestClient
from security import (
    AuthContext,
    Role,
    create_access_token,
    get_settings,
    resolve_permissions,
)
from sqlalchemy.orm import Session

from ghostpay.api.router import create_ghostpay_router
from ghostpay.domain.service import GhostPayService
from ghostpay.replay.engine import ReplayEngine


def _make_auth_context(role: Role, *, tenant_id: UUID = TENANT_ALPHA_ID) -> AuthContext:
    return AuthContext(
        tenant_id=tenant_id,
        actor_type="USER",
        actor_id=f"user-{role.value.lower()}",
        user_id=uuid4(),
        email=f"{role.value.lower()}@example.com",
        role=role,
        permissions=resolve_permissions(role),
    )


def _make_db_session_factory(tmp_path: Path):
    db_path = tmp_path / "ghostpay_api_test.db"
    engine = create_db_engine(f"sqlite:///{db_path}")
    init_db(engine)
    return engine, create_session_factory(engine)


def _seed_two_step_ledger(
    session: Session,
) -> dict[str, Any]:
    """Seed tenant, agent, merchant, passport, and purchase with snapshot binding."""
    fixture = build_authorized_39_purchase_fixture()
    ledger = LedgerRepository(session)
    platform = PlatformRepository(session)

    if platform.get_organization(TENANT_ALPHA_ID) is None:
        platform.create_organization(
            name="Alpha Test Org", slug=f"alpha-{str(TENANT_ALPHA_ID)[:8]}", org_id=TENANT_ALPHA_ID
        )

    ledger.create_agent(fixture["agent"])
    ledger.create_merchant(fixture["approved_merchant"])
    passport = ledger.create_passport(fixture["passport"], created_by="seed")

    # Purchase 1 ($39.00) when available_budget_minor=10000, per_tx_limit_minor=7500
    ledger.save_proposal(fixture["proposal"])
    ledger.save_quote(fixture["quote_snapshot"])
    ledger.save_intent(fixture["payment_intent"])
    dec1 = fixture["decision"].model_copy(
        update={
            "policy_inputs": {
                **fixture["decision"].policy_inputs,
                "available_budget_minor": 10000,
                "per_tx_limit_minor": 7500,
            }
        }
    )
    ledger.save_decision(dec1)
    snap1 = ledger.get_latest_passport_snapshot(TENANT_ALPHA_ID, passport.id)
    assert snap1 is not None
    dec1_row = session.get(AuthorizationDecisionRow, dec1.id)
    assert dec1_row is not None
    dec1_row.passport_snapshot_id = snap1["id"]
    for ev in fixture["replay_request"].events:
        ledger.append_financial_event(
            tenant_id=ev.tenant_id,
            correlation_id=ev.correlation_id,
            payment_intent_id=ev.payment_intent_id,
            event_type=ev.event_type,
            actor_type=ev.actor_type,
            actor_id=ev.actor_id,
            payload=ev.payload,
        )
    for rec in fixture["replay_request"].evidence_records:
        ledger.save_evidence(
            rec.model_copy(update={"content_hash": compute_payload_hash(rec.content)})
        )

    # Reserve & capture $39.00 on Purchase 1, then mutate passport AFTER decision 1 (creates snapshot v2 with REVOKED & per_tx=1000)
    res = ledger.reserve_budget_atomic(
        tenant_id=TENANT_ALPHA_ID,
        correlation_id=fixture["payment_intent"].correlation_id,
        passport_id=passport.id,
        payment_intent_id=fixture["payment_intent"].id,
        amount_minor=3900,
        currency="USD",
        expires_at=BASE_TIME + timedelta(hours=1),
    )
    ledger.capture_reservation_atomic(TENANT_ALPHA_ID, res.id)
    ledger.update_passport_policy(
        TENANT_ALPHA_ID,
        passport.id,
        status=PassportStatus.REVOKED,
        per_tx_limit_minor=1000,
        created_by="admin-post-decision",
    )

    session.commit()
    return {
        "fixture": fixture,
        "ledger": ledger,
        "platform": platform,
        "decision_1": dec1,
        "snapshot_1": snap1,
    }


def test_rbac_enforces_ghostpay_read_and_simulate_permissions() -> None:
    fixture = build_authorized_39_purchase_fixture()
    req: ReplayRequest = fixture["replay_request"]
    current_role = {"role": Role.OWNER}

    def auth_dep() -> AuthContext:
        return _make_auth_context(current_role["role"])

    app = FastAPI()
    app.include_router(create_ghostpay_router(auth_resolver=auth_dep), prefix="/v1")
    client = TestClient(app)

    # Seed a trace as OPERATOR so read endpoints have a valid trace_id
    current_role["role"] = Role.OPERATOR
    ingest_payload = {
        "tenant_id": str(TENANT_ALPHA_ID),
        "agent_id": str(AGENT_PROCUREMENT_ID),
        "payment_intent_id": str(req.payment_intent.id),
        "events": [ev.model_dump(mode="json") for ev in req.events],
        "quote_snapshot": req.quote_snapshot.model_dump(mode="json"),
        "evidence_records": [rec.model_dump(mode="json") for rec in req.evidence_records],
        "recorded_decision": req.recorded_decision.model_dump(mode="json"),
        "recorded_passport": req.recorded_passport.model_dump(mode="json"),
        "recorded_merchant": req.recorded_merchant.model_dump(mode="json"),
        "approval_record": req.approval_record.model_dump(mode="json") if req.approval_record else None,
        "payment_intent": req.payment_intent.model_dump(mode="json"),
    }
    ingest_resp = client.post("/v1/ghostpay/traces/ingest", json=ingest_payload)
    assert ingest_resp.status_code == 200, ingest_resp.text
    trace_id = ingest_resp.json()["trace_id"]

    # VIEWER has ghostpay:read (200 on read routes), lacks ghostpay:simulate (403 on simulate/mutate)
    current_role["role"] = Role.VIEWER
    assert client.get("/v1/ghostpay/traces").status_code == 200
    assert client.get(f"/v1/ghostpay/traces/{trace_id}").status_code == 200
    assert client.get(f"/v1/ghostpay/traces/{trace_id}/timeline").status_code == 200
    assert client.post("/v1/ghostpay/replay", json=req.model_dump(mode="json")).status_code == 200
    assert client.get(f"/v1/ghostpay/agents/{AGENT_PROCUREMENT_ID}/profile").status_code == 200
    assert (
        client.post(
            f"/v1/ghostpay/agents/{AGENT_PROCUREMENT_ID}/analyze",
            json={"target_trace_id": trace_id},
        ).status_code
        == 200
    )

    for method, path, body in (
        ("POST", "/v1/ghostpay/simulate", {"request": req.model_dump(mode="json"), "overrides": {"per_tx_limit_minor": 1000}}),
        ("POST", "/v1/ghostpay/counterfactual", {"request": req.model_dump(mode="json"), "overrides": {"per_tx_limit_minor": 1000}}),
        (
            "POST",
            "/v1/ghostpay/replay/compare",
            {"replay_request": req.model_dump(mode="json"), "policies": [{"name": "strict", "per_tx_limit_minor": 1000}]},
        ),
        ("POST", "/v1/ghostpay/traces/ingest", ingest_payload),
        ("POST", "/v1/ghostpay/investigations", {"trace_id": trace_id}),
    ):
        resp = client.request(method, path, json=body)
        assert resp.status_code == 403, f"Expected 403 for VIEWER on {path}, got {resp.status_code}"
        assert resp.json()["detail"]["error_code"] == "PERMISSION_DENIED"

    # AGENT_SERVICE lacks BOTH ghostpay:read and ghostpay:simulate -> 403 everywhere
    current_role["role"] = Role.AGENT_SERVICE
    assert client.get("/v1/ghostpay/traces").status_code == 403
    assert client.get(f"/v1/ghostpay/traces/{trace_id}").status_code == 403
    assert client.post("/v1/ghostpay/replay", json=req.model_dump(mode="json")).status_code == 403
    assert (
        client.post(
            "/v1/ghostpay/simulate",
            json={"request": req.model_dump(mode="json"), "overrides": {"per_tx_limit_minor": 1000}},
        ).status_code
        == 403
    )

    # AUDITOR has both ghostpay:read and ghostpay:simulate -> 200
    current_role["role"] = Role.AUDITOR
    assert (
        client.post(
            "/v1/ghostpay/simulate",
            json={"request": req.model_dump(mode="json"), "overrides": {"per_tx_limit_minor": 1000}},
        ).status_code
        == 200
    )
    inv_resp = client.post("/v1/ghostpay/investigations", json={"trace_id": trace_id})
    assert inv_resp.status_code == 200


def test_rbac_bearer_jwt_header_rejects_viewer_on_simulate_and_agent_on_read() -> None:
    fixture = build_authorized_39_purchase_fixture()
    req: ReplayRequest = fixture["replay_request"]
    settings = get_settings()

    app = FastAPI()
    app.include_router(create_ghostpay_router(), prefix="/v1")
    client = TestClient(app)

    viewer_token = create_access_token(
        user_id=uuid4(),
        tenant_id=TENANT_ALPHA_ID,
        role=Role.VIEWER,
        secret=settings.jwt_secret,
    )
    agent_token = create_access_token(
        user_id=uuid4(),
        tenant_id=TENANT_ALPHA_ID,
        role=Role.AGENT_SERVICE,
        secret=settings.jwt_secret,
    )
    auditor_token = create_access_token(
        user_id=uuid4(),
        tenant_id=TENANT_ALPHA_ID,
        role=Role.AUDITOR,
        secret=settings.jwt_secret,
    )

    assert (
        client.post(
            "/v1/ghostpay/replay",
            json=req.model_dump(mode="json"),
            headers={"X-Tenant-Id": str(TENANT_ALPHA_ID), "Authorization": f"Bearer {viewer_token}"},
        ).status_code
        == 200
    )
    assert (
        client.post(
            "/v1/ghostpay/simulate",
            json={"request": req.model_dump(mode="json"), "overrides": {"per_tx_limit_minor": 1000}},
            headers={"X-Tenant-Id": str(TENANT_ALPHA_ID), "Authorization": f"Bearer {viewer_token}"},
        ).status_code
        == 403
    )
    assert (
        client.post(
            "/v1/ghostpay/replay",
            json=req.model_dump(mode="json"),
            headers={"X-Tenant-Id": str(TENANT_ALPHA_ID), "Authorization": f"Bearer {agent_token}"},
        ).status_code
        == 403
    )
    assert (
        client.post(
            "/v1/ghostpay/simulate",
            json={"request": req.model_dump(mode="json"), "overrides": {"per_tx_limit_minor": 1000}},
            headers={"X-Tenant-Id": str(TENANT_ALPHA_ID), "Authorization": f"Bearer {auditor_token}"},
        ).status_code
        == 200
    )


def test_adapter_reconstructs_replay_from_immutable_snapshot_and_policy_inputs(
    tmp_path: Path,
) -> None:
    engine, session_factory = _make_db_session_factory(tmp_path)
    try:
        with session_factory() as session:
            seeded = _seed_two_step_ledger(session)
            fixture = seeded["fixture"]
            adapter = SqlAlchemyGhostPayRepository(
                LedgerRepository(session), PlatformRepository(session)
            )
            replay_req = adapter.load_replay_request_by_payment(
                TENANT_ALPHA_ID, fixture["payment_intent"].id
            )
            assert replay_req is not None
            # Even though live passport was later REVOKED & capped at $10, historical replay
            # reconstructs snapshot v1 (ACTIVE, per_tx=7500) + policy_inputs available_budget=10000
            assert replay_req.recorded_passport.status == PassportStatus.ACTIVE
            assert replay_req.recorded_passport.per_tx_limit_minor == 7500
            assert replay_req.recorded_passport.available_budget_minor == 10000

            result = ReplayEngine.replay(replay_req)
            assert result.consistency_status == "CONSISTENT"
            assert result.recomputed_outcome == DecisionOutcome.ALLOW
            assert result.drift_detected is False
    finally:
        engine.dispose()


def test_adapter_falls_back_gracefully_when_snapshot_is_missing_for_legacy_rows(
    tmp_path: Path,
) -> None:
    engine, session_factory = _make_db_session_factory(tmp_path)
    try:
        with session_factory() as session:
            fixture = build_authorized_39_purchase_fixture()
            ledger = LedgerRepository(session)
            platform = PlatformRepository(session)
            if platform.get_organization(TENANT_ALPHA_ID) is None:
                platform.create_organization(
                    name="Alpha Legacy Org",
                    slug=f"legacy-{str(TENANT_ALPHA_ID)[:8]}",
                    org_id=TENANT_ALPHA_ID,
                )

            # Create rows WITHOUT calling get_passport_snapshot_for_decision (simulate legacy DB)
            class _LegacyLedgerProxy:
                def __getattr__(self, name: str) -> Any:
                    return getattr(ledger, name)

                def get_passport_snapshot_for_decision(
                    self, tenant_id: UUID, decision_id: UUID
                ) -> None:
                    return None

            ledger.create_agent(fixture["agent"])
            ledger.create_merchant(fixture["approved_merchant"])
            ledger.create_passport(fixture["passport"], created_by="legacy")
            ledger.save_proposal(fixture["proposal"])
            ledger.save_quote(fixture["quote_snapshot"])
            ledger.save_intent(fixture["payment_intent"])
            dec = fixture["decision"].model_copy(
                update={
                    "policy_inputs": {
                        "per_tx_limit_minor": 7500,
                        "available_budget_minor": 8500,
                    }
                }
            )
            ledger.save_decision(dec)
            # Mutate live passport limit down to 500; policy_inputs fallback still restores 7500!
            ledger.update_passport_policy(
                TENANT_ALPHA_ID, fixture["passport"].id, per_tx_limit_minor=500
            )
            session.commit()

            adapter = SqlAlchemyGhostPayRepository(_LegacyLedgerProxy(), platform)  # type: ignore[arg-type]
            replay_req = adapter.load_replay_request_by_payment(
                TENANT_ALPHA_ID, fixture["payment_intent"].id
            )
            assert replay_req is not None
            assert replay_req.recorded_passport.per_tx_limit_minor == 7500
            assert replay_req.recorded_passport.available_budget_minor == 8500

            # And if policy_inputs is completely empty, falls back to reservation/intent subtraction
            dec_empty = AuthorizationDecision(
                tenant_id=TENANT_ALPHA_ID,
                correlation_id=fixture["payment_intent"].correlation_id,
                payment_intent_id=fixture["payment_intent"].id,
                proposal_id=fixture["proposal"].id,
                passport_id=fixture["passport"].id,
                quote_snapshot_id=fixture["quote_snapshot"].id,
                quote_hash=fixture["quote_snapshot"].quote_hash,
                policy_version="policy-v1",
                outcome=DecisionOutcome.ALLOW,
                reason_codes=[DecisionReasonCode.OK_WITHIN_POLICY],
                explanation="Legacy decision without policy_inputs",
                policy_inputs={},
                decided_at=BASE_TIME + timedelta(minutes=1),
            )
            ledger.save_decision(dec_empty)
            intent_row = ledger.get_intent(TENANT_ALPHA_ID, fixture["payment_intent"].id)
            assert intent_row is not None
            # Verify fallback doesn't crash when snapshot is None and policy_inputs is {}
            reconstructed = adapter._reconstruct_decision_passport(
                TENANT_ALPHA_ID,
                intent_row.model_copy(update={"state": PaymentState.SUCCEEDED}),
                fixture["passport"].model_copy(update={"spent_minor": 3900}),
                dec_empty,
            )
            assert reconstructed.spent_minor == 0
    finally:
        engine.dispose()


def test_adapter_defensive_bridge_when_platform_lacks_trace_and_dna_methods(
    tmp_path: Path,
) -> None:
    engine, session_factory = _make_db_session_factory(tmp_path)
    try:
        with session_factory() as session:
            ledger = LedgerRepository(session)

            class _MinimalPlatform:
                pass

            adapter = SqlAlchemyGhostPayRepository(ledger, _MinimalPlatform())  # type: ignore[arg-type]
            assert adapter.list_ghostpay_traces(TENANT_ALPHA_ID) == []
            assert adapter.get_ghostpay_trace(TENANT_ALPHA_ID, uuid4()) is None
            assert adapter.get_agent_dna_profile(TENANT_ALPHA_ID, AGENT_PROCUREMENT_ID) is None

            # Also verify PaymentTrace save returns trace safely
            from ghostpay.testing import make_test_trace

            trace = make_test_trace()
            assert adapter.save_ghostpay_trace(TENANT_ALPHA_ID, trace) == trace
    finally:
        engine.dispose()


def test_router_persists_traces_agent_dna_and_investigations_across_restart_and_pagination(
    tmp_path: Path,
) -> None:
    engine, session_factory = _make_db_session_factory(tmp_path)
    try:
        def make_app() -> FastAPI:
            app = FastAPI()

            def _repo_dep() -> Iterator[SqlAlchemyGhostPayRepository]:
                session = session_factory()
                try:
                    yield SqlAlchemyGhostPayRepository(
                        LedgerRepository(session), PlatformRepository(session)
                    )
                    session.commit()
                except Exception:
                    session.rollback()
                    raise
                finally:
                    session.close()

            router = create_ghostpay_router(
                GhostPayService(),
                tenant_resolver=lambda: TENANT_ALPHA_ID,
                repo_resolver=_repo_dep,
                auth_resolver=lambda: _make_auth_context(Role.OPERATOR),
            )
            app.include_router(router, prefix="/v1")
            return app

        fixture = build_authorized_39_purchase_fixture()
        req: ReplayRequest = fixture["replay_request"]

        # Instance 1: ingest 3 traces and create 2 investigations
        client_1 = TestClient(make_app())
        trace_ids: list[str] = []
        for idx in range(3):
            pi = req.payment_intent.model_copy(
                update={"id": uuid4(), "idempotency_key": f"idem-key-{idx}"}
            )
            ingest_body = {
                "tenant_id": str(TENANT_ALPHA_ID),
                "agent_id": str(AGENT_PROCUREMENT_ID),
                "payment_intent_id": str(pi.id),
                "events": [ev.model_dump(mode="json") for ev in req.events],
                "quote_snapshot": req.quote_snapshot.model_dump(mode="json"),
                "evidence_records": [rec.model_dump(mode="json") for rec in req.evidence_records],
                "recorded_decision": req.recorded_decision.model_dump(mode="json"),
                "recorded_passport": req.recorded_passport.model_dump(mode="json"),
                "recorded_merchant": req.recorded_merchant.model_dump(mode="json"),
                "approval_record": req.approval_record.model_dump(mode="json") if req.approval_record else None,
                "payment_intent": pi.model_dump(mode="json"),
            }
            resp = client_1.post("/v1/ghostpay/traces/ingest", json=ingest_body)
            assert resp.status_code == 200, resp.text
            trace_ids.append(resp.json()["trace_id"])

        # Also seed a ledger payment chain to test POST /investigations by payment_intent_id
        with session_factory() as seed_session:
            seeded = _seed_two_step_ledger(seed_session)
            seeded_intent_id = str(seeded["fixture"]["payment_intent"].id)

        inv_1 = client_1.post("/v1/ghostpay/investigations", json={"trace_id": trace_ids[0]})
        assert inv_1.status_code == 200, inv_1.text
        inv_id_1 = inv_1.json()["investigation_id"]

        inv_2 = client_1.post(
            "/v1/ghostpay/investigations",
            json={
                "trace_id": seeded_intent_id,
                "counterfactual_policies": [{"name": "strict", "per_tx_limit_minor": 1000}],
            },
        )
        assert inv_2.status_code == 200, inv_2.text
        inv_id_2 = inv_2.json()["investigation_id"]

        # Instance 2 (fresh GhostPayService with empty RAM!) must recover everything from DB
        client_2 = TestClient(make_app())

        # Paginated traces list
        page_1 = client_2.get("/v1/ghostpay/traces?limit=2&offset=0")
        assert page_1.status_code == 200
        assert len(page_1.json()) == 2
        page_2 = client_2.get("/v1/ghostpay/traces?limit=2&offset=2")
        assert page_2.status_code == 200
        assert len(page_2.json()) == 1
        assert client_2.get("/v1/ghostpay/traces?limit=0").status_code == 422

        # Single trace & timeline recovered after restart
        fetched_trace = client_2.get(f"/v1/ghostpay/traces/{trace_ids[0]}")
        assert fetched_trace.status_code == 200
        assert fetched_trace.json()["trace_id"] == trace_ids[0]
        assert len(client_2.get(f"/v1/ghostpay/traces/{trace_ids[0]}/timeline").json()) == 4

        # Agent DNA profile & analyze recovered after restart
        profile_resp = client_2.get(f"/v1/ghostpay/agents/{AGENT_PROCUREMENT_ID}/profile")
        assert profile_resp.status_code == 200
        assert profile_resp.json()["sample_count"] == 3

        analyze_resp = client_2.post(
            f"/v1/ghostpay/agents/{AGENT_PROCUREMENT_ID}/analyze",
            json={"target_trace_id": trace_ids[2]},
        )
        assert analyze_resp.status_code == 200
        assert analyze_resp.json()["agent_id"] == str(AGENT_PROCUREMENT_ID)

        # Persisted investigations & DisputeOS evidence bundle recovered after restart
        inv_list_p1 = client_2.get("/v1/ghostpay/investigations?limit=1&offset=0")
        assert inv_list_p1.status_code == 200
        assert inv_list_p1.json()["total"] == 2
        assert len(inv_list_p1.json()["items"]) == 1

        got_inv_1 = client_2.get(f"/v1/ghostpay/investigations/{inv_id_1}")
        assert got_inv_1.status_code == 200
        assert got_inv_1.json()["investigation_id"] == inv_id_1

        got_inv_2 = client_2.get(f"/v1/ghostpay/investigations/{inv_id_2}")
        assert got_inv_2.status_code == 200
        assert got_inv_2.json()["mode"] == "COUNTERFACTUAL"

        bundle_resp = client_2.get(f"/v1/ghostpay/investigations/{inv_id_1}/evidence")
        assert bundle_resp.status_code == 200
        assert bundle_resp.json()["tenant_id"] == str(TENANT_ALPHA_ID)

        # Cross-tenant / missing trace lookup returns 404
        assert client_2.get(f"/v1/ghostpay/traces/{uuid4()}").status_code == 404
    finally:
        engine.dispose()
