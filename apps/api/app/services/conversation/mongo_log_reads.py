"""Reading the conversation log: its entries after a seq, its state, and what is still unsettled."""

from collections.abc import Sequence

from app.models.conversation_log_models import ConversationState, LoggedEntry
from app.services.conversation.mongo_log_base import MongoLogBase, not_found
from app.services.conversation.ports import Unsettled


class LogReads(MongoLogBase):
    """The log's reads, each one read of the head and its entries."""

    async def read_after(
        self, conversation_id: str, user_id: str, seq: int
    ) -> Sequence[LoggedEntry]:
        """Return the entries after seq in order, with their current content."""
        entries = await self._repository.read_log(conversation_id, user_id=user_id, after_seq=seq)
        if entries is None:
            raise not_found(conversation_id)
        return entries

    async def pinned(self, conversation_id: str, user_id: str) -> Sequence[LoggedEntry]:
        """Return the user messages and replies the user pinned, in order."""
        entries = await self._repository.read_pinned(conversation_id, user_id=user_id)
        if entries is None:
            raise not_found(conversation_id)
        return entries

    async def state(self, conversation_id: str, user_id: str) -> ConversationState:
        """Return the conversation's current state."""
        return (await self._head(conversation_id, user_id)).state

    async def unsettled(self, conversation_id: str, user_id: str) -> Unsettled:
        """Return the current state and the entries after max(settled_through, stopped_through), in one read of the head."""
        read = await self._repository.read_unsettled(conversation_id, user_id=user_id)
        if read is None:
            raise not_found(conversation_id)
        state, entries = read
        return Unsettled(state=state, entries=entries)
