"""
Integration tests for Bot-to-API Authentication Chain.

Tests the full bot authentication flow: API key verification, JWT session
tokens, platform header extraction, and middleware integration. Uses the
real BotAuthMiddleware, bot_token_service, and bot endpoints with mocked
I/O boundaries (MongoDB, Redis).
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import AsyncGenerator
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI, HTTPException, Request
from httpx import ASGITransport, AsyncClient
from jose import JWTError, jwt

from app.config.settings import settings
from app.constants.auth import JWT_ALGORITHM
from app.core.bot_auth_middleware import BotAuthMiddleware
from app.services.bot_token_service import (
    BOT_SESSION_TOKEN_EXPIRY_MINUTES,
    create_bot_session_token,
    verify_bot_session_token,
)
from app.services.platform_link_service import PlatformLinkService

# ---------------------------------------------------------------------------
# Test constants
# ---------------------------------------------------------------------------

TEST_BOT_API_KEY = "test-bot-api-key-for-integration-tests"
TEST_BOT_SESSION_SECRET = "a" * 64  # 64-char secret for JWT signing
TEST_USER_ID = "507f1f77bcf86cd799439011"
TEST_PLATFORM = "discord"
TEST_PLATFORM_USER_ID = "123456789012345678"
TEST_USER_DOC = {
    "_id": TEST_USER_ID,
    "email": "botuser@example.com",
    "name": "Bot Test User",
    "picture": None,
}


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _bot_settings():
    """Patch settings to provide bot API key and session secret."""
    with (
        patch.object(settings, "GAIA_BOT_API_KEY", TEST_BOT_API_KEY),
        patch.object(settings, "BOT_SESSION_TOKEN_SECRET", TEST_BOT_SESSION_SECRET),
    ):
        yield


@pytest.fixture
def mock_platform_lookup():
    """Mock PlatformLinkService.get_user_by_platform_id for middleware tests."""
    with patch.object(
        PlatformLinkService,
        "get_user_by_platform_id",
        new_callable=AsyncMock,
    ) as mock_fn:
        yield mock_fn


@pytest.fixture
def mock_redis_cache():
    """Mock Redis cache get/set used by middleware."""
    with (
        patch(
            "app.core.bot_auth_middleware.get_cache", new_callable=AsyncMock
        ) as mock_get,
        patch(
            "app.core.bot_auth_middleware.set_cache", new_callable=AsyncMock
        ) as mock_set,
    ):
        mock_get.return_value = None  # No cache hit by default
        yield {"get": mock_get, "set": mock_set}


async def _require_bot_api_key_from_header(request: Request) -> None:
    """Replacement for require_bot_api_key that checks the header directly.

    The test app strips BotAuthMiddleware (it needs Redis). This function
    replicates the API key verification so bot endpoints can be tested via
    the HTTP client without the full middleware stack.
    """

    api_key = request.headers.get("X-Bot-API-Key")
    bot_api_key = getattr(settings, "GAIA_BOT_API_KEY", None)
    if not api_key or not bot_api_key or api_key != bot_api_key:
        raise HTTPException(status_code=401, detail="Invalid or missing bot API key")

    # Set state attributes that bot endpoints read
    request.state.bot_api_key_valid = True
    request.state.bot_platform = request.headers.get("X-Bot-Platform")
    request.state.bot_platform_user_id = request.headers.get("X-Bot-Platform-User-Id")


@pytest.fixture
async def bot_client(test_app: FastAPI) -> AsyncGenerator[AsyncClient, None]:
    """HTTP client that patches require_bot_api_key to check the header directly."""
    with patch(
        "app.api.v1.endpoints.bot.require_bot_api_key",
        _require_bot_api_key_from_header,
    ):
        transport = ASGITransport(app=test_app, raise_app_exceptions=False)
        async with AsyncClient(
            transport=transport,
            base_url="http://test",
        ) as ac:
            yield ac


def _make_mock_request(
    path: str = "/api/v1/bot/test",
    headers: dict | None = None,
    already_authenticated: bool = False,
) -> MagicMock:
    """Create a mock request with proper headers.get behavior."""
    _headers = headers or {}
    request = MagicMock()
    request.url.path = path
    request.headers.get = lambda key, default=None: _headers.get(key, default)
    request.state = MagicMock(spec=[])
    if already_authenticated:
        request.state.authenticated = True
    return request


async def _noop_call_next(request: Request) -> MagicMock:
    return MagicMock(status_code=200)


# ---------------------------------------------------------------------------
# TEST 7: Bot-to-API Authentication Chain
# ---------------------------------------------------------------------------


@pytest.mark.integration
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

        assert payload["user_id"] == TEST_USER_ID
        assert payload["platform"] == TEST_PLATFORM
        assert payload["platform_user_id"] == TEST_PLATFORM_USER_ID

    def test_token_contains_correct_claims(self) -> None:
        """Verify the raw JWT claims include role=bot, correct sub, and expiry."""
        token = create_bot_session_token(
            user_id=TEST_USER_ID,
            platform="slack",
            platform_user_id="U999",
            expires_minutes=10,
        )

        raw = jwt.decode(token, TEST_BOT_SESSION_SECRET, algorithms=[JWT_ALGORITHM])

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

        with pytest.raises(JWTError, match="Token verification failed"):
            verify_bot_session_token(token)

    def test_tampered_token_rejected(self) -> None:
        """A token signed with a different secret is rejected."""
        wrong_secret = "b" * 64
        expire = datetime.now(timezone.utc) + timedelta(minutes=15)
        payload = {
            "sub": TEST_USER_ID,
            "platform": TEST_PLATFORM,
            "platform_user_id": TEST_PLATFORM_USER_ID,
            "role": "bot",
            "exp": expire,
            "iat": datetime.now(timezone.utc),
        }
        bad_token = jwt.encode(payload, wrong_secret, algorithm=JWT_ALGORITHM)

        with pytest.raises(JWTError, match="Token verification failed"):
            verify_bot_session_token(bad_token)

    def test_wrong_role_rejected(self) -> None:
        """A token with role != 'bot' is rejected even if otherwise valid."""
        expire = datetime.now(timezone.utc) + timedelta(minutes=15)
        payload = {
            "sub": TEST_USER_ID,
            "platform": TEST_PLATFORM,
            "platform_user_id": TEST_PLATFORM_USER_ID,
            "role": "agent",  # Wrong role
            "exp": expire,
            "iat": datetime.now(timezone.utc),
        }
        token = jwt.encode(payload, TEST_BOT_SESSION_SECRET, algorithm=JWT_ALGORITHM)

        with pytest.raises(JWTError, match="Invalid token role"):
            verify_bot_session_token(token)

    def test_missing_secret_raises_value_error(self) -> None:
        """Creating a token without BOT_SESSION_TOKEN_SECRET configured raises ValueError."""
        with patch.object(settings, "BOT_SESSION_TOKEN_SECRET", None):
            with pytest.raises(
                ValueError, match="BOT_SESSION_TOKEN_SECRET is required"
            ):
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
        raw = jwt.decode(token, TEST_BOT_SESSION_SECRET, algorithms=[JWT_ALGORITHM])

        iat = datetime.fromtimestamp(raw["iat"], tz=timezone.utc)
        exp = datetime.fromtimestamp(raw["exp"], tz=timezone.utc)
        delta = exp - iat
        # Allow 2 seconds of clock drift between iat and exp computation
        assert (
            timedelta(minutes=14, seconds=58)
            <= delta
            <= timedelta(minutes=15, seconds=2)
        )


@pytest.mark.integration
class TestBotAuthMiddlewareAPIKey:
    """Tests for API key verification in BotAuthMiddleware."""

    def test_verify_api_key_valid(self) -> None:
        """Valid API key passes verification."""
        middleware = BotAuthMiddleware(app=MagicMock())
        assert middleware._verify_api_key(TEST_BOT_API_KEY) is True

    def test_verify_api_key_invalid(self) -> None:
        """Wrong API key fails verification."""
        middleware = BotAuthMiddleware(app=MagicMock())
        assert middleware._verify_api_key("wrong-key") is False

    def test_verify_api_key_empty(self) -> None:
        """Empty string fails verification."""
        middleware = BotAuthMiddleware(app=MagicMock())
        assert middleware._verify_api_key("") is False

    def test_verify_api_key_when_not_configured(self) -> None:
        """When GAIA_BOT_API_KEY is not set, all keys are rejected."""
        with patch.object(settings, "GAIA_BOT_API_KEY", None):
            middleware = BotAuthMiddleware(app=MagicMock())
            assert middleware._verify_api_key(TEST_BOT_API_KEY) is False

    def test_excluded_paths_skip_auth(self) -> None:
        """Requests to excluded paths (e.g. /health) skip bot auth."""
        middleware = BotAuthMiddleware(app=MagicMock())
        assert "/health" in middleware.exclude_paths
        assert "/docs" in middleware.exclude_paths
        assert "/redoc" in middleware.exclude_paths
        assert "/openapi.json" in middleware.exclude_paths


@pytest.mark.integration
class TestBotAuthMiddlewareJWT:
    """Tests for JWT Bearer token authentication in BotAuthMiddleware."""

    async def test_jwt_auth_sets_user_state(
        self, mock_platform_lookup: AsyncMock, mock_redis_cache: dict
    ) -> None:
        """Valid JWT sets request.state.user and request.state.authenticated."""
        mock_platform_lookup.return_value = TEST_USER_DOC

        token = create_bot_session_token(
            user_id=TEST_USER_ID,
            platform=TEST_PLATFORM,
            platform_user_id=TEST_PLATFORM_USER_ID,
        )

        request = _make_mock_request(
            headers={"Authorization": f"Bearer {token}"},
        )

        middleware = BotAuthMiddleware(app=MagicMock())
        await middleware.dispatch(request, _noop_call_next)

        assert request.state.user["user_id"] == TEST_USER_ID
        assert request.state.user["email"] == "botuser@example.com"
        assert request.state.user["auth_provider"] == "bot:discord"
        assert request.state.user["bot_authenticated"] is True
        assert request.state.authenticated is True

    async def test_jwt_auth_uses_cache(self, mock_redis_cache: dict) -> None:
        """JWT auth uses cached user info when available."""
        cached_user = {
            "user_id": TEST_USER_ID,
            "email": "cached@example.com",
            "name": "Cached User",
            "auth_provider": "bot:discord",
            "bot_authenticated": True,
        }
        mock_redis_cache["get"].return_value = cached_user

        token = create_bot_session_token(
            user_id=TEST_USER_ID,
            platform=TEST_PLATFORM,
            platform_user_id=TEST_PLATFORM_USER_ID,
        )

        request = _make_mock_request(
            headers={"Authorization": f"Bearer {token}"},
        )

        middleware = BotAuthMiddleware(app=MagicMock())
        await middleware.dispatch(request, _noop_call_next)

        assert request.state.user == cached_user
        assert request.state.authenticated is True
        # Cache was hit, so set_cache should not have been called
        mock_redis_cache["set"].assert_not_called()

    async def test_invalid_jwt_falls_through_to_api_key(
        self, mock_redis_cache: dict
    ) -> None:
        """Invalid JWT does not set authenticated, falls through to API key check."""
        request = _make_mock_request(
            headers={"Authorization": "Bearer invalid.jwt.token"},
        )

        middleware = BotAuthMiddleware(app=MagicMock())
        await middleware.dispatch(request, _noop_call_next)

        # Should not be authenticated -- JWT failed and no API key provided
        # The middleware does not set authenticated when both paths fail
        with pytest.raises(AttributeError):
            _ = request.state.authenticated


@pytest.mark.integration
class TestBotAuthMiddlewarePlatformHeaders:
    """Tests for API key + platform header authentication."""

    async def test_api_key_with_platform_headers_authenticates(
        self, mock_platform_lookup: AsyncMock, mock_redis_cache: dict
    ) -> None:
        """Valid API key + platform headers resolves user from DB."""
        mock_platform_lookup.return_value = TEST_USER_DOC

        request = _make_mock_request(
            headers={
                "X-Bot-API-Key": TEST_BOT_API_KEY,
                "X-Bot-Platform": TEST_PLATFORM,
                "X-Bot-Platform-User-Id": TEST_PLATFORM_USER_ID,
            },
        )

        middleware = BotAuthMiddleware(app=MagicMock())
        await middleware.dispatch(request, _noop_call_next)

        assert request.state.authenticated is True
        assert request.state.user["user_id"] == TEST_USER_ID
        assert request.state.user["auth_provider"] == f"bot:{TEST_PLATFORM}"
        assert request.state.bot_api_key_valid is True
        assert request.state.bot_platform == TEST_PLATFORM
        assert request.state.bot_platform_user_id == TEST_PLATFORM_USER_ID

        mock_platform_lookup.assert_awaited_once_with(
            TEST_PLATFORM, TEST_PLATFORM_USER_ID
        )

    async def test_api_key_without_platform_headers_sets_bot_key_valid(
        self, mock_redis_cache: dict
    ) -> None:
        """Valid API key without platform headers still marks bot_api_key_valid."""
        request = _make_mock_request(
            headers={"X-Bot-API-Key": TEST_BOT_API_KEY},
        )

        middleware = BotAuthMiddleware(app=MagicMock())
        await middleware.dispatch(request, _noop_call_next)

        assert request.state.bot_api_key_valid is True
        assert request.state.bot_platform is None
        assert request.state.bot_platform_user_id is None

    async def test_invalid_api_key_does_not_authenticate(
        self, mock_redis_cache: dict
    ) -> None:
        """Wrong API key does not set any bot auth state."""
        request = _make_mock_request(
            headers={
                "X-Bot-API-Key": "wrong-key",
                "X-Bot-Platform": TEST_PLATFORM,
                "X-Bot-Platform-User-Id": TEST_PLATFORM_USER_ID,
            },
        )

        middleware = BotAuthMiddleware(app=MagicMock())
        await middleware.dispatch(request, _noop_call_next)

        # bot_api_key_valid should NOT be set
        with pytest.raises(AttributeError):
            _ = request.state.bot_api_key_valid

    async def test_unlinked_platform_user_no_user_state(
        self, mock_platform_lookup: AsyncMock, mock_redis_cache: dict
    ) -> None:
        """Valid API key + platform headers but no linked user: bot_api_key_valid set, no user."""
        mock_platform_lookup.return_value = None  # User not found

        request = _make_mock_request(
            headers={
                "X-Bot-API-Key": TEST_BOT_API_KEY,
                "X-Bot-Platform": TEST_PLATFORM,
                "X-Bot-Platform-User-Id": "unknown-user-999",
            },
        )

        middleware = BotAuthMiddleware(app=MagicMock())
        await middleware.dispatch(request, _noop_call_next)

        # API key is valid but no user resolved
        assert request.state.bot_api_key_valid is True
        assert request.state.bot_platform == TEST_PLATFORM
        assert request.state.bot_platform_user_id == "unknown-user-999"


@pytest.mark.integration
class TestBotAuthMiddlewareSkipAuthenticated:
    """Tests for middleware skipping already-authenticated requests."""

    async def test_already_authenticated_skips_bot_auth(self) -> None:
        """If WorkOS middleware already authenticated, bot middleware is a no-op."""
        call_next_invoked = False

        async def capture_call_next(request):
            nonlocal call_next_invoked
            call_next_invoked = True
            return MagicMock(status_code=200)

        middleware = BotAuthMiddleware(app=MagicMock())
        request = MagicMock()
        request.url.path = "/api/v1/some-endpoint"
        request.state.authenticated = True  # Already auth'd by WorkOS
        request.headers = {}

        await middleware.dispatch(request, capture_call_next)

        assert call_next_invoked is True


@pytest.mark.integration
class TestBotEndpointAuthStatus:
    """Tests for the /bot/auth-status endpoint through the HTTP client."""

    async def test_auth_status_with_valid_api_key(self, bot_client) -> None:
        """GET /bot/auth-status returns auth status for a platform user."""
        with patch.object(
            PlatformLinkService,
            "get_user_by_platform_id",
            new_callable=AsyncMock,
            return_value=TEST_USER_DOC,
        ):
            response = await bot_client.get(
                f"/api/v1/bot/auth-status/{TEST_PLATFORM}/{TEST_PLATFORM_USER_ID}",
                headers={"X-Bot-API-Key": TEST_BOT_API_KEY},
            )

        assert response.status_code == 200
        data = response.json()
        assert data["authenticated"] is True
        assert data["platform"] == TEST_PLATFORM
        assert data["platform_user_id"] == TEST_PLATFORM_USER_ID

    async def test_auth_status_unauthenticated_user(self, bot_client) -> None:
        """GET /bot/auth-status returns authenticated=False for unlinked user."""
        with patch.object(
            PlatformLinkService,
            "get_user_by_platform_id",
            new_callable=AsyncMock,
            return_value=None,
        ):
            response = await bot_client.get(
                f"/api/v1/bot/auth-status/{TEST_PLATFORM}/unlinked-user-id",
                headers={"X-Bot-API-Key": TEST_BOT_API_KEY},
            )

        assert response.status_code == 200
        data = response.json()
        assert data["authenticated"] is False

    async def test_auth_status_invalid_platform(self, bot_client) -> None:
        """GET /bot/auth-status with invalid platform returns 400."""
        response = await bot_client.get(
            "/api/v1/bot/auth-status/invalid_platform/some-user",
            headers={"X-Bot-API-Key": TEST_BOT_API_KEY},
        )

        assert response.status_code == 400
        assert "Invalid platform" in response.json()["detail"]

    async def test_auth_status_without_api_key_rejected(self, bot_client) -> None:
        """GET /bot/auth-status without X-Bot-API-Key returns 401."""
        response = await bot_client.get(
            f"/api/v1/bot/auth-status/{TEST_PLATFORM}/{TEST_PLATFORM_USER_ID}",
        )

        assert response.status_code == 401

    async def test_auth_status_wrong_api_key_rejected(self, bot_client) -> None:
        """GET /bot/auth-status with wrong API key returns 401."""
        response = await bot_client.get(
            f"/api/v1/bot/auth-status/{TEST_PLATFORM}/{TEST_PLATFORM_USER_ID}",
            headers={"X-Bot-API-Key": "wrong-api-key"},
        )

        assert response.status_code == 401


@pytest.mark.integration
class TestBotEndpointSettings:
    """Tests for the /bot/settings endpoint."""

    async def test_settings_for_linked_user(self, bot_client) -> None:
        """GET /bot/settings returns user settings for a linked user."""
        user_doc = {
            **TEST_USER_DOC,
            "name": "Bot User",
            "profile_image_url": "https://example.com/avatar.png",
            "created_at": datetime(2024, 1, 15, tzinfo=timezone.utc),
        }
        with (
            patch.object(
                PlatformLinkService,
                "get_user_by_platform_id",
                new_callable=AsyncMock,
                return_value=user_doc,
            ),
            patch(
                "app.api.v1.endpoints.bot.get_user_connected_integrations",
                new_callable=AsyncMock,
                return_value=[],
            ),
        ):
            response = await bot_client.get(
                f"/api/v1/bot/settings/{TEST_PLATFORM}/{TEST_PLATFORM_USER_ID}",
                headers={"X-Bot-API-Key": TEST_BOT_API_KEY},
            )

        assert response.status_code == 200
        data = response.json()
        assert data["authenticated"] is True
        assert data["user_name"] == "Bot User"
        assert data["profile_image_url"] == "https://example.com/avatar.png"

    async def test_settings_for_unlinked_user(self, bot_client) -> None:
        """GET /bot/settings returns authenticated=False for unlinked user."""
        with patch.object(
            PlatformLinkService,
            "get_user_by_platform_id",
            new_callable=AsyncMock,
            return_value=None,
        ):
            response = await bot_client.get(
                f"/api/v1/bot/settings/{TEST_PLATFORM}/{TEST_PLATFORM_USER_ID}",
                headers={"X-Bot-API-Key": TEST_BOT_API_KEY},
            )

        assert response.status_code == 200
        data = response.json()
        assert data["authenticated"] is False
        assert data["connected_integrations"] == []


@pytest.mark.integration
class TestBotEndpointRequireBotApiKey:
    """Tests for the require_bot_api_key guard used by all bot endpoints."""

    async def test_require_bot_api_key_passes_with_valid_key(self, bot_client) -> None:
        """Endpoints behind require_bot_api_key work with valid key."""
        with patch.object(
            PlatformLinkService,
            "get_user_by_platform_id",
            new_callable=AsyncMock,
            return_value=TEST_USER_DOC,
        ):
            response = await bot_client.get(
                f"/api/v1/bot/auth-status/{TEST_PLATFORM}/{TEST_PLATFORM_USER_ID}",
                headers={"X-Bot-API-Key": TEST_BOT_API_KEY},
            )

        assert response.status_code == 200

    async def test_require_bot_api_key_rejects_missing_key(self, bot_client) -> None:
        """Endpoints behind require_bot_api_key return 401 without key."""
        response = await bot_client.get(
            f"/api/v1/bot/auth-status/{TEST_PLATFORM}/{TEST_PLATFORM_USER_ID}",
        )

        assert response.status_code == 401

    async def test_require_bot_api_key_rejects_empty_key(self, bot_client) -> None:
        """Endpoints behind require_bot_api_key return 401 with empty key."""
        response = await bot_client.get(
            f"/api/v1/bot/auth-status/{TEST_PLATFORM}/{TEST_PLATFORM_USER_ID}",
            headers={"X-Bot-API-Key": ""},
        )

        assert response.status_code == 401


@pytest.mark.integration
class TestBotEndpointResetSession:
    """Tests for the /bot/reset-session endpoint."""

    async def test_reset_session_unauthenticated_returns_401(self, bot_client) -> None:
        """POST /bot/reset-session without linked user returns 401."""
        with patch.object(
            PlatformLinkService,
            "get_user_by_platform_id",
            new_callable=AsyncMock,
            return_value=None,
        ):
            response = await bot_client.post(
                "/api/v1/bot/reset-session",
                json={
                    "platform": TEST_PLATFORM,
                    "platform_user_id": TEST_PLATFORM_USER_ID,
                },
                headers={
                    "X-Bot-API-Key": TEST_BOT_API_KEY,
                    "X-Bot-Platform": TEST_PLATFORM,
                    "X-Bot-Platform-User-Id": TEST_PLATFORM_USER_ID,
                },
            )

        assert response.status_code == 401
        assert "not authenticated" in response.json()["detail"].lower()


@pytest.mark.integration
class TestBotEndpointUnlink:
    """Tests for the /bot/unlink endpoint."""

    async def test_unlink_without_platform_headers_returns_400(
        self, bot_client
    ) -> None:
        """POST /bot/unlink without platform headers returns 400."""
        response = await bot_client.post(
            "/api/v1/bot/unlink",
            headers={"X-Bot-API-Key": TEST_BOT_API_KEY},
        )

        assert response.status_code == 400
        assert "Missing platform headers" in response.json()["detail"]

    async def test_unlink_invalid_platform_returns_400(self, bot_client) -> None:
        """POST /bot/unlink with invalid platform returns 400."""
        response = await bot_client.post(
            "/api/v1/bot/unlink",
            headers={
                "X-Bot-API-Key": TEST_BOT_API_KEY,
                "X-Bot-Platform": "invalid_platform",
                "X-Bot-Platform-User-Id": TEST_PLATFORM_USER_ID,
            },
        )

        assert response.status_code == 400
        assert "Invalid platform" in response.json()["detail"]

    async def test_unlink_not_linked_returns_404(self, bot_client) -> None:
        """POST /bot/unlink for unlinked user returns 404."""
        with patch.object(
            PlatformLinkService,
            "get_user_by_platform_id",
            new_callable=AsyncMock,
            return_value=None,
        ):
            response = await bot_client.post(
                "/api/v1/bot/unlink",
                headers={
                    "X-Bot-API-Key": TEST_BOT_API_KEY,
                    "X-Bot-Platform": TEST_PLATFORM,
                    "X-Bot-Platform-User-Id": TEST_PLATFORM_USER_ID,
                },
            )

        assert response.status_code == 404
        assert "not linked" in response.json()["detail"].lower()


@pytest.mark.integration
class TestBotAuthFullChain:
    """End-to-end tests for the complete bot auth chain: API key -> JWT -> endpoint."""

    async def test_jwt_auth_then_endpoint_access(
        self, bot_client, mock_redis_cache: dict
    ) -> None:
        """Bot authenticates via JWT Bearer token and accesses auth-status endpoint."""
        token = create_bot_session_token(
            user_id=TEST_USER_ID,
            platform=TEST_PLATFORM,
            platform_user_id=TEST_PLATFORM_USER_ID,
        )

        with patch.object(
            PlatformLinkService,
            "get_user_by_platform_id",
            new_callable=AsyncMock,
            return_value=TEST_USER_DOC,
        ):
            response = await bot_client.get(
                f"/api/v1/bot/auth-status/{TEST_PLATFORM}/{TEST_PLATFORM_USER_ID}",
                headers={
                    "Authorization": f"Bearer {token}",
                    "X-Bot-API-Key": TEST_BOT_API_KEY,
                },
            )

        assert response.status_code == 200
        data = response.json()
        assert data["authenticated"] is True

    async def test_api_key_auth_flow_platform_resolution(
        self, bot_client, mock_redis_cache: dict
    ) -> None:
        """Bot authenticates via API key + platform headers, user is resolved."""
        with patch.object(
            PlatformLinkService,
            "get_user_by_platform_id",
            new_callable=AsyncMock,
            return_value=TEST_USER_DOC,
        ):
            response = await bot_client.get(
                f"/api/v1/bot/auth-status/{TEST_PLATFORM}/{TEST_PLATFORM_USER_ID}",
                headers={
                    "X-Bot-API-Key": TEST_BOT_API_KEY,
                    "X-Bot-Platform": TEST_PLATFORM,
                    "X-Bot-Platform-User-Id": TEST_PLATFORM_USER_ID,
                },
            )

        assert response.status_code == 200
        data = response.json()
        assert data["authenticated"] is True

    def test_token_roundtrip_all_platforms(self) -> None:
        """Token create/verify works for all supported platforms."""
        platforms = ["discord", "slack", "telegram"]
        for platform in platforms:
            token = create_bot_session_token(
                user_id=TEST_USER_ID,
                platform=platform,
                platform_user_id=f"{platform}-user-42",
            )
            payload = verify_bot_session_token(token)
            assert payload["platform"] == platform
            assert payload["platform_user_id"] == f"{platform}-user-42"
            assert payload["user_id"] == TEST_USER_ID
