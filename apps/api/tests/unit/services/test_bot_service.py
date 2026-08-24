"""Unit tests for BotService."""

from unittest.mock import AsyncMock, patch

from fastapi import HTTPException
import pytest

from app.models.bot_models import BotSessionDocument
from app.models.conversation_models import ConversationDocument
from app.services.bot_service import BOT_RATE_LIMIT, BOT_RATE_WINDOW, BotService


def _conv(messages: list[dict]) -> ConversationDocument:
    return ConversationDocument.model_validate(
        {"user_id": "user1", "conversation_id": "conv1", "messages": messages}
    )


def _session(
    conversation_id: str, *, session_key: str = "discord:user123:dm"
) -> BotSessionDocument:
    return BotSessionDocument(
        session_key=session_key,
        conversation_id=conversation_id,
        platform=session_key.split(":", 1)[0],
        platform_user_id="user123",
        channel_id=None,
    )


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_bot_repo():
    """Patch the bot_sessions repository so the session claim/delete is mocked."""
    with patch("app.services.bot_service.bot_session_repository") as mock_repo:
        yield mock_repo


@pytest.fixture
def mock_conversations():
    """Patch the conversation_repository so conversation reads are mocked."""
    with patch("app.services.bot_service.conversation_repository") as mock_repo:
        yield mock_repo


@pytest.fixture
def mock_redis():
    """Patch redis_cache with an async-mock Redis client for rate-limit tests."""
    with patch("app.services.bot_service.redis_cache") as mock_rc:
        mock_rc.redis = AsyncMock()
        yield mock_rc


@pytest.fixture
def mock_create_conversation():
    """Patch create_conversation_service with an async mock for session creation."""
    with patch(
        "app.services.bot_service.create_conversation_service", new_callable=AsyncMock
    ) as mock_fn:
        yield mock_fn


@pytest.fixture
def sample_user():
    """Return a sample user dict with id, email and name for session tests."""
    return {
        "_id": "507f1f77bcf86cd799439011",
        "user_id": "507f1f77bcf86cd799439011",
        "email": "test@example.com",
        "name": "Test User",
    }


# ---------------------------------------------------------------------------
# BotService.enforce_rate_limit
# ---------------------------------------------------------------------------


class TestEnforceRateLimit:
    """Tests for enforce_rate_limit Redis counting, the 429 cap, and fail-open behavior."""

    async def test_first_request_sets_expiry(self, mock_redis):
        mock_redis.redis.incr = AsyncMock(return_value=1)
        mock_redis.redis.expire = AsyncMock()

        await BotService.enforce_rate_limit("discord", "user123")

        mock_redis.redis.incr.assert_awaited_once_with("bot_ratelimit:discord:user123")
        mock_redis.redis.expire.assert_awaited_once_with(
            "bot_ratelimit:discord:user123", BOT_RATE_WINDOW
        )

    async def test_subsequent_request_no_expire(self, mock_redis):
        mock_redis.redis.incr = AsyncMock(return_value=5)

        await BotService.enforce_rate_limit("slack", "user456")

        mock_redis.redis.expire.assert_not_awaited()

    async def test_rate_limit_exceeded(self, mock_redis):
        mock_redis.redis.incr = AsyncMock(return_value=BOT_RATE_LIMIT + 1)

        with pytest.raises(HTTPException) as exc_info:
            await BotService.enforce_rate_limit("telegram", "user789")

        assert exc_info.value.status_code == 429

    async def test_rate_limit_at_boundary_passes(self, mock_redis):
        mock_redis.redis.incr = AsyncMock(return_value=BOT_RATE_LIMIT)

        # Should not raise
        await BotService.enforce_rate_limit("discord", "user123")

    async def test_redis_unavailable_fails_open(self):
        with patch("app.services.bot_service.redis_cache") as mock_rc:
            mock_rc.redis = None
            # Should not raise when Redis is unavailable
            await BotService.enforce_rate_limit("discord", "user123")

    async def test_redis_error_fails_open(self, mock_redis):
        mock_redis.redis.incr = AsyncMock(side_effect=ConnectionError("Redis down"))

        # Should not raise — fail open
        await BotService.enforce_rate_limit("discord", "user123")


# ---------------------------------------------------------------------------
# BotService.build_session_key
# ---------------------------------------------------------------------------


