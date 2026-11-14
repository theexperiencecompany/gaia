"""The boot check that refuses to serve while any conversation still holds the old message shape.

The running app reads only the conversation log. Two marks say a conversation is not in it yet: an
embedded messages array no migration pass marked, and a message-shaped entry. Both queries are
index-backed (see indexes.py), so the check costs two indexed lookups however large the data grows.
"""

from __future__ import annotations

from app.constants.chat import (
    CONVERSATION_ENTRIES_COLLECTION,
    CONVERSATION_ENTRIES_MIGRATION_SCRIPT,
)
from app.db.repositories.conversation_entries import store_errors
from app.db.repositories.conversations import ConversationRepository
from app.models.conversation_models import _ConversationIdRow
from app.utils.errors import UnmigratedConversationError

#: The fingerprint of the embedded array as the migration last rewrote it, so any later old-build write shows.
MIGRATED_FINGERPRINT_FIELD = "migrated_fingerprint"
#: An embedded array no migration pass ever marked.
NEVER_MIGRATED_HEADS: dict[str, object] = {
    "messages.0": {"$exists": True},
    MIGRATED_FINGERPRINT_FIELD: {"$exists": False},
}
#: Message-shaped entries carry the old type field (user or bot); no log entry has one.
MESSAGE_SHAPED: dict[str, object] = {"type": {"$exists": True}}


def unmigrated(subject: str) -> UnmigratedConversationError:
    """Build the boot refusal for messages still in the old shape, naming the command that rewrites them."""
    return UnmigratedConversationError(
        message=(
            f"{subject} still holds messages in the old shape: run "
            f"python -m {CONVERSATION_ENTRIES_MIGRATION_SCRIPT} --apply, then --verify"
        ),
    )


class ConversationMigrationGuard(ConversationRepository):
    """Reads the two marks of a conversation the log does not hold yet."""

    async def first_unmigrated(self) -> str | None:
        """Name one conversation the new build cannot serve: an array no pass marked, or message-shaped entries."""
        with store_errors("migration check"):  # pragma: no mutate — error label only
            head = await self._raw_collection().find_one(
                NEVER_MIGRATED_HEADS, {"_id": 0, "conversation_id": 1}
            )
            if head is not None:
                return _ConversationIdRow.model_validate(head).conversation_id
            entry = await self._sibling_collection(CONVERSATION_ENTRIES_COLLECTION).find_one(
                MESSAGE_SHAPED, {"_id": 0, "conversation_id": 1}
            )
        return None if entry is None else _ConversationIdRow.model_validate(entry).conversation_id


async def refuse_unmigrated_conversations() -> None:
    """Refuse to boot while any conversation still needs the entries migration."""
    conversation_id = await ConversationMigrationGuard().first_unmigrated()
    if conversation_id is not None:
        raise unmigrated(f"conversation {conversation_id}")
