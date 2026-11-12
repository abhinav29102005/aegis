"""Comprehensive unit tests for GhostPay forensics & provenance hardening (GAP-011, GAP-013, GAP-026)."""

from __future__ import annotations

import importlib
from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest
from contracts import (
    AgentIdentity,
    BudgetReservation,
    DecisionOutcome,
    DecisionReasonCode,
    EvidenceRecord,
    EvidenceSourceType,
    PassportStatus,
    PaymentAttempt,
    PaymentState,
    ReplayRequest,
    ReservationStatus,
    VerifiedPayPalCapture,
    compute_payload_hash,
    compute_quote_hash,
)
from contracts.fixtures import (
    TENANT_ALPHA_ID,
    TENANT_BETA_ID,
    build_authorized_39_purchase_fixture,
)
from contracts.policy_v1 import evaluate_policy_v1
from security import TenantIsolationError

from ghostpay.agentdna.features import extract_agent_features
from ghostpay.agentdna.profiles import build_agent_profile
from ghostpay.anomalies import detect_anomalies
from ghostpay.domain.exceptions import CrossTenantAccessError, InsufficientEvidenceError
from ghostpay.domain.service import GhostPayService
from ghostpay.forensics import (
    build_timeline as compat_build_timeline,
)
from ghostpay.forensics import (
    detect_anomalies as compat_detect_anomalies,
)
from ghostpay.forensics import (
    verify_evidence_digest as compat_verify_evidence_digest,
)
from ghostpay.ingestion.adapter import TraceIngestionAdapter
from ghostpay.ingestion.validation import TraceValidator
from ghostpay.provenance import (
    verify_evidence_digest,
    verify_execution_artifacts_consistency,
    verify_provenance_and_integrity,
)
from ghostpay.replay import ReplayEngine
from ghostpay.testing import make_test_trace
from ghostpay.timelines import build_timeline
from ghostpay.timemachine import CounterfactualPolicy, PolicyTimeMachine
from ghostpay.timemachine.recommendations import generate_safeguard_recommendations


def _canonical_fixture() -> dict:
    fixture = build_authorized_39_purchase_fixture()
    canonical_evidence = [
        rec.model_copy(update={"content_hash": compute_payload_hash(rec.content)})
        for rec in fixture["evidence_records"]
    ]
    fixture["evidence_records"] = canonical_evidence
    fixture["replay_request"] = fixture["replay_request"].model_copy(
        update={"evidence_records": canonical_evidence}
    )
    return fixture


# ---------------------------------------------------------------------------
# 1. Retired Duplicate Modules & Unified Compatibility Exports
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "legacy_module",
    [
        "ghostpay.timemachine.replay",
        "ghostpay.forensics.provenance",
        "ghostpay.forensics.timeline",
        "ghostpay.forensics.anomalies",
    ],
)
def test_retired_duplicate_modules_do_not_exist(legacy_module: str) -> None:
    with pytest.raises(ModuleNotFoundError):
        importlib.import_module(legacy_module)


def test_compatibility_exports_route_to_hardened_implementations() -> None:
    assert PolicyTimeMachine is ReplayEngine
    assert compat_detect_anomalies is detect_anomalies
    assert compat_verify_evidence_digest is verify_evidence_digest
    assert compat_build_timeline is build_timeline


# ---------------------------------------------------------------------------
# 2. Policy-v1 Parity with contracts.policy_v1.evaluate_policy_v1
# ---------------------------------------------------------------------------


