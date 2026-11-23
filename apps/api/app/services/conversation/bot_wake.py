"""Wake a bot conversation's bot when something it renders is logged, so its follower delivers it.

A chat platform hears a conversation only through its follower on the events stream. A follower
runs while a message posted there is answered; this wakes one for what lands outside that: a
Notice, an approval, a reply to work that finished later.
"""

from app.db.repositories.bot_sessions import bot_session_repository
from app.models.conversation_frame_models import EntryFrame, OutputFrame
from app.models.conversation_log_models import ApprovalRequested, Notice, Reply
from app.services.conversation.ports import Frames
from app.services.outbound_delivery import publish_conversation_wake

#: The entries a bot follower sends to the platform when they are appended.
_BOT_RENDERED = (Reply, Notice, ApprovalRequested)


class BotWakingFrames:
    """The Frames port that also wakes the conversation's bot for each entry a bot renders."""

    def __init__(self, frames: Frames) -> None:
        self._frames = frames

    async def publish(self, conversation_id: str, *frames: OutputFrame) -> None:
        """Publish frames, owe the entries a bot renders to the conversation's bot, and wake it from its cursor."""
        await self._frames.publish(conversation_id, *frames)
        rendered = [
            frame.seq
            for frame in frames
            if isinstance(frame, EntryFrame) and isinstance(frame.entry, _BOT_RENDERED)
        ]
        if not rendered:
            return
        session = await bot_session_repository.owe_delivery(
            conversation_id, first_seq=min(rendered), last_seq=max(rendered)
        )
        if session is not None:
            await publish_conversation_wake(session)
