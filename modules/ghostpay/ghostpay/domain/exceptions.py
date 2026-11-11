"""Domain exceptions for GhostPay."""

from __future__ import annotations


class GhostPayError(Exception):
    """Base exception for all GhostPay domain errors."""


class IntegrityError(GhostPayError):
    """Raised when financial event chain, quote hash, or payload integrity is violated."""


class MissingEvidenceError(GhostPayError):
    """Raised when essential historical context or evidence is missing."""


class InsufficientHistoryError(GhostPayError):
    """Raised when insufficient historical observations exist for Agent DNA baseline."""


class CrossTenantAccessError(GhostPayError, PermissionError):
    """Raised when cross-tenant trace or evidence access is attempted."""


class IllegalSideEffectError(GhostPayError, PermissionError):
    """Raised when a replay or forensic operation attempts payment execution or ledger mutation."""


class TraceNotFoundError(GhostPayError):
    """Raised when a payment trace is not found."""


class InvestigationNotFoundError(GhostPayError):
    """Raised when an investigation report is not found."""
