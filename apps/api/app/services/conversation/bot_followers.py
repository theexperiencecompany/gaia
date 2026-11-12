"""The bot conversations a restarted bot must follow again: those still answering or working."""

from app.constants.conversation import ACTIVE_BOT_CONVERSATIONS_LIMIT
from app.db.repositories.bot_sessions import bot_session_repository
from app.db.repositories.conversation_log import SweepHead, conversation_log_repository
from app.models.conversation_log_models import ReplySettled
from app.models.conversation_send_models import ActiveBotConversation
from app.services.conversation.runtime import runtime_ports


async def list_active_bot_conversations(platform: str) -> list[ActiveBotConversation]:
    """Return the platform's session conversations with live work, an open reply or unanswered inputs."""
    active: list[ActiveBotConversation] = []
    heads = await conversation_log_repository.list_live_heads(
        platform, ACTIVE_BOT_CONVERSATIONS_LIMIT
    )
    for head in heads:
        session = await bot_session_repository.get_by_conversation_id(head.conversation_id)
        if session is None or session.platform != platform:
            continue
        active.append(
            ActiveBotConversation(
                conversation_id=head.conversation_id,
                platform_user_id=session.platform_user_id,
                channel_id=session.channel_id,
                is_dm=session.channel_id is None,
                after_seq=await _last_settled_seq(head),
            )
        )
    return active


async def _last_settled_seq(head: SweepHead) -> int:
    """Return the newest settled reply's seq; settled_through when none follows it."""
    since = head.state.settled_through
    entries = await runtime_ports().log.read_after(head.conversation_id, head.user_id, since)
    settled = [logged.seq for logged in entries if isinstance(logged.entry, ReplySettled)]
    return max(settled, default=since)
