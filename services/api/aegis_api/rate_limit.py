"""Sliding-window API rate limiter middleware with bounded in-memory and Redis backends."""

from __future__ import annotations

import hashlib
import inspect
import logging
import time
from collections import OrderedDict, deque
from threading import Lock
from typing import Any
from uuid import uuid4

import redis
from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.responses import JSONResponse

from aegis_api.metrics import record_rate_limit_rejection

logger = logging.getLogger("aegis.api.rate_limit")

_EXEMPT_PATHS = frozenset({"/health", "/ready", "/metrics", "/openapi.json", "/docs", "/redoc"})
_PRUNE_INTERVAL_REQUESTS = 256


async def _maybe_await(result: Any) -> Any:
    if inspect.isawaitable(result):
        return await result
    return result


class SlidingWindowRateLimiterMiddleware(BaseHTTPMiddleware):
    """Enforces per-client / per-API-key sliding 60-second request limits."""

    def __init__(
        self,
        app,  # type: ignore[no-untyped-def]
        *,
        requests_per_minute: int = 240,
        max_buckets: int = 10_000,
        redis_url: str | None = None,
        redis_client: Any | None = None,
        window_seconds: float = 60.0,
    ) -> None:
        super().__init__(app)
        self.rpm = max(1, requests_per_minute)
        self.max_buckets = max(1, max_buckets)
        self.window_seconds = max(1.0, float(window_seconds))
        self._buckets: OrderedDict[str, deque[float]] = OrderedDict()
        self._lock = Lock()
        self._request_counter = 0

        self.redis_url = redis_url.strip() if redis_url and redis_url.strip() else None
        self._redis: Any | None = redis_client
        if self._redis is None and self.redis_url is not None:
            try:
                self._redis = redis.Redis.from_url(
                    self.redis_url,
                    socket_connect_timeout=0.5,
                    socket_timeout=0.5,
                    decode_responses=True,
                )
            except (redis.RedisError, OSError, ValueError, TypeError) as exc:
                logger.warning(
                    "Invalid Redis URL for rate limiter; falling back to in-memory backend: %s",
                    exc,
                )
                self._redis = None

    def _client_key(self, request: Request) -> str:
        api_key = request.headers.get("X-API-Key")
        if api_key and api_key.strip():
            digest = hashlib.sha256(api_key.strip().encode("utf-8")).hexdigest()[:16]
            return f"key:{digest}"
        auth = request.headers.get("Authorization")
        if auth and auth.strip().lower().startswith("bearer "):
            token = auth.strip()[7:].strip()
            if token:
                digest = hashlib.sha256(token.encode("utf-8")).hexdigest()[:16]
                return f"tok:{digest}"
        host = request.client.host if request.client else "unknown"
        return f"ip:{host}"

    def _prune_expired_buckets_locked(self, cutoff: float) -> None:
        empty_keys: list[str] = []
        for bucket_key, timestamps in self._buckets.items():
            while timestamps and timestamps[0] <= cutoff:
                timestamps.popleft()
            if not timestamps:
                empty_keys.append(bucket_key)
        for bucket_key in empty_keys:
            del self._buckets[bucket_key]

    def _check_in_memory(self, key: str) -> tuple[bool, int]:
        now = time.monotonic()
        cutoff = now - self.window_seconds

        with self._lock:
            self._request_counter += 1
            if self._request_counter % _PRUNE_INTERVAL_REQUESTS == 0:
                self._prune_expired_buckets_locked(cutoff)

            bucket = self._buckets.get(key)
            if bucket is None:
                if len(self._buckets) >= self.max_buckets:
                    self._prune_expired_buckets_locked(cutoff)
                while len(self._buckets) >= self.max_buckets:
                    self._buckets.popitem(last=False)
                bucket = deque()
                self._buckets[key] = bucket
            else:
                self._buckets.move_to_end(key)

            while bucket and bucket[0] <= cutoff:
                bucket.popleft()

            if len(bucket) >= self.rpm:
                return False, 0

            bucket.append(now)
            remaining = max(0, self.rpm - len(bucket))
            return True, remaining

    async def _check_redis(self, key: str) -> tuple[bool, int]:
        assert self._redis is not None
        now = time.time()
        cutoff = now - self.window_seconds
        redis_key = f"aegis:ratelimit:{key}"
        member = f"{now:.6f}:{uuid4().hex[:8]}"
        ttl_seconds = int(self.window_seconds) + 1

        pipeline_fn = getattr(self._redis, "pipeline", None)
        if callable(pipeline_fn):
            pipe = pipeline_fn()
            pipe.zremrangebyscore(redis_key, "-inf", cutoff)
            pipe.zcard(redis_key)
            results = await _maybe_await(pipe.execute())
            current_count = int(results[1])
            if current_count >= self.rpm:
                return False, 0
            write_pipe = pipeline_fn()
            write_pipe.zadd(redis_key, {member: now})
            write_pipe.expire(redis_key, ttl_seconds)
            await _maybe_await(write_pipe.execute())
            return True, max(0, self.rpm - (current_count + 1))

        await _maybe_await(self._redis.zremrangebyscore(redis_key, "-inf", cutoff))
        current_count = int(await _maybe_await(self._redis.zcard(redis_key)))
        if current_count >= self.rpm:
            return False, 0
        await _maybe_await(self._redis.zadd(redis_key, {member: now}))
        await _maybe_await(self._redis.expire(redis_key, ttl_seconds))
        return True, max(0, self.rpm - (current_count + 1))

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        if request.url.path in _EXEMPT_PATHS:
            return await call_next(request)

        key = self._client_key(request)
        backend = "memory"
        if self._redis is not None:
            try:
                allowed, remaining = await self._check_redis(key)
                backend = "redis"
            except (redis.RedisError, OSError, TimeoutError, ValueError, TypeError) as exc:
                logger.warning(
                    "Redis rate limiter error; falling back to in-memory sliding window: %s",
                    exc,
                )
                allowed, remaining = self._check_in_memory(key)
        else:
            allowed, remaining = self._check_in_memory(key)

        if not allowed:
            record_rate_limit_rejection(backend)
            return JSONResponse(
                status_code=429,
                content={
                    "error_code": "RATE_LIMIT_EXCEEDED",
                    "message": f"Rate limit exceeded ({self.rpm} requests/minute).",
                },
                headers={
                    "Retry-After": str(int(self.window_seconds)),
                    "X-RateLimit-Limit": str(self.rpm),
                    "X-RateLimit-Remaining": "0",
                },
            )

        response = await call_next(request)
        response.headers["X-RateLimit-Limit"] = str(self.rpm)
        response.headers["X-RateLimit-Remaining"] = str(remaining)
        return response
