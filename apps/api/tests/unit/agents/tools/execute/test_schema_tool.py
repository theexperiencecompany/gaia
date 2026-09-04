"""get_tool_schema — the host-side depth behind the discovery pointer."""

import json
from unittest.mock import AsyncMock, patch

import pytest

from app.agents.tools.execute.schema_tool import get_tool_schema
from app.agents.tools.execute.tool_info import ToolInfo

MODULE = "app.agents.tools.execute.schema_tool"
CONFIG = {"configurable": {"user_id": "u1"}}


def _info(**overrides: object) -> ToolInfo:
    defaults: dict = {
        "tool_name": "GMAIL_FETCH_EMAILS",
        "description": "Fetch emails.",
        "input_schema": {"type": "object", "properties": {"max_results": {"type": "integer"}}},
        "provider_output_schema": {
            "type": "object",
            "properties": {"data": {"type": "object"}},
            "required": ["data"],
        },
        "observed_output_schema": None,
        "observed_call_count": 0,
    }
    defaults.update(overrides)
    return ToolInfo(**defaults)


@pytest.mark.unit
class TestGetToolSchema:
    async def test_returns_args_and_type_notation_never_raw_schema_json(self) -> None:
        with patch(f"{MODULE}.full_tool_info", new=AsyncMock(return_value=_info())) as info:
            doc = await get_tool_schema.ainvoke({"tool_name": "GMAIL_FETCH_EMAILS"}, config=CONFIG)
        info.assert_awaited_once_with("u1", "GMAIL_FETCH_EMAILS")
        assert "## GMAIL_FETCH_EMAILS" in doc
        assert '"max_results"' in doc  # args stay JSON schema
        assert "Returns: {data:obj}" in doc  # returns are type notation
        assert '"provider_output_schema"' not in doc  # never the raw dump

    async def test_observed_only_shape_carries_its_confidence(self) -> None:
        info = _info(
            provider_output_schema=None,
            observed_output_schema={"type": "object", "properties": {"ok": {"type": "boolean"}}},
            observed_call_count=17,
        )
        with patch(f"{MODULE}.full_tool_info", new=AsyncMock(return_value=info)):
            doc = await get_tool_schema.ainvoke({"tool_name": "GMAIL_FETCH_EMAILS"}, config=CONFIG)
        assert "Returns: {ok?:bool}" in doc
        assert "observed from 17 real calls" in doc

    async def test_undocumented_shape_says_so_instead_of_inventing_one(self) -> None:
        info = _info(provider_output_schema=None, observed_output_schema=None)
        with patch(f"{MODULE}.full_tool_info", new=AsyncMock(return_value=info)):
            doc = await get_tool_schema.ainvoke({"tool_name": "GMAIL_FETCH_EMAILS"}, config=CONFIG)
        assert "not documented yet" in doc
        assert "Returns: {" not in doc

    async def test_unknown_tool_is_a_structured_error(self) -> None:
        with patch(f"{MODULE}.full_tool_info", new=AsyncMock(return_value=None)):
            doc = await get_tool_schema.ainvoke({"tool_name": "NOPE"}, config=CONFIG)
        body = json.loads(doc)
        assert body["ok"] is False
        assert body["error"] == "unknown_tool"
