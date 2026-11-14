"""Unit tests for app.agents.core.messages — comms_turn_messages.

After the caching optimisation work, the message-construction contract is:

    [static_main_prompt, dynamic_stable, memory_recall?, human_task, time_msg]

The static main prompt is byte-identical across users/channels. Per-user
identity (name, timezone, preferences, integrations) lives in the stable
dynamic-context message; volatile per-turn content (memory recall, knowledge,
skills, todos) lives in an optional memory-recall message. Both are built by
the shared context-assembly module. The current-time HumanMessage is appended
LAST so minute ticks never shift the cacheable prefix. These tests exercise the
orchestration — they patch create_system_message and assemble_context
and verify the assembled message list.
"""

from typing import Any, NamedTuple
from unittest.mock import AsyncMock, patch

from langchain_core.messages import HumanMessage, SystemMessage
import pytest

from app.agents.context.assemble import AssembledContext
from app.agents.context.tiers import AgentTier
from app.agents.core.messages import (
    MessageAttachments,
    MessageScope,
)
from app.models.calendar_models import GoogleCalendarEventDateTime
from app.models.message_models import FileData, SelectedCalendarEventData, SelectedWorkflowData
from app.models.user_models import AuthenticatedUser, OnboardingSubdocument
from app.models.workflow_models import WorkflowStep
from shared.py.conversation_wire import ReplyToMessageData
from tests._harness.context_chain import comms_turn_messages

SYSTEM_MSG = SystemMessage(content="System prompt here")
DYNAMIC_MSG = SystemMessage(
    content="Dynamic context",
    additional_kwargs={"dynamic_context": True, "memory_message": True},
)


class _Returns(NamedTuple):
    """What each patched helper returns; override only what a test asserts on."""

    system_msg: SystemMessage = SYSTEM_MSG
    dynamic_msg: SystemMessage = DYNAMIC_MSG
    memory_recall_msg: SystemMessage | None = None
    workflow_msg: str = "Workflow exec"
    calendar_msg: str = "Calendar context"
    tool_msg: str = "Tool selection"
    reply_msg: str = "Reply context\n\noriginal"
    files_str: str = ""
    server_files: tuple[FileData, ...] = ()


def _patches(returns: _Returns = _Returns()) -> dict[str, Any]:
    """Bundle context-manager patches for the helpers comms_turn_messages calls."""
    return {
        "create_system": patch(
            "app.agents.core.messages.create_system_message",
            return_value=returns.system_msg,
        ),
        "build_dynamic": patch(
            "app.agents.core.messages.assemble_context",
            new_callable=AsyncMock,
            return_value=AssembledContext(
                stable=returns.dynamic_msg, volatile=returns.memory_recall_msg
            ),
        ),
        "format_workflow": patch(
            "app.agents.core.messages.format_workflow_execution_message",
            new_callable=AsyncMock,
            return_value=returns.workflow_msg,
        ),
        "format_calendar": patch(
            "app.agents.core.messages.format_calendar_event_context",
            return_value=returns.calendar_msg,
        ),
        "format_tool": patch(
            "app.agents.core.messages.format_tool_selection_message",
            return_value=returns.tool_msg,
        ),
        "format_reply": patch(
            "app.agents.core.messages.format_reply_context",
            return_value=returns.reply_msg,
        ),
        "format_files": patch(
            "app.agents.core.messages.format_files_list",
            return_value=returns.files_str,
        ),
        "get_uploads": patch(
            "app.agents.core.messages.FileService.get_uploads",
            new_callable=AsyncMock,
            return_value=list(returns.server_files),
        ),
    }


