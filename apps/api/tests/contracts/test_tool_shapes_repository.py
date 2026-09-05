"""Contract tests for ToolShapesRepository (global, one record per scope+tool)."""

from __future__ import annotations

import uuid

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
