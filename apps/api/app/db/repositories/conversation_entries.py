"""The stored shape of a conversation entry and its head: the one place their raw documents are read.

An entry is one message as stored today, keyed by (user_id, conversation_id, seq)
and (user_id, conversation_id, id); id is the message's message_id. The head is the
conversations document: log_head is the highest committed seq and outbox holds the
committed entries not yet copied into conversation_entries.
"""

from __future__ import annotations

from collections.abc import Iterator, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime

from pymongo.errors import PyMongoError

from app.constants.chat import CONVERSATION_ENTRIES_MIGRATION_SCRIPT
from app.models.chat_models import MessageModel
from app.models.conversation_models import ConversationEntry
from app.utils.errors import ConversationStoreError, UnmigratedConversationError

LOG_HEAD_FIELD = "log_head"
OUTBOX_FIELD = "outbox"
#: The message_id the migration last copied from the embedded array, so a later write by the old build shows.
MIGRATED_LAST_ID_FIELD = "migrated_last_id"
#: On a migrated entry: the hash of the embedded element it was copied from (verify compares it).
MIGRATION_HASH_FIELD = "migration_hash"
_EMBEDDED_FIELD = "_embedded"
#: Head fields that never reach a ConversationDocument (or the client it is returned to).
HEAD_INTERNAL_FIELDS = (
    "messages",
    LOG_HEAD_FIELD,
    OUTBOX_FIELD,
    MIGRATED_LAST_ID_FIELD,
    _EMBEDDED_FIELD,
)
_ENTRY_KEY_FIELDS = ("_id", "conversation_id", "user_id", "seq", "id", "at", MIGRATION_HASH_FIELD)

#: The last embedded message_id, as the migration records it; missing when the array holds none.
EMBEDDED_LAST_ID: dict[str, object] = {
    "$arrayElemAt": [{"$ifNull": ["$messages.message_id", []]}, -1]
}
#: Heads whose embedded array holds messages the entries do not: never migrated, or written since.
UNMIGRATED_HEADS: dict[str, object] = {
    "messages.0": {"$exists": True},
    "$or": [
        {LOG_HEAD_FIELD: {"$exists": False}},
        {"$expr": {"$ne": [EMBEDDED_LAST_ID, f"${MIGRATED_LAST_ID_FIELD}"]}},
    ],
}
#: Added to every head read so the refusal below needs no second query and never ships the array.
EMBEDDED_STATE_STAGE: dict[str, object] = {
    "$addFields": {
        _EMBEDDED_FIELD: {
            "count": {"$size": {"$ifNull": ["$messages", []]}},
            "last_id": EMBEDDED_LAST_ID,
        }
    }
}
DROP_EMBEDDED_STAGE: dict[str, object] = {"$project": {"messages": 0}}
#: A head the protocol may commit on at log_head 0: empty, or written before log_head existed with no messages.
EMPTY_LOG: dict[str, object] = {
    "$or": [
        {LOG_HEAD_FIELD: 0},
        {LOG_HEAD_FIELD: {"$exists": False}, "messages.0": {"$exists": False}},
    ]
}


@dataclass
class Head:
    """A conversation head as the protocol reads it: its document fields, log_head and outbox."""

    raw: dict[str, object]
    log_head: int
    outbox: dict[int, dict[str, object]] = field(default_factory=dict)
    existing: dict[str, int] = field(default_factory=dict)

    @property
    def conversation_id(self) -> str:
        return str(self.raw["conversation_id"])

    @property
    def user_id(self) -> str:
        return str(self.raw["user_id"])

    def known_seqs(self) -> dict[str, int]:
        """Every entry id this head's reads saw, outbox and collection both, by seq."""
        return {**self.existing, **{str(e["id"]): seq for seq, e in self.outbox.items()}}

    def pending(self) -> list[ConversationEntry]:
        """Read the outbox's committed entries."""
        return [entry_from_raw(entry) for entry in self.outbox.values()]


@dataclass(frozen=True)
class StoredRow:
    """A stored entry with what places it across conversations: whose, which, and when it was committed."""

    user_id: str
    conversation_id: str
    at: datetime
    entry: ConversationEntry


