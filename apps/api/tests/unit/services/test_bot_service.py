"""Unit tests for BotService."""

from unittest.mock import AsyncMock, patch

from fastapi import HTTPException
import pytest

from app.services.bot_service import BOT_RATE_LIMIT, BOT_RATE_WINDOW, BotService

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_bot_sessions():
    """Patch the bot_sessions_collection so session lookups/upserts are mocked."""
    with patch("app.services.bot_service.bot_sessions_collection") as mock_col:
        yield mock_col


@pytest.fixture
def mock_conversations():
    """Patch the conversations_collection so conversation reads are mocked."""
    with patch("app.services.bot_service.conversations_collection") as mock_col:
        yield mock_col


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


@pytest.mark.unit
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


@pytest.mark.unit
class TestBuildSessionKey:
    """Tests for build_session_key formatting, including the DM fallback for missing channels."""

    def test_with_channel_id(self):
        key = BotService.build_session_key("discord", "user123", "channel456")
        assert key == "discord:user123:channel456"

    def test_without_channel_id_uses_dm(self):
        key = BotService.build_session_key("slack", "user789", None)
        assert key == "slack:user789:dm"

    def test_empty_string_channel_uses_dm(self):
        key = BotService.build_session_key("telegram", "user000", "")
        assert key == "telegram:user000:dm"


# ---------------------------------------------------------------------------
# BotService.get_or_create_session
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestGetOrCreateSession:
    """Tests for get_or_create_session reuse, creation, source tagging and deleted-conversation recovery."""

    @staticmethod
    def _existing_session(conversation_id: str, session_key: str = "discord:user123:dm"):
        """find_one_and_update returns the pre-existing session unchanged on a match."""
        return {"session_key": session_key, "conversation_id": conversation_id}

    @staticmethod
    def _inserted_session(update_filter, update, *, return_document=None, upsert=None):
        """Simulate an upsert insert: return the doc carrying the $setOnInsert id."""
        set_on_insert = update["$setOnInsert"]
        return {
            "session_key": set_on_insert["session_key"],
            "conversation_id": set_on_insert["conversation_id"],
        }

    async def test_returns_existing_session(
        self, mock_bot_sessions, mock_conversations, sample_user
    ):
        mock_bot_sessions.find_one_and_update = AsyncMock(
            return_value=self._existing_session("conv-existing")
        )
        mock_conversations.find_one = AsyncMock(return_value={"_id": "some-id"})

        result = await BotService.get_or_create_session("discord", "user123", None, sample_user)

        assert result == "conv-existing"

    async def test_creates_new_session_when_no_existing(
        self,
        mock_bot_sessions,
        mock_conversations,
        mock_create_conversation,
        sample_user,
    ):
        # find_one_and_update inserts a fresh session (returns the $setOnInsert id).
        mock_bot_sessions.find_one_and_update = AsyncMock(side_effect=self._inserted_session)
        # No conversation document exists yet for the freshly-minted id.
        mock_conversations.find_one = AsyncMock(return_value=None)

        result = await BotService.get_or_create_session("discord", "user123", None, sample_user)

        assert result is not None
        mock_create_conversation.assert_awaited_once()
        mock_bot_sessions.find_one_and_update.assert_awaited_once()

    async def test_sets_source_on_created_conversation(
        self,
        mock_bot_sessions,
        mock_conversations,
        mock_create_conversation,
        sample_user,
    ):
        """The created bot conversation must carry the platform as its source so the
        web list query's $nin filter excludes it."""
        mock_bot_sessions.find_one_and_update = AsyncMock(side_effect=self._inserted_session)
        mock_conversations.find_one = AsyncMock(return_value=None)

        await BotService.get_or_create_session("whatsapp", "user123", None, sample_user)

        conversation_model = mock_create_conversation.call_args[0][0]
        assert conversation_model.source is not None
        assert conversation_model.source.value == "whatsapp"

    async def test_recreates_with_same_id_when_conv_deleted(
        self,
        mock_bot_sessions,
        mock_conversations,
        mock_create_conversation,
        sample_user,
    ):
        """If the session exists but its conversation was deleted (web UI / race),
        the conversation is recreated with the SAME id — never a new one — so the
        thread is not orphaned or forked."""
        mock_bot_sessions.find_one_and_update = AsyncMock(
            return_value=self._existing_session("conv-deleted")
        )
        mock_conversations.find_one = AsyncMock(return_value=None)

        result = await BotService.get_or_create_session("discord", "user123", None, sample_user)

        # Same id is reused — no minting + repointing.
        assert result == "conv-deleted"
        mock_create_conversation.assert_awaited_once()
        recreated_model = mock_create_conversation.call_args[0][0]
        assert recreated_model.conversation_id == "conv-deleted"

    async def test_does_not_repoint_session_when_conv_deleted(
        self,
        mock_bot_sessions,
        mock_conversations,
        mock_create_conversation,
        sample_user,
    ):
        """Recreation must not mint a new conversation_id that differs from the one
        already stored on the session."""
        mock_bot_sessions.find_one_and_update = AsyncMock(
            return_value=self._existing_session("conv-deleted")
        )
        mock_conversations.find_one = AsyncMock(return_value=None)

        result = await BotService.get_or_create_session("discord", "user123", None, sample_user)

        # The id sent to find_one_and_update's $setOnInsert is a *candidate* only; on
        # an existing session it is discarded, so the returned id must be the stored one.
        assert result == "conv-deleted"

    async def test_normalizes_user_dict_with_underscore_id(
        self,
        mock_bot_sessions,
        mock_conversations,
        mock_create_conversation,
    ):
        """User dict with _id but no user_id should be normalized."""
        user = {"_id": "507f1f77bcf86cd799439011", "email": "test@example.com"}
        mock_bot_sessions.find_one_and_update = AsyncMock(side_effect=self._inserted_session)
        mock_conversations.find_one = AsyncMock(return_value=None)

        result = await BotService.get_or_create_session("discord", "user123", None, user)

        assert result is not None
        mock_create_conversation.assert_awaited_once()

    async def test_conversation_description_uses_platform(
        self,
        mock_bot_sessions,
        mock_conversations,
        mock_create_conversation,
        sample_user,
    ):
        mock_bot_sessions.find_one_and_update = AsyncMock(side_effect=self._inserted_session)
        mock_conversations.find_one = AsyncMock(return_value=None)

        await BotService.get_or_create_session("telegram", "user123", None, sample_user)

        call_args = mock_create_conversation.call_args
        conversation_model = call_args[0][0]
        assert conversation_model.description == "Telegram Chat"


