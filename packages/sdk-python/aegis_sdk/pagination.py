"""Pagination helpers and iterators for AEGIS list endpoints."""

from __future__ import annotations

from collections.abc import AsyncIterator, Awaitable, Callable, Iterator
from typing import Any, Generic, TypeVar

T = TypeVar("T")


def _extract_items_and_total(resp: Any) -> tuple[list[Any], int | None]:
    if isinstance(resp, list):
        return resp, None
    if isinstance(resp, dict):
        if "items" in resp and isinstance(resp["items"], list):
            return resp["items"], resp.get("total")
        if "data" in resp and isinstance(resp["data"], list):
            return resp["data"], resp.get("total")
    return [], 0


class PaginationIterator(Generic[T], Iterator[T]):
    """Synchronous iterator across paginated AEGIS API endpoints."""

    def __init__(
        self,
        fetch_page: Callable[[int, int], Any],
        limit: int = 50,
        max_items: int | None = None,
    ) -> None:
        self._fetch_page = fetch_page
        self._limit = max(1, limit)
        self._max_items = max_items
        self._offset = 0
        self._buffer: list[T] = []
        self._yielded = 0
        self._exhausted = False

    def __iter__(self) -> PaginationIterator[T]:
        return self

    def __next__(self) -> T:
        if self._max_items is not None and self._yielded >= self._max_items:
            raise StopIteration

        if not self._buffer and not self._exhausted:
            self._load_next_page()

        if not self._buffer:
            raise StopIteration

        item = self._buffer.pop(0)
        self._yielded += 1
        return item

    def _load_next_page(self) -> None:
        resp = self._fetch_page(self._limit, self._offset)
        items, total = _extract_items_and_total(resp)
        self._buffer.extend(items)  # type: ignore[arg-type]
        self._offset += len(items)

        if len(items) < self._limit:
            self._exhausted = True
        elif total is not None and self._offset >= total:
            self._exhausted = True


class AsyncPaginationIterator(Generic[T], AsyncIterator[T]):
    """Asynchronous iterator across paginated AEGIS API endpoints."""

    def __init__(
        self,
        fetch_page: Callable[[int, int], Awaitable[Any]],
        limit: int = 50,
        max_items: int | None = None,
    ) -> None:
        self._fetch_page = fetch_page
        self._limit = max(1, limit)
        self._max_items = max_items
        self._offset = 0
        self._buffer: list[T] = []
        self._yielded = 0
        self._exhausted = False

    def __aiter__(self) -> AsyncPaginationIterator[T]:
        return self

    async def __anext__(self) -> T:
        if self._max_items is not None and self._yielded >= self._max_items:
            raise StopAsyncIteration

        if not self._buffer and not self._exhausted:
            await self._load_next_page()

        if not self._buffer:
            raise StopAsyncIteration

        item = self._buffer.pop(0)
        self._yielded += 1
        return item

    async def _load_next_page(self) -> None:
        resp = await self._fetch_page(self._limit, self._offset)
        items, total = _extract_items_and_total(resp)
        self._buffer.extend(items)  # type: ignore[arg-type]
        self._offset += len(items)

        if len(items) < self._limit:
            self._exhausted = True
        elif total is not None and self._offset >= total:
            self._exhausted = True


def paginate(
    fetch_page: Callable[[int, int], Any],
    *,
    limit: int = 50,
    max_items: int | None = None,
) -> PaginationIterator[Any]:
    """Return a synchronous iterator that yields individual items across paginated pages."""
    return PaginationIterator(fetch_page, limit=limit, max_items=max_items)


def paginate_async(
    fetch_page: Callable[[int, int], Awaitable[Any]],
    *,
    limit: int = 50,
    max_items: int | None = None,
) -> AsyncPaginationIterator[Any]:
    """Return an asynchronous iterator that yields individual items across paginated pages."""
    return AsyncPaginationIterator(fetch_page, limit=limit, max_items=max_items)
