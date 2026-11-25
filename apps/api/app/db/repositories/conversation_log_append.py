"""The conversation log's append: read the head an entry is reduced against, then commit it conditionally.

The head stores the log's fold (state), its step holder (runner) and the last epoch (runner_epoch);
a commit lands only while the head is still as read, so concurrent appends serialize on seq.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from app.db.repositories.conversation_entries import (
    ADVANCE_SYNC_CLOCK,
    LOG_HEAD_FIELD,
    OUTBOX_FIELD,
    RUNNER_FIELD,
    STATE_FIELD,
    Head,
    at_log_head,
    current_state,
    log_document,
    store_errors,
)
from app.db.repositories.conversations import ConversationRepository
from app.models.conversation_log_models import (
    SYNCED_KINDS,
    CommsPhase,
    ConversationState,
    LoggedEntry,
)
from app.models.conversation_models import StoredEntry


@dataclass(frozen=True)
class LogHead:
    """A conversation head as the log reads it before a write."""

    conversation_id: str
    user_id: str
    log_head: int
    state: ConversationState
    # The comms phase the head stored; None while it stores no state yet.
    stored_comms: CommsPhase | None
    holder: int | None
    runner_epoch: int
    known: Mapping[str, int]
    # What the outbox held when read: the next commit's flush carries it with its own entry.
    unflushed: tuple[StoredEntry, ...]


class LogAppendRepository(ConversationRepository):
    """The read-then-conditionally-commit pair an append runs on the conversations head."""

    async def read_log_head(
        self, conversation_id: str, *, user_id: str, entry_id: str | None = None
    ) -> LogHead | None:
        """Read the head, and entry_id's seq when it is already committed; None for a missing conversation."""
        head = await self._read_head_for_append(
            conversation_id, user_id, [] if entry_id is None else [entry_id]
        )
        return None if head is None else _log_head(head)

    async def commit_log_entry(
        self,
        head: LogHead,
        logged: LoggedEntry,
        state: ConversationState,
        *,
        epoch: int | None,
        unread: bool = False,
        flush: bool = True,
    ) -> bool:
        """Commit logged and the state after it, only while the head is as read (and held by epoch when given).

        unread also marks the conversation unread. An entry that changes what history shows (a
        message, its settle) advances the sync clock, so batch sync and the activity signal see it.
        flush=False leaves the copy to conversation_entries to a later commit or the sweeper.
        """
        expected: dict[str, object] = {
            "conversation_id": head.conversation_id,
            "user_id": head.user_id,
            **at_log_head(head.log_head),
            **_comms_as_read(head.stored_comms),
        }
        if epoch is not None:
            expected[f"{RUNNER_FIELD}.epoch"] = epoch
        document = log_document(head.conversation_id, head.user_id, logged)
        advances_sync = unread or logged.entry.kind in SYNCED_KINDS
        with store_errors("log append", entry=document):  # pragma: no mutate — error label
            result = await self._raw_collection().update_one(
                expected,
                {
                    "$set": {
                        LOG_HEAD_FIELD: logged.seq,
                        f"{OUTBOX_FIELD}.{logged.seq}": document,
                        # Equivalent under mutation: the state's ints, strs and tuples store alike in BSON.
                        STATE_FIELD: state.model_dump(mode="json"),  # pragma: no mutate
                        **({"is_unread": True} if unread else {}),
                    },
                    **(ADVANCE_SYNC_CLOCK if advances_sync else {}),
                },
            )
        if not result.matched_count:
            return False
        if advances_sync:
            self._announce_row_changed(head.conversation_id, head.user_id)
        if flush:
            self._spawn_flush(
                head.conversation_id,
                head.user_id,
                [*head.unflushed, StoredEntry.model_validate(document)],
            )
        return True


def _comms_as_read(comms: CommsPhase | None) -> dict[str, object]:
    # set_comms writes state.comms outside an append: an append computed against an older phase must not undo it.
    if comms is None:
        return {STATE_FIELD: {"$exists": False}}
    return {f"{STATE_FIELD}.comms": comms.value}


def _log_head(head: Head) -> LogHead:
    document = head.document
    return LogHead(
        conversation_id=head.conversation_id,
        user_id=head.user_id,
        log_head=head.log_head,
        state=current_state(document),
        stored_comms=None if document.state is None else document.state.comms,
        holder=None if document.runner is None else document.runner.epoch,
        runner_epoch=document.runner_epoch,
        known=head.known_seqs(),
        unflushed=tuple(document.outbox.values()),
    )
