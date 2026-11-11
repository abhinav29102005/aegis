"""Policy Time Machine Mandatory Tests (T07 - T13)."""

from __future__ import annotations

import pytest
from contracts import (
    DecisionOutcome,
    DecisionReasonCode,
    ReplayRequest,
)
from contracts.fixtures import (
    MERCHANT_UNKNOWN_ID,
)

from ghostpay.domain.exceptions import IllegalSideEffectError
from ghostpay.testing import make_test_trace
from ghostpay.timemachine.comparison import compare_policies
from ghostpay.timemachine.policies import CounterfactualPolicy
from ghostpay.timemachine.replay import PolicyTimeMachine


def test_t07_original_allowed_purchase_becomes_denied_under_stricter_limit(
    authorized_39_fixture: dict,
) -> None:
    """T07: Original allowed purchase becomes denied under a stricter transaction limit."""
    req: ReplayRequest = authorized_39_fixture["replay_request"]
    assert req.recorded_decision.outcome == DecisionOutcome.ALLOW

    # Stricter per-transaction limit: $20.00 (2000 minor) against a $39.00 purchase
    stricter_req = req.model_copy(
        update={"counterfactual_overrides": {"per_tx_limit_minor": 2000}}
    )
    result = PolicyTimeMachine.replay(stricter_req)

    assert result.original_outcome == DecisionOutcome.ALLOW
    assert result.recomputed_outcome == DecisionOutcome.DENY
    assert DecisionReasonCode.DENIED_EXCEEDS_PER_TX_LIMIT in result.recomputed_reason_codes
    assert result.drift_detected is True
    assert result.executed_payment is False


def test_t08_merchant_substitution_is_rejected_under_alternative_allowlist(
    authorized_39_fixture: dict,
) -> None:
    """T08: Merchant substitution is rejected under an alternative allowlist."""
    req: ReplayRequest = authorized_39_fixture["replay_request"]

    # Substitute merchant with an unknown / unapproved merchant
    sub_req = req.model_copy(
        update={
            "counterfactual_overrides": {
                "merchant_override": MERCHANT_UNKNOWN_ID,
                "allow_unknown_merchants": False,
            }
        }
    )
    result = PolicyTimeMachine.replay(sub_req)

    assert result.recomputed_outcome == DecisionOutcome.DENY
    assert DecisionReasonCode.DENIED_MERCHANT_NOT_ALLOWLISTED in result.recomputed_reason_codes
    assert result.drift_detected is True


def test_t09_approval_threshold_change_produces_expected_escalation(
    authorized_39_fixture: dict,
) -> None:
    """T09: Approval threshold change produces the expected escalation."""
    req: ReplayRequest = authorized_39_fixture["replay_request"]

    # Lower human approval threshold from $50.00 (5000 minor) to $25.00 (2500 minor)
    # The $39.00 purchase now requires human approval!
    escalate_req = req.model_copy(
        update={"counterfactual_overrides": {"human_approval_threshold_minor": 2500}}
    )
    result = PolicyTimeMachine.replay(escalate_req)

    assert result.recomputed_outcome == DecisionOutcome.ESCALATE
    assert DecisionReasonCode.ESCALATED_REQUIRES_HUMAN_APPROVAL in result.recomputed_reason_codes
    assert result.drift_detected is True


def test_t10_missing_historical_budget_state_returns_insufficient_evidence() -> None:
    """T10: Missing historical budget state returns INSUFFICIENT_EVIDENCE."""
    # Build trace missing passport and decision
    trace = make_test_trace()
    trace_missing = trace.model_copy(
        update={"recorded_passport": None, "recorded_decision": None}
    )

    result = PolicyTimeMachine.replay_trace(trace_missing)
    assert result.consistency_status == "INCOMPLETE_EVIDENCE"
    assert "INSUFFICIENT_EVIDENCE" in result.missing_evidence
    assert result.executed_payment is False


def test_t11_replaying_same_trace_and_policy_produces_identical_results(
    authorized_39_fixture: dict,
) -> None:
    """T11: Replaying the same trace and policy produces identical results and digests."""
    req: ReplayRequest = authorized_39_fixture["replay_request"]

    res1 = PolicyTimeMachine.replay(req)
    res2 = PolicyTimeMachine.replay(req)

    assert res1.recomputed_outcome == res2.recomputed_outcome
    assert res1.recomputed_reason_codes == res2.recomputed_reason_codes
    assert res1.changed_constraints == res2.changed_constraints
    assert res1.consistency_status == res2.consistency_status
    assert res1.executed_payment is False
    assert res2.executed_payment is False


def test_t12_replay_cannot_invoke_paypal_reserve_or_mutate_state() -> None:
    """T12: Replay cannot invoke PayPal, reserve budgets, capture funds, or mutate ledger state."""
    # Attempting to call side-effect methods on replay engine raises IllegalSideEffectError
    with pytest.raises((IllegalSideEffectError, PermissionError)):
        PolicyTimeMachine.capture_payment()

    with pytest.raises((IllegalSideEffectError, PermissionError)):
        PolicyTimeMachine.reserve_budget()

    with pytest.raises((IllegalSideEffectError, PermissionError)):
        PolicyTimeMachine.release_reservation()


def test_t13_multiple_policy_comparisons_produce_independent_results(
    authorized_39_fixture: dict,
) -> None:
    """T13: Multiple policy comparisons produce independent, reproducible results."""
    req: ReplayRequest = authorized_39_fixture["replay_request"]

    p1 = CounterfactualPolicy(name="Policy A - Stricter Limit", per_tx_limit_minor=2000)
    p2 = CounterfactualPolicy(name="Policy B - Lower Approval Threshold", human_approval_threshold_minor=2500)
    p3 = CounterfactualPolicy(name="Policy C - Generous Limit", per_tx_limit_minor=50000)

    report = compare_policies(req, [p1, p2, p3])
    assert len(report.results) == 3

    assert report.results[0].outcome == DecisionOutcome.DENY
    assert report.results[0].outcome_changed is True

    assert report.results[1].outcome == DecisionOutcome.ESCALATE
    assert report.results[1].outcome_changed is True

    assert report.results[2].outcome == DecisionOutcome.ALLOW
    assert report.results[2].outcome_changed is False
