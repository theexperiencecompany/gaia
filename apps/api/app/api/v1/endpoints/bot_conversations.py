"""Bot route listing the conversations a restarted bot must follow again.

Mounted on the shared /api/v1/bot prefix; the bot API key is the only credential.
"""

from fastapi import APIRouter, Request

from app.api.v1.endpoints.bot import require_bot_api_key
from app.constants.chat import ConversationSource
from app.models.conversation_send_models import ActiveBotConversation
from app.services.conversation.bot_followers import list_active_bot_conversations
from shared.py.wide_events import log

router = APIRouter()


@router.get(
    "/conversations/active",
    summary="List Active Bot Conversations",
    description="The platform's conversations still answering or working, with the seq to follow after.",
)
async def list_active_conversations(
    request: Request, platform: ConversationSource
) -> list[ActiveBotConversation]:
    """List the platform's bot conversations with live work, an open reply or unanswered inputs."""
    await require_bot_api_key(request)
    active = await list_active_bot_conversations(platform.value)
    log.set(operation="list_active_bot_conversations", platform=platform.value, active=len(active))
    return active
