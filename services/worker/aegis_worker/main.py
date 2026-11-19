"""CLI / daemon entrypoint for AEGIS durable worker."""

from __future__ import annotations

import argparse
import asyncio
import logging
import math
import os
import signal
import time
from collections.abc import Sequence
from pathlib import Path

import httpx
from database import create_db_engine, create_session_factory
from security import NexusSettings, get_settings
from sqlalchemy import text
from sqlalchemy.engine import Engine
from sqlalchemy.exc import SQLAlchemyError

from aegis_worker.processor import OutboxWorker

logger = logging.getLogger("aegis.worker.main")

DEFAULT_HEARTBEAT_PATH = Path("/tmp/aegis-worker-heartbeat")


def _resolve_heartbeat_path(heartbeat_path: Path | None = None) -> Path:
    if heartbeat_path is not None:
        return heartbeat_path
    env_path = os.getenv("AEGIS_WORKER_HEARTBEAT_FILE", "").strip()
    return Path(env_path) if env_path else DEFAULT_HEARTBEAT_PATH


def touch_heartbeat(heartbeat_path: Path | None = None, *, now: float | None = None) -> Path:
    """Write the current UNIX timestamp atomically to the worker heartbeat file."""
    path = _resolve_heartbeat_path(heartbeat_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    ts = time.time() if now is None else float(now)
    tmp_path = path.with_name(f".{path.name}.tmp.{os.getpid()}")
    payload = f"{ts:.6f}\n"
    try:
        tmp_path.write_text(payload, encoding="utf-8")
        tmp_path.replace(path)
    except OSError:
        path.write_text(payload, encoding="utf-8")
    return path


def check_worker_health(
    *,
    settings: NexusSettings | None = None,
    heartbeat_path: Path | None = None,
    max_age_seconds: float | None = None,
    now: float | None = None,
) -> bool:
    """Verify database connectivity (SELECT 1) and a fresh worker heartbeat file."""
    cfg = settings or get_settings()
    hb_path = _resolve_heartbeat_path(heartbeat_path)

    if max_age_seconds is None:
        env_max_age = os.getenv("AEGIS_WORKER_HEARTBEAT_MAX_AGE_SECONDS", "").strip()
        if env_max_age:
            try:
                max_age_seconds = float(env_max_age)
            except ValueError:
                pass

    allowed_age = (
        float(max_age_seconds)
        if max_age_seconds is not None
        else max(30.0, cfg.worker_poll_interval_seconds * 5.0)
    )
    if allowed_age <= 0:
        allowed_age = 30.0

    try:
        raw_ts = hb_path.read_text(encoding="utf-8").strip()
        hb_ts = float(raw_ts)
        if not math.isfinite(hb_ts) or hb_ts < 0:
            logger.warning("Worker healthcheck failed: invalid heartbeat timestamp (%s)", raw_ts)
            return False
    except (OSError, ValueError):
        logger.warning("Worker healthcheck failed: missing or unreadable heartbeat at %s", hb_path)
        return False

    current = time.time() if now is None else float(now)
    age = current - hb_ts
    if age > allowed_age or age < -allowed_age:
        logger.warning(
            "Worker healthcheck failed: heartbeat out of bounds (age=%.2fs, allowed=%.2fs)",
            age,
            allowed_age,
        )
        return False

    engine: Engine | None = None
    try:
        engine = create_db_engine(cfg.database_url)
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
    except (SQLAlchemyError, OSError, RuntimeError, ValueError) as exc:
        logger.warning("Worker healthcheck failed: database error (%s)", type(exc).__name__)
        return False
    finally:
        if engine is not None:
            engine.dispose()

    return True


async def run_worker_loop(
    *,
    settings: NexusSettings | None = None,
    heartbeat_path: Path | None = None,
    stop_event: asyncio.Event | None = None,
) -> None:
    cfg = settings or get_settings()
    cfg.validate_security_posture()
    logging.basicConfig(level=getattr(logging, cfg.log_level.upper(), logging.INFO))

    hb_path = _resolve_heartbeat_path(heartbeat_path)
    engine = create_db_engine(cfg.database_url)
    session_factory = create_session_factory(engine)

    shutdown_event = stop_event or asyncio.Event()
    worker = OutboxWorker(session_factory=session_factory, settings=cfg, stop_event=shutdown_event)

    loop = asyncio.get_running_loop()

    def _on_signal(signum: int) -> None:
        try:
            sig_name = signal.Signals(signum).name
        except ValueError:
            sig_name = str(signum)
        logger.info("Received shutdown signal %s, initiating graceful worker shutdown", sig_name)
        shutdown_event.set()

    registered_signals: list[signal.Signals] = []
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, _on_signal, sig)
            registered_signals.append(sig)
        except NotImplementedError:
            pass

    logger.info("AEGIS worker started (poll_interval=%ss, worker_id=%s)", cfg.worker_poll_interval_seconds, worker.worker_id)
    consecutive_errors = 0
    try:
        touch_heartbeat(hb_path)
        while not shutdown_event.is_set():
            sleep_seconds = cfg.worker_poll_interval_seconds
            try:
                stats = await worker.run_once()
                consecutive_errors = 0
                touch_heartbeat(hb_path)
                if stats["outbox"]["claimed"] or stats["reconciliation"]["checked"]:
                    logger.info("Worker tick: %s", stats)
            except (SQLAlchemyError, httpx.HTTPError, OSError, RuntimeError, ValueError) as exc:
                consecutive_errors += 1
                backoff = min(
                    30.0,
                    max(0.5, cfg.worker_poll_interval_seconds) * (2 ** min(consecutive_errors - 1, 4)),
                )
                sleep_seconds = backoff
                logger.warning(
                    "Transient worker tick error (%s), backing off %.2fs",
                    type(exc).__name__,
                    sleep_seconds,
                    exc_info=True,
                )
            try:
                await asyncio.wait_for(shutdown_event.wait(), timeout=sleep_seconds)
            except TimeoutError:
                continue
    finally:
        for sig in registered_signals:
            try:
                loop.remove_signal_handler(sig)
            except (NotImplementedError, RuntimeError):
                pass
        engine.dispose()
        logger.info("AEGIS worker stopped cleanly")


def main(argv: Sequence[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="AEGIS durable outbox and reconciliation worker")
    parser.add_argument(
        "--healthcheck",
        action="store_true",
        help="Verify database connectivity and recent worker heartbeat, exiting 0 if healthy or 1 otherwise.",
    )
    parser.add_argument(
        "--heartbeat-file",
        type=Path,
        default=None,
        help="Path to heartbeat file (defaults to AEGIS_WORKER_HEARTBEAT_FILE or /tmp/aegis-worker-heartbeat).",
    )
    parser.add_argument(
        "--max-age",
        type=float,
        default=None,
        help="Maximum allowed age of heartbeat in seconds for healthcheck.",
    )
    args = parser.parse_args(list(argv) if argv is not None else None)

    if args.healthcheck:
        is_healthy = check_worker_health(
            heartbeat_path=args.heartbeat_file,
            max_age_seconds=args.max_age,
        )
        raise SystemExit(0 if is_healthy else 1)

    try:
        asyncio.run(run_worker_loop(heartbeat_path=args.heartbeat_file))
    except (KeyboardInterrupt, SystemExit):
        pass


if __name__ == "__main__":
    main()
