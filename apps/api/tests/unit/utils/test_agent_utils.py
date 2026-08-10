"""Tests for app/utils/agent_utils.py"""

from datetime import UTC, datetime, timedelta
import json
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock, call, patch

import pytest

from app.constants.cache import CUSTOM_INT_METADATA_CACHE_PREFIX, CUSTOM_INT_METADATA_TTL
from app.constants.log_tags import LogTag
from app.models.integration_models import Integration
from app.utils.agent_utils import (
    _lookup_custom_integration_name,
    _resolve_handoff_display_name,
    _resolve_mcp_icon_name,
    _resolve_mcp_integration_id,
    _resolve_mcp_ui_metadata,
    format_sse_data,
    format_sse_response,
    format_subagent_end_event,
    format_subagent_start_event,
    format_tool_call_entry,
    parse_subagent_id,
    process_custom_event_for_tools,
    strip_internal_agent_markers,
)


def _integration(integration_id: str, name: str, icon_url: str | None = None) -> Integration:
    return Integration(
        integration_id=integration_id,
        name=name,
        description="",
        category="custom",
        managed_by="mcp",
        source="custom",
        is_public=False,
        is_featured=False,
        icon_url=icon_url,
    )


def _tool_call(
    name: str, args: dict[str, Any] | None = None, tool_id: str = "tc"
) -> dict[str, Any]:
    call: dict[str, Any] = {"name": name, "id": tool_id}
    if args is not None:
        call["args"] = args
    return call


def _registry(category: str | None = None, tools: list[Any] | None = None) -> MagicMock:
    registry = MagicMock()
    registry.get_category_of_tool.return_value = category
    registry.get_all_tools_for_search.return_value = tools or []
    return registry


def _mcp_client_with_tool(name: str, metadata: Any) -> MagicMock:
    tool = MagicMock()
    tool.name = name
    tool.metadata = metadata
    client = MagicMock()
    client._tools = {"int_a": [tool]}
    return client


async def _format_entry(tool_call: dict[str, Any], registry: MagicMock, **kwargs: Any) -> Any:
    with patch(
        "app.utils.agent_utils.get_tool_registry",
        new_callable=AsyncMock,
        return_value=registry,
    ):
        return await format_tool_call_entry(tool_call, **kwargs)  # type: ignore[arg-type]


def _assert_utc_iso_timestamp(value: Any) -> None:
    assert isinstance(value, str)
    timestamp = datetime.fromisoformat(value)
    assert timestamp.tzinfo is not None
    assert timestamp.utcoffset() == timedelta(0)
    assert abs((datetime.now(UTC) - timestamp).total_seconds()) < 60


# ---------------------------------------------------------------------------
# strip_internal_agent_markers
# ---------------------------------------------------------------------------


class TestStripInternalAgentMarkers:
    def test_strips_executor_result_marker(self) -> None:
        assert (
            strip_internal_agent_markers("[EXECUTOR_RESULT]Here is the answer")
            == "Here is the answer"
        )

    def test_strips_every_marker(self) -> None:
        text = (
            "[EXECUTOR_RESULT][EXECUTOR_ERROR][EXECUTOR_CANCELLED]"
            "[RETURNED_TO_FRONTEND][PLATFORM_DELIVERY]Done"
        )
        assert strip_internal_agent_markers(text) == "Done"

    def test_case_insensitive(self) -> None:
        assert strip_internal_agent_markers("[executor_result] answer") == "answer"

    def test_marker_in_the_middle_leaves_inner_spaces(self) -> None:
        assert strip_internal_agent_markers("answer [RETURNED_TO_FRONTEND] here") == "answer  here"

    def test_no_markers_passthrough(self) -> None:
        assert strip_internal_agent_markers("plain text") == "plain text"

    def test_marker_only_input_strips_to_empty(self) -> None:
        assert strip_internal_agent_markers("[EXECUTOR_RESULT]") == ""

    def test_surrounding_whitespace_stripped(self) -> None:
        assert strip_internal_agent_markers("  [EXECUTOR_RESULT] answer  ") == "answer"


# ---------------------------------------------------------------------------
# format_subagent_start_event / format_subagent_end_event
# ---------------------------------------------------------------------------


class TestFormatSubagentEvents:
    def test_start_event_with_all_fields(self) -> None:
        result = format_subagent_start_event(
            subagent_name="Researcher",
            agent_type="research",
            subagent_id="sub-1",
            icon_url="https://icon.png",
            tool_category="research",
            parent_subagent_id="parent-0",
        )

        assert result["subagent_id"] == "sub-1"
        assert result["subagent_name"] == "Researcher"
        assert result["agent_type"] == "research"
        assert result["icon_url"] == "https://icon.png"
        assert result["tool_category"] == "research"
        assert result["parent_subagent_id"] == "parent-0"
        _assert_utc_iso_timestamp(result["started_at"])
        assert set(result) == {
            "subagent_id",
            "subagent_name",
            "agent_type",
            "started_at",
            "icon_url",
            "tool_category",
            "parent_subagent_id",
        }

    def test_start_event_excludes_none_fields(self) -> None:
        result = format_subagent_start_event(
            subagent_name="Researcher",
            agent_type="research",
            subagent_id="sub-1",
        )

        assert set(result) == {"subagent_id", "subagent_name", "agent_type", "started_at"}

    def test_start_event_partial_optionals(self) -> None:
        result = format_subagent_start_event(
            subagent_name="Researcher",
            agent_type="research",
            subagent_id="sub-1",
            icon_url="https://icon.png",
        )

        assert result["icon_url"] == "https://icon.png"
        assert "tool_category" not in result
        assert "parent_subagent_id" not in result

    def test_end_event_with_token_count(self) -> None:
        result = format_subagent_end_event(subagent_id="sub-1", duration_ms=1234, token_count=567)

        assert result == {"subagent_id": "sub-1", "duration_ms": 1234, "token_count": 567}

    def test_end_event_without_token_count_includes_null(self) -> None:
        result = format_subagent_end_event(subagent_id="sub-1", duration_ms=1234)

        assert result == {"subagent_id": "sub-1", "duration_ms": 1234, "token_count": None}


