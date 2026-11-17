"""The one rule for which surface a reply is read on, which picks its prompt, its format and its reactions.

A reply to the user's own message is read where they wrote it. A reply GAIA sends on by itself
(a workflow's result, a tracked todo run's write-up) is read where that send goes: the chat app
its stored destination names, else the app. Any other is read on the conversation's own surface.
"""

from collections.abc import Sequence
from dataclasses import dataclass

from app.constants.chat import ConversationSource
from app.db.repositories.conversations import conversation_repository
from app.models.conversation_log_models import StepClaim, UserMessage
from app.models.delivery_models import ChatChannel, ProactiveTarget
from app.services.conversation.mongo_log_base import not_found
from app.services.delivery.chat_channel import resolve_proactive_target


@dataclass(frozen=True, slots=True)
class SentOn:
    """A reply GAIA sends on by itself, and the destination its waking entry stored (None when logged before one was)."""

    stored: ProactiveTarget | None


async def resolve_reply_surface(
    claim: StepClaim, said: Sequence[UserMessage], sent_on: SentOn | None
) -> ConversationSource:
    """Return the surface the reply is read on; a destination lookup that fails raises."""
    if said:
        return said[-1].surface
    if sent_on is not None:
        target = sent_on.stored or await resolve_proactive_target(claim.user_id)
        if isinstance(target, ChatChannel):
            return target.source
    stored = await conversation_repository.get_source(claim.conversation_id, user_id=claim.user_id)
    if stored is None:
        raise not_found(claim.conversation_id)
    return stored