class TestConstructLangchainMessages:
    """Exercise the [static, dynamic, human] assembly."""

    @pytest.mark.asyncio
    async def test_basic_user_message(self) -> None:
        """The time HumanMessage is split off and appended last so minute ticks never shift the cacheable prefix."""
        p = _patches()
        with p["create_system"], p["build_dynamic"], p["format_files"]:
            result = await comms_turn_messages(
                query="Hi there",
            )

        assert len(result) == 4
        assert isinstance(result[0], SystemMessage)
        assert isinstance(result[1], SystemMessage)
        assert result[1].additional_kwargs.get("dynamic_context") is True
        # Third is the actual user task.
        assert isinstance(result[2], HumanMessage)
        assert result[2].content == "Hi there"
        # Fourth (last) is the current-time HumanMessage.
        assert isinstance(result[3], HumanMessage)
        assert result[3].additional_kwargs.get("time_context") is True

    @pytest.mark.asyncio
    async def test_memory_recall_message_slotted_when_present(self) -> None:
        """Shape: [static, dynamic_stable, memory_recall, human_task, time_msg]."""
        recall = SystemMessage(
            content="Recalled memories", additional_kwargs={"memory_recall": True}
        )
        p = _patches(_Returns(memory_recall_msg=recall))
        with p["create_system"], p["build_dynamic"], p["format_files"]:
            result = await comms_turn_messages(
                query="Hi there",
            )

        assert len(result) == 5
        assert result[1].additional_kwargs.get("dynamic_context") is True
        assert result[2].additional_kwargs.get("memory_recall") is True
        assert isinstance(result[3], HumanMessage)
        assert result[3].content == "Hi there"
        assert result[4].additional_kwargs.get("time_context") is True

    @pytest.mark.asyncio
    async def test_create_system_receives_agent_type_and_source(self) -> None:
        p = _patches()
        with p["create_system"] as mock_sys, p["build_dynamic"], p["format_files"]:
            await comms_turn_messages(
                query="Hello",
                scope=MessageScope(agent_type="executor", source="web"),
            )
        mock_sys.assert_called_once()
        kwargs = mock_sys.call_args.kwargs
        assert kwargs["agent_type"] == "executor"
        assert kwargs["source"] == "web"

    @pytest.mark.asyncio
    async def test_dynamic_message_receives_user_and_source(self) -> None:
        p = _patches()
        user_dict = AuthenticatedUser(
            user_id="uid-1",
            timezone="Asia/Kolkata",
            onboarding=OnboardingSubdocument.model_validate(
                {"preferences": {"response_style": "formal"}}
            ),
        )
        with p["create_system"], p["build_dynamic"] as mock_dyn, p["format_files"]:
            await comms_turn_messages(
                query="hi",
                scope=MessageScope(
                    user_id="uid-1",
                    user_name="Alice",
                    user_dict=user_dict,
                    agent_type="comms",
                    source="whatsapp",
                ),
            )

        ctx = mock_dyn.call_args.args[0]
        assert ctx.tier is AgentTier.COMMS
        assert ctx.user_id == "uid-1"
        assert ctx.user_name == "Alice"
        assert ctx.user_timezone == "Asia/Kolkata"
        assert ctx.user_preferences == {"response_style": "formal"}
        assert ctx.query == "hi"
        assert ctx.source == "whatsapp"

    @pytest.mark.asyncio
    async def test_every_field_the_context_is_built_from_survives_the_trip(self) -> None:
        """Every field dropped here silently renders nothing, with no error anywhere."""
        p = _patches()
        user_dict = AuthenticatedUser(
            user_id="uid-1",
            timezone="Asia/Kolkata",
            onboarding=OnboardingSubdocument.model_validate(
                {"preferences": {"response_style": "formal"}, "writing_style": {"case": "lower"}}
            ),
        )
        with p["create_system"], p["build_dynamic"] as mock_dyn, p["format_files"]:
            await comms_turn_messages(
                query="hi",
                scope=MessageScope(
                    user_id="uid-1",
                    user_name="Alice",
                    user_dict=user_dict,
                    active_todo_id="todo-7",
                    execution_mode="background",
                    source="slack",
                ),
            )

        ctx = mock_dyn.call_args.args[0]
        assert ctx.writing_style == {"case": "lower"}
        assert ctx.active_todo_id == "todo-7"
        assert ctx.execution_mode == "background"
        assert ctx.source == "slack"

    @pytest.mark.asyncio
    async def test_a_user_with_no_onboarding_answers_carries_none_not_a_crash(self) -> None:
        p = _patches()
        with p["create_system"], p["build_dynamic"] as mock_dyn, p["format_files"]:
            await comms_turn_messages(
                query="hi",
                scope=MessageScope(user_id="uid-1", user_dict=AuthenticatedUser(user_id="uid-1")),
            )

        ctx = mock_dyn.call_args.args[0]
        assert ctx.user_timezone is None
        assert ctx.user_preferences is None
        assert ctx.writing_style is None

    @pytest.mark.asyncio
    async def test_an_unauthenticated_turn_carries_no_user_fields(self) -> None:
        p = _patches()
        with p["create_system"], p["build_dynamic"] as mock_dyn, p["format_files"]:
            await comms_turn_messages(
                query="hi",
                scope=MessageScope(user_dict=None),
            )

        ctx = mock_dyn.call_args.args[0]
        assert ctx.user_timezone is None
        assert ctx.user_preferences is None
        assert ctx.writing_style is None

    @pytest.mark.asyncio
    async def test_source_passed_to_static_prompt_selector(self) -> None:
        """The per-channel static prompt is selected via the source kwarg on create_system_message."""
        p = _patches()
        with p["create_system"] as mock_sys, p["build_dynamic"], p["format_files"]:
            await comms_turn_messages(
                query="hi",
                scope=MessageScope(agent_type="comms", source="telegram"),
            )
        assert mock_sys.call_args.kwargs["source"] == "telegram"


