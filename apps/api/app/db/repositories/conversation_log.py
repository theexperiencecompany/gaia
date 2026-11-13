"""The conversation log's half of the conversation repository: its entries, its fold, and the step's claim.

A log entry is one conversation_entries document, {conversation_id, user_id, seq, at} plus
the entry's own fields (id and kind among them), committed through the head's outbox.
The head stores the log's fold (state), its step holder (runner) and the last epoch (runner_epoch).
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime

from bson import ObjectId
from pymongo import ReturnDocument

from app.constants.chat import (
    CONVERSATION_APPEND_MAX_ATTEMPTS,
    CONVERSATION_ENTRIES_COLLECTION,
)
from app.db.repositories.conversation_entries import (
    LOG_HEAD_FIELD,
    OUTBOX_FIELD,
    RUNNER_EPOCH_FIELD,
    RUNNER_FIELD,
    STATE_FIELD,
    EntryWindow,
    Head,
    at_log_head,
    log_document,
    logged_of,
    store_errors,
)
from app.db.repositories.conversations import ConversationRepository
from app.models.conversation_log_models import (
    CommsPhase,
    ConversationState,
    EntryKind,
    LoggedEntry,
    Reply,
    UserMessage,
)
from app.models.conversation_models import ConversationHead, StoredEntry
from app.utils.errors import ConversationStoreError

_INTEGRATION_KINDS = (EntryKind.INTEGRATION_NEEDED, EntryKind.INTEGRATION_CONNECTED)
#: A head the sweep must visit: unflushed entries, unsettled inputs or live work. A non-empty
#: outbox sorts after {}. Also the sweep index's partial filter, so only these heads are indexed.
SWEEP_DUE_FILTER: dict[str, object] = {
    "$or": [
        {OUTBOX_FIELD: {"$gt": {}}},
        {f"{STATE_FIELD}.unsettled_waking.0": {"$exists": True}},
        {f"{STATE_FIELD}.work.0": {"$exists": True}},
    ]
}
SWEEP_INDEX_NAME = "conversation_sweep_due_by_id"
_SWEEP_PROJECTION = {"_id": 1, "conversation_id": 1, "user_id": 1, OUTBOX_FIELD: 1, STATE_FIELD: 1}
#: The fold of a log with no entries yet: what a head that stores no state holds.
EMPTY_LOG_STATE = ConversationState(
    head=0,
    settled_through=0,
    stopped_through=0,
    unsettled_waking=(),
    comms=CommsPhase.IDLE,
    open_reply=None,
    work=(),
)
_EMPTY_STATE: dict[str, object] = EMPTY_LOG_STATE.model_dump(mode="json")


@dataclass(frozen=True)
class SweepHead:
    """A step-run head as the sweeper reads it; cursor is its _id, where the next page starts."""

    cursor: str
    conversation_id: str
    user_id: str
    has_outbox: bool
    state: ConversationState


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
        self,
        head: LogHead,
        logged: LoggedEntry,
        state: ConversationState,
        *,
        epoch: int | None,
        unread: bool = False,
    ) -> bool:
        """Commit logged and the state after it, only while the head is as read (and held by epoch when given).

        unread also marks the conversation unread and advances its sync clock, in the same write.
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
        with store_errors("log append"):  # pragma: no mutate — error label
            result = await self._raw_collection().update_one(
                expected,
                {
                    "$set": {
                        LOG_HEAD_FIELD: logged.seq,
                        f"{OUTBOX_FIELD}.{logged.seq}": document,
                        STATE_FIELD: state.model_dump(mode="json"),
                        **({"is_unread": True} if unread else {}),
                    },
                    **({"$currentDate": {"updatedAt": True}} if unread else {}),
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
        ids: Sequence[str] | None = None,
        reply_ids: Sequence[str] | None = None,
    ) -> list[LoggedEntry] | None:
        """Return the log entries after after_seq (through through_seq, of ids) in seq order; None for a missing conversation."""
        heads = await self._read_heads({"conversation_id": conversation_id, "user_id": user_id})
        if not heads:
            return None
        before = None if through_seq is None else through_seq + 1
        window = EntryWindow(after_seq=after_seq, before_seq=before, ids=ids, reply_ids=reply_ids)
        [(_, entries)] = await self._union_for(heads, window)
        return [logged_of(entry) for entry in entries]

    async def stage_log_amend(
        self, conversation_id: str, *, user_id: str, epoch: int, amended: LoggedEntry
    ) -> bool:
        """Stage amended in the head's outbox, only while epoch holds the step; the flush carries it to its document.

        The one write of an amendment is this head update, so the epoch fence and the write are atomic.
        """
        with store_errors("log amend"):  # pragma: no mutate — error label
            result = await self._raw_collection().update_one(
                {
                    "conversation_id": conversation_id,
                    "user_id": user_id,
                    f"{RUNNER_FIELD}.epoch": epoch,
                },
                {
                    "$set": {
                        f"{OUTBOX_FIELD}.{amended.seq}": log_document(
                            conversation_id, user_id, amended
                        )
                    }
                },
            )
        if not result.matched_count:
            return False
        self._spawn_flush(conversation_id, user_id)
        return True

    async def stage_unfenced_amend(
        self,
        conversation_id: str,
        *,
        user_id: str,
        amended: LoggedEntry,
        after_revision: int,
        advances_sync: bool = False,
    ) -> bool:
        """Stage amended unfenced, only while the stored entry is still at after_revision; the flush carries it.

        A staged amendment newer than after_revision (a fill, a reaction, a pin) makes this a no-op.
        advances_sync bumps updatedAt, so batch sync carries the edit to the user's other devices.
        """
        staged = f"{OUTBOX_FIELD}.{amended.seq}"
        with store_errors("log reaction"):  # pragma: no mutate — error label
            result = await self._raw_collection().update_one(
                {
                    "conversation_id": conversation_id,
                    "user_id": user_id,
                    "$or": [
                        {staged: {"$exists": False}},
                        {f"{staged}.revision": after_revision},
                    ],
                },
                {
                    "$set": {staged: log_document(conversation_id, user_id, amended)},
                    **({"$currentDate": {"updatedAt": True}} if advances_sync else {}),
                },
            )
        if not result.matched_count:
            return False
        self._spawn_flush(conversation_id, user_id)
        return True

    async def set_pinned(
        self, conversation_id: str, *, user_id: str, message_id: str, pinned: bool
    ) -> bool:
        """Pin or unpin the user message with this id or the reply with this reply id; False when there is none."""
        for _ in range(CONVERSATION_APPEND_MAX_ATTEMPTS):
            found = await self.read_log(
                conversation_id, user_id=user_id, ids=[message_id], reply_ids=[message_id]
            )
            target = next(
                (logged for logged in found or [] if isinstance(logged.entry, UserMessage | Reply)),
                None,
            )
            if target is None or not isinstance(entry := target.entry, UserMessage | Reply):
                return False
            if entry.pinned is pinned:
                return True
            revised = entry.model_copy(update={"pinned": pinned, "revision": entry.revision + 1})
            if await self.stage_unfenced_amend(
                conversation_id,
                user_id=user_id,
                amended=target.model_copy(update={"entry": revised}),
                after_revision=entry.revision,
                advances_sync=True,
            ):
                return True
        raise ConversationStoreError(
            message=f"pinning in conversation {conversation_id} lost every conditional write",
            meta={"conversation_id": conversation_id, "entry_id": message_id},
        )

    async def list_heads_to_sweep(self, limit: int, after: str | None) -> list[SweepHead]:
        """Return up to limit heads with unflushed entries, unsettled inputs or live work, in _id order past after."""
        query = (
            SWEEP_DUE_FILTER
            if after is None
            else {"_id": {"$gt": ObjectId(after)}, **SWEEP_DUE_FILTER}
        )
        with store_errors("log sweep"):  # pragma: no mutate — error label
            cursor = self._raw_collection().find(
                query,
                # Equivalent under mutation: any truthy flag projects the field.
                _SWEEP_PROJECTION,  # pragma: no mutate
                sort=[("_id", 1)],
                limit=limit,
                hint=SWEEP_INDEX_NAME,
            )
            rows = [row async for row in cursor]
        return [_sweep_head(row) for row in rows]

    async def list_live_heads(self, source: str, limit: int) -> list[SweepHead]:
        """Return the source's heads with live work or unanswered inputs (an open reply has its inputs unsettled)."""
        with store_errors("log live heads"):  # pragma: no mutate — error label
            cursor = self._raw_collection().find(
                {"source": source, **SWEEP_DUE_FILTER},
                # Equivalent under mutation: any truthy flag projects the field.
                _SWEEP_PROJECTION,  # pragma: no mutate
                limit=limit,
                hint=SWEEP_INDEX_NAME,
            )
            rows = [row async for row in cursor]
        heads = [_sweep_head(row) for row in rows]
        return [head for head in heads if head.state.work or head.state.unsettled_waking]

    async def list_integration_entries(
        self, *, user_id: str, integration_id: str, since: datetime
    ) -> list[tuple[str, LoggedEntry]]:
        """Return the user's integration entries for integration_id since since, as (conversation_id, entry).

        Read from conversation_entries alone: an entry still in a head's outbox is flushed within moments.
        """
        entries = self._sibling_collection(CONVERSATION_ENTRIES_COLLECTION)
        with store_errors("integration entries"):  # pragma: no mutate — error label
            cursor = entries.find(
                {
                    "user_id": user_id,
                    "at": {"$gte": since},
                    "kind": {"$in": [k.value for k in _INTEGRATION_KINDS]},
                    "integration_id": integration_id,
                }
            )
            rows = [row async for row in cursor]
        return [
            (str(row["conversation_id"]), logged_of(StoredEntry.model_validate(row)))
            for row in rows
        ]

    async def take_runner(
        self, conversation_id: str, *, user_id: str, runner_epoch: int, alive_key: str
    ) -> bool:
        """Hand the step to epoch runner_epoch + 1, only while runner_epoch is still the last one handed out."""
        last = runner_epoch if runner_epoch else {"$exists": False}
        epoch = runner_epoch + 1
        with store_errors("log claim"):  # pragma: no mutate — error label
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
        with store_errors("log release"):  # pragma: no mutate — error label
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
        with store_errors("log comms"):  # pragma: no mutate — error label
            raw = await self._raw_collection().find_one_and_update(
                {
                    "conversation_id": conversation_id,
                    "user_id": user_id,
                    f"{RUNNER_FIELD}.epoch": epoch,
                },
                [{"$set": {STATE_FIELD: state}}],
                return_document=ReturnDocument.AFTER,
            )
        return None if raw is None else _state(raw)


def _comms_as_read(comms: CommsPhase | None) -> dict[str, object]:
    # set_comms writes state.comms outside an append: an append computed against an older phase must not undo it.
    if comms is None:
        return {STATE_FIELD: {"$exists": False}}
    return {f"{STATE_FIELD}.comms": comms.value}


def _current(head: ConversationHead) -> ConversationState:
    """Return the stored fold at log_head: a seq holding a message folds as an entry that changes nothing."""
    stored = head.state or EMPTY_LOG_STATE
    return stored.model_copy(update={"head": head.log_head or 0})


def _state(raw: Mapping[str, object]) -> ConversationState:
    return _current(ConversationHead.model_validate(raw))


def _log_head(head: Head) -> LogHead:
    document = head.document
    return LogHead(
        conversation_id=head.conversation_id,
        user_id=head.user_id,
        log_head=head.log_head,
        state=_current(document),
        stored_comms=None if document.state is None else document.state.comms,
        holder=None if document.runner is None else document.runner.epoch,
        runner_epoch=document.runner_epoch,
        known=head.known_seqs(),
    )


conversation_log_repository = ConversationLogRepository()


def _sweep_head(row: Mapping[str, object]) -> SweepHead:
    cursor = row["_id"]
    if not isinstance(cursor, ObjectId):
        raise TypeError(f"conversation head _id is a {type(cursor).__name__}, not an ObjectId")
    return SweepHead(
        cursor=str(cursor),
        conversation_id=str(row["conversation_id"]),
        user_id=str(row["user_id"]),
        has_outbox=bool(row.get(OUTBOX_FIELD)),
        state=_state(row),
    )
