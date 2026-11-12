"""Dispute case lifecycle service and fail-closed submission gates."""

from disputeos.cases.service import (
    ApprovalGateError,
    CaseNotFoundError,
    DisputeCaseService,
    InvalidDisputeTransitionError,
    SyntheticSubmissionError,
)

__all__ = [
    "ApprovalGateError",
    "CaseNotFoundError",
    "DisputeCaseService",
    "InvalidDisputeTransitionError",
    "SyntheticSubmissionError",
]
