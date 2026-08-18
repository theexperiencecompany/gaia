"""Asana tools using Composio custom tool infrastructure."""

from datetime import date
from typing import Any

from composio import Composio
from composio.types import ExecuteRequestFn

from app.models.common_models import GatherContextInput
from app.utils.context_utils import execute_tool
from app.utils.json_helpers import list_bag, text_bag, text_opt_bag


def register_asana_custom_tools(composio: Composio[Any, Any]) -> list[str]:  # type: ignore[explicit-any]
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
        user_id = text_bag(auth_credentials, "user_id")
        if not user_id:
            raise ValueError("Missing user_id in auth_credentials")

        data = execute_tool(
            "ASANA_SEARCH_TASKS_IN_WORKSPACE",
            {"assignee.any": "me", "completed": False, "limit": 10},
            user_id,
        )
        tasks = list_bag(data, "data") or list_bag(data, "tasks")
        today = date.today().strftime("%Y-%m-%d")
        overdue = [
            t
            for t in tasks
            if isinstance(t, dict) and (due_on := text_opt_bag(t, "due_on")) and due_on < today
        ]
        return {"tasks": tasks, "overdue_tasks": overdue}

    return ["ASANA_CUSTOM_GATHER_CONTEXT"]
