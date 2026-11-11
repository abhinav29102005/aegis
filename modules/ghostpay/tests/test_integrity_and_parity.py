"""Historical policy parity and transaction provenance regression cases."""

from datetime import timedelta
from uuid import uuid4

import pytest
from contracts import (
    ApprovalRecord,
    ApprovalStatus,
    PassportStatus,
    compute_payload_hash,
)
from contracts.fixtures import build_authorized_39_purchase_fixture
from ghostpay.counterfactual import simulate_counterfactual
from ghostpay.provenance.verifier import verify_evidence_digest
from ghostpay.replay import ReplayEngine
from ghostpay.replay.engine import evaluate_deterministic_policy
from guardian.policies.engine import PolicyEngine


@pytest.fixture
def record():
    return build_authorized_39_purchase_fixture()["replay_request"]


@pytest.mark.parametrize(
    "case",
    [
        "baseline",
        "expired_quote",
        "threshold_equal",
        "threshold_above",
        "paused",
        "currency",
        "budget",
        "category",
        "global_allowlist",
        "unknown_merchant",
        "expired_passport",
    ],
)
def test_guardian_policy_parity(record, case):
    r = record.model_copy(deep=True)
    t = r.recorded_decision.decided_at
    if case == "expired_quote":
        r.quote_snapshot.expires_at = t - timedelta(seconds=1)
    if case in ("threshold_equal", "threshold_above"):
        r.proposal.amount_minor = r.recorded_passport.human_approval_threshold_minor + (
            case == "threshold_above"
        )
    if case == "paused":
        r.recorded_passport.status = PassportStatus.PAUSED
    if case == "currency":
        r.recorded_passport.currency = "EUR"
    if case == "budget":
        r.recorded_passport.total_budget_minor = 100
    if case == "category":
        r.recorded_merchant.category = "OTHER"
    if case == "global_allowlist":
        r.recorded_passport.allowed_merchant_ids = []
        r.recorded_merchant.is_allowlisted = True
    if case == "unknown_merchant":
        r.recorded_passport.allowed_merchant_ids = []
        r.recorded_merchant.is_allowlisted = False
        r.recorded_passport.allow_unknown_merchants = True
    if case == "expired_passport":
        r.recorded_passport.expires_at = t - timedelta(seconds=1)
    args = {
        "proposal": r.proposal,
        "quote": r.quote_snapshot,
        "passport": r.recorded_passport,
        "merchant": r.recorded_merchant,
    }
    expected = PolicyEngine().evaluate(**args, now=t)
    actual = evaluate_deterministic_policy(**args, evaluation_time=t)
    assert actual == (
        expected.outcome,
        expected.reason_codes,
        expected.violated_constraints,
    )


@pytest.mark.parametrize("target", ["request", "passport", "decision"])
def test_unsupported_or_mismatched_versions_rejected(record, target):
    obj = {
        "request": record,
        "passport": record.recorded_passport,
        "decision": record.recorded_decision,
    }[target]
    obj.policy_version = "policy-v999"
    with pytest.raises(ValueError, match="policy version"):
        ReplayEngine.replay(record)


@pytest.mark.parametrize("field", ["payment_intent_id", "correlation_id"])
def test_foreign_evidence_cannot_satisfy_completeness(record, field):
    for evidence in record.evidence_records:
        setattr(evidence, field, uuid4())
    result = ReplayEngine.replay(record)
    assert result.consistency_status == "INTEGRITY_FAILURE"
    assert "QUOTE" in result.missing_evidence
    assert result.evidence_references == []
    assert all(not event.evidence_ids for event in result.timeline)


@pytest.mark.parametrize(
    "target,field",
    [
        ("recorded_decision", "payment_intent_id"),
        ("quote_snapshot", "proposal_id"),
        ("proposal", "passport_id"),
        ("recorded_passport", "agent_id"),
    ],
)
def test_record_identity_mismatch_is_integrity_failure(record, target, field):
    setattr(getattr(record, target), field, uuid4())
    assert ReplayEngine.replay(record).consistency_status == "INTEGRITY_FAILURE"


def test_empty_and_truncated_chains(record):
    empty = record.model_copy(update={"events": []})
    assert "FINANCIAL_EVENTS" in ReplayEngine.replay(empty).missing_evidence
    truncated = record.model_copy(update={"events": record.events[1:]})
    assert not ReplayEngine.replay(truncated).integrity_valid
    duplicate = record.model_copy(update={"events": [*record.events, record.events[0]]})
    assert not ReplayEngine.replay(duplicate).integrity_valid


def test_partial_digest_is_rejected(record):
    evidence = record.evidence_records[0]
    evidence.content_hash = compute_payload_hash(
        {
            "quote_hash": evidence.content["quote_hash"],
            "amount_minor": evidence.content["amount_minor"],
        }
    )
    assert verify_evidence_digest(evidence)[0] is False
    assert not ReplayEngine.replay(record).integrity_valid


def test_counterfactual_cannot_hide_source_corruption(record):
    record.evidence_records[0].payment_intent_id = uuid4()
    result = simulate_counterfactual(record, {"per_tx_limit_minor": 3000})
    assert result.consistency_status == "INTEGRITY_FAILURE"
    assert "QUOTE" in result.missing_evidence
    assert result.executed_payment is False


def test_approval_is_bound_but_does_not_rewrite_initial_decision(record):
    record.approval_record = ApprovalRecord(
        tenant_id=record.tenant_id,
        correlation_id=record.correlation_id,
        payment_intent_id=record.payment_intent.id,
        decision_id=record.recorded_decision.id,
        approver_id="test-reviewer",
        status=ApprovalStatus.APPROVED,
        bound_merchant_id=record.payment_intent.merchant_id,
        bound_amount_minor=3900,
        bound_currency="USD",
        bound_quote_hash=record.payment_intent.quote_hash,
        expires_at=record.recorded_passport.expires_at,
    )
    assert ReplayEngine.replay(record).integrity_valid
    record.approval_record.bound_currency = "EUR"
    assert not ReplayEngine.replay(record).integrity_valid


def test_evaluation_cannot_precede_historical_inputs(record):
    record.evaluation_time = record.proposal.created_at - timedelta(seconds=1)
    with pytest.raises(ValueError, match="predates"):
        ReplayEngine.replay(record)


def test_empty_capture_artifact_is_not_verified(record):
    evidence = record.evidence_records[-1]
    evidence.content = {}
    evidence.content_hash = compute_payload_hash({})
    assert not ReplayEngine.replay(record).integrity_valid
