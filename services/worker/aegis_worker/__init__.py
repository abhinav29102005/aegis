"""AEGIS durable outbox and reconciliation worker."""

from __future__ import annotations

from typing import Any

from aegis_worker.processor import OutboxWorker

__all__ = ["OutboxWorker", "check_worker_health", "touch_heartbeat"]


def __getattr__(name: str) -> Any:
    if name in {"check_worker_health", "touch_heartbeat"}:
        from aegis_worker import main as _main

        return getattr(_main, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
