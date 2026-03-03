"""Reddit custom tools using Composio custom tool infrastructure."""

from typing import Any, Dict, List

import httpx
from app.models.common_models import GatherContextInput
from composio import Composio

_http_client = httpx.Client(timeout=30)

REDDIT_API_BASE = "https://oauth.reddit.com"


def register_reddit_custom_tools(composio: Composio) -> List[str]:
    @composio.tools.custom_tool(toolkit="REDDIT")
    def CUSTOM_GATHER_CONTEXT(
        request: GatherContextInput,
        execute_request: Any,
        auth_credentials: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Get Reddit context snapshot: user profile, subscribed subreddits, and unread messages.

        Zero required parameters. Returns authenticated user's Reddit state.
        """
        token = auth_credentials.get("access_token")
        if not token:
            raise ValueError("Missing access_token in auth_credentials")

        headers = {
            "Authorization": f"Bearer {token}",
            "User-Agent": "GAIA/1.0",
            "Accept": "application/json",
        }

        # Get current user profile
        me_resp = _http_client.get(f"{REDDIT_API_BASE}/api/v1/me", headers=headers)
        me_resp.raise_for_status()
        me = me_resp.json()

        # Get subscribed subreddits (top 5)
        subs_resp = _http_client.get(
            f"{REDDIT_API_BASE}/subreddits/mine/subscriber",
            headers=headers,
            params={"limit": 5},
        )
        subreddits: List[Dict[str, Any]] = []
        if subs_resp.status_code == 200:
            children = subs_resp.json().get("data", {}).get("children", [])
            subreddits = [
                {
                    "name": c["data"].get("display_name"),
                    "title": c["data"].get("title", "")[:80],
                    "subscribers": c["data"].get("subscribers", 0),
                }
                for c in children
            ]

        # Get unread messages
        messages_resp = _http_client.get(
            f"{REDDIT_API_BASE}/message/unread",
            headers=headers,
            params={"limit": 5},
        )
        unread_messages: List[Dict[str, Any]] = []
        if messages_resp.status_code == 200:
            children = messages_resp.json().get("data", {}).get("children", [])
            unread_messages = [
                {
                    "id": c["data"].get("id"),
                    "subject": c["data"].get("subject", "")[:80],
                    "author": c["data"].get("author"),
                    "created_utc": c["data"].get("created_utc"),
                }
                for c in children
            ]

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