def test_policy_v1_threshold_boundary_strict_gt_parity() -> None:
    """Threshold uses strict '>' (amount == threshold -> ALLOW; amount == threshold + 1 -> ESCALATE)."""
    fixture = _canonical_fixture()
    req: ReplayRequest = fixture["replay_request"]

    # Equal to threshold (3900 == 3900) -> ALLOW
    eq_passport = req.recorded_passport.model_copy(update={"human_approval_threshold_minor": 3900})
    eq_req = req.model_copy(update={"recorded_passport": eq_passport})
    eq_res = ReplayEngine.replay(eq_req)
    eq_canonical = evaluate_policy_v1(
        passport=eq_passport,
        proposal=req.proposal,
        quote=req.quote_snapshot,
        merchant=req.recorded_merchant,
        agent=None,
        now=req.evaluation_time,
    )
    assert eq_res.recomputed_outcome == eq_canonical.outcome == DecisionOutcome.ALLOW
    assert eq_res.recomputed_reason_codes == eq_canonical.reason_codes

    # One minor unit above threshold (3900 > 3899) -> ESCALATE
    gt_passport = req.recorded_passport.model_copy(update={"human_approval_threshold_minor": 3899})
    gt_req = req.model_copy(update={"recorded_passport": gt_passport})
    gt_res = ReplayEngine.replay(gt_req)
    gt_canonical = evaluate_policy_v1(
        passport=gt_passport,
        proposal=req.proposal,
        quote=req.quote_snapshot,
        merchant=req.recorded_merchant,
        agent=None,
        now=req.evaluation_time,
    )
    assert gt_res.recomputed_outcome == gt_canonical.outcome == DecisionOutcome.ESCALATE
    assert gt_res.recomputed_reason_codes == gt_canonical.reason_codes
    assert DecisionReasonCode.ESCALATED_REQUIRES_HUMAN_APPROVAL in gt_res.recomputed_reason_codes


def test_policy_v1_enforces_agent_status_currency_and_quote_expiry() -> None:
    fixture = _canonical_fixture()
    req: ReplayRequest = fixture["replay_request"]

    # A. Suspended agent identity -> DENY even if passport is ACTIVE
    suspended_agent = AgentIdentity(
        id=req.recorded_passport.agent_id,
        tenant_id=req.tenant_id,
        name="Suspended Agent",
        status="SUSPENDED",
        public_fingerprint="fp-suspended-1234",
    )
    res_agent = ReplayEngine.replay(req, agent=suspended_agent)
    assert res_agent.recomputed_outcome == DecisionOutcome.DENY
    assert DecisionReasonCode.DENIED_AGENT_SUSPENDED in res_agent.recomputed_reason_codes

    # B. Currency not in allowed_currencies -> DENY
    eur_proposal = req.proposal.model_copy(update={"currency": "EUR"})
    eur_quote_hash = compute_quote_hash(
        merchant_id=req.quote_snapshot.merchant_id,
        amount_minor=req.quote_snapshot.amount_minor,
        currency="EUR",
        line_items=req.quote_snapshot.line_items,
    )
    eur_quote = req.quote_snapshot.model_copy(update={"currency": "EUR", "quote_hash": eur_quote_hash})
    res_currency = ReplayEngine.replay(
        req.model_copy(update={"proposal": eur_proposal, "quote_snapshot": eur_quote})
    )
    assert res_currency.recomputed_outcome == DecisionOutcome.DENY
    assert DecisionReasonCode.DENIED_CURRENCY_NOT_ALLOWED in res_currency.recomputed_reason_codes

    # Also verify CounterfactualPolicy emits currency_override cleanly
    pol_overrides = CounterfactualPolicy(name="EUR Policy", currency="eur").to_overrides_dict()
    assert pol_overrides == {"currency_override": "EUR"}

    # C. Quote expired at exact boundary (<=) -> DENY
    res_quote_exp = ReplayEngine.replay(
        req.model_copy(update={"evaluation_time": req.quote_snapshot.expires_at})
    )
    assert res_quote_exp.recomputed_outcome == DecisionOutcome.DENY
    assert DecisionReasonCode.DENIED_QUOTE_EXPIRED in res_quote_exp.recomputed_reason_codes


# ---------------------------------------------------------------------------
# 3. Provenance Verifier Hardening (GAP-013)
# ---------------------------------------------------------------------------


