"""Explicit policy version registry for deterministic GhostPay replay."""

from __future__ import annotations

from collections.abc import Callable

from contracts import (
    DecisionOutcome,
    DecisionReasonCode,
)

from ghostpay.errors import UnsupportedPolicyVersionError

PolicyEvaluator = Callable[
    ...,
    tuple[DecisionOutcome, list[DecisionReasonCode], list[str]],
]

DEFAULT_POLICY_VERSION = "policy-v1"
SUPPORTED_POLICY_VERSIONS: tuple[str, ...] = (DEFAULT_POLICY_VERSION,)

_POLICY_REGISTRY: dict[str, PolicyEvaluator] = {}


def register_policy_evaluator(version: str, evaluator: PolicyEvaluator) -> None:
    """Register a concrete, deterministic policy evaluator for an explicit version identifier."""
    normalized = version.strip()
    if not normalized:
        raise ValueError("Policy version identifier cannot be empty.")
    _POLICY_REGISTRY[normalized] = evaluator


def get_registered_policy_versions() -> tuple[str, ...]:
    """Return registered supported policy versions in stable order."""
    return tuple(sorted(_POLICY_REGISTRY.keys()))


def resolve_policy_evaluator(policy_version: str) -> tuple[str, PolicyEvaluator]:
    """Resolve an exact registered policy evaluator or fail closed."""
    if not isinstance(policy_version, str) or not policy_version.strip():
        raise UnsupportedPolicyVersionError(
            str(policy_version),
            get_registered_policy_versions() or SUPPORTED_POLICY_VERSIONS,
        )
    normalized = policy_version.strip()
    evaluator = _POLICY_REGISTRY.get(normalized)
    if evaluator is None:
        raise UnsupportedPolicyVersionError(
            normalized,
            get_registered_policy_versions() or SUPPORTED_POLICY_VERSIONS,
        )
    return normalized, evaluator
