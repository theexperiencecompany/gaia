"""Tests for workflow context extractor."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.workflow.context_extractor import (
    ExtractedContext,
    WorkflowContextExtractor,
)


# ---------------------------------------------------------------------------
# ExtractedContext dataclass
# ---------------------------------------------------------------------------


class TestExtractedContext:
    def test_basic_creation(self) -> None:
        ctx = ExtractedContext(
            suggested_title="My Workflow",
            summary="A summary",
            workflow_steps=[],
        )
        assert ctx.suggested_title == "My Workflow"
        assert ctx.integrations_used == []

    def test_with_integrations(self) -> None:
        ctx = ExtractedContext(
            suggested_title="T",
            summary="S",
            workflow_steps=[],
            integrations_used=["gmail", "slack"],
        )
        assert ctx.integrations_used == ["gmail", "slack"]


# ---------------------------------------------------------------------------
# _infer_category
# ---------------------------------------------------------------------------


class TestInferCategory:
    @patch("app.services.workflow.context_extractor.get_toolkit_to_integration_map")
    def test_from_agent_name(self, mock_map: MagicMock) -> None:
        mock_map.return_value = {}
        result = WorkflowContextExtractor._infer_category("gmail_agent", "some_tool")
        assert result == "gmail"

    @patch("app.services.workflow.context_extractor.get_toolkit_to_integration_map")
    def test_executor_agent_falls_through(self, mock_map: MagicMock) -> None:
        mock_map.return_value = {}
        result = WorkflowContextExtractor._infer_category("executor", "some_tool")
        assert result == "general"

    @patch("app.services.workflow.context_extractor.get_toolkit_to_integration_map")
    def test_from_tool_prefix(self, mock_map: MagicMock) -> None:
        mock_map.return_value = {"GMAIL": "gmail", "SLACK": "slack"}
        result = WorkflowContextExtractor._infer_category(
            "executor", "GMAIL_SEND_EMAIL"
        )
        assert result == "gmail"

    @patch("app.services.workflow.context_extractor.get_toolkit_to_integration_map")
    def test_no_match_returns_general(self, mock_map: MagicMock) -> None:
        mock_map.return_value = {"GMAIL": "gmail"}
        result = WorkflowContextExtractor._infer_category("executor", "unknown_tool")
        assert result == "general"

    @patch("app.services.workflow.context_extractor.get_toolkit_to_integration_map")
    def test_empty_agent_name(self, mock_map: MagicMock) -> None:
        mock_map.return_value = {}
        result = WorkflowContextExtractor._infer_category("", "some_tool")
        assert result == "general"


# ---------------------------------------------------------------------------
# _humanize_tool_name
# ---------------------------------------------------------------------------


class TestHumanizeToolName:
    @patch("app.services.workflow.context_extractor.get_toolkit_to_integration_map")
    def test_removes_prefix_and_humanizes(self, mock_map: MagicMock) -> None:
        mock_map.return_value = {"GMAIL": "gmail"}
        result = WorkflowContextExtractor._humanize_tool_name("GMAIL_SEND_EMAIL")
        assert result == "Send Email"

    @patch("app.services.workflow.context_extractor.get_toolkit_to_integration_map")
    def test_removes_custom_prefix(self, mock_map: MagicMock) -> None:
        mock_map.return_value = {}
        result = WorkflowContextExtractor._humanize_tool_name("CUSTOM_my_tool")
        assert result == "My Tool"

    @patch("app.services.workflow.context_extractor.get_toolkit_to_integration_map")
    def test_plain_tool_name(self, mock_map: MagicMock) -> None:
        mock_map.return_value = {}
        result = WorkflowContextExtractor._humanize_tool_name("create_todo")
        assert result == "Create Todo"


# ---------------------------------------------------------------------------
# _build_description
# ---------------------------------------------------------------------------


class TestBuildDescription:
    def test_basic_description(self) -> None:
        result = WorkflowContextExtractor._build_description("my_tool", {}, "")
        assert result == "Execute my_tool"

    def test_with_args(self) -> None:
        result = WorkflowContextExtractor._build_description(
            "my_tool", {"to": "user@example.com", "subject": "Hello"}, ""
        )
        assert "with" in result
        assert "to=user@example.com" in result

    def test_with_output(self) -> None:
        result = WorkflowContextExtractor._build_description(
            "my_tool", {}, "Message sent successfully"
        )
        assert "returned" in result
        assert "Message sent successfully" in result

    def test_truncates_long_args(self) -> None:
        result = WorkflowContextExtractor._build_description(
            "my_tool", {"body": "A" * 50}, ""
        )
        assert "..." in result

    def test_truncates_long_output(self) -> None:
        result = WorkflowContextExtractor._build_description("my_tool", {}, "A" * 200)
        assert "..." in result

    def test_limits_arg_count(self) -> None:
        many_args = {f"arg{i}": f"val{i}" for i in range(10)}
        result = WorkflowContextExtractor._build_description("my_tool", many_args, "")
        # Should only include first 3
        assert result.count("=") <= 3

    def test_empty_output_skipped(self) -> None:
        result = WorkflowContextExtractor._build_description("my_tool", {}, "   ")
        assert "returned" not in result


# ---------------------------------------------------------------------------
# _build_context
# ---------------------------------------------------------------------------


class TestBuildContext:
    def _make_human_msg(self, content: str) -> MagicMock:
        from langchain_core.messages import HumanMessage

        return HumanMessage(content=content)  # type: ignore[return-value]

    def _make_ai_msg(self, tool_calls: list) -> MagicMock:
        from langchain_core.messages import AIMessage

        return AIMessage(content="", tool_calls=tool_calls)  # type: ignore[return-value]

    def _make_tool_msg(self, content: str, tool_call_id: str) -> MagicMock:
        from langchain_core.messages import ToolMessage

        return ToolMessage(content=content, tool_call_id=tool_call_id)  # type: ignore[return-value]

    @patch(
        "app.services.workflow.context_extractor.get_toolkit_to_integration_map",
        return_value={},
    )
    def test_empty_messages(self, mock_map: MagicMock) -> None:
        result = WorkflowContextExtractor._build_context([], 100)
        assert result.suggested_title == "New Workflow"
        assert result.summary == "No executable steps found in conversation"
        assert result.workflow_steps == []

    @patch(
        "app.services.workflow.context_extractor.get_toolkit_to_integration_map",
        return_value={},
    )
    def test_extracts_tool_calls(self, mock_map: MagicMock) -> None:
        msgs = [
            self._make_human_msg("Send an email to Bob"),
            self._make_tool_msg("Email sent", "tc1"),
            self._make_ai_msg(
                [
                    {"name": "send_email", "args": {"to": "bob@x.com"}, "id": "tc1"},
                ]
            ),
        ]
        result = WorkflowContextExtractor._build_context(msgs, 100)
        assert len(result.workflow_steps) == 1
        assert result.workflow_steps[0]["title"] == "Send Email"

    @patch(
        "app.services.workflow.context_extractor.get_toolkit_to_integration_map",
        return_value={},
    )
    def test_skips_internal_tools(self, mock_map: MagicMock) -> None:
        msgs = [
            self._make_ai_msg(
                [
                    {"name": "retrieve_tools", "args": {}, "id": "tc1"},
                    {"name": "search_memory", "args": {}, "id": "tc2"},
                    {"name": "create_workflow", "args": {}, "id": "tc3"},
                ]
            ),
        ]
        result = WorkflowContextExtractor._build_context(msgs, 100)
        assert result.workflow_steps == []

    @patch(
        "app.services.workflow.context_extractor.get_toolkit_to_integration_map",
        return_value={},
    )
    def test_handoff_updates_agent(self, mock_map: MagicMock) -> None:
        msgs = [
            self._make_ai_msg(
                [
                    {"name": "handoff", "args": {"subagent_id": "gmail"}, "id": "tc1"},
                ]
            ),
            self._make_ai_msg(
                [
                    {"name": "send_email", "args": {}, "id": "tc2"},
                ]
            ),
        ]
        result = WorkflowContextExtractor._build_context(msgs, 100)
        assert len(result.workflow_steps) == 1
        assert result.workflow_steps[0]["category"] == "gmail"
        assert "gmail" in result.integrations_used

    @patch(
        "app.services.workflow.context_extractor.get_toolkit_to_integration_map",
        return_value={},
    )
    def test_suggested_title_from_human_message(self, mock_map: MagicMock) -> None:
        msgs = [
            self._make_human_msg("Send an email to Bob"),
        ]
        result = WorkflowContextExtractor._build_context(msgs, 100)
        assert result.suggested_title == "Send an email to Bob"

    @patch(
        "app.services.workflow.context_extractor.get_toolkit_to_integration_map",
        return_value={},
    )
    def test_suggested_title_truncation(self, mock_map: MagicMock) -> None:
        long_msg = "Please send a very detailed email to Bob about the quarterly report and upcoming deadlines for Q3"
        msgs = [self._make_human_msg(long_msg)]
        result = WorkflowContextExtractor._build_context(msgs, 100)
        assert len(result.suggested_title) < len(long_msg)
        assert result.suggested_title.endswith("...")

    @patch(
        "app.services.workflow.context_extractor.get_toolkit_to_integration_map",
        return_value={},
    )
    def test_suggested_title_from_integrations(self, mock_map: MagicMock) -> None:
        msgs = [
            self._make_ai_msg(
                [
                    {"name": "handoff", "args": {"subagent_id": "gmail"}, "id": "tc1"},
                ]
            ),
            self._make_ai_msg(
                [
                    {"name": "send_email", "args": {}, "id": "tc2"},
                ]
            ),
        ]
        result = WorkflowContextExtractor._build_context(msgs, 100)
        assert "gmail" in result.suggested_title.lower()

    @patch(
        "app.services.workflow.context_extractor.get_toolkit_to_integration_map",
        return_value={},
    )
    def test_multimodal_human_message(self, mock_map: MagicMock) -> None:
        from langchain_core.messages import HumanMessage

        content = [
            {"type": "image", "url": "https://example.com/img.png"},
            {"type": "text", "text": "Describe this image"},
        ]
        msgs = [HumanMessage(content=content)]  # type: ignore[arg-type]
        result = WorkflowContextExtractor._build_context(msgs, 100)
        assert result.suggested_title == "Describe this image"

    @patch(
        "app.services.workflow.context_extractor.get_toolkit_to_integration_map",
        return_value={},
    )
    def test_summary_with_steps(self, mock_map: MagicMock) -> None:
        msgs = [
            self._make_ai_msg(
                [
                    {"name": "create_todo", "args": {"title": "Test"}, "id": "tc1"},
                ]
            ),
        ]
        result = WorkflowContextExtractor._build_context(msgs, 100)
        assert "1 steps" in result.summary

    @patch(
        "app.services.workflow.context_extractor.get_toolkit_to_integration_map",
        return_value={},
    )
    def test_tool_output_linked_to_step(self, mock_map: MagicMock) -> None:
        msgs = [
            self._make_tool_msg("Todo created: Buy groceries", "tc1"),
            self._make_ai_msg(
                [
                    {"name": "create_todo", "args": {"title": "Buy"}, "id": "tc1"},
                ]
            ),
        ]
        result = WorkflowContextExtractor._build_context(msgs, 100)
        assert "Todo created" in result.workflow_steps[0]["description"]


# ---------------------------------------------------------------------------
# extract_from_thread
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestExtractFromThread:
    @patch.object(WorkflowContextExtractor, "_fetch_messages", new_callable=AsyncMock)
    @patch(
        "app.services.workflow.context_extractor.get_toolkit_to_integration_map",
        return_value={},
    )
    async def test_returns_none_on_empty_messages(
        self, mock_map: MagicMock, mock_fetch: AsyncMock
    ) -> None:
        mock_fetch.return_value = []
        result = await WorkflowContextExtractor.extract_from_thread("thread1")
        assert result is None

    @patch.object(WorkflowContextExtractor, "_fetch_messages", new_callable=AsyncMock)
    @patch(
        "app.services.workflow.context_extractor.get_toolkit_to_integration_map",
        return_value={},
    )
    async def test_returns_context_on_success(
        self, mock_map: MagicMock, mock_fetch: AsyncMock
    ) -> None:
        from langchain_core.messages import HumanMessage

        mock_fetch.return_value = [HumanMessage(content="Do something")]
        result = await WorkflowContextExtractor.extract_from_thread("thread1")
        assert result is not None
        assert result.suggested_title == "Do something"

    @patch.object(WorkflowContextExtractor, "_fetch_messages", new_callable=AsyncMock)
    async def test_returns_none_on_error(self, mock_fetch: AsyncMock) -> None:
        mock_fetch.side_effect = RuntimeError("db error")
        result = await WorkflowContextExtractor.extract_from_thread("thread1")
        assert result is None

    @patch.object(WorkflowContextExtractor, "_fetch_messages", new_callable=AsyncMock)
    @patch(
        "app.services.workflow.context_extractor.get_toolkit_to_integration_map",
        return_value={},
    )
    async def test_custom_max_output_chars(
        self, mock_map: MagicMock, mock_fetch: AsyncMock
    ) -> None:
        from langchain_core.messages import AIMessage, ToolMessage

        mock_fetch.return_value = [
            ToolMessage(content="A" * 500, tool_call_id="tc1"),
            AIMessage(
                content="",
                tool_calls=[{"name": "my_tool", "args": {}, "id": "tc1"}],
            ),
        ]
        result = await WorkflowContextExtractor.extract_from_thread(
            "thread1", max_output_chars=10
        )
        assert result is not None
        # The tool output in description should be truncated
        desc = result.workflow_steps[0]["description"]
        assert len(desc) < 500


# ---------------------------------------------------------------------------
# _fetch_messages
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestFetchMessages:
    @patch(
        "app.agents.core.graph_builder.checkpointer_manager.get_checkpointer_manager"
    )
    async def test_returns_messages_from_state(self, mock_get_mgr: AsyncMock) -> None:
        mock_cp = AsyncMock()
        mock_cp.aget = AsyncMock(
            return_value={"channel_values": {"messages": ["msg1", "msg2"]}}
        )
        mock_mgr = AsyncMock()
        mock_mgr.get_checkpointer = MagicMock(return_value=mock_cp)
        mock_get_mgr.return_value = mock_mgr

        result = await WorkflowContextExtractor._fetch_messages("thread1")
        assert result == ["msg1", "msg2"]

    @patch(
        "app.agents.core.graph_builder.checkpointer_manager.get_checkpointer_manager"
    )
    async def test_returns_empty_on_no_state(self, mock_get_mgr: AsyncMock) -> None:
        mock_cp = AsyncMock()
        mock_cp.aget = AsyncMock(return_value=None)
        mock_mgr = AsyncMock()
        mock_mgr.get_checkpointer = MagicMock(return_value=mock_cp)
        mock_get_mgr.return_value = mock_mgr

        result = await WorkflowContextExtractor._fetch_messages("thread1")
        assert result == []

    @patch(
        "app.agents.core.graph_builder.checkpointer_manager.get_checkpointer_manager"
    )
    async def test_returns_empty_on_no_channel_values(
        self, mock_get_mgr: AsyncMock
    ) -> None:
        mock_cp = AsyncMock()
        mock_cp.aget = AsyncMock(return_value={"other": "data"})
        mock_mgr = AsyncMock()
        mock_mgr.get_checkpointer = MagicMock(return_value=mock_cp)
        mock_get_mgr.return_value = mock_mgr

        result = await WorkflowContextExtractor._fetch_messages("thread1")
        assert result == []