def test_partial_2field_evidence_digests_are_rejected() -> None:
    """Legacy 2-field partial hashes for QUOTE / PAYPAL_CAPTURE / CARRIER_TRACKING / CUSTOMER_MESSAGE fail closed."""
    fixture = _canonical_fixture()
    raw_fixture = build_authorized_39_purchase_fixture()

    # Raw fixture has legacy 2-field partial digests on QUOTE and PAYPAL_CAPTURE
    for rec in raw_fixture["evidence_records"]:
        valid, err = verify_evidence_digest(rec)
        assert valid is False
        assert err is not None and "does not match canonical payload hash" in err

    # Also check CARRIER_TRACKING and CUSTOMER_MESSAGE 2-field partial digests fail closed
    tracking_rec = EvidenceRecord(
        tenant_id=TENANT_ALPHA_ID,
        correlation_id=raw_fixture["payment_intent"].correlation_id,
        payment_intent_id=raw_fixture["payment_intent"].id,
        source_type=EvidenceSourceType.CARRIER_TRACKING,
        source_ref="track-1Z999",
        title="Carrier Tracking",
        content={"tracking_number": "1Z999", "status": "DELIVERED", "extra": "tampered"},
        content_hash=compute_payload_hash({"tracking_number": "1Z999", "status": "DELIVERED"}),
    )
    msg_rec = EvidenceRecord(
        tenant_id=TENANT_ALPHA_ID,
        correlation_id=raw_fixture["payment_intent"].correlation_id,
        payment_intent_id=raw_fixture["payment_intent"].id,
        source_type=EvidenceSourceType.CUSTOMER_MESSAGE,
        source_ref="msg-1",
        title="Customer Message",
        content={"message_id": "msg-1", "body": "Refund me", "extra": "tampered"},
        content_hash=compute_payload_hash({"message_id": "msg-1", "body": "Refund me"}),
    )
    assert verify_evidence_digest(tracking_rec)[0] is False
    assert verify_evidence_digest(msg_rec)[0] is False

    # Replay with raw partial-hash records must fail integrity
    bad_req = fixture["replay_request"].model_copy(
        update={"evidence_records": raw_fixture["evidence_records"]}
    )
    res = ReplayEngine.replay(bad_req)
    assert res.integrity_valid is False
    assert res.consistency_status == "INTEGRITY_FAILURE"


def test_evidence_metadata_envelope_digest_is_accepted_and_tampered_metadata_rejected() -> None:
    content = {"quote_hash": "abc", "amount_minor": 3900}
    rec = EvidenceRecord(
        tenant_id=TENANT_ALPHA_ID,
        correlation_id=uuid4(),
        payment_intent_id=uuid4(),
        source_type=EvidenceSourceType.QUOTE,
        source_ref="quote-ref-1",
        title="Merchant Quote",
        content=content,
        content_hash=compute_payload_hash({
            "source_type": EvidenceSourceType.QUOTE.value,
            "source_ref": "quote-ref-1",
            "title": "Merchant Quote",
            "content": content,
        }),
    )
    assert verify_evidence_digest(rec) == (True, None)

    tampered_title = rec.model_copy(update={"title": "Forged Quote"})
    assert verify_evidence_digest(tampered_title)[0] is False

    # Full-context envelope hash is also accepted and rejects tampered correlation_id
    full_hash = compute_payload_hash({
        "tenant_id": str(rec.tenant_id),
        "correlation_id": str(rec.correlation_id),
        "payment_intent_id": str(rec.payment_intent_id),
        "dispute_case_id": None,
        "source_type": rec.source_type.value,
        "source_ref": rec.source_ref,
        "title": rec.title,
        "content": rec.content,
        "is_synthetic": rec.is_synthetic,
        "collected_at": rec.collected_at.isoformat(),
    })
    full_rec = rec.model_copy(update={"content_hash": full_hash})
    assert verify_evidence_digest(full_rec) == (True, None)
    assert verify_evidence_digest(full_rec.model_copy(update={"correlation_id": uuid4()}))[0] is False


def test_correlation_id_binding_enforced_across_evidence_and_entities() -> None:
    fixture = _canonical_fixture()
    req: ReplayRequest = fixture["replay_request"]
    foreign_corr = UUID("99999999-9999-4000-8000-000000000099")

    # 1. Foreign correlation_id on EvidenceRecord
    bad_ev = req.evidence_records[0].model_copy(update={"correlation_id": foreign_corr})
    ok, _missing, errors = verify_provenance_and_integrity(
        req.model_copy(update={"evidence_records": [bad_ev, *req.evidence_records[1:]]})
    )
    assert ok is False
    assert any("Correlation mismatch on EvidenceRecord" in err for err in errors)

    # 2. Foreign correlation_id on QuoteSnapshot
    bad_quote = req.quote_snapshot.model_copy(update={"correlation_id": foreign_corr})
    ok_q, _missing_q, errors_q = verify_provenance_and_integrity(
        req.model_copy(update={"quote_snapshot": bad_quote})
    )
    assert ok_q is False
    assert any("Correlation mismatch on QuoteSnapshot" in err for err in errors_q)


