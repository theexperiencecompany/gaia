"""Moves each conversation's embedded messages array into conversation_entries and verifies it.

Per conversation, by its head's _id: an element with no message_id, or one repeating an
earlier element's, first gets a fresh ObjectId written back into the array, so every
element has a real, unique, stable id. The first pass then copies element i to seq i+1;
a later pass merges, by id, what the old build wrote since: new elements are appended
through the one seq allocator, and only the fields the old build changed are rewritten.
Every write is conditional on the array's server-side fingerprint, so a write the old
build makes meanwhile is never lost: the pass reports RACED and the next one takes it.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
import hashlib
import json

from bson import ObjectId

from app.constants.chat import CONVERSATION_ENTRIES_COLLECTION
from app.db.repositories.conversation_entries import (
    EMBEDDED_FINGERPRINT,
    LOG_HEAD_FIELD,
    MIGRATED_FINGERPRINT_FIELD,
    MIGRATION_FIELDS_FIELD,
    UNMIGRATED_HEADS,
    store_errors,
)
from app.db.repositories.conversations import ConversationRepository
from app.models.conversation_models import (
    ConversationHead,
    HeadRefRow,
    LegacyMessage,
    StoredEntry,
)

#: A scan reads only what a HeadRef holds, never the embedded array it is about to copy.
_HEAD_REF_STAGE: dict[str, object] = {
    "$project": {
        "_id": 0,
        "head_id": {"$toString": "$_id"},
        "conversation_id": 1,
        "user_id": 1,
    }
}
_BY_HEAD_ID: dict[str, object] = {"$sort": {"_id": 1}}
_BY_SEQ: list[tuple[str, int]] = [("seq", 1)]
_FINGERPRINT = "_fingerprint"
_UNSET_EMBEDDED: dict[str, object] = {"messages": "", MIGRATED_FINGERPRINT_FIELD: ""}
_ID_FIELD = "message_id"


class MigrationAction(StrEnum):
    """What a pass did, or would do, to one conversation."""

    COPIED = "copied"
    MERGED = "merged"
    UNCHANGED = "unchanged"
    RACED = "raced"


@dataclass
class MigrationOutcome:
    """One conversation's result: the action and the counts behind it."""

    conversation_id: str
    action: MigrationAction
    copied: int = 0
    rewritten: int = 0
    identified: int = 0
    reason: str = ""


@dataclass
class VerifyReport:
    """One conversation's verify result: every embedded element is an entry, in order, unchanged."""

    conversation_id: str
    embedded: int
    entries: int
    fingerprint: int | None = None
    mismatches: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.mismatches


@dataclass(frozen=True)
class HeadRef:
    """The head a pass works on: its _id (the resume cursor) and identity."""

    head_id: str
    conversation_id: str
    user_id: str


@dataclass(frozen=True)
class _EmbeddedHead:
    """A head as a pass reads it: the parsed array and its fingerprint at that read."""

    head: ConversationHead
    fingerprint: int


def field_hashes(element: Mapping[str, object]) -> dict[str, str]:
    """Hash each of an element's fields (its id aside) canonically, so a later read hashes the same."""
    return {
        key: hashlib.sha256(json.dumps(value, sort_keys=True, default=str).encode()).hexdigest()
        for key, value in element.items()
        if key != _ID_FIELD
    }


def minted_ids(elements: Sequence[LegacyMessage]) -> list[str | None]:
    """Return a fresh id for each element with none or one an earlier element holds, None for the rest."""
    seen: set[str] = set()
    minted: list[str | None] = []
    for element in elements:
        if element.message_id and element.message_id not in seen:
            seen.add(element.message_id)
            minted.append(None)
        else:
            minted.append(str(ObjectId()))
    return minted


def entry_at(date: object) -> datetime:
    """Return when an embedded element was written: its ISO date (a naive one read as UTC), else now."""
    if not isinstance(date, str):
        return datetime.now(UTC)
    try:
        parsed = datetime.fromisoformat(date)
    except ValueError:
        return datetime.now(UTC)
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def _of(ref: HeadRef) -> dict[str, str]:
    """Match the entries of ref's conversation."""
    return {"user_id": ref.user_id, "conversation_id": ref.conversation_id}


