"""The stored shape of a conversation entry and its head, and the expressions the append protocol commits with.

An entry is one conversation log entry, keyed by (user_id, conversation_id, seq) and
(user_id, conversation_id, id). The head is the conversations document: log_head is the
highest committed seq and outbox holds the committed entries not yet copied into
conversation_entries.
"""

from __future__ import annotations

from collections.abc import Iterator, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime

from pydantic import TypeAdapter
from pymongo.errors import PyMongoError

from app.constants.chat import CONVERSATION_ENTRIES_MIGRATION_SCRIPT
from app.models.conversation_log_models import Entry, EntryKind, LoggedEntry
from app.models.conversation_models import (
    ConversationHead,
    EntryKey,
    StoredEntry,
)
from app.utils.errors import ConversationStoreError, UnmigratedConversationError

LOG_HEAD_FIELD = "log_head"
OUTBOX_FIELD = "outbox"
#: The conversation log's fold, its step holder {epoch, alive_key} and the last epoch handed out.
STATE_FIELD = "state"
RUNNER_FIELD = "runner"
RUNNER_EPOCH_FIELD = "runner_epoch"
#: On an amendable log entry (a reply, a user message): bumped by each amend, staged through the outbox.
REVISION_FIELD = "revision"
#: The fingerprint of the embedded array as the migration last rewrote it, so any later old-build write shows.
MIGRATED_FINGERPRINT_FIELD = "migrated_fingerprint"
#: On a migrated entry: each field's hash as the migration wrote it (the next pass sets only what changed).
MIGRATION_FIELDS_FIELD = "migration_fields"
#: Head fields that never reach a ConversationDocument (or the client it is returned to).
HEAD_INTERNAL_FIELDS = (
    "messages",
    LOG_HEAD_FIELD,
    OUTBOX_FIELD,
    STATE_FIELD,
    RUNNER_FIELD,
    RUNNER_EPOCH_FIELD,
    MIGRATED_FINGERPRINT_FIELD,
)
#: The kinds the conversation log appends; a stored entry with any other kind, or none, is a message.
LOG_KINDS: list[str] = [kind.value for kind in EntryKind]

#: Derived from the log's stored state: live work is paused on the user's approval.
AWAITING_APPROVAL: dict[str, object] = {
    "$anyElementTrue": [
        {
            "$map": {
                "input": {"$ifNull": [f"${STATE_FIELD}.work", []]},
                "as": "work",
                "in": {"$gt": [{"$size": {"$ifNull": ["$$work.pending_approvals", []]}}, 0]},
            }
        }
    ]
}
#: Added to every head read, which never ships the embedded array.
AWAITING_APPROVAL_STAGE: dict[str, object] = {
    "$addFields": {"awaiting_approval": AWAITING_APPROVAL}
}
DROP_EMBEDDED_STAGE: dict[str, object] = {"$project": {"messages": 0}}
#: Cards whose message is not committed yet wait on the head under this field, by message id;
#: a turn saves within itself, so ones a day old are dropped by the next commit.
FOLDED_CARDS_FIELD = "folded_cards"
FOLDED_CARDS_KEEP_SECONDS = 86_400
#: What an append reads of its head: identity and the log.
_APPEND_HEAD_FIELDS: dict[str, object] = {
    "conversation_id": 1,
    "user_id": 1,
    LOG_HEAD_FIELD: 1,
    OUTBOX_FIELD: 1,
    STATE_FIELD: 1,
    RUNNER_FIELD: 1,
    RUNNER_EPOCH_FIELD: 1,
}
CONTENT_HASH_FIELD = "content_hash"
_EXISTING_FIELDS: dict[str, object] = {"_id": 0, "id": 1, "seq": 1, CONTENT_HASH_FIELD: 1}
_HEAD_OF_ENTRY = "_head"
#: Each outbox entry of a head, one document apiece.
_OUTBOX_AS_ENTRIES: list[dict[str, object]] = [
    {"$project": {"_id": 0, "entry": {"$objectToArray": f"${OUTBOX_FIELD}"}}},
    {"$unwind": "$entry"},
    {"$replaceRoot": {"newRoot": "$entry.v"}},
]
#: A head the protocol may commit on at log_head 0: empty, or written before log_head existed with no messages.
EMPTY_LOG: dict[str, object] = {
    "$or": [
        {LOG_HEAD_FIELD: 0},
        {LOG_HEAD_FIELD: {"$exists": False}, "messages.0": {"$exists": False}},
    ]
}


