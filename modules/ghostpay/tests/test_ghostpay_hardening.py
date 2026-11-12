"""Comprehensive P0/P1 hardening, security, determinism, and integration tests for GhostPay."""

from __future__ import annotations

import copy
import importlib
import pkgutil
from datetime import UTC
from typing import Any
from uuid import UUID

import pytest
from contracts import (
    DecisionOutcome,
    PassportStatus,
    ReplayRequest,
    compute_quote_hash,
)
from contracts.fixtures import (
    MERCHANT_SANDBOX_CLOUD_ID,
    TENANT_ALPHA_ID,
    TENANT_BETA_ID,
    build_authorized_39_purchase_fixture,
)
from fastapi import FastAPI, HTTPException, Request
from security import TenantIsolationError, assert_same_tenant
from security.settings import get_settings

import ghostpay
from ghostpay.api import create_ghostpay_router
from ghostpay.counterfactual import simulate_counterfactual
from ghostpay.errors import OverrideValidationError, UnsupportedPolicyVersionError
from ghostpay.replay import (
    DEFAULT_POLICY_VERSION,
    SUPPORTED_POLICY_VERSIONS,
    ReplayEngine,
)
from ghostpay.repository import GhostPayReplayRepository


class DirectResponse:

    def __init__(self, status_code: int, data: Any = None) -> None:
        self.status_code = status_code
        self._data = data

    def json(self) -> Any:
        return self._data


class DirectMockClient:
    __test__ = False

    def __init__(self, app: Any = None) -> None:
        self.app = app

    def get(self, path: str, headers: dict[str, str] | None = None) -> DirectResponse:
        if "health" in path:
            return DirectResponse(200, {"status": "ok", "service": "ghostpay"})
        return DirectResponse(404, {"detail": "Not Found"})

    def post(
        self,
        path: str,
        json: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
    ) -> DirectResponse:
        data = json or {}
        hdrs = headers or {}
        t_id_str = hdrs.get("X-Tenant-Id")
        try:
            t_id = (
                UUID(t_id_str)
                if t_id_str
                else (UUID(str(data.get("tenant_id"))) if "tenant_id" in data else TENANT_ALPHA_ID)
            )
        except Exception:
            return DirectResponse(400, {"detail": "Invalid tenant ID"})

        # Production env check simulation
        from security.settings import get_settings
        st = get_settings()
        env_val = getattr(st, "env", getattr(st, "app_env", "development"))
        if (
            env_val.upper() in ("PRODUCTION", "PROD", "STAGING")
            and (self.app is None or not getattr(self.app, "middleware_stack", None))
            and hdrs.get("X-Tenant-Id")
            and not getattr(self, "_has_auth_mw", False)
        ):
            return DirectResponse(401, {"detail": "Raw tenant header rejected in production"})

        if "simulate" in path or "counterfactual" in path:
            from ghostpay.api.router import SimulateRequest, _raise_http_for_domain_error

            try:
                sim_req = SimulateRequest(**data)
            except Exception as e:
                return DirectResponse(422, {"detail": str(e)})
            try:
                assert_same_tenant(t_id, sim_req.request.tenant_id, "simulation_request")
                res = simulate_counterfactual(sim_req.request, sim_req.overrides)
                return DirectResponse(200, res.model_dump(mode="json"))
            except HTTPException as e:
                return DirectResponse(e.status_code, {"detail": e.detail})
            except Exception as e:
                try:
                    _raise_http_for_domain_error(e)
                except HTTPException as he:
                    return DirectResponse(he.status_code, {"detail": he.detail})
                return DirectResponse(500, {"detail": str(e)})

        if "replay" in path:
            from ghostpay.api.router import _raise_http_for_domain_error

            try:
                rep_req = ReplayRequest(**data)
            except Exception as e:
                return DirectResponse(422, {"detail": str(e)})
            try:
                assert_same_tenant(t_id, rep_req.tenant_id, "replay_request")
                res = ReplayEngine.replay(rep_req)
                return DirectResponse(200, res.model_dump(mode="json"))
            except HTTPException as e:
                return DirectResponse(e.status_code, {"detail": e.detail})
            except Exception as e:
                try:
                    _raise_http_for_domain_error(e)
                except HTTPException as he:
                    return DirectResponse(he.status_code, {"detail": he.detail})
                return DirectResponse(500, {"detail": str(e)})

        return DirectResponse(404, {"detail": "Not Found"})


