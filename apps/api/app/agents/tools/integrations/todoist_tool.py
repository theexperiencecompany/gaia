"""Todoist tools using Composio custom tool infrastructure."""

from datetime import UTC, datetime

from composio import Composio
from composio.types import ExecuteRequestFn

from app.models.common_models import GatherContextInput
from app.models.integrations.composio import CustomToolAuthCredentials
from app.models.integrations.todoist import TodoistTask, TodoistTaskList
from app.utils.context_utils import execute_tool


def _is_overdue(task: TodoistTask, today: str) -> bool:
    return task.due is not None and task.due.date is not None and task.due.date < today


def register_todoist_custom_tools(composio: Composio) -> list[str]:
    """Register Todoist tools as Composio custom tools."""

    @composio.tools.custom_tool(toolkit="TODOIST")
    def CUSTOM_GATHER_CONTEXT(
        request: GatherContextInput,
        execute_request: ExecuteRequestFn,
        auth_credentials: dict[str, object],
    ) -> dict[str, object]:
        """Get Todoist context snapshot: tasks and overdue items.

        Zero required parameters. Returns current task state for situational awareness.
        """
        del request, execute_request  # unused: framework-mandated custom-tool signature
        user_id = CustomToolAuthCredentials.parse(auth_credentials).user_id

        tasks = TodoistTaskList.model_validate(
            execute_tool("TODOIST_GET_ALL_TASKS", {}, user_id)
        ).all
        today = datetime.now(UTC).date().strftime("%Y-%m-%d")
        all_tasks: list[dict[str, object]] = []
        overdue: list[dict[str, object]] = []
        for task in tasks:
            # A task is all strings, so the lint-pinned json mode dumps what python mode would.
            payload = task.model_dump(mode="json", exclude_unset=True)  # pragma: no mutate
            all_tasks.append(payload)
            if _is_overdue(task, today):
                overdue.append(payload)
        return {"tasks": all_tasks, "overdue_tasks": overdue}

    return ["TODOIST_CUSTOM_GATHER_CONTEXT"]
