"""The stored shape of a conversation entry and the head expressions the append protocol commits with.

An entry is one message as stored today, or one conversation log entry told apart by its
kind (is_log_entry), keyed by (user_id, conversation_id, seq) and (user_id,
conversation_id, id); a message's id is its message_id. The head is the
conversations document: log_head is the highest committed seq and outbox holds the
committed entries not yet copied into conversation_entries.
"""

from __future__ import annotations

from collections.abc import Iterator, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass, field

from pydantic import BaseModel, ConfigDict
from pymongo.errors import PyMongoError

from app.constants.chat import (
    CONVERSATION_ENTRIES_MIGRATION_SCRIPT,
    FOLDED_CARDS_FIELD,
    FOLDED_CARDS_KEEP_SECONDS,
)
from app.models.chat_models import MessageModel
from app.models.conversation_log_models import EntryKind
from app.models.conversation_models import ConversationEntry
from app.utils.errors import ConversationStoreError, UnmigratedConversationError

LOG_HEAD_FIELD = "log_head"
OUTBOX_FIELD = "outbox"
#: The conversation log's fold, its step holder {epoch, alive_key} and the last epoch handed out.
STATE_FIELD = "state"
RUNNER_FIELD = "runner"
RUNNER_EPOCH_FIELD = "runner_epoch"
#: On an amendable log entry (a reply, a user message): bumped by each amend, staged through the outbox.
REVISION_FIELD = "revision"
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
    STATE_FIELD,
    RUNNER_FIELD,
    RUNNER_EPOCH_FIELD,
    MIGRATED_LAST_ID_FIELD,
    _EMBEDDED_FIELD,
)
_ENTRY_KEY_FIELDS = ("_id", "conversation_id", "user_id", "seq", "id", "at", MIGRATION_HASH_FIELD)
#: The kinds the conversation log appends; a stored entry with any other kind, or none, is a message.
LOG_KINDS: list[str] = [kind.value for kind in EntryKind]
MESSAGES_ONLY: dict[str, object] = {"kind": {"$nin": LOG_KINDS}}
LOG_ENTRIES_ONLY: dict[str, object] = {"kind": {"$in": LOG_KINDS}}

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


class _Revisioned(BaseModel):
    model_config = ConfigDict(extra="ignore")

    revision: int | None = None


def revision_of(entry: Mapping[str, object]) -> int | None:
    """Return an amendable log entry's revision; None for an entry no amend ever changes."""
    return _Revisioned.model_validate(entry).revision


def newest(
    stored: Mapping[str, object] | None, staged: Mapping[str, object]
) -> Mapping[str, object]:
    """Pick the copy of one entry a read returns: the staged one unless the collection already holds its revision."""
    if stored is None:
        return staged
    staged_revision = revision_of(staged)
    if staged_revision is None:
        return stored
    stored_revision = revision_of(stored)
    return staged if stored_revision is None or staged_revision > stored_revision else stored


def is_log_entry(raw: Mapping[str, object]) -> bool:
    """Whether a stored entry is one the conversation log appended rather than a message."""
    return raw.get("kind") in LOG_KINDS


def head_from_raw(raw: Mapping[str, object]) -> Head:
    """Parse a head read, refusing one whose messages still live only in the embedded array."""
    data = dict(raw)
    embedded = data.get(_EMBEDDED_FIELD)
    count = embedded.get("count", 0) if isinstance(embedded, Mapping) else 0
    if count:
        last_id = embedded.get("last_id") if isinstance(embedded, Mapping) else None
        if LOG_HEAD_FIELD not in data or data.get(MIGRATED_LAST_ID_FIELD) != last_id:
            raise unmigrated(f"conversation {data.get('conversation_id')}")
    outbox_raw = data.get(OUTBOX_FIELD)
    outbox = (
        {int(seq): dict(entry) for seq, entry in outbox_raw.items()}
        if isinstance(outbox_raw, Mapping)
        else {}
    )
    existing_raw = data.pop("existing", [])
    existing = (
        {str(row["id"]): int(row["seq"]) for row in existing_raw}
        if isinstance(existing_raw, list)
        else {}
    )
    log_head = data.get(LOG_HEAD_FIELD, 0)
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
    message["seq"] = raw["seq"]
    return ConversationEntry.model_validate(message)