def _with_ids(minted: Sequence[str | None]) -> dict[str, object]:
    """Write each minted id into its element in place, leaving every other element as it is."""
    return {
        "$map": {
            "input": {"$range": [0, {"$size": "$messages"}]},
            "as": "i",
            "in": {
                "$let": {
                    "vars": {
                        "element": {"$arrayElemAt": ["$messages", "$$i"]},
                        "minted": {"$arrayElemAt": [{"$literal": list(minted)}, "$$i"]},
                    },
                    "in": {
                        "$cond": [
                            {"$eq": ["$$minted", None]},
                            "$$element",
                            {"$mergeObjects": ["$$element", {_ID_FIELD: "$$minted"}]},
                        ]
                    },
                }
            },
        }
    }


def _changed_fields(entry: StoredEntry, element: Mapping[str, object]) -> dict[str, object]:
    """Return the update that takes only the fields the old build changed since this entry was copied."""
    copied = entry.migration_fields or {}
    now = field_hashes(element)
    changed = {key: element[key] for key, digest in now.items() if copied.get(key) != digest}
    removed = {key: "" for key in copied if key not in now}
    update: dict[str, object] = {"$set": {**changed, MIGRATION_FIELDS_FIELD: now}}
    if removed:
        update["$unset"] = removed
    return update