# ---------------------------------------------------------------------------
# parse_subagent_id
# ---------------------------------------------------------------------------


class TestParseSubagentId:
    def test_with_subagent_prefix_and_brackets(self) -> None:
        assert parse_subagent_id("subagent:Researcher [abc-123-uuid]") == (
            "abc-123-uuid",
            "Researcher",
        )

    def test_with_subagent_prefix_and_parens(self) -> None:
        assert parse_subagent_id("subagent:my_tool (Tool Name)") == ("my_tool", "Tool Name")

    def test_plain_id(self) -> None:
        assert parse_subagent_id("my_integration") == ("my_integration", None)

    def test_subagent_prefix_plain(self) -> None:
        assert parse_subagent_id("subagent:calendar") == ("calendar", None)

    def test_name_with_spaces_in_brackets(self) -> None:
        assert parse_subagent_id("subagent:Deep Research [u1]") == ("u1", "Deep Research")

    def test_id_with_spaces_in_parens(self) -> None:
        assert parse_subagent_id("subagent:my tool (Name)") == ("my tool", "Name")

    def test_id_with_trailing_x_in_brackets(self) -> None:
        assert parse_subagent_id("subagent:N [abcX]") == ("abcX", "N")

    def test_name_with_trailing_x_in_parens(self) -> None:
        assert parse_subagent_id("subagent:my_tool (Tool NamX)") == ("my_tool", "Tool NamX")

    def test_leading_and_trailing_whitespace_stripped(self) -> None:
        assert parse_subagent_id("  subagent:my_tool (Tool Name)  ") == ("my_tool", "Tool Name")

    def test_bare_id_with_whitespace_stripped(self) -> None:
        assert parse_subagent_id("  my_tool  ") == ("my_tool", None)


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
        mock_repo.find_by_id_prefix.assert_awaited_once_with("custom_id_123")

    @pytest.mark.asyncio
    async def test_not_found(self) -> None:
        with patch("app.utils.agent_utils.integration_repository") as mock_repo:
            mock_repo.find_by_id_prefix = AsyncMock(return_value=None)
            result = await _lookup_custom_integration_name.__wrapped__("unknown_id")  # type: ignore[attr-defined]
        assert result is None
        mock_repo.find_by_id_prefix.assert_awaited_once_with("unknown_id")


# ---------------------------------------------------------------------------
# _resolve_handoff_display_name
# ---------------------------------------------------------------------------


class TestResolveHandoffDisplayName:
    @pytest.mark.asyncio
    async def test_parsed_name_returned(self) -> None:
        assert (
            await _resolve_handoff_display_name("subagent:Researcher [some-uuid]") == "Researcher"
        )

    @pytest.mark.asyncio
    async def test_parsed_parens_name_returned(self) -> None:
        assert await _resolve_handoff_display_name("subagent:my_tool (Tool Name)") == "Tool Name"

    @pytest.mark.asyncio
    async def test_platform_integration_name(self) -> None:
        mock_subagent = MagicMock()
        mock_subagent.name = "Google Calendar"

        with patch(
            "app.utils.agent_utils.get_subagent_by_id",
            return_value=mock_subagent,
        ) as mock_get:
            result = await _resolve_handoff_display_name("googlecalendar")

        assert result == "Google Calendar"
        mock_get.assert_called_once_with("googlecalendar")

    @pytest.mark.asyncio
    async def test_custom_integration_from_db(self) -> None:
        with (
            patch(
                "app.utils.agent_utils.get_subagent_by_id",
                return_value=None,
            ) as mock_get,
            patch(
                "app.utils.agent_utils._lookup_custom_integration_name",
                new_callable=AsyncMock,
                return_value="DB Integration",
            ) as mock_lookup,
        ):
            result = await _resolve_handoff_display_name("custom_tool_id")

        assert result == "DB Integration"
        mock_get.assert_called_once_with("custom_tool_id")
        mock_lookup.assert_awaited_once_with("custom_tool_id")

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
            assert await _resolve_handoff_display_name("my_cool_tool") == "My Cool Tool"

    @pytest.mark.asyncio
    async def test_fallback_to_title_case_without_underscores(self) -> None:
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
            assert await _resolve_handoff_display_name("researcher") == "Researcher"

    @pytest.mark.asyncio
    async def test_empty_cached_name_falls_through_to_title_case(self) -> None:
        with (
            patch(
                "app.utils.agent_utils.get_subagent_by_id",
                return_value=None,
            ),
            patch(
                "app.utils.agent_utils._lookup_custom_integration_name",
                new_callable=AsyncMock,
                return_value="",
            ),
        ):
            assert await _resolve_handoff_display_name("my_tool") == "My Tool"


# ---------------------------------------------------------------------------
# format_tool_call_entry
# ---------------------------------------------------------------------------


