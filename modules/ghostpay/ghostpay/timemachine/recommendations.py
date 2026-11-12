"""Safeguard recommendations generator harmonized with GhostPay anomaly and reason codes."""

from __future__ import annotations

from contracts import DecisionOutcome, DecisionReasonCode, ReplayResult

_REASON_RECOMMENDATIONS: dict[DecisionReasonCode, str] = {
    DecisionReasonCode.DENIED_EXCEEDS_PER_TX_LIMIT: (
        "Consider enforcing a lower per-transaction limit or tiered approvals for this agent role."
    ),
    DecisionReasonCode.DENIED_EXCEEDS_PASSPORT_BUDGET: (
        "Enforce stricter remaining passport budget reservations or top-up governance."
    ),
    DecisionReasonCode.DENIED_INSUFFICIENT_BUDGET: (
        "Enforce stricter remaining passport budget reservations or top-up governance."
    ),
    DecisionReasonCode.DENIED_EXCEEDS_DAILY_LIMIT: (
        "Review agent daily velocity caps and split high-frequency purchasing schedules."
    ),
    DecisionReasonCode.DENIED_MONTHLY_LIMIT: (
        "Review agent monthly budget allocations and require CFO approval for cap increases."
    ),
    DecisionReasonCode.DENIED_MERCHANT_NOT_ALLOWLISTED: (
        "Keep unknown merchants disallowed or restrict to human escalation (allow_unknown_merchants=True with threshold=0)."
    ),
    DecisionReasonCode.DENIED_CATEGORY_NOT_ALLOWED: (
        "Ensure strict spending passport merchant category allowlists are maintained."
    ),
    DecisionReasonCode.DENIED_CURRENCY_NOT_ALLOWED: (
        "Restrict proposal currencies to the passport's explicitly allowed ISO currency list."
    ),
    DecisionReasonCode.DENIED_APPROVAL_MISMATCH: (
        "Cryptographic quote or approval binding detected mismatch: enforce immutable quote snapshot verification."
    ),
    DecisionReasonCode.DENIED_APPROVAL_EXPIRED: (
        "Shorten approval SLA windows or require fresh human re-approval on expired authorizations."
    ),
    DecisionReasonCode.DENIED_QUOTE_EXPIRED: (
        "Refresh merchant quote snapshots before checkout when authorization latency exceeds quote TTL."
    ),
    DecisionReasonCode.DENIED_PASSPORT_EXPIRED: (
        "Rotate expired spending passports and block stale agent credentials automatically."
    ),
    DecisionReasonCode.DENIED_PASSPORT_REVOKED: (
        "Revoke active agent sessions immediately when a spending passport is revoked."
    ),
    DecisionReasonCode.DENIED_PASSPORT_PAUSED: (
        "Keep agent transactions blocked while the spending passport remains paused."
    ),
    DecisionReasonCode.DENIED_AGENT_SUSPENDED: (
        "Audit agent identity status transitions before re-enabling autonomous purchasing."
    ),
}

_ANOMALY_RECOMMENDATIONS: list[tuple[str, str]] = [
    (
        "MERCHANT_SUBSTITUTION",
        "Merchant mismatch or unapproved substitution detected: bind quote and merchant IDs before execution.",
    ),
    (
        "AMOUNT_SPIKE",
        "Transaction amount exceeded passport limits: tighten per-transaction caps and human approval thresholds.",
    ),
    (
        "HIGH_RISK_AMOUNT",
        "High-value threshold reached: require multi-party dual human approval above $1,000.00.",
    ),
    (
        "EXPIRED_PASSPORT",
        "Expired passport activity detected: enforce strict pre-checkout passport expiry gates.",
    ),
    (
        "REVOKED_PASSPORT",
        "Revoked passport activity detected: terminate agent credentials and audit recent traces.",
    ),
    (
        "PAUSED_PASSPORT",
        "Paused passport activity detected: verify operator pause controls are enforced prior to checkout.",
    ),
    (
        "QUOTE_MISMATCH",
        "Quote snapshot tampering or drift detected: require strict quote_hash verification across all stages.",
    ),
    (
        "CURRENCY_MISMATCH",
        "Currency mismatch detected: lock currency allowlists at passport issuance.",
    ),
    (
        "EXECUTION_DESPITE_DENY",
        "CRITICAL: Payment execution occurred despite DENY decision; audit checkout coordinator gates immediately.",
    ),
    (
        "UNCERTAIN_PROVIDER_STATE",
        "Capture provider timeout detected: ensure automated reconciliation runs every 5 minutes.",
    ),
    (
        "PAYMENT_EXECUTION_FAILED",
        "Payment execution failure recorded: verify budget holds were cleanly released.",
    ),
    (
        "AUTHORIZATION_DRIFT",
        "Authorization drift detected between recorded and replayed outcomes: inspect policy version snapshots.",
    ),
    (
        "POLICY_VERSION_MISMATCH",
        "Policy version mismatch detected: archive immutable policy version rules alongside decisions.",
    ),
    (
        "INTEGRITY_VIOLATION",
        "Cryptographic provenance or hash-chain integrity failure detected: quarantine trace for forensic audit.",
    ),
]


def generate_safeguard_recommendations(result: ReplayResult) -> list[str]:
    """Generate deterministic safeguard recommendations from policy reason codes and harmonized anomalies."""
    recommendations: list[str] = []

    for code in result.recomputed_reason_codes:
        rec = _REASON_RECOMMENDATIONS.get(code)
        if rec:
            recommendations.append(rec)

    for anomaly in result.anomalies:
        for prefix, rec in _ANOMALY_RECOMMENDATIONS:
            if anomaly.startswith(prefix) or prefix in anomaly:
                recommendations.append(rec)

    if not recommendations:
        if result.recomputed_outcome == DecisionOutcome.ALLOW:
            recommendations.append("Transaction is within policy limits. No additional safeguards required.")
        else:
            recommendations.append("Review agent spending passport configuration and audit logs.")

    return list(dict.fromkeys(recommendations))
