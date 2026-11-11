"""Safeguard recommendations generator for Policy Time Machine."""

from __future__ import annotations

from contracts import DecisionOutcome, DecisionReasonCode, ReplayResult


def generate_safeguard_recommendations(result: ReplayResult) -> list[str]:
    """Generate minimal safeguard recommendations from observed policy violations and anomalies."""
    recommendations: list[str] = []

    # Check reason codes
    for code in result.recomputed_reason_codes:
        if code == DecisionReasonCode.DENIED_EXCEEDS_PER_TX_LIMIT:
            recommendations.append(
                "Consider enforcing a lower per-transaction limit or tiered approvals for this agent role."
            )
        elif code == DecisionReasonCode.DENIED_MERCHANT_NOT_ALLOWLISTED:
            recommendations.append(
                "Keep unknown merchants disallowed or restrict to human escalation (allow_unknown_merchants=True with threshold=0)."
            )
        elif code == DecisionReasonCode.DENIED_CATEGORY_NOT_ALLOWED:
            recommendations.append(
                "Ensure strict spending passport merchant category allowlists are maintained."
            )
        elif code == DecisionReasonCode.DENIED_APPROVAL_MISMATCH:
            recommendations.append(
                "Cryptographic quote binding detected tampering: enforce immutable quote snapshot verification."
            )

    # Check anomalies
    for anomaly in result.anomalies:
        if "HIGH_RISK_AMOUNT" in anomaly:
            recommendations.append(
                "High-value threshold reached: require multi-party dual human approval above $1,000.00."
            )
        elif "UNCERTAIN_PROVIDER_STATE" in anomaly:
            recommendations.append(
                "Capture provider timeout detected: ensure automated reconciliation runs every 5 minutes."
            )

    if not recommendations:
        if result.recomputed_outcome == DecisionOutcome.ALLOW:
            recommendations.append("Transaction is within policy limits. No additional safeguards required.")
        else:
            recommendations.append("Review agent spending passport configuration and audit logs.")

    return recommendations

