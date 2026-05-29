"""Behavior spec for app.agents.core.messages :: construct_langchain_messages.

UNIT: app/agents/core/messages.py :: construct_langchain_messages
EXPECTED:
    Assemble the LangChain message list for one agent turn. The shape is
    ``[static_system, dynamic_context_system, current_time_human, (onboarding_system?), human_task]``.
    The static prompt is byte-identical across users on a channel (cache-friendly);
    everything per-user/per-turn lives in the dynamic-context SystemMessage; the
    clock lives in its own HumanMessage; the user's task is the final HumanMessage.
MECHANISM:
    system_msg = create_system_message(user_id, user_name, agent_type, source)
    user_timezone/user_preferences/writing_style are pulled out of user_dict["onboarding"]
    dynamic_msg = await build_dynamic_context_message(user_id, query, user_name,
        user_timezone, user_preferences, writing_style, source, active_todo_id, execution_mode)
    time_msg = build_current_time_message(user_timezone)   # NOT mocked — real
    chain = [system_msg, dynamic_msg, time_msg]
    user_content = last message's content (stripped) iff messages and last role == "user", else ""
    if user_id and conversation_id: maybe append SystemMessage(onboarding, memory_message=True)
    content = workflow > calendar > tool > user_content   (first truthy selector wins)
    if not content: raise ValueError("No human message or selected tool")
    if reply_to_message: content = format_reply_context(reply, content)
    if currently_uploaded_file_ids and files_str: content += "\n\n" + files_str
    return [*chain, HumanMessage(content)]
MUST-CATCH (each maps to >=1 test + >=1 killed mutant):
  - assembled order is exactly [static, dynamic, time, human] with the right types/markers
  - create_system_message receives agent_type defaulting to "comms" (L39 default)   [cache contract]
  - create_system_message receives the explicit agent_type / source forwarded through
  - build_dynamic_context_message receives user_id, user_name, timezone, preferences,
    query, source AND writing_style pulled from onboarding (L81)
  - user_content extraction requires BOTH a non-empty list AND last role == "user" (L104 And)
    -> assistant-last and empty-list and whitespace-only all raise ValueError
  - content priority: workflow beats calendar beats tool beats raw user message
  - selected_tool forwards (selected_tool, content, tool_category) positionally
  - empty resolved content raises ValueError("No human message or selected tool")
  - onboarding branch fires only when user_id AND conversation_id are both set (L110 And);
    the appended onboarding SystemMessage carries memory_message=True (L115)
  - reply_to_message wraps the content via format_reply_context(reply, content)
  - file context appends exactly "\n\n" + files_str, only when ids non-empty and files_str truthy (L141)
EQUIVALENT MUTANTS (allowed survivors, justified):
  - L39 str->'' on the two ``Literal["comms", "executor"]`` annotation strings: pure
    typing annotation, never evaluated at runtime — no behavior change, unkillable.
  - L43 str->'' on the function docstring: ``__doc__`` is read by no code path.
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
    onboarding_prompt: str | None = None,
) -> dict[str, Any]:
    """Bundle context-manager patches for the I/O-boundary helpers.

    ``create_system_message`` reads prompt-template modules, the rest hit
    Mongo / Redis / ChromaDB / the memory service — all real I/O boundaries.
    ``build_current_time_message`` is intentionally NOT patched: it is a pure
    clock formatter and the assembly contract for slot [2] is asserted against
    its real output.
    """
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
        "onboarding": patch(
            "app.agents.core.messages.get_onboarding_system_prompt_if_applicable",
            new_callable=AsyncMock,
            return_value=onboarding_prompt,
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
class TestAssemblyAndDelegation:
    """The [static, dynamic, time, human] assembly and the kwargs forwarded to helpers."""

    @pytest.mark.asyncio
    async def test_message_order_types_and_markers(self) -> None:
        """Shape is exactly [static, dynamic_context, time_msg, human_task].

        The time HumanMessage is split off from the task so minute ticks don't
        invalidate the ``system_instruction`` prefix; slot [2] is the real
        ``build_current_time_message`` output, marked ``time_context=True``.
        """
        p = _patches()
        with p["create_system"], p["build_dynamic"], p["onboarding"], p["format_files"]:
            result = await construct_langchain_messages(
                messages=[{"role": "user", "content": "Hi there"}],
            )

        assert len(result) == 4
        assert result[0] is SYSTEM_MSG
        assert result[1] is DYNAMIC_MSG
        assert result[1].additional_kwargs.get("dynamic_context") is True
        assert isinstance(result[2], HumanMessage)
        assert result[2].additional_kwargs.get("time_context") is True
        assert isinstance(result[3], HumanMessage)
        assert result[3].content == "Hi there"

    @pytest.mark.asyncio
    async def test_agent_type_defaults_to_comms(self) -> None:
        """With no explicit agent_type, create_system_message must get "comms".

        This default selects the user-facing comms prompt; mutating it would
        silently route every default turn to the wrong static prompt.
        """
        p = _patches()
        with p["create_system"] as mock_sys, p["build_dynamic"], p["onboarding"], p["format_files"]:
            await construct_langchain_messages(
                messages=[{"role": "user", "content": "Hello"}],
            )
        assert mock_sys.call_args.kwargs["agent_type"] == "comms"

    @pytest.mark.asyncio
    async def test_explicit_agent_type_and_source_forwarded(self) -> None:
        """Explicit agent_type/source pass through to the static prompt selector."""
        p = _patches()
        with p["create_system"] as mock_sys, p["build_dynamic"], p["onboarding"], p["format_files"]:
            await construct_langchain_messages(
                messages=[{"role": "user", "content": "Hello"}],
                agent_type="executor",
                source="web",
            )
        kwargs = mock_sys.call_args.kwargs
        assert kwargs["agent_type"] == "executor"
        assert kwargs["source"] == "web"

    @pytest.mark.asyncio
    async def test_dynamic_message_receives_user_context(self) -> None:
        """user_dict["onboarding"] is decomposed into timezone, preferences,
        writing_style and forwarded with user_id/name/query/source."""
        p = _patches()
        user_dict = {
            "timezone": "Asia/Kolkata",
            "onboarding": {
                "preferences": {"tone": "formal"},
                "writing_style": {"voice": "concise"},
            },
        }
        with p["create_system"], p["build_dynamic"] as mock_dyn, p["onboarding"], p["format_files"]:
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
        assert kwargs["writing_style"] == {"voice": "concise"}
        assert kwargs["query"] == "hi"
        assert kwargs["source"] == "whatsapp"

    @pytest.mark.asyncio
    async def test_missing_user_dict_yields_none_context(self) -> None:
        """No user_dict -> timezone/preferences/writing_style are all None."""
        p = _patches()
        with p["create_system"], p["build_dynamic"] as mock_dyn, p["onboarding"], p["format_files"]:
            await construct_langchain_messages(
                messages=[{"role": "user", "content": "hi"}],
            )
        kwargs = mock_dyn.call_args.kwargs
        assert kwargs["user_timezone"] is None
        assert kwargs["user_preferences"] is None
        assert kwargs["writing_style"] is None


@pytest.mark.unit
class TestContentPriority:
    """Workflow > calendar > tool selection > raw user message."""

    @pytest.mark.asyncio
    async def test_workflow_beats_calendar_tool_and_user(self) -> None:
        """When a workflow is selected it wins over calendar/tool/raw content."""
        workflow = SelectedWorkflowData(
            id="wf-1",
            title="Test WF",
            description="desc",
            steps=[{"title": "s1", "category": "c1", "description": "d1"}],
        )
        cal = SelectedCalendarEventData(
            id="e-1",
            summary="Meeting",
            description="sync",
            start={"dateTime": "2025-01-01T10:00:00Z"},
            end={"dateTime": "2025-01-01T11:00:00Z"},
        )
        p = _patches(workflow_msg="WORKFLOW OUTPUT")
        with (
            p["create_system"],
            p["build_dynamic"],
            p["onboarding"],
            p["format_workflow"] as mock_wf,
            p["format_calendar"] as mock_cal,
            p["format_tool"] as mock_tool,
            p["format_files"],
        ):
            result = await construct_langchain_messages(
                messages=[{"role": "user", "content": "run it"}],
                selected_workflow=workflow,
                selected_calendar_event=cal,
                selected_tool="web_search",
                user_id="uid",
            )

        mock_wf.assert_awaited_once()
        # Lower-priority selectors must NOT be consulted when workflow wins.
        mock_cal.assert_not_called()
        mock_tool.assert_not_called()
        assert result[-1].content == "WORKFLOW OUTPUT"

    @pytest.mark.asyncio
    async def test_calendar_beats_tool_and_user(self) -> None:
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
            p["onboarding"],
            p["format_calendar"] as mock_cal,
            p["format_tool"] as mock_tool,
            p["format_files"],
        ):
            result = await construct_langchain_messages(
                messages=[{"role": "user", "content": "what about this"}],
                selected_calendar_event=cal_event,
                selected_tool="web_search",
            )

        mock_cal.assert_called_once()
        mock_tool.assert_not_called()
        assert result[-1].content == "CALENDAR OUTPUT"

    @pytest.mark.asyncio
    async def test_tool_selection_beats_user_and_forwards_positionally(self) -> None:
        """Tool selection wins over raw content; args are (tool, content, category)."""
        p = _patches(tool_msg="TOOL OUTPUT")
        with (
            p["create_system"],
            p["build_dynamic"],
            p["onboarding"],
            p["format_tool"] as mock_tool,
            p["format_files"],
        ):
            result = await construct_langchain_messages(
                messages=[{"role": "user", "content": "use this tool"}],
                selected_tool="web_search",
                tool_category="search",
            )

        args = mock_tool.call_args[0]
        assert args[0] == "web_search"
        assert args[1] == "use this tool"
        assert args[2] == "search"
        assert result[-1].content == "TOOL OUTPUT"

    @pytest.mark.asyncio
    async def test_raw_user_content_when_no_selector(self) -> None:
        p = _patches()
        with p["create_system"], p["build_dynamic"], p["onboarding"], p["format_files"]:
            result = await construct_langchain_messages(
                messages=[{"role": "user", "content": "plain text"}],
            )

        assert result[-1].content == "plain text"

    @pytest.mark.asyncio
    async def test_trigger_context_forwarded_to_workflow(self) -> None:
        """trigger_context is the 3rd positional arg to format_workflow_execution_message."""
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
            p["onboarding"],
            p["format_workflow"] as mock_wf,
            p["format_files"],
        ):
            await construct_langchain_messages(
                messages=[{"role": "user", "content": "run"}],
                selected_workflow=workflow,
                trigger_context=trigger,
                user_id="uid",
            )

        assert mock_wf.call_args[0][2] == trigger


@pytest.mark.unit
class TestUserContentExtraction:
    """user_content needs BOTH a non-empty list AND a user-role last message."""

    @pytest.mark.asyncio
    async def test_assistant_last_message_raises(self) -> None:
        p = _patches()
        with p["create_system"], p["build_dynamic"], p["onboarding"], p["format_files"]:
            with pytest.raises(ValueError, match="No human message or selected tool"):
                await construct_langchain_messages(
                    messages=[{"role": "assistant", "content": "Hi"}],
                )

    @pytest.mark.asyncio
    async def test_empty_messages_list_raises(self) -> None:
        p = _patches()
        with p["create_system"], p["build_dynamic"], p["onboarding"], p["format_files"]:
            with pytest.raises(ValueError, match="No human message or selected tool"):
                await construct_langchain_messages(messages=[])

    @pytest.mark.asyncio
    async def test_whitespace_only_content_raises(self) -> None:
        """Whitespace is stripped to "" -> empty content -> ValueError."""
        p = _patches()
        with p["create_system"], p["build_dynamic"], p["onboarding"], p["format_files"]:
            with pytest.raises(ValueError, match="No human message or selected tool"):
                await construct_langchain_messages(
                    messages=[{"role": "user", "content": "   "}],
                )

    @pytest.mark.asyncio
    async def test_content_is_stripped(self) -> None:
        """Leading/trailing whitespace is trimmed off the surviving content."""
        p = _patches()
        with p["create_system"], p["build_dynamic"], p["onboarding"], p["format_files"]:
            result = await construct_langchain_messages(
                messages=[{"role": "user", "content": "  hello world  "}],
            )
        assert result[-1].content == "hello world"


@pytest.mark.unit
class TestOnboardingPrompt:
    """The onboarding SystemMessage is appended only when user_id AND conversation_id are set."""

    @pytest.mark.asyncio
    async def test_onboarding_appended_with_memory_marker(self) -> None:
        """Both ids set + a returned prompt -> a memory_message SystemMessage is
        inserted before the human task."""
        p = _patches(onboarding_prompt="ONBOARDING SYSTEM PROMPT")
        with p["create_system"], p["build_dynamic"], p["onboarding"] as mock_ob, p["format_files"]:
            result = await construct_langchain_messages(
                messages=[{"role": "user", "content": "hi"}],
                user_id="uid-1",
                conversation_id="conv-1",
            )

        mock_ob.assert_awaited_once_with("uid-1", "conv-1", latest_user_message="hi")
        # [static, dynamic, time, onboarding, human]
        assert len(result) == 5
        onboarding_msg = result[3]
        assert isinstance(onboarding_msg, SystemMessage)
        assert onboarding_msg.content == "ONBOARDING SYSTEM PROMPT"
        # ``memory_message=True`` is passed as a top-level kwarg, landing as a
        # model-extra attribute (not in additional_kwargs). manage_system_prompts_node
        # reads it to preserve this prompt alongside the main comms prompt.
        assert getattr(onboarding_msg, "memory_message") is True  # noqa: B009
        assert result[-1].content == "hi"

    @pytest.mark.asyncio
    async def test_no_onboarding_message_when_prompt_is_none(self) -> None:
        """Both ids set but the helper returns None -> nothing appended."""
        p = _patches(onboarding_prompt=None)
        with p["create_system"], p["build_dynamic"], p["onboarding"] as mock_ob, p["format_files"]:
            result = await construct_langchain_messages(
                messages=[{"role": "user", "content": "hi"}],
                user_id="uid-1",
                conversation_id="conv-1",
            )

        mock_ob.assert_awaited_once()
        assert len(result) == 4
        assert all(m.content != "ONBOARDING SYSTEM PROMPT" for m in result)

    @pytest.mark.asyncio
    async def test_onboarding_skipped_without_conversation_id(self) -> None:
        """user_id set but conversation_id None -> the onboarding helper is never
        consulted (guards the Mongo lookup)."""
        p = _patches(onboarding_prompt="SHOULD NOT APPEAR")
        with p["create_system"], p["build_dynamic"], p["onboarding"] as mock_ob, p["format_files"]:
            result = await construct_langchain_messages(
                messages=[{"role": "user", "content": "hi"}],
                user_id="uid-1",
            )

        mock_ob.assert_not_called()
        assert len(result) == 4

    @pytest.mark.asyncio
    async def test_onboarding_skipped_without_user_id(self) -> None:
        """conversation_id set but user_id None -> helper never consulted."""
        p = _patches(onboarding_prompt="SHOULD NOT APPEAR")
        with p["create_system"], p["build_dynamic"], p["onboarding"] as mock_ob, p["format_files"]:
            result = await construct_langchain_messages(
                messages=[{"role": "user", "content": "hi"}],
                conversation_id="conv-1",
            )

        mock_ob.assert_not_called()
        assert len(result) == 4


@pytest.mark.unit
class TestReplyContext:
    @pytest.mark.asyncio
    async def test_reply_context_wraps_content(self) -> None:
        reply = ReplyToMessageData(id="msg-1", content="original msg", role="user")
        p = _patches(reply_msg="[reply context]\n\nuser content")
        with (
            p["create_system"],
            p["build_dynamic"],
            p["onboarding"],
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
    async def test_no_reply_wrapping_without_reply_data(self) -> None:
        p = _patches()
        with (
            p["create_system"],
            p["build_dynamic"],
            p["onboarding"],
            p["format_reply"] as mock_reply,
            p["format_files"],
        ):
            result = await construct_langchain_messages(
                messages=[{"role": "user", "content": "hello"}],
            )

        mock_reply.assert_not_called()
        assert result[-1].content == "hello"


@pytest.mark.unit
class TestFileContext:
    @pytest.mark.asyncio
    async def test_files_appended_with_double_newline_separator(self) -> None:
        """File context is appended as exactly content + "\\n\\n" + files_str."""
        files_data = [
            FileData(fileId="f1", url="https://example.com/f1", filename="test.txt"),
        ]
        p = _patches(files_str="Uploaded Files:\n- Name: test.txt Id: f1")
        with (
            p["create_system"],
            p["build_dynamic"],
            p["onboarding"],
            p["format_files"] as mock_files,
        ):
            result = await construct_langchain_messages(
                messages=[{"role": "user", "content": "check this"}],
                files_data=files_data,
                currently_uploaded_file_ids=["f1"],
            )

        mock_files.assert_called_once_with(files_data, ["f1"])
        assert result[-1].content == "check this\n\nUploaded Files:\n- Name: test.txt Id: f1"

    @pytest.mark.asyncio
    async def test_no_file_lookup_when_ids_empty(self) -> None:
        p = _patches()
        with (
            p["create_system"],
            p["build_dynamic"],
            p["onboarding"],
            p["format_files"] as mock_files,
        ):
            result = await construct_langchain_messages(
                messages=[{"role": "user", "content": "hello"}],
                currently_uploaded_file_ids=[],
            )

        mock_files.assert_not_called()
        assert result[-1].content == "hello"

    @pytest.mark.asyncio
    async def test_no_file_lookup_when_ids_none(self) -> None:
        p = _patches()
        with (
            p["create_system"],
            p["build_dynamic"],
            p["onboarding"],
            p["format_files"] as mock_files,
        ):
            result = await construct_langchain_messages(
                messages=[{"role": "user", "content": "hello"}],
                currently_uploaded_file_ids=None,
            )

        mock_files.assert_not_called()
        assert result[-1].content == "hello"

    @pytest.mark.asyncio
    async def test_empty_files_str_not_appended(self) -> None:
        """ids present but format_files_list returns "" -> content unchanged."""
        p = _patches(files_str="")
        with (
            p["create_system"],
            p["build_dynamic"],
            p["onboarding"],
            p["format_files"],
        ):
            result = await construct_langchain_messages(
                messages=[{"role": "user", "content": "hello"}],
                currently_uploaded_file_ids=["f1"],
            )

        assert result[-1].content == "hello"
