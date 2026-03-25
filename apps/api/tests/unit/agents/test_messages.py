"""Unit tests for app.agents.core.messages — construct_langchain_messages."""

from unittest.mock import AsyncMock, patch

import pytest
from langchain_core.messages import HumanMessage, SystemMessage

from app.agents.core.messages import construct_langchain_messages
from app.models.message_models import (
    FileData,
    ReplyToMessageData,
    SelectedCalendarEventData,
    SelectedWorkflowData,
)


# ---------------------------------------------------------------------------
# Fixtures & helpers
# ---------------------------------------------------------------------------

SYSTEM_MSG = SystemMessage(content="System prompt here")
MEMORY_MSG = SystemMessage(content="Memory context", memory_message=True)


def _patches(
    system_msg=SYSTEM_MSG,
    memory_msg=MEMORY_MSG,
    workflow_msg: str = "Workflow exec",
    calendar_msg: str = "Calendar context",
    tool_msg: str = "Tool selection",
    reply_msg: str = "Reply context\n\noriginal",
    files_str: str = "",
):
    """Create a dict of context-manager patches for message_helpers functions."""
    return {
        "create_system": patch(
            "app.agents.core.messages.create_system_message",
            return_value=system_msg,
        ),
        "get_memory": patch(
            "app.agents.core.messages.get_memory_message",
            new_callable=AsyncMock,
            return_value=memory_msg,
        ),
        "format_workflow": patch(
            "app.agents.core.messages.format_workflow_execution_message",
            new_callable=AsyncMock,
            return_value=workflow_msg,
        ),
        "format_calendar": patch(
            "app.agents.core.messages.format_calendar_event_context",
            return_value=calendar_msg,
        ),
        "format_tool": patch(
            "app.agents.core.messages.format_tool_selection_message",
            return_value=tool_msg,
        ),
        "format_reply": patch(
            "app.agents.core.messages.format_reply_context",
            return_value=reply_msg,
        ),
        "format_files": patch(
            "app.agents.core.messages.format_files_list",
            return_value=files_str,
        ),
    }


# ---------------------------------------------------------------------------
# Basic construction
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestConstructLangchainMessages:
    """Core tests for construct_langchain_messages."""

    @pytest.mark.asyncio
    async def test_basic_user_message(self):
        """Minimal call: system + human message."""
        p = _patches()
        with p["create_system"], p["get_memory"], p["format_files"]:
            result = await construct_langchain_messages(
                messages=[{"role": "user", "content": "Hi there"}],
            )

        assert len(result) == 2
        assert isinstance(result[0], SystemMessage)
        assert isinstance(result[1], HumanMessage)
        assert result[1].content == "Hi there"

    @pytest.mark.asyncio
    async def test_system_message_created_with_user_name(self):
        p = _patches()
        with p["create_system"] as mock_sys, p["get_memory"], p["format_files"]:
            await construct_langchain_messages(
                messages=[{"role": "user", "content": "Hello"}],
                user_name="Alice",
                user_id="uid-1",
            )

        mock_sys.assert_called_once_with("uid-1", "Alice", "comms")

    @pytest.mark.asyncio
    async def test_agent_type_passed_to_system_message(self):
        p = _patches()
        with p["create_system"] as mock_sys, p["get_memory"], p["format_files"]:
            await construct_langchain_messages(
                messages=[{"role": "user", "content": "Hello"}],
                agent_type="executor",
            )

        mock_sys.assert_called_once()
        assert mock_sys.call_args[0][2] == "executor"


# ---------------------------------------------------------------------------
# Memory retrieval
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestMemoryRetrieval:
    """Tests for memory message inclusion."""

    @pytest.mark.asyncio
    async def test_memory_included_when_user_id_and_query(self):
        p = _patches()
        with p["create_system"], p["get_memory"] as mock_mem, p["format_files"]:
            result = await construct_langchain_messages(
                messages=[{"role": "user", "content": "weather"}],
                user_id="uid-1",
                query="weather",
            )

        mock_mem.assert_awaited_once()
        # system + memory + human = 3
        assert len(result) == 3
        assert result[1] is MEMORY_MSG

    @pytest.mark.asyncio
    async def test_memory_skipped_when_no_user_id(self):
        p = _patches()
        with p["create_system"], p["get_memory"] as mock_mem, p["format_files"]:
            result = await construct_langchain_messages(
                messages=[{"role": "user", "content": "weather"}],
                query="weather",
            )

        mock_mem.assert_not_awaited()
        assert len(result) == 2

    @pytest.mark.asyncio
    async def test_memory_skipped_when_no_query(self):
        p = _patches()
        with p["create_system"], p["get_memory"] as mock_mem, p["format_files"]:
            result = await construct_langchain_messages(
                messages=[{"role": "user", "content": "hello"}],
                user_id="uid-1",
            )

        mock_mem.assert_not_awaited()
        assert len(result) == 2

    @pytest.mark.asyncio
    async def test_memory_none_not_appended(self):
        """If get_memory_message returns None, it should not be in the list."""
        p = _patches(memory_msg=None)
        with p["create_system"], p["get_memory"], p["format_files"]:
            result = await construct_langchain_messages(
                messages=[{"role": "user", "content": "hello"}],
                user_id="uid-1",
                query="hello",
            )

        # Only system + human
        assert len(result) == 2

    @pytest.mark.asyncio
    async def test_memory_receives_user_dict_timezone(self):
        p = _patches()
        user_dict = {
            "timezone": "Asia/Kolkata",
            "onboarding": {"preferences": {"tone": "formal"}},
        }
        with p["create_system"], p["get_memory"] as mock_mem, p["format_files"]:
            await construct_langchain_messages(
                messages=[{"role": "user", "content": "hi"}],
                user_id="uid-1",
                query="hi",
                user_dict=user_dict,
            )

        kwargs = mock_mem.call_args.kwargs
        assert kwargs["user_timezone"] == "Asia/Kolkata"
        assert kwargs["user_preferences"] == {"tone": "formal"}


