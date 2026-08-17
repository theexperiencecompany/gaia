"""Tests for app/helpers/message_helpers.py"""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from langchain_core.messages import SystemMessage
import pytest

from app.helpers.message_helpers import (
    create_system_message,
    format_calendar_event_context,
    format_files_list,
    format_reply_context,
    format_tool_selection_message,
    format_workflow_execution_message,
    get_onboarding_system_prompt_if_applicable,
)
from app.models.message_models import (
    FileData,
    ReplyToMessageData,
    SelectedCalendarEventData,
    SelectedWorkflowData,
)
from app.models.user_models import OnboardingPhase, UserDocument

# ---------------------------------------------------------------------------
# create_system_message
# ---------------------------------------------------------------------------


class TestCreateSystemMessage:
    """The main system prompt must be byte-identical across users/channels so
    implicit LLM caching hits. No `{user_name}` interpolation lives here —
    per-user context is assembled separately by ``app.agents.context``."""

    def test_comms_agent_static_is_per_channel(self) -> None:
        """Different user_name must produce identical content on the same
        channel (byte-stable prefix). Different channels produce different
        content (OpenUI on web, platform restrictions on WhatsApp)."""
        web_a = create_system_message(user_name="Foo", agent_type="comms", source="web")
        web_b = create_system_message(user_name="Bar", agent_type="comms", source="web")
        whatsapp = create_system_message(user_name="Foo", agent_type="comms", source="whatsapp")
        assert isinstance(web_a, SystemMessage)
        assert web_a.content == web_b.content
        assert web_a.content != whatsapp.content
        # Output-format addenda should be inline in the static per-channel
        # prompt — web has OpenUI, text-only has platform restrictions.
        assert ":::openui" in web_a.content
        assert "Platform Context" in whatsapp.content

    def test_executor_agent_is_static(self) -> None:
        msg_a = create_system_message(user_name="Bob", agent_type="executor")
        msg_b = create_system_message(user_name="Dana", agent_type="executor")
        assert isinstance(msg_a, SystemMessage)
        assert msg_a.content == msg_b.content
        assert len(msg_a.content) > 0

    def test_default_name_not_injected(self) -> None:
        msg = create_system_message()
        # "there" used to be injected as user_name fallback; no longer.
        assert "{user_name}" not in msg.content

    def test_unknown_agent_type_defaults_to_comms(self) -> None:
        msg = create_system_message(user_name="X", agent_type="unknown")  # type: ignore[arg-type]
        comms = create_system_message(agent_type="comms")
        assert isinstance(msg, SystemMessage)
        assert msg.content == comms.content


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

    @pytest.mark.asyncio
    async def test_tracked_todos_context_reaches_signal_matching_template(self) -> None:
        """The tracked_todos_context value reaches the signal-matching section."""
        selected = SelectedWorkflowData(
            id="wf7",
            title="Todo WF",
            description="d",
            steps=[{"title": "S", "category": "c", "description": "d"}],
        )
        trigger_ctx = {"tracked_todos_context": "DISTINCTIVE_TODO_MARKER_XYZ"}

        with (
            patch(
                "app.helpers.message_helpers.WorkflowService.get_workflow",
                new_callable=AsyncMock,
                return_value=None,
            ),
            # The real SIGNAL_MATCHING_INSTRUCTIONS carries unescaped example
            # braces, so .format() on it raises KeyError('date') — a product bug
            # tracked separately. Substituting a minimal template keeps this test
            # on the helper's own behavior: reading the right key and rendering it.
            patch(
                "app.helpers.message_helpers.SIGNAL_MATCHING_INSTRUCTIONS",
                "TRACKED TODOS\n{tracked_todos_context}",
            ),
        ):
            result = await format_workflow_execution_message(
                selected, user_id="u1", trigger_context=trigger_ctx
            )

        assert "TRACKED TODOS" in result
        assert "DISTINCTIVE_TODO_MARKER_XYZ" in result

    @pytest.mark.asyncio
    async def test_no_tracked_todos_context_omits_signal_matching_section(self) -> None:
        """When the key is absent, the signal-matching section is omitted entirely."""
        selected = SelectedWorkflowData(
            id="wf8",
            title="No Todo WF",
            description="d",
            steps=[{"title": "S", "category": "c", "description": "d"}],
        )
        trigger_ctx = {"some_other_key": "value"}

        with patch(
            "app.helpers.message_helpers.WorkflowService.get_workflow",
            new_callable=AsyncMock,
            return_value=None,
        ):
            result = await format_workflow_execution_message(
                selected, user_id="u1", trigger_context=trigger_ctx
            )

        assert "TRACKED TODOS" not in result

    @pytest.mark.asyncio
    async def test_email_sender_and_subject_flow_through(self) -> None:
        """A real sender/subject on the triggering email must reach the message."""
        selected = SelectedWorkflowData(
            id="wf9",
            title="Email WF2",
            description="d",
            steps=[{"title": "S", "category": "c", "description": "d"}],
        )
        trigger_ctx = {
            "type": "gmail",
            "email_data": {
                "sender": "DISTINCTIVE_SENDER@example.com",
                "subject": "DISTINCTIVE SUBJECT LINE",
                "message_text": "body",
            },
            "triggered_at": "2024-06-01T00:00:00Z",
        }

        with patch(
            "app.helpers.message_helpers.WorkflowService.get_workflow",
            new_callable=AsyncMock,
            return_value=None,
        ):
            result = await format_workflow_execution_message(
                selected, user_id="u1", trigger_context=trigger_ctx
            )

        assert "DISTINCTIVE_SENDER@example.com" in result
        assert "DISTINCTIVE SUBJECT LINE" in result

    @pytest.mark.asyncio
    async def test_email_sender_and_subject_fall_back_when_missing(self) -> None:
        """Missing sender/subject keys render the exact literal fallbacks."""
        selected = SelectedWorkflowData(
            id="wf10",
            title="Email WF3",
            description="d",
            steps=[{"title": "S", "category": "c", "description": "d"}],
        )
        trigger_ctx = {
            "type": "gmail",
            "email_data": {"message_text": "body"},
            "triggered_at": "2024-06-01T00:00:00Z",
        }

        with patch(
            "app.helpers.message_helpers.WorkflowService.get_workflow",
            new_callable=AsyncMock,
            return_value=None,
        ):
            result = await format_workflow_execution_message(
                selected, user_id="u1", trigger_context=trigger_ctx
            )

        assert "From: Unknown" in result
        assert "Subject: No Subject" in result

    @pytest.mark.asyncio
    async def test_trigger_timestamp_flows_through(self) -> None:
        """A real triggered_at value must reach the rendered message."""
        selected = SelectedWorkflowData(
            id="wf11",
            title="Email WF4",
            description="d",
            steps=[{"title": "S", "category": "c", "description": "d"}],
        )
        trigger_ctx = {
            "type": "gmail",
            "email_data": {"sender": "a@b.com", "subject": "s", "message_text": "body"},
            "triggered_at": "DISTINCTIVE_TIMESTAMP_2024",
        }

        with patch(
            "app.helpers.message_helpers.WorkflowService.get_workflow",
            new_callable=AsyncMock,
            return_value=None,
        ):
            result = await format_workflow_execution_message(
                selected, user_id="u1", trigger_context=trigger_ctx
            )

        assert "DISTINCTIVE_TIMESTAMP_2024" in result

    @pytest.mark.asyncio
    async def test_trigger_timestamp_falls_back_when_missing(self) -> None:
        """A missing triggered_at key renders the exact literal fallback."""
        selected = SelectedWorkflowData(
            id="wf12",
            title="Email WF5",
            description="d",
            steps=[{"title": "S", "category": "c", "description": "d"}],
        )
        trigger_ctx = {
            "type": "gmail",
            "email_data": {"sender": "a@b.com", "subject": "s", "message_text": "body"},
        }

        with patch(
            "app.helpers.message_helpers.WorkflowService.get_workflow",
            new_callable=AsyncMock,
            return_value=None,
        ):
            result = await format_workflow_execution_message(
                selected, user_id="u1", trigger_context=trigger_ctx
            )

        assert "Received: Unknown" in result


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
        assert format_files_list(None) == ""
        assert format_files_list([]) == ""

    def test_empty_file_ids(self) -> None:
        files = [FileData(fileId="f1", url="u", filename="test.txt")]
        assert format_files_list(files, file_ids=[]) == ""

    def test_all_files(self) -> None:
        files = [
            FileData(fileId="f1", url="u1", filename="a.txt", sandbox_path="/mirrored/a.txt"),
            FileData(fileId="f2", url="u2", filename="b.pdf", sandbox_path="/mirrored/b.pdf"),
        ]
        result = format_files_list(files)
        assert "a.txt" in result
        assert "b.pdf" in result
        assert "user-uploaded/" in result

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
        assert format_files_list(files, file_ids=["f99"]) == ""

    def test_file_ids_none_returns_all(self) -> None:
        files = [FileData(fileId="f1", url="u", filename="a.txt")]
        result = format_files_list(files, file_ids=None)
        assert "a.txt" in result

    def test_conversation_id_in_path(self) -> None:
        files = [FileData(fileId="f1", url="u", filename="a.txt", sandbox_path="/mirrored/a.txt")]
        result = format_files_list(files, conversation_id="conv123")
        assert "/workspace/sessions/conv123/user-uploaded/a.txt" in result

    # The workspace mirror is best-effort — it needs JuiceFS, and `sandbox_path`
    # is None whenever it was unavailable. Handing the agent a path anyway sent
    # the executor into read/bash attempts that could only fail; it burned the
    # recursion limit on a real GAIA .xlsx case doing exactly that.

    def test_omits_the_path_when_the_file_never_reached_the_workspace(self) -> None:
        files = [FileData(fileId="f1", url="u", filename="a.txt", sandbox_path=None)]
        result = format_files_list(files, conversation_id="conv123")
        assert "/workspace/sessions/conv123/user-uploaded/a.txt" not in result
        assert "a.txt" in result
        assert "search_uploaded_files" in result

    def test_drops_the_read_bash_guide_when_nothing_is_on_disk(self) -> None:
        files = [FileData(fileId="f1", url="u", filename="a.txt", description="a summary")]
        result = format_files_list(files, conversation_id="conv123")
        assert "read the file at its path" not in result
        assert "copy into" not in result
        assert ".summary.md" not in result
        assert "a summary" in result

    def test_keeps_the_full_guide_when_a_file_is_on_disk(self) -> None:
        files = [
            FileData(
                fileId="f1",
                url="u",
                filename="a.txt",
                description="a summary",
                sandbox_path="/mirrored/a.txt",
            )
        ]
        result = format_files_list(files, conversation_id="conv123")
        assert "read the file at its path" in result
        assert "/workspace/sessions/conv123/user-uploaded/a.txt.summary.md" in result


