"""Microsoft Teams tools using Composio custom tool infrastructure.

These tools provide Microsoft Teams functionality using the access_token from Composio's
auth_credentials. Uses Microsoft Graph API v1.0 for all operations.

Note: Errors are raised as exceptions - Composio wraps responses automatically.
"""

from typing import Any, Dict, List

import httpx
from composio import Composio

from app.models.common_models import GatherContextInput

GRAPH_API_BASE = "https://graph.microsoft.com/v1.0"

# Reusable sync HTTP client
_http_client = httpx.Client(timeout=30)


def register_microsoft_teams_custom_tools(composio: Composio) -> List[str]:
    """Register Microsoft Teams tools as Composio custom tools."""

    @composio.tools.custom_tool(toolkit="MICROSOFT_TEAMS")
    def CUSTOM_GATHER_CONTEXT(
        request: GatherContextInput,
        execute_request: Any,
        auth_credentials: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Get Microsoft Teams context snapshot: user info, joined teams, and recent chats.

        Zero required parameters. Returns current Teams state for situational awareness.
        """
        token = auth_credentials.get("access_token")
        if not token:
            raise ValueError("Missing access_token in auth_credentials")
        headers = {"Authorization": f"Bearer {token}"}

        # Get current user profile
        me_resp = _http_client.get(
            f"{GRAPH_API_BASE}/me",
            headers=headers,
            params={"$select": "id,displayName,mail,userPrincipalName"},
        )
        me_resp.raise_for_status()
        me_data = me_resp.json()

        # Get joined teams
        teams_resp = _http_client.get(
            f"{GRAPH_API_BASE}/me/joinedTeams",
            headers=headers,
            params={"$select": "id,displayName,description"},
        )
        teams_resp.raise_for_status()
        teams_data = teams_resp.json()
        teams: List[Dict[str, Any]] = teams_data.get("value", [])

        # Get recent chats with last message preview for unread detection
        chats_resp = _http_client.get(
            f"{GRAPH_API_BASE}/me/chats",
            headers=headers,
            params={"$expand": "lastMessagePreview", "$top": 5},
        )
        chats_resp.raise_for_status()
        chats_data = chats_resp.json()
        chats: List[Dict[str, Any]] = chats_data.get("value", [])

        unread_count = sum(
            1
            for c in chats
            if c.get("lastMessagePreview")
            and not c["lastMessagePreview"].get("isRead", True)
        )

        return {
            "user": {
                "id": me_data.get("id"),
                "display_name": me_data.get("displayName"),
                "email": me_data.get("mail") or me_data.get("userPrincipalName"),
            },
            "teams": [
                {
                    "id": t.get("id"),
                    "name": t.get("displayName"),
                    "description": t.get("description"),
                }
                for t in teams
            ],
            "recent_chats": [
                {
                    "id": c.get("id"),
                    "topic": c.get("topic"),
                    "chat_type": c.get("chatType"),
                    "last_message_preview": (
                        c["lastMessagePreview"].get("body", {}).get("content", "")[:100]
                        if c.get("lastMessagePreview")
                        else None
                    ),
                    "is_read": (
                        c["lastMessagePreview"].get("isRead", True)
                        if c.get("lastMessagePreview")
                        else True
                    ),
                }
                for c in chats
            ],
            "team_count": len(teams),
            "chat_count": len(chats),
            "unread_chat_count": unread_count,
        }

    return ["MICROSOFT_TEAMS_CUSTOM_GATHER_CONTEXT"]
