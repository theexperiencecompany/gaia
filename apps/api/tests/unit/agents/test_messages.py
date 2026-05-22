"""Unit tests for app.agents.core.messages — construct_langchain_messages.

After the caching optimisation work, the message-construction contract is:

    [static_main_prompt, dynamic_context_message, human_task]

The static main prompt is byte-identical across users/channels. Everything
per-user/per-turn (user name, memories, platform restrictions, OpenUI
availability) lives in the dynamic-context message built by
``build_dynamic_context_message``. These tests exercise the orchestration —
they patch ``create_system_message`` and ``build_dynamic_context_message``
and verify the assembled message list.
"""

from typing import Any
from unittest.mock import AsyncMock, patch

from langchain_core.messages import HumanMessage, SystemMessage
import pytest

from app.agents.core.messages import construct_langchain_messages
from app.models.message_models import (
    FileData,
    ReplyToMessageData,
    SelectedCalendarEventData,
    SelectedWorkflowData,
)

SYSTEM_MSG = SystemMessage(content="System prompt here")
DYNAMIC_MSG = SystemMessage(
    content="Dynamic context",
    additional_kwargs={"dynamic_context": True, "memory_message": True},
)


def _patches(
    system_msg: SystemMessage = SYSTEM_MSG,
    dynamic_msg: SystemMessage = DYNAMIC_MSG,
    workflow_msg: str = "Workflow exec",
    calendar_msg: str = "Calendar context",
    tool_msg: str = "Tool selection",
    reply_msg: str = "Reply context\n\noriginal",
    files_str: str = "",
) -> dict[str, Any]:
    """Bundle context-manager patches for the helpers `construct_langchain_messages` calls."""
    return {
        "create_system": patch(
            "app.agents.core.messages.create_system_message",
            return_value=system_msg,
        ),
        "build_dynamic": patch(
            "app.agents.core.messages.build_dynamic_context_message",
            new_callable=AsyncMock,
            return_value=dynamic_msg,
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


@pytest.mark.unit
class TestConstructLangchainMessages:
    """Exercise the [static, dynamic, human] assembly."""

    @pytest.mark.asyncio
    async def test_basic_user_message(self) -> None:
        """Shape is [static, dynamic_context, time_msg, human_task].

        The time HumanMessage is split off from the task so minute ticks
        don't invalidate the ``system_instruction`` prefix.
        """
        p = _patches()
        with p["create_system"], p["build_dynamic"], p["format_files"]:
            result = await construct_langchain_messages(
                messages=[{"role": "user", "content": "Hi there"}],
            )

        assert len(result) == 4
        assert isinstance(result[0], SystemMessage)
        assert isinstance(result[1], SystemMessage)
        assert result[1].additional_kwargs.get("dynamic_context") is True
        # Third is the current-time HumanMessage.
        assert isinstance(result[2], HumanMessage)
        assert result[2].additional_kwargs.get("time_context") is True
        # Fourth is the actual user task.
        assert isinstance(result[3], HumanMessage)
        assert result[3].content == "Hi there"

    @pytest.mark.asyncio
    async def test_create_system_receives_agent_type_and_source(self) -> None:
        p = _patches()
        with p["create_system"] as mock_sys, p["build_dynamic"], p["format_files"]:
            await construct_langchain_messages(
                messages=[{"role": "user", "content": "Hello"}],
                agent_type="executor",
                source="web",
            )
        mock_sys.assert_called_once()
        kwargs = mock_sys.call_args.kwargs
        assert kwargs["agent_type"] == "executor"
        assert kwargs["source"] == "web"

    @pytest.mark.asyncio
    async def test_dynamic_message_receives_user_and_source(self) -> None:
        p = _patches()
        user_dict = {
            "timezone": "Asia/Kolkata",
            "onboarding": {"preferences": {"tone": "formal"}},
        }
        with p["create_system"], p["build_dynamic"] as mock_dyn, p["format_files"]:
            await construct_langchain_messages(
                messages=[{"role": "user", "content": "hi"}],
                user_id="uid-1",
                user_name="Alice",
                user_dict=user_dict,
                query="hi",
                agent_type="comms",
                source="whatsapp",
            )

        kwargs = mock_dyn.call_args.kwargs
        assert kwargs["user_id"] == "uid-1"
        assert kwargs["user_name"] == "Alice"
        assert kwargs["user_timezone"] == "Asia/Kolkata"
        assert kwargs["user_preferences"] == {"tone": "formal"}
        assert kwargs["query"] == "hi"
        assert kwargs["source"] == "whatsapp"

    @pytest.mark.asyncio
    async def test_source_passed_to_static_prompt_selector(self) -> None:
        """The per-channel static prompt is selected via the ``source`` kwarg
        on ``create_system_message``. Different sources must produce different
        static prompts (OpenUI on web, platform restrictions on WhatsApp).
        """
        p = _patches()
        with p["create_system"] as mock_sys, p["build_dynamic"], p["format_files"]:
            await construct_langchain_messages(
                messages=[{"role": "user", "content": "hi"}],
                agent_type="comms",
                source="telegram",
            )
        assert mock_sys.call_args.kwargs["source"] == "telegram"


@pytest.mark.unit
class TestContentPriority:
    """Workflow > calendar > tool selection > raw user message."""

    @pytest.mark.asyncio
    async def test_workflow_takes_priority(self) -> None:
        workflow = SelectedWorkflowData(
            id="wf-1",
            title="Test WF",
            description="desc",
            steps=[{"title": "s1", "category": "c1", "description": "d1"}],
        )
        p = _patches(workflow_msg="WORKFLOW OUTPUT")
        with (
            p["create_system"],
            p["build_dynamic"],
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
    async def test_calendar_when_no_workflow(self) -> None:
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
            p["build_dynamic"],
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
    async def test_tool_selection_when_no_workflow_or_calendar(self) -> None:
        p = _patches(tool_msg="TOOL OUTPUT")
        with (
            p["create_system"],
            p["build_dynamic"],
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
    async def test_tool_category_passed(self) -> None:
        p = _patches(tool_msg="TOOL OUTPUT")
        with (
            p["create_system"],
            p["build_dynamic"],
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
    async def test_user_content_fallback(self) -> None:
        p = _patches()
        with p["create_system"], p["build_dynamic"], p["format_files"]:
            result = await construct_langchain_messages(
                messages=[{"role": "user", "content": "plain text"}],
            )

        assert result[-1].content == "plain text"


@pytest.mark.unit
class TestUserContentExtraction:
    """User content edge cases."""

    @pytest.mark.asyncio
    async def test_last_message_not_user_gives_empty_content(self) -> None:
        p = _patches()
        with p["create_system"], p["build_dynamic"], p["format_files"]:
            with pytest.raises(ValueError, match="No human message"):
                await construct_langchain_messages(
                    messages=[{"role": "assistant", "content": "Hi"}],
                )

    @pytest.mark.asyncio
    async def test_empty_messages_list_raises(self) -> None:
        p = _patches()
        with p["create_system"], p["build_dynamic"], p["format_files"]:
            with pytest.raises(ValueError, match="No human message"):
                await construct_langchain_messages(messages=[])

    @pytest.mark.asyncio
    async def test_whitespace_only_content_raises(self) -> None:
        p = _patches()
        with p["create_system"], p["build_dynamic"], p["format_files"]:
            with pytest.raises(ValueError, match="No human message"):
                await construct_langchain_messages(
                    messages=[{"role": "user", "content": "   "}],
                )


@pytest.mark.unit
class TestReplyContext:
    @pytest.mark.asyncio
    async def test_reply_context_added(self) -> None:
        reply = ReplyToMessageData(id="msg-1", content="original msg", role="user")
        p = _patches(reply_msg="[reply context]\n\nuser content")
        with (
            p["create_system"],
            p["build_dynamic"],
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
    async def test_no_reply_context_without_data(self) -> None:
        p = _patches()
        with (
            p["create_system"],
            p["build_dynamic"],
            p["format_reply"] as mock_reply,
            p["format_files"],
        ):
            await construct_langchain_messages(
                messages=[{"role": "user", "content": "hello"}],
            )

        mock_reply.assert_not_called()


@pytest.mark.unit
class TestFileContext:
    @pytest.mark.asyncio
    async def test_files_appended_to_content(self) -> None:
        files_data = [
            FileData(fileId="f1", url="https://example.com/f1", filename="test.txt"),
        ]
        p = _patches(files_str="Uploaded Files:\n- Name: test.txt Id: f1")
        with (
            p["create_system"],
            p["build_dynamic"],
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
    async def test_no_files_when_ids_empty(self) -> None:
        p = _patches()
        with (
            p["create_system"],
            p["build_dynamic"],
            p["format_files"] as mock_files,
        ):
            result = await construct_langchain_messages(
                messages=[{"role": "user", "content": "hello"}],
                currently_uploaded_file_ids=[],
            )

        mock_files.assert_not_called()
        assert result[-1].content == "hello"

    @pytest.mark.asyncio
    async def test_files_empty_string_not_appended(self) -> None:
        p = _patches(files_str="")
        with (
            p["create_system"],
            p["build_dynamic"],
            p["format_files"],
        ):
            result = await construct_langchain_messages(
                messages=[{"role": "user", "content": "hello"}],
                currently_uploaded_file_ids=["f1"],
            )

        assert result[-1].content == "hello"

    @pytest.mark.asyncio
    async def test_no_files_when_ids_none(self) -> None:
        p = _patches()
        with (
            p["create_system"],
            p["build_dynamic"],
            p["format_files"] as mock_files,
        ):
            await construct_langchain_messages(
                messages=[{"role": "user", "content": "hello"}],
                currently_uploaded_file_ids=None,
            )

        mock_files.assert_not_called()


@pytest.mark.unit
class TestTriggerContext:
    @pytest.mark.asyncio
    async def test_trigger_context_passed_to_workflow(self) -> None:
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
            p["build_dynamic"],
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
        assert call_args[0][2] == trigger
