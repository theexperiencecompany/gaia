"""Bot Service

Business logic for bot chat sessions, rate limiting, and conversation management.
"""

from datetime import UTC, datetime
from uuid import uuid4

from fastapi import HTTPException

from app.db.redis import redis_cache
from app.db.repositories.bot_sessions import bot_session_repository
from app.db.repositories.conversations import conversation_repository
from app.models.chat_models import ConversationModel, ConversationSource
from app.models.user_models import AuthenticatedUser
from app.services.bot_session_merge import apply_merge, plan_merge
from app.services.conversation_service import create_conversation_service
from shared.py.wide_events import log

# Constants
BOT_RATE_LIMIT = 20  # requests per minute per user
BOT_RATE_WINDOW = 60  # seconds


class BotService:
    """Service for bot-related operations."""

    @staticmethod
    async def enforce_rate_limit(platform: str, platform_user_id: str) -> None:
        """
        Enforce rate limiting for bot requests.

        Args:
            platform: Platform name
            platform_user_id: User's ID on the platform

        Raises:
            HTTPException: If rate limit exceeded
        """
        key = f"bot_ratelimit:{platform}:{platform_user_id}"
        try:
            if redis_cache.redis:
                count = await redis_cache.redis.incr(key)
                if count == 1:
                    await redis_cache.redis.expire(key, BOT_RATE_WINDOW)
                if count > BOT_RATE_LIMIT:
                    raise HTTPException(
                        status_code=429,
                        detail="Rate limit exceeded. Please wait before sending more messages.",
                    )
        except HTTPException:
            raise
        except Exception as e:
            # Intentional fail-open behavior: if Redis is unavailable, allow the request
            # to proceed without rate limiting to maintain service availability. This is
            # acceptable because bot rate limiting is a nice-to-have feature that should
            # not block legitimate users when infrastructure is degraded.
            log.warning(
                "Rate limit check failed, failing open",
                platform=platform,
                platform_user_id=platform_user_id,
                error=str(e),
                error_type=type(e).__name__,
            )

    @staticmethod
    def build_session_key(platform: str, platform_user_id: str, channel_id: str | None) -> str:
        """The one key a (platform, user, channel) conversation lives under.

        No ``channel_id`` means "the user's DM" — all a backend-originated
        delivery knows, since it resolves its destination from the platform link
        (``outbound_delivery._resolve_destination`` returns the platform user id)
        rather than from an inbound chat. A DM therefore has to key off the
        platform user id, which is exactly what Telegram sends as the chat id for
        a private chat: ``ctx.chat.id == ctx.from.id`` there.

        This used to key an absent channel as the literal ``"dm"``, so one
        Telegram DM lived under two keys — ``telegram:<id>:<id>`` from the chat
        and ``telegram:<id>:dm`` from workflow delivery — and the user's chat
        forked into a second conversation carrying none of the history.

        Discord and Slack DM channel ids are NOT the user id, so an inbound DM
        there must not key off its channel: the bot flags those messages as DMs
        and ``get_or_create_session`` drops the channel id before keying, which
        lands them here on the user-id form a backend-originated delivery also
        produces. The flag lives with the bot because a DM-channel key is
        indistinguishable from a guild/channel key server-side.
        """
        return f"{platform}:{platform_user_id}:{channel_id or platform_user_id}"

    @staticmethod
    async def _absorb_channel_keyed_dm(
        platform: str, platform_user_id: str, channel_id: str | None
    ) -> None:
        """Fold a DM session keyed by its platform channel onto the user-id key.

        Discord and Slack DMs used to key off the DM channel id, which differs
        from the user id there, so the same DM forked: inbound chat under
        ``platform:<user>:<dm-channel>``, workflow delivery under
        ``platform:<user>:<user>``. Now that the bot flags DMs, the first
        flagged message finds the channel-keyed row and merges it onto the
        canonical key — rename when the canonical key is free, otherwise the
        more recently used conversation wins. Runs at most once per DM: after
        the merge no channel-keyed row remains.
        """
        if not channel_id or channel_id == platform_user_id:
            return
        legacy_key = BotService.build_session_key(platform, platform_user_id, channel_id)
        legacy = await bot_session_repository.get_by_session_key(legacy_key)
        if legacy is None:
            return
        canonical_key = BotService.build_session_key(platform, platform_user_id, None)
        canonical = await bot_session_repository.get_by_session_key(canonical_key)
        merge = plan_merge(legacy, canonical, canonical_key)
        if merge is None:
            return
        landed = await apply_merge(merge)
        log.info(
            "folded channel-keyed DM session onto the user-id key",
            action=merge.action.value,
            landed=landed,
            legacy_key=legacy_key,
            canonical_key=canonical_key,
            surviving_conversation_id=merge.surviving_conversation_id,
            orphaned_conversation_id=merge.orphaned_conversation_id,
        )

    @staticmethod
    async def get_or_create_session(
        platform: str,
        platform_user_id: str,
        channel_id: str | None,
        user: AuthenticatedUser,
        *,
        is_dm: bool = False,
    ) -> str:
        """
        Get existing bot session or create a new one.

        Args:
            platform: Platform name
            platform_user_id: User's ID on the platform
            channel_id: Channel/group ID (None for DM)
            user: User document from database

        Returns:
            Conversation ID for the session
        """
        # Normalize user dict: support both raw MongoDB docs (_id) and
        # pre-formatted dicts (user_id) so create_conversation_service works
        if not user.get("user_id") and user.get("_id"):
            user = {**user, "user_id": str(user["_id"])}

        if is_dm:
            await BotService._absorb_channel_keyed_dm(platform, platform_user_id, channel_id)
            channel_id = None
        session_key = BotService.build_session_key(platform, platform_user_id, channel_id)
        now = datetime.now(UTC).isoformat()

        # Atomically claim (or reuse) the session for this session_key. The
        # conversation_id is set exactly once, on insert, via $setOnInsert so two
        # racing first-messages can never mint two conversations: only the inserter
        # wins the id and every other caller reads it back. The unique index on
        # session_key (see app/db/mongodb/indexes.py) guarantees this atomicity.
        candidate_conversation_id = str(uuid4())
        session = await bot_session_repository.claim_session(
            session_key=session_key,
            platform=platform,
            platform_user_id=platform_user_id,
            channel_id=channel_id,
            candidate_conversation_id=candidate_conversation_id,
            timestamp=now,
        )

        conversation_id = session.conversation_id
        is_new_session = conversation_id == candidate_conversation_id

        # Ensure the conversation document exists for this session. On a fresh
        # session it never does; on an existing session it normally does, but it
        # may have been deleted from the web UI (or lost to a race). Either way we
        # (re)create it with the SAME conversation_id stored on the session rather
        # than minting a new one and repointing, so the chat thread is never
        # orphaned or forked.
        if await conversation_repository.exists(conversation_id, user_id=user.get("user_id", "")):
            log.set(
                bot={
                    "platform": platform,
                    "session_key": session_key,
                    "conversation_id": conversation_id,
                    "session_status": "existing",
                }
            )
            return conversation_id

        conversation = ConversationModel(
            conversation_id=conversation_id,
            description=f"{platform.capitalize()} Chat",
            source=ConversationSource(platform),
        )
        await create_conversation_service(conversation, user)

        log.set(
            bot={
                "platform": platform,
                "session_key": session_key,
                "conversation_id": conversation_id,
                "session_status": "new" if is_new_session else "recreated",
            }
        )
        return conversation_id

    @staticmethod
    async def reset_session(
        platform: str,
        platform_user_id: str,
        channel_id: str | None,
        user: AuthenticatedUser,
        *,
        is_dm: bool = False,
    ) -> str:
        """
        Reset bot session (delete existing and create new).

        Args:
            platform: Platform name
            platform_user_id: User's ID on the platform
            channel_id: Channel/group ID (None for DM)
            user: User document from database

        Returns:
            New conversation ID
        """
        if is_dm:
            # The channel-keyed legacy row IS this DM: left in place, the next
            # inbound merge would resurrect the conversation the user just reset.
            legacy_key = BotService.build_session_key(platform, platform_user_id, channel_id)
            await bot_session_repository.delete_by_session_key(legacy_key)
            channel_id = None
        session_key = BotService.build_session_key(platform, platform_user_id, channel_id)
        await bot_session_repository.delete_by_session_key(session_key)

        return await BotService.get_or_create_session(platform, platform_user_id, channel_id, user)

    @staticmethod
    async def load_conversation_history(
        conversation_id: str, user_id: str, limit: int = 20
    ) -> list[dict]:
        """
        Load recent conversation history for context.

        Args:
            conversation_id: Conversation ID
            user_id: User ID
            limit: Maximum number of messages to load (default: 20)

        Returns:
            List of message dicts with role and content
        """
        conversation = await conversation_repository.get(conversation_id, user_id=user_id)
        if conversation is None or not conversation.messages:
            return []

        history = []
        for msg in conversation.messages[-limit:]:
            if msg.type == "user":
                history.append({"role": "user", "content": msg.response or ""})
            elif msg.type == "bot":
                history.append({"role": "assistant", "content": msg.response or ""})
        return history