class TestContentPriority:
    """Workflow > calendar > tool selection > raw user message."""

    @pytest.mark.asyncio
    async def test_workflow_takes_priority(self) -> None:
        workflow = SelectedWorkflowData(
            id="wf-1",
            title="Test WF",
            description="desc",
            steps=[WorkflowStep(title="s1", category="c1", description="d1")],
        )
        p = _patches(_Returns(workflow_msg="WORKFLOW OUTPUT"))
        with (
            p["create_system"],
            p["build_dynamic"],
            p["format_workflow"] as mock_wf,
            p["format_calendar"],
            p["format_tool"],
            p["format_files"],
        ):
            result = await comms_turn_messages(
                query="run it",
                scope=MessageScope(user_id="uid"),
                attachments=MessageAttachments(selected_workflow=workflow),
            )

        mock_wf.assert_awaited_once_with(workflow, "uid", None, "run it")
        # result[-1] is the current-time message; the task is second-to-last.
        assert result[-2].content == "WORKFLOW OUTPUT"

    @pytest.mark.asyncio
    async def test_calendar_when_no_workflow(self) -> None:
        cal_event = SelectedCalendarEventData(
            id="e-1",
            summary="Meeting",
            description="Team sync",
            start=GoogleCalendarEventDateTime(dateTime="2025-01-01T10:00:00Z"),
            end=GoogleCalendarEventDateTime(dateTime="2025-01-01T11:00:00Z"),
        )
        p = _patches(_Returns(calendar_msg="CALENDAR OUTPUT"))
        with (
            p["create_system"],
            p["build_dynamic"],
            p["format_calendar"] as mock_cal,
            p["format_tool"],
            p["format_files"],
        ):
            result = await comms_turn_messages(
                query="what about this",
                attachments=MessageAttachments(selected_calendar_event=cal_event),
            )

        mock_cal.assert_called_once_with(cal_event, "what about this")
        assert result[-2].content == "CALENDAR OUTPUT"

    @pytest.mark.asyncio
    async def test_tool_selection_when_no_workflow_or_calendar(self) -> None:
        p = _patches(_Returns(tool_msg="TOOL OUTPUT"))
        with (
            p["create_system"],
            p["build_dynamic"],
            p["format_tool"] as mock_tool,
            p["format_files"],
        ):
            result = await comms_turn_messages(
                query="use this tool",
                attachments=MessageAttachments(selected_tool="web_search"),
            )

        mock_tool.assert_called_once()
        assert result[-2].content == "TOOL OUTPUT"

    @pytest.mark.asyncio
    async def test_tool_category_passed(self) -> None:
        p = _patches(_Returns(tool_msg="TOOL OUTPUT"))
        with (
            p["create_system"],
            p["build_dynamic"],
            p["format_tool"] as mock_tool,
            p["format_files"],
        ):
            await comms_turn_messages(
                query="search",
                attachments=MessageAttachments(selected_tool="web_search", tool_category="search"),
            )

        args = mock_tool.call_args[0]
        assert args[0] == "web_search"
        assert args[2] == "search"

    @pytest.mark.asyncio
    async def test_user_content_fallback(self) -> None:
        p = _patches()
        with p["create_system"], p["build_dynamic"], p["format_files"]:
            result = await comms_turn_messages(
                query="plain text",
            )

        assert result[-2].content == "plain text"


