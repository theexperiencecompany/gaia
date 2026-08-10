"""ClickUp tools using Composio custom tool infrastructure."""

from datetime import UTC, datetime
from typing import Any

from composio import Composio
from composio.types import ExecuteRequestFn

from app.models.common_models import GatherContextInput
from app.utils.context_utils import execute_tool
from app.utils.json_helpers import dict_bag, list_bag, text_bag, text_opt_bag


def register_clickup_custom_tools(composio: Composio[Any, Any]) -> list[str]:  # type: ignore[explicit-any]
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
        user_id = text_bag(auth_credentials, "user_id")
        if not user_id:
            raise ValueError("Missing user_id in auth_credentials")

        data = execute_tool(
            "CLICKUP_GET_FILTERED_TEAM_TASKS",
            {"assignees": ["me"], "include_closed": False},
            user_id,
        )
        tasks = list_bag(data, "tasks")
        today_ms = int(datetime.now(UTC).timestamp() * 1000)
        overdue = [
            t
            for t in tasks
            if isinstance(t, dict)
            if t.get("due_date")
            and int(t["due_date"]) < today_ms
            and text_opt_bag(dict_bag(t, "status"), "type") not in ("closed",)
        ]
        return {"tasks": tasks, "overdue_tasks": overdue}

    return ["CLICKUP_CUSTOM_GATHER_CONTEXT"]