class TestFormatToolCallEntry:
    @pytest.mark.asyncio
    async def test_missing_tool_name_returns_none(self) -> None:
        result = await _format_entry({"name": None, "args": {}, "id": "tc1"}, _registry())
        assert result is None

    @pytest.mark.asyncio
    async def test_empty_tool_name_returns_none(self) -> None:
        result = await _format_entry({"name": "", "args": {}, "id": "tc1"}, _registry())
        assert result is None

    @pytest.mark.asyncio
    async def test_missing_name_key_returns_none(self) -> None:
        result = await _format_entry({"args": {}, "id": "tc1"}, _registry())
        assert result is None

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        ("tool_name", "expected_category", "expected_message"),
        [
            ("retrieve_tools", "retrieve_tools", "Retrieve tools"),
            ("call_executor", "executor", "Delegating to executor"),
            ("cancel_executor", "cancel_executor", "Cancelling the task"),
            ("spawn_subagent", "spawn_subagent", "Spawn subagent"),
            ("wait_for_subagents", "wait_for_subagents", "Wait for subagents"),
            ("plan_tasks", "plan_tasks", "Plan tasks"),
            ("update_tasks", "plan_tasks", "Update tasks"),
            ("finish_task", "finish_task", "Finish task"),
        ],
    )
    async def test_special_tools(
        self, tool_name: str, expected_category: str, expected_message: str
    ) -> None:
        registry = _registry()
        result = await _format_entry(
            _tool_call(tool_name, args={"k": "v"}, tool_id="tc-special"),
            registry,
        )

        assert result is not None
        assert result["tool_name"] == "tool_calls_data"
        assert result["tool_category"] == expected_category
        assert result["data"]["tool_name"] == tool_name
        assert result["data"]["tool_category"] == expected_category
        assert result["data"]["message"] == expected_message
        assert result["data"]["show_category"] is False
        assert result["data"]["tool_call_id"] == "tc-special"
        assert result["data"]["inputs"] == {"k": "v"}
        registry.get_category_of_tool.assert_not_called()
        registry.get_all_tools_for_search.assert_called_once_with()

    @pytest.mark.asyncio
    async def test_handoff_tool_resolves_display_name(self) -> None:
        result = await _format_entry(
            _tool_call("handoff", args={"subagent_id": "subagent:Calendar [cal-uuid]"}),
            _registry(),
        )

        assert result is not None
        assert result["data"]["message"] == "Handing off to Calendar"
        assert result["data"]["tool_category"] == "handoff"
        assert result["data"]["show_category"] is False

    @pytest.mark.asyncio
    async def test_handoff_tool_platform_subagent(self) -> None:
        mock_subagent = MagicMock()
        mock_subagent.name = "Google Calendar"

        with patch(
            "app.utils.agent_utils.get_subagent_by_id",
            return_value=mock_subagent,
        ) as mock_get:
            result = await _format_entry(
                _tool_call("handoff", args={"subagent_id": "googlecalendar"}),
                _registry(),
            )

        assert result is not None
        assert result["data"]["message"] == "Handing off to Google Calendar"
        mock_get.assert_called_once_with("googlecalendar")

    @pytest.mark.asyncio
    async def test_handoff_tool_default_subagent_id(self) -> None:
        with patch(
            "app.utils.agent_utils._resolve_handoff_display_name",
            new_callable=AsyncMock,
            return_value="Subagent",
        ) as mock_resolve:
            result = await _format_entry(_tool_call("handoff", args={}), _registry())

        assert result is not None
        assert result["data"]["message"] == "Handing off to Subagent"
        mock_resolve.assert_awaited_once_with("subagent")

    @pytest.mark.asyncio
    async def test_handoff_tool_missing_args_key(self) -> None:
        with patch(
            "app.utils.agent_utils._resolve_handoff_display_name",
            new_callable=AsyncMock,
            return_value="Subagent",
        ) as mock_resolve:
            result = await _format_entry(_tool_call("handoff"), _registry())

        assert result is not None
        assert result["data"]["message"] == "Handing off to Subagent"
        assert result["data"]["inputs"] == {}
        mock_resolve.assert_awaited_once_with("subagent")

    @pytest.mark.asyncio
    async def test_regular_tool_with_integration_id(self) -> None:
        registry = _registry()
        result = await _format_entry(
            _tool_call("send_email", args={"to": "x@y.z"}, tool_id="tc4"),
            registry,
            integration_id="gmail_integration",
        )

        assert result is not None
        assert result["tool_category"] == "gmail_integration"
        assert result["data"]["tool_category"] == "gmail_integration"
        assert result["data"]["message"] == "Send Email"
        assert result["data"]["show_category"] is True
        assert result["data"]["tool_call_id"] == "tc4"
        assert result["data"]["inputs"] == {"to": "x@y.z"}
        registry.get_category_of_tool.assert_called_once_with("send_email")

    @pytest.mark.asyncio
    async def test_curated_tool_label_and_no_category_line(self) -> None:
        registry = _registry(category="calendar")
        result = await _format_entry(_tool_call("GOOGLECALENDAR_CUSTOM_FETCH_EVENTS"), registry)

        assert result is not None
        assert result["data"]["message"] == "Checking your calendar"
        assert result["data"]["tool_category"] == "calendar"
        assert result["data"]["show_category"] is False

    @pytest.mark.asyncio
    async def test_toolkit_prefix_stripped_from_message(self) -> None:
        registry = _registry(category="googlecalendar")
        result = await _format_entry(_tool_call("GOOGLECALENDAR_FETCH_EVENTS"), registry)

        assert result is not None
        assert result["data"]["message"] == "Fetch Events"

    @pytest.mark.asyncio
    async def test_unknown_category_is_not_core(self) -> None:
        registry = _registry(category="unknown")
        result = await _format_entry(_tool_call("mystery_tool"), registry, integration_id="mcp_int")

        assert result is not None
        assert result["data"]["tool_category"] == "mcp_int"

    @pytest.mark.asyncio
    async def test_integration_id_wins_over_mcp_registry_category(self) -> None:
        registry = _registry(category="mcp_some_server")
        result = await _format_entry(
            _tool_call("mcp_tool"), registry, integration_id="custom_mcp_id"
        )

        assert result is not None
        assert result["data"]["tool_category"] == "custom_mcp_id"

    @pytest.mark.asyncio
    async def test_mcp_registry_category_stripped_without_integration_id(self) -> None:
        registry = _registry(category="mcp_some_server")
        result = await _format_entry(_tool_call("other_tool"), registry)

        assert result is not None
        assert result["data"]["tool_category"] == "some_server"
        assert result["data"]["message"] == "Other"

    @pytest.mark.asyncio
    async def test_core_tool_drops_integration_identity(self) -> None:
        registry = _registry(category="vfs")
        result = await _format_entry(
            _tool_call("vfs_cmd"),
            registry,
            integration_id="mcp_custom",
            integration_name="Custom Server",
            icon_url="https://icon.png",
        )

        assert result is not None
        assert result["data"]["tool_category"] == "vfs"
        assert result["data"]["icon_url"] is None
        assert result["data"]["integration_name"] is None

    @pytest.mark.asyncio
    async def test_core_tool_preserves_icon_without_integration_id(self) -> None:
        registry = _registry(category="vfs")
        result = await _format_entry(
            _tool_call("vfs_cmd"),
            registry,
            icon_url="https://icon.png",
            integration_name="Custom Server",
        )

        assert result is not None
        assert result["data"]["icon_url"] == "https://icon.png"
        assert result["data"]["integration_name"] == "Custom Server"

    @pytest.mark.asyncio
    async def test_core_tool_does_not_use_mcp_client(self) -> None:
        registry_tool = MagicMock()
        registry_tool.name = "vfs_cmd"
        registry_tool.tool.metadata = {"mcp_ui": {"type": "form"}}
        registry = _registry(category="vfs", tools=[registry_tool])
        mock_client = MagicMock()
        mock_client._tools = {}

        with (
            patch(
                "app.services.mcp.mcp_client.get_mcp_client",
                new_callable=AsyncMock,
                return_value=mock_client,
            ) as mock_get,
            patch("app.db.redis.get_cache", new_callable=AsyncMock) as mock_get_cache,
        ):
            result = await _format_entry(
                _tool_call("vfs_cmd"),
                registry,
                integration_id="mcp_custom",
                user_id="user-1",
            )

        assert result is not None
        assert result["mcp_ui"] == {"type": "form"}
        assert result["data"]["icon_url"] is None
        mock_get.assert_not_awaited()
        mock_get_cache.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_core_tool_without_integration_skips_mcp_resolution(self) -> None:
        registry_tool = MagicMock()
        registry_tool.name = "vfs_cmd"
        registry_tool.tool.metadata = {"mcp_ui": {"type": "form"}}
        registry = _registry(category="vfs", tools=[registry_tool])
        mock_client = MagicMock()
        mock_client._tools = {}

        with patch(
            "app.services.mcp.mcp_client.get_mcp_client",
            new_callable=AsyncMock,
            return_value=mock_client,
        ) as mock_get:
            result = await _format_entry(_tool_call("vfs_cmd"), registry, user_id="user-1")

        assert result is not None
        assert result["mcp_ui"] == {"type": "form"}
        mock_get.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_mcp_integration_and_ui_resolved_via_user_client(self) -> None:
        registry = _registry()
        ui_tool = MagicMock()
        ui_tool.name = "custom_mcp_tool"
        ui_tool.metadata = {
            "mcp_ui": {"type": "form"},
            "mcp_server_url": "https://mcp.example.com",
        }
        mock_client = MagicMock()
        mock_client.find_integration.return_value = "mcp_server_x"
        mock_client._tools = {"mcp_server_x": [ui_tool]}

        with patch(
            "app.services.mcp.mcp_client.get_mcp_client",
            new_callable=AsyncMock,
            return_value=mock_client,
        ) as mock_get:
            result = await _format_entry(_tool_call("custom_mcp_tool"), registry, user_id="user-1")

        assert result is not None
        assert result["data"]["tool_category"] == "mcp_server_x"
        assert result["mcp_ui"] == {"type": "form"}
        assert result["mcp_server_url"] == "https://mcp.example.com"
        mock_client.find_integration.assert_called_once_with("custom_mcp_tool")
        assert mock_get.await_args_list == [call("user-1"), call("user-1")]

    @pytest.mark.asyncio
    async def test_mcp_tool_without_integration_falls_back_to_registry_category(self) -> None:
        registry = _registry(category="mcp_unknown_server")
        mock_client = MagicMock()
        mock_client.find_integration.return_value = None
        mock_client._tools = {}

        with patch(
            "app.services.mcp.mcp_client.get_mcp_client",
            new_callable=AsyncMock,
            return_value=mock_client,
        ):
            result = await _format_entry(_tool_call("orphan_tool"), registry, user_id="user-1")

        assert result is not None
        assert result["data"]["tool_category"] == "unknown_server"

    @pytest.mark.asyncio
    async def test_mcp_resolution_failure_logs_and_continues(self) -> None:
        registry = _registry()

        with (
            patch(
                "app.services.mcp.mcp_client.get_mcp_client",
                new_callable=AsyncMock,
                side_effect=RuntimeError("client boom"),
            ),
            patch("app.utils.agent_utils.log") as mock_log,
        ):
            result = await _format_entry(_tool_call("custom_mcp_tool"), registry, user_id="user-1")

        assert result is not None
        assert result["data"]["tool_category"] == ""
        assert mock_log.warning.call_count == 2
        assert mock_log.warning.call_args.kwargs["error"] == "client boom"

    @pytest.mark.asyncio
    async def test_special_tool_lazy_fills_integration_icon(self) -> None:
        registry = _registry()
        mock_client = MagicMock()
        mock_client._tools = {}

        with (
            patch(
                "app.db.redis.get_cache", new_callable=AsyncMock, return_value=None
            ) as mock_get_cache,
            patch("app.db.redis.set_cache", new_callable=AsyncMock),
            patch("app.utils.agent_utils.integration_repository") as mock_repo,
            patch(
                "app.services.mcp.mcp_client.get_mcp_client",
                new_callable=AsyncMock,
                return_value=mock_client,
            ),
        ):
            mock_repo.get = AsyncMock(
                return_value=_integration("mcp_x", "Custom X", icon_url="https://icon.png")
            )
            result = await _format_entry(
                _tool_call("retrieve_tools"),
                registry,
                integration_id="mcp_x",
                user_id="user-1",
            )

        assert result is not None
        assert result["data"]["icon_url"] == "https://icon.png"
        assert result["data"]["integration_name"] == "Custom X"
        mock_get_cache.assert_awaited_once_with(f"{CUSTOM_INT_METADATA_CACHE_PREFIX}:mcp_x")

    @pytest.mark.asyncio
    async def test_provided_icon_skips_lazy_fill_and_mcp_client(self) -> None:
        registry_tool = MagicMock()
        registry_tool.name = "custom_mcp_tool"
        registry_tool.tool.metadata = {"mcp_ui": {"type": "form"}}
        registry = _registry(tools=[registry_tool])
        mock_client = MagicMock()
        mock_client._tools = {}

        with (
            patch("app.db.redis.get_cache", new_callable=AsyncMock) as mock_get_cache,
            patch("app.utils.agent_utils.integration_repository") as mock_repo,
            patch(
                "app.services.mcp.mcp_client.get_mcp_client",
                new_callable=AsyncMock,
                return_value=mock_client,
            ) as mock_get,
        ):
            result = await _format_entry(
                _tool_call("custom_mcp_tool"),
                registry,
                integration_id="mcp_int",
                icon_url="https://icon.png",
                user_id="user-1",
            )

        assert result is not None
        assert result["data"]["icon_url"] == "https://icon.png"
        mock_get_cache.assert_not_awaited()
        mock_repo.get.assert_not_called()
        mock_get.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_registry_scan_failure_falls_back_to_user_mcp_and_logs(self) -> None:
        registry = _registry(category="custom")
        registry.get_all_tools_for_search.side_effect = RuntimeError("scan boom")
        mock_client = _mcp_client_with_tool(
            "ui_tool",
            {"mcp_ui": {"type": "table"}, "mcp_server_url": "https://user-mcp.example.com"},
        )

        with (
            patch(
                "app.services.mcp.mcp_client.get_mcp_client",
                new_callable=AsyncMock,
                return_value=mock_client,
            ),
            patch("app.utils.agent_utils.log") as mock_log,
        ):
            result = await _format_entry(_tool_call("ui_tool"), registry, user_id="user-1")

        assert result is not None
        assert result["mcp_ui"] == {"type": "table"}
        assert result["mcp_server_url"] == "https://user-mcp.example.com"
        mock_log.debug.assert_called_once()
        assert (
            mock_log.debug.call_args.args[0]
            == f"{LogTag.AGENT} Tool registry lookup failed for mcp_ui metadata"
        )
        assert mock_log.debug.call_args.kwargs["error"] == "scan boom"
        assert mock_log.debug.call_args.kwargs["error_type"] == "RuntimeError"

    @pytest.mark.asyncio
    async def test_mcp_ui_metadata_extracted(self) -> None:
        registry_tool = MagicMock()
        registry_tool.name = "ui_tool"
        registry_tool.tool.metadata = {
            "mcp_ui": {"type": "form"},
            "mcp_server_url": "https://mcp.example.com",
        }
        registry = _registry(category="custom", tools=[registry_tool])

        result = await _format_entry(_tool_call("ui_tool"), registry)

        assert result is not None
        assert result["mcp_ui"] == {"type": "form"}
        assert result["mcp_server_url"] == "https://mcp.example.com"

    @pytest.mark.asyncio
    async def test_mcp_ui_metadata_non_dict_ignored(self) -> None:
        registry_tool = MagicMock()
        registry_tool.name = "ui_tool"
        registry_tool.tool.metadata = "not-a-dict"
        registry = _registry(category="custom", tools=[registry_tool])

        with patch("app.utils.agent_utils.log") as mock_log:
            result = await _format_entry(_tool_call("ui_tool"), registry)

        assert result is not None
        assert result["mcp_ui"] is None
        assert result["mcp_server_url"] is None
        mock_log.debug.assert_not_called()

    @pytest.mark.asyncio
    async def test_registry_tool_without_metadata_attr(self) -> None:
        registry_tool = SimpleNamespace(name="ui_tool", tool=SimpleNamespace())
        registry = _registry(category="custom", tools=[registry_tool])

        with patch("app.utils.agent_utils.log") as mock_log:
            result = await _format_entry(_tool_call("ui_tool"), registry)

        assert result is not None
        assert result["mcp_ui"] is None
        assert result["mcp_server_url"] is None
        mock_log.debug.assert_not_called()

    @pytest.mark.asyncio
    async def test_payload_shape_without_category(self) -> None:
        result = await _format_entry(_tool_call("send_email", tool_id="tc-payload"), _registry())

        assert result is not None
        assert result["tool_name"] == "tool_calls_data"
        assert result["tool_category"] == ""
        assert result["data"]["tool_category"] == ""
        assert result["data"]["message"] == "Send Email"
        assert result["data"]["show_category"] is True
        assert result["data"]["tool_call_id"] == "tc-payload"
        assert result["data"]["inputs"] == {}
        assert result["data"]["icon_url"] is None
        assert result["data"]["integration_name"] is None
        assert result["mcp_ui"] is None
        assert result["mcp_server_url"] is None
        _assert_utc_iso_timestamp(result["timestamp"])

    @pytest.mark.asyncio
    async def test_integration_name_passed_through(self) -> None:
        registry = _registry()
        result = await _format_entry(
            _tool_call("tool_x"),
            registry,
            icon_url="https://icon.png",
            integration_name="My Service",
        )

        assert result is not None
        assert result["data"]["icon_url"] == "https://icon.png"
        assert result["data"]["integration_name"] == "My Service"
        assert result["data"]["message"] == "X"

    @pytest.mark.asyncio
    async def test_missing_tool_call_id_yields_none(self) -> None:
        tool_call: dict[str, Any] = {"name": "some_tool", "args": {}}
        result = await _format_entry(tool_call, _registry())

        assert result is not None
        assert result["data"]["tool_call_id"] is None

    @pytest.mark.asyncio
    async def test_mcp_ui_metadata_without_server_url(self) -> None:
        registry_tool = MagicMock()
        registry_tool.name = "ui_tool"
        registry_tool.tool.metadata = {"mcp_ui": {"type": "form"}}
        registry = _registry(category="custom", tools=[registry_tool])

        result = await _format_entry(_tool_call("ui_tool"), registry)

        assert result is not None
        assert result["mcp_ui"] == {"type": "form"}
        assert result["mcp_server_url"] is None


