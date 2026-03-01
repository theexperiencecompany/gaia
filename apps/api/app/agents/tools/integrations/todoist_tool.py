"""Todoist tools using Composio custom tool infrastructure.

These tools provide Todoist functionality using the access_token from Composio's
auth_credentials. Uses Todoist REST API v2 for all operations.

Note: Errors are raised as exceptions - Composio wraps responses automatically.
"""

from datetime import datetime
from typing import Any, Dict, List

import httpx
from composio import Composio

from app.models.common_models import GatherContextInput

TODOIST_API_BASE = "https://api.todoist.com/rest/v2"

# Reusable sync HTTP client
_http_client = httpx.Client(timeout=30)


def register_todoist_custom_tools(composio: Composio) -> List[str]:
    """Register Todoist tools as Composio custom tools."""

    @composio.tools.custom_tool(toolkit="TODOIST")
    def CUSTOM_GATHER_CONTEXT(
        request: GatherContextInput,
        execute_request: Any,
        auth_credentials: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Get Todoist context snapshot: projects, today's tasks, and overdue tasks.

        Zero required parameters. Returns current task state for situational awareness.
        """
        token = auth_credentials.get("access_token")
        if not token:
            raise ValueError("Missing access_token in auth_credentials")
        headers = {"Authorization": f"Bearer {token}"}

        # Get all projects
        projects_resp = _http_client.get(
            f"{TODOIST_API_BASE}/projects",
            headers=headers,
        )
        projects_resp.raise_for_status()
        projects: List[Dict[str, Any]] = projects_resp.json()

        # Get all active tasks
        tasks_resp = _http_client.get(
            f"{TODOIST_API_BASE}/tasks",
            headers=headers,
        )
        tasks_resp.raise_for_status()
        all_tasks: List[Dict[str, Any]] = tasks_resp.json()

        today_str = datetime.now().date().isoformat()
        today_tasks: List[Dict[str, Any]] = []
        overdue_tasks: List[Dict[str, Any]] = []

        for task in all_tasks:
            due = task.get("due")
            if not due:
                continue
            due_date = due.get("date", "")
            if not due_date:
                continue
            # due_date may be "YYYY-MM-DD" or "YYYY-MM-DDTHH:MM:SS"
            due_day = due_date[:10]
            task_summary = {
                "id": task.get("id"),
                "content": task.get("content", ""),
                "due": due_date,
                "priority": task.get("priority", 1),
            }
            if due_day == today_str:
                today_tasks.append(task_summary)
            elif due_day < today_str:
                overdue_tasks.append(task_summary)

        return {
            "projects": [
                {"id": p.get("id"), "name": p.get("name")} for p in projects[:10]
            ],
            "today_tasks": today_tasks,
            "overdue_tasks": overdue_tasks,
            "project_count": len(projects),
            "today_count": len(today_tasks),
            "overdue_count": len(overdue_tasks),
        }

    return ["TODOIST_CUSTOM_GATHER_CONTEXT"]
