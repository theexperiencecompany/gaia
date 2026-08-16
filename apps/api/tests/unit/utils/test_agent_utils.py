"""Tests for app/utils/agent_utils.py"""

import json
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.constants.agents import EXECUTOR_ERROR_MARKER, EXECUTOR_RESULT_MARKER
from app.models.integration_models import Integration
from app.utils.agent_utils import (
    InternalMarkerFilter,
    _lookup_custom_integration_name,
    _resolve_handoff_display_name,
    format_sse_data,
    format_sse_response,
    format_tool_call_entry,
    parse_subagent_id,
    process_custom_event_for_tools,
    strip_internal_agent_markers,
)


def _integration(integration_id: str, name: str) -> Integration:
    return Integration(
        integration_id=integration_id,
        name=name,
        description="",
        category="custom",
        managed_by="mcp",
    )


# ---------------------------------------------------------------------------
# parse_subagent_id
# ---------------------------------------------------------------------------


class TestParseSubagentId:
    def test_with_subagent_prefix_and_brackets(self) -> None:
        clean_id, name = parse_subagent_id("subagent:Researcher [abc-123-uuid]")
        assert clean_id == "abc-123-uuid"
        assert name == "Researcher"

    def test_with_subagent_prefix_and_parens(self) -> None:
        clean_id, name = parse_subagent_id("subagent:my_tool (Tool Name)")
        assert clean_id == "my_tool"
        assert name == "Tool Name"

    def test_plain_id(self) -> None:
        clean_id, name = parse_subagent_id("my_integration")
        assert clean_id == "my_integration"
        assert name is None

    def test_subagent_prefix_plain(self) -> None:
        clean_id, name = parse_subagent_id("subagent:calendar")
        assert clean_id == "calendar"
        assert name is None


# ---------------------------------------------------------------------------
# _lookup_custom_integration_name
# ---------------------------------------------------------------------------


class TestLookupCustomIntegrationName:
    @pytest.mark.asyncio
    async def test_found(self) -> None:
        with patch("app.utils.agent_utils.integration_repository") as mock_repo:
            mock_repo.find_by_id_prefix = AsyncMock(
                return_value=_integration("custom_id_123", "My Custom Tool")
            )
            result = await _lookup_custom_integration_name.__wrapped__("custom_id_123")  # type: ignore[attr-defined]
        assert result == "My Custom Tool"

    @pytest.mark.asyncio
    async def test_not_found(self) -> None:
        with patch("app.utils.agent_utils.integration_repository") as mock_repo:
            mock_repo.find_by_id_prefix = AsyncMock(return_value=None)
            result = await _lookup_custom_integration_name.__wrapped__("unknown_id")  # type: ignore[attr-defined]
        assert result is None


# ---------------------------------------------------------------------------
# _resolve_handoff_display_name
# ---------------------------------------------------------------------------


class TestResolveHandoffDisplayName:
    @pytest.mark.asyncio
    async def test_parsed_name_returned(self) -> None:
        result = await _resolve_handoff_display_name("subagent:Researcher [some-uuid]")
        assert result == "Researcher"

    @pytest.mark.asyncio
    async def test_platform_integration_name(self) -> None:
        mock_subagent = MagicMock()
        mock_subagent.name = "Google Calendar"

        with patch(
            "app.utils.agent_utils.get_subagent_by_id",
            return_value=mock_subagent,
        ):
            result = await _resolve_handoff_display_name("googlecalendar")

        assert result == "Google Calendar"

    @pytest.mark.asyncio
    async def test_custom_integration_from_db(self) -> None:
        with (
            patch(
                "app.utils.agent_utils.get_subagent_by_id",
                return_value=None,
            ),
            patch(
                "app.utils.agent_utils._lookup_custom_integration_name",
                new_callable=AsyncMock,
                return_value="DB Integration",
            ),
        ):
            result = await _resolve_handoff_display_name("custom_tool_id")

        assert result == "DB Integration"

    @pytest.mark.asyncio
    async def test_fallback_to_title_case(self) -> None:
        with (
            patch(
                "app.utils.agent_utils.get_subagent_by_id",
                return_value=None,
            ),
            patch(
                "app.utils.agent_utils._lookup_custom_integration_name",
                new_callable=AsyncMock,
                return_value=None,
            ),
        ):
            result = await _resolve_handoff_display_name("my_cool_tool")

        assert result == "My Cool Tool"


