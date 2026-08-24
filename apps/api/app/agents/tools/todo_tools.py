"""
Agent task management tools using InjectedState.

Two tools for agent self-organization during complex multi-step work:
- plan_tasks: Create initial task list
- update_tasks: Update task statuses and/or add new tasks in a single call

Tools read/write the `todos` channel in graph state directly via
InjectedState and Command(update=...). No middleware, no markers,
no class — just pure functions with closures over `source`.

Streaming: Each mutation emits a `todo_progress` event via
get_stream_writer() so the frontend renders progress in real-time.

Pre-model hook: `create_todo_pre_model_hook()` injects current task
context into the latest non-memory SystemMessage before each LLM call.
"""

from collections.abc import Callable
from datetime import UTC, datetime
from typing import Annotated, Any, Literal, cast
from uuid import uuid4

from langchain.tools import InjectedToolCallId
from langchain_core.messages import SystemMessage, ToolMessage
from langchain_core.runnables import RunnableConfig
from langchain_core.tools import BaseTool, tool
from langgraph.config import get_stream_writer
from langgraph.prebuilt import InjectedState
from langgraph.store.base import BaseStore
from langgraph.types import Command
from typing_extensions import TypedDict

from app.agents.context.slots import TODO_CONTEXT_MARKER, mark
from app.agents.prompts.todo_prompts import (
    PLAN_TASKS_DESCRIPTION,
    TODO_SYSTEM_PROMPT,
    UPDATE_TASKS_DESCRIPTION,
)
from app.constants.log_tags import LogTag
from app.override.langgraph_bigtool.utils import State
from shared.py.wide_events import log

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
    payload = {"todo_progress": snapshot}
    try:
        writer = get_stream_writer()
        writer(payload)
    except Exception as e:
        log.warning(
            f"{LogTag.TOOL} Stream writer not available for todo_progress",
            error_type=type(e).__name__,
        )


def _format_todos(todos: list[Todo]) -> str:
    """Format todos for context injection."""
    if not todos:
        return ""

    lines = ["## Current Tasks"]
    for i, todo in enumerate(todos, 1):
        icon = {
            "completed": "\u2713",
            "in_progress": "\u2192",
            "cancelled": "\u2717",
            "pending": " ",
        }.get(todo["status"], " ")
        lines.append(f"[{icon}] {i}. ({todo['id']}) {todo['content']}")

    return "\n".join(lines)


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

    # TODO: Remove these tool calls from the conversation history, we are tracking
    # the tasks in state and these tool calls are just for updating the state.
    # We should not be adding these tool calls to the conversation history.

    @tool(description=PLAN_TASKS_DESCRIPTION)
    async def plan_tasks(
        tasks: list[TaskInput],
        tool_call_id: Annotated[str, InjectedToolCallId],
    ) -> Command[Any]:
        """Create a task plan for multi-step work."""
        now = datetime.now(UTC).isoformat()
        new_todos: list[Todo] = []

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

        first_task = new_todos[0]["content"] if new_todos else "none"
        return Command(
            update={
                "todos": new_todos,
                "messages": [
                    ToolMessage(
                        content=f"Created plan with {len(new_todos)} tasks. Starting: {first_task}",
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
    ) -> Command[Any]:
        """Update task statuses and/or add new tasks in a single call."""
        now = datetime.now(UTC).isoformat()
        updated_todos: list[Todo] = [t.copy() for t in todos]
        todo_map = {t["id"]: t for t in updated_todos}

        summary_parts: list[str] = []
        added: list[str] = []

        # Validate the whole batch before applying any of it. Two reasons this is
        # all-or-nothing rather than best-effort: a silently skipped entry told
        # the model "no changes" while reporting success, so it moved on with a
        # checklist that never advanced; and partial application makes the
        # model's retry non-idempotent — the valid additions would land twice
        # once it corrects the bad entry and resends the batch.
        problems: list[str] = []
        if not updates:
            problems.append("the updates list was empty")
        for entry in updates:
            task_id = entry.get("task_id")
            content = entry.get("content")
            status = entry.get("status")
            if task_id:
                if task_id not in todo_map:
                    problems.append(f"no task with id '{task_id}' exists")
                elif not status:
                    problems.append(f"task '{task_id}' was given no status to apply")
            elif not content:
                problems.append("an entry had neither a task_id to update nor content to add")

        if problems:
            return Command(
                update={
                    "messages": [
                        ToolMessage(
                            content=(
                                "Updated nothing — " + "; ".join(problems) + ". "
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

        for entry in updates:
            task_id = entry.get("task_id")
            content = entry.get("content")
            status = entry.get("status")

            if task_id:
                # Update existing task
                if task_id in todo_map and status:
                    todo_map[task_id]["status"] = status
                    summary_parts.append(f"{task_id}→{status}")
            elif content:
                # Add new task
                new_todo = Todo(
                    id=str(uuid4())[:8],
                    content=content,
                    status="pending",
                    created_at=now,
                )
                updated_todos.append(new_todo)
                todo_map[new_todo["id"]] = new_todo
                added.append(content)

        if added:
            summary_parts.append(f"added: {', '.join(added)}")

        summary = "; ".join(summary_parts) if summary_parts else "no changes"
        _emit_todo_progress(updated_todos, source, source_label)

        return Command(
            update={
                "todos": updated_todos,
                "messages": [
                    ToolMessage(
                        content=f"Updated tasks: {summary}",
                        tool_call_id=tool_call_id,
                        name="update_tasks",
                        additional_kwargs={"todo_tool": True, "todo_source": source},
                    )
                ],
            }
        )

    return [plan_tasks, update_tasks]


def create_todo_pre_model_hook(
    source: str = "executor",
) -> Callable[[State, RunnableConfig, BaseStore], State]:
    """Pre-model hook that emits a fresh ``todo_context`` SystemMessage each step.

    Appends and marks; where the message lands, and which older copy it replaces,
    is ``manage_system_prompts_node``'s job — this hook runs before it. Placing
    the message itself is what used to make its position depend on which other
    slots happened to be occupied that turn.
    """
    del source  # intentionally unused — kept for signature stability

    def todo_pre_model_hook(state: State, config: RunnableConfig, store: BaseStore) -> State:  # noqa: ARG001 -- LangChain injects config/store via the tool-call signature
        messages = list(state.get("messages", []))
        if not messages:
            return state

        todos = state.get("todos", [])
        parts = [TODO_SYSTEM_PROMPT]
        if todos:
            parts.append(_format_todos(todos))

        todo_msg = mark(
            SystemMessage(content="\n\n".join(parts)),
            TODO_CONTEXT_MARKER,
        )
        return cast(State, {**state, "messages": [*messages, todo_msg]})

    return todo_pre_model_hook
