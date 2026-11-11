"""Deployment trust boundaries and real mounted service contracts."""

import pytest
from contracts.fixtures import (
    TENANT_ALPHA_ID,
    TENANT_BETA_ID,
    build_authorized_39_purchase_fixture,
)
from fastapi.testclient import TestClient
from ghostpay.app import create_app

TOKEN = "test-only-ghostpay-token-" + "x" * 32


@pytest.fixture
def client():
    with TestClient(create_app({TOKEN: str(TENANT_ALPHA_ID)})) as client:
        yield client


@pytest.mark.parametrize(
    "tokens",
    [
        {},
        {"short": str(TENANT_ALPHA_ID)},
        {TOKEN: "invalid"},
        [],
        {"é" * 40: str(TENANT_ALPHA_ID)},
    ],
)
def test_configuration_fails_closed(tokens):
    with pytest.raises(ValueError, match="Configure GHOSTPAY_TOKENS"):
        create_app(tokens)


def test_missing_configuration_fails_closed(monkeypatch):
    monkeypatch.delenv("GHOSTPAY_TOKENS", raising=False)
    with pytest.raises(ValueError):
        create_app()


def test_health_and_web_assets(client):
    for path in ("/healthz", "/", "/app.js", "/app.css"):
        response = client.get(path)
        assert response.status_code == 200
        assert response.headers["cache-control"] == "no-store"
        assert "frame-ancestors 'none'" in response.headers["content-security-policy"]
    assert client.get("/openapi.json").status_code == 404


@pytest.mark.parametrize("authorization", [None, "Bearer wrong", "Basic anything"])
def test_missing_or_wrong_authentication_is_rejected(client, authorization):
    headers = {"Authorization": authorization} if authorization else {}
    response = client.post(
        "/v1/ghostpay/replay",
        json=build_authorized_39_purchase_fixture()["replay_request"].model_dump(
            mode="json"
        ),
        headers=headers,
    )
    assert response.status_code == 401


def test_token_controls_tenant_even_if_header_is_forged(client):
    record = build_authorized_39_purchase_fixture()["replay_request"]
    record.tenant_id = TENANT_BETA_ID
    response = client.post(
        "/v1/ghostpay/replay",
        json=record.model_dump(mode="json"),
        headers={
            "Authorization": f"Bearer {TOKEN}",
            "X-Tenant-Id": str(TENANT_BETA_ID),
        },
    )
    assert response.status_code == 403


def test_deployed_example_replay_and_simulation(client):
    headers = {"Authorization": f"Bearer {TOKEN}"}
    example = client.get("/v1/ghostpay/example", headers=headers).json()
    assert example["source"] == "SYNTHETIC"
    record = example["request"]
    replay = client.post("/v1/ghostpay/replay", json=record, headers=headers)
    assert replay.status_code == 200
    assert replay.json()["consistency_status"] == "CONSISTENT"
    simulated = client.post(
        "/v1/ghostpay/simulate",
        json={"request": record, "overrides": {"per_tx_limit_minor": 3000}},
        headers=headers,
    )
    assert simulated.status_code == 200
    assert simulated.json()["recomputed_outcome"] == "DENY"
    assert simulated.json()["executed_payment"] is False


def test_invalid_inputs_do_not_echo_payload(client):
    marker = "private-user-content"
    response = client.post(
        "/v1/ghostpay/replay",
        json={"secret": marker},
        headers={"Authorization": f"Bearer {TOKEN}"},
    )
    assert response.status_code == 422
    assert marker not in response.text


def test_request_size_limit(client):
    response = client.post("/v1/ghostpay/replay", content=b"x" * 2_097_153)
    assert response.status_code == 413


def test_stored_snapshots_are_tenant_scoped_and_read_only(tmp_path, monkeypatch):
    record = build_authorized_39_purchase_fixture()["replay_request"]
    path = tmp_path / str(record.tenant_id) / f"{record.payment_intent.id}.json"
    path.parent.mkdir()
    path.write_text(record.model_dump_json())
    original = path.read_bytes()
    monkeypatch.setenv("GHOSTPAY_SNAPSHOT_DIR", str(tmp_path))
    with TestClient(
        create_app({TOKEN: str(TENANT_ALPHA_ID), TOKEN + "b": str(TENANT_BETA_ID)})
    ) as client:
        url = f"/v1/ghostpay/payments/{record.payment_intent.id}/replay"
        assert (
            client.get(url, headers={"Authorization": f"Bearer {TOKEN}"}).json()[
                "consistency_status"
            ]
            == "CONSISTENT"
        )
        assert (
            client.get(url, headers={"Authorization": f"Bearer {TOKEN}b"}).status_code
            == 404
        )
        record.payment_intent.id = TENANT_BETA_ID
        path.write_text(record.model_dump_json())
        assert (
            client.get(url, headers={"Authorization": f"Bearer {TOKEN}"}).status_code
            == 422
        )
    path.write_bytes(original)
    with TestClient(create_app({TOKEN: str(TENANT_ALPHA_ID)})) as client:
        client.get(url, headers={"Authorization": f"Bearer {TOKEN}"})
    assert path.read_bytes() == original


def test_timeline_rejects_mixed_transaction_chains(client):
    record = build_authorized_39_purchase_fixture()["replay_request"]
    record.events[-1].correlation_id = TENANT_BETA_ID
    response = client.post(
        "/v1/ghostpay/timeline",
        json={
            "events": [event.model_dump(mode="json") for event in record.events],
        },
        headers={"Authorization": f"Bearer {TOKEN}"},
    )
    assert response.status_code == 400
