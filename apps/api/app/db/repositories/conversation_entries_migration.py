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
from pymongo import ReplaceOne

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


def element_ids(elements: Sequence[Mapping[str, object]]) -> list[str]:
    """Each element's entry id: its message_id, or a legacy id from its position when it has none."""
    return [
        str(element["message_id"]) if element.get("message_id") else f"{_LEGACY_ID_PREFIX}{n}"
        for n, element in enumerate(elements, 1)
    ]


def last_embedded_id(elements: Sequence[Mapping[str, object]]) -> object:
    """Return what EMBEDDED_LAST_ID computes server-side: the last element's message_id that is present."""
    present = [element["message_id"] for element in elements if "message_id" in element]
    return present[-1] if present else None


def _elements(head: Mapping[str, object]) -> list[dict[str, object]]:
    embedded = head.get("messages")
    return (
        [dict(e) for e in embedded if isinstance(e, Mapping)] if isinstance(embedded, list) else []
    )


def _entry_at(element: Mapping[str, object]) -> datetime:
    raw = element.get("date")
    if isinstance(raw, str):
        try:
            parsed = datetime.fromisoformat(raw)
        except ValueError:
            parsed = None
        if parsed is not None:
            return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)
    return datetime.now(UTC)


class ConversationEntriesMigration(ConversationRepository):
    """The entries migration's reads and writes of the conversations heads and their entries."""

    async def heads_with_embedded(
        self, *, after_head_id: str | None, since: datetime | None, batch: int
    ) -> list[HeadRef]:
        """Return the next batch of heads still holding an embedded array, in _id order after after_head_id."""
        match: dict[str, object] = {"messages.0": {"$exists": True}}
        if after_head_id is not None:
            match["_id"] = {"$gt": ObjectId(after_head_id)}
        if since is not None:
            match["updatedAt"] = {"$gte": since}
        with store_errors("migration scan"):
            rows = (
                await self._raw_collection()
                .find(match, {"_id": 1, "conversation_id": 1, "user_id": 1})
                .sort("_id", 1)
                .limit(batch)
                .to_list(length=batch)
            )
        return [
            HeadRef(str(row["_id"]), str(row["conversation_id"]), str(row["user_id"]))
            for row in rows
        ]

    async def migrate(self, ref: HeadRef, *, apply: bool) -> MigrationOutcome:
        """Copy or merge one conversation's embedded array into its entries (only report when not apply)."""
        head = await self._embedded_head(ref)
        elements = _elements(head)
        ids = element_ids(elements)
        duplicated = sorted({i for i in ids if ids.count(i) > 1})
        if duplicated:
            return MigrationOutcome(
                ref.conversation_id,
                MigrationAction.REFUSED,
                reason=f"message ids repeat in the embedded array: {', '.join(duplicated)}",
            )
        if LOG_HEAD_FIELD not in head:
            if apply and not await self._copy(ref, elements, ids):
                return MigrationOutcome(ref.conversation_id, MigrationAction.RACED)
            return MigrationOutcome(
                ref.conversation_id, MigrationAction.COPIED, copied=len(elements)
            )
        return await self._merge(ref, head, elements, ids, apply=apply)

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
        previous_seq = 0
        for position, (entry_id, element) in enumerate(zip(element_ids(elements), elements), 1):
            entry = by_id.get(entry_id)
            if entry is None:
                report.mismatches.append(f"element {position} ({entry_id}) has no entry")
                continue
            seq = int(str(entry["seq"]))
            if seq <= previous_seq:
                report.mismatches.append(
                    f"element {position} ({entry_id}) is out of order: seq {seq}"
                )
            previous_seq = seq
            if entry.get(MIGRATION_HASH_FIELD) != element_hash(element):
                report.mismatches.append(f"element {position} ({entry_id}) differs from its entry")
        return report

    async def drop_embedded(self, ref: HeadRef) -> bool:
        """Unset the embedded array once verify passes; False when it does not, or the old build wrote since."""
        if not (await self.verify(ref)).ok:
            return False
        with store_errors("drop embedded"):
            result = await self._raw_collection().update_one(
                {
                    "_id": ObjectId(ref.head_id),
                    "$expr": {"$eq": [EMBEDDED_LAST_ID, f"${MIGRATED_LAST_ID_FIELD}"]},
                },
                {"$unset": {"messages": "", MIGRATED_LAST_ID_FIELD: ""}},
            )
        return result.modified_count > 0

    async def heads_without_embedded(
        self, *, after_head_id: str | None, batch: int
    ) -> list[HeadRef]:
        """Return the next batch of migrated heads whose embedded array is gone, for the rollback rebuild."""
        match: dict[str, object] = {
            LOG_HEAD_FIELD: {"$exists": True},
            "messages": {"$exists": False},
        }
        if after_head_id is not None:
            match["_id"] = {"$gt": ObjectId(after_head_id)}
        with store_errors("rebuild scan"):
            rows = (
                await self._raw_collection()
                .find(match, {"_id": 1, "conversation_id": 1, "user_id": 1})
                .sort("_id", 1)
                .limit(batch)
                .to_list(length=batch)
            )
        return [
            HeadRef(str(row["_id"]), str(row["conversation_id"]), str(row["user_id"]))
            for row in rows
        ]

    async def rebuild_embedded(self, ref: HeadRef, *, apply: bool) -> int:
        """Rollback: write the entries back as the embedded array and leave the head unmigrated; returns the count."""
        await self.flush_outbox(ref.conversation_id, user_id=ref.user_id)
        entries = await self._stored(ref)
        if not apply:
            return len(entries)
        messages = [
            {
                **{
                    k: v
                    for k, v in entry.items()
                    if k
                    not in {
                        "_id",
                        "conversation_id",
                        "user_id",
                        "seq",
                        "at",
                        "id",
                        MIGRATION_HASH_FIELD,
                    }
                },
                **(
                    {}
                    if str(entry["id"]).startswith(_LEGACY_ID_PREFIX)
                    else {"message_id": entry["id"]}
                ),
            }
            for entry in entries
        ]
        with store_errors("rebuild embedded"):
            await self._raw_collection().update_one(
                {"_id": ObjectId(ref.head_id)},
                {
                    "$set": {"messages": messages},
                    "$unset": {LOG_HEAD_FIELD: "", OUTBOX_FIELD: "", MIGRATED_LAST_ID_FIELD: ""},
                },
            )
            await self._entries().delete_many(
                {"user_id": ref.user_id, "conversation_id": ref.conversation_id}
            )
        return len(messages)

    async def _embedded_head(self, ref: HeadRef) -> dict[str, object]:
        with store_errors("migration read"):
            head = await self._raw_collection().find_one({"_id": ObjectId(ref.head_id)})
        if head is None:
            return {}
        return dict(head)

    async def _stored(self, ref: HeadRef) -> list[dict[str, object]]:
        with store_errors("migration read"):
            rows = (
                await self._entries()
                .find({"user_id": ref.user_id, "conversation_id": ref.conversation_id})
                .sort("seq", 1)
                .to_list(length=None)
            )
        return [dict(row) for row in rows]

    def _entry(
        self, ref: HeadRef, element: Mapping[str, object], entry_id: str, seq: int
    ) -> dict[str, object]:
        payload = {k: v for k, v in element.items() if k != "message_id"}
        return {
            **payload,
            "conversation_id": ref.conversation_id,
            "user_id": ref.user_id,
            "seq": seq,
            "id": entry_id,
            "at": _entry_at(element),
            MIGRATION_HASH_FIELD: element_hash(element),
        }

    async def _copy(
        self, ref: HeadRef, elements: Sequence[Mapping[str, object]], ids: Sequence[str]
    ) -> bool:
        """First pass: entries at seq 1..n (replacing a crashed pass's), then log_head, if the array is unchanged."""
        writes = [
            ReplaceOne(
                {"user_id": ref.user_id, "conversation_id": ref.conversation_id, "seq": seq},
                self._entry(ref, element, entry_id, seq),
                upsert=True,
            )
            for seq, (entry_id, element) in enumerate(zip(ids, elements), 1)
        ]
        with store_errors("migration copy"):
            await self._entries().bulk_write(writes, ordered=True)
            result = await self._raw_collection().update_one(
                {
                    "_id": ObjectId(ref.head_id),
                    LOG_HEAD_FIELD: {"$exists": False},
                    "$expr": {"$eq": [{"$size": "$messages"}, len(elements)]},
                },
                {
                    "$set": {
                        LOG_HEAD_FIELD: len(elements),
                        MIGRATED_LAST_ID_FIELD: last_embedded_id(elements),
                    }
                },
            )
        return result.modified_count > 0

    async def _merge(
        self,
        ref: HeadRef,
        head: Mapping[str, object],
        elements: Sequence[Mapping[str, object]],
        ids: Sequence[str],
        *,
        apply: bool,
    ) -> MigrationOutcome:
        """Later pass: append elements the entries lack, rewrite ones the old build changed, then re-mark the head."""
        await self.flush_outbox(ref.conversation_id, user_id=ref.user_id)
        by_id = {str(entry["id"]): entry for entry in await self._stored(ref)}
        fresh = [(i, e) for i, e in zip(ids, elements) if i not in by_id]
        changed = [
            (i, e)
            for i, e in zip(ids, elements)
            if i in by_id and by_id[i].get(MIGRATION_HASH_FIELD) != element_hash(e)
        ]
        stale = head.get(MIGRATED_LAST_ID_FIELD) != last_embedded_id(elements)
        if not (fresh or changed or stale):
            return MigrationOutcome(ref.conversation_id, MigrationAction.UNCHANGED)
        outcome = MigrationOutcome(
            ref.conversation_id, MigrationAction.MERGED, copied=len(fresh), rewritten=len(changed)
        )
        if not apply:
            return outcome
        with store_errors("migration merge"):
            for entry_id, element in changed:
                seq = int(str(by_id[entry_id]["seq"]))
                await self._entries().replace_one(
                    {"user_id": ref.user_id, "conversation_id": ref.conversation_id, "seq": seq},
                    self._entry(ref, element, entry_id, seq),
                )
        log_head = head.get(LOG_HEAD_FIELD)
        if fresh and not await self._commit(
            ref.conversation_id,
            ref.user_id,
            log_head if isinstance(log_head, int) else 0,
            [(i, {**self._entry(ref, e, i, 0), "id": i}) for i, e in fresh],
            {
                i: (log_head if isinstance(log_head, int) else 0) + n
                for n, (i, _) in enumerate(fresh, 1)
            },
        ):
            return MigrationOutcome(ref.conversation_id, MigrationAction.RACED)
        await self.flush_outbox(ref.conversation_id, user_id=ref.user_id)
        with store_errors("migration merge"):
            marked = await self._raw_collection().update_one(
                {
                    "_id": ObjectId(ref.head_id),
                    "$expr": {"$eq": [EMBEDDED_LAST_ID, last_embedded_id(elements)]},
                },
                {"$set": {MIGRATED_LAST_ID_FIELD: last_embedded_id(elements)}},
            )
        if not marked.matched_count:
            return MigrationOutcome(ref.conversation_id, MigrationAction.RACED)
        return outcome


conversation_entries_migration = ConversationEntriesMigration()
