"""The bot conversations a restarted bot must follow again: those still answering, working or not yet delivered."""

from app.constants.conversation import ACTIVE_BOT_CONVERSATIONS_LIMIT
from app.db.repositories.bot_sessions import bot_session_repository
from app.db.repositories.conversation_log import SweepHead, conversation_log_repository
from app.models.bot_models import BotDelivery
from app.models.conversation_log_models import ReplySettled
from app.models.conversation_send_models import ActiveBotConversation
from app.services.conversation.runtime import runtime_ports


async def list_active_bot_conversations(platform: str) -> list[ActiveBotConversation]:
    """Return the platform's session conversations with live work, unanswered inputs, or entries not yet delivered."""
    active: dict[str, ActiveBotConversation] = {}
    for session in await bot_session_repository.list_owed(platform, ACTIVE_BOT_CONVERSATIONS_LIMIT):
        if session.delivery is not None:
            active[session.conversation_id] = ActiveBotConversation.of(session, session.delivery)
    heads = await conversation_log_repository.list_live_heads(
        platform, ACTIVE_BOT_CONVERSATIONS_LIMIT
    )
    for head in heads:
        if head.conversation_id in active:
            continue
        session = await bot_session_repository.get_by_conversation_id(head.conversation_id)
        if session is None or session.platform != platform:
            continue
        active[head.conversation_id] = ActiveBotConversation.of(
            session, session.delivery or await _undelivered_from(head)
        )
    return list(active.values())


async def _undelivered_from(head: SweepHead) -> BotDelivery:
    """Return the cursor of a session nothing was owed on yet: through the newest settled reply, which the bot sent."""
    since = head.state.settled_through
    entries = await runtime_ports().log.read_after(head.conversation_id, head.user_id, since)
    settled = [logged.seq for logged in entries if isinstance(logged.entry, ReplySettled)]
    return BotDelivery(delivered_seq=max(settled, default=since))
