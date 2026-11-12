"""Deterministic policy & authorization replay engine for GhostPay."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Any
from uuid import UUID, uuid4

from contracts import (
    AgentIdentity,
    ApprovalRecord,
    ApprovalStatus,
    DecisionOutcome,
    DecisionReasonCode,
    Merchant,
    PurchaseProposal,
    QuoteSnapshot,
    ReplayRequest,
    ReplayResult,
    SpendingPassport,
    evaluate_policy_v1,
)
from contracts.policy_v1 import evaluate_policy_v1_rules

from ghostpay.anomalies.detector import detect_anomalies
from ghostpay.domain.exceptions import IllegalSideEffectError, InsufficientEvidenceError
from ghostpay.errors import (
    OverrideValidationError,
    ReplayExecutionForbiddenError,
)
from ghostpay.provenance.verifier import verify_provenance_and_integrity
from ghostpay.replay.registry import (
    DEFAULT_POLICY_VERSION,
    register_policy_evaluator,
    resolve_policy_evaluator,
)
from ghostpay.timelines.builder import build_timeline

if TYPE_CHECKING:
    from ghostpay.domain.models import PaymentTrace
    from ghostpay.timemachine.policies import CounterfactualPolicy


def _safe_nonneg_int(val: Any, default: int = 0) -> int:
    if isinstance(val, int) and not isinstance(val, bool) and val >= 0:
        return val
    return default


def evaluate_deterministic_policy(
    *,
    proposal: PurchaseProposal,
    quote: QuoteSnapshot,
    passport: SpendingPassport,
    merchant: Merchant,
    approval_record: ApprovalRecord | None = None,
    evaluation_time: datetime | None = None,
    now: datetime | None = None,
    check_quote_expiration: bool = False,
    agent: AgentIdentity | None = None,
    daily_spent_minor: int = 0,
    monthly_spent_minor: int = 0,
    correlation_id: UUID | None = None,
    payment_intent_id: UUID | None = None,
) -> tuple[DecisionOutcome, list[DecisionReasonCode], list[str]]:
    """Delegate policy-v1 evaluation strictly to contracts.policy_v1.evaluate_policy_v1."""
    # Never fall back to wall-clock time during forensic evaluation.
    eval_time = evaluation_time or now or quote.created_at

    decision = evaluate_policy_v1(
        proposal=proposal,
        passport=passport,
        merchant=merchant,
        quote=quote,
        agent=agent,
        approval_record=approval_record,
        daily_spent_minor=daily_spent_minor,
        monthly_spent_minor=monthly_spent_minor,
        now=eval_time,
        correlation_id=correlation_id or proposal.correlation_id,
        policy_version=DEFAULT_POLICY_VERSION,
        payment_intent_id=payment_intent_id,
    )

    return decision.outcome, list(decision.reason_codes), list(decision.violated_constraints)


register_policy_evaluator(DEFAULT_POLICY_VERSION, evaluate_deterministic_policy)


class ReplayEngine:
    """Read-only forensic policy & authorization replay engine."""

    @staticmethod
    def capture_payment(*args: Any, **kwargs: Any) -> None:
        raise IllegalSideEffectError("Replay engine cannot invoke payment capture")

    @staticmethod
    def reserve_budget(*args: Any, **kwargs: Any) -> None:
        raise IllegalSideEffectError("Replay engine cannot reserve budget")

    @staticmethod
    def release_reservation(*args: Any, **kwargs: Any) -> None:
        raise IllegalSideEffectError("Replay engine cannot release budget")

    @classmethod
    def replay(cls, request: ReplayRequest, *, agent: AgentIdentity | None = None) -> ReplayResult:
        """Deterministically replay a transaction without mutating state or executing payments."""
        # 1. Baseline replay must never silently ignore counterfactual overrides
        if request.counterfactual_overrides:
            raise OverrideValidationError(
                "Baseline replay cannot execute with nonempty counterfactual_overrides. "
                "Use /ghostpay/simulate or simulate_counterfactual() for what-if simulations.",
                errors=[
                    {
                        "field": "counterfactual_overrides",
                        "message": "Nonempty counterfactual_overrides are forbidden in baseline replay.",
                    }
                ],
            )

        # 2. Enforce tenancy & verify provenance, correlation binding, event hash-chain, evidence integrity
        integrity_valid, missing_evidence, integrity_errors = verify_provenance_and_integrity(request)

        # 3. Resolve exact requested policy evaluator (fail closed on unsupported versions)
        executed_policy_version, policy_evaluator = resolve_policy_evaluator(request.policy_version)

        # 4. Reconstruct deterministic event timeline
        timeline = build_timeline(request.events, request.evidence_records)

        # 5. Deterministically recompute policy outcome (never using wall-clock time)
        original_decision = request.recorded_decision
        eval_time = request.evaluation_time or original_decision.decided_at
        policy_inputs = original_decision.policy_inputs or {}
        daily_spent = _safe_nonneg_int(policy_inputs.get("daily_spent_minor"), 0)
        monthly_spent = _safe_nonneg_int(policy_inputs.get("monthly_spent_minor"), 0)
        agent_obj = agent if agent is not None else getattr(request, "agent", None)

        recomputed_outcome, recomputed_reasons, new_violated_constraints = policy_evaluator(
            proposal=request.proposal,
            quote=request.quote_snapshot,
            passport=request.recorded_passport,
            merchant=request.recorded_merchant,
            approval_record=request.approval_record,
            evaluation_time=eval_time,
            agent=agent_obj,
            daily_spent_minor=daily_spent,
            monthly_spent_minor=monthly_spent,
            correlation_id=request.correlation_id,
            payment_intent_id=request.payment_intent.id,
        )

        original_outcome = original_decision.outcome
        original_reasons = original_decision.reason_codes

        # 6. Check policy-version consistency against recorded artifacts
        version_mismatches: list[str] = []
        if original_decision.policy_version != executed_policy_version:
            version_mismatches.append(
                f"POLICY_VERSION_MISMATCH: executed={executed_policy_version} != "
                f"recorded_decision.policy_version={original_decision.policy_version}"
            )
        if request.recorded_passport.policy_version != executed_policy_version:
            version_mismatches.append(
                f"POLICY_VERSION_MISMATCH: executed={executed_policy_version} != "
                f"recorded_passport.policy_version={request.recorded_passport.policy_version}"
            )

        # 7. Check authorization drift
        outcome_changed = recomputed_outcome != original_outcome
        reasons_changed = set(recomputed_reasons) != set(original_reasons)
        drift_detected = outcome_changed or reasons_changed or bool(version_mismatches)

        # 8. Compute changed constraints
        changed_constraints: list[str] = []
        if outcome_changed:
            changed_constraints.append(
                f"OUTCOME_CHANGED: {original_outcome.value} -> {recomputed_outcome.value}"
            )
        changed_constraints.extend(version_mismatches)
        for constraint in new_violated_constraints:
            if constraint not in original_decision.violated_constraints:
                changed_constraints.append(f"VIOLATED_CONSTRAINT: {constraint}")
        for code in recomputed_reasons:
            if code not in original_reasons:
                changed_constraints.append(f"NEW_REASON_CODE: {code.value}")

        # 9. Detect anomalies
        anomalies = detect_anomalies(
            request,
            original_decision=original_decision,
            recomputed_outcome=recomputed_outcome,
            recomputed_reason_codes=recomputed_reasons,
            integrity_errors=integrity_errors,
            executed_policy_version=executed_policy_version,
        )

        # 10. Determine consistency status with canonical priority:
        # INTEGRITY_FAILURE > INCOMPLETE_EVIDENCE > DRIFT_DETECTED > CONSISTENT
        if not integrity_valid:
            consistency_status = "INTEGRITY_FAILURE"
        elif missing_evidence:
            consistency_status = "INCOMPLETE_EVIDENCE"
        elif drift_detected:
            consistency_status = "DRIFT_DETECTED"
        else:
            consistency_status = "CONSISTENT"

        # 11. Deterministic explanation (bounded cleanly to <= 2000 chars)
        explanation = (
            f"Deterministic replay completed for correlation_id={request.correlation_id} "
            f"using policy_version={executed_policy_version}. "
            f"Original outcome: {original_outcome.value} ({[r.value for r in original_reasons]}). "
            f"Recomputed outcome: {recomputed_outcome.value} ({[r.value for r in recomputed_reasons]}). "
            f"Consistency status: {consistency_status}. "
            f"Drift detected: {drift_detected}. "
            f"Integrity valid: {integrity_valid}. "
            f"Missing evidence count: {len(missing_evidence)}. "
            f"Anomalies detected: {len(anomalies)}."
        )[:2000]

        # 12. Evidence references
        evidence_references = [ev.id for ev in request.evidence_records]

        result = ReplayResult(
            replay_id=uuid4(),
            tenant_id=request.tenant_id,
            correlation_id=request.correlation_id,
            payment_intent_id=request.payment_intent.id,
            policy_version=executed_policy_version,
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
        if result.executed_payment is not False:
            raise ReplayExecutionForbiddenError(
                "Replay invariant violated: executed_payment must always remain False."
            )
        return result

    @classmethod
    def replay_trace(
        cls,
        trace: PaymentTrace,
        policy: CounterfactualPolicy | None = None,
    ) -> ReplayResult:
        """Replay a PaymentTrace object, failing closed to INCOMPLETE_EVIDENCE if artifacts are missing."""
        try:
            req = trace.to_replay_request()
        except InsufficientEvidenceError as exc:
            missing = getattr(trace, "missing_evidence", None) or ["INSUFFICIENT_EVIDENCE"]
            outcome = trace.recorded_decision.outcome if trace.recorded_decision else DecisionOutcome.DENY
            return ReplayResult(
                tenant_id=trace.tenant_id,
                correlation_id=trace.payment_intent_id,
                payment_intent_id=trace.payment_intent_id,
                policy_version=trace.policy_version,
                original_outcome=outcome,
                recomputed_outcome=outcome,
                drift_detected=False,
                explanation=str(exc)[:2000],
                missing_evidence=missing,
                integrity_valid=False,
                consistency_status="INCOMPLETE_EVIDENCE",
                executed_payment=False,
            )

        if policy is not None:
            from ghostpay.counterfactual.simulator import simulate_counterfactual

            return simulate_counterfactual(req, policy.to_overrides_dict())
        return cls.replay(req)


class PolicyTimeMachine(ReplayEngine):
    """Forensic Policy Time Machine supporting counterfactual replay and simulation."""

    @classmethod
    def replay(cls, request: ReplayRequest, *, agent: AgentIdentity | None = None) -> ReplayResult:
        """Replay transaction; if counterfactual_overrides are present, simulate counterfactual."""
        if request.counterfactual_overrides:
            from ghostpay.counterfactual.simulator import simulate_counterfactual

            return simulate_counterfactual(request, request.counterfactual_overrides)
        return super().replay(request, agent=agent)


__all__ = [
    "DEFAULT_POLICY_VERSION",
    "PolicyTimeMachine",
    "ReplayEngine",
    "evaluate_deterministic_policy",
]
