"""Unit tests for app.agents.tools.todo_tools.

Covers plan_tasks / update_tasks (the executor's ephemeral task list tools),
the todo_progress streaming helper, the context formatter, and the
create_todo_pre_model_hook system-message injection.

The tools are LangGraph tools with InjectedState("todos") / InjectedToolCallId
params — invoked directly via ``await .coroutine(...)`` with the injected
values passed as plain kwargs, exactly as the compiled graph's tool node
would. ``datetime`` and ``uuid4`` are pinned so the produced todos are
byte-exact.
"""

from datetime import datetime, tzinfo
from typing import Any
from unittest.mock import MagicMock, patch
from uuid import UUID

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_core.tools import BaseTool
import pytest

from app.agents.prompts.todo_prompts import TODO_SYSTEM_PROMPT
from app.agents.tools.todo_tools import (
    _emit_todo_progress,
    _format_todos,
    create_todo_pre_model_hook,
    create_todo_tools,
)

MODULE = "app.agents.tools.todo_tools"


class _FrozenDatetime(datetime):
    """datetime subclass whose now() is pinned to a fixed UTC instant."""

    @classmethod
    def now(cls, tz: tzinfo | None = None) -> "_FrozenDatetime":
        return cls(2026, 7, 15, 12, 0, 0, tzinfo=tz)


def _uuid(hex_prefix: str) -> UUID:
    return UUID(hex=f"{hex_prefix}{'0' * 24}")


def _todo(id: str, content: str, status: str) -> dict[str, str]:
    return {"id": id, "content": content, "status": status, "created_at": "created"}


def _plan_tasks() -> BaseTool:
    return create_todo_tools(source="executor")[0]


def _update_tasks() -> BaseTool:
    return create_todo_tools(source="executor")[1]


# ---------------------------------------------------------------------------
# _emit_todo_progress
# ---------------------------------------------------------------------------


class TestEmitTodoProgress:
    @patch(f"{MODULE}.get_stream_writer")
    def test_writes_exact_payload_without_source_label(
        self, mock_writer_factory: MagicMock
    ) -> None:
        writer = MagicMock()
        mock_writer_factory.return_value = writer

        _emit_todo_progress([_todo("t1", "Task one", "completed")], "executor")

        writer.assert_called_once_with(
            {
                "todo_progress": {
                    "todos": [{"id": "t1", "content": "Task one", "status": "completed"}],
                    "source": "executor",
                }
            }
        )

    @patch(f"{MODULE}.get_stream_writer")
    def test_includes_integration_name_when_source_label_given(
        self, mock_writer_factory: MagicMock
    ) -> None:
        writer = MagicMock()
        mock_writer_factory.return_value = writer

        _emit_todo_progress([], "gmail", "Gmail Integration")

        payload = writer.call_args.args[0]
        assert payload == {
            "todo_progress": {
                "todos": [],
                "source": "gmail",
                "integration_name": "Gmail Integration",
            }
        }

    @patch(f"{MODULE}.get_stream_writer")
    def test_omits_integration_name_when_source_label_is_empty_string(
        self, mock_writer_factory: MagicMock
    ) -> None:
        writer = MagicMock()
        mock_writer_factory.return_value = writer

        _emit_todo_progress([], "executor", "")

        payload = writer.call_args.args[0]
        assert "integration_name" not in payload["todo_progress"]

    @patch(f"{MODULE}.get_stream_writer")
    def test_projects_only_id_content_status_from_each_todo(
        self, mock_writer_factory: MagicMock
    ) -> None:
        writer = MagicMock()
        mock_writer_factory.return_value = writer

        _emit_todo_progress(
            [{"id": "t1", "content": "c", "status": "pending", "created_at": "x", "extra": 1}],
            "executor",
        )

        payload = writer.call_args.args[0]
        assert payload["todo_progress"]["todos"] == [
            {"id": "t1", "content": "c", "status": "pending"}
        ]

    @patch(f"{MODULE}.get_stream_writer", side_effect=RuntimeError("no graph context"))
    @patch(f"{MODULE}.log")
    def test_missing_stream_writer_logs_warning_with_error_type(
        self, mock_log: MagicMock, mock_writer_factory: MagicMock
    ) -> None:
        _emit_todo_progress([_todo("t1", "c", "pending")], "executor")

        mock_log.warning.assert_called_once_with(
            "[TOOL] Stream writer not available for todo_progress", error_type="RuntimeError"
        )

    @patch(f"{MODULE}.get_stream_writer")
    @patch(f"{MODULE}.log")
    def test_writer_call_failure_logs_warning_with_error_type(
        self, mock_log: MagicMock, mock_writer_factory: MagicMock
    ) -> None:
        writer = MagicMock(side_effect=ValueError("channel closed"))
        mock_writer_factory.return_value = writer

        _emit_todo_progress([], "executor")

        mock_log.warning.assert_called_once_with(
            "[TOOL] Stream writer not available for todo_progress", error_type="ValueError"
        )

    @patch(f"{MODULE}.get_stream_writer")
    @patch(f"{MODULE}.log")
    def test_base_exception_propagates_without_logging(
        self, mock_log: MagicMock, mock_writer_factory: MagicMock
    ) -> None:
        """The guard is `except Exception` — BaseExceptions must propagate."""
        writer = MagicMock(side_effect=KeyboardInterrupt())
        mock_writer_factory.return_value = writer

        with pytest.raises(KeyboardInterrupt):
            _emit_todo_progress([], "executor")

        mock_log.warning.assert_not_called()


