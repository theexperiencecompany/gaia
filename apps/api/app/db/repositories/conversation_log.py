"""The conversation log's half of the conversation repository: its entries, its fold, and the step's claim.

A log entry is one conversation_entries document, {conversation_id, user_id, seq, at} plus
the entry's own fields (id and kind among them), committed through the same outbox and seq
allocator as a message. kind alone tells the two apart: is_log_entry and MESSAGES_ONLY keep
every message reader to messages, and EntryWindow(log=True) keeps the log to its own kinds.
The head stores the log's fold (state), its step holder (runner) and the last epoch (runner_epoch).
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime

from pydantic import BaseModel, ConfigDict, TypeAdapter
from pymongo import ReturnDocument

from app.db.repositories.conversation_entries import (
    LOG_HEAD_FIELD,
    OUTBOX_FIELD,
    RUNNER_EPOCH_FIELD,
    RUNNER_FIELD,
    STATE_FIELD,
    EntryWindow,
    Head,
    at_log_head,
    store_errors,
)
from app.db.repositories.conversations import ConversationRepository
from app.models.conversation_log_models import (
    CommsPhase,
    ConversationState,
    Entry,
    LoggedEntry,
    Reply,
    UserMessage,
)

_ENTRY: TypeAdapter[Entry] = TypeAdapter(Entry)
_DOCUMENT_KEYS = ("_id", "conversation_id", "user_id")
_EMPTY_STATE: dict[str, object] = ConversationState.empty().model_dump(mode="json")


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


class ConversationLogRepository(ConversationRepository):
    """Reads and conditional writes of the conversation log on the conversations head and its entries."""

    async def read_log_head(
        self, conversation_id: str, *, user_id: str, entry_id: str | None = None
    ) -> LogHead | None:
        """Read the head, and entry_id's seq when it is already committed; None for a missing conversation."""
        head = await self._read_head_for_append(
            conversation_id, user_id, [] if entry_id is None else [entry_id]
        )
        return None if head is None else _log_head(head)

    async def commit_log_entry(
        self, head: LogHead, logged: LoggedEntry, state: ConversationState, *, epoch: int | None
    ) -> bool:
        """Commit logged and the state after it, only while the head is as read (and held by epoch when given)."""
        expected: dict[str, object] = {
            "conversation_id": head.conversation_id,
            "user_id": head.user_id,
            **at_log_head(head.log_head),
            **_comms_as_read(head.stored_comms),
        }
        if epoch is not None:
            expected[f"{RUNNER_FIELD}.epoch"] = epoch
        document = {
            **logged.entry.model_dump(mode="json"),
            "conversation_id": head.conversation_id,
            "user_id": head.user_id,
            "seq": logged.seq,
            "at": logged.at,
        }
        with store_errors("log append"):
            result = await self._raw_collection().update_one(
                expected,
                {
                    "$set": {
                        LOG_HEAD_FIELD: logged.seq,
                        f"{OUTBOX_FIELD}.{logged.seq}": document,
                        STATE_FIELD: state.model_dump(mode="json"),
                    }
                },
            )
        if not result.matched_count:
            return False
        self._spawn_flush(head.conversation_id, head.user_id)
        return True

    async def read_log(
        self,
        conversation_id: str,
        *,
        user_id: str,
        after_seq: int = 0,
        through_seq: int | None = None,
    ) -> list[LoggedEntry] | None:
        """Return the log entries after after_seq (through through_seq) in seq order; None for a missing conversation."""
        heads = await self._read_heads({"conversation_id": conversation_id, "user_id": user_id})
        if not heads:
            return None
        before = None if through_seq is None else through_seq + 1
        window = EntryWindow(after_seq=after_seq, before_seq=before, log=True)
        [(_, rows)] = await self._union_for(heads, window)
        return [_logged(row) for row in rows]

    async def amend_log_entry(
        self, conversation_id: str, *, user_id: str, entry: Reply | UserMessage
    ) -> LoggedEntry | None:
        """Replace the content of the entry with entry's id and kind at its next revision; None when absent."""
        content = entry.model_dump(mode="json", exclude={"id", "kind", "revision"})
        revised = [
            {
                "$set": {
                    **{name: {"$literal": value} for name, value in content.items()},
                    "revision": {"$add": [{"$ifNull": ["$revision", 0]}, 1]},
                }
            }
        ]
        match = {"id": entry.id, "kind": entry.kind.value}
        if not await self._update_entry(conversation_id, user_id, match, revised):
            return None
        with store_errors("log read"):
            raw = await self._entries().find_one(
                {"user_id": user_id, "conversation_id": conversation_id, **match}
            )
        return None if raw is None else _logged(raw)

    async def take_runner(
        self, conversation_id: str, *, user_id: str, runner_epoch: int, alive_key: str
    ) -> bool:
        """Hand the step to epoch runner_epoch + 1, only while runner_epoch is still the last one handed out."""
        last = runner_epoch if runner_epoch else {"$in": [0, None]}
        epoch = runner_epoch + 1
        with store_errors("log claim"):
            result = await self._raw_collection().update_one(
                {"conversation_id": conversation_id, "user_id": user_id, RUNNER_EPOCH_FIELD: last},
                {
                    "$set": {
                        RUNNER_EPOCH_FIELD: epoch,
                        RUNNER_FIELD: {"epoch": epoch, "alive_key": alive_key},
                    }
                },
            )
        return bool(result.matched_count)

    async def release_runner(self, conversation_id: str, *, user_id: str, epoch: int) -> bool:
        """Clear the step's holder, only while epoch holds it and nothing waking is unsettled."""
        with store_errors("log release"):
            result = await self._raw_collection().update_one(
                {
                    "conversation_id": conversation_id,
                    "user_id": user_id,
                    f"{RUNNER_FIELD}.epoch": epoch,
                    "$or": [
                        {f"{STATE_FIELD}.unsettled_waking": []},
                        {STATE_FIELD: {"$exists": False}},
                    ],
                },
                {"$set": {RUNNER_FIELD: None}},
            )
        return bool(result.matched_count)

    async def set_log_comms(
        self, conversation_id: str, *, user_id: str, epoch: int, phase: CommsPhase
    ) -> ConversationState | None:
        """Write the comms phase while epoch holds the step, returning the state; None when it does not."""
        state = {"$mergeObjects": [{"$literal": _EMPTY_STATE}, f"${STATE_FIELD}", {"comms": phase}]}
        with store_errors("log comms"):
            raw = await self._raw_collection().find_one_and_update(
                {
                    "conversation_id": conversation_id,
                    "user_id": user_id,
                    f"{RUNNER_FIELD}.epoch": epoch,
                },
                [{"$set": {STATE_FIELD: state}}],
                projection={STATE_FIELD: 1, LOG_HEAD_FIELD: 1},
                return_document=ReturnDocument.AFTER,
            )
        return None if raw is None else _state(raw)