def test_execution_artifacts_cross_check_attempt_capture_and_reservation() -> None:
    fixture = _canonical_fixture()
    req: ReplayRequest = fixture["replay_request"]
    intent = req.payment_intent
    cap_ev = next(e for e in req.evidence_records if e.source_type == EvidenceSourceType.PAYPAL_CAPTURE)
    order_id = cap_ev.content["paypal_order_id"]
    capture_id = cap_ev.content["capture_id"]

    capture = VerifiedPayPalCapture(
        paypal_order_id=order_id,
        paypal_capture_id=capture_id,
        paypal_status="COMPLETED",
        verified_amount_minor=intent.amount_minor,
        verified_currency=intent.currency,
        verification_hash="v" * 32,
    )
    attempt = PaymentAttempt(
        id=intent.active_attempt_id,
        tenant_id=intent.tenant_id,
        correlation_id=intent.correlation_id,
        payment_intent_id=intent.id,
        idempotency_key="idem-key-3900",
        paypal_order_id=order_id,
        verified_capture=capture,
        state=PaymentState.SUCCEEDED,
    )
    reservation = BudgetReservation(
        id=intent.reservation_id,
        tenant_id=intent.tenant_id,
        correlation_id=intent.correlation_id,
        passport_id=req.recorded_passport.id,
        payment_intent_id=intent.id,
        amount_minor=intent.amount_minor,
        currency=intent.currency,
        status=ReservationStatus.CAPTURED,
        expires_at=req.recorded_passport.expires_at,
    )

    errors = verify_execution_artifacts_consistency(
        req,
        payment_attempt=attempt,
        verified_capture=capture,
        budget_reservation=reservation,
    )
    assert errors == []

    # Mismatched capture amount + released reservation on SUCCEEDED intent -> detected
    bad_capture = capture.model_copy(update={"verified_amount_minor": 9999})
    bad_reservation = reservation.model_copy(update={"status": ReservationStatus.RELEASED})
    bad_errors = verify_execution_artifacts_consistency(
        req,
        payment_attempt=attempt,
        verified_capture=bad_capture,
        budget_reservation=bad_reservation,
    )
    assert any("Capture amount mismatch" in e for e in bad_errors)
    assert any("Reservation state mismatch" in e for e in bad_errors)

    # Cross-tenant execution artifacts raise TenantIsolationError via provenance verification
    foreign_attempt = attempt.model_copy(update={"tenant_id": TENANT_BETA_ID})
    with pytest.raises(TenantIsolationError):
        verify_provenance_and_integrity(req, payment_attempt=foreign_attempt)

    foreign_reservation = reservation.model_copy(update={"tenant_id": TENANT_BETA_ID})
    with pytest.raises(TenantIsolationError):
        verify_provenance_and_integrity(req, budget_reservation=foreign_reservation)


# ---------------------------------------------------------------------------
# 4. PaymentTrace.to_replay_request Fail-Closed Behavior
# ---------------------------------------------------------------------------


def test_payment_trace_to_replay_request_fails_closed_when_missing_evidence() -> None:
    trace_no_proposal = make_test_trace()
    assert trace_no_proposal.proposal is None
    with pytest.raises(InsufficientEvidenceError):
        trace_no_proposal.to_replay_request()

    fixture = _canonical_fixture()
    complete_trace = trace_no_proposal.model_copy(
        update={
            "proposal": fixture["proposal"].model_copy(
                update={
                    "tenant_id": trace_no_proposal.tenant_id,
                    "correlation_id": trace_no_proposal.payment_intent.correlation_id,
                    "agent_id": trace_no_proposal.agent_id,
                    "merchant_id": trace_no_proposal.quote_snapshot.merchant_id,
                    "amount_minor": trace_no_proposal.quote_snapshot.amount_minor,
                    "currency": trace_no_proposal.quote_snapshot.currency,
                }
            )
        }
    )
    req = complete_trace.to_replay_request()
    assert isinstance(req, ReplayRequest)
    assert req.evaluation_time == complete_trace.recorded_decision.decided_at

    trace_no_intent = complete_trace.model_copy(update={"payment_intent": None})
    with pytest.raises(InsufficientEvidenceError):
        trace_no_intent.to_replay_request()


