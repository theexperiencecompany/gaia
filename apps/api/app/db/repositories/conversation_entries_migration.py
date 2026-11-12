"""Moves each conversation's embedded messages array into conversation_entries, verifies it, and undoes it.

Per conversation, by its head's _id: the first pass copies element i to seq i+1 and
records the last copied message_id on the head. A later pass merges, by message id,
what the old build wrote since: new elements are appended through the one seq
allocator, changed ones (their migration_hash differs) are rewritten. Each entry keeps
the hash of the element it was copied from, which is what verify compares.
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
    EMBEDDED_LAST_ID,
    LOG_HEAD_FIELD,
    MIGRATED_LAST_ID_FIELD,
    MIGRATION_HASH_FIELD,
    OUTBOX_FIELD,
    store_errors,
)
from app.db.repositories.conversations import ConversationRepository

#: The id given to a legacy element stored without a message_id: stable, so every pass agrees.
_LEGACY_ID_PREFIX = "legacy-"
#: A scan reads only what a HeadRef holds, never the embedded array it is about to copy.
_HEAD_REF_FIELDS: dict[str, object] = {"_id": 1, "conversation_id": 1, "user_id": 1}
_BY_HEAD_ID: list[tuple[str, int]] = [("_id", 1)]
_BY_SEQ: list[tuple[str, int]] = [("seq", 1)]
#: Fields an entry carries that the embedded element it came from did not.
_ENTRY_ONLY_FIELDS = frozenset(
    {"_id", "conversation_id", "user_id", "seq", "at", "id", MIGRATION_HASH_FIELD}
)
_UNSET_EMBEDDED: dict[str, object] = {"messages": "", MIGRATED_LAST_ID_FIELD: ""}
_UNSET_LOG: dict[str, object] = {LOG_HEAD_FIELD: "", OUTBOX_FIELD: "", MIGRATED_LAST_ID_FIELD: ""}


class MigrationAction(StrEnum):
    """What a pass did, or would do, to one conversation."""

    COPIED = "copied"
    MERGED = "merged"
    UNCHANGED = "unchanged"
    REFUSED = "refused"
    RACED = "raced"


@dataclass
class MigrationOutcome:
    """One conversation's result: the action and the counts behind it."""

    conversation_id: str
    action: MigrationAction
    copied: int = 0
    rewritten: int = 0
    reason: str = ""


@dataclass
class VerifyReport:
    """One conversation's verify result: every embedded element is an entry, in order, unchanged."""

    conversation_id: str
    embedded: int
    entries: int
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


def element_hash(element: Mapping[str, object]) -> str:
    """Hash an embedded element canonically, so a later read of the same element hashes the same."""
    canonical = json.dumps(dict(element), sort_keys=True, default=str)
    return hashlib.sha256(canonical.encode()).hexdigest()


def identified(
    elements: Sequence[Mapping[str, object]],
) -> list[tuple[str, Mapping[str, object]]]:
    """Pair each element with its entry id: its message_id, or a legacy id from its position."""
    return [
        (
            str(element["message_id"]) if element.get("message_id") else f"{_LEGACY_ID_PREFIX}{n}",
            element,
        )
        for n, element in enumerate(elements, 1)
    ]


def last_embedded_id(elements: Sequence[Mapping[str, object]]) -> object:
    """Return what EMBEDDED_LAST_ID computes server-side: the last element's message_id that is present."""
    present = [element["message_id"] for element in elements if "message_id" in element]
    return present[-1] if present else None


def entry_at(element: Mapping[str, object]) -> datetime:
    """Return when an embedded element was written: its ISO date (a naive one read as UTC), else now."""
    raw = element.get("date")
    if not isinstance(raw, str):
        return datetime.now(UTC)
    try:
        parsed = datetime.fromisoformat(raw)
    except ValueError:
        return datetime.now(UTC)
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def _elements(head: Mapping[str, object]) -> list[dict[str, object]]:
    embedded = head.get("messages")
    return (
        [dict(e) for e in embedded if isinstance(e, Mapping)] if isinstance(embedded, list) else []
    )


def _of(ref: HeadRef) -> dict[str, str]:
    """Match the entries of ref's conversation."""
    return {"user_id": ref.user_id, "conversation_id": ref.conversation_id}


def _embedded_element(entry: Mapping[str, object]) -> dict[str, object]:
    """Turn an entry back into the embedded element it was: no entry fields, its id as message_id."""
    element = {k: v for k, v in entry.items() if k not in _ENTRY_ONLY_FIELDS}
    entry_id = str(entry["id"])
    if not entry_id.startswith(_LEGACY_ID_PREFIX):
        element["message_id"] = entry_id
    return element


