"""Prometheus metrics registry and optional OpenTelemetry instrumentation."""

from __future__ import annotations

import logging
import os
from collections.abc import Iterator
from contextlib import contextmanager
from threading import Lock
from typing import Any

from fastapi import FastAPI
from opentelemetry import trace
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from prometheus_client import (
    CollectorRegistry,
    Counter,
    Gauge,
    Histogram,
    generate_latest,
)

logger = logging.getLogger("aegis.api.metrics")

PROMETHEUS_CONTENT_TYPE = "text/plain; version=0.0.4; charset=utf-8"

# Dedicated registry prevents duplicate timeseries errors across repeated create_app() calls.
AEGIS_REGISTRY = CollectorRegistry(auto_describe=True)

HTTP_REQUESTS_TOTAL = Counter(
    "aegis_http_requests_total",
    "Total HTTP requests processed by AEGIS API.",
    labelnames=("method", "path", "status_code"),
    registry=AEGIS_REGISTRY,
)

HTTP_REQUEST_DURATION_SECONDS = Histogram(
    "aegis_http_request_duration_seconds",
    "HTTP request latency in seconds.",
    labelnames=("method", "path"),
    buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0),
    registry=AEGIS_REGISTRY,
)

HTTP_REQUESTS_IN_PROGRESS = Gauge(
    "aegis_http_requests_in_progress",
    "Number of HTTP requests currently in flight.",
    labelnames=("method",),
    registry=AEGIS_REGISTRY,
)

RATE_LIMIT_REJECTIONS_TOTAL = Counter(
    "aegis_rate_limit_rejections_total",
    "Total requests rejected with HTTP 429 by rate limiter.",
    labelnames=("backend",),
    registry=AEGIS_REGISTRY,
)

_otel_lock = Lock()
_configured_provider: TracerProvider | None = None


def record_http_request(method: str, path: str, status_code: int, duration_seconds: float) -> None:
    """Record completed HTTP request count and duration."""
    norm_method = method.upper()
    HTTP_REQUESTS_TOTAL.labels(
        method=norm_method,
        path=path,
        status_code=str(status_code),
    ).inc()
    HTTP_REQUEST_DURATION_SECONDS.labels(
        method=norm_method,
        path=path,
    ).observe(max(0.0, duration_seconds))


def record_rate_limit_rejection(backend: str) -> None:
    """Increment rate-limit rejection counter for the active limiter backend."""
    RATE_LIMIT_REJECTIONS_TOTAL.labels(backend=backend).inc()


@contextmanager
def track_in_progress(method: str) -> Iterator[None]:
    """Track active in-flight HTTP requests for a given HTTP method."""
    gauge = HTTP_REQUESTS_IN_PROGRESS.labels(method=method.upper())
    gauge.inc()
    try:
        yield
    finally:
        gauge.dec()


def render_metrics() -> tuple[bytes, str]:
    """Render AEGIS Prometheus metrics payload and content type."""
    return generate_latest(AEGIS_REGISTRY), PROMETHEUS_CONTENT_TYPE


def _is_truthy(value: str | None) -> bool:
    if not value:
        return False
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _is_falsy(value: str | None) -> bool:
    if not value:
        return False
    return value.strip().lower() in {"0", "false", "no", "off"}


def _build_otlp_exporter(endpoint: str) -> Any | None:
    """Attempt to construct an OTLP span exporter if optional packages are installed."""
    try:
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import (
            OTLPSpanExporter,
        )

        return OTLPSpanExporter(endpoint=endpoint)
    except ImportError:
        try:
            from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import (
                OTLPSpanExporter,
            )

            return OTLPSpanExporter(endpoint=endpoint)
        except ImportError:
            logger.warning(
                "OTEL_EXPORTER_OTLP_ENDPOINT is set but opentelemetry-exporter-otlp is not installed."
            )
            return None


def _get_or_init_tracer_provider(settings: Any | None) -> TracerProvider:
    global _configured_provider
    with _otel_lock:
        if _configured_provider is not None:
            return _configured_provider

        current = trace.get_tracer_provider()
        if isinstance(current, TracerProvider):
            _configured_provider = current
            return current

        env_name = getattr(settings, "app_env", None) or os.getenv("APP_ENV", "development")
        service_name = os.getenv("OTEL_SERVICE_NAME", "aegis-api")
        provider = TracerProvider(
            resource=Resource.create(
                {
                    "service.name": service_name,
                    "deployment.environment": str(env_name),
                }
            )
        )
        otlp_endpoint = os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT", "").strip()
        if otlp_endpoint:
            exporter = _build_otlp_exporter(otlp_endpoint)
            if exporter is not None:
                provider.add_span_processor(BatchSpanProcessor(exporter))

        trace.set_tracer_provider(provider)
        _configured_provider = provider
        return provider


def configure_opentelemetry(
    app: FastAPI,
    *,
    settings: Any | None = None,
    enabled: bool | None = None,
) -> bool:
    """Safely configure OpenTelemetry tracing on a FastAPI app across repeated factory calls."""
    if _is_truthy(os.getenv("OTEL_SDK_DISABLED")):
        return False

    if enabled is None:
        raw_toggle = os.getenv("AEGIS_OTEL_ENABLED") or os.getenv("OTEL_ENABLED")
        if _is_falsy(raw_toggle):
            return False
        enabled = bool(
            _is_truthy(raw_toggle)
            or os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT", "").strip()
            or getattr(settings, "otel_enabled", False)
        )

    if not enabled:
        return False

    if getattr(app.state, "_otel_instrumented", False):
        return True

    provider = _get_or_init_tracer_provider(settings)
    FastAPIInstrumentor.instrument_app(
        app,
        tracer_provider=provider,
        excluded_urls="health,ready,metrics",
    )
    app.state._otel_instrumented = True
    return True
