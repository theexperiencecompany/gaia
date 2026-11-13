"""Reddit custom tools using Composio custom tool infrastructure."""

from composio import Composio
from composio.types import ExecuteRequestFn

from app.constants.log_tags import LogTag
from app.models.common_models import GatherContextInput
from app.models.integrations.composio import CustomToolAuthCredentials
from app.models.integrations.reddit import (
    RedditAccount,
    RedditMessage,
    RedditMessageListing,
    RedditSubreddit,
    RedditSubredditListing,
)
from app.services.composio.proxy_client import ProxyRequest, proxy_request_sync
from app.utils.errors import AppError
from shared.py.wide_events import log

REDDIT_API_BASE = "https://oauth.reddit.com"
REDDIT_TOOLKIT = "REDDIT"
_REDDIT_HEADERS = {"User-Agent": "GAIA/1.0"}


def register_reddit_custom_tools(composio: Composio) -> list[str]:
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
        try:
            user_id = CustomToolAuthCredentials.parse(auth_credentials).user_id
        except ValueError as e:
            raise AppError(
                message=str(e),
                why="CUSTOM_GATHER_CONTEXT requires a user-scoped auth context",
                status_code=500,
            ) from e

        me: RedditAccount | None = None
        try:
            me = RedditAccount.model_validate(
                proxy_request_sync(
                    ProxyRequest(
                        user_id=user_id,
                        toolkit=REDDIT_TOOLKIT,
                        endpoint=f"{REDDIT_API_BASE}/api/v1/me",
                        method="GET",
                        headers=_REDDIT_HEADERS,
                    )
                )
            )
        except Exception as e:
            log.set(
                user_id=user_id, endpoint=f"{REDDIT_API_BASE}/api/v1/me", toolkit=REDDIT_TOOLKIT
            )
            log.error(f"{LogTag.TOOL} Reddit /me fetch failed", exc=e)

        subreddits: list[RedditSubreddit] = []
        try:
            subreddits = RedditSubredditListing.model_validate(
                proxy_request_sync(
                    ProxyRequest(
                        user_id=user_id,
                        toolkit=REDDIT_TOOLKIT,
                        endpoint=f"{REDDIT_API_BASE}/subreddits/mine/subscriber",
                        method="GET",
                        query={"limit": 5},
                        headers=_REDDIT_HEADERS,
                    )
                )
            ).things
        except Exception as e:
            log.set(
                user_id=user_id,
                endpoint=f"{REDDIT_API_BASE}/subreddits/mine/subscriber",
                toolkit=REDDIT_TOOLKIT,
            )
            log.error(f"{LogTag.TOOL} Reddit subreddits fetch failed", exc=e)

        unread_messages: list[RedditMessage] = []
        try:
            unread_messages = RedditMessageListing.model_validate(
                proxy_request_sync(
                    ProxyRequest(
                        user_id=user_id,
                        toolkit=REDDIT_TOOLKIT,
                        endpoint=f"{REDDIT_API_BASE}/message/unread",
                        method="GET",
                        query={"limit": 5},
                        headers=_REDDIT_HEADERS,
                    )
                )
            ).things
        except Exception as e:
            log.set(
                user_id=user_id,
                endpoint=f"{REDDIT_API_BASE}/message/unread",
                toolkit=REDDIT_TOOLKIT,
            )
            log.error(f"{LogTag.TOOL} Reddit unread messages fetch failed", exc=e)

        return {
            "user": {
                "name": me.name if me is not None else None,
                "id": me.id if me is not None else None,
                "link_karma": me.link_karma if me is not None else 0,
                "comment_karma": me.comment_karma if me is not None else 0,
                "total_karma": me.total_karma if me is not None else 0,
                "icon_img": me.icon_img if me is not None else None,
                "is_gold": me.is_gold if me is not None else False,
            },
            "subscribed_subreddits": [
                {
                    "name": subreddit.display_name,
                    "title": subreddit.title[:80],
                    "subscribers": subreddit.subscribers,
                }
                for subreddit in subreddits
            ],
            "unread_messages": [
                {
                    "id": message.id,
                    "subject": message.subject[:80],
                    "author": message.author,
                    "created_utc": message.created_utc,
                }
                for message in unread_messages
            ],
            "unread_message_count": len(unread_messages),
        }

    return ["REDDIT_CUSTOM_GATHER_CONTEXT"]