class TestBuildSessionKey:
    """The exact key each surface resolves. A DM has to key the same whether the
    caller came in from the chat (real channel id) or from a background delivery
    that only knows the platform link (no channel id) — otherwise one DM becomes
    two conversations."""

    #: The prod user whose Telegram chat forked across the two key formats.
    TELEGRAM_USER = "6222050155"

    def test_a_telegram_dm_keys_the_same_inbound_and_backend_originated(self):
        """Telegram's private chat id IS the user id, so the inbound path sends it
        as ``channel_id`` while a workflow delivery has none. Both are the same DM."""
        inbound = BotService.build_session_key("telegram", self.TELEGRAM_USER, self.TELEGRAM_USER)
        backend_originated = BotService.build_session_key("telegram", self.TELEGRAM_USER, None)

        assert inbound == f"telegram:{self.TELEGRAM_USER}:{self.TELEGRAM_USER}"
        assert backend_originated == inbound

    def test_a_telegram_group_keys_on_the_group_chat(self):
        key = BotService.build_session_key("telegram", self.TELEGRAM_USER, "-1001234567890")
        assert key == f"telegram:{self.TELEGRAM_USER}:-1001234567890"

    def test_another_platform_keys_its_channel_the_same_way(self):
        assert BotService.build_session_key("discord", "user123", "channel456") == (
            "discord:user123:channel456"
        )
        assert BotService.build_session_key("slack", "user789", None) == "slack:user789:user789"

    def test_an_empty_channel_is_a_dm_not_a_channel_named_empty(self):
        assert BotService.build_session_key("telegram", "user000", "") == "telegram:user000:user000"


# ---------------------------------------------------------------------------
# BotService.get_or_create_session
# ---------------------------------------------------------------------------


class TestGetOrCreateSession:
    """Tests for get_or_create_session reuse, creation, source tagging and deleted-conversation recovery."""

    @staticmethod
    async def _claim_insert(*, candidate_conversation_id: str, session_key: str, **_: object):
        """Simulate a fresh claim: the session commits the candidate id."""
        return _session(candidate_conversation_id, session_key=session_key)

    async def test_returns_existing_session(self, mock_bot_repo, mock_conversations, sample_user):
        mock_bot_repo.claim_session = AsyncMock(return_value=_session("conv-existing"))
        mock_conversations.exists = AsyncMock(return_value=True)

        result = await BotService.get_or_create_session("discord", "user123", None, sample_user)

        assert result == "conv-existing"

    async def test_creates_new_session_when_no_existing(
        self,
        mock_bot_repo,
        mock_conversations,
        mock_create_conversation,
        sample_user,
    ):
        # A fresh claim commits (and returns) the candidate conversation id.
        mock_bot_repo.claim_session = AsyncMock(side_effect=self._claim_insert)
        # No conversation document exists yet for the freshly-minted id.
        mock_conversations.exists = AsyncMock(return_value=False)

        result = await BotService.get_or_create_session("discord", "user123", None, sample_user)

        assert result is not None
        mock_create_conversation.assert_awaited_once()
        mock_bot_repo.claim_session.assert_awaited_once()

    async def test_sets_source_on_created_conversation(
        self,
        mock_bot_repo,
        mock_conversations,
        mock_create_conversation,
        sample_user,
    ):
        """The created bot conversation must carry the platform as its source so the
        web list query's $nin filter excludes it."""
        mock_bot_repo.claim_session = AsyncMock(side_effect=self._claim_insert)
        mock_conversations.exists = AsyncMock(return_value=False)

        await BotService.get_or_create_session("whatsapp", "user123", None, sample_user)

        conversation_model = mock_create_conversation.call_args[0][0]
        assert conversation_model.source is not None
        assert conversation_model.source.value == "whatsapp"

    async def test_recreates_with_same_id_when_conv_deleted(
        self,
        mock_bot_repo,
        mock_conversations,
        mock_create_conversation,
        sample_user,
    ):
        """If the session exists but its conversation was deleted (web UI / race),
        the conversation is recreated with the SAME id — never a new one — so the
        thread is not orphaned or forked."""
        mock_bot_repo.claim_session = AsyncMock(return_value=_session("conv-deleted"))
        mock_conversations.exists = AsyncMock(return_value=False)

        result = await BotService.get_or_create_session("discord", "user123", None, sample_user)

        # Same id is reused — no minting + repointing.
        assert result == "conv-deleted"
        mock_create_conversation.assert_awaited_once()
        recreated_model = mock_create_conversation.call_args[0][0]
        assert recreated_model.conversation_id == "conv-deleted"

    async def test_does_not_repoint_session_when_conv_deleted(
        self,
        mock_bot_repo,
        mock_conversations,
        mock_create_conversation,
        sample_user,
    ):
        """Recreation must not mint a new conversation_id that differs from the one
        already stored on the session."""
        mock_bot_repo.claim_session = AsyncMock(return_value=_session("conv-deleted"))
        mock_conversations.exists = AsyncMock(return_value=False)

        result = await BotService.get_or_create_session("discord", "user123", None, sample_user)

        # The candidate id passed to claim_session is discarded on an existing
        # session, so the returned id must be the stored one.
        assert result == "conv-deleted"

    async def test_normalizes_user_dict_with_underscore_id(
        self,
        mock_bot_repo,
        mock_conversations,
        mock_create_conversation,
    ):
        """User dict with _id but no user_id should be normalized."""
        user = {"_id": "507f1f77bcf86cd799439011", "email": "test@example.com"}
        mock_bot_repo.claim_session = AsyncMock(side_effect=self._claim_insert)
        mock_conversations.exists = AsyncMock(return_value=False)

        result = await BotService.get_or_create_session("discord", "user123", None, user)

        assert result is not None
        mock_create_conversation.assert_awaited_once()

    async def test_conversation_description_uses_platform(
        self,
        mock_bot_repo,
        mock_conversations,
        mock_create_conversation,
        sample_user,
    ):
        mock_bot_repo.claim_session = AsyncMock(side_effect=self._claim_insert)
        mock_conversations.exists = AsyncMock(return_value=False)

        await BotService.get_or_create_session("telegram", "user123", None, sample_user)

        call_args = mock_create_conversation.call_args
        conversation_model = call_args[0][0]
        assert conversation_model.description == "Telegram Chat"


