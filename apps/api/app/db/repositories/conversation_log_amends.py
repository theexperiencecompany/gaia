"""The conversation log's amendments: an entry rewritten in place, staged in the head's outbox.

A fenced amend lands only while its epoch holds the step; an unfenced one (a reaction, a pin)
lands only while the stored entry is still at the revision it was read at.
"""

from __future__ import annotations

from app.constants.chat import CONVERSATION_APPEND_MAX_ATTEMPTS
from app.db.repositories.conversation_entries import (
    ADVANCE_SYNC_CLOCK,
    OUTBOX_FIELD,
    RUNNER_FIELD,
    log_document,
    store_errors,
)
from app.db.repositories.conversation_log_reads import LogReadRepository
from app.models.conversation_log_models import LoggedEntry, Reply, UserMessage
from app.models.conversation_models import StoredEntry
from app.utils.errors import ConversationStoreError


class LogAmendRepository(LogReadRepository):
    """Conditional rewrites of one stored log entry, flushed to its document like an append."""

    async def stage_log_amend(
        self, conversation_id: str, *, user_id: str, epoch: int, amended: LoggedEntry
    ) -> bool:
        """Stage amended in the head's outbox, only while epoch holds the step; the flush carries it to its document.

        The one write of an amendment is this head update, so the epoch fence and the write are atomic.
        """
        document = log_document(conversation_id, user_id, amended)
        with store_errors("log amend"):  # pragma: no mutate — error label
            result = await self._raw_collection().update_one(
                {
                    "conversation_id": conversation_id,
                    "user_id": user_id,
                    f"{RUNNER_FIELD}.epoch": epoch,
                },
                {"$set": {f"{OUTBOX_FIELD}.{amended.seq}": document}},
            )
        if not result.matched_count:
            return False
        self._spawn_flush(conversation_id, user_id, [StoredEntry.model_validate(document)])
        return True

    async def stage_unfenced_amend(
        self,
        conversation_id: str,
        *,
        user_id: str,
        amended: LoggedEntry,
        after_revision: int,
        advances_sync: bool = False,
    ) -> bool:
        """Stage amended unfenced, only while the stored entry is still at after_revision; the flush carries it.

        A staged amendment newer than after_revision (a fill, a reaction, a pin) makes this a no-op.
        advances_sync bumps updatedAt, so batch sync carries the edit to the user's other devices.
        """
        staged = f"{OUTBOX_FIELD}.{amended.seq}"
        document = log_document(conversation_id, user_id, amended)
        with store_errors("log reaction"):  # pragma: no mutate — error label
            result = await self._raw_collection().update_one(
                {
                    "conversation_id": conversation_id,
                    "user_id": user_id,
                    "$or": [
                        {staged: {"$exists": False}},
                        {f"{staged}.revision": after_revision},
                    ],
                },
                {
                    "$set": {staged: document},
                    **(ADVANCE_SYNC_CLOCK if advances_sync else {}),
                },
            )
        if not result.matched_count:
            return False
        if advances_sync:
            self._announce_row_changed(conversation_id, user_id)
        self._spawn_flush(conversation_id, user_id, [StoredEntry.model_validate(document)])
        return True

    async def set_pinned(
        self, conversation_id: str, *, user_id: str, message_id: str, pinned: bool
    ) -> bool:
        """Pin or unpin the user message with this id or the reply with this reply id; False when there is none."""
        for _ in range(CONVERSATION_APPEND_MAX_ATTEMPTS):
            found = await self.read_log(
                conversation_id, user_id=user_id, ids=[message_id], reply_ids=[message_id]
            )
            target = next(
                (logged for logged in found or [] if isinstance(logged.entry, UserMessage | Reply)),
                None,
            )
            if target is None or not isinstance(entry := target.entry, UserMessage | Reply):
                return False
            if entry.pinned is pinned:
                return True
            revised = entry.model_copy(update={"pinned": pinned, "revision": entry.revision + 1})
            if await self.stage_unfenced_amend(
                conversation_id,
                user_id=user_id,
                amended=target.model_copy(update={"entry": revised}),
                after_revision=entry.revision,
                advances_sync=True,
            ):
                return True
        raise ConversationStoreError(
            message=f"pinning in conversation {conversation_id} lost every conditional write",
            meta={"conversation_id": conversation_id, "entry_id": message_id},
        )
