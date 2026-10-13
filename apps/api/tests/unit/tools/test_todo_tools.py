"""plan_tasks: the plan it streams to the UI and the message it hands back to the model."""

from unittest.mock import MagicMock, patch

from langchain_core.messages import ToolMessage
import pytest

from app.agents.tools.todo_tools import create_todo_tools

pytestmark = pytest.mark.unit

WRITER = "app.agents.tools.todo_tools.current_stream_writer"


async def _plan(contents: list[str]) -> tuple[dict, MagicMock]:
    plan_tasks = create_todo_tools(source="mcp-42", source_label="Linear")[0]
    writer = MagicMock()
    with patch(WRITER, return_value=writer):
        command = await plan_tasks.coroutine(
            tasks=[{"content": content} for content in contents], tool_call_id="call-1"
        )
    return command.update, writer


async def test_a_plan_is_streamed_and_starts_on_its_first_task() -> None:
    update, writer = await _plan(["Draft the brief", "Send it"])

    todos = update["todos"]
    assert [(t["content"], t["status"]) for t in todos] == [
        ("Draft the brief", "in_progress"),
        ("Send it", "pending"),
    ]
    writer.assert_called_once_with(
        {
            "todo_progress": {
                "todos": [
                    {"id": t["id"], "content": t["content"], "status": t["status"]} for t in todos
                ],
                "source": "mcp-42",
                "integration_name": "Linear",
            }
        }
    )
    (message,) = update["messages"]
    assert isinstance(message, ToolMessage)
    assert message.content == "Created plan with 2 tasks. Starting: Draft the brief"


async def test_an_empty_plan_says_it_starts_on_nothing() -> None:
    update, _ = await _plan([])

    assert update["messages"][0].content == "Created plan with 0 tasks. Starting: none"


async def test_an_update_moves_a_task_and_adds_a_new_one() -> None:
    update_tasks = create_todo_tools()[1]
    todos = [
        {"id": "t1", "content": "Draft", "status": "in_progress", "created_at": "2026-01-01"},
    ]
    with patch(WRITER, return_value=MagicMock()):
        command = await update_tasks.coroutine(
            updates=[{"task_id": "t1", "status": "completed"}, {"content": "Send it"}],
            tool_call_id="call-2",
            todos=todos,
        )

    updated = command.update["todos"]
    assert [(t["content"], t["status"]) for t in updated] == [
        ("Draft", "completed"),
        ("Send it", "pending"),
    ]
    assert command.update["messages"][0].content == "Updated tasks: t1→completed; added: Send it"
    assert todos[0]["status"] == "in_progress"


async def test_an_update_naming_an_unknown_task_lists_the_real_ids() -> None:
    update_tasks = create_todo_tools()[1]
    todos = [{"id": "t1", "content": "Draft", "status": "pending", "created_at": "2026-01-01"}]

    command = await update_tasks.coroutine(
        updates=[{"task_id": "t9", "status": "completed"}], tool_call_id="call-3", todos=todos
    )

    assert command.update["messages"][0].content.endswith("Current task ids: t1")