@dataclass(frozen=True)
class Head:
    """A conversation head as the protocol reads it: the parsed log and the conversation document's own fields."""

    document: ConversationHead
    fields: dict[str, object]

    @property
    def conversation_id(self) -> str:
        return self.document.conversation_id

    @property
    def user_id(self) -> str:
        return self.document.user_id

    @property
    def log_head(self) -> int:
        return self.document.log_head or 0

    @property
    def outbox(self) -> dict[int, StoredEntry]:
        return self.document.outbox

    def known_seqs(self) -> dict[str, int]:
        """Every entry id this head's reads saw, outbox and collection both, by seq."""
        stored = {row.id: row.seq for row in self.document.existing}
        return {**stored, **{entry.id: seq for seq, entry in self.outbox.items()}}

    def known_content(self) -> dict[str, str | None]:
        """Return the committed-content hash of every entry id this head's reads saw."""
        stored = {row.id: row.content_hash for row in self.document.existing}
        return {**stored, **{entry.id: entry.content_hash for entry in self.outbox.values()}}


def newest(stored: StoredEntry | None, staged: StoredEntry) -> StoredEntry:
    """Pick the copy of one entry a read returns: the staged one unless the collection already holds its revision."""
    if stored is None:
        return staged
    if staged.revision is None:
        return stored
    return staged if stored.revision is None or staged.revision > stored.revision else stored


_ENTRY: TypeAdapter[Entry] = TypeAdapter(Entry)
#: A stored entry's keys beside the log entry's own fields; id is both, so it stays.
_POSITION_KEYS = ("conversation_id", "user_id", "seq", "at", "content_hash", "migration_fields")


@dataclass(frozen=True)
class StoredRow:
    """A stored log entry with the conversation it belongs to."""

    conversation_id: str
    logged: LoggedEntry


def head_from_raw(raw: Mapping[str, object]) -> Head:
    """Parse a head read into the log's view and the conversation document's own fields."""
    return Head(document=ConversationHead.model_validate(raw), fields=head_fields(raw))


def head_with_existing(
    conversation_id: str, user_id: str, ids: Sequence[str], *, entries_collection: str
) -> list[dict[str, object]]:
    """Read the head, then which of ids the collection holds, in one aggregate.

    The $lookup runs after its head is read, so an entry flushed out of the outbox in
    between is still seen in the collection.
    """
    return [
        {"$match": {"conversation_id": conversation_id, "user_id": user_id}},
        {"$project": _APPEND_HEAD_FIELDS},
        {
            "$lookup": {
                "from": entries_collection,
                "pipeline": [
                    {
                        "$match": {
                            "user_id": user_id,
                            "conversation_id": conversation_id,
                            "id": {"$in": list(ids)},
                        }
                    },
                    {"$project": _EXISTING_FIELDS},
                ],
                "as": "existing",
            }
        },
    ]


def _counted_heads(excluding: Mapping[str, object] | None) -> dict[str, object]:
    """Match the heads whose entries a cross-conversation read counts: all but the excluded."""
    return {"$nor": [dict(excluding)]} if excluding else {}


def outbox_entries_matching(
    user_id: str, match: Mapping[str, object], *, excluding: Mapping[str, object] | None
) -> list[dict[str, object]]:
    """Read the user's outbox entries that match, from the heads a cross-conversation read counts."""
    heads: dict[str, object] = {
        "user_id": user_id,
        OUTBOX_FIELD: {"$exists": True, "$ne": {}},
        **_counted_heads(excluding),
    }
    return [{"$match": heads}, *_OUTBOX_AS_ENTRIES, {"$match": dict(match)}]


def every_outbox_entry_matching(match: Mapping[str, object]) -> list[dict[str, object]]:
    """Read every head's outbox entries that match, across all users (a maintenance sweep's read)."""
    heads = {OUTBOX_FIELD: {"$exists": True, "$ne": {}}}
    return [{"$match": heads}, *_OUTBOX_AS_ENTRIES, {"$match": dict(match)}]


def stored_entries_matching(
    user_id: str,
    match: Mapping[str, object],
    *,
    excluding: Mapping[str, object] | None,
    heads_collection: str,
    limit: int,
) -> list[dict[str, object]]:
    """Read the user's stored entries that match and whose head is live and counted.

    An entry with no head is a deleted conversation's leftover: it is never read.
    """
    pipeline: list[dict[str, object]] = [
        {"$match": {"user_id": user_id, **match}},
        {
            "$lookup": {
                "from": heads_collection,
                "localField": "conversation_id",
                "foreignField": "conversation_id",
                "pipeline": [
                    {"$match": {"user_id": user_id, **_counted_heads(excluding)}},
                    {"$project": {"_id": 1}},
                    {"$limit": 1},
                ],
                "as": _HEAD_OF_ENTRY,
            }
        },
        {"$match": {f"{_HEAD_OF_ENTRY}.0": {"$exists": True}}},
        {"$project": {_HEAD_OF_ENTRY: 0}},
    ]
    return [*pipeline, {"$limit": limit}] if limit else pipeline


def unmigrated(subject: str) -> UnmigratedConversationError:
    """Build the boot refusal for messages still in the old shape, naming the command that rewrites them."""
    return UnmigratedConversationError(
        message=(
            f"{subject} still holds messages in the old shape: run "
            f"python -m {CONVERSATION_ENTRIES_MIGRATION_SCRIPT} --apply, then --verify"
        ),
        why="an embedded messages array no migration pass marked, or message-shaped entries",
    )


