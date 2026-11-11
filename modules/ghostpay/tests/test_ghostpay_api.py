"""Tests for GhostPay FastAPI router surface."""

from __future__ import annotations

from contracts import DecisionOutcome
from contracts.fixtures import (
    TENANT_ALPHA_ID,
    TENANT_BETA_ID,
    build_authorized_39_purchase_fixture,
)
from fastapi import FastAPI
from fastapi.testclient import TestClient
from ghostpay.api import router

app = FastAPI()
app.include_router(router)
client = TestClient(app)


def test_api_health_check() -> None:
    response = client.get("/ghostpay/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert data["service"] == "ghostpay"


def test_api_replay_success() -> None:
    fixture = build_authorized_39_purchase_fixture()
    req = fixture["replay_request"]
    payload = req.model_dump(mode="json")

    response = client.post(
        "/ghostpay/replay",
        json=payload,
        headers={"X-Tenant-Id": str(TENANT_ALPHA_ID)},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["consistency_status"] == "CONSISTENT"
    assert data["original_outcome"] == DecisionOutcome.ALLOW
    assert data["recomputed_outcome"] == DecisionOutcome.ALLOW
    assert data["executed_payment"] is False
    assert len(data["timeline"]) == 4


def test_api_replay_cross_tenant_forbidden() -> None:
    fixture = build_authorized_39_purchase_fixture()
    req = fixture["replay_request"]
    payload = req.model_dump(mode="json")

    # Mismatched tenant in header vs payload
    response = client.post(
        "/ghostpay/replay",
        json=payload,
        headers={"X-Tenant-Id": str(TENANT_BETA_ID)},
    )
    assert response.status_code == 403
    assert "Cross-tenant access denied" in response.json()["detail"]


def test_api_simulate_counterfactual() -> None:
    fixture = build_authorized_39_purchase_fixture()
    req = fixture["replay_request"]

    payload = {
        "request": req.model_dump(mode="json"),
        "overrides": {
            "per_tx_limit_minor": 1000,
        },
    }

    response = client.post(
        "/ghostpay/simulate",
        json=payload,
        headers={"X-Tenant-Id": str(TENANT_ALPHA_ID)},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["recomputed_outcome"] == DecisionOutcome.DENY
    assert data["drift_detected"] is True
    assert data["executed_payment"] is False


def test_api_reconstruct_timeline() -> None:
    fixture = build_authorized_39_purchase_fixture()
    req = fixture["replay_request"]

    events_data = [e.model_dump(mode="json") for e in req.events]
    evidence_data = [ev.model_dump(mode="json") for ev in req.evidence_records]

    response = client.post(
        "/ghostpay/timeline",
        json={"events": events_data, "evidence_records": evidence_data},
        headers={"X-Tenant-Id": str(TENANT_ALPHA_ID)},
    )
    assert response.status_code == 200
    entries = response.json()
    assert len(entries) == 4
    assert [e["sequence_number"] for e in entries] == [1, 2, 3, 4]
