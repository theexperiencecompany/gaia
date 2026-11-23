"""Bot routes for the conversations a bot follows: which to follow again, and how far it delivered.

Mounted on the shared /api/v1/bot prefix; the bot API key is the only credential.
"""

from fastapi import APIRouter, Request

from app.api.v1.endpoints.bot import require_bot_api_key
from app.constants.chat import ConversationSource
from app.db.repositories.bot_sessions import bot_session_repository
from app.models.conversation_send_models import (
    ActiveBotConversation,
    BotDeliveryRecorded,
    BotDeliveryReport,
)
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
    """List the platform's bot conversations with live work, unanswered inputs or entries not yet delivered."""
    await require_bot_api_key(request)
    active = await list_active_bot_conversations(platform.value)
    log.set(operation="list_active_bot_conversations", platform=platform.value, active=len(active))
    return active


@router.put(
    "/conversations/{conversation_id}/delivered",
    summary="Record Bot Delivery",
    description="Move the conversation's bot cursor to what its follower put on the platform.",
)
async def record_delivered(
    request: Request, conversation_id: str, report: BotDeliveryReport
) -> BotDeliveryRecorded:
    """Record how far the bot delivered the conversation, so a restart resumes there and repeats nothing."""
    await require_bot_api_key(request)
    recorded = await bot_session_repository.record_delivered(
        conversation_id,
        platform=report.platform.value,
        delivered_seq=report.delivered_seq,
        partial_reply=report.partial_reply,
    )
    log.set(
        operation="record_bot_delivery",
        platform=report.platform.value,
        conversation_id=conversation_id,
        delivered_seq=report.delivered_seq,
        recorded=recorded,
    )
    return BotDeliveryRecorded(recorded=recorded)
