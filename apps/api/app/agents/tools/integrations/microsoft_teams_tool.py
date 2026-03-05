"""Microsoft Teams tools using Composio custom tool infrastructure."""

from typing import Any, Dict, List

import httpx
from composio import Composio

from app.config.loggers import chat_logger as logger
from app.models.common_models import GatherContextInput


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
        base = "https://graph.microsoft.com/v1.0"

        user_info: Dict[str, Any] = {}
        try:
            resp = httpx.get(
                f"{base}/me",
                headers=headers,
                params={"$select": "id,displayName,mail,userPrincipalName"},
                timeout=15,
            )
            resp.raise_for_status()
            me = resp.json()
            user_info = {
                "id": me.get("id"),
                "display_name": me.get("displayName"),
                "email": me.get("mail") or me.get("userPrincipalName"),
            }
        except Exception as e:
            logger.debug(f"Teams /me fetch failed: {e}")

        teams: List[Dict[str, Any]] = []
        try:
            resp = httpx.get(
                f"{base}/me/joinedTeams",
                headers=headers,
                params={"$select": "id,displayName,description"},
                timeout=15,
            )
            resp.raise_for_status()
            teams = [
                {
                    "id": t.get("id"),
                    "name": t.get("displayName"),
                    "description": t.get("description"),
                }
                for t in resp.json().get("value", [])
            ]
        except Exception as e:
            logger.debug(f"Teams joinedTeams fetch failed: {e}")

        chats: List[Dict[str, Any]] = []
        unread_count = 0
        try:
            resp = httpx.get(
                f"{base}/me/chats",
                headers=headers,
                params={"$expand": "lastMessagePreview", "$top": 10},
                timeout=15,
            )
            resp.raise_for_status()
            raw_chats = resp.json().get("value", [])
            unread_count = sum(
                1
                for c in raw_chats
                if c.get("lastMessagePreview")
                and not c["lastMessagePreview"].get("isRead", True)
            )
            chats = [
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
                for c in raw_chats
            ]
        except Exception as e:
            logger.debug(f"Teams chats fetch failed: {e}")

        return {
            "user": user_info,
            "teams": teams,
            "recent_chats": chats,
            "team_count": len(teams),
            "chat_count": len(chats),
            "unread_chat_count": unread_count,
        }

    return ["MICROSOFT_TEAMS_CUSTOM_GATHER_CONTEXT"]
