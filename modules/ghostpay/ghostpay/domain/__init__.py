"""GhostPay domain package."""

from typing import TYPE_CHECKING

from ghostpay.domain.exceptions import (
    CrossTenantAccessError,
    GhostPayError,
    IllegalSideEffectError,
    InsufficientEvidenceError,
    InsufficientHistoryError,
    IntegrityError,
    InvestigationNotFoundError,
    MissingEvidenceError,
    TraceNotFoundError,
)
from ghostpay.domain.models import InvestigationReport, PaymentTrace

if TYPE_CHECKING:
    from ghostpay.domain.service import GhostPayService

__all__ = [
    "GhostPayError",
    "IntegrityError",
    "MissingEvidenceError",
    "InsufficientEvidenceError",
    "InsufficientHistoryError",
    "CrossTenantAccessError",
    "IllegalSideEffectError",
    "TraceNotFoundError",
    "InvestigationNotFoundError",
    "PaymentTrace",
    "InvestigationReport",
    "GhostPayService",
]


def __getattr__(name: str):
    if name == "GhostPayService":
        from ghostpay.domain.service import GhostPayService
        return GhostPayService
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
