"""Agent DNA Mandatory Tests (T14 - T20)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from contracts import DecisionOutcome
from contracts.fixtures import (
    AGENT_PROCUREMENT_ID,
    MERCHANT_SANDBOX_CLOUD_ID,
    MERCHANT_UNKNOWN_ID,
    TENANT_ALPHA_ID,
)
from ghostpay.agentdna.detector import AgentDNADetector
from ghostpay.agentdna.features import extract_agent_features
from ghostpay.agentdna.profiles import build_agent_profile
from ghostpay.domain.models import PaymentTrace
from ghostpay.testing import make_test_trace


def test_t14_stable_historical_behavior_produces_no_material_anomaly(
    agent_baseline_history: list[PaymentTrace],
) -> None:
    """T14: Stable historical behavior produces no material anomaly."""
    profile = build_agent_profile(TENANT_ALPHA_ID, AGENT_PROCUREMENT_ID, agent_baseline_history)
    detector = AgentDNADetector(min_samples=3)

    # Legitimate purchase conforming to baseline: $28.00 on approved merchant
    conforming_trace = make_test_trace(
        amount_minor=2800,
        merchant_id=MERCHANT_SANDBOX_CLOUD_ID,
        created_at=datetime.now(UTC),
    )
    result = detector.detect(profile, conforming_trace)

    assert result.is_anomaly is False
    assert result.status == "NORMAL"
    assert result.anomaly_score < 0.4
    assert len(result.signals) == 0


def test_t15_previously_unseen_merchant_produces_merchant_novelty_signal(
    agent_baseline_history: list[PaymentTrace],
) -> None:
    """T15: Previously unseen merchant produces a merchant-novelty signal."""
    profile = build_agent_profile(TENANT_ALPHA_ID, AGENT_PROCUREMENT_ID, agent_baseline_history)
    detector = AgentDNADetector(min_samples=3)

    # Target transaction on a completely unseen merchant
    novel_merchant_id = MERCHANT_UNKNOWN_ID
    target_trace = make_test_trace(
        amount_minor=2500,
        merchant_id=novel_merchant_id,
        created_at=datetime.now(UTC),
    )
    result = detector.detect(profile, target_trace)

    signal_types = [s["signal_type"] for s in result.signals]
    assert "MERCHANT_NOVELTY" in signal_types
    assert result.is_anomaly is True
    assert "Merchant novelty detected" in "\n".join(result.explanations)


def test_t16_abnormally_large_transaction_produces_amount_deviation_signal(
    agent_baseline_history: list[PaymentTrace],
) -> None:
    """T16: Abnormally large transaction produces an amount-deviation signal."""
    profile = build_agent_profile(TENANT_ALPHA_ID, AGENT_PROCUREMENT_ID, agent_baseline_history)
    detector = AgentDNADetector(min_samples=3)

    # Historical max is 3500 ($35.00). Target amount is $90.00 (9000 minor)
    target_trace = make_test_trace(
        amount_minor=9000,
        merchant_id=MERCHANT_SANDBOX_CLOUD_ID,
        created_at=datetime.now(UTC),
    )
    result = detector.detect(profile, target_trace)

    signal_types = [s["signal_type"] for s in result.signals]
    assert "AMOUNT_DEVIATION" in signal_types or "AMOUNT_STATISTICAL_OUTLIER" in signal_types
    assert result.is_anomaly is True


def test_t17_repeated_denied_attempts_produce_behavioral_warning() -> None:
    """T17: Repeated denied attempts produce a behavioral warning."""
    # Build history with high policy denial rate (> 50%)
    denied_history = [
        make_test_trace(amount_minor=2000, outcome=DecisionOutcome.DENY),
        make_test_trace(amount_minor=2200, outcome=DecisionOutcome.DENY),
        make_test_trace(amount_minor=2500, outcome=DecisionOutcome.DENY),
        make_test_trace(amount_minor=2100, outcome=DecisionOutcome.ALLOW),
    ]
    profile = build_agent_profile(TENANT_ALPHA_ID, AGENT_PROCUREMENT_ID, denied_history)
    detector = AgentDNADetector(min_samples=3)

    target_trace = make_test_trace(amount_minor=2300, outcome=DecisionOutcome.DENY)
    result = detector.detect(profile, target_trace)

    signal_types = [s["signal_type"] for s in result.signals]
    assert "REPEATED_POLICY_DENIALS" in signal_types


def test_t18_insufficient_historical_observations_return_insufficient_history() -> None:
    """T18: Insufficient historical observations return INSUFFICIENT_HISTORY."""
    # Only 1 historical trace
    short_history = [make_test_trace(amount_minor=2000)]
    profile = build_agent_profile(TENANT_ALPHA_ID, AGENT_PROCUREMENT_ID, short_history)
    detector = AgentDNADetector(min_samples=3)

    target_trace = make_test_trace(amount_minor=9999)
    result = detector.detect(profile, target_trace)

    assert result.status == "INSUFFICIENT_HISTORY"
    assert result.is_anomaly is False
    assert result.anomaly_score == 0.0


def test_t19_evaluated_transaction_is_excluded_from_own_baseline(
    agent_baseline_history: list[PaymentTrace],
) -> None:
    """T19: Evaluated transaction is excluded from its own historical baseline."""
    target_trace = make_test_trace(
        amount_minor=99999,
        created_at=datetime.now(UTC),
    )
    combined_history = agent_baseline_history + [target_trace]

    # When extracting features strictly prior to target_trace.created_at or excluding target_trace
    features = extract_agent_features(
        combined_history,
        cutoff_time=target_trace.created_at,
        exclude_trace_id=target_trace.trace_id,
    )

    # Historical max should still be 3500, not 99999
    assert features.max_amount_minor == 3500
    assert features.sample_count == len(agent_baseline_history)


def test_t20_agent_dna_results_never_change_guardian_decisions() -> None:
    """T20: Agent DNA results never change Guardian authorization decisions."""
    detector = AgentDNADetector()
    target_trace = make_test_trace(
        amount_minor=95000,
        outcome=DecisionOutcome.ALLOW,
    )
    profile = build_agent_profile(
        TENANT_ALPHA_ID,
        AGENT_PROCUREMENT_ID,
        [make_test_trace(amount_minor=2000), make_test_trace(amount_minor=2500), make_test_trace(amount_minor=3000)],
    )
    dna_result = detector.detect(profile, target_trace)

    # Even if an anomaly is detected
    assert dna_result.is_anomaly is True
    # The note must explicitly state Guardian authority remains unaffected
    assert "Guardian remains authoritative" in dna_result.authorization_note
    # The trace's recorded decision remains unchanged
    assert target_trace.recorded_decision.outcome == DecisionOutcome.ALLOW
