"""Jobs that finish a proactive chat message's delivery later than it was sent.

deliver_deferred_chat_message posts a message quiet hours held back, at the
window's end. It posts through post_to_platform_chat, so the policy is applied
again: a user who moved their window since gets it at the new end.

record_proactive_delivery writes a delivered message into its conversation's
checkpoint once no run or interrupt holds the thread.
"""

from arq.worker import Retry

from app.agents.core.background.platform_chat import DeferredChatMessage, post_to_platform_chat
from app.agents.core.background.thread_record import try_record_platform_delivery
from app.constants.notifications import PROACTIVE_RECORD_RETRY_DELAY
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


async def record_proactive_delivery(
    ctx: ArqJobContext,  # noqa: ARG001 -- ARQ task contract
    conversation_id: str,
    text: str,
) -> str:
    """Record text in the conversation's checkpoint, or retry while the thread is held.

    Past the registered max tries ARQ fails the job loudly: the message was
    delivered, but the conversation will not remember it.
    """
    log.set(conversation_id=conversation_id)
    if not await try_record_platform_delivery(conversation_id, text):
        raise Retry(defer=PROACTIVE_RECORD_RETRY_DELAY)
    return "recorded"
