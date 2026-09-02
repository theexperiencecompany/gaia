"""Tests for app/helpers/message_helpers.py"""

from unittest.mock import AsyncMock, MagicMock, patch

from langchain_core.messages import SystemMessage
import pytest

from app.constants.agents import PLAYBOOK_FALLBACK_CONTEXT_KEY
from app.constants.chat import UPLOADED_FILE_INLINE_SUMMARY_MAX_CHARS
from app.helpers.message_helpers import (
    _uploaded_file_lines,
    create_system_message,
    format_calendar_event_context,
    format_files_list,
    format_reply_context,
    format_tool_selection_message,
    format_workflow_execution_message,
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
        msg = create_system_message(user_name="X", agent_type="unknown")  # type: ignore[arg-type]  # out-of-Literal value exercises the unknown-agent branch
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


class TestWorkflowExecutionMessageBranches:
    """The branch choices and bounds inside ``format_workflow_execution_message``.

    The existing tests above assert a title survives into the output, which a
    great many wrong implementations also satisfy. These pin the decisions: which
    template is chosen, where the email preview is cut, and whether a partially
    replayed run's evidence reaches the agent — getting that last one wrong makes
    the agent redo steps that already had side effects.
    """

    @staticmethod
    def _selected() -> SelectedWorkflowData:
        return SelectedWorkflowData(
            id="wf_1",
            title="Morning Brief",
            description="desc",
            prompt="do the thing",
            steps=[{"title": "S1", "category": "c1", "description": "d1"}],
        )

    @staticmethod
    def _no_db_workflow():
        return patch(
            "app.helpers.message_helpers.WorkflowService.get_workflow",
            new_callable=AsyncMock,
            return_value=None,
        )

    @pytest.mark.asyncio
    async def test_a_gmail_trigger_selects_the_email_template(self) -> None:
        with self._no_db_workflow():
            result = await format_workflow_execution_message(
                self._selected(),
                user_id="u1",
                trigger_context={
                    "type": "gmail",
                    "email_data": {"sender": "a@b.com", "subject": "Subj", "message_text": "Body"},
                    "triggered_at": "2026-08-27T00:00:00Z",
                },
            )

        assert "a@b.com" in result
        assert "Subj" in result
        assert "2026-08-27T00:00:00Z" in result

    @pytest.mark.asyncio
    async def test_a_non_gmail_trigger_does_not_select_the_email_template(self) -> None:
        with self._no_db_workflow():
            result = await format_workflow_execution_message(
                self._selected(),
                user_id="u1",
                trigger_context={"type": "schedule", "triggered_at": "2026-08-27T00:00:00Z"},
            )

        assert "a@b.com" not in result
        assert "Morning Brief" in result

    @pytest.mark.asyncio
    async def test_a_long_email_body_is_previewed_not_pasted_whole(self) -> None:
        with self._no_db_workflow():
            result = await format_workflow_execution_message(
                self._selected(),
                user_id="u1",
                trigger_context={
                    "type": "gmail",
                    "email_data": {"sender": "a@b.com", "subject": "S", "message_text": "x" * 500},
                },
            )

        assert "x" * 200 + "..." in result
        assert "x" * 201 not in result

    @pytest.mark.asyncio
    async def test_a_short_email_body_is_not_marked_truncated(self) -> None:
        with self._no_db_workflow():
            result = await format_workflow_execution_message(
                self._selected(),
                user_id="u1",
                trigger_context={
                    "type": "gmail",
                    "email_data": {"sender": "a@b.com", "subject": "S", "message_text": "short"},
                },
            )

        assert "short" in result
        assert "short..." not in result

    @pytest.mark.asyncio
    async def test_a_stopped_replay_tells_the_agent_what_already_ran(self) -> None:
        """Without this the agent repeats steps whose side effects already happened."""
        note = "<already_ran>sent the digest email</already_ran>"

        with self._no_db_workflow():
            result = await format_workflow_execution_message(
                self._selected(),
                user_id="u1",
                trigger_context={PLAYBOOK_FALLBACK_CONTEXT_KEY: note},
            )

        assert result.endswith(note)

    @pytest.mark.asyncio
    async def test_the_same_evidence_reaches_an_email_triggered_fallback(self) -> None:
        note = "<already_ran>archived 3 threads</already_ran>"

        with self._no_db_workflow():
            result = await format_workflow_execution_message(
                self._selected(),
                user_id="u1",
                trigger_context={
                    "type": "gmail",
                    "email_data": {"sender": "a@b.com", "subject": "S", "message_text": "m"},
                    PLAYBOOK_FALLBACK_CONTEXT_KEY: note,
                },
            )

        assert result.endswith(note)
        assert "a@b.com" in result

    @pytest.mark.asyncio
    async def test_an_ordinary_run_carries_no_replay_evidence(self) -> None:
        with self._no_db_workflow():
            result = await format_workflow_execution_message(self._selected(), user_id="u1")

        assert "already_ran" not in result

    @pytest.mark.asyncio
    async def test_a_gmail_trigger_missing_every_field_renders_the_stated_defaults(self) -> None:
        """A Gmail trigger can arrive with an unparsed header or no timestamp. The
        prompt still has to read as a sentence, so each blank renders its own named
        placeholder rather than the literal ``None`` a bare ``.get`` would leave."""
        with self._no_db_workflow():
            result = await format_workflow_execution_message(
                self._selected(),
                user_id="u1",
                trigger_context={"type": "gmail", "email_data": {"message_text": ""}},
            )

        lines = result.splitlines()
        assert "- From: Unknown" in lines
        assert "- Subject: No Subject" in lines
        assert "- Preview: " in lines
        assert "- Received: Unknown" in lines

    @pytest.mark.asyncio
    async def test_an_email_body_at_the_preview_limit_is_not_marked_truncated(self) -> None:
        """Exactly at the bound is a whole body, not a cut one — an ellipsis here
        tells the agent to go fetch a rest that does not exist."""
        with self._no_db_workflow():
            result = await format_workflow_execution_message(
                self._selected(),
                user_id="u1",
                trigger_context={
                    "type": "gmail",
                    "email_data": {"sender": "a@b.com", "subject": "S", "message_text": "x" * 200},
                },
            )

        assert f"- Preview: {'x' * 200}" in result.splitlines()

    @pytest.mark.asyncio
    async def test_an_email_body_one_char_over_the_limit_is_marked_truncated(self) -> None:
        with self._no_db_workflow():
            result = await format_workflow_execution_message(
                self._selected(),
                user_id="u1",
                trigger_context={
                    "type": "gmail",
                    "email_data": {"sender": "a@b.com", "subject": "S", "message_text": "x" * 201},
                },
            )

        assert f"- Preview: {'x' * 200}..." in result.splitlines()

    @pytest.mark.asyncio
    async def test_a_manual_run_ends_with_the_users_own_message(self) -> None:
        """The user's words are the last thing the prompt says, so the model reads
        them as the instruction rather than as one more line of workflow boilerplate."""
        with self._no_db_workflow():
            result = await format_workflow_execution_message(
                self._selected(), user_id="u1", existing_content="Run it now please"
            )

        assert result.splitlines()[-1] == "Run it now please"

    @pytest.mark.asyncio
    async def test_a_manual_run_with_no_message_falls_back_to_naming_the_workflow(self) -> None:
        with self._no_db_workflow():
            result = await format_workflow_execution_message(
                self._selected(), user_id="u1", existing_content=""
            )

        assert result.splitlines()[-1] == "Execute workflow: Morning Brief"


# ---------------------------------------------------------------------------
# _uploaded_file_lines
# ---------------------------------------------------------------------------


class TestUploadedFileLines:
    """One attachment's rendered lines. ``format_files_list`` only joins these, so
    the path, the id and the summary bound are all decided here."""

    @staticmethod
    def _file(**overrides: object) -> FileData:
        fields: dict[str, object] = {
            "fileId": "f1",
            "url": "u",
            "filename": "a.txt",
            "sandbox_path": "/mirrored/a.txt",
        }
        fields.update(overrides)
        return FileData(**fields)  # type: ignore[arg-type]  # overrides are typed per-field by FileData

    def test_a_run_with_no_conversation_uses_the_relative_upload_dir(self) -> None:
        entry = _uploaded_file_lines(self._file(), None, True)

        assert entry == (["- a.txt  (id: f1)  →  `./user-uploaded/a.txt`"], True)

    def test_a_file_that_never_reached_the_workspace_names_the_search_tool(self) -> None:
        entry = _uploaded_file_lines(self._file(sandbox_path=None), "conv1", True)

        assert entry == (
            ["- a.txt  (id: f1) — not on disk, use `search_uploaded_files`"],
            False,
        )

    def test_a_summary_exactly_at_the_limit_is_kept_whole(self) -> None:
        summary = "s" * UPLOADED_FILE_INLINE_SUMMARY_MAX_CHARS
        entry = _uploaded_file_lines(self._file(description=summary), "conv1", True)

        assert entry == (
            [
                "- a.txt  (id: f1)  →  `/workspace/sessions/conv1/user-uploaded/a.txt`",
                f"    summary: {summary}",
                "    full summary: `/workspace/sessions/conv1/user-uploaded/a.txt.summary.md`",
            ],
            True,
        )

    def test_an_over_long_summary_is_cut_at_the_limit_with_no_dangling_space(self) -> None:
        """The cut lands mid-sentence, so the character before it is often a space.
        Leaving it in puts the ellipsis adrift from the last word it belongs to."""
        body = "s" * (UPLOADED_FILE_INLINE_SUMMARY_MAX_CHARS - 1)
        entry = _uploaded_file_lines(
            self._file(description=f"{body} tail-past-the-limit"), "conv1", True
        )

        assert entry == (
            [
                "- a.txt  (id: f1)  →  `/workspace/sessions/conv1/user-uploaded/a.txt`",
                f"    summary: {body}…",
                "    full summary: `/workspace/sessions/conv1/user-uploaded/a.txt.summary.md`",
            ],
            True,
        )

    def test_an_unsafe_filename_is_dropped_rather_than_rendered(self) -> None:
        assert _uploaded_file_lines(self._file(filename=".."), "conv1", True) is None