def head_from_raw(raw: Mapping[str, object]) -> Head:
    """Parse a head read, refusing one whose messages still live only in the embedded array."""
    data = dict(raw)
    embedded = data.get(_EMBEDDED_FIELD)
    if isinstance(embedded, Mapping) and embedded.get("count"):
        migrated = LOG_HEAD_FIELD in data
        if not migrated or data.get(MIGRATED_LAST_ID_FIELD) != embedded.get("last_id"):
            raise unmigrated(f"conversation {data.get('conversation_id')}")
    outbox_raw = data.get(OUTBOX_FIELD)
    outbox = (
        {int(seq): dict(entry) for seq, entry in outbox_raw.items()}
        if isinstance(outbox_raw, Mapping)
        else {}
    )
    existing_raw = data.get("existing")
    existing = (
        {str(row["id"]): int(row["seq"]) for row in existing_raw}
        if isinstance(existing_raw, list)
        else {}
    )
    log_head = data.get(LOG_HEAD_FIELD)
    return Head(
        raw=data,
        log_head=log_head if isinstance(log_head, int) else 0,
        outbox=outbox,
        existing=existing,
    )


def unmigrated(subject: str) -> UnmigratedConversationError:
    """Build the refusal for messages that still live only in the embedded array, naming the script."""
    return UnmigratedConversationError(
        message=(
            f"{subject} has messages the entries migration has not copied: run "
            f"python -m {CONVERSATION_ENTRIES_MIGRATION_SCRIPT} --apply (or --since for a second pass)"
        ),
        why="its messages still live only in the embedded messages array",
    )


def head_fields(raw: Mapping[str, object]) -> dict[str, object]:
    """Drop the protocol's own fields from a head, leaving the conversation document."""
    return {key: value for key, value in raw.items() if key not in HEAD_INTERNAL_FIELDS}


def stored_message(message: MessageModel) -> dict[str, object]:
    """Return the message as an entry stores it: today's fields, with id in place of message_id."""
    data = {k: v for k, v in message.model_dump().items() if v is not None}
    data["id"] = data.pop("message_id")
    return data


def entry_from_raw(raw: Mapping[str, object]) -> ConversationEntry:
    """Read a stored entry (from the collection or an outbox) back as a seq-tagged message."""
    message = {k: v for k, v in raw.items() if k not in _ENTRY_KEY_FIELDS}
    message["message_id"] = raw["id"]
    return ConversationEntry.model_validate({"seq": raw["seq"], "message": message})


def stored_row(raw: Mapping[str, object]) -> StoredRow:
    """Read a stored entry with its owner, conversation and commit time; one without a commit time is corrupt."""
    at = raw.get("at")
    if not isinstance(at, datetime):
        raise ConversationStoreError(
            message="a stored conversation entry has no commit time",
            meta={"conversation_id": str(raw.get("conversation_id")), "seq": str(raw.get("seq"))},
        )
    return StoredRow(
        user_id=str(raw["user_id"]),
        conversation_id=str(raw["conversation_id"]),
        at=at,
        entry=entry_from_raw(raw),
    )


def at_its_seq(entry: Mapping[str, object]) -> dict[str, object]:
    """Match the stored entry holding this entry's seq in its conversation."""
    return {
        "user_id": entry["user_id"],
        "conversation_id": entry["conversation_id"],
        "seq": entry["seq"],
    }


def is_same_entry(stored: Mapping[str, object] | None, entry: Mapping[str, object]) -> bool:
    """Whether stored is this entry (same id at its seq), so inserting it again found it flushed."""
    return stored is not None and stored.get("id") == entry["id"]


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
    """Which entries of a conversation a read asks for: a seq range, the newest limit, or these ids."""

    after_seq: int = 0
    before_seq: int | None = None
    limit: int | None = None
    newest_first: bool = False
    ids: Sequence[str] | None = None

    def seq_range(self, log_head: int) -> dict[str, int]:
        upper = log_head if self.before_seq is None else min(log_head, self.before_seq - 1)
        return {"$gt": self.after_seq, "$lte": upper}

    def id_clause(self) -> dict[str, object]:
        return {} if self.ids is None else {"id": {"$in": list(self.ids)}}

    def admits(self, entry: ConversationEntry, log_head: int) -> bool:
        bounds = self.seq_range(log_head)
        in_range = bounds["$gt"] < entry.seq <= bounds["$lte"]
        return in_range and (self.ids is None or entry.message.message_id in self.ids)

    def take(self, union: Mapping[int, ConversationEntry]) -> list[ConversationEntry]:
        seqs = sorted(union, reverse=True)
        if self.limit:
            seqs = seqs[: self.limit]
        if not self.newest_first:
            seqs.reverse()
        return [union[seq] for seq in seqs]