def test_create_investigation_handles_incomplete_trace_without_crashing() -> None:
    service = GhostPayService()
    trace = make_test_trace(with_events=True)  # proposal is None
    service.ingestion.traces[trace.trace_id] = trace
    service.agent_history[(trace.tenant_id, trace.agent_id)] = [trace]

    report = service.create_investigation(tenant_id=trace.tenant_id, trace_id=trace.trace_id)
    assert report.detected_anomalies == []
    assert report.counterfactual_replay_results == []


# ---------------------------------------------------------------------------
# 5. Anomaly Detector & Safeguard Recommendations Harmonization
# ---------------------------------------------------------------------------


def test_legitimate_deny_blocks_do_not_emit_false_positive_anomalies() -> None:
    fixture = _canonical_fixture()
    req: ReplayRequest = fixture["replay_request"]

    unknown_merchant = fixture["unknown_merchant"]
    matching_proposal = req.proposal.model_copy(update={"merchant_id": unknown_merchant.id, "amount_minor": 60000})
    matching_quote_hash = compute_quote_hash(
        merchant_id=unknown_merchant.id,
        amount_minor=60000,
        currency=req.quote_snapshot.currency,
        line_items=req.quote_snapshot.line_items,
    )
    matching_quote = req.quote_snapshot.model_copy(
        update={
            "merchant_id": unknown_merchant.id,
            "amount_minor": 60000,
            "quote_hash": matching_quote_hash,
        }
    )
    denied_decision = req.recorded_decision.model_copy(
        update={
            "outcome": DecisionOutcome.DENY,
            "quote_hash": matching_quote_hash,
            "reason_codes": [
                DecisionReasonCode.DENIED_PASSPORT_EXPIRED,
                DecisionReasonCode.DENIED_MERCHANT_NOT_ALLOWLISTED,
            ],
        }
    )
    expired_passport = req.recorded_passport.model_copy(update={"status": PassportStatus.EXPIRED})
    denied_intent = req.payment_intent.model_copy(
        update={
            "state": PaymentState.FAILED,
            "amount_minor": 60000,
            "quote_hash": matching_quote_hash,
        }
    )
    pre_capture_events = [
        ev for ev in req.events if ev.event_type.value != "PAYPAL_CAPTURE_VERIFIED"
    ]

    denied_req = req.model_copy(
        update={
            "recorded_decision": denied_decision,
            "payment_intent": denied_intent,
            "recorded_passport": expired_passport,
            "recorded_merchant": unknown_merchant,
            "proposal": matching_proposal,
            "quote_snapshot": matching_quote,
            "events": pre_capture_events,
        }
    )

    anomalies = detect_anomalies(
        denied_req,
        original_decision=denied_decision,
        recomputed_outcome=DecisionOutcome.DENY,
        recomputed_reason_codes=denied_decision.reason_codes,
    )
    assert anomalies == []


def test_execution_despite_deny_and_recommendations_are_flagged() -> None:
    fixture = _canonical_fixture()
    req: ReplayRequest = fixture["replay_request"]
    denied_decision = req.recorded_decision.model_copy(
        update={
            "outcome": DecisionOutcome.DENY,
            "reason_codes": [DecisionReasonCode.DENIED_EXCEEDS_PER_TX_LIMIT],
        }
    )
    # PaymentIntent is still SUCCEEDED despite DENY decision!
    bad_req = req.model_copy(update={"recorded_decision": denied_decision})
    anomalies = detect_anomalies(
        bad_req,
        original_decision=denied_decision,
        recomputed_outcome=DecisionOutcome.DENY,
        recomputed_reason_codes=[DecisionReasonCode.DENIED_EXCEEDS_PER_TX_LIMIT],
    )
    assert any(a.startswith("EXECUTION_DESPITE_DENY:") for a in anomalies)

    res = ReplayEngine.replay(bad_req)
    recs = generate_safeguard_recommendations(res)
    assert any("CRITICAL:" in r for r in recs)


