"""Instagram custom tools using Composio custom tool infrastructure."""

from typing import Any, Dict, List

import httpx
from app.models.common_models import GatherContextInput
from composio import Composio

_http_client = httpx.Client(timeout=30)

INSTAGRAM_API_BASE = "https://graph.instagram.com/v18.0"


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
        token = auth_credentials.get("access_token")
        if not token:
            raise ValueError("Missing access_token in auth_credentials")

        params = {"access_token": token}

        # Get user profile
        me_resp = _http_client.get(
            f"{INSTAGRAM_API_BASE}/me",
            params={
                **params,
                "fields": "id,name,username,account_type,media_count,followers_count,follows_count,biography",
            },
        )
        me_resp.raise_for_status()
        me = me_resp.json()

        # Get recent media
        media_resp = _http_client.get(
            f"{INSTAGRAM_API_BASE}/me/media",
            params={
                **params,
                "limit": "5",
                "fields": "id,caption,media_type,timestamp,like_count,comments_count,permalink",
            },
        )
        recent_media: List[Dict[str, Any]] = []
        if media_resp.status_code == 200:
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
                for m in media_resp.json().get("data", [])
            ]

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
