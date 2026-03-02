"""Asana tools using Composio custom tool infrastructure."""

from datetime import date
from typing import Any, Dict, List

from composio import Composio

from app.models.common_models import GatherContextInput
from app.utils.context_utils import execute_tool


def register_asana_custom_tools(composio: Composio) -> List[str]:
    """Register Asana tools as Composio custom tools."""

    @composio.tools.custom_tool(toolkit="ASANA")
    def CUSTOM_GATHER_CONTEXT(
        request: GatherContextInput,
        execute_request: Any,
        auth_credentials: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Get Asana context snapshot: assigned open tasks across workspaces.

        Zero required parameters. Returns current workspace state for situational awareness.
        """
        user_id = auth_credentials.get("user_id", "")
        if not user_id:
            raise ValueError("Missing user_id in auth_credentials")

        data = execute_tool(
            "ASANA_SEARCH_TASKS_IN_WORKSPACE",
            {"assignee.any": "me", "completed": False, "limit": 10},
            user_id,
        )
        tasks = data.get("data", data.get("tasks", []))
        today = date.today().strftime("%Y-%m-%d")
        overdue = [t for t in tasks if t.get("due_on") and t["due_on"] < today]
        return {"tasks": tasks, "overdue_tasks": overdue}

    return ["ASANA_CUSTOM_GATHER_CONTEXT"]
