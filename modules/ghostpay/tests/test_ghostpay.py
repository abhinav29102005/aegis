"""Mandatory forensic and determinism test scenarios for GhostPay."""

from __future__ import annotations

import pytest
from contracts import (
    DecisionOutcome,
    DecisionReasonCode,
    PassportStatus,
    compute_quote_hash,
)
from contracts.fixtures import (
    TENANT_BETA_ID,
    build_authorized_39_purchase_fixture,
)
from security import TenantIsolationError

from ghostpay.counterfactual import simulate_counterfactual
from ghostpay.errors import OverrideValidationError
from ghostpay.replay import ReplayEngine


def test_1_identical_inputs_and_policy_version_produce_identical_results() -> None:
    """Scenario 1: Identical inputs and policy version produce identical results (CONSISTENT)."""
    fixture = build_authorized_39_purchase_fixture()
    req = fixture["replay_request"]

    res1 = ReplayEngine.replay(req)
    res2 = ReplayEngine.replay(req)

    assert res1.consistency_status == "CONSISTENT"
    assert res1.drift_detected is False
    assert res1.integrity_valid is True
    assert res1.original_outcome == DecisionOutcome.ALLOW
    assert res1.recomputed_outcome == DecisionOutcome.ALLOW
    assert res1.original_reason_codes == [DecisionReasonCode.OK_WITHIN_POLICY]
    assert res1.recomputed_reason_codes == [DecisionReasonCode.OK_WITHIN_POLICY]
    assert res1.missing_evidence == []
    assert res1.executed_payment is False

    # Determinism: identical outputs across runs (excluding generated UUID and timestamp)
    dump1 = res1.model_dump(exclude={"replay_id", "replayed_at"})
    dump2 = res2.model_dump(exclude={"replay_id", "replayed_at"})
    assert dump1 == dump2


def test_2_merchant_substitution_changes_authorization_outcome() -> None:
    """Scenario 2: Merchant substitution changes authorization outcome (DRIFT_DETECTED)."""
    fixture = build_authorized_39_purchase_fixture()
    req = fixture["replay_request"]
    unknown_merchant = fixture["unknown_merchant"]

    # Substitute recorded_merchant with an unapproved merchant
    sub_req = req.model_copy(update={"recorded_merchant": unknown_merchant})
    res = ReplayEngine.replay(sub_req)

    assert res.drift_detected is True
    assert res.consistency_status == "DRIFT_DETECTED"
    assert res.original_outcome == DecisionOutcome.ALLOW
    assert res.recomputed_outcome == DecisionOutcome.DENY
    assert DecisionReasonCode.DENIED_MERCHANT_NOT_ALLOWLISTED in res.recomputed_reason_codes
    assert any("MERCHANT_SUBSTITUTION" in a for a in res.anomalies)


def test_3_amount_increase_above_limit_changes_authorization_outcome() -> None:
    """Scenario 3: Amount increase above limit changes authorization outcome (DRIFT_DETECTED)."""
    fixture = build_authorized_39_purchase_fixture()
    req = fixture["replay_request"]

    # $85.00 exceeds $75.00 per-transaction limit
    new_amount = 8500
    new_proposal = req.proposal.model_copy(update={"amount_minor": new_amount})
    new_q_hash = compute_quote_hash(
        merchant_id=req.quote_snapshot.merchant_id,
        amount_minor=new_amount,
        currency=req.quote_snapshot.currency,
        line_items=req.quote_snapshot.line_items,
    )
    new_quote = req.quote_snapshot.model_copy(update={
        "amount_minor": new_amount,
        "quote_hash": new_q_hash,
    })

    high_req = req.model_copy(update={
        "proposal": new_proposal,
        "quote_snapshot": new_quote,
    })
    res = ReplayEngine.replay(high_req)

    assert res.drift_detected is True
    assert res.consistency_status == "DRIFT_DETECTED"
    assert res.original_outcome == DecisionOutcome.ALLOW
    assert res.recomputed_outcome == DecisionOutcome.DENY
    assert DecisionReasonCode.DENIED_EXCEEDS_PER_TX_LIMIT in res.recomputed_reason_codes
    assert any("AMOUNT_SPIKE" in a for a in res.anomalies)


