"""Todoist tools using Composio custom tool infrastructure."""

from datetime import date
from typing import Any, Dict, List

from composio import Composio

from app.models.common_models import GatherContextInput
from app.utils.context_utils import execute_tool


def register_todoist_custom_tools(composio: Composio) -> List[str]:
    """Register Todoist tools as Composio custom tools."""

    @composio.tools.custom_tool(toolkit="TODOIST")
    def CUSTOM_GATHER_CONTEXT(
        request: GatherContextInput,
        execute_request: Any,
        auth_credentials: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Get Todoist context snapshot: tasks and overdue items.

        Zero required parameters. Returns current task state for situational awareness.
        """
        user_id = auth_credentials.get("user_id", "")
        if not user_id:
            raise ValueError("Missing user_id in auth_credentials")

        data = execute_tool("TODOIST_GET_ALL_TASKS", {}, user_id)
        tasks = (
            data.get("items", data.get("tasks", data))
            if isinstance(data, dict)
            else data
        )
        if not isinstance(tasks, list):
            tasks = []
        today = date.today().strftime("%Y-%m-%d")
        overdue = [
            t
            for t in tasks
            if isinstance(t.get("due"), dict) and t["due"].get("date", "9999") < today
        ]
        return {"tasks": tasks, "overdue_tasks": overdue}

    return ["TODOIST_CUSTOM_GATHER_CONTEXT"]