# ---------------------------------------------------------------------------
# _resolve_mcp_integration_id
# ---------------------------------------------------------------------------


class TestResolveMcpIntegrationId:
    @pytest.mark.asyncio
    async def test_found(self) -> None:
        mock_client = MagicMock()
        mock_client.find_integration.return_value = "mcp_gmail"

        with patch(
            "app.services.mcp.mcp_client.get_mcp_client",
            new_callable=AsyncMock,
            return_value=mock_client,
        ) as mock_get:
            assert await _resolve_mcp_integration_id("GMAIL_SEND_EMAIL", "user-1") == "mcp_gmail"

        mock_get.assert_awaited_once_with("user-1")
        mock_client.find_integration.assert_called_once_with("GMAIL_SEND_EMAIL")

    @pytest.mark.asyncio
    async def test_not_found(self) -> None:
        mock_client = MagicMock()
        mock_client.find_integration.return_value = None

        with patch(
            "app.services.mcp.mcp_client.get_mcp_client",
            new_callable=AsyncMock,
            return_value=mock_client,
        ):
            assert await _resolve_mcp_integration_id("no_such_tool", "user-1") is None

    @pytest.mark.asyncio
    async def test_client_error_logs_and_returns_none(self) -> None:
        with (
            patch(
                "app.services.mcp.mcp_client.get_mcp_client",
                new_callable=AsyncMock,
                side_effect=RuntimeError("boom"),
            ),
            patch("app.utils.agent_utils.log") as mock_log,
        ):
            assert await _resolve_mcp_integration_id("tool", "user-1") is None

        mock_log.warning.assert_called_once()
        assert (
            mock_log.warning.call_args.args[0]
            == f"{LogTag.AGENT} MCP integration lookup failed for"
        )
        assert mock_log.warning.call_args.kwargs["tool_name"] == "tool"
        assert mock_log.warning.call_args.kwargs["user_id"] == "user-1"
        assert mock_log.warning.call_args.kwargs["error"] == "boom"
        assert mock_log.warning.call_args.kwargs["error_type"] == "RuntimeError"