# ---------------------------------------------------------------------------
# BotService.reset_session
# ---------------------------------------------------------------------------


class TestResetSession:
    """Tests for reset_session deleting the old session and minting a fresh one."""

    async def test_deletes_existing_and_creates_new(
        self,
        mock_bot_repo,
        mock_conversations,
        mock_create_conversation,
        sample_user,
    ):
        mock_bot_repo.delete_by_session_key = AsyncMock()
        mock_bot_repo.claim_session = AsyncMock(side_effect=TestGetOrCreateSession._claim_insert)
        mock_conversations.exists = AsyncMock(return_value=False)

        result = await BotService.reset_session("discord", "user123", None, sample_user)

        assert result is not None
        mock_bot_repo.delete_by_session_key.assert_awaited_once_with("discord:user123:user123")

    async def test_reset_with_channel_id(
        self,
        mock_bot_repo,
        mock_conversations,
        mock_create_conversation,
        sample_user,
    ):
        mock_bot_repo.delete_by_session_key = AsyncMock()
        mock_bot_repo.claim_session = AsyncMock(side_effect=TestGetOrCreateSession._claim_insert)
        mock_conversations.exists = AsyncMock(return_value=False)

        await BotService.reset_session("slack", "user123", "channel789", sample_user)

        mock_bot_repo.delete_by_session_key.assert_awaited_once_with("slack:user123:channel789")


# ---------------------------------------------------------------------------
# BotService.load_conversation_history
# ---------------------------------------------------------------------------


class TestLoadConversationHistory:
    """Tests for load_conversation_history mapping stored messages to roles and applying the limit."""

    async def test_returns_empty_when_no_conv(self, mock_conversations):
        mock_conversations.get = AsyncMock(return_value=None)

        result = await BotService.load_conversation_history("conv1", "user1")

        assert result == []

    async def test_returns_empty_when_no_messages(self, mock_conversations):
        mock_conversations.get = AsyncMock(return_value=_conv([]))

        result = await BotService.load_conversation_history("conv1", "user1")

        assert result == []

    async def test_maps_user_messages(self, mock_conversations):
        mock_conversations.get = AsyncMock(
            return_value=_conv([{"type": "user", "response": "Hello"}])
        )

        result = await BotService.load_conversation_history("conv1", "user1")

        assert len(result) == 1
        assert result[0] == {"role": "user", "content": "Hello"}

    async def test_maps_bot_messages(self, mock_conversations):
        mock_conversations.get = AsyncMock(
            return_value=_conv([{"type": "bot", "response": "Hi there!"}])
        )

        result = await BotService.load_conversation_history("conv1", "user1")

        assert len(result) == 1
        assert result[0] == {"role": "assistant", "content": "Hi there!"}

    async def test_skips_unknown_message_types(self, mock_conversations):
        mock_conversations.get = AsyncMock(
            return_value=_conv(
                [
                    {"type": "system", "response": "System msg"},
                    {"type": "user", "response": "Hello"},
                ]
            )
        )

        result = await BotService.load_conversation_history("conv1", "user1")

        assert len(result) == 1
        assert result[0]["role"] == "user"

    async def test_respects_limit(self, mock_conversations):
        messages = [{"type": "user", "response": f"msg{i}"} for i in range(30)]
        mock_conversations.get = AsyncMock(return_value=_conv(messages))

        result = await BotService.load_conversation_history("conv1", "user1", limit=5)

        # Should only return the last 5 messages
        assert len(result) == 5
        assert result[0]["content"] == "msg25"

    async def test_handles_empty_response_field(self, mock_conversations):
        mock_conversations.get = AsyncMock(return_value=_conv([{"type": "user", "response": ""}]))

        result = await BotService.load_conversation_history("conv1", "user1")

        assert len(result) == 1
        assert result[0]["content"] == ""