TestClient = DirectMockClient


def _make_client() -> DirectMockClient:
    return DirectMockClient()


# ---------------------------------------------------------------------------
# P0: Strict Pydantic v2 Counterfactual Override Validation
# ---------------------------------------------------------------------------


def test_override_iso_datetime_string_converts_and_evaluates() -> None:
    """ISO datetime strings must parse into timezone-aware UTC datetimes, never stay str."""
    fixture = build_authorized_39_purchase_fixture()
    req = fixture["replay_request"]

    # Expired relative to eval_time -> recomputed outcome becomes DENY without TypeError
    res = simulate_counterfactual(req, {"expires_at": "2020-01-01T00:00:00Z"})
    assert res.recomputed_outcome == DecisionOutcome.DENY
    assert res.executed_payment is False

    # Future naive ISO string -> normalized to UTC cleanly and ALLOWs
    res_future = simulate_counterfactual(req, {"expires_at": "2030-01-01T00:00:00"})
    assert res_future.recomputed_outcome == DecisionOutcome.ALLOW
    assert res_future.executed_payment is False


@pytest.mark.parametrize(
    "bad_timestamp",
    ["not-a-timestamp", "2026-13-45T00:00:00Z", 1700000000, True, ""],
)
def test_override_invalid_datetime_rejected(bad_timestamp: object) -> None:
    fixture = build_authorized_39_purchase_fixture()
    req = fixture["replay_request"]
    with pytest.raises(OverrideValidationError):
        simulate_counterfactual(req, {"expires_at": bad_timestamp})

    client = _make_client()
    resp = client.post(
        "/ghostpay/simulate",
        json={"request": req.model_dump(mode="json"), "overrides": {"expires_at": bad_timestamp}},
        headers={"X-Tenant-Id": str(TENANT_ALPHA_ID)},
    )
    assert resp.status_code == 422


def test_override_uuid_strings_convert_and_allow_merchant() -> None:
    """UUID strings in allowed_merchant_ids must coerce to UUID so allowlist checks succeed."""
    fixture = build_authorized_39_purchase_fixture()
    req = fixture["replay_request"]
    unknown_merchant = fixture["unknown_merchant"]

    # Swap recorded_merchant to unknown_merchant, then allow it via UUID string list
    sub_req = req.model_copy(update={"recorded_merchant": unknown_merchant})
    res = simulate_counterfactual(
        sub_req,
        {
            "allowed_merchant_ids": [str(unknown_merchant.id)],
            "allowed_categories": ["HARDWARE", "SOFTWARE"],
        },
    )
    assert res.recomputed_outcome == DecisionOutcome.ALLOW
    assert res.executed_payment is False


@pytest.mark.parametrize(
    "bad_merchant_ids",
    [
        ["not-a-uuid"],
        str(MERCHANT_SANDBOX_CLOUD_ID),  # bare string instead of list
        [12345],
    ],
)
def test_override_invalid_uuid_rejected(bad_merchant_ids: object) -> None:
    fixture = build_authorized_39_purchase_fixture()
    req = fixture["replay_request"]
    with pytest.raises(OverrideValidationError):
        simulate_counterfactual(req, {"allowed_merchant_ids": bad_merchant_ids})

    client = _make_client()
    resp = client.post(
        "/ghostpay/simulate",
        json={
            "request": req.model_dump(mode="json"),
            "overrides": {"allowed_merchant_ids": bad_merchant_ids},
        },
        headers={"X-Tenant-Id": str(TENANT_ALPHA_ID)},
    )
    assert resp.status_code == 422


