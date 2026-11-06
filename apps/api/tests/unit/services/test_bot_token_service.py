"""Bot session tokens: what create_bot_session_token mints and what verify_bot_session_token accepts."""

from datetime import UTC, datetime, timedelta
from unittest.mock import patch

from jwt import InvalidTokenError
import pytest

from app.config.settings import settings
from app.constants.auth import JWT_ALGORITHM
from app.services.bot_token_service import (
    BOT_SESSION_TOKEN_EXPIRY_MINUTES,
    BotSessionClaims,
    create_bot_session_token,
    verify_bot_session_token,
)
from tests.helpers import JOSE_MINTED_BOT_TOKEN, bot_jwt_claims, forge_jwt, hostile_jwts, read_jwt

TEST_BOT_SESSION_SECRET = "a" * 64
TEST_USER_ID = "507f1f77bcf86cd799439011"
TEST_PLATFORM = "discord"
TEST_PLATFORM_USER_ID = "123456789012345678"


@pytest.fixture(autouse=True)
def _bot_session_secret():
    with patch.object(settings, "BOT_SESSION_TOKEN_SECRET", TEST_BOT_SESSION_SECRET):
        yield


class TestBotTokenService:
    """Tests for the bot session token create/verify cycle."""

    def test_create_and_verify_token(self) -> None:
        """Create a bot session token and verify it returns correct payload."""
        token = create_bot_session_token(
            user_id=TEST_USER_ID,
            platform=TEST_PLATFORM,
            platform_user_id=TEST_PLATFORM_USER_ID,
        )

        payload = verify_bot_session_token(token)

        assert payload.user_id == TEST_USER_ID
        assert payload.platform == TEST_PLATFORM
        assert payload.platform_user_id == TEST_PLATFORM_USER_ID

    def test_token_contains_correct_claims(self) -> None:
        """Verify the raw JWT claims include role=bot, correct sub, and expiry."""
        token = create_bot_session_token(
            user_id=TEST_USER_ID,
            platform="slack",
            platform_user_id="U999",
            expires_minutes=10,
        )

        _, raw = read_jwt(token)

        assert raw["sub"] == TEST_USER_ID
        assert raw["platform"] == "slack"
        assert raw["platform_user_id"] == "U999"
        assert raw["role"] == "bot"
        assert "exp" in raw
        assert "iat" in raw

    def test_expired_token_rejected(self) -> None:
        """A token created with a past expiry is rejected on verification."""
        token = create_bot_session_token(
            user_id=TEST_USER_ID,
            platform=TEST_PLATFORM,
            platform_user_id=TEST_PLATFORM_USER_ID,
            expires_minutes=-1,  # Already expired
        )

        with pytest.raises(InvalidTokenError, match="Token verification failed"):
            verify_bot_session_token(token)

    def test_tampered_token_rejected(self) -> None:
        """A token signed with a different secret is rejected."""
        wrong_secret = "b" * 64
        expire = datetime.now(UTC) + timedelta(minutes=15)
        payload = {
            "sub": TEST_USER_ID,
            "platform": TEST_PLATFORM,
            "platform_user_id": TEST_PLATFORM_USER_ID,
            "role": "bot",
            "exp": int(expire.timestamp()),
            "iat": int(datetime.now(UTC).timestamp()),
        }
        bad_token = forge_jwt(payload, wrong_secret, alg=JWT_ALGORITHM)

        with pytest.raises(InvalidTokenError, match="Token verification failed"):
            verify_bot_session_token(bad_token)

    def test_a_token_minted_by_python_jose_still_verifies(self) -> None:
        assert verify_bot_session_token(JOSE_MINTED_BOT_TOKEN) == BotSessionClaims(
            user_id="u-jose",
            platform="telegram",
            platform_user_id="tg-jose",
        )

    @pytest.mark.parametrize("kind", sorted(hostile_jwts({}, "s")))
    def test_a_hostile_token_is_rejected(self, kind: str) -> None:
        token = hostile_jwts(
            bot_jwt_claims(TEST_USER_ID, TEST_PLATFORM, TEST_PLATFORM_USER_ID),
            TEST_BOT_SESSION_SECRET,
        )[kind]
        with pytest.raises(InvalidTokenError, match="^Token verification failed: "):
            verify_bot_session_token(token)

    def test_a_claim_of_the_wrong_type_is_rejected(self) -> None:
        token = forge_jwt(
            {
                **bot_jwt_claims(TEST_USER_ID, TEST_PLATFORM, TEST_PLATFORM_USER_ID),
                "platform_user_id": 42,
            },
            TEST_BOT_SESSION_SECRET,
            alg=JWT_ALGORITHM,
        )

        with pytest.raises(InvalidTokenError, match="^Token verification failed: "):
            verify_bot_session_token(token)

    def test_wrong_role_rejected(self) -> None:
        """A token with role != 'bot' is rejected even if otherwise valid."""
        expire = datetime.now(UTC) + timedelta(minutes=15)
        payload = {
            "sub": TEST_USER_ID,
            "platform": TEST_PLATFORM,
            "platform_user_id": TEST_PLATFORM_USER_ID,
            "role": "agent",  # Wrong role
            "exp": int(expire.timestamp()),
            "iat": int(datetime.now(UTC).timestamp()),
        }
        token = forge_jwt(payload, TEST_BOT_SESSION_SECRET, alg=JWT_ALGORITHM)

        with pytest.raises(
            InvalidTokenError, match="^Token verification failed: Invalid token role$"
        ):
            verify_bot_session_token(token)

    def test_missing_secret_raises_value_error(self) -> None:
        """Creating a token without BOT_SESSION_TOKEN_SECRET configured raises ValueError."""
        with patch.object(settings, "BOT_SESSION_TOKEN_SECRET", None):
            with pytest.raises(ValueError, match="BOT_SESSION_TOKEN_SECRET is required"):
                create_bot_session_token(
                    user_id=TEST_USER_ID,
                    platform=TEST_PLATFORM,
                    platform_user_id=TEST_PLATFORM_USER_ID,
                )

    def test_short_secret_raises_value_error(self) -> None:
        """A secret shorter than 32 characters is rejected."""
        with patch.object(settings, "BOT_SESSION_TOKEN_SECRET", "short"):
            with pytest.raises(ValueError, match="must be at least 32 characters"):
                create_bot_session_token(
                    user_id=TEST_USER_ID,
                    platform=TEST_PLATFORM,
                    platform_user_id=TEST_PLATFORM_USER_ID,
                )

    def test_default_expiry_is_15_minutes(self) -> None:
        """Default token expiry matches BOT_SESSION_TOKEN_EXPIRY_MINUTES constant."""
        assert BOT_SESSION_TOKEN_EXPIRY_MINUTES == 15

        token = create_bot_session_token(
            user_id=TEST_USER_ID,
            platform=TEST_PLATFORM,
            platform_user_id=TEST_PLATFORM_USER_ID,
        )
        _, raw = read_jwt(token)

        iat = datetime.fromtimestamp(raw["iat"], tz=UTC)
        exp = datetime.fromtimestamp(raw["exp"], tz=UTC)
        delta = exp - iat
        # Allow 2 seconds of clock drift between iat and exp computation
        assert timedelta(minutes=14, seconds=58) <= delta <= timedelta(minutes=15, seconds=2)
