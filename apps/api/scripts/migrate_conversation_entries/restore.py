"""Put each archived head's embedded array back, for a rollback to the build that reads it.

A pass moves the array off a head too full to take the log pointer. Restoring sets it back
ahead of anything the old build appended since, and removes the fields the migration added,
so the head is as it was and a later pass migrates it afresh. A head that would no longer fit
under Mongo's limit is reported and left archived.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from bson import ObjectId, encode

from app.constants.chat import CONVERSATION_ARCHIVED_MESSAGES_COLLECTION
from app.db.repositories.conversation_entries import LOG_HEAD_FIELD, STATE_FIELD, store_errors
from app.db.repositories.conversation_migration_guard import MIGRATED_FINGERPRINT_FIELD
from scripts.migrate_conversation_entries.migration import (
    ARCHIVED_FIELD,
    MAX_HEAD_BYTES,
    ConversationEntriesMigration,
    HeadRef,
)

#: What a restore removes from the head: every field a migration pass set on it.
_MIGRATION_FIELDS = [ARCHIVED_FIELD, LOG_HEAD_FIELD, STATE_FIELD, MIGRATED_FINGERPRINT_FIELD]


class RestoreAction(StrEnum):
    """What a restore did, or would do, to one archived head."""

    RESTORED = "restored"
    TOO_LARGE = "too_large"
    RACED = "raced"


@dataclass(frozen=True)
class RestoreOutcome:
    """One archived head's result, and the size the head would reach with its array back."""

    conversation_id: str
    action: RestoreAction
    elements: int
    restored_size: int


class ArchivedHeadRestore(ConversationEntriesMigration):
    """Reads each archived array and writes it back onto its head."""

    async def archived_heads(self, *, after_head_id: str | None, batch: int) -> list[HeadRef]:
        """Return the next batch of heads whose array a pass archived, in _id order."""
        match: dict[str, object] = {ARCHIVED_FIELD: {"$exists": True}}
        return await self._scan(match, after_head_id=after_head_id, batch=batch)

    async def restore(self, ref: HeadRef, *, apply: bool) -> RestoreOutcome | None:
        """Set the archived array back onto the head (report only unless apply); None when it is not archived."""
        head = await self._head(ref)
        if head is None or head.messages_archived is None:
            return None
        archived = await self._archived(ref, head.messages_archived)
        size = await self._restored_size(ref, archived)
        if size > MAX_HEAD_BYTES:
            return RestoreOutcome(ref.conversation_id, RestoreAction.TOO_LARGE, len(archived), size)
        outcome = RestoreOutcome(ref.conversation_id, RestoreAction.RESTORED, len(archived), size)
        if apply and not await self._put_back(ref, head.messages_archived, archived):
            return RestoreOutcome(ref.conversation_id, RestoreAction.RACED, len(archived), size)
        return outcome

    async def _restored_size(self, ref: HeadRef, archived: list[dict[str, object]]) -> int:
        """Return the BSON size the head reaches once restored, encoded exactly as the write leaves it."""
        with store_errors("archive restore"):  # pragma: no mutate — error label only
            raw = await self._raw_collection().find_one({"_id": ObjectId(ref.head_id)}) or {}
        kept = {key: value for key, value in raw.items() if key not in _MIGRATION_FIELDS}
        return len(encode({**kept, "messages": [*archived, *raw.get("messages", [])]}))

    async def _put_back(
        self, ref: HeadRef, fingerprint: int, archived: list[dict[str, object]]
    ) -> bool:
        """Write the array back ahead of any later messages, then drop its archive rows."""
        restored = {"$concatArrays": [{"$literal": archived}, {"$ifNull": ["$messages", []]}]}
        with store_errors("archive restore"):  # pragma: no mutate — error label only
            result = await self._raw_collection().update_one(
                {"_id": ObjectId(ref.head_id), ARCHIVED_FIELD: fingerprint},
                [{"$set": {"messages": restored}}, {"$unset": _MIGRATION_FIELDS}],
            )
            if result.matched_count:
                await self._sibling_collection(
                    CONVERSATION_ARCHIVED_MESSAGES_COLLECTION
                ).delete_many({"head_id": ref.head_id, "fingerprint": fingerprint})
        return result.matched_count > 0


archived_head_restore = ArchivedHeadRestore()