def test_4_expired_passport_prevents_eligibility() -> None:
    """Scenario 4: Expired passport prevents eligibility (DENY, DENIED_PASSPORT_EXPIRED)."""
    fixture = build_authorized_39_purchase_fixture()
    req = fixture["replay_request"]

    expired_passport = req.recorded_passport.model_copy(update={"status": PassportStatus.EXPIRED})
    expired_req = req.model_copy(update={"recorded_passport": expired_passport})
    res = ReplayEngine.replay(expired_req)

    assert res.recomputed_outcome == DecisionOutcome.DENY
    assert DecisionReasonCode.DENIED_PASSPORT_EXPIRED in res.recomputed_reason_codes
    assert res.drift_detected is True
    assert res.consistency_status == "DRIFT_DETECTED"
    assert any("EXPIRED_PASSPORT" in a for a in res.anomalies)


def test_5_counterfactual_policies_do_not_mutate_original_records() -> None:
    """Scenario 5: Counterfactual policies do not mutate original records."""
    fixture = build_authorized_39_purchase_fixture()
    req = fixture["replay_request"]

    orig_tx_limit = req.recorded_passport.per_tx_limit_minor
    orig_total_budget = req.recorded_passport.total_budget_minor
    orig_passport_status = req.recorded_passport.status
    orig_amount = req.proposal.amount_minor
    orig_merchant_id = req.recorded_merchant.id

    overrides = {
        "per_tx_limit_minor": 1500,
        "amount_override_minor": 1200,
        "passport_status": PassportStatus.PAUSED,
        "allow_unknown_merchants": True,
    }

    res = simulate_counterfactual(req, overrides)

    # Invariant: Output must reflect simulation and never execute payment
    assert res.executed_payment is False

    # Invariant: Original records must remain completely unmutated
    assert req.recorded_passport.per_tx_limit_minor == orig_tx_limit
    assert req.recorded_passport.total_budget_minor == orig_total_budget
    assert req.recorded_passport.status == orig_passport_status
    assert req.proposal.amount_minor == orig_amount
    assert req.recorded_merchant.id == orig_merchant_id


