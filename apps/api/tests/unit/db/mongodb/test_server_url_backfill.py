"""Regression: the server-URL dedup backfill must finish when a custom integration has no usable URL.

A connector (no mcp_config) or a loser of a contested key stays keyless, so a
loop that re-queries "keyless rows" until none are left never ended, and the
API hung at startup inside index creation.
"""

import asyncio
from typing import Any
from unittest.mock import patch

import pytest

from app.db.mongodb.indexes import _backfill_custom_server_url_keys


class _Cursor:
    def __init__(self, docs: list[dict[str, Any]]) -> None:
        self._docs = docs

    def sort(self, *_: object) -> "_Cursor":
        return self

    def limit(self, _: int) -> "_Cursor":
        return self

    async def to_list(self, length: int) -> list[dict[str, Any]]:
        await asyncio.sleep(0)  # a real driver yields here, which lets the timeout fire
        return self._docs[:length]

    def __aiter__(self) -> "_Cursor":
        self._iter = iter(self._docs)
        return self

    async def __anext__(self) -> dict[str, Any]:
        try:
            return next(self._iter)
        except StopIteration as stop:
            raise StopAsyncIteration from stop


class _Integrations:
    """Keyless custom rows: one connector, one MCP server whose key another row already claims."""

    def __init__(self) -> None:
        self.keyless: list[dict[str, Any]] = [
            {"integration_id": "conn-1", "created_by": "u1"},
            {
                "integration_id": "mcp-2",
                "created_by": "u1",
                "mcp_config": {"server_url": "https://a.example/mcp"},
            },
        ]
        self.updates: list[str] = []

    def find(self, *_: object) -> _Cursor:
        return _Cursor(list(self.keyless))

    async def find_one(self, *_: object, **__: object) -> dict[str, str]:
        return {"_id": "the-winner"}

    async def update_one(self, query: dict[str, str], _: object) -> None:
        self.updates.append(query["integration_id"])


@pytest.mark.regression
async def test_the_backfill_finishes_when_rows_stay_keyless() -> None:
    collection = _Integrations()
    with (
        patch("app.db.mongodb.indexes.get_async_collection", return_value=collection),
        patch("app.db.mongodb.indexes.log"),
    ):
        await asyncio.wait_for(_backfill_custom_server_url_keys(), timeout=2)

    assert collection.updates == []
