"""The stored shape of a conversation entry and its head, and the expressions the append protocol commits with.

An entry is one message as stored today, keyed by (user_id, conversation_id, seq)
and (user_id, conversation_id, id); id is the message's message_id. The head is the
conversations document: log_head is the highest committed seq and outbox holds the
committed entries not yet copied into conversation_entries.
"""

from __future__ import annotations

from collections.abc import Iterator, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime
import hashlib
import json

from pymongo.errors import PyMongoError

from app.constants.chat import CONVERSATION_ENTRIES_MIGRATION_SCRIPT
from app.models.chat_models import MessageModel
from app.models.conversation_models import (
    ConversationEntry,
    ConversationHead,
    EntryKey,
    StoredEntry,
)
from app.utils.errors import ConversationStoreError, UnmigratedConversationError

LOG_HEAD_FIELD = "log_head"
OUTBOX_FIELD = "outbox"
#: The fingerprint of the embedded array as the migration last copied it, so any later old-build write shows.
MIGRATED_FINGERPRINT_FIELD = "migrated_fingerprint"
#: On a migrated entry: each field's hash as its embedded element held it (verify and the merge compare them).
MIGRATION_FIELDS_FIELD = "migration_fields"
_EMBEDDED_FIELD = "_embedded"
#: Head fields that never reach a ConversationDocument (or the client it is returned to).
HEAD_INTERNAL_FIELDS = (
    "messages",
    LOG_HEAD_FIELD,
    OUTBOX_FIELD,
    MIGRATED_FINGERPRINT_FIELD,
    _EMBEDDED_FIELD,
)

