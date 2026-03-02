"""ClickUp tools using Composio custom tool infrastructure."""

from datetime import datetime, timezone
from typing import Any, Dict, List

from composio import Composio

from app.models.common_models import GatherContextInput
from app.utils.context_utils import execute_tool


def register_clickup_custom_tools(composio: Composio) -> List[str]:
    """Register ClickUp tools as Composio custom tools."""

    @composio.tools.custom_tool(toolkit="CLICKUP")
    def CUSTOM_GATHER_CONTEXT(
        request: GatherContextInput,
        execute_request: Any,
        auth_credentials: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Get ClickUp context snapshot: assigned tasks across teams.

        Zero required parameters. Returns current account state for situational awareness.
        """
        user_id = auth_credentials.get("user_id", "")
        if not user_id:
            raise ValueError("Missing user_id in auth_credentials")

        data = execute_tool(
            "CLICKUP_GET_FILTERED_TEAM_TASKS",
            {"assignees": ["me"], "include_closed": False},
            user_id,
        )
        tasks = data.get("tasks", [])
        today_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
        overdue = [
            t
            for t in tasks
            if t.get("due_date")
            and int(t["due_date"]) < today_ms
            and t.get("status", {}).get("type") not in ("closed",)
        ]
        return {"tasks": tasks, "overdue_tasks": overdue}

    return ["CLICKUP_CUSTOM_GATHER_CONTEXT"]
