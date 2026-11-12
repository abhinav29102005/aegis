"""Shared error types and retrying HTTP transport helper for multi-rail provider adapters."""

from __future__ import annotations

import asyncio
from typing import Any

import httpx

from guardian.domain.exceptions import GuardianError


class ProviderAdapterError(GuardianError):
    """Base error for multi-rail payment provider adapters."""


class ProviderConfigurationError(ProviderAdapterError):
    """Raised when required provider credentials or secrets are missing."""


class ProviderSignatureError(ProviderAdapterError):
    """Raised when a webhook, mandate, or token signature fails verification."""


class ProviderValidationError(ProviderAdapterError):
    """Raised when a provider payload violates amount, currency, expiry, or binding checks."""


class ProviderAPIError(ProviderAdapterError):
    """Raised when an upstream provider HTTP API returns a non-success response."""

    def __init__(self, message: str, *, status_code: int = 502, provider: str = "unknown") -> None:
        super().__init__(message)
        self.status_code = status_code
        self.provider = provider


class RetryingHTTPClient:
    """Async httpx request helper with exponential backoff on 429, 5xx, and transport errors."""

    def __init__(
        self,
        *,
        provider_name: str,
        base_url: str = "",
        http_client: httpx.AsyncClient | None = None,
        timeout_seconds: float = 15.0,
        max_retries: int = 2,
        retry_base_delay: float = 0.05,
        retry_max_delay: float = 1.0,
    ) -> None:
        self.provider_name = provider_name
        self.base_url = base_url.rstrip("/")
        self._external_client = http_client
        self.timeout_seconds = timeout_seconds
        self.max_retries = max(0, max_retries)
        self.retry_base_delay = max(0.0, retry_base_delay)
        self.retry_max_delay = max(0.0, retry_max_delay)

    def _build_client(self) -> httpx.AsyncClient:
        if self._external_client is not None:
            return self._external_client
        return httpx.AsyncClient(base_url=self.base_url, timeout=self.timeout_seconds)

    def _retry_delay(self, attempt: int, response: httpx.Response | None = None) -> float:
        if response is not None:
            retry_after = response.headers.get("Retry-After")
            if retry_after:
                try:
                    parsed = float(retry_after.strip())
                    if parsed >= 0:
                        return min(self.retry_max_delay, parsed)
                except ValueError:
                    pass
        return min(self.retry_max_delay, self.retry_base_delay * (2**attempt))

    async def request(
        self,
        method: str,
        path: str,
        *,
        timeout_seconds: float | None = None,
        **kwargs: Any,
    ) -> httpx.Response:
        close_after = self._external_client is None
        client = self._build_client()
        if timeout_seconds is not None:
            kwargs["timeout"] = timeout_seconds

        try:
            for attempt in range(self.max_retries + 1):
                try:
                    if hasattr(client, "request"):
                        resp = await client.request(method, path, **kwargs)
                    elif method.upper() == "POST" and hasattr(client, "post"):
                        resp = await client.post(path, **kwargs)
                    elif method.upper() == "GET" and hasattr(client, "get"):
                        resp = await client.get(path, **kwargs)
                    else:
                        resp = await client.request(method, path, **kwargs)
                except httpx.TimeoutException as exc:
                    if attempt < self.max_retries:
                        await asyncio.sleep(self._retry_delay(attempt))
                        continue
                    raise ProviderAPIError(
                        f"{self.provider_name} request timed out: {exc}",
                        status_code=504,
                        provider=self.provider_name,
                    ) from exc
                except httpx.TransportError as exc:
                    if attempt < self.max_retries:
                        await asyncio.sleep(self._retry_delay(attempt))
                        continue
                    raise ProviderAPIError(
                        f"{self.provider_name} transport error: {exc}",
                        status_code=502,
                        provider=self.provider_name,
                    ) from exc

                if (resp.status_code == 429 or 500 <= resp.status_code < 600) and attempt < self.max_retries:
                    await asyncio.sleep(self._retry_delay(attempt, resp))
                    continue
                return resp
        finally:
            if close_after:
                await client.aclose()

        raise ProviderAPIError(
            f"{self.provider_name} request exhausted retries",
            status_code=502,
            provider=self.provider_name,
        )
