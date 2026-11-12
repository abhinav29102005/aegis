"""Authorization drift and forensic anomaly detection for GhostPay."""

from __future__ import annotations

from typing import Any

from contracts import (
    AuthorizationDecision,
    DecisionOutcome,
    FinancialEventType,
    PassportStatus,
    PaymentState,
    ReplayRequest,
    compute_quote_hash,
)


def detect_anomalies(
    request: ReplayRequest,
    timeline: Any = None,
    *,
    original_decision: AuthorizationDecision | None = None,
    recomputed_outcome: DecisionOutcome | None = None,
    recomputed_reason_codes: list[Any] | None = None,
    integrity_errors: list[str] | None = None,
    executed_policy_version: str | None = None,
) -> list[str]:
    """Detect forensic anomalies while avoiding false positives on legitimate DENY decisions."""
    anomalies: list[str] = []

    decision = original_decision or request.recorded_decision
    recomp_outcome = recomputed_outcome if recomputed_outcome is not None else decision.outcome
    recomp_reasons = (
        recomputed_reason_codes if recomputed_reason_codes is not None else decision.reason_codes
    )
    is_legitimate_deny = decision.outcome == DecisionOutcome.DENY

    proposal = request.proposal
    quote = request.quote_snapshot
    passport = request.recorded_passport
    merchant = request.recorded_merchant
    intent = request.payment_intent
    eval_time = request.evaluation_time or decision.decided_at

    # 1. Cross-artifact merchant substitution (always anomalous regardless of DENY)
    if merchant.id != proposal.merchant_id:
        anomalies.append(
            f"MERCHANT_SUBSTITUTION: Recorded merchant ({merchant.id}) differs from proposal merchant ({proposal.merchant_id})."
        )
    if merchant.id != quote.merchant_id:
        anomalies.append(
            f"MERCHANT_SUBSTITUTION: Recorded merchant ({merchant.id}) differs from quote merchant ({quote.merchant_id})."
        )
    # 2. Policy-violation anomalies (suppressed when Guardian already legitimately DENY'd)
    if not is_legitimate_deny:
        if (
            passport.allowed_merchant_ids
            and merchant.id not in passport.allowed_merchant_ids
            and not passport.allow_unknown_merchants
        ):
            anomalies.append(
                f"MERCHANT_SUBSTITUTION: Merchant ({merchant.id}, '{merchant.name}') is not allowlisted in passport ({passport.id})."
            )

        if proposal.amount_minor > passport.per_tx_limit_minor:
            anomalies.append(
                f"AMOUNT_SPIKE: Amount {proposal.amount_minor} exceeds per-transaction limit of {passport.per_tx_limit_minor}."
            )
        if proposal.amount_minor > passport.available_budget_minor:
            anomalies.append(
                f"AMOUNT_SPIKE: Amount {proposal.amount_minor} exceeds passport available budget of {passport.available_budget_minor}."
            )
        if proposal.amount_minor >= 100000:
            anomalies.append(
                f"HIGH_RISK_AMOUNT: Transaction amount {proposal.amount_minor} exceeds high-value threshold (100000 minor)."
            )

        if passport.status == PassportStatus.EXPIRED:
            anomalies.append(
                f"EXPIRED_PASSPORT: Spending passport {passport.id} is marked EXPIRED."
            )
        elif eval_time >= passport.expires_at:
            anomalies.append(
                f"EXPIRED_PASSPORT: Evaluation time {eval_time.isoformat()} is at or after passport expiration {passport.expires_at.isoformat()}."
            )
        elif passport.status == PassportStatus.REVOKED:
            anomalies.append(
                f"REVOKED_PASSPORT: Spending passport {passport.id} is REVOKED."
            )
        elif passport.status == PassportStatus.PAUSED:
            anomalies.append(
                f"PAUSED_PASSPORT: Spending passport {passport.id} is PAUSED."
            )

        allowed_currencies = (
            {c.upper() for c in passport.allowed_currencies}
            if passport.allowed_currencies
            else {passport.currency.upper()}
        )
        if quote.currency.upper() not in allowed_currencies:
            anomalies.append(
                f"CURRENCY_MISMATCH: Quote currency ({quote.currency}) is not permitted by passport ({sorted(allowed_currencies)})."
            )

    # 3. Quote mismatch & tampering detection (always anomalous)
    if proposal.amount_minor != quote.amount_minor:
        anomalies.append(
            f"QUOTE_MISMATCH: Proposal amount ({proposal.amount_minor}) differs from quote snapshot amount ({quote.amount_minor})."
        )
    if proposal.currency.upper() != quote.currency.upper():
        anomalies.append(
            f"QUOTE_MISMATCH: Proposal currency ({proposal.currency}) differs from quote currency ({quote.currency})."
        )
    if intent.quote_hash and quote.quote_hash and intent.quote_hash != quote.quote_hash:
        anomalies.append(
            f"QUOTE_MISMATCH: Payment intent quote hash ({intent.quote_hash}) does not match quote snapshot ({quote.quote_hash})."
        )
    if decision.quote_hash and quote.quote_hash and decision.quote_hash != quote.quote_hash:
        anomalies.append(
            f"QUOTE_MISMATCH: Original authorization decision quote hash ({decision.quote_hash}) does not match quote snapshot ({quote.quote_hash})."
        )

    computed_q_hash = compute_quote_hash(
        merchant_id=quote.merchant_id,
        amount_minor=quote.amount_minor,
        currency=quote.currency,
        line_items=quote.line_items,
    )
    if computed_q_hash != quote.quote_hash:
        anomalies.append(
            f"QUOTE_MISMATCH: Quote snapshot hash {quote.quote_hash} does not match computed hash {computed_q_hash}."
        )

    # 4. Execution despite DENY check
    event_types = [ev.event_type for ev in request.events]
    if is_legitimate_deny and (
        intent.state == PaymentState.SUCCEEDED
        or FinancialEventType.PAYPAL_CAPTURE_VERIFIED in event_types
    ):
        anomalies.append(
            "EXECUTION_DESPITE_DENY: Payment completed or captured despite DENY authorization decision."
        )

    # 5. Execution & provider timeline anomalies (non-DENY)
    if not is_legitimate_deny:
        if FinancialEventType.PAYMENT_FAILED in event_types:
            anomalies.append(
                "PAYMENT_EXECUTION_FAILED: Timeline contains explicit payment failure event."
            )
        if (
            FinancialEventType.PAYPAL_CAPTURE_REQUESTED in event_types
            and FinancialEventType.PAYPAL_CAPTURE_VERIFIED not in event_types
            and FinancialEventType.PAYMENT_FAILED not in event_types
        ):
            anomalies.append(
                "UNCERTAIN_PROVIDER_STATE: Capture requested but neither verified nor failed."
            )

    # 6. Authorization drift detection
    if decision.outcome != recomp_outcome:
        anomalies.append(
            f"AUTHORIZATION_DRIFT: Decision outcome drifted from {decision.outcome.value} to {recomp_outcome.value}."
        )
    elif set(decision.reason_codes) != set(recomp_reasons):
        anomalies.append(
            f"AUTHORIZATION_DRIFT: Reason codes changed from {[r.value for r in decision.reason_codes]} to {[r.value for r in recomp_reasons]}."
        )

    # 7. Policy version mismatch detection
    active_policy_version = executed_policy_version or request.policy_version
    if decision.policy_version != active_policy_version:
        anomalies.append(
            f"POLICY_VERSION_MISMATCH: Replayed under '{active_policy_version}', "
            f"recorded_decision used '{decision.policy_version}'."
        )
    if passport.policy_version != active_policy_version:
        anomalies.append(
            f"POLICY_VERSION_MISMATCH: Replayed under '{active_policy_version}', "
            f"recorded_passport specifies '{passport.policy_version}'."
        )

    # 8. Integrity failure anomalies
    if integrity_errors:
        for err in integrity_errors:
            anomalies.append(f"INTEGRITY_VIOLATION: {err}")

    return anomalies
