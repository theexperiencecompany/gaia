"""Asana tools using Composio custom tool infrastructure.

These tools provide Asana functionality using the access_token from Composio's
auth_credentials. Uses Asana REST API v1 for all operations.

Note: Errors are raised as exceptions - Composio wraps responses automatically.
"""

from typing import Any, Dict, List

import httpx
from composio import Composio

from app.models.common_models import GatherContextInput

ASANA_API_BASE = "https://app.asana.com/api/1.0"

# Reusable sync HTTP client
_http_client = httpx.Client(timeout=30)


def register_asana_custom_tools(composio: Composio) -> List[str]:
    """Register Asana tools as Composio custom tools."""

    @composio.tools.custom_tool(toolkit="ASANA")
    def CUSTOM_GATHER_CONTEXT(
        request: GatherContextInput,
        execute_request: Any,
        auth_credentials: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Get Asana context snapshot: user info, workspaces, and assigned open tasks.

        Zero required parameters. Returns current workspace state for situational awareness.
        """
        token = auth_credentials.get("access_token")
        if not token:
            raise ValueError("Missing access_token in auth_credentials")
        headers = {"Authorization": f"Bearer {token}"}

        # Get current user and workspaces
        me_resp = _http_client.get(
            f"{ASANA_API_BASE}/users/me",
            headers=headers,
            params={"opt_fields": "gid,name,email,workspaces.gid,workspaces.name"},
        )
        me_resp.raise_for_status()
        me_data = me_resp.json().get("data", {})

        workspaces = me_data.get("workspaces", [])
        workspace_gid = workspaces[0].get("gid") if workspaces else None

        # Get open tasks assigned to current user in first workspace
        tasks: List[Dict[str, Any]] = []
        if workspace_gid:
            tasks_resp = _http_client.get(
                f"{ASANA_API_BASE}/tasks",
                headers=headers,
                params={
                    "assignee": "me",
                    "workspace": workspace_gid,
                    "completed_since": "now",
                    "opt_fields": "gid,name,due_on,completed",
                    "limit": 15,
                },
            )
            tasks_resp.raise_for_status()
            tasks_data = tasks_resp.json()
            tasks = [
                {
                    "gid": t.get("gid"),
                    "name": t.get("name"),
                    "due_on": t.get("due_on"),
                }
                for t in tasks_data.get("data", [])
            ]

        return {
            "user": {
                "gid": me_data.get("gid"),
                "name": me_data.get("name"),
                "email": me_data.get("email"),
            },
            "workspaces": [
                {"gid": w.get("gid"), "name": w.get("name")} for w in workspaces
            ],
            "my_open_tasks": tasks,
            "task_count": len(tasks),
        }

    return ["ASANA_CUSTOM_GATHER_CONTEXT"]
