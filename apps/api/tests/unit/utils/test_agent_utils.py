"""Tests for app/utils/agent_utils.py"""

import json
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.constants.agents import AgentTag, wrap_agent_payload
from app.models.integration_models import Integration
from app.utils.agent_utils import (
    _general_tool_category,
    _lookup_custom_integration_name,
    _registry_mcp_ui_metadata,
    _resolve_handoff_display_name,
    _special_tool_display,
    format_sse_data,
    format_sse_response,
    format_tool_call_entry,
    parse_subagent_id,
    process_custom_event_for_tools,
    strip_internal_agent_tags,
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
            result = await _lookup_custom_integration_name.__wrapped__("custom_id_123")  # type: ignore[attr-defined]  # reaching the unwrapped original under functools.wraps
        assert result == "My Custom Tool"

    @pytest.mark.asyncio
    async def test_not_found(self) -> None:
        with patch("app.utils.agent_utils.integration_repository") as mock_repo:
            mock_repo.find_by_id_prefix = AsyncMock(return_value=None)
            result = await _lookup_custom_integration_name.__wrapped__("unknown_id")  # type: ignore[attr-defined]  # reaching the unwrapped original under functools.wraps
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
            result = await format_tool_call_entry(tool_call)  # type: ignore[arg-type]  # hand-built dict stands in for a ToolCall
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
            result = await format_tool_call_entry(tool_call)  # type: ignore[arg-type]  # hand-built dict stands in for a ToolCall

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
            result = await format_tool_call_entry(tool_call)  # type: ignore[arg-type]  # hand-built dict stands in for a ToolCall

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
                tool_call,  # type: ignore[arg-type]  # hand-built dict stands in for a ToolCall
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
            result = await format_tool_call_entry(tool_call)  # type: ignore[arg-type]  # hand-built dict stands in for a ToolCall

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
            result = await format_tool_call_entry(tool_call)  # type: ignore[arg-type]  # hand-built dict stands in for a ToolCall

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
                tool_call,  # type: ignore[arg-type]  # hand-built dict stands in for a ToolCall
                icon_url="https://icon.png",
                integration_name="My Service",
            )

        assert result["data"]["icon_url"] == "https://icon.png"  # type: ignore[index]  # runtime returns a dict though the signature says str
        assert result["data"]["integration_name"] == "My Service"  # type: ignore[index]  # runtime returns a dict though the signature says str


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
                tool_call,  # type: ignore[arg-type]  # hand-built dict stands in for a ToolCall
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
                tool_call,  # type: ignore[arg-type]  # hand-built dict stands in for a ToolCall
                integration_id="custom_integration_2",
                user_id="user123",
            )

        assert result is not None
        assert result["data"]["icon_url"] == "cached.png"
        assert result["data"]["integration_name"] == "Cached"
        mock_repo_get.assert_not_awaited()


# ---------------------------------------------------------------------------
# _special_tool_display
# ---------------------------------------------------------------------------


def _no_known_handoff_target() -> Any:
    """Neither a platform subagent nor a custom integration answers to the id, so
    the display name falls through to the title-cased id itself."""
    return patch("app.utils.agent_utils.get_subagent_by_id", return_value=None)


class TestSpecialToolDisplay:
    """A ``handoff`` card names the target agent. The args it reads come straight
    off the model's tool call, so both the missing-``args`` and the
    missing-``subagent_id`` shapes are routine, not malformed input."""

    @pytest.mark.asyncio
    async def test_a_handoff_with_no_args_at_all_still_renders(self) -> None:
        with (
            _no_known_handoff_target(),
            patch(
                "app.utils.agent_utils._lookup_custom_integration_name",
                new_callable=AsyncMock,
                return_value=None,
            ),
        ):
            result = await _special_tool_display("handoff", {"name": "handoff", "id": "tc"})  # type: ignore[arg-type]  # hand-built dict stands in for a ToolCall

        assert result == ("handoff", "Handing off to Subagent", False)

    @pytest.mark.asyncio
    async def test_a_handoff_naming_no_subagent_looks_up_the_literal_default(self) -> None:
        with (
            _no_known_handoff_target(),
            patch(
                "app.utils.agent_utils._lookup_custom_integration_name",
                new_callable=AsyncMock,
                return_value=None,
            ) as mock_lookup,
        ):
            result = await _special_tool_display(
                "handoff",  # type: ignore[arg-type]  # hand-built dict stands in for a ToolCall
                {"name": "handoff", "args": {}, "id": "tc"},
            )

        assert result == ("handoff", "Handing off to Subagent", False)
        mock_lookup.assert_awaited_once_with("subagent")

    @pytest.mark.asyncio
    async def test_a_non_handoff_special_tool_uses_its_table_row_verbatim(self) -> None:
        result = await _special_tool_display("run_playbook", {"name": "run_playbook", "args": {}})  # type: ignore[arg-type]  # hand-built dict stands in for a ToolCall

        assert result == ("playbooks", "Run playbook", True)


# ---------------------------------------------------------------------------
# _general_tool_category
# ---------------------------------------------------------------------------


