"""Unit tests for bot API endpoints.

Tests the bot endpoints with mocked service layer to verify
routing, status codes, response bodies, and auth checks.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import AsyncClient

BOT_BASE = "/api/v1/bot"


def _make_request(bot_api_key_valid: bool = True, **extra_state: object) -> MagicMock:
    """Build a fake Request whose .state carries bot auth attributes."""
    state = MagicMock()
    state.bot_api_key_valid = bot_api_key_valid
    state.bot_platform = extra_state.get("bot_platform")
    state.bot_platform_user_id = extra_state.get("bot_platform_user_id")
    state.user = extra_state.get("user")
    state.authenticated = extra_state.get("authenticated", False)
    return state


# ---------------------------------------------------------------------------
# POST /bot/create-link-token
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestCreateLinkToken:
    """POST /api/v1/bot/create-link-token"""

    @patch("app.api.v1.endpoints.bot.redis_cache")
    @patch("app.api.v1.endpoints.bot.require_bot_api_key", new_callable=AsyncMock)
    async def test_create_link_token_success(
        self,
        mock_auth: AsyncMock,
        mock_redis: MagicMock,
        client: AsyncClient,
    ):
        mock_redis.client = AsyncMock()
        response = await client.post(
            f"{BOT_BASE}/create-link-token",
            json={
                "platform": "discord",
                "platform_user_id": "user123",
            },
        )
        assert response.status_code == 200
        data = response.json()
        assert "token" in data
        assert "auth_url" in data

    @patch("app.api.v1.endpoints.bot.require_bot_api_key", new_callable=AsyncMock)
    async def test_create_link_token_validation_error(
        self,
        mock_auth: AsyncMock,
        client: AsyncClient,
    ):
        """Missing required fields returns 422."""
        response = await client.post(
            f"{BOT_BASE}/create-link-token",
            json={},
        )
        assert response.status_code == 422

    async def test_create_link_token_no_api_key(self, client: AsyncClient):
        """Without bot_api_key_valid on request.state, require_bot_api_key raises 401."""
        response = await client.post(
            f"{BOT_BASE}/create-link-token",
            json={"platform": "discord", "platform_user_id": "u1"},
        )
        assert response.status_code == 401


# ---------------------------------------------------------------------------
# GET /bot/link-token-info/{token}
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestGetLinkTokenInfo:
    """GET /api/v1/bot/link-token-info/{token}"""

    @patch("app.api.v1.endpoints.bot.redis_cache")
    async def test_link_token_info_success(
        self,
        mock_redis: MagicMock,
        client: AsyncClient,
    ):
        mock_redis.client.hgetall = AsyncMock(
            return_value={
                "platform": "discord",
                "username": "alice",
                "display_name": "Alice",
            }
        )
        response = await client.get(f"{BOT_BASE}/link-token-info/sometoken")
        assert response.status_code == 200
        data = response.json()
        assert data["platform"] == "discord"
        assert data["username"] == "alice"

    @patch("app.api.v1.endpoints.bot.redis_cache")
    async def test_link_token_info_not_found(
        self,
        mock_redis: MagicMock,
        client: AsyncClient,
    ):
        mock_redis.client.hgetall = AsyncMock(return_value={})
        response = await client.get(f"{BOT_BASE}/link-token-info/badtoken")
        assert response.status_code == 404


# ---------------------------------------------------------------------------
# POST /bot/reset-session
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestResetSession:
    """POST /api/v1/bot/reset-session"""

    @patch("app.api.v1.endpoints.bot.BotService")
    @patch(
        "app.api.v1.endpoints.bot.PlatformLinkService.get_user_by_platform_id",
        new_callable=AsyncMock,
    )
    @patch("app.api.v1.endpoints.bot.require_bot_api_key", new_callable=AsyncMock)
    async def test_reset_session_success(
        self,
        mock_auth: AsyncMock,
        mock_get_user: AsyncMock,
        mock_bot_svc: MagicMock,
        client: AsyncClient,
    ):
        mock_get_user.return_value = {"user_id": "uid1", "_id": "uid1"}
        mock_bot_svc.reset_session = AsyncMock(return_value="new-convo-id")
        response = await client.post(
            f"{BOT_BASE}/reset-session",
            json={
                "platform": "discord",
                "platform_user_id": "u1",
                "channel_id": "ch1",
            },
        )
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert data["conversation_id"] == "new-convo-id"

    @patch(
        "app.api.v1.endpoints.bot.PlatformLinkService.get_user_by_platform_id",
        new_callable=AsyncMock,
    )
    @patch("app.api.v1.endpoints.bot.require_bot_api_key", new_callable=AsyncMock)
    async def test_reset_session_user_not_found(
        self,
        mock_auth: AsyncMock,
        mock_get_user: AsyncMock,
        client: AsyncClient,
    ):
        mock_get_user.return_value = None
        response = await client.post(
            f"{BOT_BASE}/reset-session",
            json={
                "platform": "discord",
                "platform_user_id": "u1",
                "channel_id": "ch1",
            },
        )
        assert response.status_code == 401

    async def test_reset_session_no_api_key(self, client: AsyncClient):
        response = await client.post(
            f"{BOT_BASE}/reset-session",
            json={
                "platform": "discord",
                "platform_user_id": "u1",
                "channel_id": "ch1",
            },
        )
        assert response.status_code == 401

    @patch("app.api.v1.endpoints.bot.require_bot_api_key", new_callable=AsyncMock)
    async def test_reset_session_validation_error(
        self, mock_auth: AsyncMock, client: AsyncClient
    ):
        response = await client.post(f"{BOT_BASE}/reset-session", json={})
        assert response.status_code == 422


# ---------------------------------------------------------------------------
# GET /bot/auth-status/{platform}/{platform_user_id}
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestCheckAuthStatus:
    """GET /api/v1/bot/auth-status/{platform}/{platform_user_id}"""

    @patch(
        "app.api.v1.endpoints.bot.PlatformLinkService.get_user_by_platform_id",
        new_callable=AsyncMock,
    )
    @patch("app.api.v1.endpoints.bot.require_bot_api_key", new_callable=AsyncMock)
    async def test_auth_status_authenticated(
        self,
        mock_auth: AsyncMock,
        mock_get_user: AsyncMock,
        client: AsyncClient,
    ):
        mock_get_user.return_value = {"user_id": "uid1"}
        response = await client.get(f"{BOT_BASE}/auth-status/discord/u1")
        assert response.status_code == 200
        data = response.json()
        assert data["authenticated"] is True
        assert data["platform"] == "discord"

    @patch(
        "app.api.v1.endpoints.bot.PlatformLinkService.get_user_by_platform_id",
        new_callable=AsyncMock,
    )
    @patch("app.api.v1.endpoints.bot.require_bot_api_key", new_callable=AsyncMock)
    async def test_auth_status_not_authenticated(
        self,
        mock_auth: AsyncMock,
        mock_get_user: AsyncMock,
        client: AsyncClient,
    ):
        mock_get_user.return_value = None
        response = await client.get(f"{BOT_BASE}/auth-status/discord/u1")
        assert response.status_code == 200
        data = response.json()
        assert data["authenticated"] is False

    @patch("app.api.v1.endpoints.bot.require_bot_api_key", new_callable=AsyncMock)
    async def test_auth_status_invalid_platform(
        self, mock_auth: AsyncMock, client: AsyncClient
    ):
        response = await client.get(f"{BOT_BASE}/auth-status/invalid_plat/u1")
        assert response.status_code == 400

    async def test_auth_status_no_api_key(self, client: AsyncClient):
        response = await client.get(f"{BOT_BASE}/auth-status/discord/u1")
        assert response.status_code == 401


# ---------------------------------------------------------------------------
# GET /bot/settings/{platform}/{platform_user_id}
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestGetSettings:
    """GET /api/v1/bot/settings/{platform}/{platform_user_id}"""

    @patch(
        "app.api.v1.endpoints.bot.get_user_connected_integrations",
        new_callable=AsyncMock,
    )
    @patch(
        "app.api.v1.endpoints.bot.PlatformLinkService.get_user_by_platform_id",
        new_callable=AsyncMock,
    )
    @patch("app.api.v1.endpoints.bot.require_bot_api_key", new_callable=AsyncMock)
    async def test_settings_authenticated_user(
        self,
        mock_auth: AsyncMock,
        mock_get_user: AsyncMock,
        mock_integrations: AsyncMock,
        client: AsyncClient,
    ):
        mock_get_user.return_value = {
            "user_id": "uid1",
            "_id": "uid1",
            "name": "Alice",
            "profile_image_url": "https://img.example.com/a.png",
            "created_at": None,
        }
        mock_integrations.return_value = []
        response = await client.get(f"{BOT_BASE}/settings/discord/u1")
        assert response.status_code == 200
        data = response.json()
        assert data["authenticated"] is True
        assert data["user_name"] == "Alice"

    @patch(
        "app.api.v1.endpoints.bot.PlatformLinkService.get_user_by_platform_id",
        new_callable=AsyncMock,
    )
    @patch("app.api.v1.endpoints.bot.require_bot_api_key", new_callable=AsyncMock)
    async def test_settings_unauthenticated_user(
        self,
        mock_auth: AsyncMock,
        mock_get_user: AsyncMock,
        client: AsyncClient,
    ):
        mock_get_user.return_value = None
        response = await client.get(f"{BOT_BASE}/settings/discord/u1")
        assert response.status_code == 200
        data = response.json()
        assert data["authenticated"] is False

    @patch("app.api.v1.endpoints.bot.require_bot_api_key", new_callable=AsyncMock)
    async def test_settings_invalid_platform(
        self, mock_auth: AsyncMock, client: AsyncClient
    ):
        response = await client.get(f"{BOT_BASE}/settings/badplatform/u1")
        assert response.status_code == 400


# ---------------------------------------------------------------------------
# POST /bot/unlink
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestUnlinkAccount:
    """POST /api/v1/bot/unlink"""

    @patch("app.api.v1.endpoints.bot.redis_cache")
    @patch(
        "app.api.v1.endpoints.bot.PlatformLinkService.unlink_account",
        new_callable=AsyncMock,
    )
    @patch(
        "app.api.v1.endpoints.bot.PlatformLinkService.get_user_by_platform_id",
        new_callable=AsyncMock,
    )
    @patch("app.api.v1.endpoints.bot.require_bot_api_key", new_callable=AsyncMock)
    async def test_unlink_success(
        self,
        mock_auth: AsyncMock,
        mock_get_user: AsyncMock,
        mock_unlink: AsyncMock,
        mock_redis: MagicMock,
        client: AsyncClient,
    ):
        mock_get_user.return_value = {"_id": "uid1", "user_id": "uid1"}
        mock_redis.client = AsyncMock()
        response = await client.post(
            f"{BOT_BASE}/unlink",
            headers={
                "X-Bot-Platform": "discord",
                "X-Bot-Platform-User-Id": "u1",
            },
        )
        assert response.status_code == 200
        assert response.json()["success"] is True

    @patch("app.api.v1.endpoints.bot.require_bot_api_key", new_callable=AsyncMock)
    async def test_unlink_missing_headers(
        self, mock_auth: AsyncMock, client: AsyncClient
    ):
        response = await client.post(f"{BOT_BASE}/unlink")
        assert response.status_code == 400

    @patch("app.api.v1.endpoints.bot.require_bot_api_key", new_callable=AsyncMock)
    async def test_unlink_invalid_platform(
        self, mock_auth: AsyncMock, client: AsyncClient
    ):
        response = await client.post(
            f"{BOT_BASE}/unlink",
            headers={
                "X-Bot-Platform": "badplatform",
                "X-Bot-Platform-User-Id": "u1",
            },
        )
        assert response.status_code == 400

    @patch(
        "app.api.v1.endpoints.bot.PlatformLinkService.get_user_by_platform_id",
        new_callable=AsyncMock,
    )
    @patch("app.api.v1.endpoints.bot.require_bot_api_key", new_callable=AsyncMock)
    async def test_unlink_account_not_linked(
        self,
        mock_auth: AsyncMock,
        mock_get_user: AsyncMock,
        client: AsyncClient,
    ):
        mock_get_user.return_value = None
        response = await client.post(
            f"{BOT_BASE}/unlink",
            headers={
                "X-Bot-Platform": "discord",
                "X-Bot-Platform-User-Id": "u1",
            },
        )
        assert response.status_code == 404

    async def test_unlink_no_api_key(self, client: AsyncClient):
        response = await client.post(
            f"{BOT_BASE}/unlink",
            headers={
                "X-Bot-Platform": "discord",
                "X-Bot-Platform-User-Id": "u1",
            },
        )
        assert response.status_code == 401


# ---------------------------------------------------------------------------
# POST /bot/chat-stream
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestBotChatStream:
    """POST /api/v1/bot/chat-stream"""

    async def test_chat_stream_no_api_key(self, client: AsyncClient):
        response = await client.post(
            f"{BOT_BASE}/chat-stream",
            json={
                "message": "hello",
                "platform": "discord",
                "platform_user_id": "u1",
            },
        )
        assert response.status_code == 401

    @patch("app.api.v1.endpoints.bot.require_bot_api_key", new_callable=AsyncMock)
    async def test_chat_stream_validation_error(
        self, mock_auth: AsyncMock, client: AsyncClient
    ):
        response = await client.post(f"{BOT_BASE}/chat-stream", json={})
        assert response.status_code == 422
