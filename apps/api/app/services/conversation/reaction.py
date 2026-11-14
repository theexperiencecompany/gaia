"""GAIA's reaction on a user message: stored as the message's reaction field, announced as one reaction frame.

The instant pick (JEV) writes only while the message has no reaction; the chat model's
pick always writes. So a slow instant reaction can never replace the chat model's.
"""

from dataclasses import dataclass

from app.core.stream_manager import stream_manager
from app.db.repositories.conversations import conversation_repository
from app.models.chat_models import MessageReaction, ReactionBy
from app.models.stream_events import ReactionFrame, ReactionPayload
from app.services.conversation.ack import decide_reaction
from app.utils.agent_utils import format_sse_data
from shared.py.wide_events import log


@dataclass(frozen=True)
class ReactionTarget:
    """The user message a reaction sits on, and the turn stream that announces it."""

    stream_id: str
    conversation_id: str
    user_id: str
    message_id: str


@dataclass(frozen=True)
class InstantReactionInput:
    """What the instant classifier reads: the user's words and GAIA's message before them."""

    message_text: str
    previous_assistant_text: str


def reaction_frame(message_id: str, reaction: MessageReaction) -> ReactionFrame:
    """Return the frame a client applies to set message_id's reaction badge."""
    return ReactionFrame(reaction=ReactionPayload(message_id=message_id, **reaction.model_dump()))


async def react_instantly(target: ReactionTarget, said: InstantReactionInput) -> str | None:
    """Put JEV's emoji on the user's message when one fits; return the emoji once it is stored and published."""
    decision = await decide_reaction(said.message_text, said.previous_assistant_text)
    if decision.emoji is None:
        return None
    reaction = MessageReaction(emoji=decision.emoji, by=ReactionBy.JEV)
    try:
        if not await conversation_repository.set_message_reaction(
            target.conversation_id,
            user_id=target.user_id,
            message_id=target.message_id,
            reaction=reaction,
            only_if_unset=True,
        ):
            return None
        await _publish(target, reaction)
    except Exception as e:  # a missing tap-back is the whole degradation: the turn goes on
        log.error(
            "reaction_ack.place_failed",
            conversation_id=target.conversation_id,
            error=str(e)[:300],
            error_type=type(e).__name__,
        )
        return None
    return decision.emoji


async def react_as_chat_model(target: ReactionTarget, emoji: str) -> bool:
    """Store the chat model's emoji on the user's message, replacing any reaction there; publish it once stored.

    Returns whether it was stored: False when the message is not there to react to.
    """
    reaction = MessageReaction(emoji=emoji, by=ReactionBy.CHAT_MODEL)
    if not await conversation_repository.set_message_reaction(
        target.conversation_id,
        user_id=target.user_id,
        message_id=target.message_id,
        reaction=reaction,
    ):
        return False
    await _publish(target, reaction)
    return True


async def _publish(target: ReactionTarget, reaction: MessageReaction) -> None:
    frame = reaction_frame(target.message_id, reaction)
    await stream_manager.publish_chunk(target.stream_id, format_sse_data(frame.model_dump()))