class TestGetOnboardingSystemPrompt:
    """get_onboarding_system_prompt_if_applicable — onboarding/demo turns get
    the profession/inbox-triage prompt; everything else gets None."""

    async def test_onboarding_turn_builds_profession_context(self) -> None:
        user = UserDocument(
            id="u-1",
            name="Alice",
            onboarding={
                "phase": OnboardingPhase.INITIAL,
                "preferences": {"profession": "developer"},
                "triage_summary": {"summary": "17 unread from work", "total_scanned": 40},
            },
        )
        with (
            patch(
                "app.helpers.message_helpers.conversation_repository.get_onboarding_probe",
                new_callable=AsyncMock,
                return_value=SimpleNamespace(is_onboarding_conversation=True, message_count=1),
            ),
            patch(
                "app.helpers.message_helpers.user_repository.get",
                new_callable=AsyncMock,
                return_value=user,
            ),
        ):
            prompt = await get_onboarding_system_prompt_if_applicable(
                "u-1", "conv-1", latest_user_message="hello"
            )

        assert prompt is not None
        assert "Profession: developer" in prompt
        assert "Inbox summary: 17 unread from work" in prompt
        assert "Alice" in prompt

    async def test_a_legacy_profession_still_reaches_the_prompt(self) -> None:
        # `UserDocument.onboarding` skips validation because stored rows predate
        # today's constraints, so a read site must not re-impose them: the 50-char
        # cap guards new submissions. Re-imposing it here raises into the broad
        # except at the end of the helper and the user silently loses the prompt.
        legacy = "a" * 80
        user = UserDocument(
            id="u-1",
            name="Alice",
            onboarding={
                "phase": OnboardingPhase.INITIAL,
                "preferences": {"profession": legacy},
            },
        )
        with (
            patch(
                "app.helpers.message_helpers.conversation_repository.get_onboarding_probe",
                new_callable=AsyncMock,
                return_value=SimpleNamespace(is_onboarding_conversation=True, message_count=1),
            ),
            patch(
                "app.helpers.message_helpers.user_repository.get",
                new_callable=AsyncMock,
                return_value=user,
            ),
        ):
            prompt = await get_onboarding_system_prompt_if_applicable(
                "u-1", "conv-1", latest_user_message="hello"
            )

        assert prompt is not None
        assert f"Profession: {legacy}" in prompt

    async def test_no_profession_falls_back_to_not_specified(self) -> None:
        user = UserDocument(id="u-1", onboarding={"phase": OnboardingPhase.INITIAL})
        with (
            patch(
                "app.helpers.message_helpers.conversation_repository.get_onboarding_probe",
                new_callable=AsyncMock,
                return_value=SimpleNamespace(is_onboarding_conversation=True, message_count=1),
            ),
            patch(
                "app.helpers.message_helpers.user_repository.get",
                new_callable=AsyncMock,
                return_value=user,
            ),
        ):
            prompt = await get_onboarding_system_prompt_if_applicable(
                "u-1", "conv-1", latest_user_message="hello"
            )

        assert prompt is not None
        assert "Profession: not specified" in prompt
