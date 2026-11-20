"""Repository for the bot_sessions collection — platform→conversation mapping.

Global, keyed by a unique session_key. claim_session is an atomic
get-or-create: the conversation_id is minted exactly once via $setOnInsert
under the unique index, so two racing first-messages can never fork a session.
"""

from app.constants.cache import REPO_GLOBAL_SCOPE
from app.db.repositories.base import MongoRepository
from app.models.bot_models import BotSessionDocument, BotSessionUpdate, PartialReply
from app.utils.errors import AppError

#: Suffix a retired key derivation gave channel-less sessions; only pre-fix rows carry it.
#: app.scripts.merge_legacy_dm_bot_sessions retires them, and this constant goes with it.
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
        """Atomically reuse or create the session for session_key.

        On an existing session the stored conversation_id is returned and the
        candidate is discarded; on a fresh session the candidate is committed
        via $setOnInsert. timestamp is an ISO-format string (the TTL anchor),
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
        """Return the session on this key, or None — read-only, never mints one on a miss."""
        return await self._find_one({"session_key": session_key})

    async def get_by_conversation_id(self, conversation_id: str) -> BotSessionDocument | None:
        """Return the bot session for this conversation, or None for a non-bot conversation.

        Carries the channel_id a proactive delivery needs; indexed on conversation_id.
        """
        return await self._find_one({"conversation_id": conversation_id})

    async def list_sessions(self, *, platform: str | None = None) -> list[BotSessionDocument]:
        """Every session, optionally on one platform — the offline repair scans."""
        return await self._find({} if platform is None else {"platform": platform})

    async def list_legacy_dm_sessions(
        self, *, platform: str | None = None
    ) -> list[BotSessionDocument]:
        """Every session still keyed with the retired :dm suffix.

        Anchored at the end of the key on purpose: a live Slack or Discord channel
        id can CONTAIN dm, and rewriting one of those would fork the very chat
        this repairs.
        """
        filter_: dict[str, object] = {"session_key": {"$regex": f"{LEGACY_DM_SESSION_KEY_SUFFIX}$"}}
        if platform is not None:
            filter_["platform"] = platform
        return await self._find(filter_)

    async def rename_session_key(
        self, *, session_key: str, new_session_key: str, channel_id: str
    ) -> bool:
        """Move a session onto a different key, restamping its channel; False if unmatched.

        Safe only against a key nothing else holds — the caller checks that first.
        """
        matched = await self._apply_raw_update_unfetched(
            {"session_key": session_key},
            {"$set": {"session_key": new_session_key, "channel_id": channel_id}},
            scope=REPO_GLOBAL_SCOPE,
        )
        return matched > 0

    async def repoint_conversation(self, *, session_key: str, conversation_id: str) -> bool:
        """Point an existing session at a different conversation; False when unmatched."""
        matched = await self._apply_raw_update_unfetched(
            {"session_key": session_key},
            {"$set": {"conversation_id": conversation_id}, "$unset": {"delivery": ""}},
            scope=REPO_GLOBAL_SCOPE,
        )
        return matched > 0

    async def owe_delivery(
        self, conversation_id: str, *, first_seq: int, last_seq: int
    ) -> BotSessionDocument | None:
        """Record entries first_seq..last_seq as logged for the conversation's bot to render; None for a non-bot one.

        The first entry ever owed starts the bot's cursor just before it.
        """
        await self._apply_raw_update_unfetched(
            {"conversation_id": conversation_id, "delivery": {"$exists": False}},
            {"$set": {"delivery": {"delivered_seq": first_seq - 1, "owed_seq": last_seq}}},
            scope=REPO_GLOBAL_SCOPE,
        )
        return await self._apply_raw_update(
            {"conversation_id": conversation_id},
            {"$max": {"delivery.owed_seq": last_seq}},
            scope=REPO_GLOBAL_SCOPE,
        )

    async def record_delivered(
        self,
        conversation_id: str,
        *,
        platform: str,
        delivered_seq: int,
        partial_reply: PartialReply | None,
    ) -> bool:
        """Move the bot's cursor to what it delivered; False for a report behind the recorded one."""
        matched = await self._apply_raw_update_unfetched(
            {
                "conversation_id": conversation_id,
                "platform": platform,
                "$or": [
                    {"delivery": {"$exists": False}},
                    {"delivery.delivered_seq": {"$lte": delivered_seq}},
                ],
            },
            {
                "$set": {
                    "delivery.delivered_seq": delivered_seq,
                    "delivery.partial_reply": (
                        None if partial_reply is None else partial_reply.model_dump()
                    ),
                }
            },
            scope=REPO_GLOBAL_SCOPE,
        )
        return matched > 0

    async def list_owed(self, platform: str, limit: int) -> list[BotSessionDocument]:
        """Return the platform's sessions whose bot has not delivered everything logged for it."""
        return await self._find(
            {
                "platform": platform,
                "$expr": {"$gt": ["$delivery.owed_seq", "$delivery.delivered_seq"]},
            },
            limit=limit,
        )

    async def delete_by_session_key(self, session_key: str) -> int:
        """Remove the session on this key, returning how many rows were deleted."""
        return await self._delete_many({"session_key": session_key}, scope=REPO_GLOBAL_SCOPE)

    async def delete_for_platform_user(self, *, platform: str, platform_user_id: str) -> int:
        """Remove every session (DM and channels) of one platform account, returning the count."""
        return await self._delete_many(
            {"platform": platform, "platform_user_id": platform_user_id},
            scope=REPO_GLOBAL_SCOPE,
        )


bot_session_repository = BotSessionsRepository()
