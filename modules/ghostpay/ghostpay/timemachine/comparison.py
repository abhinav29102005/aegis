"""Policy comparison engine for Policy Time Machine."""

from __future__ import annotations

from typing import Any
from uuid import UUID, uuid4

from contracts import DecisionOutcome, ReplayRequest, ReplayResult
from ghostpay.timemachine.policies import CounterfactualPolicy
from ghostpay.timemachine.replay import PolicyTimeMachine
from pydantic import BaseModel, Field


class PolicyComparisonEntry(BaseModel):
    policy_name: str
    outcome: DecisionOutcome
    outcome_changed: bool
    recomputed_reason_codes: list[str]
    changed_constraints: list[str]
    applied_overrides: dict[str, Any]


class PolicyComparisonReport(BaseModel):
    comparison_id: UUID = Field(default_factory=uuid4)
    tenant_id: UUID
    payment_intent_id: UUID
    original_outcome: DecisionOutcome
    results: list[PolicyComparisonEntry] = Field(default_factory=list)


def compare_policies(
    request: ReplayRequest,
    policies: list[CounterfactualPolicy],
) -> PolicyComparisonReport:
    """Compare multiple counterfactual policies against a single transaction trace."""
    entries: list[PolicyComparisonEntry] = []
    orig_outcome = request.recorded_decision.outcome

    for pol in policies:
        overrides = pol.to_overrides_dict()
        pol_req = request.model_copy(update={"counterfactual_overrides": overrides})
        res: ReplayResult = PolicyTimeMachine.replay(pol_req)

        entries.append(
            PolicyComparisonEntry(
                policy_name=pol.name,
                outcome=res.recomputed_outcome,
                outcome_changed=(res.recomputed_outcome != orig_outcome),
                recomputed_reason_codes=[rc.value for rc in res.recomputed_reason_codes],
                changed_constraints=res.changed_constraints,
                applied_overrides=overrides,
            )
        )

    return PolicyComparisonReport(
        tenant_id=request.tenant_id,
        payment_intent_id=request.payment_intent.id,
        original_outcome=orig_outcome,
        results=entries,
    )
