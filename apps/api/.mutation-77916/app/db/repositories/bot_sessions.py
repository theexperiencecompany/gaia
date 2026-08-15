"""Repository for the ``bot_sessions`` collection — platform→conversation mapping.

Global, keyed by a unique ``session_key``. ``claim_session`` is an atomic
get-or-create: the ``conversation_id`` is minted exactly once via ``$setOnInsert``
under the unique index, so two racing first-messages can never fork a session.
"""

from app.constants.cache import REPO_GLOBAL_SCOPE
from app.db.repositories.base import MongoRepository
from app.models.bot_models import BotSessionDocument, BotSessionUpdate
from app.utils.errors import AppError


class BotSessionsRepository(MongoRepository[BotSessionDocument, BotSessionUpdate]):
    collection_name = "bot_sessions"
    document_model = BotSessionDocument
    update_model = BotSessionUpdate
    uses_object_id = True
    cache_policy = None

    async def claim_session(
        self,
        *,
        session_key: str,
        platform: str,
        platform_user_id: str,
        channel_id: str | None,
        candidate_conversation_id: str,
        timestamp: str,
    ) -> BotSessionDocument:
        """Atomically reuse or create the session for ``session_key``.

        On an existing session the stored ``conversation_id`` is returned and the
        ``candidate`` is discarded; on a fresh session the candidate is committed
        via ``$setOnInsert``. ``timestamp`` is an ISO-format string (the TTL anchor),
        written raw so the on-disk string shape is preserved."""
        session = await self._apply_raw_update(
            {"session_key": session_key},
            {
                "$set": {
                    "platform": platform,
                    "platform_user_id": platform_user_id,
                    "channel_id": channel_id,
                    "updated_at": timestamp,
                },
                "$setOnInsert": {
                    "session_key": session_key,
                    "conversation_id": candidate_conversation_id,
                    "created_at": timestamp,
                },
            },
            scope=REPO_GLOBAL_SCOPE,
            upsert=True,
        )
        if session is None:
            # find_one_and_update(upsert=True, AFTER) always yields a document.
            raise AppError(message="bot session upsert returned no document")
        return session

    async def delete_by_session_key(self, session_key: str) -> None:
        await self._delete_many({"session_key": session_key}, scope=REPO_GLOBAL_SCOPE)


bot_session_repository = BotSessionsRepository()
