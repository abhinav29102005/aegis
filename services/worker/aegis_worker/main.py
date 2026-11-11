"""CLI / daemon entrypoint for AEGIS durable worker."""

from __future__ import annotations

import asyncio
import logging
import signal

from database import create_db_engine, create_session_factory
from security import get_settings

from aegis_worker.processor import OutboxWorker

logger = logging.getLogger("aegis.worker.main")


async def run_worker_loop() -> None:
    settings = get_settings()
    settings.validate_security_posture()
    logging.basicConfig(level=getattr(logging, settings.log_level.upper(), logging.INFO))

    engine = create_db_engine(settings.database_url)
    session_factory = create_session_factory(engine)
    worker = OutboxWorker(session_factory=session_factory, settings=settings)

    stop_event = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, stop_event.set)
        except NotImplementedError:
            pass

    logger.info("AEGIS worker started (poll_interval=%ss)", settings.worker_poll_interval_seconds)
    try:
        while not stop_event.is_set():
            try:
                stats = await worker.run_once()
                if stats["outbox"]["claimed"] or stats["reconciliation"]["checked"]:
                    logger.info("Worker tick: %s", stats)
            except (OSError, RuntimeError, ValueError):
                logger.exception("Worker tick error")
            try:
                await asyncio.wait_for(stop_event.wait(), timeout=settings.worker_poll_interval_seconds)
            except TimeoutError:
                continue
    finally:
        engine.dispose()
        logger.info("AEGIS worker stopped cleanly")


def main() -> None:
    asyncio.run(run_worker_loop())


if __name__ == "__main__":
    main()
