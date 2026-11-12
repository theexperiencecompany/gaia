"""GAIA's reaction on a user message: stored as the message's reaction field, announced as one reaction frame.

The instant pick (JEV) writes only while the message has no reaction; the chat model's
pick always writes. So a slow instant reaction can never replace the chat model's.
"""

from dataclasses import dataclass

from app.core.stream_manager import stream_manager
from app.models.chat_models import MessageReaction
from app.models.stream_events import ReactionFrame, ReactionPayload
from app.utils.agent_utils import format_sse_data


@dataclass(frozen=True)
class ReactionTarget:
    """The user message a reaction sits on, and the turn stream that announces it."""

    stream_id: str
    conversation_id: str
    user_id: str
    message_id: str


def reaction_frame(message_id: str, reaction: MessageReaction) -> ReactionFrame:
    """Return the frame a client applies to set message_id's reaction badge."""
    return ReactionFrame(reaction=ReactionPayload(message_id=message_id, **reaction.model_dump()))


async def _publish(target: ReactionTarget, reaction: MessageReaction) -> None:
    frame = reaction_frame(target.message_id, reaction)
    await stream_manager.publish_chunk(target.stream_id, format_sse_data(frame.model_dump()))
