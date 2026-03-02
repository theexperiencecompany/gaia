"""Google Tasks custom tools using Composio custom tool infrastructure."""

from datetime import date
from typing import Any, Dict, List

from composio import Composio

from app.models.common_models import GatherContextInput
from app.utils.context_utils import execute_tool


def register_google_tasks_custom_tools(composio: Composio) -> List[str]:
    """Register Google Tasks tools as Composio custom tools."""

    @composio.tools.custom_tool(toolkit="GOOGLETASKS")
    def CUSTOM_GATHER_CONTEXT(
        request: GatherContextInput,
        execute_request: Any,
        auth_credentials: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Get Google Tasks context snapshot: task lists and overdue/due-today tasks.

        Zero required parameters. Returns task lists and urgent tasks.
        """
        user_id = auth_credentials.get("user_id", "")
        if not user_id:
            raise ValueError("Missing user_id in auth_credentials")

        data = execute_tool(
            "GOOGLETASKS_LIST_ALL_TASKS",
            {"showCompleted": False, "maxResults": 20},
            user_id,
        )
        tasks = data.get("items", data.get("tasks", []))
        today = date.today().strftime("%Y-%m-%d")
        overdue = [t for t in tasks if t.get("due", "9999") < today]
        return {"tasks": tasks, "overdue_tasks": overdue}

    return ["GOOGLETASKS_CUSTOM_GATHER_CONTEXT"]