# ---------------------------------------------------------------------------
# Content priority: workflow > calendar > tool > user message
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestContentPriority:
    """Tests for the priority logic in content selection."""

    @pytest.mark.asyncio
    async def test_workflow_takes_priority(self):
        workflow = SelectedWorkflowData(
            id="wf-1",
            title="Test WF",
            description="desc",
            steps=[{"title": "s1", "category": "c1", "description": "d1"}],
        )
        p = _patches(workflow_msg="WORKFLOW OUTPUT")
        with (
            p["create_system"],
            p["get_memory"],
            p["format_workflow"] as mock_wf,
            p["format_calendar"],
            p["format_tool"],
            p["format_files"],
        ):
            result = await construct_langchain_messages(
                messages=[{"role": "user", "content": "run it"}],
                selected_workflow=workflow,
                user_id="uid",
            )

        mock_wf.assert_awaited_once()
        assert result[-1].content == "WORKFLOW OUTPUT"

    @pytest.mark.asyncio
    async def test_calendar_when_no_workflow(self):
        cal_event = SelectedCalendarEventData(
            id="e-1",
            summary="Meeting",
            description="Team sync",
            start={"dateTime": "2025-01-01T10:00:00Z"},
            end={"dateTime": "2025-01-01T11:00:00Z"},
        )
        p = _patches(calendar_msg="CALENDAR OUTPUT")
        with (
            p["create_system"],
            p["get_memory"],
            p["format_calendar"] as mock_cal,
            p["format_tool"],
            p["format_files"],
        ):
            result = await construct_langchain_messages(
                messages=[{"role": "user", "content": "what about this"}],
                selected_calendar_event=cal_event,
            )

        mock_cal.assert_called_once()
        assert result[-1].content == "CALENDAR OUTPUT"

    @pytest.mark.asyncio
    async def test_tool_selection_when_no_workflow_or_calendar(self):
        p = _patches(tool_msg="TOOL OUTPUT")
        with (
            p["create_system"],
            p["get_memory"],
            p["format_tool"] as mock_tool,
            p["format_files"],
        ):
            result = await construct_langchain_messages(
                messages=[{"role": "user", "content": "use this tool"}],
                selected_tool="web_search",
            )

        mock_tool.assert_called_once()
        assert result[-1].content == "TOOL OUTPUT"

    @pytest.mark.asyncio
    async def test_tool_category_passed(self):
        p = _patches(tool_msg="TOOL OUTPUT")
        with (
            p["create_system"],
            p["get_memory"],
            p["format_tool"] as mock_tool,
            p["format_files"],
        ):
            await construct_langchain_messages(
                messages=[{"role": "user", "content": "search"}],
                selected_tool="web_search",
                tool_category="search",
            )

        args = mock_tool.call_args[0]
        assert args[0] == "web_search"
        assert args[2] == "search"

    @pytest.mark.asyncio
    async def test_user_content_fallback(self):
        """When no workflow/calendar/tool, the user message content is used."""
        p = _patches()
        with p["create_system"], p["get_memory"], p["format_files"]:
            result = await construct_langchain_messages(
                messages=[{"role": "user", "content": "plain text"}],
            )

        assert result[-1].content == "plain text"


