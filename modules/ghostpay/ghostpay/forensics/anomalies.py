"""Rule-based forensic anomaly detection across single traces and replay requests."""

from __future__ import annotations

from contracts import (
    FinancialEventType,
    PassportStatus,
    ReplayRequest,
    ReplayTimelineEntry,
)


def detect_anomalies(
    request: ReplayRequest,
    timeline: list[ReplayTimelineEntry],
) -> list[str]:
    """Detect heuristic policy anomalies, state transition inconsistencies, and risk signals."""
    anomalies: list[str] = []

    proposal = request.proposal
    passport = request.recorded_passport
    merchant = request.recorded_merchant
    decision = request.recorded_decision
    eval_time = request.evaluation_time or decision.decided_at

    # 1. Proposal amount exceeds passport per-tx limit
    if proposal.amount_minor > passport.per_tx_limit_minor:
        anomalies.append(
            f"AMOUNT_EXCEEDS_PER_TX_LIMIT: proposal {proposal.amount_minor} > limit {passport.per_tx_limit_minor}"
        )

    # 2. Proposal amount exceeds available budget
    if proposal.amount_minor > passport.available_budget_minor:
        anomalies.append(
            f"AMOUNT_EXCEEDS_BUDGET: proposal {proposal.amount_minor} > available {passport.available_budget_minor}"
        )

    # 3. High risk amount threshold
    if proposal.amount_minor >= 100000:  # >= $1,000.00
        anomalies.append(f"HIGH_RISK_AMOUNT: transaction amount {proposal.amount_minor} is high-value")

    # 4. Merchant novelty / allowlist status
    if merchant.id not in passport.allowed_merchant_ids:
        anomalies.append(f"UNAPPROVED_MERCHANT: merchant {merchant.id} ({merchant.name}) not in allowed_merchant_ids")

    # 5. Expired passport
    if passport.status == PassportStatus.EXPIRED or (passport.expires_at and eval_time > passport.expires_at):
        anomalies.append(f"EXPIRED_PASSPORT_USED: passport {passport.id} expired at {passport.expires_at.isoformat()}")

    # 6. Event timeline anomalies: missing transitions or failures
    event_types = [e.event_type for e in timeline]
    if FinancialEventType.PAYMENT_FAILED in event_types:
        anomalies.append("PAYMENT_EXECUTION_FAILED: timeline contains explicit payment failure event")

    if (
        FinancialEventType.PAYPAL_CAPTURE_REQUESTED in event_types
        and FinancialEventType.PAYPAL_CAPTURE_VERIFIED not in event_types
        and FinancialEventType.PAYMENT_FAILED not in event_types
    ):
        anomalies.append("UNCERTAIN_PROVIDER_STATE: capture requested but neither verified nor failed")

    return anomalies

