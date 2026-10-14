"""Deliver a proactive chat message that quiet hours held back.

post_to_platform_chat schedules this job for the end of the user's window. It
posts through the same function, so the policy is applied again: a user who
moved their window since gets the message at the new end, not mid-window.
"""

from app.agents.core.background.platform_chat import DeferredChatMessage, post_to_platform_chat
from app.db.repositories.users import user_repository
from app.utils.auth_utils import build_user_context
from app.workers.task_envelope import ArqJobContext
from shared.py.wide_events import log


async def deliver_deferred_chat_message(
    ctx: ArqJobContext,  # noqa: ARG001 -- ARQ task contract
    message: DeferredChatMessage,
) -> str:
    """Post message to the chat it was addressed to; returns the outcome for the job result."""
    log.set(platform=message.source.value, message_class=message.message_class.value)
    user_doc = await user_repository.get(message.user_id)
    if user_doc is None:
        log.warning("deferred chat message dropped: user no longer exists", user_id=message.user_id)
        return "user_missing"
    result = await post_to_platform_chat(
        user=build_user_context(user_doc, auth_provider=None),
        channel=message.channel,
        text=message.text,
        origin=message.origin,
        message_class=message.message_class,
    )
    return result.value