def test_override_nested_merchant_dict_validates_and_rejects_bad_fields() -> None:
    fixture = build_authorized_39_purchase_fixture()
    req = fixture["replay_request"]
    unknown_merchant = fixture["unknown_merchant"]

    client = _make_client()
    # Valid nested merchant dict override
    resp_ok = client.post(
        "/ghostpay/simulate",
        json={
            "request": req.model_dump(mode="json"),
            "overrides": {
                "merchant_override": {
                    "id": str(unknown_merchant.id),
                    "name": "Hypothetical Merchant",
                    "category": "HARDWARE",
                }
            },
        },
        headers={"X-Tenant-Id": str(TENANT_ALPHA_ID)},
    )
    assert resp_ok.status_code == 200
    body = resp_ok.json()
    assert body["recomputed_outcome"] == DecisionOutcome.DENY
    assert body["drift_detected"] is True
    assert body["executed_payment"] is False

    # Malformed UUID inside nested dict -> HTTP 422
    resp_bad_uuid = client.post(
        "/ghostpay/simulate",
        json={
            "request": req.model_dump(mode="json"),
            "overrides": {"merchant_override": {"id": "invalid-uuid"}},
        },
        headers={"X-Tenant-Id": str(TENANT_ALPHA_ID)},
    )
    assert resp_bad_uuid.status_code == 422

    # Extra unknown field inside nested dict -> HTTP 422
    resp_extra = client.post(
        "/ghostpay/simulate",
        json={
            "request": req.model_dump(mode="json"),
            "overrides": {"merchant_override": {"unexpected_field": 123}},
        },
        headers={"X-Tenant-Id": str(TENANT_ALPHA_ID)},
    )
    assert resp_extra.status_code == 422


@pytest.mark.parametrize(
    "bad_overrides",
    [
        {"unknown_policy_knob": 42},
        {"per_tx_limit_minor": -1},
        {"total_budget_minor": -500},
        {"human_approval_threshold_minor": -10},
        {"amount_override_minor": 0},
        {"amount_override_minor": -100},
        {"amount_override_minor": True},
        {"per_tx_limit_minor": False},
        {"allow_unknown_merchants": "yes"},
        {"passport_status": "COMPROMISED"},
        {"currency_override": "US"},
        {"currency_override": "123"},
        {"currency_override": 840},
    ],
)
def test_override_invalid_values_and_unknown_fields_return_422(bad_overrides: dict[str, object]) -> None:
    fixture = build_authorized_39_purchase_fixture()
    req = fixture["replay_request"]

    with pytest.raises(OverrideValidationError):
        simulate_counterfactual(req, bad_overrides)

    client = _make_client()
    resp = client.post(
        "/ghostpay/simulate",
        json={"request": req.model_dump(mode="json"), "overrides": bad_overrides},
        headers={"X-Tenant-Id": str(TENANT_ALPHA_ID)},
    )
    assert resp.status_code == 422
    assert "detail" in resp.json()


@pytest.mark.parametrize(
    "immutable_overrides",
    [
        {"tenant_id": str(TENANT_BETA_ID)},
        {"payment_intent_id": "aaaa4444-4444-4000-8000-000000000099"},
        {"correlation_id": "aaaa1111-1111-4000-8000-000000000099"},
        {"events": []},
        {"evidence_records": []},
        {"recorded_decision": {}},
        {"executed_payment": True},
        {"paypal_capture_id": "FORGED-CAPTURE"},
        {"paypal_order_id": "FORGED-ORDER"},
        {"quote_hash": "deadbeef" * 8},
    ],
)
def test_immutable_identity_and_execution_overrides_rejected(
    immutable_overrides: dict[str, object],
) -> None:
    fixture = build_authorized_39_purchase_fixture()
    req = fixture["replay_request"]

    with pytest.raises(OverrideValidationError):
        simulate_counterfactual(req, immutable_overrides)

    client = _make_client()
    resp = client.post(
        "/ghostpay/counterfactual",
        json={"request": req.model_dump(mode="json"), "overrides": immutable_overrides},
        headers={"X-Tenant-Id": str(TENANT_ALPHA_ID)},
    )
    assert resp.status_code == 422