# ---------------------------------------------------------------------------
# _resolve_mcp_ui_metadata
# ---------------------------------------------------------------------------


class TestResolveMcpUiMetadata:
    @pytest.mark.asyncio
    async def test_found(self) -> None:
        mock_client = _mcp_client_with_tool(
            "ui_tool",
            {"mcp_ui": {"type": "form"}, "mcp_server_url": "https://mcp.example.com"},
        )

        with patch(
            "app.services.mcp.mcp_client.get_mcp_client",
            new_callable=AsyncMock,
            return_value=mock_client,
        ) as mock_get:
            mcp_ui, mcp_server_url = await _resolve_mcp_ui_metadata("ui_tool", "user-1")

        assert mcp_ui == {"type": "form"}
        assert mcp_server_url == "https://mcp.example.com"
        mock_get.assert_awaited_once_with("user-1")

    @pytest.mark.asyncio
    async def test_tool_without_metadata(self) -> None:
        mock_client = _mcp_client_with_tool("ui_tool", None)

        with patch(
            "app.services.mcp.mcp_client.get_mcp_client",
            new_callable=AsyncMock,
            return_value=mock_client,
        ):
            assert await _resolve_mcp_ui_metadata("ui_tool", "user-1") == (None, None)

    @pytest.mark.asyncio
    async def test_tool_with_non_dict_metadata(self) -> None:
        mock_client = _mcp_client_with_tool("ui_tool", "not-a-dict")

        with (
            patch(
                "app.services.mcp.mcp_client.get_mcp_client",
                new_callable=AsyncMock,
                return_value=mock_client,
            ),
            patch("app.utils.agent_utils.log") as mock_log,
        ):
            assert await _resolve_mcp_ui_metadata("ui_tool", "user-1") == (None, None)

        mock_log.warning.assert_not_called()

    @pytest.mark.asyncio
    async def test_tool_without_metadata_attr(self) -> None:
        tool = SimpleNamespace(name="ui_tool")
        mock_client = MagicMock()
        mock_client._tools = {"int_a": [tool]}

        with (
            patch(
                "app.services.mcp.mcp_client.get_mcp_client",
                new_callable=AsyncMock,
                return_value=mock_client,
            ),
            patch("app.utils.agent_utils.log") as mock_log,
        ):
            assert await _resolve_mcp_ui_metadata("ui_tool", "user-1") == (None, None)

        mock_log.warning.assert_not_called()

    @pytest.mark.asyncio
    async def test_tool_not_found(self) -> None:
        mock_client = _mcp_client_with_tool("other_tool", {"mcp_ui": {}})

        with patch(
            "app.services.mcp.mcp_client.get_mcp_client",
            new_callable=AsyncMock,
            return_value=mock_client,
        ):
            assert await _resolve_mcp_ui_metadata("ui_tool", "user-1") == (None, None)

    @pytest.mark.asyncio
    async def test_metadata_with_only_mcp_ui(self) -> None:
        mock_client = _mcp_client_with_tool("ui_tool", {"mcp_ui": {"type": "form"}})

        with patch(
            "app.services.mcp.mcp_client.get_mcp_client",
            new_callable=AsyncMock,
            return_value=mock_client,
        ):
            assert await _resolve_mcp_ui_metadata("ui_tool", "user-1") == ({"type": "form"}, None)

    @pytest.mark.asyncio
    async def test_metadata_with_only_server_url(self) -> None:
        mock_client = _mcp_client_with_tool(
            "ui_tool", {"mcp_server_url": "https://mcp.example.com"}
        )

        with patch(
            "app.services.mcp.mcp_client.get_mcp_client",
            new_callable=AsyncMock,
            return_value=mock_client,
        ):
            assert await _resolve_mcp_ui_metadata("ui_tool", "user-1") == (
                None,
                "https://mcp.example.com",
            )

    @pytest.mark.asyncio
    async def test_client_error_logs_and_returns_none(self) -> None:
        with (
            patch(
                "app.services.mcp.mcp_client.get_mcp_client",
                new_callable=AsyncMock,
                side_effect=RuntimeError("boom"),
            ),
            patch("app.utils.agent_utils.log") as mock_log,
        ):
            assert await _resolve_mcp_ui_metadata("ui_tool", "user-1") == (None, None)

        mock_log.warning.assert_called_once()
        assert (
            mock_log.warning.call_args.args[0]
            == f"{LogTag.AGENT} MCP UI metadata lookup failed for"
        )
        assert mock_log.warning.call_args.kwargs["tool_name"] == "ui_tool"
        assert mock_log.warning.call_args.kwargs["user_id"] == "user-1"
        assert mock_log.warning.call_args.kwargs["error"] == "boom"
        assert mock_log.warning.call_args.kwargs["error_type"] == "RuntimeError"


