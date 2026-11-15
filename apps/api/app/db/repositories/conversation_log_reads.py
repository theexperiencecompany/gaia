"""The conversation log's reads: its entries in seq order, and what the head has not settled yet.

A log entry is one conversation_entries document, {conversation_id, user_id, seq, at} plus the
entry's own fields; until it is flushed it is also staged in the head's outbox, so every read
unions the two.
"""

from __future__ import annotations

from collections.abc import Sequence

from app.constants.chat import CONVERSATION_ENTRIES_COLLECTION
from app.db.repositories.conversation_entries import (
    UNSETTLED_ROWS_FIELD,
    EntryWindow,
    current_state,
    head_from_raw,
    head_with_unsettled,
    logged_of,
    store_errors,
)
from app.db.repositories.conversations import ConversationRepository, union_with_outboxes
from app.models.conversation_log_models import ConversationState, LoggedEntry


class LogReadRepository(ConversationRepository):
    """Reads of the conversation log: the head's outbox unioned with conversation_entries."""

    async def read_log(
        self,
        conversation_id: str,
        *,
        user_id: str,
        after_seq: int = 0,
        through_seq: int | None = None,
        ids: Sequence[str] | None = None,
        reply_ids: Sequence[str] | None = None,
    ) -> list[LoggedEntry] | None:
        """Return the log entries after after_seq (through through_seq, of ids) in seq order; None for a missing conversation."""
        before = None if through_seq is None else through_seq + 1
        window = EntryWindow(after_seq=after_seq, before_seq=before, ids=ids, reply_ids=reply_ids)
        return await self._read_window(conversation_id, user_id, window)

    async def read_pinned(self, conversation_id: str, *, user_id: str) -> list[LoggedEntry] | None:
        """Return the entries the user pinned, in seq order; None for a missing conversation."""
        return await self._read_window(conversation_id, user_id, EntryWindow(pinned=True))

    async def _read_window(
        self, conversation_id: str, user_id: str, window: EntryWindow
    ) -> list[LoggedEntry] | None:
        heads = await self._read_heads({"conversation_id": conversation_id, "user_id": user_id})
        if not heads:
            return None
        [(_, entries)] = await self._union_for(heads, window)
        return [logged_of(entry) for entry in entries]

    async def read_unsettled(
        self, conversation_id: str, *, user_id: str
    ) -> tuple[ConversationState, list[LoggedEntry]] | None:
        """Return the state at the head and the entries after what it settled or stopped, through that head; None for a missing conversation."""
        entries = self._sibling_collection(CONVERSATION_ENTRIES_COLLECTION).name
        pipeline = head_with_unsettled(conversation_id, user_id, entries_collection=entries)
        with store_errors("head read"):  # pragma: no mutate — error label only
            raws = await self._raw_collection().aggregate(pipeline).to_list(length=None)
        if not raws:
            return None
        rows = raws[0].pop(UNSETTLED_ROWS_FIELD)
        head = head_from_raw(raws[0])
        state = current_state(head.document)
        window = EntryWindow(after_seq=max(state.settled_through, state.stopped_through))
        [(_, unsettled)] = union_with_outboxes([head], rows, window)
        return state, [logged_of(entry) for entry in unsettled]
