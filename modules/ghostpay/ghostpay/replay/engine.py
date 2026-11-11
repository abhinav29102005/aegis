"""Deterministic policy & authorization replay engine for GhostPay."""

from __future__ import annotations

from datetime import datetime
from uuid import uuid4

from contracts import (
    ApprovalRecord,
    DecisionOutcome,
    DecisionReasonCode,
    Merchant,
    PurchaseProposal,
    QuoteSnapshot,
    ReplayRequest,
    ReplayResult,
    SpendingPassport,
)
from guardian.policies.engine import PolicyEngine

from ghostpay.anomalies.detector import detect_anomalies
from ghostpay.provenance.verifier import verify_provenance_and_integrity
from ghostpay.timelines.builder import build_timeline


def evaluate_deterministic_policy(
    *,
    proposal: PurchaseProposal,
    quote: QuoteSnapshot,
    passport: SpendingPassport,
    merchant: Merchant,
    approval_record: ApprovalRecord | None = None,
    evaluation_time: datetime | None = None,
) -> tuple[DecisionOutcome, list[DecisionReasonCode], list[str]]:
    """Deterministic policy rules engine recomputing authorization outcome."""
    # Replay the initial authorization decision, not subsequent approval consumption.
    # Use Guardian's public deterministic policy interface to prevent rule drift.
    decision = PolicyEngine(policy_version="policy-v1").evaluate(
        proposal=proposal,
        passport=passport,
        merchant=merchant,
        quote=quote,
        now=evaluation_time or quote.created_at,
    )
    return decision.outcome, decision.reason_codes, decision.violated_constraints


class ReplayEngine:
    """Forensic policy & authorization replay engine."""

    @classmethod
    def replay(cls, request: ReplayRequest) -> ReplayResult:
        """Deterministically replay a transaction, recomputing policy, provenance, and timeline."""
        return cls._replay(request, hypothetical=False)

    @classmethod
    def _replay(cls, request: ReplayRequest, *, hypothetical: bool) -> ReplayResult:
        request = ReplayRequest.model_validate(request.model_dump())
        versions = {
            request.policy_version,
            request.recorded_decision.policy_version,
            request.recorded_passport.policy_version,
        }
        if versions != {"policy-v1"}:
            raise ValueError(
                "Unsupported or mismatched policy version; supported: policy-v1"
            )
        # 1. Enforce tenancy & verify provenance, event hash-chain, evidence integrity
        integrity_valid, missing_evidence, integrity_errors = (
            verify_provenance_and_integrity(request, hypothetical=hypothetical)
        )

        # 2. Reconstruct deterministic event timeline
        timeline = build_timeline(request.events, request.evidence_records)

        # 3. Deterministically recompute policy outcome
        eval_time = request.evaluation_time or request.recorded_decision.decided_at
        if eval_time < max(
            request.proposal.created_at,
            request.quote_snapshot.created_at,
            request.recorded_passport.created_at,
        ):
            raise ValueError("Evaluation time predates the supplied historical records")
        recomputed_outcome, recomputed_reasons, new_violated_constraints = (
            evaluate_deterministic_policy(
                proposal=request.proposal,
                quote=request.quote_snapshot,
                passport=request.recorded_passport,
                merchant=request.recorded_merchant,
                approval_record=request.approval_record,
                evaluation_time=eval_time,
            )
        )

        original_decision = request.recorded_decision
        original_outcome = original_decision.outcome
        original_reasons = original_decision.reason_codes

        # 4. Check authorization drift
        outcome_changed = recomputed_outcome != original_outcome
        reasons_changed = set(recomputed_reasons) != set(original_reasons)
        drift_detected = outcome_changed or reasons_changed

        # 5. Compute changed constraints
        changed_constraints: list[str] = []
        if outcome_changed:
            changed_constraints.append(
                f"OUTCOME_CHANGED: {original_outcome.value} -> {recomputed_outcome.value}"
            )
        for c in new_violated_constraints:
            if c not in original_decision.violated_constraints:
                changed_constraints.append(f"VIOLATED_CONSTRAINT: {c}")
        for code in recomputed_reasons:
            if code not in original_reasons:
                changed_constraints.append(f"NEW_REASON_CODE: {code.value}")

        # 6. Detect anomalies
        anomalies = detect_anomalies(
            request,
            original_decision=original_decision,
            recomputed_outcome=recomputed_outcome,
            recomputed_reason_codes=recomputed_reasons,
            integrity_errors=integrity_errors,
        )

        # 7. Determine consistency status with canonical priority:
        # INTEGRITY_FAILURE > INCOMPLETE_EVIDENCE > DRIFT_DETECTED > CONSISTENT
        if not integrity_valid:
            consistency_status = "INTEGRITY_FAILURE"
        elif missing_evidence:
            consistency_status = "INCOMPLETE_EVIDENCE"
        elif drift_detected:
            consistency_status = "DRIFT_DETECTED"
        else:
            consistency_status = "CONSISTENT"

        # 8. Deterministic explanation
        explanation = (
            f"{'Hypothetical simulation' if hypothetical else 'Initial authorization replay'} completed for correlation_id={request.correlation_id}. "
            f"Original outcome: {original_outcome.value} ({[r.value for r in original_reasons]}). "
            f"Recomputed outcome: {recomputed_outcome.value} ({[r.value for r in recomputed_reasons]}). "
            f"Consistency status: {consistency_status}. "
            f"Drift detected: {drift_detected}. "
            f"Integrity valid: {integrity_valid}. "
            f"Missing evidence count: {len(missing_evidence)}. "
            f"Anomalies detected: {len(anomalies)}."
        )

        # 9. Evidence references
        evidence_references = sorted(
            {
                ev.id
                for ev in request.evidence_records
                if ev.payment_intent_id == request.payment_intent.id
                and ev.correlation_id == request.correlation_id
            },
            key=str,
        )

        return ReplayResult(
            replay_id=uuid4(),
            tenant_id=request.tenant_id,
            correlation_id=request.correlation_id,
            payment_intent_id=request.payment_intent.id,
            policy_version=request.policy_version,
            timeline=timeline,
            original_outcome=original_outcome,
            recomputed_outcome=recomputed_outcome,
            original_reason_codes=original_reasons,
            recomputed_reason_codes=recomputed_reasons,
            changed_constraints=changed_constraints,
            drift_detected=drift_detected,
            explanation=explanation,
            evidence_references=evidence_references,
            missing_evidence=missing_evidence,
            anomalies=anomalies,
            integrity_valid=integrity_valid,
            consistency_status=consistency_status,
            executed_payment=False,
        )