#: A server-side hash of the whole embedded array: any append, trim or in-place edit changes it.
EMBEDDED_FINGERPRINT: dict[str, object] = {"$toHashedIndexKey": {"$ifNull": ["$messages", []]}}
#: Heads whose embedded array holds messages the entries do not: never migrated, or written since.
UNMIGRATED_HEADS: dict[str, object] = {
    "messages.0": {"$exists": True},
    "$or": [
        {LOG_HEAD_FIELD: {"$exists": False}},
        {"$expr": {"$ne": [EMBEDDED_FINGERPRINT, f"${MIGRATED_FINGERPRINT_FIELD}"]}},
    ],
}
#: Added to every head read so the refusal below needs no second query and never ships the array.
EMBEDDED_STATE_STAGE: dict[str, object] = {
    "$addFields": {
        _EMBEDDED_FIELD: {
            "count": {"$size": {"$ifNull": ["$messages", []]}},
            "fingerprint": EMBEDDED_FINGERPRINT,
        }
    }
}
DROP_EMBEDDED_STAGE: dict[str, object] = {"$project": {"messages": 0}}
#: Cards whose message is not committed yet wait on the head under this field, by message id;
#: a turn saves within itself, so ones a day old are dropped by the next commit.
FOLDED_CARDS_FIELD = "folded_cards"
FOLDED_CARDS_KEEP_SECONDS = 86_400
#: What an append reads of its head: identity, the log, and whether the migration caught up.
_APPEND_HEAD_FIELDS: dict[str, object] = {
    "conversation_id": 1,
    "user_id": 1,
    LOG_HEAD_FIELD: 1,
    OUTBOX_FIELD: 1,
    MIGRATED_FINGERPRINT_FIELD: 1,
    _EMBEDDED_FIELD: 1,
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

    def pending(self) -> list[ConversationEntry]:
        """Read the outbox's committed entries."""
        return [entry_of(entry) for entry in self.outbox.values()]


@dataclass(frozen=True)
class StoredRow:
    """A stored entry with what places it across conversations: whose, which, and when it was committed."""

    user_id: str
    conversation_id: str
    at: datetime
    entry: ConversationEntry


def head_from_raw(raw: Mapping[str, object]) -> Head:
    """Parse a head read, refusing one whose messages still live only in the embedded array."""
    document = ConversationHead.model_validate(raw)
    embedded = document.embedded
    if embedded is not None and embedded.count:
        migrated = document.log_head is not None
        if not migrated or document.migrated_fingerprint != embedded.fingerprint:
            raise unmigrated(f"conversation {document.conversation_id}")
    return Head(document=document, fields=head_fields(raw))


def head_with_existing(
    conversation_id: str, user_id: str, ids: Sequence[str], *, entries_collection: str
) -> list[dict[str, object]]:
    """Read the head, then which of ids the collection holds, in one aggregate.

    The $lookup runs after its head is read, so an entry flushed out of the outbox in
    between is still seen in the collection.
    """
    return [
        {"$match": {"conversation_id": conversation_id, "user_id": user_id}},
        EMBEDDED_STATE_STAGE,
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
    """Match the heads whose entries a cross-conversation read counts: migrated, and not excluded."""
    return {"$nor": [UNMIGRATED_HEADS, *([dict(excluding)] if excluding else [])]}


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
    """Build the refusal for messages that still live only in the embedded array, naming the script."""
    return UnmigratedConversationError(
        message=(
            f"{subject} has messages the entries migration has not copied: run "
            f"python -m {CONVERSATION_ENTRIES_MIGRATION_SCRIPT} --apply"
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


def content_hash(stored: Mapping[str, object]) -> str:
    """Hash a message as append commits it, so a retry can tell the same message from another under its id."""
    return hashlib.sha256(
        json.dumps(dict(stored), sort_keys=True, default=str).encode()
    ).hexdigest()


def entry_of(stored: StoredEntry) -> ConversationEntry:
    """Read a stored entry (from the collection or an outbox) back as a seq-tagged message."""
    return ConversationEntry.model_validate(
        {**stored.message_fields(), "message_id": stored.id, "seq": stored.seq}
    )


def stored_row(raw: Mapping[str, object]) -> StoredRow:
    """Read a stored entry with its owner, conversation and commit time; one without a commit time is corrupt."""
    stored = StoredEntry.model_validate(raw)
    if stored.at is None:
        raise ConversationStoreError(
            message="a stored conversation entry has no commit time",
            meta={"conversation_id": stored.conversation_id, "seq": str(stored.seq)},
        )
    return StoredRow(
        user_id=stored.user_id,
        conversation_id=stored.conversation_id,
        at=stored.at,
        entry=entry_of(stored),
    )


def at_its_seq(entry: StoredEntry) -> dict[str, object]:
    """Match the stored entry holding this entry's seq in its conversation."""
    return {"user_id": entry.user_id, "conversation_id": entry.conversation_id, "seq": entry.seq}


def is_same_entry(stored: Mapping[str, object] | None, entry: StoredEntry) -> bool:
    """Whether stored is this entry (same id at its seq), so inserting it again found it flushed."""
    return stored is not None and EntryKey.model_validate(stored).id == entry.id


def filled(message: MessageModel) -> list[dict[str, object]]:
    """Pipeline that replaces an entry's content with message, keeping its keys and the cards folded in since it opened."""
    data = stored_message(message)
    # The entry now holds this message: a retried append of it is the same save, not a conflict.
    committed = content_hash(data)
    own_cards = data.pop("tool_data", [])
    del data["id"]
    cleared = [
        name
        for name in MessageModel.model_fields
        # pinned is the user's mark on the message, not the turn's content.
        if name not in data and name not in ("message_id", "tool_data", "pinned")
    ]
    cards = {"$concatArrays": [{"$literal": own_cards}, {"$ifNull": ["$tool_data", []]}]}
    pipeline: list[dict[str, object]] = [
        {
            "$set": {
                **{key: {"$literal": value} for key, value in data.items()},
                CONTENT_HASH_FIELD: committed,
                "tool_data": {"$cond": [{"$eq": [cards, []]}, "$$REMOVE", cards]},
            }
        }
    ]
    if cleared:
        pipeline.append({"$unset": cleared})
    return pipeline


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

    def upper(self, log_head: int) -> int:
        return log_head if self.before_seq is None else min(log_head, self.before_seq - 1)

    def lower(self, log_head: int) -> int:
        # Seqs are dense, so the newest limit entries are the top limit seqs: a read of many heads
        # bounds each one in the query instead of fetching all and trimming.
        if self.limit and self.ids is None:
            return max(self.after_seq, self.upper(log_head) - self.limit)
        return self.after_seq

    def seq_range(self, log_head: int) -> dict[str, int]:
        return {"$gt": self.lower(log_head), "$lte": self.upper(log_head)}

    def id_clause(self) -> dict[str, object]:
        return {} if self.ids is None else {"id": {"$in": list(self.ids)}}

    def admits(self, entry: ConversationEntry, log_head: int) -> bool:
        in_range = self.lower(log_head) < entry.seq <= self.upper(log_head)
        return in_range and (self.ids is None or entry.message_id in self.ids)

    def take(self, union: Mapping[int, ConversationEntry]) -> list[ConversationEntry]:
        seqs = sorted(union, reverse=True)
        if self.limit:
            seqs = seqs[: self.limit]
        if not self.newest_first:
            seqs.reverse()
        return [union[seq] for seq in seqs]


def waiting_for(message_id: str) -> dict[str, object]:
    """Read the waiting-room entry for message_id, taking the id as a literal, never a path."""
    return {
        "$getField": {
            "field": {"$literal": message_id},
            "input": {"$ifNull": [f"${FOLDED_CARDS_FIELD}", {}]},
        }
    }


def absorbing(message_id: str, message: Mapping[str, object]) -> dict[str, object]:
    """Build the entry as committed, stamped at commit time unless it carries its own, its waiting cards after its tool_data.

    The entry itself is a $literal, so text that starts with "$" is never read as a path.
    """
    waiting = {"$getField": {"field": "cards", "input": waiting_for(message_id)}}
    tool_data = {
        "$concatArrays": [{"$ifNull": ["$$message.tool_data", []]}, {"$ifNull": [waiting, []]}]
    }
    return {
        "$let": {
            "vars": {"message": {"$literal": dict(message)}},
            "in": {
                "$mergeObjects": [
                    "$$message",
                    {
                        "at": {"$ifNull": ["$$message.at", "$$NOW"]},
                        "tool_data": {"$cond": [{"$eq": [tool_data, []]}, "$$REMOVE", tool_data]},
                    },
                ]
            },
        }
    }


def still_waiting(saved_ids: list[str]) -> dict[str, object]:
    """Keep the waiting room minus the cards these messages absorbed and any a day stale."""
    kept = {
        "$arrayToObject": {
            "$filter": {
                "input": {"$objectToArray": {"$ifNull": [f"${FOLDED_CARDS_FIELD}", {}]}},
                "as": "waiting",
                "cond": {
                    "$and": [
                        {"$not": [{"$in": ["$$waiting.k", {"$literal": saved_ids}]}]},
                        {
                            "$gt": [
                                "$$waiting.v.since",
                                {
                                    "$dateSubtract": {
                                        "startDate": "$$NOW",
                                        "unit": "second",
                                        "amount": FOLDED_CARDS_KEEP_SECONDS,
                                    }
                                },
                            ]
                        },
                    ]
                },
            }
        }
    }
    return {
        "$let": {
            "vars": {"kept": kept},
            "in": {"$cond": [{"$eq": ["$$kept", {}]}, "$$REMOVE", "$$kept"]},
        }
    }


def parked(message_id: str, cards: Sequence[Mapping[str, object]]) -> dict[str, object]:
    """Return the waiting room with these cards added under message_id, keeping when it first waited."""
    waiting = waiting_for(message_id)
    return {
        "$setField": {
            "field": {"$literal": message_id},
            "input": {"$ifNull": [f"${FOLDED_CARDS_FIELD}", {}]},
            "value": {
                "since": {
                    "$ifNull": [{"$getField": {"field": "since", "input": waiting}}, "$$NOW"]
                },
                "cards": {
                    "$concatArrays": [
                        {"$ifNull": [{"$getField": {"field": "cards", "input": waiting}}, []]},
                        {"$literal": [dict(card) for card in cards]},
                    ]
                },
            },
        }
    }
