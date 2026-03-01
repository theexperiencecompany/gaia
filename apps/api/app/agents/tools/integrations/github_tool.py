"""GitHub tools using Composio custom tool infrastructure.

These tools provide GitHub functionality using the access_token from Composio's
auth_credentials. Uses GitHub REST API v3 for all operations.

Note: Errors are raised as exceptions - Composio wraps responses automatically.
"""

from typing import Any, Dict, List

import httpx
from composio import Composio

from app.models.common_models import GatherContextInput

GITHUB_API_BASE = "https://api.github.com"

# Reusable sync HTTP client
_http_client = httpx.Client(timeout=30)


def register_github_custom_tools(composio: Composio) -> List[str]:
    """Register GitHub tools as Composio custom tools."""

    @composio.tools.custom_tool(toolkit="GITHUB")
    def CUSTOM_GATHER_CONTEXT(
        request: GatherContextInput,
        execute_request: Any,
        auth_credentials: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Get GitHub context snapshot: user info, open PRs assigned, and notifications.

        Zero required parameters. Returns current GitHub state for situational awareness.
        """
        token = auth_credentials.get("access_token")
        if not token:
            raise ValueError("Missing access_token in auth_credentials")
        headers = {
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }

        # Get authenticated user
        user_resp = _http_client.get(
            f"{GITHUB_API_BASE}/user",
            headers=headers,
        )
        user_resp.raise_for_status()
        user_data = user_resp.json()
        login = user_data.get("login", "")

        # Get open PRs assigned to user
        prs_resp = _http_client.get(
            f"{GITHUB_API_BASE}/search/issues",
            headers=headers,
            params={"q": f"is:pr is:open assignee:{login}", "per_page": 10},
        )
        prs_resp.raise_for_status()
        prs_data = prs_resp.json()
        prs = prs_data.get("items", [])

        # Get unread notifications
        notifs_params: Dict[str, Any] = {"per_page": 10, "all": "false"}
        if request.since:
            notifs_params["since"] = request.since
        notifs_resp = _http_client.get(
            f"{GITHUB_API_BASE}/notifications",
            headers=headers,
            params=notifs_params,
        )
        notifs_resp.raise_for_status()
        notifs_raw = notifs_resp.json()
        notifications: List[Dict[str, Any]] = (
            notifs_raw if isinstance(notifs_raw, list) else []
        )

        return {
            "user": {
                "login": user_data.get("login"),
                "name": user_data.get("name"),
                "public_repos": user_data.get("public_repos"),
                "followers": user_data.get("followers"),
            },
            "open_prs_assigned": [
                {
                    "number": p.get("number"),
                    "title": p.get("title"),
                    "repo": p.get("repository_url", "").split("/repos/")[-1],
                    "url": p.get("html_url"),
                }
                for p in prs[:5]
            ],
            "unread_notification_count": len(
                [n for n in notifications if n.get("unread", False)]
            ),
            "recent_notifications": [
                {
                    "subject": n.get("subject", {}).get("title"),
                    "type": n.get("subject", {}).get("type"),
                    "repo": n.get("repository", {}).get("full_name"),
                }
                for n in notifications[:5]
            ],
        }

    return ["GITHUB_CUSTOM_GATHER_CONTEXT"]