# ---------------------------------------------------------------------------
# _format_todos
# ---------------------------------------------------------------------------


class TestFormatTodos:
    def test_empty_list_returns_empty_string(self) -> None:
        assert _format_todos([]) == ""

    def test_single_pending_todo_is_exact(self) -> None:
        assert _format_todos([_todo("abc12345", "Write docs", "pending")]) == (
            "## Current Tasks\n[ ] 1. (abc12345) Write docs"
        )

    def test_status_icons_and_enumeration_are_exact(self) -> None:
        todos = [
            _todo("t1", "Done", "completed"),
            _todo("t2", "Doing", "in_progress"),
            _todo("t3", "Dropped", "cancelled"),
            _todo("t4", "Waiting", "pending"),
        ]
        assert _format_todos(todos) == (
            "## Current Tasks\n"
            "[✓] 1. (t1) Done\n"
            "[→] 2. (t2) Doing\n"
            "[✗] 3. (t3) Dropped\n"
            "[ ] 4. (t4) Waiting"
        )

    def test_unknown_status_falls_back_to_blank_icon(self) -> None:
        assert _format_todos([_todo("t1", "Weird", "archived")]) == (
            "## Current Tasks\n[ ] 1. (t1) Weird"
        )


# ---------------------------------------------------------------------------
# create_todo_tools — tool shapes
# ---------------------------------------------------------------------------


class TestCreateTodoTools:
    def test_returns_plan_tasks_and_update_tasks(self) -> None:
        tools = create_todo_tools()
        assert [t.name for t in tools] == ["plan_tasks", "update_tasks"]
        assert all(isinstance(t, BaseTool) for t in tools)


# ---------------------------------------------------------------------------
# plan_tasks
# ---------------------------------------------------------------------------


