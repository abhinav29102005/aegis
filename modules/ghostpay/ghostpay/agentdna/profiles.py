"""Agent DNA behavioral profile construction."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any
from uuid import UUID

from contracts import compute_payload_hash
from pydantic import BaseModel, Field, field_validator

from ghostpay.agentdna.features import extract_agent_features
from ghostpay.domain.exceptions import CrossTenantAccessError

if TYPE_CHECKING:
    from ghostpay.domain.models import PaymentTrace


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _normalize_utc(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    return dt.astimezone(UTC) if dt.tzinfo else dt.replace(tzinfo=UTC)


class AgentBehaviorProfile(BaseModel):
    """Interpretable, tenant-isolated behavioral profile for an autonomous purchasing agent."""

    tenant_id: UUID
    agent_id: UUID
    training_window_start: datetime
    training_window_end: datetime
    sample_count: int = Field(ge=0)
    feature_schema_version: str = Field(default="agent-dna-v1")
    baseline_stats: dict[str, Any] = Field(default_factory=dict)
    merchant_distribution: dict[str, int] = Field(default_factory=dict)
    confidence_indicators: dict[str, float] = Field(default_factory=dict)
    profile_digest: str

    @field_validator("training_window_start", "training_window_end")
    @classmethod
    def _utc_windows(cls, v: datetime) -> datetime:
        return _normalize_utc(v)  # type: ignore[return-value]


def build_agent_profile(
    tenant_id: UUID,
    agent_id: UUID,
    history: list[PaymentTrace],
    *,
    cutoff_time: datetime | None = None,
    exclude_trace_id: UUID | None = None,
) -> AgentBehaviorProfile:
    """Build a versioned, reproducible AgentBehaviorProfile strictly prior to cutoff_time."""
    norm_cutoff = _normalize_utc(cutoff_time)
    seen_trace_ids: set[UUID] = set()
    eligible_traces: list[PaymentTrace] = []

    for tr in history:
        if tr.tenant_id != tenant_id:
            raise CrossTenantAccessError(
                f"Tenant isolation breach in agent profile history: "
                f"trace {tr.trace_id} tenant {tr.tenant_id} != {tenant_id}"
            )
        if tr.agent_id != agent_id:
            continue
        if tr.trace_id in seen_trace_ids:
            continue
        seen_trace_ids.add(tr.trace_id)
        if exclude_trace_id and tr.trace_id == exclude_trace_id:
            continue
        created_utc = _normalize_utc(tr.created_at)
        if norm_cutoff is not None and created_utc is not None and created_utc >= norm_cutoff:
            continue
        eligible_traces.append(tr)

    features = extract_agent_features(
        eligible_traces,
        cutoff_time=norm_cutoff,
        exclude_trace_id=exclude_trace_id,
    )

    now = _utc_now()
    if eligible_traces:
        sorted_h = sorted(eligible_traces, key=lambda t: _normalize_utc(t.created_at) or now)
        start_time = sorted_h[0].created_at
        end_time = sorted_h[-1].created_at
    else:
        fallback_time = norm_cutoff or now
        start_time = fallback_time
        end_time = fallback_time

    baseline = {
        "mean_amount_minor": features.mean_amount_minor,
        "median_amount_minor": features.median_amount_minor,
        "std_amount_minor": round(features.std_amount_minor, 2),
        "max_amount_minor": features.max_amount_minor,
        "policy_denial_rate": features.policy_denial_rate,
        "completed_ratio": features.completed_ratio,
    }

    confidence = {
        "sample_sufficiency": min(1.0, features.sample_count / 10.0),
        "merchant_diversity": min(1.0, features.unique_merchant_count / 5.0),
    }

    digest = compute_payload_hash({
        "tenant_id": str(tenant_id),
        "agent_id": str(agent_id),
        "sample_count": features.sample_count,
        "baseline": baseline,
        "merchants": sorted(features.merchant_distribution.keys()),
    })

    return AgentBehaviorProfile(
        tenant_id=tenant_id,
        agent_id=agent_id,
        training_window_start=start_time,
        training_window_end=end_time,
        sample_count=features.sample_count,
        feature_schema_version="agent-dna-v1",
        baseline_stats=baseline,
        merchant_distribution=features.merchant_distribution,
        confidence_indicators=confidence,
        profile_digest=digest,
    )