# ---------------------------------------------------------------------------
# _resolve_mcp_icon_name
# ---------------------------------------------------------------------------


class TestResolveMcpIconName:
    @pytest.mark.asyncio
    async def test_cache_hit(self) -> None:
        with (
            patch(
                "app.db.redis.get_cache",
                new_callable=AsyncMock,
                return_value={"icon_url": "https://icon.png", "integration_name": "My MCP"},
            ) as mock_get_cache,
            patch("app.db.redis.set_cache", new_callable=AsyncMock) as mock_set_cache,
            patch("app.utils.agent_utils.integration_repository") as mock_repo,
        ):
            result = await _resolve_mcp_icon_name("mcp_int")

        assert result == ("https://icon.png", "My MCP")
        mock_get_cache.assert_awaited_once_with(f"{CUSTOM_INT_METADATA_CACHE_PREFIX}:mcp_int")
        mock_set_cache.assert_not_awaited()
        mock_repo.get.assert_not_called()

    @pytest.mark.asyncio
    async def test_cache_hit_with_partial_entry(self) -> None:
        with (
            patch(
                "app.db.redis.get_cache",
                new_callable=AsyncMock,
                return_value={"icon_url": "https://icon.png"},
            ) as mock_get_cache,
            patch("app.db.redis.set_cache", new_callable=AsyncMock) as mock_set_cache,
            patch("app.utils.agent_utils.integration_repository") as mock_repo,
        ):
            result = await _resolve_mcp_icon_name("mcp_int")

        assert result == ("https://icon.png", None)
        mock_get_cache.assert_awaited_once_with(f"{CUSTOM_INT_METADATA_CACHE_PREFIX}:mcp_int")
        mock_set_cache.assert_not_awaited()
        mock_repo.get.assert_not_called()

    @pytest.mark.asyncio
    async def test_db_integration_without_icon_url(self) -> None:
        with (
            patch("app.db.redis.get_cache", new_callable=AsyncMock, return_value=None),
            patch("app.db.redis.set_cache", new_callable=AsyncMock) as mock_set_cache,
            patch("app.utils.agent_utils.integration_repository") as mock_repo,
        ):
            mock_repo.get = AsyncMock(return_value=_integration("mcp_int", "My MCP"))
            result = await _resolve_mcp_icon_name("mcp_int")

        assert result == (None, "My MCP")
        mock_set_cache.assert_awaited_once_with(
            f"{CUSTOM_INT_METADATA_CACHE_PREFIX}:mcp_int",
            {
                "icon_url": None,
                "integration_id": "mcp_int",
                "integration_name": "My MCP",
            },
            ttl=CUSTOM_INT_METADATA_TTL,
        )

    @pytest.mark.asyncio
    async def test_db_hit_populates_cache(self) -> None:
        with (
            patch("app.db.redis.get_cache", new_callable=AsyncMock, return_value=None),
            patch("app.db.redis.set_cache", new_callable=AsyncMock) as mock_set_cache,
            patch("app.utils.agent_utils.integration_repository") as mock_repo,
        ):
            mock_repo.get = AsyncMock(
                return_value=_integration("mcp_int", "My MCP", icon_url="https://icon.png")
            )
            result = await _resolve_mcp_icon_name("mcp_int")

        assert result == ("https://icon.png", "My MCP")
        mock_repo.get.assert_awaited_once_with("mcp_int")
        mock_set_cache.assert_awaited_once_with(
            f"{CUSTOM_INT_METADATA_CACHE_PREFIX}:mcp_int",
            {
                "icon_url": "https://icon.png",
                "integration_id": "mcp_int",
                "integration_name": "My MCP",
            },
            ttl=CUSTOM_INT_METADATA_TTL,
        )

    @pytest.mark.asyncio
    async def test_db_miss_caches_empty(self) -> None:
        with (
            patch("app.db.redis.get_cache", new_callable=AsyncMock, return_value=None),
            patch("app.db.redis.set_cache", new_callable=AsyncMock) as mock_set_cache,
            patch("app.utils.agent_utils.integration_repository") as mock_repo,
        ):
            mock_repo.get = AsyncMock(return_value=None)
            result = await _resolve_mcp_icon_name("mcp_int")

        assert result == (None, None)
        mock_set_cache.assert_awaited_once_with(
            f"{CUSTOM_INT_METADATA_CACHE_PREFIX}:mcp_int", {}, ttl=CUSTOM_INT_METADATA_TTL
        )

    @pytest.mark.asyncio
    async def test_db_error_logs_and_returns_none(self) -> None:
        with (
            patch("app.db.redis.get_cache", new_callable=AsyncMock, return_value=None),
            patch("app.utils.agent_utils.integration_repository") as mock_repo,
            patch("app.utils.agent_utils.log") as mock_log,
        ):
            mock_repo.get = AsyncMock(side_effect=RuntimeError("db boom"))
            result = await _resolve_mcp_icon_name("mcp_int")

        assert result == (None, None)
        mock_log.warning.assert_called_once()
        assert (
            mock_log.warning.call_args.args[0] == f"{LogTag.AGENT} MCP icon/name lookup failed for"
        )
        assert mock_log.warning.call_args.kwargs["integration_id"] == "mcp_int"
        assert mock_log.warning.call_args.kwargs["error"] == "db boom"
        assert mock_log.warning.call_args.kwargs["error_type"] == "RuntimeError"