class TestPlanTasks:
    async def test_creates_todos_first_in_progress_rest_pending(self) -> None:
        with (
            patch(
                f"{MODULE}.uuid4",
                side_effect=[_uuid("11111111"), _uuid("22222222"), _uuid("33333333")],
            ),
            patch(f"{MODULE}.datetime", _FrozenDatetime),
        ):
            result = await _plan_tasks().coroutine(
                tasks=[
                    {"content": "Research"},
                    {"content": "Write"},
                    {"content": "Publish"},
                ],
                tool_call_id="call_1",
            )
        assert result.update["todos"] == [
            {
                "id": "11111111",
                "content": "Research",
                "status": "in_progress",
                "created_at": "2026-07-15T12:00:00+00:00",
            },
            {
                "id": "22222222",
                "content": "Write",
                "status": "pending",
                "created_at": "2026-07-15T12:00:00+00:00",
            },
            {
                "id": "33333333",
                "content": "Publish",
                "status": "pending",
                "created_at": "2026-07-15T12:00:00+00:00",
            },
        ]

    async def test_ids_are_unique_eight_char_hex_prefixes(self) -> None:
        with patch(f"{MODULE}.uuid4", side_effect=[_uuid("11111111"), _uuid("22222222")]):
            result = await _plan_tasks().coroutine(
                tasks=[{"content": "A"}, {"content": "B"}], tool_call_id="c"
            )
        ids = [t["id"] for t in result.update["todos"]]
        assert len(ids) == len(set(ids))
        assert all(len(i) == 8 and all(c in "0123456789abcdef" for c in i) for i in ids)

    async def test_empty_task_list_builds_none_starting_message(self) -> None:
        with patch(f"{MODULE}.datetime", _FrozenDatetime):
            result = await _plan_tasks().coroutine(tasks=[], tool_call_id="call_1")
        assert result.update["todos"] == []
        assert result.update["messages"][0].content == "Created plan with 0 tasks. Starting: none"

    async def test_tool_message_content_and_metadata_are_exact(self) -> None:
        with (
            patch(f"{MODULE}.uuid4", side_effect=[_uuid("11111111"), _uuid("22222222")]),
            patch(f"{MODULE}.datetime", _FrozenDatetime),
        ):
            result = await _plan_tasks().coroutine(
                tasks=[{"content": "First"}, {"content": "Second"}], tool_call_id="call_1"
            )
        msg = result.update["messages"][0]
        assert msg.content == "Created plan with 2 tasks. Starting: First"
        assert msg.tool_call_id == "call_1"
        assert msg.name == "plan_tasks"
        assert msg.additional_kwargs == {"todo_tool": True, "todo_source": "executor"}

    async def test_emits_progress_with_the_new_todos(self) -> None:
        with (
            patch(f"{MODULE}.uuid4", side_effect=[_uuid("11111111")]),
            patch(f"{MODULE}.datetime", _FrozenDatetime),
            patch(f"{MODULE}._emit_todo_progress") as mock_emit,
        ):
            result = await _plan_tasks().coroutine(tasks=[{"content": "A"}], tool_call_id="c")
        mock_emit.assert_called_once_with(result.update["todos"], "executor", None)

    async def test_source_label_is_forwarded_to_progress_event(self) -> None:
        tools = create_todo_tools(source="gmail", source_label="Gmail")
        with (
            patch(f"{MODULE}.uuid4", side_effect=[_uuid("11111111")]),
            patch(f"{MODULE}.datetime", _FrozenDatetime),
            patch(f"{MODULE}._emit_todo_progress") as mock_emit,
        ):
            await tools[0].coroutine(tasks=[{"content": "A"}], tool_call_id="c")
        mock_emit.assert_called_once()
        assert mock_emit.call_args.args[1:] == ("gmail", "Gmail")


# ---------------------------------------------------------------------------
# update_tasks — updates
# ---------------------------------------------------------------------------


