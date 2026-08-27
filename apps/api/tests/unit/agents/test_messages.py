"""Unit tests for app.agents.core.messages — construct_langchain_messages.

After the caching optimisation work, the message-construction contract is:

    [static_main_prompt, dynamic_stable, memory_recall?, human_task, time_msg]

The static main prompt is byte-identical across users/channels. Per-user
identity (name, timezone, preferences, integrations) lives in the stable
dynamic-context message; volatile per-turn content (memory recall, knowledge,
skills, todos) lives in an optional memory-recall message. Both are built by
the shared context-assembly module. The current-time HumanMessage is appended
LAST so minute ticks never shift the cacheable prefix. These tests exercise the
orchestration — they patch ``create_system_message`` and ``assemble_context``
and verify the assembled message list.
"""

from typing import Any
from unittest.mock import AsyncMock, patch

from langchain_core.messages import HumanMessage, SystemMessage
import pytest

from app.agents.context.assemble import AssembledContext
from app.agents.context.slots import ONBOARDING_MARKER
from app.agents.context.tiers import AgentTier
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
    memory_recall_msg: SystemMessage | None = None,
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
            "app.agents.core.messages.assemble_context",
            new_callable=AsyncMock,
            return_value=AssembledContext(stable=dynamic_msg, volatile=memory_recall_msg),
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