class ConversationEntriesMigration(ConversationRepository):
    """The entries migration's reads and writes of the conversations heads and their entries."""

    async def heads_with_embedded(
        self, *, after_head_id: str | None, since: datetime | None, batch: int
    ) -> list[HeadRef]:
        """Return the next batch of heads still holding an embedded array, in _id order after after_head_id."""
        match: dict[str, object] = {"messages.0": {"$exists": True}}
        if since is not None:
            match["updatedAt"] = {"$gte": since}
        return await self._scan(match, after_head_id=after_head_id, batch=batch)

    async def heads_without_embedded(
        self, *, after_head_id: str | None, batch: int
    ) -> list[HeadRef]:
        """Return the next batch of migrated heads whose embedded array is gone, for the rollback rebuild."""
        match: dict[str, object] = {
            LOG_HEAD_FIELD: {"$exists": True},
            "messages": {"$exists": False},
        }
        return await self._scan(match, after_head_id=after_head_id, batch=batch)

    async def migrate(self, ref: HeadRef, *, apply: bool) -> MigrationOutcome:
        """Copy or merge one conversation's embedded array into its entries (only report when not apply)."""
        head = await self._embedded_head(ref)
        elements = _elements(head)
        pairs = identified(elements)
        ids = [entry_id for entry_id, _ in pairs]
        duplicated = sorted({i for i in ids if ids.count(i) > 1})
        if duplicated:
            return MigrationOutcome(
                ref.conversation_id,
                MigrationAction.REFUSED,
                reason=f"message ids repeat in the embedded array: {', '.join(duplicated)}",
            )
        if LOG_HEAD_FIELD not in head:
            if apply and not await self._copy(ref, pairs):
                return MigrationOutcome(ref.conversation_id, MigrationAction.RACED)
            return MigrationOutcome(
                ref.conversation_id, MigrationAction.COPIED, copied=len(elements)
            )
        return await self._merge(ref, head, pairs, apply=apply)

    async def verify(self, ref: HeadRef) -> VerifyReport:
        """Compare the embedded array with the entries: each element present, in order, unchanged since copied."""
        await self.flush_outbox(ref.conversation_id, user_id=ref.user_id)
        head = await self._embedded_head(ref)
        elements = _elements(head)
        entries = await self._stored(ref)
        by_id = {str(entry["id"]): entry for entry in entries}
        report = VerifyReport(ref.conversation_id, embedded=len(elements), entries=len(entries))
        if LOG_HEAD_FIELD not in head:
            report.mismatches.append("not migrated: no log_head")
            return report
        if head.get(MIGRATED_LAST_ID_FIELD) != last_embedded_id(elements):
            report.mismatches.append("written by the old build since its last pass: run --since")
        seqs: list[int] = []
        for entry_id, element in identified(elements):
            entry = by_id.get(entry_id)
            if entry is None:
                report.mismatches.append(f"{entry_id} has no entry")
                continue
            seqs.append(int(str(entry["seq"])))
            if entry.get(MIGRATION_HASH_FIELD) != element_hash(element):
                report.mismatches.append(f"{entry_id} differs from its entry")
        if seqs != sorted(seqs):
            report.mismatches.append("the entries are not in the embedded array's order")
        return report

    async def drop_embedded(self, ref: HeadRef) -> bool:
        """Unset the embedded array once verify passes; False when it does not, or the old build wrote since."""
        if not (await self.verify(ref)).ok:
            return False
        with store_errors("drop embedded"):  # pragma: no mutate — error label only
            result = await self._raw_collection().update_one(
                {
                    "_id": ObjectId(ref.head_id),
                    "$expr": {"$eq": [EMBEDDED_LAST_ID, f"${MIGRATED_LAST_ID_FIELD}"]},
                },
                {"$unset": _UNSET_EMBEDDED},
            )
        return result.modified_count > 0

    async def rebuild_embedded(self, ref: HeadRef, *, apply: bool) -> int:
        """Rollback: write the entries back as the embedded array and leave the head unmigrated; returns the count."""
        await self.flush_outbox(ref.conversation_id, user_id=ref.user_id)
        entries = await self._stored(ref)
        if not apply:
            return len(entries)
        messages = [_embedded_element(entry) for entry in entries]
        with store_errors("rebuild embedded"):  # pragma: no mutate — error label only
            await self._raw_collection().update_one(
                {"_id": ObjectId(ref.head_id)},
                {"$set": {"messages": messages}, "$unset": _UNSET_LOG},
            )
            await self._sibling_collection(CONVERSATION_ENTRIES_COLLECTION).delete_many(_of(ref))
        return len(messages)

    async def _scan(
        self, match: dict[str, object], *, after_head_id: str | None, batch: int
    ) -> list[HeadRef]:
        if after_head_id is not None:
            match["_id"] = {"$gt": ObjectId(after_head_id)}
        with store_errors("migration scan"):  # pragma: no mutate — error label only
            cursor = self._raw_collection().find(match, _HEAD_REF_FIELDS)
            rows = await cursor.sort(_BY_HEAD_ID).limit(batch).to_list(None)
        return [
            HeadRef(str(row["_id"]), str(row["conversation_id"]), str(row["user_id"]))
            for row in rows
        ]

    async def _embedded_head(self, ref: HeadRef) -> dict[str, object]:
        with store_errors("migration read"):  # pragma: no mutate — error label only
            head = await self._raw_collection().find_one({"_id": ObjectId(ref.head_id)})
        return dict(head or {})

    async def _stored(self, ref: HeadRef) -> list[dict[str, object]]:
        with store_errors("migration read"):  # pragma: no mutate — error label only
            rows = (
                await self._sibling_collection(CONVERSATION_ENTRIES_COLLECTION)
                .find(_of(ref))
                .sort(_BY_SEQ)
                .to_list(None)
            )
        return [dict(row) for row in rows]

    def _entry(
        self, ref: HeadRef, element: Mapping[str, object], entry_id: str, seq: int
    ) -> dict[str, object]:
        payload = {k: v for k, v in element.items() if k != "message_id"}
        return {
            **payload,
            **_of(ref),
            "seq": seq,
            "id": entry_id,
            "at": entry_at(element),
            MIGRATION_HASH_FIELD: element_hash(element),
        }

    async def _copy(self, ref: HeadRef, pairs: Sequence[tuple[str, Mapping[str, object]]]) -> bool:
        """First pass: entries at seq 1..n, then log_head, if the array is still the one copied.

        No append reaches an unmigrated head, so its entries can only be a pass that
        died before marking: they are replaced, never merged.
        """
        entries = [
            self._entry(ref, element, entry_id, seq)
            for seq, (entry_id, element) in enumerate(pairs, 1)
        ]
        with store_errors("migration copy"):  # pragma: no mutate — error label only
            await self._sibling_collection(CONVERSATION_ENTRIES_COLLECTION).delete_many(_of(ref))
            await self._sibling_collection(CONVERSATION_ENTRIES_COLLECTION).insert_many(entries)
            result = await self._raw_collection().update_one(
                {
                    "_id": ObjectId(ref.head_id),
                    LOG_HEAD_FIELD: {"$exists": False},
                    "$expr": {"$eq": [{"$size": "$messages"}, len(pairs)]},
                },
                {
                    "$set": {
                        LOG_HEAD_FIELD: len(pairs),
                        MIGRATED_LAST_ID_FIELD: last_embedded_id([e for _, e in pairs]),
                    }
                },
            )
        return result.modified_count > 0

    async def _merge(
        self,
        ref: HeadRef,
        head: Mapping[str, object],
        pairs: Sequence[tuple[str, Mapping[str, object]]],
        *,
        apply: bool,
    ) -> MigrationOutcome:
        """Later pass: append elements the entries lack, rewrite ones the old build changed, then re-mark the head."""
        await self.flush_outbox(ref.conversation_id, user_id=ref.user_id)
        by_id = {str(entry["id"]): entry for entry in await self._stored(ref)}
        fresh = [(i, e) for i, e in pairs if i not in by_id]
        changed = [
            (i, e)
            for i, e in pairs
            if i in by_id and by_id[i].get(MIGRATION_HASH_FIELD) != element_hash(e)
        ]
        last_id = last_embedded_id([element for _, element in pairs])
        if not fresh and not changed and head.get(MIGRATED_LAST_ID_FIELD) == last_id:
            return MigrationOutcome(ref.conversation_id, MigrationAction.UNCHANGED)
        outcome = MigrationOutcome(
            ref.conversation_id, MigrationAction.MERGED, copied=len(fresh), rewritten=len(changed)
        )
        if not apply:
            return outcome
        with store_errors("migration merge"):  # pragma: no mutate — error label only
            for entry_id, element in changed:
                seq = int(str(by_id[entry_id]["seq"]))
                await self._sibling_collection(CONVERSATION_ENTRIES_COLLECTION).replace_one(
                    {**_of(ref), "seq": seq}, self._entry(ref, element, entry_id, seq)
                )
        if fresh:
            log_head = int(str(head[LOG_HEAD_FIELD]))
            seqs = {i: log_head + n for n, (i, _) in enumerate(fresh, 1)}
            appended = [(i, self._entry(ref, e, i, seqs[i])) for i, e in fresh]
            if not await self._commit(ref.conversation_id, ref.user_id, log_head, appended, seqs):
                return MigrationOutcome(ref.conversation_id, MigrationAction.RACED)
            await self.flush_outbox(ref.conversation_id, user_id=ref.user_id)
        with store_errors("migration merge"):  # pragma: no mutate — error label only
            marked = await self._raw_collection().update_one(
                {"_id": ObjectId(ref.head_id), "$expr": {"$eq": [EMBEDDED_LAST_ID, last_id]}},
                {"$set": {MIGRATED_LAST_ID_FIELD: last_id}},
            )
        if not marked.matched_count:
            return MigrationOutcome(ref.conversation_id, MigrationAction.RACED)
        return outcome


conversation_entries_migration = ConversationEntriesMigration()
