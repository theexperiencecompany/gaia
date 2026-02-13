"""
TodoMiddleware - Custom task management middleware.

Provides efficient task tracking with three focused tools:
- plan_tasks: Create initial task list
- mark_task: Update one or more task statuses in a single call
- add_task: Add newly discovered tasks

Unlike LangChain's TodoListMiddleware, this:
- Injects current todos into context before each model call
- Provides granular operations instead of full list rewrites
- Uses a compact system prompt
- Processes state updates via after_model hook
- Streams todo_progress events to the frontend via stream_writer
"""

from collections.abc import Awaitable, Callable
from datetime import datetime, timezone
from typing import Annotated, Any, Literal
from uuid import uuid4

from app.agents.prompts.todo_prompts import (
    ADD_TASK_DESCRIPTION,
    MARK_TASK_DESCRIPTION,
    PLAN_TASKS_DESCRIPTION,
    TODO_SYSTEM_PROMPT,
)
from app.config.loggers import app_logger as logger
from langchain.agents.middleware.types import (
    AgentMiddleware,
    AgentState,
    ModelRequest,
    ModelResponse,
    OmitFromInput,
)
from langchain.tools import InjectedToolCallId
from langchain_core.messages import SystemMessage, ToolMessage
from langchain_core.tools import tool
from langgraph.types import Command
from typing_extensions import TypedDict

StreamWriterFn = Callable[[dict[str, Any]], None]


class Todo(TypedDict):
    """A single todo item."""

    id: str
    content: str
    status: Literal["pending", "in_progress", "completed", "cancelled"]
    created_at: str


class TodoState(AgentState[Any]):
    """State schema for todo middleware."""

    todos: Annotated[list[Todo], OmitFromInput]


class TaskInput(TypedDict):
    """Input schema for plan_tasks."""

    content: str


class TaskUpdate(TypedDict):
    """Input schema for a single task status update."""

    task_id: str
    status: Literal["in_progress", "completed", "cancelled"]


