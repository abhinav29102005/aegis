"""Tests for sync and async pagination iterators."""

from __future__ import annotations

from typing import Any

import pytest
from aegis_sdk.pagination import (
    paginate,
    paginate_async,
)


def test_sync_pagination_dict_response() -> None:
    data = list(range(125))

    def fetch_page(limit: int, offset: int) -> dict[str, Any]:
        return {
            "items": data[offset : offset + limit],
            "total": len(data),
            "limit": limit,
            "offset": offset,
        }

    it = paginate(fetch_page, limit=50)
    results = list(it)
    assert len(results) == 125
    assert results == data


def test_sync_pagination_list_response() -> None:
    data = [{"id": i} for i in range(75)]

    def fetch_page(limit: int, offset: int) -> list[dict[str, int]]:
        return data[offset : offset + limit]

    it = paginate(fetch_page, limit=25)
    results = list(it)
    assert len(results) == 75
    assert results == data


def test_sync_pagination_max_items() -> None:
    data = list(range(100))

    def fetch_page(limit: int, offset: int) -> list[int]:
        return data[offset : offset + limit]

    it = paginate(fetch_page, limit=20, max_items=35)
    results = list(it)
    assert len(results) == 35
    assert results == data[:35]


@pytest.mark.asyncio
async def test_async_pagination_dict_response() -> None:
    data = [f"item-{i}" for i in range(110)]

    async def fetch_page(limit: int, offset: int) -> dict[str, Any]:
        return {
            "items": data[offset : offset + limit],
            "total": len(data),
            "limit": limit,
            "offset": offset,
        }

    results = []
    async for item in paginate_async(fetch_page, limit=40):
        results.append(item)

    assert len(results) == 110
    assert results == data


@pytest.mark.asyncio
async def test_async_pagination_max_items() -> None:
    data = list(range(50))

    async def fetch_page(limit: int, offset: int) -> list[int]:
        return data[offset : offset + limit]

    results = []
    async for item in paginate_async(fetch_page, limit=10, max_items=25):
        results.append(item)

    assert len(results) == 25
    assert results == data[:25]
