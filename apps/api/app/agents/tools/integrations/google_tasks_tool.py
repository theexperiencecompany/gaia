"""Google Tasks custom tools using Composio custom tool infrastructure."""

from datetime import UTC, datetime

from composio import Composio
from composio.types import ExecuteRequestFn

from app.models.common_models import GatherContextInput
from app.models.integrations.composio import CustomToolAuthCredentials
from app.models.integrations.google_tasks import GoogleTaskList
from app.utils.context_utils import execute_tool


def register_google_tasks_custom_tools(composio: Composio) -> list[str]:
    """Register Google Tasks tools as Composio custom tools."""

    @composio.tools.custom_tool(toolkit="GOOGLETASKS")
    def CUSTOM_GATHER_CONTEXT(
        request: GatherContextInput,
        execute_request: ExecuteRequestFn,
        auth_credentials: dict[str, object],
    ) -> dict[str, object]:
        """Get Google Tasks context snapshot: task lists and overdue/due-today tasks.

        Zero required parameters. Returns task lists and urgent tasks.
        """
        del request, execute_request  # unused: framework-mandated custom-tool signature
        user_id = CustomToolAuthCredentials.parse(auth_credentials).user_id

        tasks = GoogleTaskList.model_validate(
            execute_tool(
                "GOOGLETASKS_LIST_ALL_TASKS",
                {"showCompleted": False, "maxResults": 20},
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
            if task.due is not None and task.due < today:
                overdue.append(payload)
        return {"tasks": all_tasks, "overdue_tasks": overdue}

    return ["GOOGLETASKS_CUSTOM_GATHER_CONTEXT"]