class TodoMiddleware(AgentMiddleware[TodoState, Any]):
    """Middleware providing task management tools with context injection.

    This middleware:
    1. Exposes 3 tools: plan_tasks, mark_task, add_task
    2. Injects current todos into system message before each model call
    3. Processes task update markers from tool calls via after_model hook
    4. Streams todo_progress snapshots to frontend on every mutation

    The tools use a marker-based update system:
    - plan_tasks: Directly sets the todos list
    - mark_task: Returns _mark_tasks marker (list), processed by after_model
    - add_task: Returns _add_task marker, processed by after_model
    """

    state_schema = TodoState

    def __init__(
        self,
        system_prompt: str = TODO_SYSTEM_PROMPT,
        source: str = "executor",
        stream_writer: StreamWriterFn | None = None,
    ):
        super().__init__()
        self.system_prompt = system_prompt
        self._source = source
        self._stream_writer: StreamWriterFn | None = stream_writer
        self.tools = [
            self._create_plan_tasks_tool(),
            self._create_mark_task_tool(),
            self._create_add_task_tool(),
        ]

    def set_stream_writer(self, writer: StreamWriterFn) -> None:
        self._stream_writer = writer

    def set_source(self, source: str) -> None:
        self._source = source

    def _emit_todo_progress(self, todos: list[Todo]) -> None:
        """Emit a todo_progress event via stream_writer.

        Tries LangGraph's get_stream_writer() first (works inside graph nodes).
        Falls back to the stored _stream_writer (for spawned subagent contexts).
        """
        payload = {
            "todo_progress": {
                "todos": [
                    {
                        "id": t["id"],
                        "content": t["content"],
                        "status": t["status"],
                    }
                    for t in todos
                ],
                "source": self._source,
            }
        }

        # Try LangGraph stream_writer (available in graph node context)
        try:
            from langgraph.config import get_stream_writer

            writer = get_stream_writer()
            writer(payload)
            return
        except Exception as e:  # noqa: B110
            # Expected when not in graph context, fall through to fallback writer
            logger.debug(f"Stream writer not available in current context: {e}")

        # Fallback to stored stream_writer (for spawned subagents)
        if self._stream_writer:
            try:
                self._stream_writer(payload)
            except Exception as e:
                logger.debug(f"Failed to emit todo_progress: {e}")

    def _format_todos(self, todos: list[Todo]) -> str:
        """Format todos for context injection."""
        if not todos:
            return ""

        lines = ["## Current Tasks"]
        for i, todo in enumerate(todos, 1):
            status_icon = {
                "completed": "✓",
                "in_progress": "→",
                "cancelled": "✗",
                "pending": " ",
            }.get(todo["status"], " ")

            lines.append(f"[{status_icon}] {i}. ({todo['id']}) {todo['content']}")

        return "\n".join(lines)

    def _create_plan_tasks_tool(self):
        middleware = self

        @tool(description=PLAN_TASKS_DESCRIPTION)
        def plan_tasks(
            tasks: list[TaskInput],
            tool_call_id: Annotated[str, InjectedToolCallId],
        ) -> Command[Any]:
            """Create a task plan for multi-step work."""
            now = datetime.now(timezone.utc).isoformat()
            todos: list[Todo] = []

            for i, task in enumerate(tasks):
                todos.append(
                    Todo(
                        id=str(uuid4())[:8],
                        content=task["content"],
                        status="in_progress" if i == 0 else "pending",
                        created_at=now,
                    )
                )

            # Emit progress snapshot immediately (plan_tasks sets todos directly)
            middleware._emit_todo_progress(todos)

            first_task = todos[0]["content"] if todos else "none"
            return Command(
                update={
                    "todos": todos,
                    "messages": [
                        ToolMessage(
                            content=f"Created plan with {len(todos)} tasks. Starting: {first_task}",
                            tool_call_id=tool_call_id,
                        )
                    ],
                }
            )

        return plan_tasks

    def _create_mark_task_tool(self):
        @tool(description=MARK_TASK_DESCRIPTION)
        def mark_task(
            updates: list[TaskUpdate],
            tool_call_id: Annotated[str, InjectedToolCallId],
        ) -> Command[Any]:
            """Update one or more task statuses."""
            summary = ", ".join(f"{u['task_id']}→{u['status']}" for u in updates)
            return Command(
                update={
                    "_mark_tasks": [
                        {"task_id": u["task_id"], "status": u["status"]}
                        for u in updates
                    ],
                    "messages": [
                        ToolMessage(
                            content=f"Updated: {summary}",
                            tool_call_id=tool_call_id,
                        )
                    ],
                }
            )

        return mark_task

    def _create_add_task_tool(self):
        @tool(description=ADD_TASK_DESCRIPTION)
        def add_task(
            content: str,
            tool_call_id: Annotated[str, InjectedToolCallId],
        ) -> Command[Any]:
            """Add a new task to the plan."""
            now = datetime.now(timezone.utc).isoformat()
            new_todo = Todo(
                id=str(uuid4())[:8],
                content=content,
                status="pending",
                created_at=now,
            )
            return Command(
                update={
                    "_add_task": new_todo,
                    "messages": [
                        ToolMessage(
                            content=f"Added task: {content}",
                            tool_call_id=tool_call_id,
                        )
                    ],
                }
            )

        return add_task

    async def awrap_model_call(
        self,
        request: ModelRequest,
        handler: Callable[[ModelRequest], Awaitable[ModelResponse]],
    ) -> ModelResponse:
        """Inject current todos into system message before model call."""
        todos = request.state.get("todos", [])
        todo_context = self._format_todos(todos) if todos else ""

        if request.system_message:
            base = request.system_message.text or ""
            parts = [base, self.system_prompt]
            if todo_context:
                parts.append(todo_context)
            new_content = "\n\n".join(parts)
        else:
            parts = [self.system_prompt]
            if todo_context:
                parts.append(todo_context)
            new_content = "\n\n".join(parts)

        updated_request = request.override(
            system_message=SystemMessage(content=new_content)
        )
        return await handler(updated_request)

    def _apply_markers(self, state: TodoState) -> dict[str, Any] | None:
        """Process _mark_tasks and _add_task markers from tool calls."""
        updates: dict[str, Any] = {}
        todos = list(state.get("todos", []))

        # Process _mark_tasks marker (list of updates)
        mark_tasks_data = state.get("_mark_tasks")
        if mark_tasks_data:
            todo_map = {t["id"]: t for t in todos}
            for entry in mark_tasks_data:
                task_id = entry.get("task_id")
                new_status = entry.get("status")
                if task_id and new_status and task_id in todo_map:
                    todo_map[task_id]["status"] = new_status

            updates["todos"] = todos
            updates["_mark_tasks"] = None

        # Process _add_task marker
        add_task_data = state.get("_add_task")
        if add_task_data:
            todos.append(add_task_data)
            updates["todos"] = todos
            updates["_add_task"] = None

        # Emit progress snapshot after applying markers
        if updates and "todos" in updates:
            self._emit_todo_progress(updates["todos"])

        return updates if updates else None

    async def aafter_model(
        self, state: TodoState, runtime: Any
    ) -> dict[str, Any] | None:
        """Process task update markers from tool calls."""
        return self._apply_markers(state)

    def after_model(self, state: TodoState, runtime: Any) -> dict[str, Any] | None:
        """Sync version of aafter_model for compatibility."""
        return self._apply_markers(state)
