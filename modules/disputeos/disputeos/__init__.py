"""DisputeOS — Dispute case management, evidence ingestion, and human-reviewed response drafts."""

from disputeos.cases import (
    ApprovalGateError,
    CaseNotFoundError,
    DisputeCaseService,
    SyntheticSubmissionError,
)
from disputeos.ingestion import (
    DocumentIngestionService,
    normalize_evidence_record,
)

__all__ = [
    "ApprovalGateError",
    "CaseNotFoundError",
    "DisputeCaseService",
    "DocumentIngestionService",
    "SyntheticSubmissionError",
    "normalize_evidence_record",
]
