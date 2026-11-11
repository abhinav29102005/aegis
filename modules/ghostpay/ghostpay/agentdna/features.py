"""Agent DNA feature extraction with strict data-leakage prevention."""

from __future__ import annotations

import math
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any
from uuid import UUID

from pydantic import BaseModel, Field

if TYPE_CHECKING:
    from ghostpay.domain.models import PaymentTrace


class AgentFeatureVector(BaseModel):
    """Deterministic behavioral feature vector for an autonomous agent."""

    agent_id: UUID
    sample_count: int = Field(ge=0)
    mean_amount_minor: int = Field(default=0, ge=0)
    median_amount_minor: int = Field(default=0, ge=0)
    std_amount_minor: float = Field(default=0.0, ge=0.0)
    max_amount_minor: int = Field(default=0, ge=0)
    total_spent_minor: int = Field(default=0, ge=0)
    unique_merchant_count: int = Field(default=0, ge=0)
    merchant_distribution: dict[str, int] = Field(default_factory=dict)
    policy_denial_count: int = Field(default=0, ge=0)
    policy_denial_rate: float = Field(default=0.0, ge=0.0, le=1.0)
    approval_request_count: int = Field(default=0, ge=0)
    completed_ratio: float = Field(default=0.0, ge=0.0, le=1.0)


def extract_agent_features(
    history: list[PaymentTrace],
    *,
    cutoff_time: datetime | None = None,
    exclude_trace_id: UUID | None = None,
) -> AgentFeatureVector:
    """Extract chronological features strictly prior to cutoff_time to prevent data leakage."""
    # 1. Filter history chronologically
    filtered_traces: list[PaymentTrace] = []
    for tr in history:
        if exclude_trace_id and tr.trace_id == exclude_trace_id:
            continue
        if cutoff_time and tr.created_at >= cutoff_time:
            continue
        filtered_traces.append(tr)

    count = len(filtered_traces)
    if count == 0:
        agent_id = history[0].agent_id if history else UUID(int=0)
        return AgentFeatureVector(agent_id=agent_id, sample_count=0)

    agent_id = filtered_traces[0].agent_id

    # 2. Extract transaction amounts
    amounts: list[int] = []
    merchant_counts: dict[str, int] = {}
    denials = 0
    approvals = 0
    completed = 0

    for tr in filtered_traces:
        amt = 0
        if tr.quote_snapshot:
            amt = tr.quote_snapshot.amount_minor
        elif tr.payment_intent:
            amt = tr.payment_intent.amount_minor
        amounts.append(amt)

        m_id = str(tr.recorded_merchant.id) if tr.recorded_merchant else (str(tr.quote_snapshot.merchant_id) if tr.quote_snapshot else "unknown")
        merchant_counts[m_id] = merchant_counts.get(m_id, 0) + 1

        if tr.recorded_decision and tr.recorded_decision.outcome.value == "DENY":
            denials += 1

        if tr.approval_record:
            approvals += 1

        if tr.payment_intent and tr.payment_intent.state.value == "SUCCEEDED":
            completed += 1

    amounts.sort()
    total_spent = sum(amounts)
    mean_amt = total_spent // count
    median_amt = amounts[count // 2] if count % 2 != 0 else (amounts[count // 2 - 1] + amounts[count // 2]) // 2

    # Standard deviation in minor units
    variance = sum((x - mean_amt) ** 2 for x in amounts) / count
    std_amt = math.sqrt(variance)

    return AgentFeatureVector(
        agent_id=agent_id,
        sample_count=count,
        mean_amount_minor=mean_amt,
        median_amount_minor=median_amt,
        std_amount_minor=std_amt,
        max_amount_minor=amounts[-1],
        total_spent_minor=total_spent,
        unique_merchant_count=len(merchant_counts),
        merchant_distribution=merchant_counts,
        policy_denial_count=denials,
        policy_denial_rate=round(denials / count, 4),
        approval_request_count=approvals,
        completed_ratio=round(completed / count, 4),
    )
