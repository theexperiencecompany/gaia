"""Business logic for bot chat sessions, rate limiting, and conversation management."""

from datetime import UTC, datetime
from uuid import uuid4

from fastapi import HTTPException

from app.db.redis import redis_cache
from app.db.repositories.bot_sessions import bot_session_repository
from app.db.repositories.conversations import conversation_repository
from app.decorators import enforce_daily_cost_budget, enforce_tiered_limit
from app.models.bot_models import BotChatRequest
from app.models.chat_models import ConversationModel, ConversationSource
from app.models.message_models import MessageDict, MessageRequestWithHistory
from app.models.user_models import AuthenticatedUser
from app.services.analytics_service import AnalyticsEvents, capture_event
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
        """Enforce per-platform-user rate limiting for bot requests.

        Raises HTTPException (429) when the limit is exceeded.
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
            # Intentional fail-open: if Redis is down, let the request through rather
            # than block legitimate users — bot rate limiting is a nice-to-have, not
            # a hard guarantee.
            log.warning(
                "Rate limit check failed, failing open",
                platform=platform,
                platform_user_id=platform_user_id,
                error=str(e),
                error_type=type(e).__name__,
            )

    @staticmethod
    def build_session_key(platform: str, platform_user_id: str, channel_id: str | None) -> str:
        """Return the one key a (platform, user, channel) conversation lives under.

        No channel_id means DM: backend delivery only knows the platform user
        id, and Telegram's own DM chat id equals it too. Discord/Slack DM
        channel ids do NOT equal the user id, so get_or_create_session drops
        the channel for a flagged inbound DM before calling this.
        """
        return f"{platform}:{platform_user_id}:{channel_id or platform_user_id}"

    @staticmethod
    async def _absorb_channel_keyed_dm(
        platform: str, platform_user_id: str, channel_id: str | None
    ) -> None:
        """Fold a DM session keyed by its platform channel onto the user-id key.

        Discord/Slack DMs used to fork (channel-keyed row vs user-id-keyed
        row) before the bot flagged DMs. Idempotent: after the first flagged
        message merges the channel-keyed row onto the canonical key, no
        channel-keyed row remains to merge again.
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
        """Return the conversation id for this bot session, creating one if needed.

        channel_id=None means the session is a DM.
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

        # conversation_id is set once, on insert, via $setOnInsert, so two racing
        # first-messages can't mint two conversations — only the inserter wins the
        # id. Guaranteed by the unique index on session_key (mongodb/indexes.py).
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

        # The conversation doc may be missing (fresh session, or deleted from the
        # web UI / lost to a race) — (re)create it with the SAME conversation_id
        # stored on the session, never a new one, so the thread can't fork.
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
        """Delete the existing bot session and return a freshly created conversation id."""
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
        """Return up to limit recent messages as role/content dicts."""
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


async def build_bot_message_request(
    body: BotChatRequest, conversation_id: str, user_id: str
) -> MessageRequestWithHistory:
    """Load conversation history and append the incoming turn, ready for the agent."""
    raw_history = await BotService.load_conversation_history(conversation_id, user_id)
    raw_history.append({"role": "user", "content": body.message})
    history: list[MessageDict] = [
        MessageDict(role=m["role"], content=m["content"]) for m in raw_history
    ]
    return MessageRequestWithHistory(
        message=body.message,
        conversation_id=conversation_id,
        messages=history,
        fileIds=body.file_ids or [],
        fileData=body.file_data or [],
    )


async def charge_bot_turn(user_id: str, body: BotChatRequest) -> None:
    """Charge quota/budget for one bot turn and record its submission event.

    Mirrors what the web chat endpoint charges via @tiered_rate_limit, done
    manually since the caller here has no authenticated request to decorate.
    """
    # Can't be a decorator: the caller has no authenticated request (resolved
    # from a platform link). Without this, bot turns had no quota and never hit
    # record_activity. enforce_rate_limit (above) is separate: flat anti-spam.
    await enforce_tiered_limit(user_id, "chat_messages")
    # Caps how EXPENSIVE the day has been (the tiered limit above caps how MANY
    # messages) — without it, an over-budget bot user got a stream that opened
    # and died partway instead of a clean refusal before any work started.
    await enforce_daily_cost_budget(user_id, feature_key="chat_messages")
    # Captured past every gate, like the web endpoint: a refusal never reached
    # the agent, so counting it here would inflate volume by exactly the users
    # who hit walls most. A refusal is its own event.
    capture_event(
        user_id,
        AnalyticsEvents.CHAT_MESSAGE_SUBMITTED,
        {
            # `source` is the canonical key: a ConversationSource value, the same
            # key every other chat event reports its surface under.
            "source": body.platform,
            "has_files": bool(body.file_ids or body.file_data),
        },
    )
