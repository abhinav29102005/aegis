"""Domain exceptions for AgentPay Guardian."""

from __future__ import annotations


class GuardianError(RuntimeError):
    """Base class for all Guardian domain errors."""


class PolicyDeniedError(GuardianError):
    """Raised when the deterministic policy engine denies a purchase proposal."""

    def __init__(self, message: str, reason_codes: list[str] | None = None) -> None:
        super().__init__(message)
        self.reason_codes: list[str] = reason_codes or []


class ApprovalExpiredError(GuardianError):
    """Raised when a human approval has expired before it was consumed."""


class ApprovalMismatchError(GuardianError):
    """Raised when an approval's bound merchant, amount, or quote hash no longer matches."""


class DuplicateIntentError(GuardianError):
    """Raised when an idempotency key is reused with a different payload."""


class IntentNotFoundError(GuardianError):
    """Raised when a PaymentIntent cannot be found by ID."""


class AttemptNotFoundError(GuardianError):
    """Raised when a PaymentAttempt cannot be found by ID."""


class InvalidStateTransitionError(GuardianError):
    """Raised when a requested payment state transition is illegal."""


class InsufficientBudgetError(GuardianError):
    """Raised when budget reservation fails due to insufficient available funds."""


class ApprovalNotFoundError(GuardianError):
    """Raised when an ApprovalRecord cannot be found."""

