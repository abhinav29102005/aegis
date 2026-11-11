"""Dispute evidence ingestion and normalization."""

from disputeos.ingestion.normalizer import (
    DocumentIngestionService,
    normalize_evidence_record,
)

__all__ = [
    "DocumentIngestionService",
    "normalize_evidence_record",
]
