"""Microsoft Teams tools using Composio custom tool infrastructure."""

from typing import Any

from composio import Composio
from composio.types import ExecuteRequestFn

from app.constants.log_tags import LogTag
from app.models.common_models import GatherContextInput
from app.services.composio.proxy_client import proxy_request_sync
from app.utils.json_helpers import dict_bag, list_bag, text_bag
from shared.py.wide_events import log

TEAMS_TOOLKIT = "MICROSOFT_TEAMS"
GRAPH_API_BASE = "https://graph.microsoft.com/v1.0"


def register_microsoft_teams_custom_tools(composio: Composio[Any, Any]) -> list[str]:
    """Register Microsoft Teams tools as Composio custom tools."""

    @composio.tools.custom_tool(toolkit="MICROSOFT_TEAMS")
    def CUSTOM_GATHER_CONTEXT(
        request: GatherContextInput,
        execute_request: ExecuteRequestFn,
        auth_credentials: dict[str, object],
    ) -> dict[str, object]:
        """Get Microsoft Teams context snapshot: user info, joined teams, and recent chats.

        Zero required parameters. Returns current Teams state for situational awareness.
        """
        del request, execute_request  # unused: framework-mandated custom-tool signature
        log.set(tool={"integration": "microsoft_teams", "action": "gather_context"})
        user_id = auth_credentials.get("user_id")
        if not isinstance(user_id, str) or not user_id:
            raise ValueError("Missing user_id in auth_credentials")

        user_info: dict[str, object] = {}
        try:
            me_response = proxy_request_sync(
                user_id=user_id,
                toolkit=TEAMS_TOOLKIT,
                endpoint=f"{GRAPH_API_BASE}/me",
                method="GET",
                query={"$select": "id,displayName,mail,userPrincipalName"},
            )
            me = me_response if isinstance(me_response, dict) else {}
            user_info = {
                "id": me.get("id"),
                "display_name": me.get("displayName"),
                "email": me.get("mail") or me.get("userPrincipalName"),
            }
        except Exception as e:
            log.debug(f"{LogTag.TOOL} Teams /me fetch failed", error_type=type(e).__name__)

        teams: list[dict[str, object]] = []
        try:
            teams_response = proxy_request_sync(
                user_id=user_id,
                toolkit=TEAMS_TOOLKIT,
                endpoint=f"{GRAPH_API_BASE}/me/joinedTeams",
                method="GET",
                query={"$select": "id,displayName,description"},
            )
            data = teams_response if isinstance(teams_response, dict) else {}
            teams = [
                {
                    "id": t.get("id"),
                    "name": t.get("displayName"),
                    "description": t.get("description"),
                }
                for t in list_bag(data, "value")
                if isinstance(t, dict)
            ]
        except Exception as e:
            log.debug(f"{LogTag.TOOL} Teams joinedTeams fetch failed", error_type=type(e).__name__)

        chats: list[dict[str, object]] = []
        unread_count = 0
        try:
            chats_response = proxy_request_sync(
                user_id=user_id,
                toolkit=TEAMS_TOOLKIT,
                endpoint=f"{GRAPH_API_BASE}/me/chats",
                method="GET",
                query={"$expand": "lastMessagePreview", "$top": 10},
            )
            data = chats_response if isinstance(chats_response, dict) else {}
            raw_chats = list_bag(data, "value")
            unread_count = sum(
                1
                for c in raw_chats
                if isinstance(c, dict)
                and c.get("lastMessagePreview")
                and not dict_bag(c, "lastMessagePreview").get("isRead", True)
            )
            chats = []
            for c in raw_chats:
                if not isinstance(c, dict):
                    continue
                preview = dict_bag(c, "lastMessagePreview")
                chats.append(
                    {
                        "id": c.get("id"),
                        "topic": c.get("topic"),
                        "chat_type": c.get("chatType"),
                        "last_message_preview": (
                            text_bag(dict_bag(preview, "body"), "content")[:100]
                            if c.get("lastMessagePreview")
                            else None
                        ),
                        "is_read": (
                            preview.get("isRead", True) if c.get("lastMessagePreview") else True
                        ),
                    }
                )
        except Exception as e:
            log.debug(f"{LogTag.TOOL} Teams chats fetch failed", error_type=type(e).__name__)

        return {
            "user": user_info,
            "teams": teams,
            "recent_chats": chats,
            "team_count": len(teams),
            "chat_count": len(chats),
            "unread_chat_count": unread_count,
        }

    return ["MICROSOFT_TEAMS_CUSTOM_GATHER_CONTEXT"]
