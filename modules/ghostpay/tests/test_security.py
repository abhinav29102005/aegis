"""Security, Tenant Isolation, and Adversarial Evaluation Tests for GhostPay."""

from __future__ import annotations

import pytest
from contracts import DecisionOutcome
from contracts.fixtures import (
    MERCHANT_UNKNOWN_ID,
    TENANT_ALPHA_ID,
    TENANT_BETA_ID,
    build_authorized_39_purchase_fixture,
)

from ghostpay.counterfactual import simulate_counterfactual
from ghostpay.domain.exceptions import CrossTenantAccessError
from ghostpay.domain.service import GhostPayService
from ghostpay.replay.engine import PolicyTimeMachine
from ghostpay.testing import make_test_trace
from ghostpay.timemachine.policies import CounterfactualPolicy


def test_tenant_isolation_on_investigations(service: GhostPayService) -> None:
    trace = make_test_trace(tenant_id=TENANT_ALPHA_ID)
    service.ingestion.traces[trace.trace_id] = trace
    service.agent_history[(TENANT_ALPHA_ID, trace.agent_id)] = [trace]

    inv = service.create_investigation(tenant_id=TENANT_ALPHA_ID, trace_id=trace.trace_id)

    # Cross-tenant access attempt by tenant beta
    with pytest.raises(CrossTenantAccessError):
        service.get_investigation(TENANT_BETA_ID, inv.investigation_id)


def test_zero_financial_side_effects_during_investigation(service: GhostPayService) -> None:
    fixture = build_authorized_39_purchase_fixture()
    trace = make_test_trace()
    trace = trace.model_copy(
        update={
            "proposal": fixture["proposal"].model_copy(
                update={
                    "tenant_id": trace.tenant_id,
                    "correlation_id": trace.payment_intent.correlation_id,
                    "agent_id": trace.agent_id,
                    "merchant_id": trace.quote_snapshot.merchant_id,
                    "amount_minor": trace.quote_snapshot.amount_minor,
                    "currency": trace.quote_snapshot.currency,
                }
            )
        }
    )
    service.ingestion.traces[trace.trace_id] = trace
    service.agent_history[(trace.tenant_id, trace.agent_id)] = [trace]

    initial_events_count = len(trace.ordered_events)

    inv = service.create_investigation(
        tenant_id=trace.tenant_id,
        trace_id=trace.trace_id,
        counterfactual_policies=[CounterfactualPolicy(name="Test Policy", per_tx_limit_minor=1000)],
    )

    # 1. No new financial events recorded on trace
    assert len(trace.ordered_events) == initial_events_count
    # 2. All counterfactual replays report executed_payment == False
    for r in inv.counterfactual_replay_results:
        assert r.executed_payment is False


def test_adversarial_evaluation_matrix() -> None:
    """Phase 11: Adversarial evaluation benchmark across 12 distinct attack and boundary vectors."""
    fixture = build_authorized_39_purchase_fixture()
    req = fixture["replay_request"]

    scenarios = [
        # (name, overrides, expected_outcome)
        ("1. Legitimate recurring purchase", {}, DecisionOutcome.ALLOW),
        ("2. Stricter per-tx limit", {"per_tx_limit_minor": 1500}, DecisionOutcome.DENY),
        ("3. Merchant substitution", {"merchant_override": MERCHANT_UNKNOWN_ID, "allow_unknown_merchants": False}, DecisionOutcome.DENY),
        ("4. Amount inflation", {"amount_override_minor": 85000}, DecisionOutcome.DENY),
        ("5. Escalation threshold exceeded", {"human_approval_threshold_minor": 2000}, DecisionOutcome.ESCALATE),
        ("6. Expired passport status", {"passport_status": "EXPIRED"}, DecisionOutcome.DENY),
        ("7. Revoked passport status", {"passport_status": "REVOKED"}, DecisionOutcome.DENY),
        ("8. Unknown merchant allowed with escalation", {"merchant_override": MERCHANT_UNKNOWN_ID, "allow_unknown_merchants": True}, DecisionOutcome.ESCALATE),
        ("9. Incompatible category", {"allowed_categories": ["HARDWARE"]}, DecisionOutcome.DENY),
        ("10. Daily limit exceeded", {"daily_limit_minor": 2500}, DecisionOutcome.DENY),
        ("11. Generous policy preserves allow", {"per_tx_limit_minor": 100000}, DecisionOutcome.ALLOW),
        ("12. Total budget exceeded", {"total_budget_minor": 1000}, DecisionOutcome.DENY),
    ]

    correct_evaluations = 0
    total_evaluations = len(scenarios)

    for _name, overrides, expected in scenarios:
        res = simulate_counterfactual(req, overrides)
        if res.recomputed_outcome == expected:
            correct_evaluations += 1

    # Measure correctness
    accuracy = correct_evaluations / total_evaluations
    assert accuracy == 1.0  # 12/12 (100% deterministic correctness)
