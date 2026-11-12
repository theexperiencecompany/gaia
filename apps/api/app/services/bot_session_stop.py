"""A bot chat's /stop and /new: stop the session's conversation, and for /new start a fresh one.

Kept out of bot_service: the outbound delivery chain imports that module, and the
stop path imports the agent stack, which imports outbound delivery back.
"""

from dataclasses import dataclass

from app.constants.chat import ConversationSource
from app.db.repositories.bot_sessions import bot_session_repository
from app.models.user_models import AuthenticatedUser
from app.models.work_cancel_models import ConversationStopResponse, WorkCancelled
from app.services.bot_service import BotService
from app.services.browser.job_stop import RequesterChat, requester_chat
from app.services.conversation_stop_service import press_stop, stop_conversation


@dataclass(frozen=True)
class _SessionConversation:
    """The conversation a bot session points at, and how far its browser stop reaches."""

    conversation_id: str
    requester: RequesterChat | None


async def _session_conversation(
    platform: str,
    platform_user_id: str,
    channel_id: str | None,
    user: AuthenticatedUser,
    *,
    is_dm: bool,
) -> _SessionConversation | None:
    """Find the session's conversation; None when the chat has no session yet."""
    session_key = BotService.build_session_key(
        platform, platform_user_id, None if is_dm else channel_id
    )
    current = await bot_session_repository.get_by_session_key(session_key)
    if current is None:
        return None
    # A DM's stop also reaches a run started in a group, which answers to this DM;
    # a group's reaches only its own.
    requester = requester_chat(user.user_id, ConversationSource.coerce(platform)) if is_dm else None
    return _SessionConversation(current.conversation_id, requester)


async def stop_bot_session(
    platform: str,
    platform_user_id: str,
    channel_id: str | None,
    user: AuthenticatedUser,
    *,
    is_dm: bool = False,
) -> ConversationStopResponse:
    """Handle the user's /stop: stop everything the session's conversation runs, keep the session."""
    session = await _session_conversation(platform, platform_user_id, channel_id, user, is_dm=is_dm)
    if session is None:
        return ConversationStopResponse(work=WorkCancelled())
    return await press_stop(session.conversation_id, user.user_id, session.requester)


async def reset_bot_session(
    platform: str,
    platform_user_id: str,
    channel_id: str | None,
    user: AuthenticatedUser,
    *,
    is_dm: bool = False,
) -> str:
    """Stop the session's conversation, then replace it with a fresh one; return the new id."""
    session = await _session_conversation(platform, platform_user_id, channel_id, user, is_dm=is_dm)
    # Work left running in a conversation the user has left keeps reporting into it.
    # Not press_stop: /new is its own action, counted as bot:session_reset.
    if session is not None:
        await stop_conversation(session.conversation_id, user.user_id, session.requester)
    return await BotService.reset_session(platform, platform_user_id, channel_id, user, is_dm=is_dm)
