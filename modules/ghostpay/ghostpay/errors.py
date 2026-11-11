"""Domain exceptions for GhostPay forensic replay and counterfactual simulation."""

from __future__ import annotations

from typing import Any


class GhostPayError(Exception):
    """Base domain error for GhostPay."""


class OverrideValidationError(GhostPayError, ValueError):
    """Raised when counterfactual override inputs are invalid, unknown, or target immutable state."""

    def __init__(self, message: str, *, errors: list[dict[str, Any]] | None = None) -> None:
        super().__init__(message)
        self.errors: list[dict[str, Any]] = errors or []


class UnsupportedPolicyVersionError(GhostPayError, ValueError):
    """Raised when a requested policy version is not registered in the evaluator registry."""

    def __init__(
        self,
        requested_version: str,
        supported_versions: tuple[str, ...],
    ) -> None:
        self.requested_version = requested_version
        self.supported_versions = supported_versions
        super().__init__(
            f"Unsupported policy_version '{requested_version}'. "
            f"Supported policy versions: {', '.join(supported_versions)}"
        )


class ReplayExecutionForbiddenError(GhostPayError, RuntimeError):
    """Fail-closed safeguard if replay or simulation attempts non-read-only execution."""
