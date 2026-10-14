"""Microsoft Teams tools using Composio custom tool infrastructure."""

from composio import Composio
from composio.types import ExecuteRequestFn

from app.constants.log_tags import LogTag
from app.models.common_models import GatherContextInput
from app.models.integrations.composio import CustomToolAuthCredentials
from app.models.integrations.microsoft_teams import GraphChatsPage, GraphTeamsPage, GraphUser
from app.services.composio.proxy_client import ProxyRequest, proxy_request_sync
from shared.py.wide_events import log

TEAMS_TOOLKIT = "MICROSOFT_TEAMS"
GRAPH_API_BASE = "https://graph.microsoft.com/v1.0"


def register_microsoft_teams_custom_tools(composio: Composio) -> list[str]:
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
        user_id = CustomToolAuthCredentials.parse(auth_credentials).user_id

        user_info: dict[str, str | None] = {}
        try:
            me = GraphUser.model_validate(
                proxy_request_sync(
                    ProxyRequest(
                        user_id=user_id,
                        toolkit=TEAMS_TOOLKIT,
                        endpoint=f"{GRAPH_API_BASE}/me",
                        method="GET",
                        query={"$select": "id,displayName,mail,userPrincipalName"},
                    )
                )
                or {}
            )
            user_info = {
                "id": me.id,
                "display_name": me.displayName,
                "email": me.mail or me.userPrincipalName,
            }
        except Exception as e:
            log.debug(f"{LogTag.TOOL} Teams /me fetch failed", error_type=type(e).__name__)

        teams: list[dict[str, str | None]] = []
        try:
            joined = GraphTeamsPage.model_validate(
                proxy_request_sync(
                    ProxyRequest(
                        user_id=user_id,
                        toolkit=TEAMS_TOOLKIT,
                        endpoint=f"{GRAPH_API_BASE}/me/joinedTeams",
                        method="GET",
                        query={"$select": "id,displayName,description"},
                    )
                )
                or {}
            )
            teams = [
                {
                    "id": t.id,
                    "name": t.displayName,
                    "description": t.description,
                }
                for t in joined.value
            ]
        except Exception as e:
            log.debug(f"{LogTag.TOOL} Teams joinedTeams fetch failed", error_type=type(e).__name__)

        chats: list[dict[str, str | bool | None]] = []
        unread_count = 0
        try:
            raw_chats = GraphChatsPage.model_validate(
                proxy_request_sync(
                    ProxyRequest(
                        user_id=user_id,
                        toolkit=TEAMS_TOOLKIT,
                        endpoint=f"{GRAPH_API_BASE}/me/chats",
                        method="GET",
                        query={"$expand": "lastMessagePreview", "$top": 10},
                    )
                )
                or {}
            ).value
            unread_count = sum(
                1 for c in raw_chats if c.lastMessagePreview and not c.lastMessagePreview.isRead
            )
            chats = [
                {
                    "id": c.id,
                    "topic": c.topic,
                    "chat_type": c.chatType,
                    "last_message_preview": (
                        c.lastMessagePreview.body.content[:100] if c.lastMessagePreview else None
                    ),
                    "is_read": (c.lastMessagePreview.isRead if c.lastMessagePreview else True),
                }
                for c in raw_chats
            ]
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