# ---------------------------------------------------------------------------
# format_sse_response / format_sse_data
# ---------------------------------------------------------------------------


class TestSSEFormatters:
    def test_format_sse_response(self) -> None:
        expected = f"data: {json.dumps({'response': 'Hello world'})}\n\n"
        assert format_sse_response("Hello world") == expected

    def test_format_sse_data(self) -> None:
        expected = f"data: {json.dumps({'key': 'value', 'count': 42})}\n\n"
        assert format_sse_data({"key": "value", "count": 42}) == expected


# ---------------------------------------------------------------------------
# process_custom_event_for_tools
# ---------------------------------------------------------------------------


class TestProcessCustomEventForTools:
    def test_with_payload(self) -> None:
        with patch(
            "app.utils.agent_utils.extract_tool_data", return_value={"tool": "data"}
        ) as mock_extract:
            result = process_custom_event_for_tools({"some": "payload"})
        assert result == {"tool": "data"}
        mock_extract.assert_called_once_with(json.dumps({"some": "payload"}))

    def test_with_none_payload(self) -> None:
        with patch("app.utils.agent_utils.extract_tool_data", return_value=None) as mock_extract:
            result = process_custom_event_for_tools(None)
        assert result == {}
        mock_extract.assert_called_once_with("{}")

    def test_with_empty_dict_payload(self) -> None:
        with patch("app.utils.agent_utils.extract_tool_data", return_value=None) as mock_extract:
            result = process_custom_event_for_tools({})
        assert result == {}
        mock_extract.assert_called_once_with("{}")

    def test_extract_returns_none(self) -> None:
        with patch("app.utils.agent_utils.extract_tool_data", return_value=None) as mock_extract:
            result = process_custom_event_for_tools({"x": 1})
        assert result == {}
        mock_extract.assert_called_once_with('{"x": 1}')

    def test_extract_returns_empty_dict(self) -> None:
        with patch("app.utils.agent_utils.extract_tool_data", return_value={}) as mock_extract:
            result = process_custom_event_for_tools({"x": 1})
        assert result == {}
        mock_extract.assert_called_once_with('{"x": 1}')

    def test_exception_returns_empty_and_logs(self) -> None:
        with (
            patch(
                "app.utils.agent_utils.extract_tool_data",
                side_effect=RuntimeError("parse fail"),
            ),
            patch("app.utils.agent_utils.log") as mock_log,
        ):
            result = process_custom_event_for_tools({"x": 1})
        assert result == {}
        mock_log.error.assert_called_once()
        assert mock_log.error.call_args.args[0] == f"{LogTag.AGENT} Error extracting tool data"
        assert mock_log.error.call_args.kwargs["error"] == "parse fail"
        assert mock_log.error.call_args.kwargs["error_type"] == "RuntimeError"
