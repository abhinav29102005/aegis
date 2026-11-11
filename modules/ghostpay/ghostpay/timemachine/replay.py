"""Policy Time Machine: Deterministic, read-only counterfactual authorization replay engine."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from contracts import (
    ApprovalRecord,
    ApprovalStatus,
    DecisionOutcome,
    DecisionReasonCode,
    Merchant,
    PassportStatus,
    PurchaseProposal,
    QuoteSnapshot,
    ReplayRequest,
    ReplayResult,
    SpendingPassport,
    compute_quote_hash,
)

from ghostpay.domain.exceptions import IllegalSideEffectError
from ghostpay.domain.models import PaymentTrace
from ghostpay.forensics.anomalies import detect_anomalies
from ghostpay.forensics.provenance import verify_provenance_and_integrity
from ghostpay.forensics.timeline import build_timeline
from ghostpay.timemachine.policies import CounterfactualPolicy


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
    reason_codes: list[DecisionReasonCode] = []
    violated_constraints: list[str] = []
    eval_time = evaluation_time or quote.created_at

    # 1. Spending passport status & expiration check
    if passport.status == PassportStatus.EXPIRED:
        reason_codes.append(DecisionReasonCode.DENIED_PASSPORT_EXPIRED)
        violated_constraints.append("PASSPORT_STATUS_EXPIRED")
    elif passport.status == PassportStatus.REVOKED:
        reason_codes.append(DecisionReasonCode.DENIED_PASSPORT_REVOKED)
        violated_constraints.append("PASSPORT_STATUS_REVOKED")
    elif passport.status != PassportStatus.ACTIVE:
        reason_codes.append(DecisionReasonCode.DENIED_AGENT_SUSPENDED)
        violated_constraints.append("PASSPORT_STATUS_SUSPENDED")

    if eval_time > passport.expires_at:
        if DecisionReasonCode.DENIED_PASSPORT_EXPIRED not in reason_codes:
            reason_codes.append(DecisionReasonCode.DENIED_PASSPORT_EXPIRED)
        violated_constraints.append("PASSPORT_EXPIRED_BY_DATE")

    # 2. Transaction limits and budget
    amount = proposal.amount_minor
    if amount > passport.per_tx_limit_minor:
        reason_codes.append(DecisionReasonCode.DENIED_EXCEEDS_PER_TX_LIMIT)
        violated_constraints.append(
            f"amount_minor {amount} exceeds per_tx_limit_minor {passport.per_tx_limit_minor}"
        )

    if amount > passport.available_budget_minor:
        reason_codes.append(DecisionReasonCode.DENIED_EXCEEDS_PASSPORT_BUDGET)
        violated_constraints.append(
            f"amount_minor {amount} exceeds available_budget_minor {passport.available_budget_minor}"
        )

    if passport.daily_limit_minor > 0 and amount > passport.daily_limit_minor:
        reason_codes.append(DecisionReasonCode.DENIED_EXCEEDS_DAILY_LIMIT)
        violated_constraints.append(
            f"amount_minor {amount} exceeds daily_limit_minor {passport.daily_limit_minor}"
        )

    # 3. Merchant allowlist
    is_in_allowlist = merchant.id in passport.allowed_merchant_ids
    escalate_unknown = False

    if not is_in_allowlist:
        if not passport.allow_unknown_merchants:
            reason_codes.append(DecisionReasonCode.DENIED_MERCHANT_NOT_ALLOWLISTED)
            violated_constraints.append(f"merchant {merchant.id} not in allowed_merchant_ids")
        else:
            escalate_unknown = True

    # 4. Merchant category allowlist
    if passport.allowed_categories:
        merchant_cat = (merchant.category or "").strip().upper()
        allowed_cats = [c.strip().upper() for c in passport.allowed_categories]
        if merchant_cat not in allowed_cats and proposal.merchant_category.strip().upper() not in allowed_cats:
            reason_codes.append(DecisionReasonCode.DENIED_CATEGORY_NOT_ALLOWED)
            violated_constraints.append(f"category {merchant.category} not in allowed_categories")

    # 5. Human approval threshold & approval record validation
    has_deny = any(code.value.startswith("DENIED_") for code in reason_codes)
    requires_approval = amount >= passport.human_approval_threshold_minor

    if not has_deny:
        if requires_approval:
            if approval_record is None:
                reason_codes.append(DecisionReasonCode.ESCALATED_REQUIRES_HUMAN_APPROVAL)
                violated_constraints.append(
                    f"amount_minor {amount} requires human approval (threshold {passport.human_approval_threshold_minor})"
                )
            else:
                if approval_record.status == ApprovalStatus.EXPIRED or (
                    approval_record.expires_at and eval_time > approval_record.expires_at
                ):
                    reason_codes.append(DecisionReasonCode.DENIED_APPROVAL_EXPIRED)
                    violated_constraints.append("APPROVAL_RECORD_EXPIRED")
                elif (
                    approval_record.bound_merchant_id != merchant.id
                    or approval_record.bound_amount_minor != amount
                    or approval_record.bound_quote_hash != quote.quote_hash
                ):
                    reason_codes.append(DecisionReasonCode.DENIED_APPROVAL_MISMATCH)
                    violated_constraints.append("APPROVAL_RECORD_MISMATCH")
                elif approval_record.status == ApprovalStatus.REJECTED:
                    reason_codes.append(DecisionReasonCode.DENIED_APPROVAL_MISMATCH)
                    violated_constraints.append("APPROVAL_RECORD_REJECTED")
                elif approval_record.status in (ApprovalStatus.APPROVED, ApprovalStatus.CONSUMED):
                    pass
                else:
                    reason_codes.append(DecisionReasonCode.ESCALATED_REQUIRES_HUMAN_APPROVAL)
                    violated_constraints.append("APPROVAL_RECORD_PENDING")
        elif escalate_unknown:
            reason_codes.append(DecisionReasonCode.ESCALATED_UNKNOWN_MERCHANT)
            violated_constraints.append("UNKNOWN_MERCHANT_ESCALATION")

    # 6. Outcome resolution
    has_denied = any(code.value.startswith("DENIED_") for code in reason_codes)
    has_escalated = any(code.value.startswith("ESCALATED_") for code in reason_codes)

    if has_denied:
        outcome = DecisionOutcome.DENY
    elif has_escalated:
        outcome = DecisionOutcome.ESCALATE
    else:
        outcome = DecisionOutcome.ALLOW
        reason_codes = [DecisionReasonCode.OK_WITHIN_POLICY]

    return outcome, reason_codes, violated_constraints


class PolicyTimeMachine:
    """Forensic policy & authorization replay engine."""

    # Explicitly forbidden side-effect methods to guarantee read-only execution
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
    def replay(cls, request: ReplayRequest) -> ReplayResult:
        """Deterministically replay a transaction, recomputing policy, provenance, and timeline."""
        # 1. Enforce tenancy & verify provenance, event hash-chain, evidence integrity
        integrity_valid, missing_evidence, integrity_errors = verify_provenance_and_integrity(request)

        # 2. Reconstruct deterministic event timeline
        timeline = build_timeline(request.events, request.evidence_records)

        # 3. Deterministically recompute policy outcome (applying counterfactual overrides if set)
        eval_time = request.evaluation_time or request.recorded_decision.decided_at
        proposal_to_eval = request.proposal
        quote_to_eval = request.quote_snapshot
        passport_to_eval = request.recorded_passport
        merchant_to_eval = request.recorded_merchant

        if request.counterfactual_overrides:
            co = request.counterfactual_overrides
            passport_updates: dict[str, Any] = {}
            if "per_tx_limit_minor" in co:
                passport_updates["per_tx_limit_minor"] = int(co["per_tx_limit_minor"])
            if "total_budget_minor" in co:
                passport_updates["total_budget_minor"] = int(co["total_budget_minor"])
            if "daily_limit_minor" in co:
                passport_updates["daily_limit_minor"] = int(co["daily_limit_minor"])
            if "allowed_merchant_ids" in co:
                passport_updates["allowed_merchant_ids"] = [
                    m if isinstance(m, UUID) else UUID(str(m)) for m in co["allowed_merchant_ids"]
                ]
            if "allowed_categories" in co:
                passport_updates["allowed_categories"] = list(co["allowed_categories"])
            if "allow_unknown_merchants" in co:
                passport_updates["allow_unknown_merchants"] = bool(co["allow_unknown_merchants"])
            if "human_approval_threshold_minor" in co:
                passport_updates["human_approval_threshold_minor"] = int(co["human_approval_threshold_minor"])
            if "passport_status" in co:
                raw_st = co["passport_status"]
                passport_updates["status"] = raw_st if isinstance(raw_st, PassportStatus) else PassportStatus(str(raw_st))
            if "expires_at" in co:
                raw_exp = co["expires_at"]
                passport_updates["expires_at"] = (
                    datetime.fromisoformat(raw_exp) if isinstance(raw_exp, str) else raw_exp
                )
            if passport_updates:
                passport_to_eval = passport_to_eval.model_copy(update=passport_updates)

            if "merchant_override" in co:
                m_val = co["merchant_override"]
                if isinstance(m_val, Merchant):
                    merchant_to_eval = m_val
                elif isinstance(m_val, dict):
                    merchant_to_eval = merchant_to_eval.model_copy(update=m_val)
                elif isinstance(m_val, UUID):
                    merchant_to_eval = merchant_to_eval.model_copy(update={"id": m_val})
                else:
                    merchant_to_eval = merchant_to_eval.model_copy(update={"id": UUID(str(m_val))})

            if "amount_override_minor" in co:
                new_amt = int(co["amount_override_minor"])
                proposal_to_eval = proposal_to_eval.model_copy(update={"amount_minor": new_amt})
                new_qh = compute_quote_hash(
                    merchant_id=quote_to_eval.merchant_id,
                    amount_minor=new_amt,
                    currency=quote_to_eval.currency,
                    line_items=quote_to_eval.line_items,
                )
                quote_to_eval = quote_to_eval.model_copy(update={"amount_minor": new_amt, "quote_hash": new_qh})

        recomputed_outcome, recomputed_reasons, new_violated_constraints = evaluate_deterministic_policy(
            proposal=proposal_to_eval,
            quote=quote_to_eval,
            passport=passport_to_eval,
            merchant=merchant_to_eval,
            approval_record=request.approval_record,
            evaluation_time=eval_time,
        )

        original_decision = request.recorded_decision
        original_outcome = original_decision.outcome
        original_reasons = original_decision.reason_codes

        # 4. Check authorization drift
        outcome_changed = (recomputed_outcome != original_outcome)
        reasons_changed = (set(recomputed_reasons) != set(original_reasons))
        drift_detected = outcome_changed or reasons_changed

        # 5. Compute changed constraints
        changed_constraints: list[str] = []
        if outcome_changed:
            changed_constraints.append(f"OUTCOME_CHANGED: {original_outcome.value} -> {recomputed_outcome.value}")
        for c in new_violated_constraints:
            if c not in original_decision.violated_constraints:
                changed_constraints.append(f"VIOLATED_CONSTRAINT: {c}")
        for code in recomputed_reasons:
            if code not in original_reasons:
                changed_constraints.append(f"NEW_REASON_CODE: {code.value}")

        # 6. Detect anomalies
        anomalies = detect_anomalies(
            request,
            timeline,
        )

        # 7. Determine consistency status
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
            f"Replay evaluated policy {request.policy_version}. "
            f"Outcome: {recomputed_outcome.value} (Original: {original_outcome.value}). "
            f"Status: {consistency_status}."
        )

        evidence_refs = [e.id for e in request.evidence_records]

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
            evidence_references=evidence_refs,
            missing_evidence=missing_evidence + integrity_errors,
            anomalies=anomalies,
            integrity_valid=integrity_valid,
            consistency_status=consistency_status,
            executed_payment=False,  # Hard non-negotiable invariant
        )

    @classmethod
    def replay_trace(
        cls,
        trace: PaymentTrace,
        policy: CounterfactualPolicy | None = None,
    ) -> ReplayResult:
        """Replay a trace object under an optional counterfactual policy."""
        overrides = policy.to_overrides_dict() if policy else {}

        if not trace.recorded_passport or not trace.recorded_decision or not trace.quote_snapshot or not trace.recorded_merchant:
            return ReplayResult(
                tenant_id=trace.tenant_id,
                correlation_id=trace.payment_intent_id,
                payment_intent_id=trace.payment_intent_id,
                policy_version=trace.policy_version,
                original_outcome=DecisionOutcome.DENY,
                recomputed_outcome=DecisionOutcome.DENY,
                drift_detected=False,
                explanation="Missing historical state: INSUFFICIENT_EVIDENCE to replay trace",
                missing_evidence=trace.missing_evidence or ["INSUFFICIENT_EVIDENCE"],
                integrity_valid=False,
                consistency_status="INCOMPLETE_EVIDENCE",
                executed_payment=False,
            )

        req = ReplayRequest(
            tenant_id=trace.tenant_id,
            correlation_id=trace.payment_intent_id,
            payment_intent=trace.payment_intent or trace.recorded_decision.model_dump(),  # type: ignore[arg-type]
            proposal=trace.quote_snapshot.model_dump(),  # type: ignore[arg-type]
            quote_snapshot=trace.quote_snapshot,
            recorded_passport=trace.recorded_passport,
            recorded_merchant=trace.recorded_merchant,
            recorded_decision=trace.recorded_decision,
            approval_record=trace.approval_record,
            policy_version=trace.policy_version,
            events=trace.ordered_events,
            evidence_records=trace.authorization_evidence,
            counterfactual_overrides=overrides,
        )
        return cls.replay(req)


# Alias for backward compatibility
ReplayEngine = PolicyTimeMachine

