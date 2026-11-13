"""Deliver an already-voiced proactive message, a reminder, into one conversation.

The conversation's log is the one record: the message is logged as a Notice carrying its
cards, which every device reads off the events stream. A bot conversation is sent the text
on its platform first, and logged only once it was sent.
"""

from uuid import uuid4

from app.constants.log_tags import LogTag
from app.db.repositories.conversations import conversation_repository
from app.models.chat_models import ConversationSource, ToolDataEntry
from app.models.conversation_log_models import Notice
from app.models.user_models import AuthenticatedUser
from app.services.conversation.log import accept
from app.services.conversation.runtime import runtime_ports
from app.services.platform_message_service import (
    deliver_message_to_platform,
    is_bot_platform,
)
from app.utils.errors import ConversationNotFoundError
from shared.py.wide_events import log


async def deliver_message_to_conversation(
    *,
    conversation_id: str,
    user: AuthenticatedUser,
    text: str,
    origin: str,
    tool_data: list[ToolDataEntry] | None = None,
) -> ConversationSource | None:
    """Log text as a Notice in the conversation, sending it to a bot platform first; the source, or None.

    None when the text is blank, the platform send failed, or the conversation is gone.
    """
    if not text.strip():
        return None
    user_id = user.user_id
    source = await _get_conversation_source(conversation_id, user_id)
    on_platform = is_bot_platform(source)
    delivered = (
        await deliver_message_to_platform(source, user_id, text, conversation_id=conversation_id)
        if on_platform
        else True
    )
    notice_id = f"notice:{uuid4()}"
    if delivered:
        notice = Notice(id=notice_id, text=text, origin=origin, tool_data=tuple(tool_data or ()))
        try:
            await accept(runtime_ports(), conversation_id, user_id, notice)
        except ConversationNotFoundError:
            log.info(
                f"{LogTag.AGENT} conversation deleted, nothing delivered",
                conversation_id=conversation_id,
            )
            return None
    _log_delivery_verdict(
        notice_id=notice_id,
        conversation_id=conversation_id,
        conversation_source=source,
        transport="platform" if on_platform else "events",
        delivered=delivered,
    )
    return source if delivered else None


def _log_delivery_verdict(
    *,
    notice_id: str,
    conversation_id: str,
    conversation_source: ConversationSource | None,
    transport: str,
    delivered: bool,
) -> None:
    """Record whether the message reached the user."""
    source = conversation_source.value if conversation_source else None
    log.set_ns("result_delivery", transport=transport, delivered=delivered, source=source)
    fields = {
        "notice_id": notice_id,
        "conversation_id": conversation_id,
        "conversation_source": source,
        "transport": transport,
    }
    if delivered:
        log.info(f"{LogTag.AGENT} deliver_message_to_conversation: delivered", **fields)
    else:
        log.error(f"{LogTag.AGENT} deliver_message_to_conversation: NOT delivered", **fields)


async def _get_conversation_source(conversation_id: str, user_id: str) -> ConversationSource | None:
    """Return the conversation's persisted originating source (web/whatsapp/...).

    This is the authoritative delivery-routing key: it says which channel the
    conversation belongs to, independent of the run that produced the message
    (so a scheduled/workflow run posting into a bot conversation still routes to
    that platform). Returns None on miss/error — treated as a non-bot conversation.
    """
    try:
        return await conversation_repository.get_source(conversation_id, user_id=user_id)
    except Exception as e:
        log.warning(f"{LogTag.AGENT} _get_conversation_source: lookup failed", error=str(e))
        return None
