"""Tests for GhostPay FastAPI router surface without socket-binding hangs."""

from __future__ import annotations

import pytest
from contracts import DecisionOutcome
from contracts.fixtures import (
    AGENT_PROCUREMENT_ID,
    TENANT_ALPHA_ID,
    TENANT_BETA_ID,
    build_authorized_39_purchase_fixture,
)
from fastapi import HTTPException

from ghostpay.api.models import (
    AnalyzeAgentRequest,
    CreateInvestigationRequest,
    IngestTraceRequest,
    ReplayCompareRequest,
)
from ghostpay.api.router import (
    SimulateRequest,
    TimelineRequest,
    create_ghostpay_router,
)
from ghostpay.domain.service import GhostPayService


@pytest.fixture
def api_service() -> GhostPayService:
    return GhostPayService()


@pytest.fixture
def endpoints(api_service: GhostPayService) -> dict:
    router = create_ghostpay_router(api_service)
    return {r.name: r.endpoint for r in router.routes}


def test_api_health_check(endpoints: dict) -> None:
    data = endpoints["health_check"]()
    assert data["status"] == "ok"
    assert data["service"] == "ghostpay"


def test_api_replay_success(endpoints: dict) -> None:
    fixture = build_authorized_39_purchase_fixture()
    req = fixture["replay_request"]

    res = endpoints["replay_transaction"](req, TENANT_ALPHA_ID)
    assert res.consistency_status == "CONSISTENT"
    assert res.original_outcome == DecisionOutcome.ALLOW
    assert res.recomputed_outcome == DecisionOutcome.ALLOW
    assert res.executed_payment is False
    assert len(res.timeline) == 4


def test_api_replay_cross_tenant_forbidden(endpoints: dict) -> None:
    fixture = build_authorized_39_purchase_fixture()
    req = fixture["replay_request"]

    with pytest.raises(HTTPException) as exc_info:
        endpoints["replay_transaction"](req, TENANT_BETA_ID)
    assert exc_info.value.status_code == 403
    assert "Cross-tenant access denied" in exc_info.value.detail


def test_api_simulate_counterfactual(endpoints: dict) -> None:
    fixture = build_authorized_39_purchase_fixture()
    req = fixture["replay_request"]

    payload = SimulateRequest(
        request=req,
        overrides={"per_tx_limit_minor": 1000},
    )

    data = endpoints["simulate_policy"](payload, TENANT_ALPHA_ID)
    assert data.recomputed_outcome == DecisionOutcome.DENY
    assert data.drift_detected is True
    assert data.executed_payment is False


def test_api_reconstruct_timeline(endpoints: dict) -> None:
    fixture = build_authorized_39_purchase_fixture()
    req = fixture["replay_request"]

    payload = TimelineRequest(
        events=req.events,
        evidence_records=req.evidence_records,
    )

    entries = endpoints["reconstruct_timeline"](payload, TENANT_ALPHA_ID)
    assert len(entries) == 4
    assert [e.sequence_number for e in entries] == [1, 2, 3, 4]


def test_api_ingest_and_get_trace(endpoints: dict) -> None:
    fixture = build_authorized_39_purchase_fixture()
    req = fixture["replay_request"]

    ingest_req = IngestTraceRequest(
        tenant_id=TENANT_ALPHA_ID,
        agent_id=AGENT_PROCUREMENT_ID,
        payment_intent_id=req.payment_intent.id,
        events=req.events,
        quote_snapshot=req.quote_snapshot,
        evidence_records=req.evidence_records,
        recorded_decision=req.recorded_decision,
        recorded_passport=req.recorded_passport,
        recorded_merchant=req.recorded_merchant,
        approval_record=req.approval_record,
        payment_intent=req.payment_intent,
    )

    trace = endpoints["ingest_trace"](ingest_req, TENANT_ALPHA_ID)
    assert trace.trace_id is not None
    assert trace.tenant_id == TENANT_ALPHA_ID

    fetched = endpoints["get_trace"](trace.trace_id, TENANT_ALPHA_ID)
    assert fetched.trace_id == trace.trace_id

    timeline = endpoints["get_trace_timeline"](trace.trace_id, TENANT_ALPHA_ID)
    assert len(timeline) == 4


def test_api_compare_policies(endpoints: dict) -> None:
    fixture = build_authorized_39_purchase_fixture()
    req = fixture["replay_request"]

    from ghostpay.timemachine.policies import CounterfactualPolicy

    compare_req = ReplayCompareRequest(
        replay_request=req,
        policies=[CounterfactualPolicy(name="strict-policy", per_tx_limit_minor=1000)],
    )

    report = endpoints["compare_policies_endpoint"](compare_req, TENANT_ALPHA_ID)
    assert len(report.results) == 1
    assert report.results[0].outcome_changed is True
    assert report.results[0].outcome == DecisionOutcome.DENY


def test_api_agent_dna_and_investigation(endpoints: dict) -> None:
    fixture = build_authorized_39_purchase_fixture()
    req = fixture["replay_request"]

    ingest_req = IngestTraceRequest(
        tenant_id=TENANT_ALPHA_ID,
        agent_id=AGENT_PROCUREMENT_ID,
        payment_intent_id=req.payment_intent.id,
        events=req.events,
        quote_snapshot=req.quote_snapshot,
        evidence_records=req.evidence_records,
        recorded_decision=req.recorded_decision,
        recorded_passport=req.recorded_passport,
        recorded_merchant=req.recorded_merchant,
        approval_record=req.approval_record,
        payment_intent=req.payment_intent,
    )
    trace = endpoints["ingest_trace"](ingest_req, TENANT_ALPHA_ID)

    # Analyze agent
    analyze_req = AnalyzeAgentRequest(target_trace_id=trace.trace_id)
    analysis = endpoints["analyze_agent_dna"](AGENT_PROCUREMENT_ID, analyze_req, TENANT_ALPHA_ID)
    assert analysis.agent_id == AGENT_PROCUREMENT_ID
    assert analysis.status == "INSUFFICIENT_HISTORY"

    # Investigation
    inv_req = CreateInvestigationRequest(
        trace_id=trace.trace_id,
    )
    inv = endpoints["create_investigation"](inv_req, TENANT_ALPHA_ID)
    assert inv.investigation_id is not None
    assert inv.tenant_id == TENANT_ALPHA_ID
    assert inv.payment_intent_id == req.payment_intent.id

    fetched_inv = endpoints["get_investigation"](inv.investigation_id, TENANT_ALPHA_ID)
    assert fetched_inv.investigation_id == inv.investigation_id

    # DisputeOS Bundle
    bundle = endpoints["get_investigation_evidence_bundle"](inv.investigation_id, TENANT_ALPHA_ID)
    assert bundle.payment_intent_id == req.payment_intent.id
    assert bundle.tenant_id == TENANT_ALPHA_ID