def test_recommendations_cover_harmonized_reason_and_anomaly_codes() -> None:
    fixture = _canonical_fixture()
    req: ReplayRequest = fixture["replay_request"]

    paused_res = ReplayEngine.replay(
        req.model_copy(
            update={
                "recorded_passport": req.recorded_passport.model_copy(
                    update={"status": PassportStatus.PAUSED}
                )
            }
        )
    )
    recs = generate_safeguard_recommendations(paused_res)
    assert any("passport" in r.lower() for r in recs)

    currency_res = ReplayEngine.replay(
        req.model_copy(
            update={
                "recorded_passport": req.recorded_passport.model_copy(
                    update={"allowed_currencies": ["EUR"]}
                )
            }
        )
    )
    recs_cur = generate_safeguard_recommendations(currency_res)
    assert any("currency" in r.lower() for r in recs_cur)


# ---------------------------------------------------------------------------
# 6. Agent DNA Deduplication, Future Leakage Prevention, & Cross-Entity Tenancy
# ---------------------------------------------------------------------------


def test_agent_profile_deduplicates_traces_and_excludes_future_window_leakage() -> None:
    t0 = datetime(2026, 11, 10, 10, 0, tzinfo=UTC)
    t1 = datetime(2026, 11, 10, 11, 0, tzinfo=UTC)
    cutoff = datetime(2026, 11, 10, 12, 0, tzinfo=UTC)
    t_future = datetime(2026, 11, 10, 15, 0, tzinfo=UTC)

    tr0 = make_test_trace(amount_minor=1000, created_at=t0)
    tr1 = make_test_trace(amount_minor=3000, created_at=t1)
    tr_future = make_test_trace(amount_minor=99999, created_at=t_future)

    # Duplicate tr0 and include tr_future beyond cutoff
    history = [tr0, tr0, tr1, tr_future]

    features = extract_agent_features(history, cutoff_time=cutoff)
    assert features.sample_count == 2
    assert features.total_spent_minor == 4000
    assert features.max_amount_minor == 3000

    profile = build_agent_profile(TENANT_ALPHA_ID, tr0.agent_id, history, cutoff_time=cutoff)
    assert profile.sample_count == 2
    assert profile.training_window_start == t0
    assert profile.training_window_end == t1
    assert profile.training_window_end < cutoff


def test_agent_profile_rejects_cross_tenant_history() -> None:
    tr_alpha = make_test_trace(tenant_id=TENANT_ALPHA_ID)
    tr_beta = make_test_trace(tenant_id=TENANT_BETA_ID)

    with pytest.raises(CrossTenantAccessError):
        build_agent_profile(TENANT_ALPHA_ID, tr_alpha.agent_id, [tr_alpha, tr_beta])


def test_trace_validator_enforces_cross_entity_tenant_isolation() -> None:
    fixture = _canonical_fixture()
    req: ReplayRequest = fixture["replay_request"]

    adapter = TraceIngestionAdapter()
    base_kwargs = {
        "tenant_id": TENANT_ALPHA_ID,
        "agent_id": req.payment_intent.agent_id,
        "payment_intent_id": req.payment_intent.id,
        "events": req.events,
        "quote_snapshot": req.quote_snapshot,
        "evidence_records": req.evidence_records,
        "recorded_decision": req.recorded_decision,
        "recorded_passport": req.recorded_passport,
        "recorded_merchant": req.recorded_merchant,
        "payment_intent": req.payment_intent,
        "proposal": req.proposal,
    }

    for field_name in (
        "proposal",
        "quote_snapshot",
        "recorded_decision",
        "recorded_passport",
        "recorded_merchant",
    ):
        foreign_entity = base_kwargs[field_name].model_copy(update={"tenant_id": TENANT_BETA_ID})
        with pytest.raises(CrossTenantAccessError):
            adapter.build_trace(**{**base_kwargs, field_name: foreign_entity})

    # Also verify direct TraceValidator rejects foreign merchant/proposal
    with pytest.raises(CrossTenantAccessError):
        TraceValidator.validate_tenant_isolation(
            TENANT_ALPHA_ID,
            recorded_merchant=req.recorded_merchant.model_copy(update={"tenant_id": TENANT_BETA_ID}),
        )