class TestUpdateTasks:
    async def test_updates_existing_task_status_in_place(self) -> None:
        todos = [_todo("t1", "A", "in_progress"), _todo("t2", "B", "pending")]
        result = await _update_tasks().coroutine(
            updates=[{"task_id": "t1", "status": "completed"}],
            tool_call_id="call_1",
            todos=todos,
        )
        assert result.update["todos"] == [
            {"id": "t1", "content": "A", "status": "completed", "created_at": "created"},
            {"id": "t2", "content": "B", "status": "pending", "created_at": "created"},
        ]
        assert result.update["messages"][0].content == "Updated tasks: t1→completed"

    async def test_multiple_status_updates_summary_is_exact(self) -> None:
        todos = [
            _todo("t1", "A", "pending"),
            _todo("t2", "B", "pending"),
            _todo("t3", "C", "pending"),
        ]
        result = await _update_tasks().coroutine(
            updates=[
                {"task_id": "t1", "status": "in_progress"},
                {"task_id": "t2", "status": "completed"},
                {"task_id": "t3", "status": "cancelled"},
            ],
            tool_call_id="c",
            todos=todos,
        )
        assert [t["status"] for t in result.update["todos"]] == [
            "in_progress",
            "completed",
            "cancelled",
        ]
        assert (
            result.update["messages"][0].content
            == "Updated tasks: t1→in_progress; t2→completed; t3→cancelled"
        )

    async def test_adds_new_task_as_pending(self) -> None:
        todos = [_todo("t1", "A", "in_progress")]
        with (
            patch(f"{MODULE}.uuid4", side_effect=[_uuid("99999999")]),
            patch(f"{MODULE}.datetime", _FrozenDatetime),
        ):
            result = await _update_tasks().coroutine(
                updates=[{"content": "Discovered"}],
                tool_call_id="call_1",
                todos=todos,
            )
        assert result.update["todos"] == [
            {"id": "t1", "content": "A", "status": "in_progress", "created_at": "created"},
            {
                "id": "99999999",
                "content": "Discovered",
                "status": "pending",
                "created_at": "2026-07-15T12:00:00+00:00",
            },
        ]
        assert result.update["messages"][0].content == "Updated tasks: added: Discovered"

    async def test_multiple_added_tasks_summary_is_exact(self) -> None:
        with (
            patch(f"{MODULE}.uuid4", side_effect=[_uuid("11111111"), _uuid("22222222")]),
            patch(f"{MODULE}.datetime", _FrozenDatetime),
        ):
            result = await _update_tasks().coroutine(
                updates=[{"content": "A"}, {"content": "B"}],
                tool_call_id="c",
                todos=[],
            )
        assert result.update["messages"][0].content == "Updated tasks: added: A, B"

    async def test_mixed_update_and_add_summary_is_exact(self) -> None:
        todos = [_todo("t1", "A", "in_progress"), _todo("t2", "B", "pending")]
        with (
            patch(f"{MODULE}.uuid4", side_effect=[_uuid("55555555")]),
            patch(f"{MODULE}.datetime", _FrozenDatetime),
        ):
            result = await _update_tasks().coroutine(
                updates=[{"task_id": "t1", "status": "completed"}, {"content": "New"}],
                tool_call_id="c",
                todos=todos,
            )
        assert result.update["messages"][0].content == "Updated tasks: t1→completed; added: New"

    async def test_success_tool_message_metadata_is_exact(self) -> None:
        with patch(f"{MODULE}.datetime", _FrozenDatetime):
            result = await _update_tasks().coroutine(
                updates=[{"task_id": "t1", "status": "completed"}],
                tool_call_id="call_1",
                todos=[_todo("t1", "A", "pending")],
            )
        msg = result.update["messages"][0]
        assert msg.tool_call_id == "call_1"
        assert msg.name == "update_tasks"
        assert msg.status == "success"
        assert msg.additional_kwargs == {"todo_tool": True, "todo_source": "executor"}

    async def test_emits_progress_with_the_updated_todos(self) -> None:
        with (
            patch(f"{MODULE}.datetime", _FrozenDatetime),
            patch(f"{MODULE}._emit_todo_progress") as mock_emit,
        ):
            result = await _update_tasks().coroutine(
                updates=[{"task_id": "t1", "status": "completed"}],
                tool_call_id="c",
                todos=[_todo("t1", "A", "pending")],
            )
        mock_emit.assert_called_once_with(result.update["todos"], "executor", None)

    async def test_source_label_is_forwarded_to_progress_event(self) -> None:
        tools = create_todo_tools(source="gmail", source_label="Gmail")
        with (
            patch(f"{MODULE}.datetime", _FrozenDatetime),
            patch(f"{MODULE}._emit_todo_progress") as mock_emit,
        ):
            await tools[1].coroutine(
                updates=[{"task_id": "t1", "status": "completed"}],
                tool_call_id="c",
                todos=[_todo("t1", "A", "pending")],
            )
        mock_emit.assert_called_once()
        assert mock_emit.call_args.args[1:] == ("gmail", "Gmail")


# ---------------------------------------------------------------------------
# update_tasks — all-or-nothing validation
# ---------------------------------------------------------------------------


