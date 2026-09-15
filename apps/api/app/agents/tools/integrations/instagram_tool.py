"""Instagram custom tools using Composio custom tool infrastructure."""

from composio import Composio
from composio.types import ExecuteRequestFn

from app.constants.log_tags import LogTag
from app.models.common_models import GatherContextInput
from app.models.integrations.composio import CustomToolAuthCredentials
from app.models.integrations.instagram import InstagramMedia, InstagramMediaList, InstagramProfile
from app.services.composio.proxy_client import ProxyRequest, proxy_request_sync
from shared.py.wide_events import log

INSTAGRAM_API_BASE = "https://graph.instagram.com/v18.0"
INSTAGRAM_TOOLKIT = "INSTAGRAM"


def _recent_media(user_id: str) -> list[InstagramMedia]:
    return InstagramMediaList.model_validate(
        proxy_request_sync(
            ProxyRequest(
                user_id=user_id,
                toolkit=INSTAGRAM_TOOLKIT,
                endpoint=f"{INSTAGRAM_API_BASE}/me/media",
                method="GET",
                query={
                    "limit": "5",
                    "fields": "id,caption,media_type,timestamp,like_count,comments_count,permalink",
                },
            )
        )
    ).data


def register_instagram_custom_tools(composio: Composio) -> list[str]:
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
        user_id = CustomToolAuthCredentials.parse(auth_credentials).user_id

        me = InstagramProfile.model_validate(
            proxy_request_sync(
                ProxyRequest(
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
            )
        )

        recent_media: list[dict[str, object]] = []
        try:
            recent_media = [
                {
                    "id": m.id,
                    "caption": (m.caption or "")[:100],
                    "media_type": m.media_type,
                    "timestamp": m.timestamp,
                    "likes": m.like_count,
                    "comments": m.comments_count,
                    "permalink": m.permalink,
                }
                for m in _recent_media(user_id)
            ]
        except Exception as e:
            log.warning(
                f"{LogTag.TOOL} Instagram media fetch failed",
                user_id=user_id,
                error_type=type(e).__name__,
            )

        return {
            "user": {
                "id": me.id,
                "name": me.name,
                "username": me.username,
                "account_type": me.account_type,
                "media_count": me.media_count,
                "followers": me.followers_count,
                "following": me.follows_count,
                "biography": (me.biography or "")[:200],
            },
            "recent_media": recent_media,
        }

    return ["INSTAGRAM_CUSTOM_GATHER_CONTEXT"]