class TestUserContentExtraction:
    """User content edge cases."""

    @pytest.mark.asyncio
    @pytest.mark.regression
    async def test_a_turn_with_no_history_still_reaches_the_model(self) -> None:
        """Regression: the maintenance sweep sends its prompt with no history, and every run raised."""
        p = _patches()
        with p["create_system"], p["build_dynamic"], p["format_files"]:
            result = await comms_turn_messages(query="Is this tracked todo still alive?")

        assert result[2] == HumanMessage(content="Is this tracked todo still alive?")

    @pytest.mark.asyncio
    async def test_an_empty_turn_raises(self) -> None:
        p = _patches()
        with p["create_system"], p["build_dynamic"], p["format_files"]:
            with pytest.raises(ValueError, match="No human message"):
                await comms_turn_messages(query="")

    @pytest.mark.asyncio
    async def test_whitespace_only_content_raises(self) -> None:
        p = _patches()
        with p["create_system"], p["build_dynamic"], p["format_files"]:
            with pytest.raises(ValueError, match="No human message"):
                await comms_turn_messages(
                    query="   ",
                )

    @pytest.mark.asyncio
    async def test_a_files_only_turn_becomes_a_message_listing_the_files(self) -> None:
        """A user may send files with no text; the turn is the files, not an error."""
        files = [FileData(fileId="f1", url="https://example.com/f1", filename="report.pdf")]
        p = _patches(
            _Returns(
                files_str="[Uploaded files]\n- report.pdf",
                server_files=tuple(files),
            )
        )
        with p["create_system"], p["build_dynamic"], p["get_uploads"], p["format_files"]:
            result = await comms_turn_messages(
                query="",
                scope=MessageScope(user_id="uid-1"),
                attachments=MessageAttachments(currently_uploaded_file_ids=["f1"]),
            )

        human = result[2]
        assert isinstance(human, HumanMessage)
        assert "[Uploaded files]" in human.content
        assert "report.pdf" in human.content

    @pytest.mark.asyncio
    async def test_files_the_turn_did_not_upload_do_not_stand_in_for_a_message(self) -> None:
        p = _patches()
        with p["create_system"], p["build_dynamic"]:
            with pytest.raises(ValueError, match="No human message"):
                await comms_turn_messages(
                    query="",
                    attachments=MessageAttachments(currently_uploaded_file_ids=[]),
                )