class TestUpdateTasksValidation:
    async def test_empty_updates_list_is_rejected(self) -> None:
        todos = [_todo("t1", "A", "pending")]
        with (
            patch(f"{MODULE}.datetime", _FrozenDatetime),
            patch(f"{MODULE}._emit_todo_progress") as mock_emit,
        ):
            result = await _update_tasks().coroutine(updates=[], tool_call_id="call_1", todos=todos)

        msg = result.update["messages"][0]
        assert msg.status == "error"
        assert msg.name == "update_tasks"
        assert msg.content == (
            "Updated nothing — the updates list was empty. Nothing in this batch "
            "was applied; fix the entry and resend the whole batch. Current task ids: t1"
        )
        assert "todos" not in result.update
        mock_emit.assert_not_called()

    async def test_unknown_task_id_is_rejected_with_current_ids(self) -> None:
        todos = [_todo("t1", "A", "pending"), _todo("t2", "B", "pending")]
        result = await _update_tasks().coroutine(
            updates=[{"task_id": "nope", "status": "completed"}],
            tool_call_id="c",
            todos=todos,
        )
        assert result.update["messages"][0].content == (
            "Updated nothing — no task with id 'nope' exists. Nothing in this batch "
            "was applied; fix the entry and resend the whole batch. Current task ids: t1, t2"
        )

    async def test_task_id_without_status_is_rejected(self) -> None:
        result = await _update_tasks().coroutine(
            updates=[{"task_id": "t1"}],
            tool_call_id="c",
            todos=[_todo("t1", "A", "pending")],
        )
        assert result.update["messages"][0].content.startswith(
            "Updated nothing — task 't1' was given no status to apply."
        )

    async def test_entry_with_neither_task_id_nor_content_is_rejected(self) -> None:
        result = await _update_tasks().coroutine(
            updates=[{"task_id": None, "content": None, "status": None}],
            tool_call_id="c",
            todos=[],
        )
        assert result.update["messages"][0].content.startswith(
            "Updated nothing — an entry had neither a task_id to update nor content to add."
        )

    async def test_multiple_problems_are_joined_in_batch_order(self) -> None:
        todos = [_todo("t1", "A", "pending")]
        result = await _update_tasks().coroutine(
            updates=[
                {"task_id": "ghost", "status": "completed"},
                {},
            ],
            tool_call_id="c",
            todos=todos,
        )
        assert result.update["messages"][0].content == (
            "Updated nothing — no task with id 'ghost' exists; "
            "an entry had neither a task_id to update nor content to add. "
            "Nothing in this batch was applied; fix the entry and resend the whole "
            "batch. Current task ids: t1"
        )

    async def test_current_task_ids_is_none_when_no_todos_exist(self) -> None:
        result = await _update_tasks().coroutine(
            updates=[{"task_id": "ghost", "status": "completed"}],
            tool_call_id="c",
            todos=[],
        )
        assert result.update["messages"][0].content.endswith("Current task ids: none")

    async def test_whole_batch_is_rejected_when_one_entry_is_invalid(self) -> None:
        """All-or-nothing: a valid update alongside an invalid one applies nothing."""
        todos = [_todo("t1", "A", "pending"), _todo("t2", "B", "pending")]
        result = await _update_tasks().coroutine(
            updates=[
                {"task_id": "t1", "status": "completed"},
                {"task_id": "ghost", "status": "completed"},
            ],
            tool_call_id="c",
            todos=todos,
        )
        msg = result.update["messages"][0]
        assert msg.status == "error"
        assert "no task with id 'ghost' exists" in msg.content
        assert "todos" not in result.update

    async def test_error_message_tool_metadata_is_exact(self) -> None:
        result = await _update_tasks().coroutine(
            updates=[{"task_id": "ghost", "status": "completed"}],
            tool_call_id="call_1",
            todos=[],
        )
        msg = result.update["messages"][0]
        assert msg.tool_call_id == "call_1"
        assert msg.name == "update_tasks"
        assert msg.status == "error"
        assert msg.additional_kwargs == {"todo_tool": True, "todo_source": "executor"}


# ---------------------------------------------------------------------------
# create_todo_pre_model_hook
# ---------------------------------------------------------------------------


