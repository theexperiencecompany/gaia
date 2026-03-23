"""Tests for app/helpers/message_helpers.py"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from langchain_core.messages import SystemMessage

from app.helpers.message_helpers import (
    _get_gaia_knowledge_section,
    _get_user_memories_section,
    create_system_message,
    format_calendar_event_context,
    format_files_list,
    format_reply_context,
    format_tool_selection_message,
    format_workflow_execution_message,
    get_memory_message,
)
from app.models.message_models import (
    FileData,
    ReplyToMessageData,
    SelectedCalendarEventData,
    SelectedWorkflowData,
)


# ---------------------------------------------------------------------------
# create_system_message
# ---------------------------------------------------------------------------


class TestCreateSystemMessage:
    def test_comms_agent(self) -> None:
        msg = create_system_message(user_name="Alice", agent_type="comms")
        assert isinstance(msg, SystemMessage)
        assert "Alice" in msg.content

    def test_executor_agent(self) -> None:
        msg = create_system_message(user_name="Bob", agent_type="executor")
        assert isinstance(msg, SystemMessage)
        # Executor template may or may not include user_name; just verify it rendered
        assert len(msg.content) > 0

    def test_default_name(self) -> None:
        msg = create_system_message()
        assert "there" in msg.content

    def test_unknown_agent_type_defaults_to_comms(self) -> None:
        msg = create_system_message(user_name="X", agent_type="unknown")  # type: ignore[arg-type]
        assert isinstance(msg, SystemMessage)


# ---------------------------------------------------------------------------
# _get_user_memories_section
# ---------------------------------------------------------------------------


class TestGetUserMemoriesSection:
    @pytest.mark.asyncio
    async def test_with_memories(self) -> None:
        mem1 = MagicMock()
        mem1.content = "User likes coffee"
        mem2 = MagicMock()
        mem2.content = "User prefers dark mode"
        mock_results = MagicMock()
        mock_results.memories = [mem1, mem2]

        with patch("app.helpers.message_helpers.memory_service") as mock_svc:
            mock_svc.search_memories = AsyncMock(return_value=mock_results)
            result = await _get_user_memories_section("coffee", "user1")

        assert "User likes coffee" in result
        assert "User prefers dark mode" in result

    @pytest.mark.asyncio
    async def test_no_memories(self) -> None:
        mock_results = MagicMock()
        mock_results.memories = None

        with patch("app.helpers.message_helpers.memory_service") as mock_svc:
            mock_svc.search_memories = AsyncMock(return_value=mock_results)
            result = await _get_user_memories_section("query", "user1")

        assert result == ""

    @pytest.mark.asyncio
    async def test_empty_memories_list(self) -> None:
        mock_results = MagicMock()
        mock_results.memories = []

        with patch("app.helpers.message_helpers.memory_service") as mock_svc:
            mock_svc.search_memories = AsyncMock(return_value=mock_results)
            result = await _get_user_memories_section("q", "u")

        assert result == ""

    @pytest.mark.asyncio
    async def test_none_results(self) -> None:
        with patch("app.helpers.message_helpers.memory_service") as mock_svc:
            mock_svc.search_memories = AsyncMock(return_value=None)
            result = await _get_user_memories_section("q", "u")

        assert result == ""

    @pytest.mark.asyncio
    async def test_exception_returns_empty(self) -> None:
        with patch("app.helpers.message_helpers.memory_service") as mock_svc:
            mock_svc.search_memories = AsyncMock(side_effect=RuntimeError("mem fail"))
            result = await _get_user_memories_section("q", "u")

        assert result == ""


# ---------------------------------------------------------------------------
# _get_gaia_knowledge_section
# ---------------------------------------------------------------------------


class TestGetGaiaKnowledgeSection:
    @pytest.mark.asyncio
    async def test_with_results(self) -> None:
        item = MagicMock()
        item.content = "Gaia can manage calendar"

        with patch("app.helpers.message_helpers.gaia_knowledge_service") as mock_svc:
            mock_svc.search_knowledge = AsyncMock(return_value=[item])
            result = await _get_gaia_knowledge_section("calendar")

        assert "Gaia can manage calendar" in result

    @pytest.mark.asyncio
    async def test_no_results(self) -> None:
        with patch("app.helpers.message_helpers.gaia_knowledge_service") as mock_svc:
            mock_svc.search_knowledge = AsyncMock(return_value=[])
            result = await _get_gaia_knowledge_section("q")

        assert result == ""

    @pytest.mark.asyncio
    async def test_none_results(self) -> None:
        with patch("app.helpers.message_helpers.gaia_knowledge_service") as mock_svc:
            mock_svc.search_knowledge = AsyncMock(return_value=None)
            result = await _get_gaia_knowledge_section("q")

        assert result == ""

    @pytest.mark.asyncio
    async def test_exception_returns_empty(self) -> None:
        with patch("app.helpers.message_helpers.gaia_knowledge_service") as mock_svc:
            mock_svc.search_knowledge = AsyncMock(
                side_effect=RuntimeError("chroma fail")
            )
            result = await _get_gaia_knowledge_section("q")

        assert result == ""


# ---------------------------------------------------------------------------
# get_memory_message
# ---------------------------------------------------------------------------


class TestGetMemoryMessage:
    @pytest.mark.asyncio
    async def test_full_context(self) -> None:
        with (
            patch(
                "app.helpers.message_helpers._get_user_memories_section",
                new_callable=AsyncMock,
                return_value="\nMemory section",
            ),
            patch(
                "app.helpers.message_helpers._get_gaia_knowledge_section",
                new_callable=AsyncMock,
                return_value="\nKnowledge section",
            ),
            patch(
                "app.helpers.message_helpers.format_user_preferences_for_agent",
                return_value="Profession: Engineer",
            ),
        ):
            msg = await get_memory_message(
                user_id="u1",
                query="hello",
                user_name="Alice",
                user_timezone="America/New_York",
                user_preferences={"profession": "engineer"},
            )

        assert isinstance(msg, SystemMessage)
        assert "Alice" in msg.content
        assert "Profession: Engineer" in msg.content
        assert "America/New_York" in msg.content
        assert "Memory section" in msg.content
        assert "Knowledge section" in msg.content

    @pytest.mark.asyncio
    async def test_no_optional_fields(self) -> None:
        with (
            patch(
                "app.helpers.message_helpers._get_user_memories_section",
                new_callable=AsyncMock,
                return_value="",
            ),
            patch(
                "app.helpers.message_helpers._get_gaia_knowledge_section",
                new_callable=AsyncMock,
                return_value="",
            ),
        ):
            msg = await get_memory_message(
                user_id="u1",
                query="hi",
            )

        assert isinstance(msg, SystemMessage)
        assert "UTC" in msg.content

    @pytest.mark.asyncio
    async def test_invalid_timezone(self) -> None:
        with (
            patch(
                "app.helpers.message_helpers._get_user_memories_section",
                new_callable=AsyncMock,
                return_value="",
            ),
            patch(
                "app.helpers.message_helpers._get_gaia_knowledge_section",
                new_callable=AsyncMock,
                return_value="",
            ),
        ):
            msg = await get_memory_message(
                user_id="u1",
                query="hi",
                user_timezone="Invalid/TZ",
            )

        # Should still return a message (warning is logged, timezone skipped)
        assert isinstance(msg, SystemMessage)

    @pytest.mark.asyncio
    async def test_error_returns_minimal_context(self) -> None:
        with patch(
            "app.helpers.message_helpers.format_user_preferences_for_agent",
            side_effect=RuntimeError("boom"),
        ):
            msg = await get_memory_message(
                user_id="u1",
                query="hi",
                user_preferences={"x": "y"},
            )

        assert isinstance(msg, SystemMessage)
        assert "UTC" in msg.content


# ---------------------------------------------------------------------------
# format_tool_selection_message
# ---------------------------------------------------------------------------


class TestFormatToolSelectionMessage:
    def test_with_content(self) -> None:
        result = format_tool_selection_message(
            selected_tool="web_search",
            existing_content="Find info about AI",
            tool_category="search",
        )
        assert "Find info about AI" in result
        assert "Web Search" in result
        assert "TOOL SELECTION" in result

    def test_without_content(self) -> None:
        result = format_tool_selection_message(
            selected_tool="code_exec",
            existing_content="",
            tool_category="code",
        )
        assert "TOOL EXECUTION REQUEST" in result
        assert "Code Exec" in result

    def test_no_category(self) -> None:
        result = format_tool_selection_message(
            selected_tool="my_tool",
            existing_content="do something",
        )
        assert "general" in result


# ---------------------------------------------------------------------------
# format_workflow_execution_message
# ---------------------------------------------------------------------------


class TestFormatWorkflowExecutionMessage:
    @pytest.mark.asyncio
    async def test_manual_with_db_workflow(self) -> None:
        selected = SelectedWorkflowData(
            id="wf1",
            title="My Workflow",
            description="desc",
            steps=[{"title": "Step 1", "category": "ai", "description": "Do AI"}],
        )
        mock_wf = MagicMock()
        mock_wf.title = "DB Workflow"
        mock_wf.effective_prompt = "DB prompt"
        step = MagicMock()
        step.title = "DB Step"
        step.category = "automation"
        step.description = "Auto step"
        mock_wf.steps = [step]

        with patch(
            "app.helpers.message_helpers.WorkflowService.get_workflow",
            new_callable=AsyncMock,
            return_value=mock_wf,
        ):
            result = await format_workflow_execution_message(
                selected, user_id="u1", existing_content="Run it"
            )

        assert "DB Workflow" in result
        assert "DB Step" in result

    @pytest.mark.asyncio
    async def test_manual_fallback_to_selected_data(self) -> None:
        selected = SelectedWorkflowData(
            id="wf2",
            title="Fallback WF",
            description="fallback desc",
            prompt="custom prompt",
            steps=[{"title": "S1", "category": "c1", "description": "d1"}],
        )

        with patch(
            "app.helpers.message_helpers.WorkflowService.get_workflow",
            new_callable=AsyncMock,
            return_value=None,
        ):
            result = await format_workflow_execution_message(selected, user_id="u1")

        assert "Fallback WF" in result

    @pytest.mark.asyncio
    async def test_email_triggered(self) -> None:
        selected = SelectedWorkflowData(
            id="wf3",
            title="Email WF",
            description="email desc",
            steps=[{"title": "ES", "category": "email", "description": "email step"}],
        )
        trigger_ctx = {
            "type": "gmail",
            "email_data": {
                "sender": "john@example.com",
                "subject": "Hello",
                "message_text": "Short msg",
            },
            "triggered_at": "2024-01-01T00:00:00Z",
        }

        with patch(
            "app.helpers.message_helpers.WorkflowService.get_workflow",
            new_callable=AsyncMock,
            return_value=None,
        ):
            result = await format_workflow_execution_message(
                selected, user_id="u1", trigger_context=trigger_ctx
            )

        assert "john@example.com" in result
        assert "Hello" in result

    @pytest.mark.asyncio
    async def test_no_user_id(self) -> None:
        selected = SelectedWorkflowData(
            id="wf4",
            title="No User WF",
            description="d",
            steps=[{"title": "S", "category": "c", "description": "d"}],
        )
        result = await format_workflow_execution_message(selected)
        assert "No User WF" in result

    @pytest.mark.asyncio
    async def test_db_fetch_error_falls_back(self) -> None:
        selected = SelectedWorkflowData(
            id="wf5",
            title="Error WF",
            description="err desc",
            steps=[{"title": "E", "category": "e", "description": "e"}],
        )

        with patch(
            "app.helpers.message_helpers.WorkflowService.get_workflow",
            new_callable=AsyncMock,
            side_effect=RuntimeError("db error"),
        ):
            result = await format_workflow_execution_message(selected, user_id="u1")

        assert "Error WF" in result

    @pytest.mark.asyncio
    async def test_email_triggered_long_message(self) -> None:
        """Message text > 200 chars gets truncated with ellipsis."""
        selected = SelectedWorkflowData(
            id="wf6",
            title="Long Email WF",
            description="d",
            steps=[{"title": "S", "category": "c", "description": "d"}],
        )
        trigger_ctx = {
            "type": "gmail",
            "email_data": {
                "sender": "a@b.com",
                "subject": "Subj",
                "message_text": "A" * 300,
            },
            "triggered_at": "now",
        }

        with patch(
            "app.helpers.message_helpers.WorkflowService.get_workflow",
            new_callable=AsyncMock,
            return_value=None,
        ):
            result = await format_workflow_execution_message(
                selected, user_id="u1", trigger_context=trigger_ctx
            )

        assert "..." in result


# ---------------------------------------------------------------------------
# format_calendar_event_context
# ---------------------------------------------------------------------------


class TestFormatCalendarEventContext:
    def test_timed_event_with_content(self) -> None:
        event = SelectedCalendarEventData(
            id="ev1",
            summary="Team Standup",
            description="Daily sync",
            start={"dateTime": "2024-01-01T09:00:00"},
            end={"dateTime": "2024-01-01T09:30:00"},
            calendarTitle="Work",
        )
        result = format_calendar_event_context(event, "What should I prepare?")
        assert "Team Standup" in result
        assert "Work" in result
        assert "What should I prepare?" in result

    def test_all_day_event(self) -> None:
        event = SelectedCalendarEventData(
            id="ev2",
            summary="Holiday",
            description="",
            start={"date": "2024-12-25"},
            end={"date": "2024-12-26"},
            isAllDay=True,
        )
        result = format_calendar_event_context(event)
        assert "All day" in result
        assert "2024-12-25" in result

    def test_no_calendar_title(self) -> None:
        event = SelectedCalendarEventData(
            id="ev3",
            summary="Meeting",
            description="desc",
            start={"dateTime": "2024-01-01T10:00:00"},
            end={"dateTime": "2024-01-01T11:00:00"},
        )
        result = format_calendar_event_context(event)
        assert "Calendar:" not in result


# ---------------------------------------------------------------------------
# format_reply_context
# ---------------------------------------------------------------------------


class TestFormatReplyContext:
    def test_reply_to_user_message(self) -> None:
        reply = ReplyToMessageData(id="m1", content="I said this", role="user")
        result = format_reply_context(reply, "Actually, I meant something else")
        assert "their own" in result
        assert "I said this" in result

    def test_reply_to_bot_message(self) -> None:
        reply = ReplyToMessageData(id="m2", content="AI response", role="assistant")
        result = format_reply_context(reply)
        assert "your" in result
        assert "AI response" in result

    def test_no_existing_content(self) -> None:
        reply = ReplyToMessageData(id="m3", content="msg", role="user")
        result = format_reply_context(reply)
        assert result.startswith("[")


# ---------------------------------------------------------------------------
# format_files_list
# ---------------------------------------------------------------------------


class TestFormatFilesList:
    def test_no_files(self) -> None:
        assert format_files_list(None) == "No files uploaded."
        assert format_files_list([]) == "No files uploaded."

    def test_empty_file_ids(self) -> None:
        files = [FileData(fileId="f1", url="u", filename="test.txt")]
        assert format_files_list(files, file_ids=[]) == "No files uploaded."

    def test_all_files(self) -> None:
        files = [
            FileData(fileId="f1", url="u1", filename="a.txt"),
            FileData(fileId="f2", url="u2", filename="b.pdf"),
        ]
        result = format_files_list(files)
        assert "a.txt" in result
        assert "b.pdf" in result
        assert "f1" in result

    def test_filtered_by_ids(self) -> None:
        files = [
            FileData(fileId="f1", url="u1", filename="a.txt"),
            FileData(fileId="f2", url="u2", filename="b.pdf"),
        ]
        result = format_files_list(files, file_ids=["f1"])
        assert "a.txt" in result
        assert "b.pdf" not in result

    def test_no_matching_ids(self) -> None:
        files = [FileData(fileId="f1", url="u", filename="a.txt")]
        assert format_files_list(files, file_ids=["f99"]) == "No files uploaded."

    def test_file_ids_none_returns_all(self) -> None:
        files = [FileData(fileId="f1", url="u", filename="a.txt")]
        result = format_files_list(files, file_ids=None)
        assert "a.txt" in result