def _comms_as_read(comms: CommsPhase | None) -> dict[str, object]:
    # set_comms writes state.comms outside an append: an append computed against an older phase must not undo it.
    if comms is None:
        return {STATE_FIELD: {"$exists": False}}
    return {f"{STATE_FIELD}.comms": comms.value}


class _StoredRunner(BaseModel):
    epoch: int
    alive_key: str


class _StoredLog(BaseModel):
    """The log's own fields on a head document."""

    model_config = ConfigDict(extra="ignore")

    log_head: int = 0
    state: ConversationState | None = None
    runner: _StoredRunner | None = None
    runner_epoch: int = 0

    def current(self) -> ConversationState:
        """Return the stored fold at log_head: a seq holding a message folds as an entry that changes nothing."""
        return (self.state or ConversationState.empty()).model_copy(update={"head": self.log_head})


def _state(raw: Mapping[str, object]) -> ConversationState:
    return _StoredLog.model_validate(raw).current()


def _log_head(head: Head) -> LogHead:
    stored = _StoredLog.model_validate(head.raw)
    return LogHead(
        conversation_id=head.conversation_id,
        user_id=head.user_id,
        log_head=head.log_head,
        state=stored.current(),
        stored_comms=None if stored.state is None else stored.state.comms,
        holder=None if stored.runner is None else stored.runner.epoch,
        runner_epoch=stored.runner_epoch,
        known=head.known_seqs(),
    )


class _StoredEntry(BaseModel):
    """A log entry document: its position, and the entry's own fields beside it."""

    model_config = ConfigDict(extra="allow")

    seq: int
    at: datetime


def _logged(raw: Mapping[str, object]) -> LoggedEntry:
    stored = _StoredEntry.model_validate(raw)
    fields = {k: v for k, v in (stored.model_extra or {}).items() if k not in _DOCUMENT_KEYS}
    return LoggedEntry(seq=stored.seq, at=stored.at, entry=_ENTRY.validate_python(fields))


conversation_log_repository = ConversationLogRepository()