class ConversationEntriesMigration(ConversationRepository):
    """The entries migration's reads and writes of the conversations heads and their entries."""

    async def heads_to_migrate(self, *, after_head_id: str | None, batch: int) -> list[HeadRef]:
        """Return the next batch of heads whose embedded array the entries do not match yet.

        Compares the array's fingerprint, so an in-place edit by the old build is seen
        whether or not it advanced updatedAt.
        """
        return await self._scan(dict(UNMIGRATED_HEADS), after_head_id=after_head_id, batch=batch)

    async def heads_with_embedded(self, *, after_head_id: str | None, batch: int) -> list[HeadRef]:
        """Return the next batch of heads still holding an embedded array, in _id order after after_head_id."""
        match: dict[str, object] = {"messages.0": {"$exists": True}}
        return await self._scan(match, after_head_id=after_head_id, batch=batch)

    async def migrate(self, ref: HeadRef, *, apply: bool) -> MigrationOutcome:
        """Copy or merge one conversation's embedded array into its entries (only report when not apply)."""
        read = await self._embedded_head(ref)
        if read is None:
            return MigrationOutcome(
                ref.conversation_id, MigrationAction.UNCHANGED, reason="deleted since the scan"
            )
        minted = minted_ids(read.head.messages)
        identified = sum(entry_id is not None for entry_id in minted)
        if identified:
            if not apply:
                outcome = await self._plan(ref, read.head)
                outcome.identified = identified
                return outcome
            if not await self._identify(ref, read.fingerprint, minted):
                return MigrationOutcome(ref.conversation_id, MigrationAction.RACED)
            read = await self._embedded_head(ref)
            if read is None:
                return MigrationOutcome(ref.conversation_id, MigrationAction.RACED)
        outcome = await self._apply(ref, read) if apply else await self._plan(ref, read.head)
        outcome.identified = identified
        return outcome

    async def verify(self, ref: HeadRef) -> VerifyReport:
        """Compare the embedded array with the entries: each element present, in order, unchanged since copied."""
        await self.flush_outbox(ref.conversation_id, user_id=ref.user_id)
        read = await self._embedded_head(ref)
        elements = read.head.messages if read else []
        entries = await self._stored(ref)
        by_id = {entry.id: entry for entry in entries}
        report = VerifyReport(ref.conversation_id, embedded=len(elements), entries=len(entries))
        if read is None or read.head.log_head is None:
            report.mismatches.append("not migrated: no log_head")
            return report
        report.fingerprint = read.fingerprint
        if read.head.migrated_fingerprint != read.fingerprint:
            report.mismatches.append("written by the old build since its last pass: run --apply")
        seqs: list[int] = []
        for element in elements:
            entry = by_id.get(element.message_id or "")
            if entry is None:
                report.mismatches.append(f"{element.message_id} has no entry")
                continue
            seqs.append(entry.seq)
            if entry.migration_fields != field_hashes(element.stored()):
                report.mismatches.append(f"{element.message_id} differs from its entry")
        if seqs != sorted(seqs):
            report.mismatches.append("the entries are not in the embedded array's order")
        return report

    async def drop_embedded(self, ref: HeadRef, *, verified: int) -> bool:
        """Unset the embedded array, only while it is exactly the array a passing verify fingerprinted."""
        with store_errors("drop embedded"):  # pragma: no mutate — error label only
            result = await self._raw_collection().update_one(
                {
                    "_id": ObjectId(ref.head_id),
                    MIGRATED_FINGERPRINT_FIELD: verified,
                    "$expr": {"$eq": [EMBEDDED_FINGERPRINT, verified]},
                },
                {"$unset": _UNSET_EMBEDDED},
            )
        return result.modified_count > 0

    async def _scan(
        self, match: dict[str, object], *, after_head_id: str | None, batch: int
    ) -> list[HeadRef]:
        if after_head_id is not None:
            match["_id"] = {"$gt": ObjectId(after_head_id)}
        pipeline: list[Mapping[str, object]] = [
            {"$match": match},
            _BY_HEAD_ID,
            {"$limit": batch},
            _HEAD_REF_STAGE,
        ]
        with store_errors("migration scan"):  # pragma: no mutate — error label only
            rows = await self._aggregate(pipeline, HeadRefRow)
        return [HeadRef(row.head_id, row.conversation_id, row.user_id) for row in rows]

    async def _embedded_head(self, ref: HeadRef) -> _EmbeddedHead | None:
        pipeline: list[Mapping[str, object]] = [
            {"$match": {"_id": ObjectId(ref.head_id)}},
            {"$addFields": {_FINGERPRINT: EMBEDDED_FINGERPRINT}},
        ]
        with store_errors("migration read"):  # pragma: no mutate — error label only
            raws = await self._raw_collection().aggregate(pipeline).to_list(length=None)
        if not raws:
            return None
        return _EmbeddedHead(ConversationHead.model_validate(raws[0]), int(raws[0][_FINGERPRINT]))

    async def _stored(self, ref: HeadRef) -> list[StoredEntry]:
        with store_errors("migration read"):  # pragma: no mutate — error label only
            rows = (
                await self._sibling_collection(CONVERSATION_ENTRIES_COLLECTION)
                .find(_of(ref))
                .sort(_BY_SEQ)
                .to_list(None)
            )
        return [StoredEntry.model_validate(row) for row in rows]

    async def _identify(self, ref: HeadRef, fingerprint: int, minted: Sequence[str | None]) -> bool:
        """Write the minted ids into the array, only while it is still the array they were minted for."""
        with store_errors("migration identify"):  # pragma: no mutate — error label only
            result = await self._raw_collection().update_one(
                {
                    "_id": ObjectId(ref.head_id),
                    "$expr": {"$eq": [EMBEDDED_FINGERPRINT, fingerprint]},
                },
                [{"$set": {"messages": _with_ids(minted)}}],
            )
        return result.modified_count > 0

    def _entry(self, ref: HeadRef, element: LegacyMessage) -> dict[str, object]:
        """Return the element as its entry stores it, minus the seq its caller assigns."""
        stored = element.stored()
        payload = {k: v for k, v in stored.items() if k != _ID_FIELD}
        return {
            **payload,
            **_of(ref),
            "id": element.message_id,
            "at": entry_at(element.date),
            MIGRATION_FIELDS_FIELD: field_hashes(stored),
        }

    async def _plan(self, ref: HeadRef, head: ConversationHead) -> MigrationOutcome:
        """Report what a pass would do, writing nothing."""
        if head.log_head is None:
            return MigrationOutcome(
                ref.conversation_id, MigrationAction.COPIED, copied=len(head.messages)
            )
        by_id = {entry.id: entry for entry in await self._stored(ref)}
        fresh = [e for e in head.messages if e.message_id not in by_id]
        changed = [
            e
            for e in head.messages
            if e.message_id in by_id
            and by_id[e.message_id].migration_fields != field_hashes(e.stored())
        ]
        return MigrationOutcome(
            ref.conversation_id, MigrationAction.MERGED, copied=len(fresh), rewritten=len(changed)
        )

    async def _apply(self, ref: HeadRef, read: _EmbeddedHead) -> MigrationOutcome:
        if read.head.log_head is None:
            if not await self._copy(ref, read):
                return MigrationOutcome(ref.conversation_id, MigrationAction.RACED)
            return MigrationOutcome(
                ref.conversation_id, MigrationAction.COPIED, copied=len(read.head.messages)
            )
        return await self._merge(ref, read)

    async def _copy(self, ref: HeadRef, read: _EmbeddedHead) -> bool:
        """First pass: entries at seq 1..n, then log_head, if the array is still the one copied.

        No append reaches an unmigrated head, so its entries can only be a pass that
        died before marking: they are replaced, never merged.
        """
        entries = [
            {**self._entry(ref, element), "seq": seq}
            for seq, element in enumerate(read.head.messages, 1)
        ]
        with store_errors("migration copy"):  # pragma: no mutate — error label only
            await self._sibling_collection(CONVERSATION_ENTRIES_COLLECTION).delete_many(_of(ref))
            await self._sibling_collection(CONVERSATION_ENTRIES_COLLECTION).insert_many(entries)
            result = await self._raw_collection().update_one(
                {
                    "_id": ObjectId(ref.head_id),
                    LOG_HEAD_FIELD: {"$exists": False},
                    "$expr": {"$eq": [EMBEDDED_FINGERPRINT, read.fingerprint]},
                },
                {
                    "$set": {
                        LOG_HEAD_FIELD: len(entries),
                        MIGRATED_FINGERPRINT_FIELD: read.fingerprint,
                    }
                },
            )
        return result.modified_count > 0

    async def _merge(self, ref: HeadRef, read: _EmbeddedHead) -> MigrationOutcome:
        """Later pass: append elements the entries lack, take the fields the old build changed, then re-mark."""
        head = read.head
        await self.flush_outbox(ref.conversation_id, user_id=ref.user_id)
        by_id = {entry.id: entry for entry in await self._stored(ref)}
        fresh = [e for e in head.messages if e.message_id not in by_id]
        changed = [
            e
            for e in head.messages
            if e.message_id in by_id
            and by_id[e.message_id].migration_fields != field_hashes(e.stored())
        ]
        if not fresh and not changed and head.migrated_fingerprint == read.fingerprint:
            return MigrationOutcome(ref.conversation_id, MigrationAction.UNCHANGED)
        with store_errors("migration merge"):  # pragma: no mutate — error label only
            for element in changed:
                await self._sibling_collection(CONVERSATION_ENTRIES_COLLECTION).update_one(
                    {**_of(ref), "id": element.message_id},
                    _changed_fields(by_id[str(element.message_id)], element.stored()),
                )
        if fresh:
            log_head = head.log_head or 0
            seqs = {str(e.message_id): log_head + n for n, e in enumerate(fresh, 1)}
            appended = [(str(e.message_id), self._entry(ref, e)) for e in fresh]
            if not await self._commit(ref.conversation_id, ref.user_id, log_head, appended, seqs):
                return MigrationOutcome(ref.conversation_id, MigrationAction.RACED)
            await self.flush_outbox(ref.conversation_id, user_id=ref.user_id)
        with store_errors("migration merge"):  # pragma: no mutate — error label only
            marked = await self._raw_collection().update_one(
                {
                    "_id": ObjectId(ref.head_id),
                    "$expr": {"$eq": [EMBEDDED_FINGERPRINT, read.fingerprint]},
                },
                {"$set": {MIGRATED_FINGERPRINT_FIELD: read.fingerprint}},
            )
        if not marked.matched_count:
            return MigrationOutcome(ref.conversation_id, MigrationAction.RACED)
        return MigrationOutcome(
            ref.conversation_id, MigrationAction.MERGED, copied=len(fresh), rewritten=len(changed)
        )


conversation_entries_migration = ConversationEntriesMigration()
