"""
Agent task management tools using InjectedState.

Two tools for agent self-organization during complex multi-step work:
- plan_tasks: Create initial task list
- update_tasks: Update task statuses and/or add new tasks in a single call

Tools read/write the `todos` channel in graph state directly via
InjectedState and Command(update=...). No middleware, no markers,
no class — just pure functions with closures over `source`.

Streaming: Each mutation emits a `todo_progress` event via
current_stream_writer() so the frontend renders progress in real-time.

Each result carries the whole plan as it now stands, so the thread holds the
current plan where it last changed; the instructions live in the executor's
static prompt (TODO_SYSTEM_PROMPT).
"""

from datetime import UTC, datetime
from typing import Annotated, Any, Literal
from uuid import uuid4

from langchain.tools import InjectedToolCallId
from langchain_core.messages import ToolMessage
from langchain_core.tools import BaseTool, tool
from langgraph.prebuilt import InjectedState
from langgraph.types import Command
from typing_extensions import TypedDict

from app.agents.prompts.todo_prompts import (
    PLAN_TASKS_DESCRIPTION,
    UPDATE_TASKS_DESCRIPTION,
)
from app.models.agent_models import current_stream_writer

TODO_TOOL_NAMES: set[str] = {"plan_tasks", "update_tasks"}


class Todo(TypedDict):
    """A single todo item."""

    id: str
    content: str
    status: Literal["pending", "in_progress", "completed", "cancelled"]
    created_at: str


class TaskInput(TypedDict):
    """Input schema for plan_tasks."""

    content: str


class TaskUpdate(TypedDict, total=False):
    """Input schema for a single task update or new task addition.

    To update an existing task: provide task_id and status.
    To add a new task: provide only content (omit task_id and status).
    """

    task_id: str | None  # omit to add a new task
    content: str | None  # required when adding a new task
    status: Literal["in_progress", "completed", "cancelled"] | None  # required when updating


def _emit_todo_progress(todos: list[Todo], source: str, source_label: str | None = None) -> None:
    """Emit a todo_progress event via LangGraph stream_writer.

    `source` is the stable grouping key (e.g. a custom MCP integration id);
    `source_label` is its human-readable name, included so the frontend can
    show the integration's name instead of reverse-mapping the id.
    """
    snapshot: dict[str, Any] = {
        "todos": [{"id": t["id"], "content": t["content"], "status": t["status"]} for t in todos],
        "source": source,
    }
    if source_label:
        snapshot["integration_name"] = source_label
    current_stream_writer()({"todo_progress": snapshot})


def _format_todos(todos: list[Todo]) -> str:
    """Render the plan as a tool result states it."""
    if not todos:
        return ""

    lines = ["## Current Tasks"]
    todo: Todo
    for i, todo in enumerate(todos, 1):
        icon = {
            "completed": "\u2713",
            "in_progress": "\u2192",
            "cancelled": "\u2717",
            "pending": " ",
        }.get(todo["status"], " ")
        lines.append(f"[{icon}] {i}. ({todo['id']}) {todo['content']}")

    return "\n".join(lines)


def _with_plan(summary: str, todos: list[Todo]) -> str:
    """Return a tool result's summary followed by the plan as it now stands, when there is one."""
    plan = _format_todos(todos)
    return f"{summary}\n\n{plan}" if plan else summary


def _by_id(todos: list[Todo]) -> dict[str, Todo]:
    """Return the plan's tasks keyed by id."""
    by_id: dict[str, Todo] = {}
    for todo in todos:
        task: Todo = todo
        by_id[task["id"]] = task
    return by_id


def _batch_problems(updates: list[TaskUpdate], todo_map: dict[str, Todo]) -> list[str]:
    """Return why a batch cannot apply, checked whole: a partial apply would land valid additions twice on retry."""
    problems: list[str] = []
    if not updates:
        problems.append("the updates list was empty")
    for entry in updates:
        update: TaskUpdate = entry
        task_id = update.get("task_id")
        if task_id:
            if task_id not in todo_map:
                problems.append(f"no task with id '{task_id}' exists")
            elif not update.get("status"):
                problems.append(f"task '{task_id}' was given no status to apply")
        elif not update.get("content"):
            problems.append("an entry had neither a task_id to update nor content to add")
    return problems


