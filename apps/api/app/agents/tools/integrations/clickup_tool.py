"""ClickUp tools using Composio custom tool infrastructure.

These tools provide ClickUp functionality using the access_token from Composio's
auth_credentials. Uses ClickUp API v2 for all operations.

Note: Errors are raised as exceptions - Composio wraps responses automatically.
Note: ClickUp API uses the token directly (no "Bearer" prefix) in Authorization header.
"""

from typing import Any, Dict, List

import httpx
from composio import Composio

from app.models.common_models import GatherContextInput

from app.config.loggers import chat_logger as logger

CLICKUP_API_BASE = "https://api.clickup.com/api/v2"

# Reusable sync HTTP client
_http_client = httpx.Client(timeout=30)


def register_clickup_custom_tools(composio: Composio) -> List[str]:
    """Register ClickUp tools as Composio custom tools."""

    @composio.tools.custom_tool(toolkit="CLICKUP")
    def CUSTOM_GATHER_CONTEXT(
        request: GatherContextInput,
        execute_request: Any,
        auth_credentials: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Get ClickUp context snapshot: user info and workspaces (teams).

        Zero required parameters. Returns current account state for situational awareness.
        """
        token = auth_credentials.get("access_token")
        if not token:
            raise ValueError("Missing access_token in auth_credentials")
        # ClickUp uses token directly, not Bearer
        headers = {"Authorization": token}

        # Get current user
        user_resp = _http_client.get(
            f"{CLICKUP_API_BASE}/user",
            headers=headers,
        )
        user_resp.raise_for_status()
        user_data = user_resp.json().get("user", {})

        # Get teams (workspaces)
        teams_resp = _http_client.get(
            f"{CLICKUP_API_BASE}/team",
            headers=headers,
        )
        teams_resp.raise_for_status()
        teams_data = teams_resp.json()
        teams: List[Dict[str, Any]] = teams_data.get("teams", [])

        # Get spaces for the first team and task counts per space
        spaces: List[Dict[str, Any]] = []
        if teams:
            first_team_id = teams[0].get("id")
            try:
                spaces_resp = _http_client.get(
                    f"{CLICKUP_API_BASE}/team/{first_team_id}/space",
                    headers=headers,
                    params={"archived": "false"},
                )
                spaces_resp.raise_for_status()
                raw_spaces: List[Dict[str, Any]] = spaces_resp.json().get("spaces", [])
                for space in raw_spaces[:3]:
                    space_id = space.get("id")
                    task_count = 0
                    try:
                        tasks_resp = _http_client.get(
                            f"{CLICKUP_API_BASE}/space/{space_id}/task",
                            headers=headers,
                            params={
                                "archived": "false",
                                "subtasks": "true",
                                "include_closed": "false",
                            },
                        )
                        tasks_resp.raise_for_status()
                        tasks_data = tasks_resp.json().get("tasks", [])
                        task_count = len(tasks_data)
                    except Exception as e:
                        logger.debug(
                            "Failed to fetch task count for space %s: %s", space_id, e
                        )
                    spaces.append(
                        {
                            "id": space_id,
                            "name": space.get("name"),
                            "task_count": task_count,
                        }
                    )
            except Exception:
                spaces = []

        return {
            "user": {
                "id": user_data.get("id"),
                "username": user_data.get("username"),
                "email": user_data.get("email"),
                "color": user_data.get("color"),
            },
            "teams": [{"id": t.get("id"), "name": t.get("name")} for t in teams],
            "team_count": len(teams),
            "spaces": [
                {
                    "id": s.get("id"),
                    "name": s.get("name"),
                    "task_count": s.get("task_count", 0),
                }
                for s in spaces
            ],
            "open_task_count": sum(s.get("task_count", 0) for s in spaces),
        }

    return ["CLICKUP_CUSTOM_GATHER_CONTEXT"]
