"""Contract tests for ToolShapesRepository (global, one record per scope+tool)."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
import uuid

from pymongo.errors import DuplicateKeyError
import pytest

from app.db.repositories.tool_shapes import ToolShapesRepository

SCHEMA_V1 = {"type": "object", "properties": {"a": {"type": "string"}}}
SCHEMA_V2 = {"type": "object", "properties": {"a": {"type": "string"}, "b": {"type": "integer"}}}


@pytest.fixture
def repo(raw_collection) -> ToolShapesRepository:
    return ToolShapesRepository()


def _tool() -> str:
    return f"TOOL_{uuid.uuid4().hex[:12].upper()}"


class TestToolShapesRepository:
    async def test_record_upserts_and_counts_observations(self, repo):
        tool = _tool()
        await repo.record("global", tool, SCHEMA_V1)
        doc = await repo.get_shape("global", tool)
        assert doc is not None
        assert doc.output_schema == SCHEMA_V1
        assert doc.call_count == 1
        assert doc.last_seen is not None

        await repo.record("global", tool, SCHEMA_V2)
        doc = await repo.get_shape("global", tool)
        assert doc.output_schema == SCHEMA_V2  # merged schema replaces
        assert doc.call_count == 2  # $inc, never reset

    async def test_scopes_are_isolated_for_the_same_tool_name(self, repo):
        tool = _tool()
        await repo.record("global", tool, SCHEMA_V1)
        await repo.record("mcp:crm-123", tool, SCHEMA_V2)

        global_doc = await repo.get_shape("global", tool)
        mcp_doc = await repo.get_shape("mcp:crm-123", tool)
        assert global_doc.output_schema == SCHEMA_V1
        assert mcp_doc.output_schema == SCHEMA_V2
        # A scope that never recorded sees nothing — the privacy boundary.
        assert await repo.get_shape("mcp:other-999", tool) is None

    async def test_get_shape_misses_cleanly_for_unknown_tool(self, repo):
        assert await repo.get_shape("global", _tool()) is None


class TestToolShapesUniqueIndexSurface:
    """The one-per-(scope, tool) index lives on the real collection, not the
    ephemeral fixture — recreate it to prove the constraint the record() upsert
    retry depends on, and that record() converges on a single document rather
    than duplicating the shape or raising when a concurrent insert wins."""

    async def _create_index(self, raw_collection) -> None:
        # Mirrors app/db/mongodb/indexes.py::create_tool_output_shapes_indexes.
        await raw_collection.create_index([("scope", 1), ("tool_name", 1)], unique=True)

    async def test_pre_existing_duplicates_are_collapsed_before_the_index(
        self, repo, raw_collection
    ):
        """A DB that raced under the pre-index code already holds duplicates; the
        unique index must still build. De-dup keeps the most-observed record."""
        from app.db.mongodb.indexes import _dedupe_tool_output_shapes

        tool = _tool()
        now = datetime.now(UTC)
        await raw_collection.insert_many(
            [
                {
                    "scope": "global",
                    "tool_name": tool,
                    "output_schema": SCHEMA_V1,
                    "call_count": 3,
                    "last_seen": now,
                },
                {
                    "scope": "global",
                    "tool_name": tool,
                    "output_schema": SCHEMA_V2,
                    "call_count": 7,
                    "last_seen": now,
                },
                {
                    "scope": "global",
                    "tool_name": tool,
                    "output_schema": SCHEMA_V1,
                    "call_count": 1,
                    "last_seen": now,
                },
            ]
        )

        await _dedupe_tool_output_shapes(raw_collection)
        # The index build is what would fail on leftover duplicates.
        await raw_collection.create_index([("scope", 1), ("tool_name", 1)], unique=True)

        docs = await raw_collection.find({"scope": "global", "tool_name": tool}).to_list(
            length=None
        )
        assert len(docs) == 1
        assert docs[0]["call_count"] == 7  # the most-observed record survives

    async def test_record_is_idempotent_under_the_unique_index(self, repo, raw_collection):
        await self._create_index(raw_collection)
        tool = _tool()

        await repo.record("global", tool, SCHEMA_V1)
        await repo.record("global", tool, SCHEMA_V2)

        assert await raw_collection.count_documents({"scope": "global", "tool_name": tool}) == 1

    async def test_record_retries_the_losing_insert_onto_the_winner(
        self, repo, raw_collection, monkeypatch
    ):
        """Two first observations race: both miss the match, one inserts, the
        other's insert collides on the unique index. record() must catch that
        DuplicateKeyError and retry onto the winner — one document, never a raise."""
        await self._create_index(raw_collection)
        tool = _tool()
        real_update = raw_collection.find_one_and_update
        calls = {"n": 0}

        async def losing_then_winning(*args: Any, **kwargs: Any):
            calls["n"] += 1
            if calls["n"] == 1:
                # The competing observation inserts the winning document between
                # our upsert's read and its insert, so our insert now conflicts.
                await raw_collection.insert_one(
                    {
                        "scope": "global",
                        "tool_name": tool,
                        "output_schema": SCHEMA_V1,
                        "call_count": 1,
                        "last_seen": datetime.now(UTC),
                    }
                )
                raise DuplicateKeyError("E11000 duplicate key")
            return await real_update(*args, **kwargs)

        monkeypatch.setattr(raw_collection, "find_one_and_update", losing_then_winning)

        await repo.record("global", tool, SCHEMA_V2)  # must not raise

        assert calls["n"] == 2  # retried exactly once
        assert await raw_collection.count_documents({"scope": "global", "tool_name": tool}) == 1
        merged = await repo.get_shape("global", tool)
        assert merged.output_schema == SCHEMA_V2  # the retry merged onto the winner
        assert merged.call_count == 2
