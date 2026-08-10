"""Instagram custom tools using Composio custom tool infrastructure."""

from typing import Any

from composio import Composio
from composio.types import ExecuteRequestFn

from app.constants.log_tags import LogTag
from app.models.common_models import GatherContextInput
from app.services.composio.proxy_client import proxy_request_sync
from app.utils.json_helpers import list_bag, text_bag, text_opt_bag
from shared.py.wide_events import log

INSTAGRAM_API_BASE = "https://graph.instagram.com/v18.0"
INSTAGRAM_TOOLKIT = "INSTAGRAM"


def register_instagram_custom_tools(composio: Composio[Any, Any]) -> list[str]:  # type: ignore[explicit-any]
    @composio.tools.custom_tool(toolkit="INSTAGRAM")
    def CUSTOM_GATHER_CONTEXT(
        request: GatherContextInput,
        execute_request: ExecuteRequestFn,
        auth_credentials: dict[str, object],
    ) -> dict[str, object]:
        """Get Instagram context snapshot: profile info and recent media.

        Zero required parameters. Returns authenticated user's Instagram state.
        """
        del request, execute_request  # unused: framework-mandated custom-tool signature
        user_id = text_opt_bag(auth_credentials, "user_id")
        if not user_id:
            raise ValueError("Missing user_id in auth_credentials")

        me_response = proxy_request_sync(
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
        )
        me = me_response if isinstance(me_response, dict) else {}

        recent_media: list[dict[str, object]] = []
        try:
            media_response = proxy_request_sync(
                user_id=user_id,
                toolkit=INSTAGRAM_TOOLKIT,
                endpoint=f"{INSTAGRAM_API_BASE}/me/media",
                method="GET",
                query={
                    "limit": "5",
                    "fields": (
                        "id,caption,media_type,timestamp,like_count,comments_count,permalink"
                    ),
                },
            )
            media_data = media_response if isinstance(media_response, dict) else {}
            recent_media = []
            for m in list_bag(media_data, "data"):
                if not isinstance(m, dict):
                    continue
                recent_media.append(
                    {
                        "id": m.get("id"),
                        "caption": text_bag(m, "caption")[:100],
                        "media_type": m.get("media_type"),
                        "timestamp": m.get("timestamp"),
                        "likes": m.get("like_count", 0),
                        "comments": m.get("comments_count", 0),
                        "permalink": m.get("permalink"),
                    }
                )
        except Exception as e:
            log.warning(
                f"{LogTag.TOOL} Instagram media fetch failed",
                user_id=user_id,
                error_type=type(e).__name__,
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
                "biography": text_bag(me, "biography")[:200],
            },
            "recent_media": recent_media,
        }

    return ["INSTAGRAM_CUSTOM_GATHER_CONTEXT"]
