"""What every part of the Mongo conversation log shares: its repository, its clock, and the head read."""

from collections.abc import Callable
from datetime import datetime

from app.db.repositories.conversation_log import ConversationLogRepository
from app.db.repositories.conversation_log_append import LogHead
from app.utils.errors import ConversationNotFoundError


class MongoLogBase:
    """The repository and clock the log's parts run on, and the one read of the head they all start from."""

    def __init__(
        self, repository: ConversationLogRepository, clock: Callable[[], datetime]
    ) -> None:
        self._repository = repository
        self._clock = clock

    async def _head(
        self, conversation_id: str, user_id: str, entry_id: str | None = None
    ) -> LogHead:
        head = await self._repository.read_log_head(
            conversation_id, user_id=user_id, entry_id=entry_id
        )
        if head is None:
            raise not_found(conversation_id)
        return head


def not_found(conversation_id: str) -> ConversationNotFoundError:
    """Return the error for a conversation this user has no head for."""
    return ConversationNotFoundError(
        message=f"conversation {conversation_id} does not exist for this user",
        meta={"conversation_id": conversation_id},
    )
