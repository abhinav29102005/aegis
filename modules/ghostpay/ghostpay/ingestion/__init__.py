"""Ingestion package for GhostPay."""

from ghostpay.ingestion.adapter import TraceIngestionAdapter
from ghostpay.ingestion.validation import TraceValidator

__all__ = ["TraceIngestionAdapter", "TraceValidator"]

