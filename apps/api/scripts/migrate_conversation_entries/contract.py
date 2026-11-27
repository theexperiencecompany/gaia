"""Contract step: drop the old embedded messages arrays the entries migration copied into the log.

The build reads only the conversation log, so a head's array is dead weight once the log matches
it. A head is dropped only while its array still hashes to the fingerprint the migration marked
(or is empty, or was archived), so an array the log does not match yet stays for the next
catch-up. Entries lose migration_fields, the per-field hashes only a re-pass reads and that it
recomputes when absent. Rollback is restoring the pre-deploy Atlas snapshot.

    cd apps/api && uv run python -m scripts.migrate_conversation_entries.contract [--apply]
"""

from __future__ import annotations

import asyncio

from bson import ObjectId
from pymongo.errors import OperationFailure

from app.constants.chat import (
    CONVERSATION_ARCHIVED_MESSAGES_COLLECTION,
    CONVERSATION_ENTRIES_COLLECTION,
)
from app.db.repositories.conversation_entries import MIGRATION_FIELDS_FIELD, store_errors
from app.db.repositories.conversation_migration_guard import (
    EMBEDDED_FINGERPRINT,
    MIGRATED_FINGERPRINT_FIELD,
)
from scripts._cli import apply_requested
from scripts.migrate_conversation_entries.migration import (
    ARCHIVED_FIELD,
    ConversationEntriesMigration,
)

#: Heads whose array the log already holds: empty, marked and unchanged since, or moved to the archive.
DROPPABLE_HEADS: dict[str, object] = {
    "$or": [
        {"messages": {"$size": 0}},
        {
            "messages.0": {"$exists": True},
            MIGRATED_FINGERPRINT_FIELD: {"$exists": True},
            "$expr": {"$eq": [EMBEDDED_FINGERPRINT, f"${MIGRATED_FINGERPRINT_FIELD}"]},
        },
        {"messages": {"$exists": False}, ARCHIVED_FIELD: {"$exists": True}},
    ]
}
_DROPPED_HEAD_FIELDS = {"messages": "", MIGRATED_FINGERPRINT_FIELD: "", ARCHIVED_FIELD: ""}
_MARKED_ENTRIES: dict[str, object] = {MIGRATION_FIELDS_FIELD: {"$exists": True}}
#: The old build's indexes on the embedded array; nothing queries them once the arrays are gone.
LEGACY_ARRAY_INDEXES = ("user_id_1_messages.message_id_1", "user_id_1_messages.pinned_1")
_INDEX_NOT_FOUND = 27


class EmbeddedArrayContract(ConversationEntriesMigration):
    """Drops what the entries migration left behind once the log holds it."""

    async def drop(self, *, apply: bool) -> None:
        """Drop every array the log holds; a head with a recorded failure keeps its array and archive."""
        heads = self._raw_collection()
        entries = self._sibling_collection(CONVERSATION_ENTRIES_COLLECTION)
        archive = self._sibling_collection(CONVERSATION_ARCHIVED_MESSAGES_COLLECTION)
        failed = await self.failed_heads()
        droppable = {**DROPPABLE_HEADS, "_id": {"$nin": [ObjectId(f.head_id) for f in failed]}}
        marked = {
            **_MARKED_ENTRIES,
            "conversation_id": {"$nin": [f.conversation_id for f in failed]},
        }
        with store_errors("embedded array contract"):  # pragma: no mutate — error label only
            if not apply:
                print(
                    f"  would drop the array of {await heads.count_documents(droppable)} "
                    f"conversations and migration_fields of "
                    f"{await entries.count_documents(marked)} entries"
                )
                return
            dropped = await heads.update_many(droppable, {"$unset": _DROPPED_HEAD_FIELDS})
            still_archived = await heads.distinct("_id", {ARCHIVED_FIELD: {"$exists": True}})
            kept = [str(head_id) for head_id in still_archived]
            unarchived = await archive.delete_many({"head_id": {"$nin": kept}})
            unmarked = await entries.update_many(marked, {"$unset": {MIGRATION_FIELDS_FIELD: ""}})
            for name in LEGACY_ARRAY_INDEXES:
                await self._drop_index(name)
            left = await heads.count_documents(
                {"$or": [{"messages": {"$exists": True}}, {ARCHIVED_FIELD: {"$exists": True}}]}
            )
        if not (
            dropped.modified_count or unarchived.deleted_count or unmarked.modified_count or left
        ):
            return
        print(
            f"  dropped the array of {dropped.modified_count} conversations, "
            f"{unarchived.deleted_count} archived messages and migration_fields of "
            f"{unmarked.modified_count} entries; {left} arrays the log does not match yet are kept"
        )

    async def _drop_index(self, name: str) -> None:
        """Drop one legacy index; a deployment that never built it has nothing to drop."""
        try:
            await self._raw_collection().drop_index(name)
        except OperationFailure as exc:
            if exc.code != _INDEX_NOT_FOUND:
                raise


async def contract(apply: bool) -> None:
    await EmbeddedArrayContract().drop(apply=apply)


if __name__ == "__main__":
    asyncio.run(contract(apply=apply_requested(__doc__)))