# ---------------------------------------------------------------------------
# format_tool_call_entry
# ---------------------------------------------------------------------------


class TestFormatToolCallEntry:
    @pytest.mark.asyncio
    async def test_missing_tool_name_returns_none(self) -> None:
        tool_call: dict[str, Any] = {"name": None, "args": {}, "id": "tc1"}
        mock_registry = MagicMock()
        with patch(
            "app.utils.agent_utils.get_tool_registry",
            new_callable=AsyncMock,
            return_value=mock_registry,
        ):
            result = await format_tool_call_entry(tool_call)  # type: ignore[arg-type]
        assert result is None

    @pytest.mark.asyncio
    async def test_special_tool_retrieve_tools(self) -> None:
        tool_call = {"name": "retrieve_tools", "args": {}, "id": "tc2"}
        mock_registry = MagicMock()
        mock_registry.get_all_tools_for_search.return_value = []
        with patch(
            "app.utils.agent_utils.get_tool_registry",
            new_callable=AsyncMock,
            return_value=mock_registry,
        ):
            result = await format_tool_call_entry(tool_call)  # type: ignore[arg-type]

        assert result is not None
        assert result["data"]["message"] == "Retrieve tools"
        assert result["data"]["show_category"] is False

    @pytest.mark.asyncio
    async def test_handoff_tool(self) -> None:
        tool_call = {
            "name": "handoff",
            "args": {"subagent_id": "subagent:Calendar [cal-uuid]"},
            "id": "tc3",
        }
        mock_registry = MagicMock()
        mock_registry.get_all_tools_for_search.return_value = []
        with patch(
            "app.utils.agent_utils.get_tool_registry",
            new_callable=AsyncMock,
            return_value=mock_registry,
        ):
            result = await format_tool_call_entry(tool_call)  # type: ignore[arg-type]

        assert result is not None
        assert "Calendar" in result["data"]["message"]
        assert result["data"]["tool_category"] == "handoff"

    @pytest.mark.asyncio
    async def test_regular_tool_with_integration_id(self) -> None:
        tool_call = {"name": "send_email", "args": {}, "id": "tc4"}
        mock_registry = MagicMock()
        mock_registry.get_all_tools_for_search.return_value = []
        with patch(
            "app.utils.agent_utils.get_tool_registry",
            new_callable=AsyncMock,
            return_value=mock_registry,
        ):
            result = await format_tool_call_entry(
                tool_call,  # type: ignore[arg-type]
                integration_id="gmail_integration",
            )

        assert result is not None
        assert result["data"]["tool_category"] == "gmail_integration"
        assert result["data"]["show_category"] is True

    @pytest.mark.asyncio
    async def test_regular_tool_mcp_category_no_uuid(self) -> None:
        tool_call = {"name": "other_tool", "args": {}, "id": "tc6"}
        mock_registry = MagicMock()
        mock_registry.get_category_of_tool.return_value = "mcp_some_server"
        mock_registry.get_all_tools_for_search.return_value = []
        with patch(
            "app.utils.agent_utils.get_tool_registry",
            new_callable=AsyncMock,
            return_value=mock_registry,
        ):
            result = await format_tool_call_entry(tool_call)  # type: ignore[arg-type]

        assert result is not None
        assert result["data"]["tool_category"] == "some_server"

    @pytest.mark.asyncio
    async def test_mcp_ui_metadata_extracted(self) -> None:
        tool_call = {"name": "ui_tool", "args": {}, "id": "tc7"}
        mock_registry_tool = MagicMock()
        mock_registry_tool.name = "ui_tool"
        mock_registry_tool.tool.metadata = {
            "mcp_ui": {"type": "form"},
            "mcp_server_url": "https://mcp.example.com",
        }

        mock_registry = MagicMock()
        mock_registry.get_category_of_tool.return_value = "custom"
        mock_registry.get_all_tools_for_search.return_value = [mock_registry_tool]

        with patch(
            "app.utils.agent_utils.get_tool_registry",
            new_callable=AsyncMock,
            return_value=mock_registry,
        ):
            result = await format_tool_call_entry(tool_call)  # type: ignore[arg-type]

        assert result is not None
        assert result["mcp_ui"] == {"type": "form"}
        assert result["mcp_server_url"] == "https://mcp.example.com"

    @pytest.mark.asyncio
    async def test_integration_name_passed_through(self) -> None:
        tool_call = {"name": "tool_x", "args": {}, "id": "tc8"}
        mock_registry = MagicMock()
        mock_registry.get_category_of_tool.return_value = None
        mock_registry.get_all_tools_for_search.return_value = []

        with patch(
            "app.utils.agent_utils.get_tool_registry",
            new_callable=AsyncMock,
            return_value=mock_registry,
        ):
            result = await format_tool_call_entry(
                tool_call,  # type: ignore[arg-type]
                icon_url="https://icon.png",
                integration_name="My Service",
            )

        assert result["data"]["icon_url"] == "https://icon.png"  # type: ignore[index]
        assert result["data"]["integration_name"] == "My Service"  # type: ignore[index]


