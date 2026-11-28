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
    Head,
    StoredRow,
    current_state,
    head_from_raw,
    head_with_unsettled,
    logged_of,
    store_errors,
)
from app.db.repositories.conversations import (
    ConversationRepository,
    read_beside,
    union_with_outboxes,
)
from app.models.conversation_log_models import (
    ConversationState,
    EntryKind,
    LoggedEntry,
    ScreenWindow,
    UserMessage,
)

_USER_MESSAGES: frozenset[str] = frozenset({EntryKind.USER_MESSAGE})


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

    async def read_screen(
        self, conversation_id: str, *, user_id: str, after: int | None, limit: int
    ) -> ScreenWindow | None:
        """Return the entries after after (the newest limit when None) a screen projects from; None for a missing conversation."""
        heads = await self._read_heads({"conversation_id": conversation_id, "user_id": user_id})
        if not heads:
            return None
        head = heads[0]
        # The newest entry always: a run that holds none has nowhere to reach back from.
        tail = (
            EntryWindow(limit=limit)
            if after is None
            else EntryWindow(after_seq=min(after, head.log_head - 1))
        )
        run = await self._read(head, tail)
        run = await self._from_newest_message(head, run, limit)
        # Running work and the reply being written change on screen until they end.
        state = current_state(head.document)
        running = [work.task_id for work in state.work]
        run = await self._with_openers(head, run, running, state.open_reply)

        # A reply the run holds settles in the run, so only the entries it names are ever missing.
        async def lookup(ids: Sequence[str], _replies: Sequence[str]) -> list[StoredRow]:
            named = await self._read(head, EntryWindow(ids=ids))
            # Equivalent under mutation: read_beside reads only each row's entry.
            return [StoredRow(conversation_id, logged) for logged in named]  # pragma: no mutate

        # Equivalent under mutation: read_beside reads only each row's entry.
        rows = [StoredRow(conversation_id, logged) for logged in run]  # pragma: no mutate
        beside = await read_beside(rows, lookup)
        entries = sorted([*run, *(row.logged for row in beside)], key=lambda logged: logged.seq)
        return ScreenWindow(entries=entries, start=run[0].seq if run else 1)

    async def _from_newest_message(
        self, head: Head, run: list[LoggedEntry], limit: int
    ) -> list[LoggedEntry]:
        """Extend run back to the newest user message among the newest limit seqs, which a chat platform shows typing on."""
        # pragma: no mutate start — a run holding a message would find it in the run, and no span before it
        if not run or any(isinstance(logged.entry, UserMessage) for logged in run):
            return run
        # pragma: no mutate end
        # The run holds no user message, so the newest of the log's last limit seqs is before it.
        newest = EntryWindow(after_seq=max(head.log_head - limit, 0), limit=1, kinds=_USER_MESSAGES)
        found = await self._read(head, newest)
        if not found:
            return run
        span = EntryWindow(after_seq=found[0].seq - 1, before_seq=run[0].seq)
        return [*await self._read(head, span), *run]

    async def _read(self, head: Head, window: EntryWindow) -> list[LoggedEntry]:
        [(_, stored)] = await self._union_for([head], window)
        return [logged_of(entry) for entry in stored]

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
