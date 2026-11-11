"""Human-interpretable anomaly explanations generator."""

from __future__ import annotations

from ghostpay.agentdna.detector import AgentDNAAnomalyResult


def format_agent_dna_explanation(result: AgentDNAAnomalyResult) -> str:
    """Format an interpretable summary of Agent DNA behavioral evaluation."""
    if result.status == "INSUFFICIENT_HISTORY":
        return "Agent DNA: Insufficient historical transactions to establish a reliable baseline. (Score: 0.0)"

    if not result.is_anomaly:
        return f"Agent DNA: Normal transaction behavior. Conforms with historical baseline. (Score: {result.anomaly_score})"

    lines = [
        f"Agent DNA: Behavioral anomaly detected (Anomaly Score: {result.anomaly_score}).",
        "Signals Observed:",
    ]
    for sig in result.signals:
        lines.append(f" - [{sig.get('signal_type')}]: {sig}")

    lines.append(f"Authority Note: {result.authorization_note}")
    return "\n".join(lines)
