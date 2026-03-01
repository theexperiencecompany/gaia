"""Google Tasks custom tools using Composio custom tool infrastructure."""

import datetime
from typing import Any, Dict, List

import httpx
from app.models.common_models import GatherContextInput
from composio import Composio

_http_client = httpx.Client(timeout=30)

TASKS_API_BASE = "https://tasks.googleapis.com/tasks/v1"


def register_google_tasks_custom_tools(composio: Composio) -> List[str]:
    @composio.tools.custom_tool(toolkit="GOOGLETASKS")
    def CUSTOM_GATHER_CONTEXT(
        request: GatherContextInput,
        execute_request: Any,
        auth_credentials: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Get Google Tasks context snapshot: task lists and overdue/due-today tasks.

        Zero required parameters. Returns task lists and urgent tasks.
        """
        token = auth_credentials.get("access_token")
        if not token:
            raise ValueError("Missing access_token in auth_credentials")

        headers = {
            "Authorization": f"Bearer {token}",
            "Accept": "application/json",
        }

        # Get task lists
        lists_resp = _http_client.get(
            f"{TASKS_API_BASE}/users/@me/lists", headers=headers
        )
        lists_resp.raise_for_status()
        lists_data = lists_resp.json()
        task_lists = [
            {"id": lst.get("id"), "title": lst.get("title")}
            for lst in lists_data.get("items", [])
        ]

        # Get tasks from all lists (up to 3 lists), filter overdue/due today
        today = datetime.date.today().isoformat()
        urgent_tasks: List[Dict[str, Any]] = []

        for task_list in task_lists[:3]:
            tasks_resp = _http_client.get(
                f"{TASKS_API_BASE}/lists/{task_list['id']}/tasks",
                headers=headers,
                params={
                    "showCompleted": "false",
                    "showHidden": "false",
                    "maxResults": 20,
                },
            )
            if tasks_resp.status_code != 200:
                continue
            for task in tasks_resp.json().get("items", []):
                due = task.get("due", "")
                if due and due[:10] <= today:
                    urgent_tasks.append(
                        {
                            "id": task.get("id"),
                            "title": task.get("title", "")[:100],
                            "due": due[:10],
                            "list": task_list["title"],
                            "overdue": due[:10] < today,
                        }
                    )

        return {
            "task_lists": task_lists,
            "list_count": len(task_lists),
            "urgent_tasks": urgent_tasks,
            "urgent_task_count": len(urgent_tasks),
        }

    return ["GOOGLETASKS_CUSTOM_GATHER_CONTEXT"]
