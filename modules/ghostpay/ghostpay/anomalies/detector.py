"""Authorization drift and forensic anomaly detection for GhostPay."""

from __future__ import annotations

from typing import Any

from contracts import (
    AuthorizationDecision,
    DecisionOutcome,
    PassportStatus,
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
    """Detect anomalies including merchant substitution, amount spikes, expired passports, and quote mismatches."""
    anomalies: list[str] = []

    proposal = request.proposal
    quote = request.quote_snapshot
    passport = request.recorded_passport
    merchant = request.recorded_merchant
    intent = request.payment_intent
    orig_dec = original_decision or request.recorded_decision
    recomp_out = recomputed_outcome if recomputed_outcome is not None else (orig_dec.outcome if orig_dec else DecisionOutcome.ALLOW)
    recomp_reasons = recomputed_reason_codes if recomputed_reason_codes is not None else (orig_dec.reason_codes if orig_dec else [])
    eval_time = request.evaluation_time or (orig_dec.decided_at if orig_dec else quote.created_at)

    # 1. Merchant substitution detection
    if merchant.id != proposal.merchant_id:
        anomalies.append(
            f"MERCHANT_SUBSTITUTION: Recorded merchant ({merchant.id}) differs from proposal merchant ({proposal.merchant_id})."
        )
    if merchant.id != quote.merchant_id:
        anomalies.append(
            f"MERCHANT_SUBSTITUTION: Recorded merchant ({merchant.id}) differs from quote merchant ({quote.merchant_id})."
        )
    both_denied = (
        orig_dec is not None
        and orig_dec.outcome == DecisionOutcome.DENY
        and recomp_out == DecisionOutcome.DENY
    )

    if not both_denied:
        if merchant.id not in passport.allowed_merchant_ids and not passport.allow_unknown_merchants:
            anomalies.append(
                f"MERCHANT_SUBSTITUTION: Merchant ({merchant.id}, '{merchant.name}') is not allowlisted in passport ({passport.id})."
            )

        # 2. Amount spike detection
        if proposal.amount_minor > passport.per_tx_limit_minor:
            anomalies.append(
                f"AMOUNT_SPIKE: Amount {proposal.amount_minor} exceeds per-transaction limit of {passport.per_tx_limit_minor}."
            )
        if proposal.amount_minor > passport.available_budget_minor:
            anomalies.append(
                f"AMOUNT_SPIKE: Amount {proposal.amount_minor} exceeds passport available budget of {passport.available_budget_minor}."
            )

    # 3. Expired passport detection
    if passport.status == PassportStatus.EXPIRED:
        anomalies.append(
            f"EXPIRED_PASSPORT: Spending passport {passport.id} is marked EXPIRED."
        )
    elif eval_time > passport.expires_at:
        anomalies.append(
            f"EXPIRED_PASSPORT: Evaluation time {eval_time.isoformat()} is after passport expiration {passport.expires_at.isoformat()}."
        )
    elif passport.status == PassportStatus.REVOKED:
        anomalies.append(
            f"REVOKED_PASSPORT: Spending passport {passport.id} is REVOKED."
        )

    # 4. Quote mismatch detection
    if proposal.amount_minor != quote.amount_minor:
        anomalies.append(
            f"QUOTE_MISMATCH: Proposal amount ({proposal.amount_minor}) differs from quote snapshot amount ({quote.amount_minor})."
        )
    if proposal.currency != quote.currency:
        anomalies.append(
            f"QUOTE_MISMATCH: Proposal currency ({proposal.currency}) differs from quote currency ({quote.currency})."
        )
    if quote.currency != passport.currency:
        anomalies.append(
            f"CURRENCY_MISMATCH: Quote currency ({quote.currency}) differs from passport currency ({passport.currency})."
        )
    if intent.quote_hash and quote.quote_hash and intent.quote_hash != quote.quote_hash:
        anomalies.append(
            f"QUOTE_MISMATCH: Payment intent quote hash ({intent.quote_hash}) does not match quote snapshot ({quote.quote_hash})."
        )
    if orig_dec and orig_dec.quote_hash and quote.quote_hash and orig_dec.quote_hash != quote.quote_hash:
        anomalies.append(
            f"QUOTE_MISMATCH: Original authorization decision quote hash ({orig_dec.quote_hash}) does not match quote snapshot ({quote.quote_hash})."
        )

    # Recheck quote snapshot hash integrity
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

    # 5. Authorization drift detection
    if orig_dec:
        if orig_dec.outcome != recomp_out:
            anomalies.append(
                f"AUTHORIZATION_DRIFT: Decision outcome drifted from {orig_dec.outcome.value} to {recomp_out.value}."
            )
        elif set(orig_dec.reason_codes) != set(recomp_reasons):
            anomalies.append(
                f"AUTHORIZATION_DRIFT: Reason codes changed from {[r.value for r in orig_dec.reason_codes]} to {[r.value for r in recomp_reasons]}."
            )

    # 6. Policy version mismatch detection
    active_policy_version = executed_policy_version or request.policy_version
    if orig_dec and orig_dec.policy_version != active_policy_version:
        anomalies.append(
            f"POLICY_VERSION_MISMATCH: Replayed under '{active_policy_version}', "
            f"recorded_decision used '{orig_dec.policy_version}'."
        )
    if passport.policy_version != active_policy_version:
        anomalies.append(
            f"POLICY_VERSION_MISMATCH: Replayed under '{active_policy_version}', "
            f"recorded_passport specifies '{passport.policy_version}'."
        )

    # 7. Integrity failure anomalies
    if integrity_errors:
        for err in integrity_errors:
            anomalies.append(f"INTEGRITY_VIOLATION: {err}")

    return anomalies