class _FakeRegistry:
    """Answers by tool name, so a call that loses the name shows up as a miss."""

    def __init__(self, categories: dict[str, str]) -> None:
        self._categories = categories

    def get_category_of_tool(self, tool_name: str) -> str | None:
        return self._categories.get(tool_name)

    def get_all_tools_for_search(self) -> list[Any]:
        return []


def _mcp_lookup(integration_id: str = "notion_int") -> Any:
    return patch(
        "app.utils.agent_utils._resolve_mcp_integration_id",
        new_callable=AsyncMock,
        return_value=integration_id,
    )


class TestGeneralToolCategory:
    """A core tool running inside an MCP subagent keeps its own category, so the
    card shows the tool's icon rather than the subagent's logo. Everything here
    turns on whether the registry category counts as core."""

    @pytest.mark.asyncio
    async def test_a_core_tool_keeps_its_category_and_never_consults_the_mcp_client(self) -> None:
        with _mcp_lookup() as mock_resolve:
            result = await _general_tool_category(
                _FakeRegistry({"vfs_cmd": "files"}),  # type: ignore[arg-type]  # name-keyed stand-in for ToolRegistry
                "vfs_cmd",
                None,
                "u1",
            )

        assert result == ("files", None, True)
        mock_resolve.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_an_unknown_registry_category_is_not_a_core_tool(self) -> None:
        result = await _general_tool_category(
            _FakeRegistry({"mystery": "unknown"}),  # type: ignore[arg-type]  # name-keyed stand-in for ToolRegistry
            "mystery",
            None,
            None,
        )

        assert result == ("unknown", None, False)

    @pytest.mark.asyncio
    async def test_an_mcp_namespaced_category_is_stripped_and_is_not_core(self) -> None:
        result = await _general_tool_category(
            _FakeRegistry({"notion_page": "mcp_notion"}),  # type: ignore[arg-type]  # name-keyed stand-in for ToolRegistry
            "notion_page",
            None,
            None,
        )

        assert result == ("notion", None, False)

    @pytest.mark.asyncio
    async def test_a_tool_the_registry_does_not_know_resolves_via_the_users_mcp_client(
        self,
    ) -> None:
        with _mcp_lookup() as mock_resolve:
            result = await _general_tool_category(
                _FakeRegistry({}),  # type: ignore[arg-type]  # name-keyed stand-in for ToolRegistry
                "notion_tool",
                None,
                "u1",
            )

        assert result == ("notion_int", "notion_int", False)
        mock_resolve.assert_awaited_once_with("notion_tool", "u1")


# ---------------------------------------------------------------------------
# _registry_mcp_ui_metadata
# ---------------------------------------------------------------------------


def _registry_tool(name: str, tool: Any) -> Any:
    registry_tool = MagicMock()
    registry_tool.name = name
    registry_tool.tool = tool
    return registry_tool


class TestRegistryMcpUiMetadata:
    """The global registry is the first of two mcp_ui sources; a miss here has to
    read as "nothing found" so the per-user MCPClient fallback still runs."""

    def test_a_tool_the_registry_does_not_hold_yields_two_nones(self) -> None:
        registry = MagicMock()
        registry.get_all_tools_for_search.return_value = [_registry_tool("other_tool", MagicMock())]

        assert _registry_mcp_ui_metadata(registry, "ui_tool") == (None, None)

    def test_a_tool_carrying_no_metadata_is_normal_and_not_logged_as_a_failure(self) -> None:
        """A plain platform tool simply has no ``metadata``. Reading that as a
        registry outage buries the real outages in noise."""

        class _PlainTool:
            pass

        registry = MagicMock()
        registry.get_all_tools_for_search.return_value = [_registry_tool("ui_tool", _PlainTool())]

        with patch("app.utils.agent_utils.log") as mock_log:
            result = _registry_mcp_ui_metadata(registry, "ui_tool")

        assert result == (None, None)
        mock_log.debug.assert_not_called()

    def test_metadata_that_is_not_a_dict_is_ignored_rather_than_duck_typed(self) -> None:
        """Only a real dict is metadata. Anything else that happens to expose
        ``.get`` would otherwise hand the frontend an arbitrary object as mcp_ui."""

        class _LooksLikeAMapping:
            def get(self, key: str) -> str:
                return f"value-for-{key}"

        tool = MagicMock()
        tool.metadata = _LooksLikeAMapping()
        registry = MagicMock()
        registry.get_all_tools_for_search.return_value = [_registry_tool("ui_tool", tool)]

        assert _registry_mcp_ui_metadata(registry, "ui_tool") == (None, None)


# ---------------------------------------------------------------------------
# format_tool_call_entry -> _general_tool_category wiring
# ---------------------------------------------------------------------------


