"""Policy Time Machine package for GhostPay."""

from ghostpay.replay.engine import (
    ReplayEngine,
    evaluate_deterministic_policy,
)
from ghostpay.timemachine.comparison import (
    PolicyComparisonEntry,
    PolicyComparisonReport,
    compare_policies,
)
from ghostpay.timemachine.policies import CounterfactualPolicy
from ghostpay.timemachine.recommendations import generate_safeguard_recommendations

PolicyTimeMachine = ReplayEngine

__all__ = [
    "CounterfactualPolicy",
    "PolicyTimeMachine",
    "ReplayEngine",
    "evaluate_deterministic_policy",
    "PolicyComparisonEntry",
    "PolicyComparisonReport",
    "compare_policies",
    "generate_safeguard_recommendations",
]
