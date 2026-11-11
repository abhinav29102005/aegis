"""Transparent Agent DNA anomaly detector."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any
from uuid import UUID

from ghostpay.agentdna.profiles import AgentBehaviorProfile
from pydantic import BaseModel, Field

if TYPE_CHECKING:
    from ghostpay.domain.models import PaymentTrace


class AgentDNAAnomalyResult(BaseModel):
    """Interpretable Agent DNA anomaly detection report."""

    agent_id: UUID
    is_anomaly: bool
    anomaly_score: float = Field(ge=0.0, le=1.0)
    status: str = Field(pattern=r"^(NORMAL|ANOMALY_DETECTED|INSUFFICIENT_HISTORY)$")
    signals: list[dict[str, Any]] = Field(default_factory=list)
    explanations: list[str] = Field(default_factory=list)
    authorization_note: str = Field(
        default="Authorization: No change. Guardian remains authoritative."
    )


class AgentDNADetector:
    """Interpretable, statistical baseline anomaly detector for agent purchasing behaviors."""

    def __init__(self, min_samples: int = 3) -> None:
        self.min_samples = min_samples

    def detect(
        self,
        profile: AgentBehaviorProfile,
        target_trace: PaymentTrace,
    ) -> AgentDNAAnomalyResult:
        """Evaluate target_trace against the historical baseline profile."""
        agent_id = target_trace.agent_id

        # 1. Cold-start check
        if profile.sample_count < self.min_samples:
            return AgentDNAAnomalyResult(
                agent_id=agent_id,
                is_anomaly=False,
                anomaly_score=0.0,
                status="INSUFFICIENT_HISTORY",
                signals=[],
                explanations=[
                    f"Agent {agent_id} has {profile.sample_count} historical observations "
                    f"(minimum required: {self.min_samples}). Baseline status: INSUFFICIENT_HISTORY."
                ],
            )

        signals: list[dict[str, Any]] = []
        explanations: list[str] = []
        score_components: list[float] = []

        # 2. Extract target parameters
        target_amt = 0
        if target_trace.quote_snapshot:
            target_amt = target_trace.quote_snapshot.amount_minor
        elif target_trace.payment_intent:
            target_amt = target_trace.payment_intent.amount_minor

        target_merchant_id = (
            str(target_trace.recorded_merchant.id)
            if target_trace.recorded_merchant
            else (str(target_trace.quote_snapshot.merchant_id) if target_trace.quote_snapshot else "unknown")
        )

        base_stats = profile.baseline_stats
        mean_amt = base_stats.get("mean_amount_minor", 0)
        max_amt = base_stats.get("max_amount_minor", 0)
        std_amt = base_stats.get("std_amount_minor", 0.0)

        # 3. Merchant Novelty Signal
        if target_merchant_id not in profile.merchant_distribution:
            signals.append({
                "signal_type": "MERCHANT_NOVELTY",
                "observed_merchant": target_merchant_id,
                "historical_merchants": list(profile.merchant_distribution.keys()),
                "severity": 0.4,
            })
            explanations.append(
                f"Agent DNA anomaly: Merchant novelty detected. "
                f"Merchant '{target_merchant_id}' has not been seen in the historical baseline set."
            )
            score_components.append(0.4)

        # 4. Amount Inflation Signal
        if max_amt > 0 and target_amt > max_amt * 1.5:
            deviation_factor = round(target_amt / max_amt, 2)
            signals.append({
                "signal_type": "AMOUNT_DEVIATION",
                "observed_amount_minor": target_amt,
                "historical_max_minor": max_amt,
                "historical_mean_minor": mean_amt,
                "deviation_factor": deviation_factor,
                "severity": 0.6,
            })
            explanations.append(
                f"Agent DNA anomaly: Abnormally large transaction detected. "
                f"Observed amount ({target_amt} minor) is {deviation_factor}x greater than historical max ({max_amt} minor)."
            )
            score_components.append(0.6)
        elif std_amt > 0 and (target_amt - mean_amt) > 3 * std_amt:
            signals.append({
                "signal_type": "AMOUNT_STATISTICAL_OUTLIER",
                "observed_amount_minor": target_amt,
                "mean": mean_amt,
                "std": std_amt,
                "severity": 0.5,
            })
            explanations.append(
                f"Agent DNA anomaly: Amount ({target_amt} minor) exceeds 3 standard deviations above baseline mean ({mean_amt} minor)."
            )
            score_components.append(0.5)

        # 5. Repeated Policy Denial Warning Signal
        denial_rate = base_stats.get("policy_denial_rate", 0.0)
        is_target_denied = (
            target_trace.recorded_decision is not None
            and target_trace.recorded_decision.outcome.value == "DENY"
        )
        if is_target_denied and denial_rate >= 0.5:
            signals.append({
                "signal_type": "REPEATED_POLICY_DENIALS",
                "historical_denial_rate": denial_rate,
                "severity": 0.5,
            })
            explanations.append(
                f"Agent DNA warning: Repeated policy denials detected. "
                f"Agent has an elevated historical denial rate of {denial_rate * 100:.1f}%."
            )
            score_components.append(0.5)

        # Calculate final anomaly score (capped at 1.0)
        total_score = min(1.0, sum(score_components))
        is_anomaly = total_score >= 0.4

        status = "ANOMALY_DETECTED" if is_anomaly else "NORMAL"

        return AgentDNAAnomalyResult(
            agent_id=agent_id,
            is_anomaly=is_anomaly,
            anomaly_score=round(total_score, 2),
            status=status,
            signals=signals,
            explanations=explanations,
        )
