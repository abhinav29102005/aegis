"""Comprehensive test suite for ReplayEngine edge cases, determinism, and invariants."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from contracts import (
    AgentIdentity,
    ApprovalRecord,
    ApprovalStatus,
    DecisionOutcome,
    DecisionReasonCode,
    EvidenceRecord,
    EvidenceSourceType,
    FinancialEvent,
    FinancialEventType,
    Merchant,
    PassportStatus,
    PaymentIntent,
    PaymentState,
    PurchaseProposal,
    QuoteSnapshot,
    ReplayRequest,
    SpendingPassport,
    compute_payload_hash,
    compute_quote_hash,
)
from contracts.fixtures import (
    AGENT_PROCUREMENT_ID,
    MERCHANT_SANDBOX_CLOUD_ID,
    PASSPORT_DEFAULT_ID,
    TENANT_ALPHA_ID,
    TENANT_BETA_ID,
    build_authorized_39_purchase_fixture,
)
from security import compute_financial_event_hash

from ghostpay.counterfactual.simulator import simulate_counterfactual
from ghostpay.domain.models import PaymentTrace
from ghostpay.errors import (
    OverrideValidationError,
    ReplayExecutionForbiddenError,
    UnsupportedPolicyVersionError,
)
from ghostpay.replay.engine import (
    ReplayEngine,
    _safe_nonneg_int,
    evaluate_deterministic_policy,
)
from ghostpay.replay.registry import (
    DEFAULT_POLICY_VERSION,
    get_registered_policy_versions,
    register_policy_evaluator,
    resolve_policy_evaluator,
)
from ghostpay.timemachine.policies import CounterfactualPolicy


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


def _make_complete_trace(
    *,
    amount_minor: int = 3900,
    outcome: DecisionOutcome = DecisionOutcome.ALLOW,
    policy_version: str = "policy-v1",
) -> PaymentTrace:
    fixture = _canonical_fixture()
    req = fixture["replay_request"]
    t_time = datetime(2026, 11, 10, 10, 0, 0, tzinfo=UTC)

    decision = req.recorded_decision.model_copy(
        update={
            "outcome": outcome,
            "policy_version": policy_version,
            "decided_at": t_time,
        }
    )

    return PaymentTrace(
        trace_id=uuid4(),
        tenant_id=req.tenant_id,
        agent_id=req.proposal.agent_id,
        payment_intent_id=req.payment_intent.id,
        ordered_events=list(req.events),
        quote_snapshot=req.quote_snapshot,
        authorization_evidence=list(req.evidence_records),
        recorded_decision=decision,
        recorded_passport=req.recorded_passport,
        recorded_merchant=req.recorded_merchant,
        payment_intent=req.payment_intent,
        proposal=req.proposal,
        policy_version=policy_version,
        integrity_status="VALID",
        created_at=t_time,
    )


def _make_approval(
    req: ReplayRequest,
    proposal: PurchaseProposal,
    quote: QuoteSnapshot,
    *,
    status: ApprovalStatus = ApprovalStatus.APPROVED,
    tenant_id: UUID | None = None,
    bound_merchant_id: UUID | None = None,
    bound_amount_minor: int | None = None,
    bound_currency: str | None = None,
    bound_quote_hash: str | None = None,
    expires_at: datetime | None = None,
) -> ApprovalRecord:
    return ApprovalRecord(
        id=uuid4(),
        tenant_id=tenant_id or req.tenant_id,
        correlation_id=req.correlation_id,
        payment_intent_id=req.payment_intent.id,
        decision_id=req.recorded_decision.id,
        approver_id="human-reviewer@example.com",
        bound_amount_minor=bound_amount_minor if bound_amount_minor is not None else proposal.amount_minor,
        bound_currency=bound_currency or proposal.currency,
        bound_merchant_id=bound_merchant_id or req.recorded_merchant.id,
        bound_quote_hash=bound_quote_hash or quote.quote_hash,
        status=status,
        expires_at=expires_at or (quote.created_at + timedelta(hours=2)),
        created_at=quote.created_at,
        comment="Approved by CFO",
    )


def test_safe_nonneg_int_edge_cases() -> None:
    """_safe_nonneg_int guards against invalid types, negative ints, and booleans."""
    assert _safe_nonneg_int(0) == 0
    assert _safe_nonneg_int(500) == 500
    assert _safe_nonneg_int(-1, default=10) == 10
    assert _safe_nonneg_int(-100) == 0
    # Crucial: in Python, isinstance(True, int) is True, but booleans must NOT be treated as integers!
    assert _safe_nonneg_int(True, default=99) == 99
    assert _safe_nonneg_int(False, default=99) == 99
    assert _safe_nonneg_int(3.14, default=42) == 42
    assert _safe_nonneg_int("100", default=5) == 5
    assert _safe_nonneg_int(None, default=0) == 0
    assert _safe_nonneg_int([], default=7) == 7


def test_approval_record_resolves_escalate_to_allow() -> None:
    """When policy-v1 escalates, a valid approved ApprovalRecord resolves to ALLOW."""
    fixture = _canonical_fixture()
    req = fixture["replay_request"]

    # Configure purchase of $60.00: exceeds human approval threshold of $50.00, below $75.00 limit
    amount = 6000
    line_items = [{"sku": "SKU-EXPENSIVE", "name": "Big Server", "amount_minor": amount, "quantity": 1}]
    q_hash = compute_quote_hash(
        merchant_id=req.quote_snapshot.merchant_id,
        amount_minor=amount,
        currency=req.quote_snapshot.currency,
        line_items=line_items,
    )
    quote = req.quote_snapshot.model_copy(update={
        "amount_minor": amount,
        "line_items": line_items,
        "quote_hash": q_hash,
    })
    proposal = req.proposal.model_copy(update={
        "amount_minor": amount,
        "line_items": line_items,
    })

    # Without approval record: policy escalates
    escalated_req = req.model_copy(update={"quote_snapshot": quote, "proposal": proposal})
    outcome_esc, reasons_esc, constraints_esc = evaluate_deterministic_policy(
        proposal=proposal,
        quote=quote,
        passport=req.recorded_passport,
        merchant=req.recorded_merchant,
        approval_record=None,
        evaluation_time=quote.created_at,
    )
    assert outcome_esc == DecisionOutcome.ESCALATE
    assert DecisionReasonCode.ESCALATED_REQUIRES_HUMAN_APPROVAL in reasons_esc

    # Attach valid APPROVED ApprovalRecord
    approval = _make_approval(req, proposal, quote, status=ApprovalStatus.APPROVED)

    outcome_allow, reasons_allow, constraints_allow = evaluate_deterministic_policy(
        proposal=proposal,
        quote=quote,
        passport=req.recorded_passport,
        merchant=req.recorded_merchant,
        approval_record=approval,
        evaluation_time=quote.created_at,
    )
    assert outcome_allow == DecisionOutcome.ALLOW
    assert reasons_allow == [DecisionReasonCode.OK_WITHIN_POLICY]
    assert constraints_allow == []

    # Also works for CONSUMED status
    approval_consumed = approval.model_copy(update={"status": ApprovalStatus.CONSUMED})
    outcome_consumed, reasons_consumed, _ = evaluate_deterministic_policy(
        proposal=proposal,
        quote=quote,
        passport=req.recorded_passport,
        merchant=req.recorded_merchant,
        approval_record=approval_consumed,
        evaluation_time=quote.created_at,
    )
    assert outcome_consumed == DecisionOutcome.ALLOW
    assert reasons_consumed == [DecisionReasonCode.OK_WITHIN_POLICY]


def test_approval_record_cross_tenant_denied() -> None:
    """Approval record with mismatched tenant_id must result in DENIED_CROSS_TENANT."""
    fixture = _canonical_fixture()
    req = fixture["replay_request"]

    amount = 6000
    line_items = [{"sku": "SKU-EXPENSIVE", "name": "Big Server", "amount_minor": amount, "quantity": 1}]
    q_hash = compute_quote_hash(
        merchant_id=req.quote_snapshot.merchant_id,
        amount_minor=amount,
        currency=req.quote_snapshot.currency,
        line_items=line_items,
    )
    quote = req.quote_snapshot.model_copy(update={
        "amount_minor": amount,
        "line_items": line_items,
        "quote_hash": q_hash,
    })
    proposal = req.proposal.model_copy(update={
        "amount_minor": amount,
        "line_items": line_items,
    })

    cross_tenant_approval = _make_approval(req, proposal, quote, tenant_id=TENANT_BETA_ID)

    outcome, reasons, constraints = evaluate_deterministic_policy(
        proposal=proposal,
        quote=quote,
        passport=req.recorded_passport,
        merchant=req.recorded_merchant,
        approval_record=cross_tenant_approval,
        evaluation_time=quote.created_at,
    )
    assert outcome == DecisionOutcome.DENY
    assert DecisionReasonCode.DENIED_CROSS_TENANT in reasons
    assert "APPROVAL_RECORD_CROSS_TENANT" in constraints


def test_approval_record_expired_status_or_timestamp_denied() -> None:
    """Approval record that is expired by status or timestamp must result in DENIED_APPROVAL_EXPIRED."""
    fixture = _canonical_fixture()
    req = fixture["replay_request"]

    amount = 6000
    line_items = [{"sku": "SKU-EXPENSIVE", "name": "Big Server", "amount_minor": amount, "quantity": 1}]
    q_hash = compute_quote_hash(
        merchant_id=req.quote_snapshot.merchant_id,
        amount_minor=amount,
        currency=req.quote_snapshot.currency,
        line_items=line_items,
    )
    quote = req.quote_snapshot.model_copy(update={
        "amount_minor": amount,
        "line_items": line_items,
        "quote_hash": q_hash,
    })
    proposal = req.proposal.model_copy(update={
        "amount_minor": amount,
        "line_items": line_items,
    })

    # Case 1: status is EXPIRED
    expired_status_approval = _make_approval(req, proposal, quote, status=ApprovalStatus.EXPIRED)
    outcome, reasons, constraints = evaluate_deterministic_policy(
        proposal=proposal,
        quote=quote,
        passport=req.recorded_passport,
        merchant=req.recorded_merchant,
        approval_record=expired_status_approval,
        evaluation_time=quote.created_at,
    )
    assert outcome == DecisionOutcome.DENY
    assert DecisionReasonCode.DENIED_APPROVAL_EXPIRED in reasons
    assert "APPROVAL_RECORD_EXPIRED" in constraints

    # Case 2: status is APPROVED, but eval_time >= expires_at
    expired_time_approval = _make_approval(
        req,
        proposal,
        quote,
        status=ApprovalStatus.APPROVED,
        expires_at=quote.created_at - timedelta(seconds=1),
    )
    outcome2, reasons2, constraints2 = evaluate_deterministic_policy(
        proposal=proposal,
        quote=quote,
        passport=req.recorded_passport,
        merchant=req.recorded_merchant,
        approval_record=expired_time_approval,
        evaluation_time=quote.created_at,
    )
    assert outcome2 == DecisionOutcome.DENY
    assert DecisionReasonCode.DENIED_APPROVAL_EXPIRED in reasons2
    assert "APPROVAL_RECORD_EXPIRED" in constraints2


def test_approval_record_mismatch_denied() -> None:
    """Approval record bound parameters mismatching proposal/quote must result in DENIED_APPROVAL_MISMATCH."""
    fixture = _canonical_fixture()
    req = fixture["replay_request"]

    amount = 6000
    line_items = [{"sku": "SKU-EXPENSIVE", "name": "Big Server", "amount_minor": amount, "quantity": 1}]
    q_hash = compute_quote_hash(
        merchant_id=req.quote_snapshot.merchant_id,
        amount_minor=amount,
        currency=req.quote_snapshot.currency,
        line_items=line_items,
    )
    quote = req.quote_snapshot.model_copy(update={
        "amount_minor": amount,
        "line_items": line_items,
        "quote_hash": q_hash,
    })
    proposal = req.proposal.model_copy(update={
        "amount_minor": amount,
        "line_items": line_items,
    })

    # 1. Merchant mismatch
    mismatched_merchant = _make_approval(req, proposal, quote, bound_merchant_id=uuid4())
    o1, r1, c1 = evaluate_deterministic_policy(
        proposal=proposal,
        quote=quote,
        passport=req.recorded_passport,
        merchant=req.recorded_merchant,
        approval_record=mismatched_merchant,
        evaluation_time=quote.created_at,
    )
    assert o1 == DecisionOutcome.DENY
    assert DecisionReasonCode.DENIED_APPROVAL_MISMATCH in r1
    assert "APPROVAL_RECORD_MISMATCH" in c1

    # 2. Amount mismatch
    mismatched_amount = _make_approval(req, proposal, quote, bound_amount_minor=5500)
    o2, r2, c2 = evaluate_deterministic_policy(
        proposal=proposal,
        quote=quote,
        passport=req.recorded_passport,
        merchant=req.recorded_merchant,
        approval_record=mismatched_amount,
        evaluation_time=quote.created_at,
    )
    assert o2 == DecisionOutcome.DENY
    assert DecisionReasonCode.DENIED_APPROVAL_MISMATCH in r2

    # 3. Currency mismatch
    mismatched_currency = _make_approval(req, proposal, quote, bound_currency="EUR")
    o3, r3, c3 = evaluate_deterministic_policy(
        proposal=proposal,
        quote=quote,
        passport=req.recorded_passport,
        merchant=req.recorded_merchant,
        approval_record=mismatched_currency,
        evaluation_time=quote.created_at,
    )
    assert o3 == DecisionOutcome.DENY
    assert DecisionReasonCode.DENIED_APPROVAL_MISMATCH in r3

    # 4. Quote hash mismatch
    mismatched_hash = _make_approval(req, proposal, quote, bound_quote_hash="deadbeef" * 8)
    o4, r4, c4 = evaluate_deterministic_policy(
        proposal=proposal,
        quote=quote,
        passport=req.recorded_passport,
        merchant=req.recorded_merchant,
        approval_record=mismatched_hash,
        evaluation_time=quote.created_at,
    )
    assert o4 == DecisionOutcome.DENY
    assert DecisionReasonCode.DENIED_APPROVAL_MISMATCH in r4


def test_approval_record_rejected_denied() -> None:
    """Approval record with status REJECTED must result in DENIED_APPROVAL_MISMATCH and APPROVAL_RECORD_REJECTED."""
    fixture = _canonical_fixture()
    req = fixture["replay_request"]

    amount = 6000
    line_items = [{"sku": "SKU-EXPENSIVE", "name": "Big Server", "amount_minor": amount, "quantity": 1}]
    q_hash = compute_quote_hash(
        merchant_id=req.quote_snapshot.merchant_id,
        amount_minor=amount,
        currency=req.quote_snapshot.currency,
        line_items=line_items,
    )
    quote = req.quote_snapshot.model_copy(update={
        "amount_minor": amount,
        "line_items": line_items,
        "quote_hash": q_hash,
    })
    proposal = req.proposal.model_copy(update={
        "amount_minor": amount,
        "line_items": line_items,
    })

    rejected_approval = _make_approval(req, proposal, quote, status=ApprovalStatus.REJECTED)
    outcome, reasons, constraints = evaluate_deterministic_policy(
        proposal=proposal,
        quote=quote,
        passport=req.recorded_passport,
        merchant=req.recorded_merchant,
        approval_record=rejected_approval,
        evaluation_time=quote.created_at,
    )
    assert outcome == DecisionOutcome.DENY
    assert DecisionReasonCode.DENIED_APPROVAL_MISMATCH in reasons
    assert "APPROVAL_RECORD_REJECTED" in constraints


def test_approval_record_cannot_override_deny() -> None:
    """Human approval record only applies when policy outcome is ESCALATE, NEVER when outcome is DENY."""
    fixture = _canonical_fixture()
    req = fixture["replay_request"]

    # Passport is REVOKED -> policy outcome is DENY
    revoked_passport = req.recorded_passport.model_copy(update={"status": PassportStatus.REVOKED})

    approval = _make_approval(
        req,
        req.proposal,
        req.quote_snapshot,
        status=ApprovalStatus.APPROVED,
    )

    outcome, reasons, constraints = evaluate_deterministic_policy(
        proposal=req.proposal,
        quote=req.quote_snapshot,
        passport=revoked_passport,
        merchant=req.recorded_merchant,
        approval_record=approval,
        evaluation_time=req.quote_snapshot.created_at,
    )
    # Outcome MUST remain DENY despite approved human approval record!
    assert outcome == DecisionOutcome.DENY
    assert DecisionReasonCode.DENIED_PASSPORT_REVOKED in reasons


def test_passport_policy_version_mismatch_triggers_drift() -> None:
    """If recorded_passport.policy_version differs from executed evaluator, drift is flagged."""
    fixture = _canonical_fixture()
    req = fixture["replay_request"]

    mismatched_passport = req.recorded_passport.model_copy(update={"policy_version": "policy-v0"})
    mismatched_req = req.model_copy(update={"recorded_passport": mismatched_passport})

    res = ReplayEngine.replay(mismatched_req)
    assert res.policy_version == "policy-v1"
    assert res.drift_detected is True
    assert res.consistency_status == "DRIFT_DETECTED"
    assert any("POLICY_VERSION_MISMATCH" in a for a in res.anomalies)
    assert any("recorded_passport.policy_version=policy-v0" in c for c in res.changed_constraints)


def test_register_policy_evaluator_validation() -> None:
    """register_policy_evaluator rejects empty version strings and resolve_policy_evaluator fails closed."""
    with pytest.raises(ValueError, match="Policy version identifier cannot be empty"):
        register_policy_evaluator("", lambda **kwargs: None)  # type: ignore[arg-type]

    with pytest.raises(ValueError, match="Policy version identifier cannot be empty"):
        register_policy_evaluator("   ", lambda **kwargs: None)  # type: ignore[arg-type]

    with pytest.raises(UnsupportedPolicyVersionError):
        resolve_policy_evaluator("")

    with pytest.raises(UnsupportedPolicyVersionError):
        resolve_policy_evaluator("unregistered-version-999")

    # Valid registration and resolution
    custom_version = "custom-test-v1"
    register_policy_evaluator(custom_version, evaluate_deterministic_policy)
    assert custom_version in get_registered_policy_versions()
    resolved_ver, resolved_eval = resolve_policy_evaluator(custom_version)
    assert resolved_ver == custom_version
    assert resolved_eval is evaluate_deterministic_policy


def test_replay_trace_with_complete_trace_and_policy() -> None:
    """ReplayEngine.replay_trace handles complete PaymentTrace objects with and without counterfactual policy."""
    trace = _make_complete_trace()

    # 1. Baseline replay without policy
    result_baseline = ReplayEngine.replay_trace(trace)
    assert result_baseline.consistency_status == "CONSISTENT"
    assert result_baseline.original_outcome == DecisionOutcome.ALLOW
    assert result_baseline.recomputed_outcome == DecisionOutcome.ALLOW
    assert result_baseline.executed_payment is False

    # 2. Counterfactual simulation with policy
    policy = CounterfactualPolicy(
        name="Strict $20 limit",
        per_tx_limit_minor=2000,
    )
    result_sim = ReplayEngine.replay_trace(trace, policy=policy)
    assert result_sim.original_outcome == DecisionOutcome.ALLOW
    assert result_sim.recomputed_outcome == DecisionOutcome.DENY
    assert DecisionReasonCode.DENIED_EXCEEDS_PER_TX_LIMIT in result_sim.recomputed_reason_codes
    assert result_sim.drift_detected is True
    assert result_sim.executed_payment is False


def test_replay_engine_executed_payment_invariant_guard(monkeypatch: pytest.MonkeyPatch) -> None:
    """ReplayEngine.replay raises ReplayExecutionForbiddenError if executed_payment is ever corrupted to True."""
    from contracts import ReplayResult

    orig_init = ReplayResult.__init__

    def corrupt_executed_payment(self: ReplayResult, *args: object, **kwargs: object) -> None:
        kwargs["executed_payment"] = True
        orig_init(self, *args, **kwargs)

    monkeypatch.setattr(ReplayResult, "__init__", corrupt_executed_payment)

    fixture = _canonical_fixture()
    req = fixture["replay_request"]
    with pytest.raises(ReplayExecutionForbiddenError, match="executed_payment must always remain False"):
        ReplayEngine.replay(req)
