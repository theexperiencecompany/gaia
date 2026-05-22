"""Reddit custom tools using Composio custom tool infrastructure."""

from typing import Any

from composio import Composio

from app.models.common_models import GatherContextInput
from app.services.composio.proxy_client import proxy_request_sync
from app.utils.errors import AppError
from shared.py.wide_events import log

REDDIT_API_BASE = "https://oauth.reddit.com"
REDDIT_TOOLKIT = "REDDIT"
_REDDIT_HEADERS = {"User-Agent": "GAIA/1.0"}


def register_reddit_custom_tools(composio: Composio) -> list[str]:
    @composio.tools.custom_tool(toolkit="REDDIT")
    def CUSTOM_GATHER_CONTEXT(
        request: GatherContextInput,
        execute_request: Any,
        auth_credentials: dict[str, Any],
    ) -> dict[str, Any]:
        """Get Reddit context snapshot: user profile, subscribed subreddits, and unread messages.

        Zero required parameters. Returns authenticated user's Reddit state.
        """
        user_id = auth_credentials.get("user_id")
        if not user_id:
            raise AppError(
                message="Missing user_id in auth_credentials",
                why="CUSTOM_GATHER_CONTEXT requires a user-scoped auth context",
                status_code=500,
            )

        me: dict[str, Any] = {}
        try:
            me = (
                proxy_request_sync(
                    user_id=user_id,
                    toolkit=REDDIT_TOOLKIT,
                    endpoint=f"{REDDIT_API_BASE}/api/v1/me",
                    method="GET",
                    headers=_REDDIT_HEADERS,
                )
                or {}
            )
        except Exception as e:
            log.set(
                user_id=user_id, endpoint=f"{REDDIT_API_BASE}/api/v1/me", toolkit=REDDIT_TOOLKIT
            )
            log.error("Reddit /me fetch failed", exc=e)

        subreddits: list[dict[str, Any]] = []
        try:
            subs_data = (
                proxy_request_sync(
                    user_id=user_id,
                    toolkit=REDDIT_TOOLKIT,
                    endpoint=f"{REDDIT_API_BASE}/subreddits/mine/subscriber",
                    method="GET",
                    query={"limit": 5},
                    headers=_REDDIT_HEADERS,
                )
                or {}
            )
            children = subs_data.get("data", {}).get("children", [])
            subreddits = [
                {
                    "name": c["data"].get("display_name"),
                    "title": c["data"].get("title", "")[:80],
                    "subscribers": c["data"].get("subscribers", 0),
                }
                for c in children
            ]
        except Exception as e:
            log.set(
                user_id=user_id,
                endpoint=f"{REDDIT_API_BASE}/subreddits/mine/subscriber",
                toolkit=REDDIT_TOOLKIT,
            )
            log.error("Reddit subreddits fetch failed", exc=e)

        unread_messages: list[dict[str, Any]] = []
        try:
            messages_data = (
                proxy_request_sync(
                    user_id=user_id,
                    toolkit=REDDIT_TOOLKIT,
                    endpoint=f"{REDDIT_API_BASE}/message/unread",
                    method="GET",
                    query={"limit": 5},
                    headers=_REDDIT_HEADERS,
                )
                or {}
            )
            children = messages_data.get("data", {}).get("children", [])
            unread_messages = [
                {
                    "id": c["data"].get("id"),
                    "subject": c["data"].get("subject", "")[:80],
                    "author": c["data"].get("author"),
                    "created_utc": c["data"].get("created_utc"),
                }
                for c in children
            ]
        except Exception as e:
            log.set(
                user_id=user_id,
                endpoint=f"{REDDIT_API_BASE}/message/unread",
                toolkit=REDDIT_TOOLKIT,
            )
            log.error("Reddit unread messages fetch failed", exc=e)

        return {
            "user": {
                "name": me.get("name"),
                "id": me.get("id"),
                "link_karma": me.get("link_karma", 0),
                "comment_karma": me.get("comment_karma", 0),
                "total_karma": me.get("total_karma", 0),
                "icon_img": me.get("icon_img"),
                "is_gold": me.get("is_gold", False),
            },
            "subscribed_subreddits": subreddits,
            "unread_messages": unread_messages,
            "unread_message_count": len(unread_messages),
        }

    return ["REDDIT_CUSTOM_GATHER_CONTEXT"]