# ---------------------------------------------------------------------------
# format_tool_call_entry -> _resolve_mcp_icon_name (custom MCP integration
# icon/name lazy-fill; only reached when integration_id + user_id are set,
# the tool isn't a core tool, and no icon_url was pre-supplied)
# ---------------------------------------------------------------------------


class TestResolveMcpIconName:
    @pytest.mark.asyncio
    async def test_cache_miss_looks_up_db_and_fills_icon_name(self) -> None:
        tool_call = {"name": "custom_mcp_tool", "args": {}, "id": "tc9"}
        mock_registry = MagicMock()
        mock_registry.get_category_of_tool.return_value = None
        mock_registry.get_all_tools_for_search.return_value = []

        integration = _integration("custom_integration_1", "Custom Service")
        integration.icon_url = "https://cdn.example.com/icon.png"

        with (
            patch(
                "app.utils.agent_utils.get_tool_registry",
                new_callable=AsyncMock,
                return_value=mock_registry,
            ),
            patch("app.db.redis.get_cache", new_callable=AsyncMock, return_value=None),
            patch("app.db.redis.set_cache", new_callable=AsyncMock) as mock_set_cache,
            patch(
                "app.utils.agent_utils.integration_repository.get",
                new_callable=AsyncMock,
                return_value=integration,
            ) as mock_repo_get,
        ):
            result = await format_tool_call_entry(
                tool_call,  # type: ignore[arg-type]
                integration_id="custom_integration_1",
                user_id="user123",
            )

        assert result is not None
        assert result["data"]["icon_url"] == "https://cdn.example.com/icon.png"
        assert result["data"]["integration_name"] == "Custom Service"
        mock_repo_get.assert_awaited_once_with("custom_integration_1")
        mock_set_cache.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_cache_hit_skips_db_lookup(self) -> None:
        tool_call = {"name": "custom_mcp_tool", "args": {}, "id": "tc10"}
        mock_registry = MagicMock()
        mock_registry.get_category_of_tool.return_value = None
        mock_registry.get_all_tools_for_search.return_value = []

        cached = {"icon_url": "cached.png", "integration_name": "Cached"}

        with (
            patch(
                "app.utils.agent_utils.get_tool_registry",
                new_callable=AsyncMock,
                return_value=mock_registry,
            ),
            patch("app.db.redis.get_cache", new_callable=AsyncMock, return_value=cached),
            patch(
                "app.utils.agent_utils.integration_repository.get",
                new_callable=AsyncMock,
            ) as mock_repo_get,
        ):
            result = await format_tool_call_entry(
                tool_call,  # type: ignore[arg-type]
                integration_id="custom_integration_2",
                user_id="user123",
            )

        assert result is not None
        assert result["data"]["icon_url"] == "cached.png"
        assert result["data"]["integration_name"] == "Cached"
        mock_repo_get.assert_not_awaited()


# ---------------------------------------------------------------------------
# format_sse_response / format_sse_data
# ---------------------------------------------------------------------------