class TestReplyContext:
    @pytest.mark.asyncio
    async def test_reply_context_added(self) -> None:
        reply = ReplyToMessageData(id="msg-1", content="original msg", role="user")
        p = _patches(_Returns(reply_msg="[reply context]\n\nuser content"))
        with (
            p["create_system"],
            p["build_dynamic"],
            p["format_reply"] as mock_reply,
            p["format_files"],
        ):
            result = await comms_turn_messages(
                query="user content",
                attachments=MessageAttachments(reply_to_message=reply),
            )

        mock_reply.assert_called_once_with(reply, "user content")
        assert result[-2].content == "[reply context]\n\nuser content"

    @pytest.mark.asyncio
    async def test_no_reply_context_without_data(self) -> None:
        p = _patches()
        with (
            p["create_system"],
            p["build_dynamic"],
            p["format_reply"] as mock_reply,
            p["format_files"],
        ):
            await comms_turn_messages(
                query="hello",
            )

        mock_reply.assert_not_called()


class TestFileContext:
    @pytest.mark.asyncio
    async def test_files_appended_to_content(self) -> None:
        files = [
            FileData(fileId="f1", url="https://example.com/f1", filename="test.txt"),
        ]
        p = _patches(
            _Returns(
                files_str="Uploaded Files:\n- Name: test.txt Id: f1",
                server_files=tuple(files),
            )
        )
        with (
            p["create_system"],
            p["build_dynamic"],
            p["get_uploads"],
            p["format_files"] as mock_files,
        ):
            result = await comms_turn_messages(
                query="check this",
                scope=MessageScope(user_id="uid-1"),
                attachments=MessageAttachments(currently_uploaded_file_ids=["f1"]),
            )

        # Comms suppresses the processing guide — that lane can't act on files.
        mock_files.assert_called_once_with(files, ["f1"], None, include_processing_guide=False)
        assert result[-2].content == "check this\n\nUploaded Files:\n- Name: test.txt Id: f1"

    @pytest.mark.asyncio
    async def test_server_metadata_reaches_the_files_list_for_this_conversation(self) -> None:
        server_files = [
            FileData(
                fileId="f1",
                url="https://example.com/f1",
                filename="a.txt",
                description="a quarterly report",
                sandbox_path="/workspace/sessions/conv-1/user-uploaded/a.txt",
            ),
        ]
        p = _patches(_Returns(files_str="FILES", server_files=tuple(server_files)))
        with (
            p["create_system"],
            p["build_dynamic"],
            p["get_uploads"] as get_uploads,
            p["format_files"] as mock_files,
        ):
            await comms_turn_messages(
                query="check these",
                scope=MessageScope(user_id="uid-1", conversation_id="conv-1"),
                attachments=MessageAttachments(currently_uploaded_file_ids=["f1", "f2"]),
            )

        get_uploads.assert_awaited_once_with(["f1", "f2"], "uid-1", "conv-1")
        mock_files.assert_called_once_with(
            server_files, ["f1", "f2"], "conv-1", include_processing_guide=False
        )

    @pytest.mark.asyncio
    async def test_no_files_when_ids_empty(self) -> None:
        p = _patches()
        with (
            p["create_system"],
            p["build_dynamic"],
            p["format_files"] as mock_files,
        ):
            result = await comms_turn_messages(
                query="hello",
                attachments=MessageAttachments(currently_uploaded_file_ids=[]),
            )

        mock_files.assert_not_called()
        assert result[-2].content == "hello"

    @pytest.mark.asyncio
    async def test_files_empty_string_not_appended(self) -> None:
        p = _patches(_Returns(files_str=""))
        with (
            p["create_system"],
            p["build_dynamic"],
            p["format_files"],
        ):
            result = await comms_turn_messages(
                query="hello",
                attachments=MessageAttachments(currently_uploaded_file_ids=["f1"]),
            )

        assert result[-2].content == "hello"

    @pytest.mark.asyncio
    async def test_no_files_when_ids_none(self) -> None:
        p = _patches()
        with (
            p["create_system"],
            p["build_dynamic"],
            p["format_files"] as mock_files,
        ):
            await comms_turn_messages(
                query="hello",
                attachments=MessageAttachments(currently_uploaded_file_ids=None),
            )

        mock_files.assert_not_called()