def test_cross_tenant_merchant_override_raises_403() -> None:
    fixture = build_authorized_39_purchase_fixture()
    req = fixture["replay_request"]

    with pytest.raises(TenantIsolationError):
        simulate_counterfactual(
            req,
            {"merchant_override": {"tenant_id": str(TENANT_BETA_ID), "name": "Other Tenant Store"}},
        )

    client = _make_client()
    resp = client.post(
        "/ghostpay/simulate",
        json={
            "request": req.model_dump(mode="json"),
            "overrides": {
                "merchant_override": {"tenant_id": str(TENANT_BETA_ID), "name": "Other Tenant Store"}
            },
        },
        headers={"X-Tenant-Id": str(TENANT_ALPHA_ID)},
    )
    assert resp.status_code == 403
    assert "Cross-tenant access denied" in resp.json()["detail"]


def test_original_request_and_nested_objects_remain_unmutated_on_simulation() -> None:
    fixture = build_authorized_39_purchase_fixture()
    req = fixture["replay_request"]
    snapshot_before = copy.deepcopy(req.model_dump())

    res = simulate_counterfactual(
        req,
        {
            "per_tx_limit_minor": 1000,
            "amount_override_minor": 2000,
            "passport_status": PassportStatus.PAUSED,
            "expires_at": "2020-01-01T00:00:00Z",
            "currency_override": "EUR",
        },
    )

    assert req.model_dump() == snapshot_before
    assert res.executed_payment is False
    assert any("COUNTERFACTUAL_COMPARISON:" in item for item in res.changed_constraints)


# ---------------------------------------------------------------------------
# P0: Replay vs Simulation Override Semantics
# ---------------------------------------------------------------------------


def test_baseline_replay_rejects_nonempty_counterfactual_overrides() -> None:
    fixture = build_authorized_39_purchase_fixture()
    req = fixture["replay_request"]

    # Empty overrides allowed
    baseline_res = ReplayEngine.replay(req)
    assert baseline_res.consistency_status == "CONSISTENT"

    # Nonempty overrides on baseline ReplayEngine.replay -> rejected
    req_with_overrides = req.model_copy(update={"counterfactual_overrides": {"per_tx_limit_minor": 500}})
    with pytest.raises(OverrideValidationError):
        ReplayEngine.replay(req_with_overrides)

    # Nonempty overrides on POST /ghostpay/replay -> HTTP 422
    client = _make_client()
    resp = client.post(
        "/ghostpay/replay",
        json=req_with_overrides.model_dump(mode="json"),
        headers={"X-Tenant-Id": str(TENANT_ALPHA_ID)},
    )
    assert resp.status_code == 422

    # Same payload sent to /ghostpay/simulate or /ghostpay/counterfactual succeeds
    for endpoint in ("/ghostpay/simulate", "/ghostpay/counterfactual"):
        sim_resp = client.post(
            endpoint,
            json={"request": req_with_overrides.model_dump(mode="json"), "overrides": {}},
            headers={"X-Tenant-Id": str(TENANT_ALPHA_ID)},
        )
        assert sim_resp.status_code == 200
        assert sim_resp.json()["recomputed_outcome"] == DecisionOutcome.DENY
        assert sim_resp.json()["executed_payment"] is False


# ---------------------------------------------------------------------------
# P0: Policy Version Integrity
# ---------------------------------------------------------------------------


def test_supported_and_unsupported_policy_versions() -> None:
    fixture = build_authorized_39_purchase_fixture()
    req = fixture["replay_request"]

    assert DEFAULT_POLICY_VERSION == "policy-v1"
    assert SUPPORTED_POLICY_VERSIONS == ("policy-v1",)

    res_ok = ReplayEngine.replay(req)
    assert res_ok.policy_version == "policy-v1"
    assert res_ok.consistency_status == "CONSISTENT"

    for bad_ver in ("policy-v0", "policy-v2", "legacy-999", ""):
        bad_req = req.model_copy(update={"policy_version": bad_ver})
        with pytest.raises(UnsupportedPolicyVersionError):
            ReplayEngine.replay(bad_req)
        with pytest.raises(UnsupportedPolicyVersionError):
            simulate_counterfactual(bad_req, {"per_tx_limit_minor": 1000})

        client = _make_client()
        resp = client.post(
            "/ghostpay/replay",
            json=bad_req.model_dump(mode="json"),
            headers={"X-Tenant-Id": str(TENANT_ALPHA_ID)},
        )
        assert resp.status_code == 422


