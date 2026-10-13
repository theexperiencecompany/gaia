"""Asana tools using Composio custom tool infrastructure."""

from datetime import UTC, datetime

from composio import Composio
from composio.types import ExecuteRequestFn

from app.models.common_models import GatherContextInput
from app.models.integrations.asana import AsanaTaskSearch
from app.models.integrations.composio import CustomToolAuthCredentials
from app.utils.context_utils import execute_tool


def register_asana_custom_tools(composio: Composio) -> list[str]:
    """Register Asana tools as Composio custom tools."""

    @composio.tools.custom_tool(toolkit="ASANA")
    def CUSTOM_GATHER_CONTEXT(
        request: GatherContextInput,
        execute_request: ExecuteRequestFn,
        auth_credentials: dict[str, object],
    ) -> dict[str, object]:
        """Get Asana context snapshot: assigned open tasks across workspaces.

        Zero required parameters. Returns current workspace state for situational awareness.
        """
        del request, execute_request  # unused: framework-mandated custom-tool signature
        user_id = CustomToolAuthCredentials.parse(auth_credentials).user_id

        tasks = AsanaTaskSearch.model_validate(
            execute_tool(
                "ASANA_SEARCH_TASKS_IN_WORKSPACE",
                {"assignee.any": "me", "completed": False, "limit": 10},
                user_id,
            )
        ).all
        today = datetime.now(UTC).date().strftime("%Y-%m-%d")
        all_tasks: list[dict[str, object]] = []
        overdue: list[dict[str, object]] = []
        for task in tasks:
            # A task is all strings, so the lint-pinned json mode dumps what python mode would.
            payload = task.model_dump(mode="json", exclude_unset=True)  # pragma: no mutate
            all_tasks.append(payload)
            if task.due_on and task.due_on < today:
                overdue.append(payload)
        return {"tasks": all_tasks, "overdue_tasks": overdue}

    return ["ASANA_CUSTOM_GATHER_CONTEXT"]
