"""Structured JSON logging with correlation ID and OpenTelemetry trace propagation."""

from __future__ import annotations

import json
import logging
from contextvars import ContextVar
from datetime import UTC, datetime

from opentelemetry import trace

correlation_id_var: ContextVar[str] = ContextVar("correlation_id", default="-")


def _active_trace_fields() -> dict[str, str]:
    try:
        span = trace.get_current_span()
        ctx = span.get_span_context() if span is not None else None
        if ctx is not None and ctx.is_valid:
            return {
                "trace_id": format(ctx.trace_id, "032x"),
                "span_id": format(ctx.span_id, "016x"),
            }
    except (AttributeError, TypeError, ValueError):
        return {}
    return {}


class JsonFormatter(logging.Formatter):
    """Emit structured single-line JSON log records without leaking secrets."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, object] = {
            "timestamp": datetime.now(UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "correlation_id": correlation_id_var.get("-"),
            "message": record.getMessage(),
        }
        trace_fields = _active_trace_fields()
        if trace_fields:
            payload.update(trace_fields)
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str)


def configure_logging(level: str = "INFO") -> None:
    root = logging.getLogger()
    root.setLevel(getattr(logging, level.upper(), logging.INFO))
    handler = logging.StreamHandler()
    handler.setFormatter(JsonFormatter())
    root.handlers = [handler]
