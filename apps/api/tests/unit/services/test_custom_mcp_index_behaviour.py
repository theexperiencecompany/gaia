"""Behaviour tests for indexing a custom MCP into the subagents namespace."""

from typing import NamedTuple
from unittest.mock import AsyncMock

from langgraph.store.base import BaseStore, PutOp
import pytest

from app.services.mcp.custom_mcp_index import (
    CustomMcpIndexRequest,
    index_custom_mcp_as_subagent,
)


class _Tool(NamedTuple):
    name: str
    description: str | None


async def _indexed_description(request: CustomMcpIndexRequest) -> str:
    batch = AsyncMock()
    store = AsyncMock(spec=BaseStore)
    store.abatch = batch

    await index_custom_mcp_as_subagent(store, request)

    (ops,) = batch.await_args.args
    (put_op,) = ops
    assert isinstance(put_op, PutOp)
    assert put_op.namespace == ("subagents",)
    assert put_op.key == "abc123"
    assert put_op.index == ["description"]
    assert put_op.value["id"] == "abc123"
    assert put_op.value["name"] == "Acme"
    assert put_op.value["source"] == "custom"
    return str(put_op.value["description"])


def _request(description: str, tools: list[_Tool] | None) -> CustomMcpIndexRequest:
    return CustomMcpIndexRequest(
        integration_id="abc123", name="Acme", description=description, tools=tools
    )


@pytest.mark.unit
class TestIndexCustomMcpAsSubagent:
    async def test_without_tools_or_description_is_just_the_name(self) -> None:
        assert await _indexed_description(_request("", None)) == "Acme."

    async def test_description_follows_the_name(self) -> None:
        assert await _indexed_description(_request("Docs search", None)) == "Acme. Docs search."

    async def test_tool_summaries_are_joined_with_semicolons(self) -> None:
        tools = [_Tool("search", "Find pages.\nMore detail."), _Tool("fetch", "Get a page")]

        result = await _indexed_description(_request("Docs", tools))

        assert result == "Acme. Docs. Available tools: search: Find pages.; fetch: Get a page."

    async def test_tool_without_description_is_listed_by_name_only(self) -> None:
        tools = [_Tool("none", None), _Tool("blank", "   "), _Tool("ok", "Does ok")]

        result = await _indexed_description(_request("", tools))

        assert result == "Acme. Available tools: none; blank; ok: Does ok."

    async def test_summary_is_cut_to_120_characters(self) -> None:
        tools = [_Tool("long", "x" * 200)]

        result = await _indexed_description(_request("", tools))

        assert result == f"Acme. Available tools: long: {'x' * 120}."
