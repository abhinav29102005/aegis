"""Counterfactual JSON validation and isolation regression tests."""

from copy import deepcopy

import pytest
from contracts import DecisionOutcome
from contracts.fixtures import (
    TENANT_ALPHA_ID,
    TENANT_BETA_ID,
    build_authorized_39_purchase_fixture,
)
from fastapi import FastAPI
from fastapi.testclient import TestClient
from ghostpay.api import router
from ghostpay.counterfactual import simulate_counterfactual
from pydantic import ValidationError
from security import TenantIsolationError


@pytest.fixture
def request_record():
    return build_authorized_39_purchase_fixture()["replay_request"]


@pytest.mark.parametrize(
    "overrides",
    [{"amount_override_minor": value} for value in (-1, 0, 1.5, True, "3900", None)]
    + [
        {"per_tx_limit_minor": -1},
        {"per_tx_limit_minor": "1000"},
        {"total_budget_minor": -1},
        {"human_approval_threshold_minor": -1},
        {"allow_unknown_merchants": "false"},
        {"expires_at": "invalid"},
        {"expires_at": "2026-12-10T12:00:00"},
        {"allowed_merchant_ids": ["invalid"]},
        {"passport_status": "invalid"},
        {"unsupported": 1},
        {"merchant_override": {"id": "invalid"}},
        {"merchant_override": {"unknown_field": "invalid"}},
    ],
)
@pytest.mark.parametrize("route", ["simulate", "counterfactual"])
def test_invalid_overrides_return_controlled_client_error(
    request_record, overrides, route
):
    app = FastAPI()
    app.include_router(router)
    payload = {
        "request": request_record.model_dump(mode="json"),
        "overrides": overrides,
    }
    original = deepcopy(payload)
    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.post(
            f"/ghostpay/{route}",
            json=payload,
            headers={"X-Tenant-Id": str(TENANT_ALPHA_ID)},
        )
    assert response.status_code == 400
    assert response.json() == {"detail": "Invalid counterfactual input"}
    assert payload == original


def test_json_uuid_and_datetime_overrides_match_python_values(request_record):
    original = request_record.model_dump()
    python_result = simulate_counterfactual(
        request_record,
        {
            "allowed_merchant_ids": [request_record.recorded_merchant.id],
            "expires_at": request_record.recorded_passport.expires_at,
        },
    )
    app = FastAPI()
    app.include_router(router)
    with TestClient(app) as client:
        response = client.post(
            "/ghostpay/simulate",
            json={
                "request": request_record.model_dump(mode="json"),
                "overrides": {
                    "allowed_merchant_ids": [str(request_record.recorded_merchant.id)],
                    "expires_at": request_record.recorded_passport.expires_at.isoformat(),
                },
            },
            headers={"X-Tenant-Id": str(TENANT_ALPHA_ID)},
        )
    assert response.status_code == 200
    assert (
        response.json()["recomputed_outcome"]
        == python_result.recomputed_outcome
        == DecisionOutcome.ALLOW
    )
    assert response.json()["executed_payment"] is False
    assert request_record.model_dump() == original


@pytest.mark.parametrize("as_object", [False, True])
def test_merchant_overrides_preserve_isolation(request_record, as_object):
    original = request_record.model_dump()
    merchant = request_record.recorded_merchant
    value = merchant if as_object else {"id": str(merchant.id)}
    assert (
        simulate_counterfactual(
            request_record, {"merchant_override": value}
        ).executed_payment
        is False
    )
    with pytest.raises(TenantIsolationError):
        simulate_counterfactual(
            request_record, {"merchant_override": {"tenant_id": str(TENANT_BETA_ID)}}
        )
    assert request_record.model_dump() == original


def test_embedded_overrides_are_validated_and_explicit_values_win(request_record):
    request_record.counterfactual_overrides = {"amount_override_minor": -1}
    original = request_record.model_dump()
    with pytest.raises(ValidationError):
        simulate_counterfactual(request_record)
    result = simulate_counterfactual(request_record, {"amount_override_minor": 3900})
    assert result.recomputed_outcome == DecisionOutcome.ALLOW
    assert request_record.model_dump() == original


def test_unvalidated_nested_models_are_revalidated(request_record):
    request_record.proposal = request_record.proposal.model_copy(
        update={"amount_minor": -1}
    )
    original = request_record.model_dump()
    with pytest.raises(ValidationError):
        simulate_counterfactual(request_record)
    assert request_record.model_dump() == original


def test_merchant_id_substitution_does_not_inherit_global_trust(request_record):
    from uuid import uuid4

    request_record.recorded_merchant.is_allowlisted = True
    result = simulate_counterfactual(request_record, {"merchant_override": str(uuid4())})
    assert result.recomputed_outcome == DecisionOutcome.DENY
    assert request_record.recorded_merchant.is_allowlisted is True