class TestTriggerContext:
    @pytest.mark.asyncio
    async def test_trigger_context_passed_to_workflow(self) -> None:
        workflow = SelectedWorkflowData(
            id="wf-1",
            title="Email WF",
            description="desc",
            steps=[WorkflowStep(title="s1", category="c1", description="d1")],
        )
        trigger = {"type": "gmail", "email_data": {"sender": "a@b.com"}}
        p = _patches()
        with (
            p["create_system"],
            p["build_dynamic"],
            p["format_workflow"] as mock_wf,
            p["format_files"],
        ):
            await comms_turn_messages(
                query="run",
                scope=MessageScope(user_id="uid"),
                attachments=MessageAttachments(selected_workflow=workflow, trigger_context=trigger),
            )

        call_args = mock_wf.call_args
        assert call_args[0][2] == trigger


class TestTheCommsContextKnowsWhereTheTurnIs:
    """The new-user guidance reads the seeded thread and the mail facts off these two fields."""

    @pytest.mark.asyncio
    async def test_the_conversation_and_the_onboarding_record_reach_the_sections(self) -> None:
        onboarding = OnboardingSubdocument(completed=True, user_bio="Runs ops at a bakery.")
        p = _patches()
        with p["create_system"], p["build_dynamic"] as assemble, p["format_files"]:
            await comms_turn_messages(
                query="hi",
                scope=MessageScope(
                    user_id="uid-1",
                    conversation_id="conv-1",
                    user_dict=AuthenticatedUser(user_id="uid-1", onboarding=onboarding),
                ),
            )

        ctx = assemble.await_args.args[0]
        assert (ctx.conversation_id, ctx.onboarding) == ("conv-1", onboarding)

    @pytest.mark.asyncio
    async def test_a_turn_with_neither_a_message_nor_a_tool_is_refused(self) -> None:
        """Silently sending an empty turn to the model would burn a call and return nothing useful."""
        p = _patches()
        with p["create_system"], p["build_dynamic"], p["format_files"]:
            with pytest.raises(
                ValueError, match=r"^No human message, selected tool or uploaded file$"
            ):
                await comms_turn_messages(
                    query="",
                    scope=MessageScope(user_id="uid-1"),
                )


class TestTheClockIsRenderedInTheUsersTimezone:
    @pytest.mark.asyncio
    async def test_the_users_zone_reaches_the_clock(self) -> None:
        """A clock in the wrong zone makes "this afternoon" resolve to the wrong day for anyone outside UTC."""
        p = _patches()
        with (
            p["create_system"],
            p["build_dynamic"],
            p["format_files"],
            patch(
                "app.agents.core.messages.build_current_time_message",
                return_value=HumanMessage(content="now", additional_kwargs={"time_context": True}),
            ) as clock,
        ):
            await comms_turn_messages(
                query="hi",
                scope=MessageScope(
                    user_dict=AuthenticatedUser(user_id="", timezone="Asia/Kolkata")
                ),
            )

        clock.assert_called_once_with(user_timezone="Asia/Kolkata")


class TestOpenuiVariantReachesTheModel:
    """The static per-channel prompt selection runs for real here (the real create_system_message is not patched), so the test proves the variant that reaches the model, not just that a selector was called."""

    @pytest.mark.asyncio
    async def test_web_serves_the_openui_variant(self) -> None:
        p = _patches()
        with p["build_dynamic"], p["format_files"]:
            result = await comms_turn_messages(
                query="hi",
                scope=MessageScope(user_id="uid-1", source="web"),
            )

        assert "## Output Format (this app renders rich components)" in result[0].content

    @pytest.mark.asyncio
    async def test_text_channel_serves_the_platform_variant(self) -> None:
        p = _patches()
        with p["build_dynamic"], p["format_files"]:
            result = await comms_turn_messages(
                query="hi",
                scope=MessageScope(user_id="uid-1", source="whatsapp"),
            )

        assert "Platform Context" in result[0].content
        assert "## Output Format (this app renders rich components)" not in result[0].content
