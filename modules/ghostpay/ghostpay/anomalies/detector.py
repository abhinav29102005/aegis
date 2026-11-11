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
    *,
    original_decision: AuthorizationDecision,
    recomputed_outcome: DecisionOutcome,
    recomputed_reason_codes: list[Any],
    integrity_errors: list[str] | None = None,
) -> list[str]:
    """Detect anomalies including merchant substitution, amount spikes, expired passports, and quote mismatches."""
    anomalies: list[str] = []

    proposal = request.proposal
    quote = request.quote_snapshot
    passport = request.recorded_passport
    merchant = request.recorded_merchant
    intent = request.payment_intent
    eval_time = request.evaluation_time or original_decision.decided_at

    # 1. Merchant substitution detection
    if merchant.id != proposal.merchant_id:
        anomalies.append(
            f"MERCHANT_SUBSTITUTION: Recorded merchant ({merchant.id}) differs from proposal merchant ({proposal.merchant_id})."
        )
    if merchant.id != quote.merchant_id:
        anomalies.append(
            f"MERCHANT_SUBSTITUTION: Recorded merchant ({merchant.id}) differs from quote merchant ({quote.merchant_id})."
        )
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
    if intent.quote_hash and quote.quote_hash and intent.quote_hash != quote.quote_hash:
        anomalies.append(
            f"QUOTE_MISMATCH: Payment intent quote hash ({intent.quote_hash}) does not match quote snapshot ({quote.quote_hash})."
        )
    if original_decision.quote_hash and quote.quote_hash and original_decision.quote_hash != quote.quote_hash:
        anomalies.append(
            f"QUOTE_MISMATCH: Original authorization decision quote hash ({original_decision.quote_hash}) does not match quote snapshot ({quote.quote_hash})."
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
    if original_decision.outcome != recomputed_outcome:
        anomalies.append(
            f"AUTHORIZATION_DRIFT: Decision outcome drifted from {original_decision.outcome.value} to {recomputed_outcome.value}."
        )
    elif set(original_decision.reason_codes) != set(recomputed_reason_codes):
        anomalies.append(
            f"AUTHORIZATION_DRIFT: Reason codes changed from {[r.value for r in original_decision.reason_codes]} to {[r.value for r in recomputed_reason_codes]}."
        )

    # 6. Integrity failure anomalies
    if integrity_errors:
        for err in integrity_errors:
            anomalies.append(f"INTEGRITY_VIOLATION: {err}")

    return anomalies