def _apply_updates(updates: list[TaskUpdate], todos: list[Todo]) -> tuple[list[Todo], str]:
    """Return the plan with a validated batch applied, and a summary of what changed."""
    now = datetime.now(UTC).isoformat()
    updated_todos: list[Todo] = [t.copy() for t in todos]
    todo_map = _by_id(updated_todos)
    summary_parts: list[str] = []
    added: list[str] = []
    for entry in updates:
        update: TaskUpdate = entry
        task_id = update.get("task_id")
        content = update.get("content")
        status = update.get("status")
        if task_id:
            if task_id in todo_map and status:
                todo_map[task_id]["status"] = status
                summary_parts.append(f"{task_id}→{status}")
        elif content:
            new_todo: Todo = Todo(
                id=str(uuid4())[:8], content=content, status="pending", created_at=now
            )
            updated_todos.append(new_todo)
            todo_map[new_todo["id"]] = new_todo
            added.append(content)
    if added:
        summary_parts.append(f"added: {', '.join(added)}")
    return updated_todos, "; ".join(summary_parts) if summary_parts else "no changes"


def create_todo_tools(source: str = "executor", source_label: str | None = None) -> list[BaseTool]:
    """Create plan_tasks and update_tasks tools with `source` baked in.

    Each tool reads current todos via InjectedState("todos"), mutates,
    streams progress, and returns Command(update={"todos": ...}).

    Args:
        source: Identifier for todo_progress events (e.g. "executor", "gmail")
        source_label: Human-readable name for the source (e.g. a custom MCP
            integration's display name). Streamed so the frontend shows the
            name instead of the raw id.

    Returns:
        List of two BaseTool instances
    """

    @tool(description=PLAN_TASKS_DESCRIPTION)
    async def plan_tasks(
        tasks: list[TaskInput],
        tool_call_id: Annotated[str, InjectedToolCallId],
    ) -> Command[str]:
        """Create a task plan for multi-step work."""
        now = datetime.now(UTC).isoformat()
        new_todos: list[Todo] = []

        task: TaskInput
        for i, task in enumerate(tasks):
            new_todos.append(
                Todo(
                    id=str(uuid4())[:8],
                    content=task["content"],
                    status="in_progress" if i == 0 else "pending",
                    created_at=now,
                )
            )

        _emit_todo_progress(new_todos, source, source_label)

        first_task = next((todo["content"] for todo in new_todos), "none")
        return Command(
            update={
                "todos": new_todos,
                "messages": [
                    ToolMessage(
                        content=_with_plan(
                            f"Created plan with {len(new_todos)} tasks. Starting: {first_task}",
                            new_todos,
                        ),
                        tool_call_id=tool_call_id,
                        name="plan_tasks",
                        additional_kwargs={"todo_tool": True, "todo_source": source},
                    )
                ],
            }
        )

    @tool(description=UPDATE_TASKS_DESCRIPTION)
    async def update_tasks(
        updates: list[TaskUpdate],
        tool_call_id: Annotated[str, InjectedToolCallId],
        todos: Annotated[list[Todo], InjectedState("todos")],
    ) -> Command[str]:
        """Update task statuses and/or add new tasks in a single call."""
        todo_map = _by_id(todos)
        problems = _batch_problems(updates, todo_map)
        if problems:
            return Command(
                update={
                    "messages": [
                        ToolMessage(
                            content=(
                                "Updated nothing: " + "; ".join(problems) + ". "
                                "Nothing in this batch was applied; fix the entry and resend "
                                "the whole batch. Current task ids: "
                                + (", ".join(todo_map) if todo_map else "none")
                            ),
                            tool_call_id=tool_call_id,
                            name="update_tasks",
                            status="error",
                            additional_kwargs={"todo_tool": True, "todo_source": source},
                        )
                    ]
                }
            )

        updated_todos, summary = _apply_updates(updates, todos)
        _emit_todo_progress(updated_todos, source, source_label)

        return Command(
            update={
                "todos": updated_todos,
                "messages": [
                    ToolMessage(
                        content=_with_plan(f"Updated tasks: {summary}", updated_todos),
                        tool_call_id=tool_call_id,
                        name="update_tasks",
                        additional_kwargs={"todo_tool": True, "todo_source": source},
                    )
                ],
            }
        )

    return [plan_tasks, update_tasks]
