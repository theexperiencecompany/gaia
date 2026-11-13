"""Repository for the outbox ledger: every message GAIA composed for a user, and what became of it.

The unique (user_id, compose_attempt_id) insert is the gate in front of every
transport: a message is sent only by the call whose insert won.
"""

from datetime import datetime
from typing import Literal

from pymongo.errors import DuplicateKeyError

from app.constants.outbox import MESSAGES_COLLECTION
from app.db.repositories.base import UserScopedRepository
from app.models.outbox_models import OutboxMessageDocument, OutboxMessageUpdate
from app.services.outbox.models import ComposeMode, MessageState


class OutboxMessagesRepository(UserScopedRepository[OutboxMessageDocument, OutboxMessageUpdate]):
    """Persistence for ledger messages, unique on (user_id, compose_attempt_id)."""

    collection_name = MESSAGES_COLLECTION
    document_model = OutboxMessageDocument
    update_model = OutboxMessageUpdate
    uses_object_id = True
    cache_policy = None

    async def insert_attempt(self, message: OutboxMessageDocument) -> bool:
        """Store the message; False when an earlier insert already holds its compose attempt."""
        try:
            await self._raw_collection().insert_one(
                message.model_dump(exclude={"id"}, exclude_none=True)
            )
        except DuplicateKeyError:
            return False
        return True

    async def get_by_attempt(self, user_id: str, attempt_id: str) -> OutboxMessageDocument | None:
        """Return the message a compose attempt produced, or None."""
        return await self._find_one({"user_id": user_id, "compose_attempt_id": attempt_id})

    async def finish_send(
        self,
        user_id: str,
        attempt_id: str,
        state: Literal[MessageState.SENT, MessageState.FAILED],
        *,
        sent_at: datetime | None = None,
    ) -> bool:
        """Settle a sending message as sent or failed; False when it was no longer sending."""
        changes: dict[str, object] = {"state": state.value}
        if sent_at is not None:
            changes["sent_at"] = sent_at
        settled = await self._apply_raw_update(
            {"user_id": user_id, "compose_attempt_id": attempt_id},
            {"$set": changes},
            scope=user_id,
            extra_filter={"state": MessageState.SENDING.value},
        )
        return settled is not None

    async def sent_since(
        self, user_id: str, since: datetime, *, limit: int
    ) -> list[OutboxMessageDocument]:
        """Return what GAIA told the user since the cutoff, newest first."""
        return await self._find(
            {"user_id": user_id, "state": MessageState.SENT.value, "sent_at": {"$gte": since}},
            sort=[("sent_at", -1)],
            limit=limit,
        )

    async def count_sent_since(self, user_id: str, since: datetime, mode: ComposeMode) -> int:
        """Return how many messages of one mode GAIA told the user since the cutoff."""
        return await self._count(
            {
                "user_id": user_id,
                "state": MessageState.SENT.value,
                "mode": mode.value,
                "sent_at": {"$gte": since},
            }
        )

    async def last_sent_at(self, user_id: str, mode: ComposeMode) -> datetime | None:
        """Return when GAIA last told the user a message of one mode, or None when it never has."""
        latest = await self._find(
            {"user_id": user_id, "state": MessageState.SENT.value, "mode": mode.value},
            sort=[("sent_at", -1)],
            limit=1,
        )
        return latest[0].sent_at if latest else None

    async def recent_sent(self, user_id: str, *, limit: int) -> list[OutboxMessageDocument]:
        """Return the user's latest sent messages, newest first."""
        return await self._find(
            {"user_id": user_id, "state": MessageState.SENT.value},
            sort=[("sent_at", -1)],
            limit=limit,
        )


outbox_messages_repository = OutboxMessagesRepository()
