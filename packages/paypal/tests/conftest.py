"""Pytest configuration and sandbox environment compatibility fixtures for paypal tests."""

import sys

if sys.platform == "win32":
    try:
        import asyncio.proactor_events as pe

        class _SandboxDummySocket:
            def fileno(self) -> int:
                return -1

            def setblocking(self, blocking: bool) -> None:
                pass

            def close(self) -> None:
                pass

        def _sandbox_fake_self_pipe(self) -> None:
            self._ssock = _SandboxDummySocket()
            self._csock = _SandboxDummySocket()
            self._internal_fds = 0

        pe.BaseProactorEventLoop._make_self_pipe = _sandbox_fake_self_pipe
        pe.BaseProactorEventLoop._close_self_pipe = lambda self: None
        pe.BaseProactorEventLoop._loop_self_reading = lambda self, f=None: None
    except Exception:  # noqa: BLE001, S110
        pass