# ---------------------------------------------------------------------------
# Edge cases for user content extraction
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestUserContentExtraction:
    """Tests for extracting user content from messages list."""

    @pytest.mark.asyncio
    async def test_last_message_not_user_gives_empty_content(self):
        """If last message is not role=user, content is empty and should raise."""
        p = _patches()
        with p["create_system"], p["get_memory"], p["format_files"]:
            with pytest.raises(ValueError, match="No human message"):
                await construct_langchain_messages(
                    messages=[{"role": "assistant", "content": "Hi"}],
                )

    @pytest.mark.asyncio
    async def test_empty_messages_list_raises(self):
        p = _patches()
        with p["create_system"], p["get_memory"], p["format_files"]:
            with pytest.raises(ValueError, match="No human message"):
                await construct_langchain_messages(messages=[])

    @pytest.mark.asyncio
    async def test_whitespace_only_content_raises(self):
        p = _patches()
        with p["create_system"], p["get_memory"], p["format_files"]:
            with pytest.raises(ValueError, match="No human message"):
                await construct_langchain_messages(
                    messages=[{"role": "user", "content": "   "}],
                )


# ---------------------------------------------------------------------------
# Reply-to-message context
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestReplyContext:
    """Tests for reply_to_message injection."""

    @pytest.mark.asyncio
    async def test_reply_context_added(self):
        reply = ReplyToMessageData(id="msg-1", content="original msg", role="user")
        p = _patches(reply_msg="[reply context]\n\nuser content")
        with (
            p["create_system"],
            p["get_memory"],
            p["format_reply"] as mock_reply,
            p["format_files"],
        ):
            result = await construct_langchain_messages(
                messages=[{"role": "user", "content": "user content"}],
                reply_to_message=reply,
            )

        mock_reply.assert_called_once_with(reply, "user content")
        assert result[-1].content == "[reply context]\n\nuser content"

    @pytest.mark.asyncio
    async def test_no_reply_context_without_data(self):
        p = _patches()
        with (
            p["create_system"],
            p["get_memory"],
            p["format_reply"] as mock_reply,
            p["format_files"],
        ):
            await construct_langchain_messages(
                messages=[{"role": "user", "content": "hello"}],
            )

        mock_reply.assert_not_called()


# ---------------------------------------------------------------------------
# File context
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestFileContext:
    """Tests for file context appending."""

    @pytest.mark.asyncio
    async def test_files_appended_to_content(self):
        files_data = [
            FileData(fileId="f1", url="https://example.com/f1", filename="test.txt"),
        ]
        p = _patches(files_str="Uploaded Files:\n- Name: test.txt Id: f1")
        with (
            p["create_system"],
            p["get_memory"],
            p["format_files"] as mock_files,
        ):
            result = await construct_langchain_messages(
                messages=[{"role": "user", "content": "check this"}],
                files_data=files_data,
                currently_uploaded_file_ids=["f1"],
            )

        mock_files.assert_called_once_with(files_data, ["f1"])
        assert "Uploaded Files" in result[-1].content
        assert result[-1].content.startswith("check this")

    @pytest.mark.asyncio
    async def test_no_files_when_ids_empty(self):
        p = _patches()
        with (
            p["create_system"],
            p["get_memory"],
            p["format_files"] as mock_files,
        ):
            result = await construct_langchain_messages(
                messages=[{"role": "user", "content": "hello"}],
                currently_uploaded_file_ids=[],
            )

        mock_files.assert_not_called()
        assert result[-1].content == "hello"

    @pytest.mark.asyncio
    async def test_files_empty_string_not_appended(self):
        """If format_files_list returns empty string, nothing is appended."""
        p = _patches(files_str="")
        with (
            p["create_system"],
            p["get_memory"],
            p["format_files"],
        ):
            result = await construct_langchain_messages(
                messages=[{"role": "user", "content": "hello"}],
                currently_uploaded_file_ids=["f1"],
            )

        assert result[-1].content == "hello"

    @pytest.mark.asyncio
    async def test_no_files_when_ids_none(self):
        """When currently_uploaded_file_ids is None (default), no files context."""
        p = _patches()
        with (
            p["create_system"],
            p["get_memory"],
            p["format_files"] as mock_files,
        ):
            await construct_langchain_messages(
                messages=[{"role": "user", "content": "hello"}],
                currently_uploaded_file_ids=None,
            )

        mock_files.assert_not_called()


# ---------------------------------------------------------------------------
# Trigger context
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestTriggerContext:
    """Tests for trigger_context passing to workflow formatter."""

    @pytest.mark.asyncio
    async def test_trigger_context_passed_to_workflow(self):
        workflow = SelectedWorkflowData(
            id="wf-1",
            title="Email WF",
            description="desc",
            steps=[{"title": "s1", "category": "c1", "description": "d1"}],
        )
        trigger = {"type": "gmail", "email_data": {"sender": "a@b.com"}}
        p = _patches()
        with (
            p["create_system"],
            p["get_memory"],
            p["format_workflow"] as mock_wf,
            p["format_files"],
        ):
            await construct_langchain_messages(
                messages=[{"role": "user", "content": "run"}],
                selected_workflow=workflow,
                trigger_context=trigger,
                user_id="uid",
            )

        call_args = mock_wf.call_args
        assert call_args[0][2] == trigger  # third positional arg
