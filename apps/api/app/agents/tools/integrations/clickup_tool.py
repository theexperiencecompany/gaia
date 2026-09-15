"""ClickUp tools using Composio custom tool infrastructure."""

from datetime import UTC, datetime

from composio import Composio
from composio.types import ExecuteRequestFn

from app.models.common_models import GatherContextInput
from app.models.integrations.clickup import ClickUpTask, ClickUpTaskList
from app.models.integrations.composio import CustomToolAuthCredentials
from app.utils.context_utils import execute_tool


def _is_overdue(task: ClickUpTask, today_ms: int) -> bool:
    if not task.due_date or int(task.due_date) >= today_ms:
        return False
    status_type = task.status.type if task.status is not None else None
    return status_type not in ("closed",)


def register_clickup_custom_tools(composio: Composio) -> list[str]:
    """Register ClickUp tools as Composio custom tools."""

    @composio.tools.custom_tool(toolkit="CLICKUP")
    def CUSTOM_GATHER_CONTEXT(
        request: GatherContextInput,
        execute_request: ExecuteRequestFn,
        auth_credentials: dict[str, object],
    ) -> dict[str, object]:
        """Get ClickUp context snapshot: assigned tasks across teams.

        Zero required parameters. Returns current account state for situational awareness.
        """
        del request, execute_request  # unused: framework-mandated custom-tool signature
        user_id = CustomToolAuthCredentials.parse(auth_credentials).user_id

        tasks = ClickUpTaskList.model_validate(
            execute_tool(
                "CLICKUP_GET_FILTERED_TEAM_TASKS",
                {"assignees": ["me"], "include_closed": False},
                user_id,
            )
        ).tasks
        today_ms = int(datetime.now(UTC).timestamp() * 1000)
        overdue = [t for t in tasks if _is_overdue(t, today_ms)]
        return {
            "tasks": [
                t.model_dump(  # pragma: no mutate -- dropping mode= is unobservable here and banned by tool-dump-boundary
                    mode="json",  # pragma: no mutate -- JSON-native fields only, so any mode value dumps identically
                    exclude_unset=True,
                )
                for t in tasks
            ],
            "overdue_tasks": [
                t.model_dump(  # pragma: no mutate -- dropping mode= is unobservable here and banned by tool-dump-boundary
                    mode="json",  # pragma: no mutate -- JSON-native fields only, so any mode value dumps identically
                    exclude_unset=True,
                )
                for t in overdue
            ],
        }

    return ["CLICKUP_CUSTOM_GATHER_CONTEXT"]