class TestCreateTodoPreModelHook:
    def test_empty_messages_returns_state_unchanged(self) -> None:
        hook = create_todo_pre_model_hook()
        state: dict[str, Any] = {"messages": [], "todos": []}
        assert hook(state, {}, None) is state

    def test_missing_messages_key_returns_state_unchanged(self) -> None:
        hook = create_todo_pre_model_hook()
        state: dict[str, Any] = {"todos": []}
        assert hook(state, {}, None) is state

    def test_injects_todo_context_system_message_after_existing_system_messages(self) -> None:
        hook = create_todo_pre_model_hook()
        messages = [SystemMessage(content="base"), HumanMessage(content="hi")]
        state: dict[str, Any] = {"messages": messages, "todos": []}

        result = hook(state, {}, None)

        todo_msg = result["messages"][1]
        assert isinstance(todo_msg, SystemMessage)
        assert todo_msg.content == TODO_SYSTEM_PROMPT
        assert todo_msg.additional_kwargs == {"todo_context": True}
        assert [type(m) for m in result["messages"]] == [SystemMessage, SystemMessage, HumanMessage]

    def test_includes_formatted_todos_when_todos_exist(self) -> None:
        hook = create_todo_pre_model_hook()
        todos = [_todo("t1", "Write docs", "in_progress")]
        state: dict[str, Any] = {"messages": [SystemMessage(content="base")], "todos": todos}

        result = hook(state, {}, None)

        todo_msg = result["messages"][1]
        assert todo_msg.content == TODO_SYSTEM_PROMPT + "\n\n" + _format_todos(todos)

    def test_strips_prior_todo_context_message_in_additional_kwargs(self) -> None:
        hook = create_todo_pre_model_hook()
        stale = SystemMessage(content="stale", additional_kwargs={"todo_context": True})
        state: dict[str, Any] = {
            "messages": [SystemMessage(content="base"), stale, HumanMessage(content="hi")],
            "todos": [],
        }

        result = hook(state, {}, None)

        assert stale not in result["messages"]
        assert sum(1 for m in result["messages"] if m.additional_kwargs.get("todo_context")) == 1

    def test_strips_prior_todo_context_message_in_model_extra(self) -> None:
        hook = create_todo_pre_model_hook()
        stale = SystemMessage(content="stale", todo_context=True)
        state: dict[str, Any] = {
            "messages": [SystemMessage(content="base"), stale],
            "todos": [],
        }

        result = hook(state, {}, None)

        assert stale not in result["messages"]

    def test_non_system_message_with_todo_context_is_not_stripped(self) -> None:
        hook = create_todo_pre_model_hook()
        human = HumanMessage(content="hi", todo_context=True)
        state: dict[str, Any] = {"messages": [human], "todos": []}

        result = hook(state, {}, None)

        assert human in result["messages"]
        assert result["messages"][0].additional_kwargs == {"todo_context": True}
        assert result["messages"][1] is human

    def test_todo_context_false_in_additional_kwargs_is_not_stripped(self) -> None:
        hook = create_todo_pre_model_hook()
        msg = SystemMessage(content="plain", additional_kwargs={"todo_context": False})
        state: dict[str, Any] = {"messages": [msg], "todos": []}

        result = hook(state, {}, None)

        assert result["messages"][0] is msg

    def test_inserts_after_leading_run_of_system_messages(self) -> None:
        hook = create_todo_pre_model_hook()
        state: dict[str, Any] = {
            "messages": [
                SystemMessage(content="s1"),
                SystemMessage(content="s2"),
                HumanMessage(content="hi"),
                SystemMessage(content="stale", additional_kwargs={"todo_context": True}),
            ],
            "todos": [],
        }

        result = hook(state, {}, None)

        assert [m.content for m in result["messages"]] == [
            "s1",
            "s2",
            TODO_SYSTEM_PROMPT,
            "hi",
        ]

    def test_inserts_at_index_zero_when_first_message_is_not_a_system_message(self) -> None:
        hook = create_todo_pre_model_hook()
        state: dict[str, Any] = {"messages": [HumanMessage(content="hi")], "todos": []}

        result = hook(state, {}, None)

        assert result["messages"][0].additional_kwargs == {"todo_context": True}
        assert result["messages"][1].content == "hi"

    def test_preserves_other_state_keys(self) -> None:
        hook = create_todo_pre_model_hook()
        state: dict[str, Any] = {
            "messages": [HumanMessage(content="hi")],
            "todos": [],
            "user_id": "u1",
        }

        result = hook(state, {}, None)

        assert result["user_id"] == "u1"
        assert result is not state

    def test_hook_is_idempotent_when_run_twice(self) -> None:
        hook = create_todo_pre_model_hook()
        state: dict[str, Any] = {
            "messages": [SystemMessage(content="base"), HumanMessage(content="hi")],
            "todos": [],
        }

        once = hook(state, {}, None)
        twice = hook(once, {}, None)

        assert [m.content for m in twice["messages"]] == [m.content for m in once["messages"]]
