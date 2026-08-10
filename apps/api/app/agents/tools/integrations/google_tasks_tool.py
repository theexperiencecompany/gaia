"""Google Tasks custom tools using Composio custom tool infrastructure."""

from datetime import date
from typing import Any

from composio import Composio
from composio.types import ExecuteRequestFn

from app.models.common_models import GatherContextInput
from app.utils.context_utils import execute_tool
from app.utils.json_helpers import list_bag, text_opt_bag


def register_google_tasks_custom_tools(composio: Composio[Any, Any]) -> list[str]:  # type: ignore[explicit-any]
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
        user_id = auth_credentials.get("user_id", "")
        if not isinstance(user_id, str) or not user_id:
            raise ValueError("Missing user_id in auth_credentials")

        data = execute_tool(
            "GOOGLETASKS_LIST_ALL_TASKS",
            {"showCompleted": False, "maxResults": 20},
            user_id,
        )
        tasks = list_bag(data, "items") or list_bag(data, "tasks")
        today = date.today().strftime("%Y-%m-%d")
        overdue = [
            t for t in tasks if isinstance(t, dict) and (text_opt_bag(t, "due") or "9999") < today
        ]
        return {"tasks": tasks, "overdue_tasks": overdue}

    return ["GOOGLETASKS_CUSTOM_GATHER_CONTEXT"]
