"""Tests for app/utils/agent_utils.py"""

import json
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.utils.agent_utils import (
    UUID_PATTERN,
    _lookup_custom_integration_name,
    _resolve_handoff_display_name,
    format_sse_data,
    format_sse_response,
    format_tool_call_entry,
    parse_subagent_id,
    process_custom_event_for_tools,
    store_agent_progress,
)


# ---------------------------------------------------------------------------
# UUID_PATTERN
# ---------------------------------------------------------------------------


class TestUUIDPattern:
    def test_valid_uuid(self) -> None:
        assert UUID_PATTERN.match("550e8400-e29b-41d4-a716-446655440000")

    def test_invalid_uuid(self) -> None:
        assert UUID_PATTERN.match("not-a-uuid") is None

    def test_uppercase_uuid(self) -> None:
        assert UUID_PATTERN.match("550E8400-E29B-41D4-A716-446655440000")


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
        with patch("app.utils.agent_utils.integrations_collection") as mock_coll:
            mock_coll.find_one = AsyncMock(return_value={"name": "My Custom Tool"})
            result = await _lookup_custom_integration_name.__wrapped__("custom_id_123")  # type: ignore[attr-defined]
        assert result == "My Custom Tool"

    @pytest.mark.asyncio
    async def test_not_found(self) -> None:
        with patch("app.utils.agent_utils.integrations_collection") as mock_coll:
            mock_coll.find_one = AsyncMock(return_value=None)
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
        mock_integration = MagicMock()
        mock_integration.name = "Google Calendar"

        with patch(
            "app.utils.agent_utils.get_integration_by_id",
            return_value=mock_integration,
        ):
            result = await _resolve_handoff_display_name("googlecalendar")

        assert result == "Google Calendar"

    @pytest.mark.asyncio
    async def test_custom_integration_from_db(self) -> None:
        with (
            patch(
                "app.utils.agent_utils.get_integration_by_id",
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
                "app.utils.agent_utils.get_integration_by_id",
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
        assert result["data"]["message"] == "Retrieving tools"
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
    async def test_regular_tool_mcp_category_with_uuid_suffix(self) -> None:
        tool_call = {"name": "custom_tool", "args": {}, "id": "tc5"}
        mock_registry = MagicMock()
        mock_registry.get_category_of_tool.return_value = (
            "mcp_my_integration_550e8400-e29b-41d4-a716-446655440000"
        )
        mock_registry.get_all_tools_for_search.return_value = []
        with patch(
            "app.utils.agent_utils.get_tool_registry",
            new_callable=AsyncMock,
            return_value=mock_registry,
        ):
            result = await format_tool_call_entry(tool_call)  # type: ignore[arg-type]

        assert result is not None
        assert result["data"]["tool_category"] == "my_integration"

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
            "app.services.chat_service.extract_tool_data",
            return_value={"tool": "data"},
        ):
            result = process_custom_event_for_tools({"some": "payload"})
        assert result == {"tool": "data"}

    def test_with_none_payload(self) -> None:
        with patch(
            "app.services.chat_service.extract_tool_data",
            return_value=None,
        ):
            result = process_custom_event_for_tools(None)
        assert result == {}

    def test_extract_returns_none(self) -> None:
        with patch(
            "app.services.chat_service.extract_tool_data",
            return_value=None,
        ):
            result = process_custom_event_for_tools({"x": 1})
        assert result == {}

    def test_exception_returns_empty(self) -> None:
        with patch(
            "app.services.chat_service.extract_tool_data",
            side_effect=RuntimeError("parse fail"),
        ):
            result = process_custom_event_for_tools({"x": 1})
        assert result == {}


# ---------------------------------------------------------------------------
# store_agent_progress
# ---------------------------------------------------------------------------


class TestStoreAgentProgress:
    @pytest.mark.asyncio
    async def test_no_content_skips_storage(self) -> None:
        with patch(
            "app.utils.agent_utils.update_messages",
            new_callable=AsyncMock,
        ) as mock_update:
            await store_agent_progress("conv1", "u1", "", {})
            mock_update.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_whitespace_only_skips(self) -> None:
        with patch(
            "app.utils.agent_utils.update_messages",
            new_callable=AsyncMock,
        ) as mock_update:
            await store_agent_progress("conv1", "u1", "   ", {})
            mock_update.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_with_message_content(self) -> None:
        with patch(
            "app.utils.agent_utils.update_messages",
            new_callable=AsyncMock,
        ) as mock_update:
            await store_agent_progress("conv1", "u1", "Hello!", {})
            mock_update.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_with_unified_tool_data(self) -> None:
        tool_data = {
            "tool_data": [
                {"tool_name": "search", "data": {"q": "test"}, "timestamp": "now"}
            ]
        }
        with patch(
            "app.utils.agent_utils.update_messages",
            new_callable=AsyncMock,
        ) as mock_update:
            await store_agent_progress("conv1", "u1", "", tool_data)
            mock_update.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_with_legacy_tool_data(self) -> None:
        tool_data: dict[str, Any] = {"calendar_options": {"events": []}}
        with patch(
            "app.utils.agent_utils.update_messages",
            new_callable=AsyncMock,
        ) as mock_update:
            await store_agent_progress("conv1", "u1", "", tool_data)
            mock_update.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_with_follow_up_actions(self) -> None:
        tool_data = {
            "tool_data": [{"tool_name": "t", "data": "d", "timestamp": "ts"}],
            "follow_up_actions": ["action1"],
        }
        with patch(
            "app.utils.agent_utils.update_messages",
            new_callable=AsyncMock,
        ) as mock_update:
            await store_agent_progress("conv1", "u1", "msg", tool_data)
            mock_update.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_storage_error_swallowed(self) -> None:
        with patch(
            "app.utils.agent_utils.update_messages",
            new_callable=AsyncMock,
            side_effect=RuntimeError("db fail"),
        ):
            # Should not raise
            await store_agent_progress("conv1", "u1", "content", {})

    @pytest.mark.asyncio
    async def test_empty_tool_data_dict_no_values(self) -> None:
        """tool_data dict with all None values treated as no content."""
        tool_data = {"tool_data": None}
        with patch(
            "app.utils.agent_utils.update_messages",
            new_callable=AsyncMock,
        ) as mock_update:
            await store_agent_progress("conv1", "u1", "", tool_data)
            mock_update.assert_not_awaited()
