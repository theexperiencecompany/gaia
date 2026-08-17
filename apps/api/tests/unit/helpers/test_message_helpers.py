"""Tests for app/helpers/message_helpers.py"""

from collections.abc import Iterator
from contextlib import contextmanager
from unittest.mock import AsyncMock, MagicMock, patch

from langchain_core.messages import SystemMessage
import pytest

from app.helpers.message_helpers import (
    _CORE_MEMORY_HEADING,
    MEMORY_RECALL_MAX_CHARS,
    _get_gaia_knowledge_section,
    _get_user_memories_section,
    build_dynamic_context_messages,
    create_system_message,
    format_calendar_event_context,
    format_files_list,
    format_reply_context,
    format_tool_selection_message,
    format_workflow_execution_message,
)
from app.memory.context import AGENDA_HEADING, RECENT_ACTIVITY_HEADING
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
    dynamic context flows via build_dynamic_context_messages."""

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

        with patch("app.helpers.message_helpers.memory_engine") as mock_svc:
            mock_svc.recall = AsyncMock(return_value=mock_results)
            result = await _get_user_memories_section("coffee", "user1")

        assert "User likes coffee" in result
        assert "User prefers dark mode" in result

    @pytest.mark.asyncio
    async def test_no_memories(self) -> None:
        mock_results = MagicMock()
        mock_results.memories = None

        with patch("app.helpers.message_helpers.memory_engine") as mock_svc:
            mock_svc.recall = AsyncMock(return_value=mock_results)
            result = await _get_user_memories_section("query", "user1")

        assert result == ""

    @pytest.mark.asyncio
    async def test_empty_memories_list(self) -> None:
        mock_results = MagicMock()
        mock_results.memories = []

        with patch("app.helpers.message_helpers.memory_engine") as mock_svc:
            mock_svc.recall = AsyncMock(return_value=mock_results)
            result = await _get_user_memories_section("q", "u")

        assert result == ""

    @pytest.mark.asyncio
    async def test_none_results(self) -> None:
        with patch("app.helpers.message_helpers.memory_engine") as mock_svc:
            mock_svc.recall = AsyncMock(return_value=None)
            result = await _get_user_memories_section("q", "u")

        assert result == ""

    @pytest.mark.asyncio
    async def test_exception_returns_empty(self) -> None:
        with patch("app.helpers.message_helpers.memory_engine") as mock_svc:
            mock_svc.recall = AsyncMock(side_effect=RuntimeError("mem fail"))
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
            mock_svc.search_knowledge = AsyncMock(side_effect=RuntimeError("chroma fail"))
            result = await _get_gaia_knowledge_section("q")

        assert result == ""


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


# ---------------------------------------------------------------------------
# build_dynamic_context_messages — the volatility split
# ---------------------------------------------------------------------------


@contextmanager
def _dynamic_context_seams(core_context: str, *, active_todo_banner: str = "") -> Iterator[None]:
    """Stub every I/O fetch `build_dynamic_context_messages` makes except the
    core-memory read, so the volatility split and the caps run for real."""
    with (
        patch("app.helpers.message_helpers.memory_engine") as mock_engine,
        patch(
            "app.helpers.message_helpers.build_connected_integrations_manifest",
            new=AsyncMock(return_value=""),
        ),
        patch(
            "app.helpers.message_helpers._get_tracked_todos_section",
            new=AsyncMock(return_value=""),
        ),
        patch(
            "app.helpers.message_helpers._build_active_todo_banner",
            new=AsyncMock(return_value=active_todo_banner),
        ),
    ):
        mock_engine.get_core_context = AsyncMock(return_value=core_context)
        yield


class TestDynamicContextVolatilitySplit:
    """The memory core is split by volatility: the byte-stable documents ride
    the cached prefix in ``memory_recall`` (uncapped — they only change when
    consolidation rewrites them), while the agenda and recent-activity journal
    churn every turn and are pushed into ``volatile_tail``, which IS capped."""

    @pytest.mark.asyncio
    async def test_stable_core_is_headed_and_is_all_the_recall_slot_holds(self) -> None:
        with _dynamic_context_seams("Loves espresso.\nShips on Fridays."):
            result = await build_dynamic_context_messages(user_id="u1", query=None)

        assert result.memory_recall is not None
        assert result.memory_recall.content == (
            f"{_CORE_MEMORY_HEADING}:\nLoves espresso.\nShips on Fridays."
        )
        assert result.volatile_tail is None

    @pytest.mark.asyncio
    async def test_agenda_and_recent_activity_leave_the_stable_core(self) -> None:
        core = (
            "Loves espresso."
            f"\n\n{AGENDA_HEADING}\n- ship the cache work"
            f"\n\n{RECENT_ACTIVITY_HEADING}\n- reviewed a PR"
        )
        with _dynamic_context_seams(core):
            result = await build_dynamic_context_messages(user_id="u1", query=None)

        assert result.memory_recall is not None
        assert result.memory_recall.content == f"{_CORE_MEMORY_HEADING}:\nLoves espresso."
        assert result.volatile_tail is not None
        assert AGENDA_HEADING in result.volatile_tail.content
        assert "- ship the cache work" in result.volatile_tail.content
        assert RECENT_ACTIVITY_HEADING in result.volatile_tail.content
        assert "- reviewed a PR" in result.volatile_tail.content

    @pytest.mark.asyncio
    async def test_the_agenda_cap_does_not_swallow_the_journal(self) -> None:
        """The agenda cap must bound the agenda ALONE.

        get_core_context emits the agenda before the journal, so splitting on
        the agenda marker first hands back the journal too. Capping that
        combined blob discarded the agenda's commitments and relabelled the
        journal's tail as the agenda — invisible unless the journal is long
        enough to blow the cap, which is why the shorter fixture above passed
        straight through the bug.
        """
        journal = "\n".join(f"- did thing {i}" for i in range(200))  # well over the cap
        core = (
            "Loves espresso."
            f"\n\n{AGENDA_HEADING}\n- ship the cache work"
            f"\n\n{RECENT_ACTIVITY_HEADING}\n{journal}"
        )
        with _dynamic_context_seams(core):
            result = await build_dynamic_context_messages(user_id="u1", query=None)

        assert result.volatile_tail is not None
        content = result.volatile_tail.content
        agenda_block = content.split(RECENT_ACTIVITY_HEADING)[0]
        # The agenda survives in full under its own heading...
        assert "- ship the cache work" in agenda_block
        # ...and the journal is a separate section, not swallowed into it.
        assert content.count(RECENT_ACTIVITY_HEADING) == 1
        assert RECENT_ACTIVITY_HEADING not in agenda_block
        # The journal keeps its newest entries under its own separate cap.
        assert "- did thing 199" in content

    @pytest.mark.asyncio
    async def test_a_user_with_no_core_memory_keeps_recall_empty(self) -> None:
        """Recall holds the stable core or nothing.

        The slot used to be filled from variable_parts[0], but that list omits
        every empty section — so a user with no core-memory document had their
        first CHURNING section filed as stable and placed inside the cached
        prefix, breaking the prefix every turn for exactly those users.
        """
        core = f"{RECENT_ACTIVITY_HEADING}\n- reviewed a PR"
        with _dynamic_context_seams(core):
            result = await build_dynamic_context_messages(user_id="u1", query=None)

        assert result.memory_recall is None
        assert result.volatile_tail is not None
        assert "- reviewed a PR" in result.volatile_tail.content

    @pytest.mark.asyncio
    async def test_stable_core_is_never_capped(self) -> None:
        """The global cap bounds the volatile tail only. Truncating the stable
        core would churn the cached prefix every time the core grew — the exact
        thing the split exists to prevent."""
        big_core = "core memory line. " * 600  # ~10.8k chars — over the cap
        with _dynamic_context_seams(big_core):
            result = await build_dynamic_context_messages(user_id="u1", query=None)

        assert result.memory_recall is not None
        content = result.memory_recall.content
        assert len(content) > MEMORY_RECALL_MAX_CHARS
        assert content == f"{_CORE_MEMORY_HEADING}:\n{big_core}"

    @pytest.mark.asyncio
    async def test_volatile_tail_is_capped_head_and_tail(self) -> None:
        banner = "ACTIVE TODO BANNER. " * 500 + "BANNER-END"  # ~10k chars
        core = f"Loves espresso.\n\n{RECENT_ACTIVITY_HEADING}\n- reviewed a PR"
        with _dynamic_context_seams(core, active_todo_banner=banner):
            result = await build_dynamic_context_messages(
                user_id="u1", query=None, active_todo_id="t1"
            )

        assert result.volatile_tail is not None
        content = result.volatile_tail.content
        assert len(content) <= MEMORY_RECALL_MAX_CHARS + 64
        # Head (recent activity) and tail (the run-binding directive) survive;
        # the middle is dropped.
        assert content.startswith(RECENT_ACTIVITY_HEADING)
        assert content.endswith("BANNER-END")
        assert "recall truncated to keep the prompt cache warm" in content