# ---------------------------------------------------------------------------
# BotService.reset_session
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestResetSession:
    """Tests for reset_session deleting the old session and minting a fresh one."""

    async def test_deletes_existing_and_creates_new(
        self,
        mock_bot_sessions,
        mock_conversations,
        mock_create_conversation,
        sample_user,
    ):
        mock_bot_sessions.delete_one = AsyncMock()
        mock_bot_sessions.find_one_and_update = AsyncMock(
            side_effect=TestGetOrCreateSession._inserted_session
        )
        mock_conversations.find_one = AsyncMock(return_value=None)

        result = await BotService.reset_session("discord", "user123", None, sample_user)

        assert result is not None
        mock_bot_sessions.delete_one.assert_awaited_once_with({"session_key": "discord:user123:dm"})

    async def test_reset_with_channel_id(
        self,
        mock_bot_sessions,
        mock_conversations,
        mock_create_conversation,
        sample_user,
    ):
        mock_bot_sessions.delete_one = AsyncMock()
        mock_bot_sessions.find_one_and_update = AsyncMock(
            side_effect=TestGetOrCreateSession._inserted_session
        )
        mock_conversations.find_one = AsyncMock(return_value=None)

        await BotService.reset_session("slack", "user123", "channel789", sample_user)

        mock_bot_sessions.delete_one.assert_awaited_once_with(
            {"session_key": "slack:user123:channel789"}
        )


# ---------------------------------------------------------------------------
# BotService.load_conversation_history
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestLoadConversationHistory:
    """Tests for load_conversation_history mapping stored messages to roles and applying the limit."""

    async def test_returns_empty_when_no_conv(self, mock_conversations):
        mock_conversations.find_one = AsyncMock(return_value=None)

        result = await BotService.load_conversation_history("conv1", "user1")

        assert result == []

    async def test_returns_empty_when_no_messages(self, mock_conversations):
        mock_conversations.find_one = AsyncMock(return_value={"messages": []})

        result = await BotService.load_conversation_history("conv1", "user1")

        assert result == []

    async def test_returns_empty_when_messages_key_missing(self, mock_conversations):
        mock_conversations.find_one = AsyncMock(return_value={})

        result = await BotService.load_conversation_history("conv1", "user1")

        assert result == []

    async def test_maps_user_messages(self, mock_conversations):
        mock_conversations.find_one = AsyncMock(
            return_value={
                "messages": [
                    {"type": "user", "response": "Hello"},
                ]
            }
        )

        result = await BotService.load_conversation_history("conv1", "user1")

        assert len(result) == 1
        assert result[0] == {"role": "user", "content": "Hello"}

    async def test_maps_bot_messages(self, mock_conversations):
        mock_conversations.find_one = AsyncMock(
            return_value={
                "messages": [
                    {"type": "bot", "response": "Hi there!"},
                ]
            }
        )

        result = await BotService.load_conversation_history("conv1", "user1")

        assert len(result) == 1
        assert result[0] == {"role": "assistant", "content": "Hi there!"}

    async def test_skips_unknown_message_types(self, mock_conversations):
        mock_conversations.find_one = AsyncMock(
            return_value={
                "messages": [
                    {"type": "system", "response": "System msg"},
                    {"type": "user", "response": "Hello"},
                ]
            }
        )

        result = await BotService.load_conversation_history("conv1", "user1")

        assert len(result) == 1
        assert result[0]["role"] == "user"

    async def test_respects_limit(self, mock_conversations):
        messages = [{"type": "user", "response": f"msg{i}"} for i in range(30)]
        mock_conversations.find_one = AsyncMock(return_value={"messages": messages})

        result = await BotService.load_conversation_history("conv1", "user1", limit=5)

        # Should only return the last 5 messages
        assert len(result) == 5
        assert result[0]["content"] == "msg25"

    async def test_handles_missing_response_field(self, mock_conversations):
        mock_conversations.find_one = AsyncMock(
            return_value={
                "messages": [
                    {"type": "user"},
                ]
            }
        )

        result = await BotService.load_conversation_history("conv1", "user1")

        assert len(result) == 1
        assert result[0]["content"] == ""
