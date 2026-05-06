"""Instagram custom tools using Composio custom tool infrastructure."""

from typing import Any, Dict, List

from shared.py.wide_events import log
from app.models.common_models import GatherContextInput
from app.services.composio.proxy_client import proxy_request_sync
from composio import Composio

INSTAGRAM_API_BASE = "https://graph.instagram.com/v18.0"
INSTAGRAM_TOOLKIT = "INSTAGRAM"


def register_instagram_custom_tools(composio: Composio) -> List[str]:
    @composio.tools.custom_tool(toolkit="INSTAGRAM")
    def CUSTOM_GATHER_CONTEXT(
        request: GatherContextInput,
        execute_request: Any,
        auth_credentials: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Get Instagram context snapshot: profile info and recent media.

        Zero required parameters. Returns authenticated user's Instagram state.
        """
        user_id = auth_credentials.get("user_id")
        if not user_id:
            raise ValueError("Missing user_id in auth_credentials")

        me = proxy_request_sync(
            user_id=user_id,
            toolkit=INSTAGRAM_TOOLKIT,
            endpoint=f"{INSTAGRAM_API_BASE}/me",
            method="GET",
            query={
                "fields": (
                    "id,name,username,account_type,media_count,"
                    "followers_count,follows_count,biography"
                ),
            },
        ) or {}

        recent_media: List[Dict[str, Any]] = []
        try:
            media_data = proxy_request_sync(
                user_id=user_id,
                toolkit=INSTAGRAM_TOOLKIT,
                endpoint=f"{INSTAGRAM_API_BASE}/me/media",
                method="GET",
                query={
                    "limit": "5",
                    "fields": (
                        "id,caption,media_type,timestamp,like_count,"
                        "comments_count,permalink"
                    ),
                },
            ) or {}
            recent_media = [
                {
                    "id": m.get("id"),
                    "caption": (m.get("caption") or "")[:100],
                    "media_type": m.get("media_type"),
                    "timestamp": m.get("timestamp"),
                    "likes": m.get("like_count", 0),
                    "comments": m.get("comments_count", 0),
                    "permalink": m.get("permalink"),
                }
                for m in media_data.get("data", [])
            ]
        except Exception as e:
            log.warning(
                f"Instagram media fetch failed for user {user_id}: {e}"
            )

        return {
            "user": {
                "id": me.get("id"),
                "name": me.get("name"),
                "username": me.get("username"),
                "account_type": me.get("account_type"),
                "media_count": me.get("media_count", 0),
                "followers": me.get("followers_count", 0),
                "following": me.get("follows_count", 0),
                "biography": (me.get("biography") or "")[:200],
            },
            "recent_media": recent_media,
        }

    return ["INSTAGRAM_CUSTOM_GATHER_CONTEXT"]