def test_counterfactual_all_nine_supported_overrides_individually() -> None:
    """Verify all 9 individual counterfactual overrides function without mutation."""
    from datetime import timedelta

    fixture = build_authorized_39_purchase_fixture()
    req = fixture["replay_request"]
    unknown_merchant = fixture["unknown_merchant"]

    # 1. per_tx_limit_minor: reduce to $20.00, below $39.00 purchase -> DENIED_EXCEEDS_PER_TX_LIMIT
    res1 = simulate_counterfactual(req, {"per_tx_limit_minor": 2000})
    assert res1.recomputed_outcome == DecisionOutcome.DENY
    assert DecisionReasonCode.DENIED_EXCEEDS_PER_TX_LIMIT in res1.recomputed_reason_codes
    assert req.recorded_passport.per_tx_limit_minor == 7500  # unmutated

    # 2. total_budget_minor: reduce to $20.00, below $39.00 purchase -> DENIED_EXCEEDS_PASSPORT_BUDGET
    res2 = simulate_counterfactual(req, {"total_budget_minor": 2000})
    assert res2.recomputed_outcome == DecisionOutcome.DENY
    assert DecisionReasonCode.DENIED_EXCEEDS_PASSPORT_BUDGET in res2.recomputed_reason_codes

    # 3. allowed_merchant_ids: override to only allow unknown_merchant -> CloudCompute store is now DENIED
    res3 = simulate_counterfactual(req, {"allowed_merchant_ids": [unknown_merchant.id]})
    assert res3.recomputed_outcome == DecisionOutcome.DENY
    assert DecisionReasonCode.DENIED_MERCHANT_NOT_ALLOWLISTED in res3.recomputed_reason_codes

    # 4. allow_unknown_merchants + unapproved merchant in allowed category: escalates instead of denied
    unapproved_software_merchant = unknown_merchant.model_copy(update={"category": "SOFTWARE"})
    unapproved_req = req.model_copy(update={"recorded_merchant": unapproved_software_merchant})
    res4 = simulate_counterfactual(unapproved_req, {"allow_unknown_merchants": True})
    assert res4.recomputed_outcome == DecisionOutcome.ESCALATE
    assert DecisionReasonCode.ESCALATED_UNKNOWN_MERCHANT in res4.recomputed_reason_codes

    # 5. human_approval_threshold_minor: reduce threshold to $30.00 -> $39.00 purchase now requires approval
    res5 = simulate_counterfactual(req, {"human_approval_threshold_minor": 3000})
    assert res5.recomputed_outcome == DecisionOutcome.ESCALATE
    assert DecisionReasonCode.ESCALATED_REQUIRES_HUMAN_APPROVAL in res5.recomputed_reason_codes

    # 6. passport_status: set to REVOKED -> DENIED_PASSPORT_REVOKED
    res6 = simulate_counterfactual(req, {"passport_status": PassportStatus.REVOKED})
    assert res6.recomputed_outcome == DecisionOutcome.DENY
    assert DecisionReasonCode.DENIED_PASSPORT_REVOKED in res6.recomputed_reason_codes

    # 7. expires_at: set expiration in the past -> DENIED_PASSPORT_EXPIRED
    res7 = simulate_counterfactual(req, {"expires_at": req.quote_snapshot.created_at - timedelta(days=1)})
    assert res7.recomputed_outcome == DecisionOutcome.DENY
    assert DecisionReasonCode.DENIED_PASSPORT_EXPIRED in res7.recomputed_reason_codes

    # 8. merchant_override: substitute merchant via override -> DENIED_MERCHANT_NOT_ALLOWLISTED
    res8 = simulate_counterfactual(req, {"merchant_override": unknown_merchant})
    assert res8.recomputed_outcome == DecisionOutcome.DENY
    assert DecisionReasonCode.DENIED_MERCHANT_NOT_ALLOWLISTED in res8.recomputed_reason_codes

    # 9. amount_override_minor: increase amount to $85.00 -> DENIED_EXCEEDS_PER_TX_LIMIT
    res9 = simulate_counterfactual(req, {"amount_override_minor": 8500})
    assert res9.recomputed_outcome == DecisionOutcome.DENY
    assert DecisionReasonCode.DENIED_EXCEEDS_PER_TX_LIMIT in res9.recomputed_reason_codes

    # Baseline ReplayEngine.replay rejects nonempty counterfactual_overrides; simulation applies them
    direct_req = req.model_copy(update={"counterfactual_overrides": {"per_tx_limit_minor": 1000}})
    with pytest.raises(OverrideValidationError):
        ReplayEngine.replay(direct_req)

    res_direct = simulate_counterfactual(direct_req)
    assert res_direct.recomputed_outcome == DecisionOutcome.DENY
    assert DecisionReasonCode.DENIED_EXCEEDS_PER_TX_LIMIT in res_direct.recomputed_reason_codes
    assert res_direct.executed_payment is False


def test_6_missing_evidence_is_explicitly_reported() -> None:
    """Scenario 6: Missing evidence is explicitly reported (missing_evidence populated, INCOMPLETE_EVIDENCE)."""
    fixture = build_authorized_39_purchase_fixture()
    req = fixture["replay_request"]

    # Remove PAYPAL_CAPTURE evidence while payment intent state is SUCCEEDED
    only_quote_evidence = [e for e in req.evidence_records if e.source_type != "PAYPAL_CAPTURE"]
    req_no_capture = req.model_copy(update={"evidence_records": only_quote_evidence})

    res = ReplayEngine.replay(req_no_capture)

    assert "PAYPAL_CAPTURE" in res.missing_evidence
    assert res.consistency_status == "INCOMPLETE_EVIDENCE"

    # Remove all evidence records
    req_empty_evidence = req.model_copy(update={"evidence_records": []})
    res_empty = ReplayEngine.replay(req_empty_evidence)

    assert "QUOTE" in res_empty.missing_evidence
    assert "PAYPAL_CAPTURE" in res_empty.missing_evidence
    assert res_empty.consistency_status == "INCOMPLETE_EVIDENCE"


