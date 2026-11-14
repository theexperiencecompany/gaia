"""A user's integration entries across conversations: the asks to connect an integration, and their answers."""

from __future__ import annotations

from datetime import datetime

from app.constants.chat import CONVERSATION_ENTRIES_COLLECTION
from app.db.repositories.conversation_entries import logged_of, store_errors
from app.db.repositories.conversations import ConversationRepository
from app.models.conversation_log_models import EntryKind, LoggedEntry
from app.models.conversation_models import StoredEntry

_INTEGRATION_KINDS = (EntryKind.INTEGRATION_NEEDED, EntryKind.INTEGRATION_CONNECTED)


class IntegrationEntryRepository(ConversationRepository):
    """The cross-conversation read of integration entries from conversation_entries."""

    async def list_integration_entries(
        self, *, user_id: str, integration_id: str, since: datetime
    ) -> list[tuple[str, LoggedEntry]]:
        """Return the user's integration entries for integration_id since since, as (conversation_id, entry).

        Read from conversation_entries alone: an entry still in a head's outbox is flushed within moments.
        """
        entries = self._sibling_collection(CONVERSATION_ENTRIES_COLLECTION)
        with store_errors("integration entries"):  # pragma: no mutate — error label
            cursor = entries.find(
                {
                    "user_id": user_id,
                    "at": {"$gte": since},
                    "kind": {"$in": [k.value for k in _INTEGRATION_KINDS]},
                    "integration_id": integration_id,
                }
            )
            rows = [row async for row in cursor]
        stored = [StoredEntry.model_validate(row) for row in rows]
        return [(entry.conversation_id, logged_of(entry)) for entry in stored]


integration_entry_repository = IntegrationEntryRepository()
