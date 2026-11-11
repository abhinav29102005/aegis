"""Sliding-window API rate limiter middleware."""

from __future__ import annotations

import time
from collections import defaultdict, deque
from threading import Lock

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.responses import JSONResponse

_EXEMPT_PATHS = frozenset({"/health", "/ready", "/openapi.json", "/docs", "/redoc"})


class SlidingWindowRateLimiterMiddleware(BaseHTTPMiddleware):
    """Enforces per-client / per-API-key sliding 60-second request limits."""

    def __init__(self, app, *, requests_per_minute: int = 240) -> None:  # type: ignore[no-untyped-def]
        super().__init__(app)
        self.rpm = max(1, requests_per_minute)
        self._buckets: dict[str, deque[float]] = defaultdict(deque)
        self._lock = Lock()

    def _client_key(self, request: Request) -> str:
        api_key = request.headers.get("X-API-Key")
        if api_key:
            return f"key:{api_key[:16]}"
        auth = request.headers.get("Authorization")
        if auth and auth.lower().startswith("bearer "):
            return f"tok:{auth[7:23]}"
        host = request.client.host if request.client else "unknown"
        return f"ip:{host}"

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        if request.url.path in _EXEMPT_PATHS:
            return await call_next(request)

        now = time.monotonic()
        cutoff = now - 60.0
        key = self._client_key(request)

        with self._lock:
            bucket = self._buckets[key]
            while bucket and bucket[0] <= cutoff:
                bucket.popleft()
            if len(bucket) >= self.rpm:
                return JSONResponse(
                    status_code=429,
                    content={
                        "error_code": "RATE_LIMIT_EXCEEDED",
                        "message": f"Rate limit exceeded ({self.rpm} requests/minute).",
                    },
                    headers={"Retry-After": "60"},
                )
            bucket.append(now)
            remaining = max(0, self.rpm - len(bucket))

        response = await call_next(request)
        response.headers["X-RateLimit-Limit"] = str(self.rpm)
        response.headers["X-RateLimit-Remaining"] = str(remaining)
        return response