def test_7_event_ordering_is_deterministic_even_when_input_events_are_shuffled() -> None:
    """Scenario 7: Event ordering is deterministic even when input events are shuffled."""
    fixture = build_authorized_39_purchase_fixture()
    req = fixture["replay_request"]
    original_events = list(req.events)

    shuffled = list(original_events)
    # Reverse order
    shuffled.reverse()
    assert [e.sequence_number for e in shuffled] != [e.sequence_number for e in original_events]

    req_shuffled = req.model_copy(update={"events": shuffled})
    res_shuffled = ReplayEngine.replay(req_shuffled)
    res_normal = ReplayEngine.replay(req)

    # Sequence numbers must be strictly ordered 1, 2, 3, 4
    seq_nums = [entry.sequence_number for entry in res_shuffled.timeline]
    assert seq_nums == [1, 2, 3, 4]
    assert [t.event_id for t in res_shuffled.timeline] == [t.event_id for t in res_normal.timeline]


def test_8_cross_tenant_evidence_access_is_denied() -> None:
    """Scenario 8: Cross-tenant evidence/record access is denied (TenantIsolationError)."""
    fixture = build_authorized_39_purchase_fixture()
    req = fixture["replay_request"]

    # Mismatched evidence tenant
    foreign_ev = req.evidence_records[0].model_copy(update={"tenant_id": TENANT_BETA_ID})
    req_bad_ev = req.model_copy(update={"evidence_records": [foreign_ev, req.evidence_records[1]]})
    with pytest.raises(TenantIsolationError):
        ReplayEngine.replay(req_bad_ev)

    # Mismatched event tenant
    foreign_event = req.events[0].model_copy(update={"tenant_id": TENANT_BETA_ID})
    req_bad_event = req.model_copy(update={"events": [foreign_event, *req.events[1:]]})
    with pytest.raises(TenantIsolationError):
        ReplayEngine.replay(req_bad_event)

    # Mismatched passport tenant
    foreign_passport = req.recorded_passport.model_copy(update={"tenant_id": TENANT_BETA_ID})
    req_bad_passport = req.model_copy(update={"recorded_passport": foreign_passport})
    with pytest.raises(TenantIsolationError):
        ReplayEngine.replay(req_bad_passport)


def test_9_tampered_records_fail_integrity_checks() -> None:
    """Scenario 9: Tampered event or evidence records fail integrity checks (integrity_valid=False, INTEGRITY_FAILURE)."""
    fixture = build_authorized_39_purchase_fixture()
    req = fixture["replay_request"]

    # 1. Tamper with event payload without updating event_hash
    tampered_event = req.events[1].model_copy(update={"payload": {"tampered_outcome": "FORGED"}})
    req_tampered_event = req.model_copy(update={"events": [req.events[0], tampered_event, *req.events[2:]]})
    res_event = ReplayEngine.replay(req_tampered_event)

    assert res_event.integrity_valid is False
    assert res_event.consistency_status == "INTEGRITY_FAILURE"
    assert any("INTEGRITY_VIOLATION" in a for a in res_event.anomalies)

    # 2. Tamper with evidence digest
    tampered_evidence = req.evidence_records[0].model_copy(update={"content_hash": "0123456789abcdef" * 4})
    req_tampered_ev = req.model_copy(update={"evidence_records": [tampered_evidence, req.evidence_records[1]]})
    res_ev = ReplayEngine.replay(req_tampered_ev)

    assert res_ev.integrity_valid is False
    assert res_ev.consistency_status == "INTEGRITY_FAILURE"

    # 3. Tamper with quote snapshot hash
    tampered_quote = req.quote_snapshot.model_copy(update={"quote_hash": "deadbeefcafebabe" * 4})
    req_tampered_quote = req.model_copy(update={"quote_snapshot": tampered_quote})
    res_quote = ReplayEngine.replay(req_tampered_quote)

    assert res_quote.integrity_valid is False
    assert res_quote.consistency_status == "INTEGRITY_FAILURE"


def test_10_replay_does_not_trigger_payment_execution() -> None:
    """Scenario 10: Replay does not trigger payment execution (executed_payment=False)."""
    fixture = build_authorized_39_purchase_fixture()
    req = fixture["replay_request"]

    res = ReplayEngine.replay(req)
    assert res.executed_payment is False

    sim_res = simulate_counterfactual(req, {"amount_override_minor": 2500})
    assert sim_res.executed_payment is False