class TestFormatToolCallEntryCategoryWiring:
    @staticmethod
    def _patches(registry: Any) -> Any:
        return (
            patch(
                "app.utils.agent_utils.get_tool_registry",
                new_callable=AsyncMock,
                return_value=registry,
            ),
            patch(
                "app.utils.agent_utils._resolve_mcp_ui_metadata",
                new_callable=AsyncMock,
                return_value=(None, None),
            ),
            patch(
                "app.utils.agent_utils._resolve_mcp_icon_name",
                new_callable=AsyncMock,
                return_value=(None, None),
            ),
        )

    @pytest.mark.asyncio
    async def test_the_category_is_looked_up_under_the_tool_being_called(self) -> None:
        registry_patch, ui_patch, icon_patch = self._patches(_FakeRegistry({"vfs_cmd": "files"}))
        with registry_patch, ui_patch, icon_patch, _mcp_lookup("wrong_integration"):
            result = await format_tool_call_entry(
                {"name": "vfs_cmd", "args": {}, "id": "tc"},  # type: ignore[arg-type]  # hand-built dict stands in for a ToolCall
                user_id="u1",
            )

        assert result is not None
        assert result["data"]["tool_category"] == "files"

    @pytest.mark.asyncio
    async def test_the_calling_user_is_carried_into_the_mcp_provenance_lookup(self) -> None:
        """Without the user there is no MCPClient to ask, and every MCP tool would
        fall back to an empty category — the frontend's "no icon" state."""
        registry_patch, ui_patch, icon_patch = self._patches(_FakeRegistry({}))
        with registry_patch, ui_patch, icon_patch, _mcp_lookup():
            result = await format_tool_call_entry(
                {"name": "notion_tool", "args": {}, "id": "tc"},  # type: ignore[arg-type]  # hand-built dict stands in for a ToolCall
                user_id="u1",
            )

        assert result is not None
        assert result["data"]["tool_category"] == "notion_int"


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


# ---------------------------------------------------------------------------
# internal agent channel tags
# ---------------------------------------------------------------------------


class TestWrapAgentPayload:
    def test_body_is_framed_by_an_open_and_close_tag(self) -> None:
        assert wrap_agent_payload(AgentTag.EXECUTOR_RESULT, "3 unread") == (
            "<executor_result>\n3 unread\n</executor_result>\n"
        )

    def test_the_producing_agent_is_named_on_the_opening_tag(self) -> None:
        assert wrap_agent_payload(AgentTag.SUBAGENT_RESULT, "sent", agent="gmail") == (
            '<subagent_result agent="gmail">\nsent\n</subagent_result>\n'
        )

    def test_a_payload_with_no_producing_agent_carries_no_attribute(self) -> None:
        """Only a subagent result is attributed; an executor result naming an
        empty agent would be a tag the strip pattern still matches but a reader
        cannot parse."""
        assert wrap_agent_payload(AgentTag.EXECUTOR_RESULT, "done", agent=None) == (
            "<executor_result>\ndone\n</executor_result>\n"
        )

    def test_consecutive_blocks_concatenate_without_running_together(self) -> None:
        """Callers build a message by string-joining blocks, so the trailing
        newline is load-bearing: without it a close tag and the next open tag
        land on one line and the frame stops reading as structure."""
        joined = wrap_agent_payload(AgentTag.RETURNED_TO_FRONTEND, "a card is up") + (
            wrap_agent_payload(AgentTag.EXECUTOR_RESULT, "3 unread")
        )

        assert joined == (
            "<returned_to_frontend>\na card is up\n</returned_to_frontend>\n"
            "<executor_result>\n3 unread\n</executor_result>\n"
        )


class TestStripInternalAgentTags:
    def test_a_parroted_block_keeps_its_words_and_loses_the_frame(self) -> None:
        text = wrap_agent_payload(AgentTag.EXECUTOR_RESULT, "you have 3 unread")

        assert strip_internal_agent_tags(text) == "you have 3 unread"

    def test_a_lone_closing_tag_is_stripped(self) -> None:
        """The common half-leak: the model writes its own reply and then closes
        the block it was handed."""
        assert strip_internal_agent_tags("3 unread</executor_result>") == "3 unread"

    def test_an_attributed_tag_is_stripped(self) -> None:
        assert (
            strip_internal_agent_tags('<subagent_result agent="gmail">\nsent\n</subagent_result>')
            == "sent"
        )

    def test_case_is_ignored(self) -> None:
        assert strip_internal_agent_tags("<Executor_Result> done") == "done"

    def test_ordinary_markup_in_a_reply_survives(self) -> None:
        """The pattern names the internal tags exactly — a reply that legitimately
        contains angle brackets (code, HTML, a comparison) must come through
        untouched, or the backstop starts eating the answer."""
        reply = "use `<div>` for that, and 3 < 5 is true"

        assert strip_internal_agent_tags(reply) == reply

    @pytest.mark.parametrize("tag", list(AgentTag))
    def test_every_declared_tag_is_covered_by_the_strip(self, tag: AgentTag) -> None:
        """Drift guard: a tag added to ``AgentTag`` extends the backstop for free.
        A hand-listed pattern would leak the new tag on its first use."""
        assert strip_internal_agent_tags(wrap_agent_payload(tag, "payload")) == "payload"