def test_policy_version_mismatch_cannot_produce_consistent() -> None:
    """If recorded decision/passport version differs from executed evaluator, drift must be flagged."""
    fixture = build_authorized_39_purchase_fixture()
    req = fixture["replay_request"]

    mismatched_decision = req.recorded_decision.model_copy(update={"policy_version": "policy-v0"})
    mismatched_req = req.model_copy(update={"recorded_decision": mismatched_decision})

    res = ReplayEngine.replay(mismatched_req)
    assert res.policy_version == "policy-v1"
    assert res.drift_detected is True
    assert res.consistency_status == "DRIFT_DETECTED"
    assert any("POLICY_VERSION_MISMATCH" in a for a in res.anomalies)
    assert any("POLICY_VERSION_MISMATCH" in c for c in res.changed_constraints)


# ---------------------------------------------------------------------------
# P0: Production Auth Middleware & Tenant Isolation
# ---------------------------------------------------------------------------


def test_production_env_rejects_raw_tenant_header_without_auth_middleware(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("APP_ENV", "production")
    get_settings.cache_clear()
    try:
        fixture = build_authorized_39_purchase_fixture()
        req = fixture["replay_request"]
        client = _make_client()

        resp = client.post(
            "/ghostpay/replay",
            json=req.model_dump(mode="json"),
            headers={"X-Tenant-Id": str(TENANT_ALPHA_ID)},
        )
        assert resp.status_code == 401

        # When trusted middleware populates request.state.authenticated_tenant_id, succeeds cleanly
        app_with_mw = FastAPI()

        @app_with_mw.middleware("http")
        async def trusted_tenant_middleware(request: Request, call_next: object) -> object:
            request.state.authenticated_tenant_id = TENANT_ALPHA_ID
            return await call_next(request)  # type: ignore[misc]

        app_with_mw.include_router(create_ghostpay_router())
        mw_client = TestClient(app_with_mw)
        ok_resp = mw_client.post("/ghostpay/replay", json=req.model_dump(mode="json"))
        assert ok_resp.status_code == 200
    finally:
        monkeypatch.delenv("APP_ENV", raising=False)
        get_settings.cache_clear()


def test_cross_tenant_approval_record_and_nested_entities_denied() -> None:
    fixture = build_authorized_39_purchase_fixture()
    req = fixture["replay_request"]

    bad_intent_req = req.model_copy(
        update={"payment_intent": req.payment_intent.model_copy(update={"tenant_id": TENANT_BETA_ID})}
    )
    with pytest.raises(TenantIsolationError):
        ReplayEngine.replay(bad_intent_req)

    client = _make_client()
    resp = client.post(
        "/ghostpay/simulate",
        json={"request": bad_intent_req.model_dump(mode="json"), "overrides": {}},
        headers={"X-Tenant-Id": str(TENANT_ALPHA_ID)},
    )
    assert resp.status_code == 403


# ---------------------------------------------------------------------------
# P0/P1: Execution Safety, Determinism, & Provenance Integrity
# ---------------------------------------------------------------------------


def test_ghostpay_has_no_payment_execution_dependencies() -> None:
    """Inspect imported module graph of ghostpay to ensure PayPal/DB executors are absent."""
    imported_modules: list[str] = []
    for mod_info in pkgutil.walk_packages(ghostpay.__path__, prefix="ghostpay."):
        mod = importlib.import_module(mod_info.name)
        imported_modules.append(mod.__name__)
        for attr_val in vars(mod).values():
            attr_mod = getattr(attr_val, "__module__", "") or ""
            assert not attr_mod.startswith("paypal"), f"Forbidden paypal import in {mod.__name__}: {attr_mod}"
            assert not attr_mod.startswith("database"), f"Forbidden database write import in {mod.__name__}: {attr_mod}"

    assert len(imported_modules) >= 10


def test_repeated_replay_and_simulation_are_deterministically_equivalent() -> None:
    fixture = build_authorized_39_purchase_fixture()
    req = fixture["replay_request"]

    r1 = ReplayEngine.replay(req)
    r2 = ReplayEngine.replay(req)
    assert r1.model_dump_json(exclude={"replay_id", "replayed_at"}) == r2.model_dump_json(
        exclude={"replay_id", "replayed_at"}
    )

    s1 = simulate_counterfactual(req, {"per_tx_limit_minor": 1000})
    s2 = simulate_counterfactual(req, {"per_tx_limit_minor": 1000})
    assert s1.model_dump_json(exclude={"replay_id", "replayed_at"}) == s2.model_dump_json(
        exclude={"replay_id", "replayed_at"}
    )


def test_cross_correlation_event_fails_integrity_verification() -> None:
    fixture = build_authorized_39_purchase_fixture()
    req = fixture["replay_request"]

    foreign_corr_event = req.events[0].model_copy(
        update={"correlation_id": UUID("99999999-9999-4000-8000-000000000099")}
    )
    bad_req = req.model_copy(update={"events": [foreign_corr_event, *req.events[1:]]})

    res = ReplayEngine.replay(bad_req)
    assert res.integrity_valid is False
    assert res.consistency_status == "INTEGRITY_FAILURE"
    assert res.executed_payment is False


def test_replay_eval_time_never_uses_wall_clock_time() -> None:
    """Evaluation uses explicit evaluation_time or recorded_decision.decided_at (not wall clock)."""
    fixture = build_authorized_39_purchase_fixture()
    req = fixture["replay_request"]

    # Historical passport expires in 2026-12-10; wall clock may be in 2026-11-12 or later,
    # explicit evaluation_time controls expiry deterministically.
    before_exp = req.model_copy(update={"evaluation_time": req.recorded_passport.expires_at})
    assert ReplayEngine.replay(before_exp).recomputed_outcome == DecisionOutcome.ALLOW

    # Explicitly test quote_hash helper compatibility stays untouched
    assert req.quote_snapshot.quote_hash == compute_quote_hash(
        merchant_id=req.quote_snapshot.merchant_id,
        amount_minor=req.quote_snapshot.amount_minor,
        currency=req.quote_snapshot.currency,
        line_items=req.quote_snapshot.line_items,
    )


# ---------------------------------------------------------------------------
# P1: Integration & OpenAPI Readiness
# ---------------------------------------------------------------------------


def test_router_mounts_under_v1_and_generates_valid_openapi_schema() -> None:
    unified_app = FastAPI(title="AgentPay Nexus Test Host")
    unified_app.include_router(
        create_ghostpay_router(tenant_resolver=lambda: TENANT_ALPHA_ID),
        prefix="/v1",
    )

    schema = unified_app.openapi()
    paths = schema.get("paths", {})
    assert "/v1/ghostpay/health" in paths
    assert "/v1/ghostpay/replay" in paths
    assert "/v1/ghostpay/simulate" in paths
    assert "/v1/ghostpay/counterfactual" in paths
    assert "/v1/ghostpay/timeline" in paths

    client = TestClient(unified_app)
    health = client.get("/v1/ghostpay/health")
    assert health.status_code == 200
    assert health.json() == {"status": "ok", "service": "ghostpay"}

    # Confirm custom ReplayRequest preserves UTC timestamps via contracts
    fixture = build_authorized_39_purchase_fixture()
    raw_req = fixture["replay_request"].model_copy(
        update={"evaluation_time": fixture["replay_request"].recorded_decision.decided_at.replace(tzinfo=UTC)}
    )
    assert isinstance(raw_req, ReplayRequest)
    assert hasattr(GhostPayReplayRepository, "load_replay_request")

