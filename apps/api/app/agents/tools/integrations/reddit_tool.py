"""Reddit custom tools using Composio custom tool infrastructure."""

from typing import Any

from composio import Composio
from composio.types import ExecuteRequestFn

from app.constants.log_tags import LogTag
from app.models.common_models import GatherContextInput
from app.services.composio.proxy_client import proxy_request_sync
from app.utils.errors import AppError
from app.utils.json_helpers import dict_bag, list_bag, text_bag, text_opt_bag
from shared.py.wide_events import log

REDDIT_API_BASE = "https://oauth.reddit.com"
REDDIT_TOOLKIT = "REDDIT"
_REDDIT_HEADERS = {"User-Agent": "GAIA/1.0"}


def register_reddit_custom_tools(composio: Composio[Any, Any]) -> list[str]:  # type: ignore[explicit-any]
    @composio.tools.custom_tool(toolkit="REDDIT")
    def CUSTOM_GATHER_CONTEXT(
        request: GatherContextInput,
        execute_request: ExecuteRequestFn,
        auth_credentials: dict[str, object],
    ) -> dict[str, object]:
        """Get Reddit context snapshot: user profile, subscribed subreddits, and unread messages.

        Zero required parameters. Returns authenticated user's Reddit state.
        """
        del request, execute_request  # unused: framework-mandated custom-tool signature
        user_id = text_opt_bag(auth_credentials, "user_id")
        if not user_id:
            raise AppError(
                message="Missing user_id in auth_credentials",
                why="CUSTOM_GATHER_CONTEXT requires a user-scoped auth context",
                status_code=500,
            )

        me: dict[str, object] = {}
        try:
            me_response = proxy_request_sync(
                user_id=user_id,
                toolkit=REDDIT_TOOLKIT,
                endpoint=f"{REDDIT_API_BASE}/api/v1/me",
                method="GET",
                headers=_REDDIT_HEADERS,
            )
            if isinstance(me_response, dict):
                me = me_response
        except Exception as e:
            log.set(
                user_id=user_id, endpoint=f"{REDDIT_API_BASE}/api/v1/me", toolkit=REDDIT_TOOLKIT
            )
            log.error(f"{LogTag.TOOL} Reddit /me fetch failed", exc=e)

        subreddits: list[dict[str, object]] = []
        try:
            subs_response = proxy_request_sync(
                user_id=user_id,
                toolkit=REDDIT_TOOLKIT,
                endpoint=f"{REDDIT_API_BASE}/subreddits/mine/subscriber",
                method="GET",
                query={"limit": 5},
                headers=_REDDIT_HEADERS,
            )
            subs_data = subs_response if isinstance(subs_response, dict) else {}
            subreddits = []
            for c in list_bag(dict_bag(subs_data, "data"), "children"):
                if not isinstance(c, dict):
                    continue
                child_data = dict_bag(c, "data")
                if not child_data:
                    continue
                subreddits.append(
                    {
                        "name": child_data.get("display_name"),
                        "title": text_bag(child_data, "title", "")[:80],
                        "subscribers": child_data.get("subscribers", 0),
                    }
                )
        except Exception as e:
            log.set(
                user_id=user_id,
                endpoint=f"{REDDIT_API_BASE}/subreddits/mine/subscriber",
                toolkit=REDDIT_TOOLKIT,
            )
            log.error(f"{LogTag.TOOL} Reddit subreddits fetch failed", exc=e)

        unread_messages: list[dict[str, object]] = []
        try:
            messages_response = proxy_request_sync(
                user_id=user_id,
                toolkit=REDDIT_TOOLKIT,
                endpoint=f"{REDDIT_API_BASE}/message/unread",
                method="GET",
                query={"limit": 5},
                headers=_REDDIT_HEADERS,
            )
            messages_data = messages_response if isinstance(messages_response, dict) else {}
            unread_messages = []
            for c in list_bag(dict_bag(messages_data, "data"), "children"):
                if not isinstance(c, dict):
                    continue
                child_data = dict_bag(c, "data")
                if not child_data:
                    continue
                unread_messages.append(
                    {
                        "id": child_data.get("id"),
                        "subject": text_bag(child_data, "subject", "")[:80],
                        "author": child_data.get("author"),
                        "created_utc": child_data.get("created_utc"),
                    }
                )
        except Exception as e:
            log.set(
                user_id=user_id,
                endpoint=f"{REDDIT_API_BASE}/message/unread",
                toolkit=REDDIT_TOOLKIT,
            )
            log.error(f"{LogTag.TOOL} Reddit unread messages fetch failed", exc=e)

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