class TestConstructLangchainMessages:
    """Exercise the [static, dynamic, human] assembly."""

    @pytest.mark.asyncio
    async def test_basic_user_message(self) -> None:
        """Shape is [static, dynamic_stable, human_task, time_msg].

        The time HumanMessage is split off from the task AND appended last so
        minute ticks never shift the cacheable prefix. With no volatile content
        the memory-recall message is omitted.
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
        # Third is the actual user task.
        assert isinstance(result[2], HumanMessage)
        assert result[2].content == "Hi there"
        # Fourth (last) is the current-time HumanMessage.
        assert isinstance(result[3], HumanMessage)
        assert result[3].additional_kwargs.get("time_context") is True

    @pytest.mark.asyncio
    async def test_memory_recall_message_slotted_when_present(self) -> None:
        """When build returns a memory-recall message it sits after the stable
        dynamic message and before the human task; time stays last.

        Shape: [static, dynamic_stable, memory_recall, human_task, time_msg].
        """
        recall = SystemMessage(
            content="Recalled memories", additional_kwargs={"memory_recall": True}
        )
        p = _patches(memory_recall_msg=recall)
        with p["create_system"], p["build_dynamic"], p["format_files"]:
            result = await construct_langchain_messages(
                messages=[{"role": "user", "content": "Hi there"}],
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

        ctx = mock_dyn.call_args.args[0]
        assert ctx.tier is AgentTier.COMMS
        assert ctx.user_id == "uid-1"
        assert ctx.user_name == "Alice"
        assert ctx.user_timezone == "Asia/Kolkata"
        assert ctx.user_preferences == {"tone": "formal"}
        assert ctx.query == "hi"
        assert ctx.source == "whatsapp"

    @pytest.mark.asyncio
    async def test_every_field_the_context_is_built_from_survives_the_trip(self) -> None:
        """This function's whole job is turning the auth payload into the shape
        assembly reads. Every field dropped here is a section that silently
        renders nothing — the user's writing style stops being honoured, or a
        background run believes a human is waiting — with no error anywhere.
        """
        p = _patches()
        user_dict = {
            "timezone": "Asia/Kolkata",
            "onboarding": {
                "preferences": {"tone": "formal"},
                "writing_style": {"case": "lower"},
            },
        }
        with p["create_system"], p["build_dynamic"] as mock_dyn, p["format_files"]:
            await construct_langchain_messages(
                messages=[{"role": "user", "content": "hi"}],
                user_id="uid-1",
                user_name="Alice",
                user_dict=user_dict,
                query="hi",
                active_todo_id="todo-7",
                execution_mode="background",
                source="slack",
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
            await construct_langchain_messages(
                messages=[{"role": "user", "content": "hi"}], user_id="uid-1", user_dict={}
            )

        ctx = mock_dyn.call_args.args[0]
        assert ctx.user_timezone is None
        assert ctx.user_preferences is None
        assert ctx.writing_style is None

    @pytest.mark.asyncio
    async def test_an_unauthenticated_turn_carries_no_user_fields(self) -> None:
        p = _patches()
        with p["create_system"], p["build_dynamic"] as mock_dyn, p["format_files"]:
            await construct_langchain_messages(
                messages=[{"role": "user", "content": "hi"}], user_dict=None
            )

        ctx = mock_dyn.call_args.args[0]
        assert ctx.user_timezone is None
        assert ctx.user_preferences is None
        assert ctx.writing_style is None

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
        # result[-1] is the current-time message; the task is second-to-last.
        assert result[-2].content == "WORKFLOW OUTPUT"

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
        assert result[-2].content == "CALENDAR OUTPUT"

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
        assert result[-2].content == "TOOL OUTPUT"

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

        assert result[-2].content == "plain text"


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
            await construct_langchain_messages(
                messages=[{"role": "user", "content": "hello"}],
            )

        mock_reply.assert_not_called()


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

        # Comms suppresses the processing guide — that lane can't act on files.
        mock_files.assert_called_once_with(files_data, ["f1"], None, include_processing_guide=False)
        assert "Uploaded Files" in result[-2].content
        assert result[-2].content.startswith("check this")

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
        assert result[-2].content == "hello"

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

        assert result[-2].content == "hello"

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


class TestTheOnboardingProbeSeesTheUsersActualMessage:
    """Whether a turn is an onboarding turn is decided partly by what the user
    just said, so the probe has to receive the user's LATEST message — not the
    first, not the assistant's reply, and not with the whitespace a chat client
    leaves on it. Getting this wrong misclassifies the turn, and onboarding is
    exactly when the agent knows least about the user.
    """

    @staticmethod
    def _probe() -> Any:
        return patch(
            "app.agents.core.messages.get_onboarding_system_prompt_if_applicable",
            new_callable=AsyncMock,
            return_value=None,
        )

    @pytest.mark.asyncio
    async def test_it_receives_the_latest_user_message_trimmed(self) -> None:
        p = _patches()
        with p["create_system"], p["build_dynamic"], p["format_files"], self._probe() as probe:
            await construct_langchain_messages(
                messages=[
                    {"role": "user", "content": "an earlier question"},
                    {"role": "assistant", "content": "an earlier answer"},
                    {"role": "user", "content": "  what can you do?  "},
                ],
                user_id="uid-1",
                conversation_id="conv-1",
            )

        probe.assert_awaited_once_with("uid-1", "conv-1", latest_user_message="what can you do?")

    @pytest.mark.asyncio
    async def test_a_thread_ending_on_the_assistant_carries_no_user_message(self) -> None:
        """A trailing assistant turn means the user has not spoken on this call;
        passing its text would have the probe classify on GAIA's own words.

        Reachable only alongside a selected tool — with neither a user message
        nor a tool the function refuses the turn outright.
        """
        p = _patches()
        with (
            p["create_system"],
            p["build_dynamic"],
            p["format_files"],
            p["format_tool"],
            self._probe() as probe,
        ):
            await construct_langchain_messages(
                messages=[
                    {"role": "user", "content": "hello"},
                    {"role": "assistant", "content": "hi there"},
                ],
                user_id="uid-1",
                conversation_id="conv-1",
                selected_tool="gmail",
            )

        probe.assert_awaited_once_with("uid-1", "conv-1", latest_user_message="")

    @pytest.mark.asyncio
    async def test_an_empty_thread_carries_no_user_message(self) -> None:
        p = _patches()
        with (
            p["create_system"],
            p["build_dynamic"],
            p["format_files"],
            p["format_tool"],
            self._probe() as probe,
        ):
            await construct_langchain_messages(
                messages=[], user_id="uid-1", conversation_id="conv-1", selected_tool="gmail"
            )

        probe.assert_awaited_once_with("uid-1", "conv-1", latest_user_message="")

    @pytest.mark.asyncio
    async def test_a_turn_with_neither_a_message_nor_a_tool_is_refused(self) -> None:
        """The refusal is what makes the two cases above reachable only with a
        tool — worth pinning, since silently sending an empty turn to the model
        would burn a call and return nothing useful."""
        p = _patches()
        with p["create_system"], p["build_dynamic"], p["format_files"]:
            with pytest.raises(ValueError, match="No human message or selected tool"):
                await construct_langchain_messages(messages=[], user_id="uid-1")

    @pytest.mark.asyncio
    async def test_a_turn_outside_a_conversation_is_never_probed(self) -> None:
        """Without a conversation there is no onboarding state to read, so the
        Mongo probe would be a query on nothing."""
        p = _patches()
        with p["create_system"], p["build_dynamic"], p["format_files"], self._probe() as probe:
            await construct_langchain_messages(
                messages=[{"role": "user", "content": "hi"}], user_id="uid-1"
            )

        probe.assert_not_awaited()


class TestAnOnboardingTurnKeepsBothItsPromptAndTheUsersIdentity:
    """The onboarding prompt used to be stamped ``memory_message`` — the stable
    block's OWN marker — and emitted after it, so the single-occupant slot kept
    the prompt and dropped the identity block. Every onboarding turn reached the
    model with no user name, timezone, preferences or integrations manifest,
    which is precisely the turn where knowing the user matters most.

    It has its own slot now. Both halves are pinned here: the prompt arrives,
    and it arrives *beside* identity rather than instead of it.
    """

    PROMPT = "Welcome! Ask about their inbox."

    def _probe(self) -> Any:
        return patch(
            "app.agents.core.messages.get_onboarding_system_prompt_if_applicable",
            new_callable=AsyncMock,
            return_value=self.PROMPT,
        )

    async def _run(self) -> list[Any]:
        p = _patches()
        with p["create_system"], p["build_dynamic"], p["format_files"], self._probe():
            return await construct_langchain_messages(
                messages=[{"role": "user", "content": "hi"}],
                user_id="uid-1",
                conversation_id="conv-1",
            )

    @pytest.mark.asyncio
    async def test_the_prompt_reaches_the_model_verbatim(self) -> None:
        onboarding = [
            m for m in await self._run() if m.additional_kwargs.get(ONBOARDING_MARKER) is True
        ]

        assert len(onboarding) == 1
        assert onboarding[0].content == self.PROMPT

    @pytest.mark.asyncio
    async def test_the_identity_block_is_still_there(self) -> None:
        assert DYNAMIC_MSG in await self._run()

    @pytest.mark.asyncio
    async def test_the_prompt_does_not_claim_the_stable_blocks_slot(self) -> None:
        """Carrying ``memory_message`` is what made it evict identity; the
        pruning node keeps only the latest holder of that marker."""
        (onboarding,) = [
            m for m in await self._run() if m.additional_kwargs.get(ONBOARDING_MARKER) is True
        ]

        assert onboarding.additional_kwargs.get("memory_message") is not True
        assert onboarding.additional_kwargs.get("dynamic_context") is not True

    @pytest.mark.asyncio
    async def test_it_follows_the_stable_block_rather_than_replacing_it(self) -> None:
        result = await self._run()
        onboarding = next(m for m in result if m.additional_kwargs.get(ONBOARDING_MARKER) is True)

        assert result.index(onboarding) > result.index(DYNAMIC_MSG)

    @pytest.mark.asyncio
    async def test_an_ordinary_turn_carries_no_onboarding_message(self) -> None:
        p = _patches()
        with (
            p["create_system"],
            p["build_dynamic"],
            p["format_files"],
            patch(
                "app.agents.core.messages.get_onboarding_system_prompt_if_applicable",
                new_callable=AsyncMock,
                return_value=None,
            ),
        ):
            result = await construct_langchain_messages(
                messages=[{"role": "user", "content": "hi"}],
                user_id="uid-1",
                conversation_id="conv-1",
            )

        assert not [m for m in result if m.additional_kwargs.get(ONBOARDING_MARKER)]


class TestTheClockIsRenderedInTheUsersTimezone:
    @pytest.mark.asyncio
    async def test_the_users_zone_reaches_the_clock(self) -> None:
        """A clock built in the wrong zone makes "this afternoon" and "tomorrow"
        resolve to the wrong day for anyone outside UTC."""
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
            await construct_langchain_messages(
                messages=[{"role": "user", "content": "hi"}],
                user_dict={"timezone": "Asia/Kolkata"},
            )

        clock.assert_called_once_with(user_timezone="Asia/Kolkata")