def filled(message: MessageModel) -> list[dict[str, object]]:
    """Pipeline that replaces an entry's content with message, keeping its keys and the cards folded in since it opened."""
    data = stored_message(message)
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


def waiting_for(message_id: str) -> dict[str, object]:
    """Read the waiting-room entry for message_id, taking the id as a literal, never a path."""
    return {
        "$getField": {
            "field": {"$literal": message_id},
            "input": {"$ifNull": [f"${FOLDED_CARDS_FIELD}", {}]},
        }
    }


def absorbing(message_id: str, entry: Mapping[str, object]) -> dict[str, object]:
    """Build the entry as committed: stamped at commit time, the cards waiting for its id after its own tool_data.

    The entry itself is a $literal, so text that starts with "$" is never read as a path.
    """
    waiting = {"$getField": {"field": "cards", "input": waiting_for(message_id)}}
    tool_data = {
        "$concatArrays": [{"$ifNull": ["$$entry.tool_data", []]}, {"$ifNull": [waiting, []]}]
    }
    return {
        "$let": {
            "vars": {"entry": {"$literal": dict(entry)}},
            "in": {
                "$mergeObjects": [
                    "$$entry",
                    {
                        "at": "$$NOW",
                        "tool_data": {"$cond": [{"$eq": [tool_data, []]}, "$$REMOVE", tool_data]},
                    },
                ]
            },
        }
    }


def still_waiting(saved_ids: Sequence[str]) -> dict[str, object]:
    """Keep the waiting room minus the cards these messages absorbed and any a day stale."""
    kept = {
        "$arrayToObject": {
            "$filter": {
                "input": {"$objectToArray": {"$ifNull": [f"${FOLDED_CARDS_FIELD}", {}]}},
                "as": "waiting",
                "cond": {
                    "$and": [
                        {"$not": [{"$in": ["$$waiting.k", {"$literal": list(saved_ids)}]}]},
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


def at_log_head(log_head: int) -> dict[str, object]:
    """Match a head still at log_head; an empty log also matches a head written before log_head existed."""
    if log_head:
        return {LOG_HEAD_FIELD: log_head}
    return {
        "$or": [
            {LOG_HEAD_FIELD: 0},
            {LOG_HEAD_FIELD: {"$exists": False}, "messages.0": {"$exists": False}},
        ]
    }


@dataclass(frozen=True)
class EntryWindow:
    """Which entries of a conversation a read asks for: a seq range, the newest limit, or these ids.

    A window reads messages, or with log the conversation log's own entries; never both.
    """

    after_seq: int = 0
    before_seq: int | None = None
    limit: int | None = None
    newest_first: bool = False
    ids: Sequence[str] | None = None
    log: bool = False

    def seq_range(self, log_head: int) -> dict[str, int]:
        upper = log_head if self.before_seq is None else min(log_head, self.before_seq - 1)
        return {"$gt": self.after_seq, "$lte": upper}

    def clauses(self) -> dict[str, object]:
        kinds = LOG_ENTRIES_ONLY if self.log else MESSAGES_ONLY
        return {**kinds, **({} if self.ids is None else {"id": {"$in": list(self.ids)}})}

    def admits(self, seq: int, entry: Mapping[str, object], log_head: int) -> bool:
        bounds = self.seq_range(log_head)
        in_range = bounds["$gt"] < seq <= bounds["$lte"]
        wanted = is_log_entry(entry) is self.log
        return in_range and wanted and (self.ids is None or str(entry["id"]) in self.ids)

    def take(self, union: Mapping[int, Mapping[str, object]]) -> list[Mapping[str, object]]:
        seqs = sorted(union, reverse=True)
        if self.limit:
            seqs = seqs[: self.limit]
        if not self.newest_first:
            seqs.reverse()
        return [union[seq] for seq in seqs]
