"""Repository for the ``bot_sessions`` collection — platform→conversation mapping.

Global, keyed by a unique ``session_key``. ``claim_session`` is an atomic
get-or-create: the ``conversation_id`` is minted exactly once via ``$setOnInsert``
under the unique index, so two racing first-messages can never fork a session.
"""

from app.constants.cache import REPO_GLOBAL_SCOPE
from app.db.repositories.base import MongoRepository
from app.models.bot_models import BotSessionDocument, BotSessionUpdate
from app.utils.errors import AppError

#: The suffix a retired key derivation gave a channel-less session (``channel_id
#: or "dm"``). A DM now keys off the platform user id, so nothing writes this any
#: more — see ``BotService.build_session_key``. Only rows minted before that fix
#: carry it, and ``app.scripts.merge_legacy_dm_bot_sessions`` retires them; this
#: constant and ``list_legacy_dm_sessions`` go with the script once it has run
#: everywhere.
LEGACY_DM_SESSION_KEY_SUFFIX = ":dm"


class BotSessionsRepository(MongoRepository[BotSessionDocument, BotSessionUpdate]):
    collection_name = "bot_sessions"
    document_model = BotSessionDocument
    update_model = BotSessionUpdate
    uses_object_id = True
    cache_policy = None
    # created_at/updated_at are ISO strings written by hand (the TTL anchor), so
    # the base must not stamp a datetime over them.
    auto_stamp_timestamps = False

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

    async def get_by_session_key(self, session_key: str) -> BotSessionDocument | None:
        """The session on this key, or ``None``. Read-only counterpart to
        ``claim_session`` for callers that must not mint one on a miss."""
        return await self._find_one({"session_key": session_key})

    async def list_legacy_dm_sessions(
        self, *, platform: str | None = None
    ) -> list[BotSessionDocument]:
        """Every session still keyed with the retired ``:dm`` suffix.

        Anchored at the end of the key on purpose: a live Slack or Discord channel
        id can CONTAIN ``dm``, and rewriting one of those would fork the very chat
        this repairs.
        """
        filter_: dict[str, object] = {"session_key": {"$regex": f"{LEGACY_DM_SESSION_KEY_SUFFIX}$"}}
        if platform is not None:
            filter_["platform"] = platform
        return await self._find(filter_)

    async def rename_session_key(
        self, *, session_key: str, new_session_key: str, channel_id: str
    ) -> bool:
        """Move a session onto a different key, restamping the channel it belongs
        to. False when the filter matched nothing.

        The unique index on ``session_key`` makes this safe only against a key
        nothing else holds — the caller checks that first.
        """
        matched = await self._apply_raw_update_unfetched(
            {"session_key": session_key},
            {"$set": {"session_key": new_session_key, "channel_id": channel_id}},
            scope=REPO_GLOBAL_SCOPE,
        )
        return matched > 0

    async def repoint_conversation(self, *, session_key: str, conversation_id: str) -> bool:
        """Point an existing session at a different conversation. False when the
        filter matched nothing."""
        matched = await self._apply_raw_update_unfetched(
            {"session_key": session_key},
            {"$set": {"conversation_id": conversation_id}},
            scope=REPO_GLOBAL_SCOPE,
        )
        return matched > 0

    async def delete_by_session_key(self, session_key: str) -> int:
        """Remove the session on this key. Returns how many rows went — a caller
        repairing data needs to know a delete matched nothing."""
        return await self._delete_many({"session_key": session_key}, scope=REPO_GLOBAL_SCOPE)


bot_session_repository = BotSessionsRepository()
