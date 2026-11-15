"""Amending a stored entry in place: the step's fenced fill of a reply or message, and the user's one reaction."""

from app.models.conversation_log_models import (
    LoggedEntry,
    Reaction,
    Reply,
    StepClaim,
    UserMessage,
)
from app.services.conversation.mongo_log_base import MongoLogBase, not_found
from app.services.conversation.ports import ClaimLost, EntryRejected
from app.services.conversation.reducer import amend_refusal
from app.utils.errors import ConversationEntryNotFoundError


class LogAmends(MongoLogBase):
    """Replace a stored entry at its next revision, never changing the conversation's state."""

    async def amend(self, claim: StepClaim, entry: Reply | UserMessage) -> LoggedEntry:
        """Replace the stored entry with entry's id in place at its next revision, fenced; never a state change."""
        found = await self._repository.read_log(
            claim.conversation_id, user_id=claim.user_id, ids=[entry.id]
        )
        if found is None:
            raise not_found(claim.conversation_id)
        stored = found[0] if found else None
        if (
            stored is None
            or not isinstance(previous := stored.entry, Reply | UserMessage)
            or type(previous) is not type(entry)
        ):
            raise ConversationEntryNotFoundError(
                message=f"no {entry.kind} entry {entry.id} in conversation {claim.conversation_id}",
                meta={"conversation_id": claim.conversation_id, "entry_id": entry.id},
            )
        if (refusal := amend_refusal(previous, entry)) is not None:
            raise EntryRejected(refusal)
        # A pin is the user's, set beside the step: a fill never takes it back.
        revised = entry.model_copy(
            update={"revision": previous.revision + 1, "pinned": previous.pinned}
        )
        amended = stored.model_copy(update={"entry": revised})
        if not await self._repository.stage_log_amend(
            claim.conversation_id, user_id=claim.user_id, epoch=claim.epoch, amended=amended
        ):
            raise ClaimLost
        return amended

    async def react_once(
        self, conversation_id: str, user_id: str, message_id: str, reaction: Reaction
    ) -> LoggedEntry | None:
        """Put reaction on the user message while it has none; None when it already had one or moved on."""
        found = await self._repository.read_log(conversation_id, user_id=user_id, ids=[message_id])
        if not found or not isinstance(message := found[0].entry, UserMessage):
            raise ConversationEntryNotFoundError(
                message=f"no user message {message_id} in conversation {conversation_id}",
                meta={"conversation_id": conversation_id, "entry_id": message_id},
            )
        if message.reaction is not None:
            return None
        revised = message.model_copy(
            update={"reaction": reaction, "revision": message.revision + 1}
        )
        amended = found[0].model_copy(update={"entry": revised})
        if not await self._repository.stage_unfenced_amend(
            conversation_id, user_id=user_id, amended=amended, after_revision=message.revision
        ):
            return None
        return amended