class TestSSEFormatters:
    def test_format_sse_response(self) -> None:
        result = format_sse_response("Hello world")
        assert result.startswith("data: ")
        assert result.endswith("\n\n")
        parsed = json.loads(result[6:])
        assert parsed["response"] == "Hello world"

    def test_format_sse_data(self) -> None:
        result = format_sse_data({"key": "value", "count": 42})
        assert result.startswith("data: ")
        parsed = json.loads(result[6:])
        assert parsed["key"] == "value"
        assert parsed["count"] == 42


# ---------------------------------------------------------------------------
# process_custom_event_for_tools
# ---------------------------------------------------------------------------


class TestProcessCustomEventForTools:
    def test_with_payload(self) -> None:
        with patch(
            "app.utils.agent_utils.extract_tool_data",
            return_value={"tool": "data"},
        ):
            result = process_custom_event_for_tools({"some": "payload"})
        assert result == {"tool": "data"}

    def test_with_none_payload(self) -> None:
        with patch(
            "app.utils.agent_utils.extract_tool_data",
            return_value=None,
        ):
            result = process_custom_event_for_tools(None)
        assert result == {}

    def test_extract_returns_none(self) -> None:
        with patch(
            "app.utils.agent_utils.extract_tool_data",
            return_value=None,
        ):
            result = process_custom_event_for_tools({"x": 1})
        assert result == {}

    def test_exception_returns_empty(self) -> None:
        with patch(
            "app.utils.agent_utils.extract_tool_data",
            side_effect=RuntimeError("parse fail"),
        ):
            result = process_custom_event_for_tools({"x": 1})
        assert result == {}


@pytest.mark.unit
class TestInternalMarkerFilter:
    def _run(self, chunks: list[str]) -> str:
        marker_filter = InternalMarkerFilter()
        out = "".join(marker_filter.feed(chunk) for chunk in chunks)
        return out + marker_filter.flush()

    def test_marker_split_across_chunks_never_reaches_the_output(self) -> None:
        assert self._run(["[EXECUTOR_", "RESULT]\nYou do not have WhatsApp.", " Want help?"]) == (
            "You do not have WhatsApp. Want help?"
        )

    def test_marker_after_a_message_break_is_removed_too(self) -> None:
        text = f"on it\n\n<NEW_MESSAGE_BREAK>\n\n{EXECUTOR_RESULT_MARKER}\nlooks not linked"
        assert self._run([text]) == "on it\n\n<NEW_MESSAGE_BREAK>\n\nlooks not linked"

    def test_marker_matching_is_case_insensitive_like_the_batch_strip(self) -> None:
        assert self._run(["[executor_result]\n", "done"]) == "done"
        assert self._run([EXECUTOR_ERROR_MARKER, " failed"]) == "failed"

    def test_bracketed_text_that_is_not_a_marker_passes_through(self) -> None:
        assert self._run(["see [the docs] and [EXEC", "UTIVE summary]"]) == (
            "see [the docs] and [EXECUTIVE summary]"
        )

    def test_partial_marker_is_held_then_flushed_when_the_stream_ends(self) -> None:
        marker_filter = InternalMarkerFilter()
        assert marker_filter.feed("hello [EXEC") == "hello "
        assert marker_filter.flush() == "[EXEC"

    def test_leading_whitespace_of_a_message_is_preserved(self) -> None:
        assert self._run(["  hi", " there"]) == "  hi there"

    def test_text_without_a_bracket_is_never_held_back(self) -> None:
        marker_filter = InternalMarkerFilter()
        assert marker_filter.feed("hello") == "hello"
        assert marker_filter.flush() == ""
        assert marker_filter.flush() == ""

    @pytest.mark.parametrize("lead", ["x ", "xx "])
    @pytest.mark.parametrize("prefix", ["[", "[E", "[EX", "[EXECUTOR_RESULT"])
    def test_every_prefix_length_is_held_so_a_split_marker_cannot_leak(
        self, lead: str, prefix: str
    ) -> None:
        rest = EXECUTOR_RESULT_MARKER[len(prefix) :]
        assert self._run([f"{lead}{prefix}", f"{rest}\nhi"]) == f"{lead}hi"

    def test_batch_strip_and_stream_filter_agree(self) -> None:
        text = f"{EXECUTOR_RESULT_MARKER}\nfoo [x] bar"
        assert self._run([text]) == strip_internal_agent_markers(text)