def head_fields(raw: Mapping[str, object]) -> dict[str, object]:
    """Drop the protocol's own fields from a head, leaving the conversation document."""
    return {key: value for key, value in raw.items() if key not in HEAD_INTERNAL_FIELDS}


def logged_of(stored: StoredEntry) -> LoggedEntry:
    """Read a stored entry (from the collection or an outbox) back as the log entry it holds."""
    fields = {k: v for k, v in stored.document().items() if k not in _POSITION_KEYS}
    return LoggedEntry(
        seq=stored.seq, at=committed_at(stored), entry=_ENTRY.validate_python(fields)
    )


def log_document(conversation_id: str, user_id: str, logged: LoggedEntry) -> dict[str, object]:
    """Return a log entry as its conversation_entries document stores it."""
    return {
        **logged.entry.model_dump(),
        "conversation_id": conversation_id,
        "user_id": user_id,
        "seq": logged.seq,
        "at": logged.at,
    }


def committed_at(stored: StoredEntry) -> datetime:
    """Return a stored entry's commit time; one without a commit time is corrupt."""
    if stored.at is None:
        raise ConversationStoreError(
            message="a stored conversation entry has no commit time",
            meta={"conversation_id": stored.conversation_id, "seq": str(stored.seq)},
        )
    return stored.at


def stored_row(raw: Mapping[str, object]) -> StoredRow:
    """Read a stored entry with the conversation it belongs to."""
    stored = StoredEntry.model_validate(raw)
    return StoredRow(conversation_id=stored.conversation_id, logged=logged_of(stored))


def at_its_seq(entry: StoredEntry) -> dict[str, object]:
    """Match the stored entry holding this entry's seq in its conversation."""
    return {"user_id": entry.user_id, "conversation_id": entry.conversation_id, "seq": entry.seq}


def is_same_entry(stored: Mapping[str, object] | None, entry: StoredEntry) -> bool:
    """Whether stored is this entry (same id at its seq), so inserting it again found it flushed."""
    return stored is not None and EntryKey.model_validate(stored).id == entry.id


@contextmanager
def store_errors(operation: str) -> Iterator[None]:
    """Raise the repository's error instead of the driver's for a failed conversation-store call."""
    try:
        yield
    except PyMongoError as exc:
        raise ConversationStoreError(
            message=f"conversation store {operation} failed",
            why=str(exc),
            meta={"error_type": type(exc).__name__},
        ) from exc


def at_log_head(log_head: int) -> dict[str, object]:
    """Match a head still at log_head; an empty log also matches a head written before log_head existed."""
    return {LOG_HEAD_FIELD: log_head} if log_head else EMPTY_LOG


@dataclass(frozen=True)
class EntryWindow:
    """Which log entries of a conversation a read asks for: a seq range, the newest limit, these ids or replies.

    kinds narrows the read (every log kind by default); ids and reply_ids together match an
    entry with one of the ids or carrying one of the reply ids.
    """

    after_seq: int = 0
    before_seq: int | None = None
    limit: int | None = None
    newest_first: bool = False
    ids: Sequence[str] | None = None
    reply_ids: Sequence[str] | None = None
    kinds: frozenset[str] | None = None

    def upper(self, log_head: int) -> int:
        return log_head if self.before_seq is None else min(log_head, self.before_seq - 1)

    def seq_range(self, log_head: int) -> dict[str, int]:
        return {"$gt": self.after_seq, "$lte": self.upper(log_head)}

    def clauses(self) -> dict[str, object]:
        named = [
            *([{"id": {"$in": list(self.ids)}}] if self.ids is not None else []),
            *([{"reply_id": {"$in": list(self.reply_ids)}}] if self.reply_ids is not None else []),
        ]
        return {"kind": {"$in": sorted(self._kinds())}, **({"$or": named} if named else {})}

    def admits(self, entry: StoredEntry, log_head: int) -> bool:
        fields = entry.message_fields()
        in_range = self.after_seq < entry.seq <= self.upper(log_head)
        return in_range and fields.get("kind") in self._kinds() and self._names(entry.id, fields)

    def take(self, union: Mapping[int, StoredEntry]) -> list[StoredEntry]:
        seqs = sorted(union, reverse=True)
        if self.limit:
            seqs = seqs[: self.limit]
        if not self.newest_first:
            seqs.reverse()
        return [union[seq] for seq in seqs]

    def _kinds(self) -> frozenset[str]:
        return self.kinds if self.kinds is not None else frozenset(LOG_KINDS)

    def _names(self, entry_id: str, fields: Mapping[str, object]) -> bool:
        if self.ids is None and self.reply_ids is None:
            return True
        return entry_id in (self.ids or ()) or fields.get("reply_id") in (self.reply_ids or ())
