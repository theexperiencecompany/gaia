"""Unit tests for bot API endpoints.

Tests the bot endpoints with mocked service layer to verify
routing, status codes, response bodies, and auth checks.
"""

import asyncio
from datetime import UTC, datetime
import json
from types import CoroutineType, SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, call, patch

from fastapi import HTTPException
from httpx import AsyncClient
import pytest

from app.api.v1.endpoints.bot import (
    _bot_approval_payload,
    _bot_rate_limit_notice,
    bot_chat_stream,
    create_link_token,
    require_bot_api_key,
    reset_session,
    transcribe_bot_audio,
)
from app.config.settings import settings
from app.constants.cache import PLATFORM_LINK_TOKEN_PREFIX, PLATFORM_LINK_TOKEN_TTL
from app.models.bot_models import BotChatRequest, CreateLinkTokenRequest, ResetSessionRequest
from app.services.audio_transcription_service import MAX_AUDIO_BYTES

BOT_BASE = "/api/v1/bot"

BOT_USER = {"user_id": "uid1", "_id": "uid1", "name": "Alice"}


def _make_request(**attrs: object) -> SimpleNamespace:
    """Build a fake Request whose .state carries bot auth attributes."""
    return SimpleNamespace(state=SimpleNamespace(**attrs))


def _sse_frames(*frames: str):
    """Build an async generator object yielding the given SSE frames."""

    async def _gen(*args: object, **kwargs: object):
        for frame in frames:
            yield frame

    return _gen()


# ---------------------------------------------------------------------------
# require_bot_api_key
# ---------------------------------------------------------------------------


class TestRequireBotApiKey:
    """require_bot_api_key: gate every bot endpoint on middleware-verified keys."""

    async def test_accepts_valid_state(self):
        request = _make_request(bot_api_key_valid=True)
        assert await require_bot_api_key(request) is None

    async def test_rejects_invalid_state(self):
        request = _make_request(bot_api_key_valid=False)
        with pytest.raises(HTTPException) as exc_info:
            await require_bot_api_key(request)
        assert exc_info.value.status_code == 401
        assert exc_info.value.detail == "Invalid or missing bot API key"

    async def test_rejects_missing_attribute(self):
        request = SimpleNamespace(state=SimpleNamespace())
        with pytest.raises(HTTPException) as exc_info:
            await require_bot_api_key(request)
        assert exc_info.value.status_code == 401
        assert exc_info.value.detail == "Invalid or missing bot API key"

    async def test_reads_key_from_state_not_request(self):
        request = SimpleNamespace(bot_api_key_valid=True, state=SimpleNamespace())
        with pytest.raises(HTTPException) as exc_info:
            await require_bot_api_key(request)
        assert exc_info.value.status_code == 401


# ---------------------------------------------------------------------------
# _bot_rate_limit_notice / _bot_approval_payload
# ---------------------------------------------------------------------------


class TestBotCardTranslators:
    """Stream chunk translators: rate-limit cards and HIL approval prompts."""

    def test_rate_limit_notice_ignores_non_card(self):
        assert _bot_rate_limit_notice({"response": "hello"}) is None
        assert _bot_rate_limit_notice({"tool_data": "not a dict"}) is None
        assert (
            _bot_rate_limit_notice({"tool_data": {"tool_name": "some_other_tool", "data": {}}})
            is None
        )

    def test_rate_limit_notice_free_plan(self):
        chunk = {
            "tool_data": {
                "tool_name": "rate_limit_data",
                "data": {"feature": "audio_transcription", "current_plan": "free"},
            }
        }
        notice = _bot_rate_limit_notice(chunk)
        assert notice is not None
        assert f"[Upgrade to Pro]({settings.FRONTEND_URL}/pricing) for higher limits." in notice
        assert "audio transcription limit" in notice

    def test_rate_limit_notice_pro_plan_has_no_upgrade_link(self):
        chunk = {
            "tool_data": {
                "tool_name": "rate_limit_data",
                "data": {"feature": "chat_messages", "current_plan": "pro"},
            }
        }
        notice = _bot_rate_limit_notice(chunk)
        assert notice is not None
        assert "Upgrade to Pro" not in notice
        assert "chat messages limit" in notice

    def test_rate_limit_notice_missing_data_uses_default_feature(self):
        chunk = {"tool_data": {"tool_name": "rate_limit_data", "data": None}}
        notice = _bot_rate_limit_notice(chunk)
        assert notice is not None
        assert "this feature limit" in notice

    def test_approval_payload_ignores_non_card(self):
        assert _bot_approval_payload({"response": "hello"}) is None
        assert _bot_approval_payload({"tool_data": {"tool_name": "other"}}) is None
        assert (
            _bot_approval_payload(
                {"tool_data": {"tool_name": "approval_request", "data": "not-dict"}}
            )
            is None
        )

    def test_approval_payload_extracts_data(self):
        payload = {"approval_id": "a1", "request": "Approve the calendar invite?"}
        chunk = {"tool_data": {"tool_name": "approval_request", "data": payload}}
        assert _bot_approval_payload(chunk) == payload


# ---------------------------------------------------------------------------
# POST /bot/create-link-token
# ---------------------------------------------------------------------------


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
                "username": "alice",
                "display_name": "Alice",
            },
        )
        assert response.status_code == 200
        data = response.json()
        assert data["token"]
        assert len(data["token"]) == 43
        assert data["auth_url"] == (
            f"{settings.FRONTEND_URL}/auth/link-platform?platform=discord&token={data['token']}"
        )
        token_key = f"{PLATFORM_LINK_TOKEN_PREFIX}:{data['token']}"
        mock_redis.client.hset.assert_awaited_once_with(
            token_key,
            mapping={
                "platform": "discord",
                "platform_user_id": "user123",
                "username": "alice",
                "display_name": "Alice",
            },
        )
        mock_redis.client.expire.assert_awaited_once_with(token_key, PLATFORM_LINK_TOKEN_TTL)

    @patch("app.api.v1.endpoints.bot.redis_cache")
    @patch("app.api.v1.endpoints.bot.require_bot_api_key", new_callable=AsyncMock)
    async def test_create_link_token_omits_optional_profile_fields(
        self,
        mock_auth: AsyncMock,
        mock_redis: MagicMock,
        client: AsyncClient,
    ):
        mock_redis.client = AsyncMock()
        response = await client.post(
            f"{BOT_BASE}/create-link-token",
            json={"platform": "discord", "platform_user_id": "user123"},
        )
        assert response.status_code == 200
        token_key = f"{PLATFORM_LINK_TOKEN_PREFIX}:{response.json()['token']}"
        mock_redis.client.hset.assert_awaited_once_with(
            token_key,
            mapping={"platform": "discord", "platform_user_id": "user123"},
        )

    @patch("app.api.v1.endpoints.bot.redis_cache")
    async def test_create_link_token_platform_header_mismatch(
        self, mock_redis: MagicMock, client: AsyncClient
    ):
        mock_redis.client = AsyncMock()
        request = _make_request(
            bot_api_key_valid=True,
            bot_platform="telegram",
            bot_platform_user_id="u1",
        )
        body = CreateLinkTokenRequest(platform="discord", platform_user_id="u1")
        with pytest.raises(HTTPException) as exc_info:
            await create_link_token(request, body)
        assert exc_info.value.status_code == 403
        assert exc_info.value.detail == "Platform in body does not match X-Bot-Platform header"
        mock_redis.client.hset.assert_not_awaited()

    @patch("app.api.v1.endpoints.bot.redis_cache")
    async def test_create_link_token_platform_user_id_header_mismatch(
        self, mock_redis: MagicMock, client: AsyncClient
    ):
        mock_redis.client = AsyncMock()
        request = _make_request(
            bot_api_key_valid=True,
            bot_platform="discord",
            bot_platform_user_id="other-user",
        )
        body = CreateLinkTokenRequest(platform="discord", platform_user_id="u1")
        with pytest.raises(HTTPException) as exc_info:
            await create_link_token(request, body)
        assert exc_info.value.status_code == 403
        assert (
            exc_info.value.detail
            == "platform_user_id in body does not match X-Bot-Platform-User-Id header"
        )
        mock_redis.client.hset.assert_not_awaited()

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
        mock_redis.client.hgetall.assert_awaited_once_with(
            f"{PLATFORM_LINK_TOKEN_PREFIX}:sometoken"
        )
        assert response.json() == {
            "platform": "discord",
            "username": "alice",
            "display_name": "Alice",
        }

    @patch("app.api.v1.endpoints.bot.redis_cache")
    async def test_link_token_info_nullable_fields(
        self, mock_redis: MagicMock, client: AsyncClient
    ):
        mock_redis.client.hgetall = AsyncMock(return_value={"platform": "telegram"})
        response = await client.get(f"{BOT_BASE}/link-token-info/othertoken")
        assert response.status_code == 200
        assert response.json() == {
            "platform": "telegram",
            "username": None,
            "display_name": None,
        }

    @patch("app.api.v1.endpoints.bot.redis_cache")
    async def test_link_token_info_not_found(
        self,
        mock_redis: MagicMock,
        client: AsyncClient,
    ):
        mock_redis.client.hgetall = AsyncMock(return_value={})
        response = await client.get(f"{BOT_BASE}/link-token-info/badtoken")
        assert response.status_code == 404
        assert response.json()["detail"] == "Token not found or expired"

    @patch("app.api.v1.endpoints.bot.redis_cache")
    async def test_link_token_info_does_not_consume_token(
        self, mock_redis: MagicMock, client: AsyncClient
    ):
        mock_redis.client = AsyncMock()
        mock_redis.client.hgetall = AsyncMock(return_value={"platform": "discord"})
        response = await client.get(f"{BOT_BASE}/link-token-info/sometoken")
        assert response.status_code == 200
        mock_redis.client.expire.assert_not_awaited()
        mock_redis.client.delete.assert_not_awaited()


# ---------------------------------------------------------------------------
# POST /bot/reset-session
# ---------------------------------------------------------------------------


class TestResetSession:
    """POST /api/v1/bot/reset-session"""

    @patch("app.api.v1.endpoints.bot.BotService.reset_session", new_callable=AsyncMock)
    @patch(
        "app.api.v1.endpoints.bot.PlatformLinkService.get_user_by_platform_id",
        new_callable=AsyncMock,
    )
    @patch("app.api.v1.endpoints.bot.require_bot_api_key", new_callable=AsyncMock)
    async def test_reset_session_success(
        self,
        mock_auth: AsyncMock,
        mock_get_user: AsyncMock,
        mock_reset_session: AsyncMock,
        client: AsyncClient,
    ):
        mock_get_user.return_value = {"user_id": "uid1", "_id": "uid1"}
        mock_reset_session.return_value = "new-convo-id"
        response = await client.post(
            f"{BOT_BASE}/reset-session",
            json={
                "platform": "discord",
                "platform_user_id": "u1",
                "channel_id": "ch1",
            },
        )
        assert response.status_code == 200
        assert response.json() == {"success": True, "conversation_id": "new-convo-id"}
        mock_get_user.assert_awaited_once_with("discord", "u1")
        mock_reset_session.assert_awaited_once_with(
            "discord", "u1", "ch1", {"user_id": "uid1", "_id": "uid1"}
        )

    @patch("app.api.v1.endpoints.bot.BotService.reset_session", new_callable=AsyncMock)
    @patch(
        "app.api.v1.endpoints.bot.PlatformLinkService.get_user_by_platform_id",
        new_callable=AsyncMock,
    )
    @patch("app.api.v1.endpoints.bot.require_bot_api_key", new_callable=AsyncMock)
    async def test_reset_session_normalizes_legacy_user_dict(
        self,
        mock_auth: AsyncMock,
        mock_get_user: AsyncMock,
        mock_reset_session: AsyncMock,
        client: AsyncClient,
    ):
        mock_get_user.return_value = {"_id": "legacy-id"}
        mock_reset_session.return_value = "new-convo-id"
        response = await client.post(
            f"{BOT_BASE}/reset-session",
            json={"platform": "discord", "platform_user_id": "u1"},
        )
        assert response.status_code == 200
        mock_reset_session.assert_awaited_once_with(
            "discord", "u1", None, {"_id": "legacy-id", "user_id": "legacy-id"}
        )

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

    @patch("app.api.v1.endpoints.bot.BotService.reset_session", new_callable=AsyncMock)
    @patch(
        "app.api.v1.endpoints.bot.PlatformLinkService.get_user_by_platform_id",
        new_callable=AsyncMock,
    )
    async def test_reset_session_uses_state_user_when_authenticated(
        self,
        mock_get_user: AsyncMock,
        mock_reset_session: AsyncMock,
    ):
        mock_reset_session.return_value = "new-convo-id"
        request = _make_request(
            bot_api_key_valid=True,
            user={"user_id": "state-uid", "_id": "state-uid"},
            authenticated=True,
        )
        result = await reset_session(
            request,
            ResetSessionRequest(platform="discord", platform_user_id="u1", channel_id="ch1"),
        )
        assert result.success is True
        assert result.conversation_id == "new-convo-id"
        mock_get_user.assert_not_awaited()
        mock_reset_session.assert_awaited_once_with(
            "discord", "u1", "ch1", {"user_id": "state-uid", "_id": "state-uid"}
        )

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
    async def test_reset_session_validation_error(self, mock_auth: AsyncMock, client: AsyncClient):
        response = await client.post(f"{BOT_BASE}/reset-session", json={})
        assert response.status_code == 422


# ---------------------------------------------------------------------------
# GET /bot/auth-status/{platform}/{platform_user_id}
# ---------------------------------------------------------------------------


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
        mock_get_user.assert_awaited_once_with("discord", "u1")
        assert response.json() == {
            "authenticated": True,
            "platform": "discord",
            "platform_user_id": "u1",
        }

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
        assert response.json()["authenticated"] is False

    @patch(
        "app.api.v1.endpoints.bot.PlatformLinkService.get_user_by_platform_id",
        new_callable=AsyncMock,
    )
    @patch("app.api.v1.endpoints.bot.require_bot_api_key", new_callable=AsyncMock)
    async def test_auth_status_invalid_platform(
        self,
        mock_auth: AsyncMock,
        mock_get_user: AsyncMock,
        client: AsyncClient,
    ):
        response = await client.get(f"{BOT_BASE}/auth-status/invalid_plat/u1")
        assert response.status_code == 400
        assert response.json()["detail"] == "Invalid platform"
        mock_get_user.assert_not_awaited()

    async def test_auth_status_no_api_key(self, client: AsyncClient):
        response = await client.get(f"{BOT_BASE}/auth-status/discord/u1")
        assert response.status_code == 401


# ---------------------------------------------------------------------------
# GET /bot/linked-users/{platform}
# ---------------------------------------------------------------------------


class TestListLinkedUsers:
    """GET /api/v1/bot/linked-users/{platform}"""

    @patch(
        "app.api.v1.endpoints.bot.PlatformLinkService.list_platform_user_ids",
        new_callable=AsyncMock,
    )
    @patch("app.api.v1.endpoints.bot.require_bot_api_key", new_callable=AsyncMock)
    async def test_list_linked_users_success(
        self,
        mock_auth: AsyncMock,
        mock_list_ids: AsyncMock,
        client: AsyncClient,
    ):
        mock_list_ids.return_value = ["u1", "u2"]
        response = await client.get(f"{BOT_BASE}/linked-users/discord")
        assert response.status_code == 200
        mock_list_ids.assert_awaited_once_with("discord")
        assert response.json() == {"platform_user_ids": ["u1", "u2"]}

    @patch("app.api.v1.endpoints.bot.require_bot_api_key", new_callable=AsyncMock)
    async def test_list_linked_users_invalid_platform(
        self, mock_auth: AsyncMock, client: AsyncClient
    ):
        response = await client.get(f"{BOT_BASE}/linked-users/invalid_plat")
        assert response.status_code == 400
        assert response.json()["detail"] == "Invalid platform"

    async def test_list_linked_users_no_api_key(self, client: AsyncClient):
        response = await client.get(f"{BOT_BASE}/linked-users/discord")
        assert response.status_code == 401


# ---------------------------------------------------------------------------
# GET /bot/settings/{platform}/{platform_user_id}
# ---------------------------------------------------------------------------


class TestGetSettings:
    """GET /api/v1/bot/settings/{platform}/{platform_user_id}"""

    @patch(
        "app.api.v1.endpoints.bot.get_user_integration_records",
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
            "created_at": datetime(2024, 3, 1, 12, 30, tzinfo=UTC),
        }
        mock_integrations.return_value = []
        response = await client.get(f"{BOT_BASE}/settings/discord/u1")
        assert response.status_code == 200
        assert response.json() == {
            "authenticated": True,
            "user_name": "Alice",
            "account_created_at": "2024-03-01T12:30:00+00:00",
            "profile_image_url": "https://img.example.com/a.png",
            "connected_integrations": [],
        }
        mock_get_user.assert_awaited_once_with("discord", "u1")
        mock_integrations.assert_awaited_once_with("uid1")

    @patch(
        "app.api.v1.endpoints.bot.get_user_integration_records",
        new_callable=AsyncMock,
    )
    @patch(
        "app.api.v1.endpoints.bot.PlatformLinkService.get_user_by_platform_id",
        new_callable=AsyncMock,
    )
    @patch("app.api.v1.endpoints.bot.require_bot_api_key", new_callable=AsyncMock)
    async def test_settings_falls_back_to_username_and_avatar(
        self,
        mock_auth: AsyncMock,
        mock_get_user: AsyncMock,
        mock_integrations: AsyncMock,
        client: AsyncClient,
    ):
        mock_get_user.return_value = {
            "user_id": "uid1",
            "username": "alice_dev",
            "avatar_url": "https://img.example.com/avatar.png",
        }
        mock_integrations.return_value = []
        response = await client.get(f"{BOT_BASE}/settings/discord/u1")
        assert response.status_code == 200
        data = response.json()
        assert data["user_name"] == "alice_dev"
        assert data["profile_image_url"] == "https://img.example.com/avatar.png"
        assert data["account_created_at"] is None

    @patch(
        "app.api.v1.endpoints.bot.get_user_integration_records",
        new_callable=AsyncMock,
    )
    @patch(
        "app.api.v1.endpoints.bot.PlatformLinkService.get_user_by_platform_id",
        new_callable=AsyncMock,
    )
    @patch("app.api.v1.endpoints.bot.require_bot_api_key", new_callable=AsyncMock)
    async def test_settings_uses_id_for_legacy_user_dict(
        self,
        mock_auth: AsyncMock,
        mock_get_user: AsyncMock,
        mock_integrations: AsyncMock,
        client: AsyncClient,
    ):
        mock_get_user.return_value = {"_id": "legacy-id"}
        mock_integrations.return_value = []
        response = await client.get(f"{BOT_BASE}/settings/discord/u1")
        assert response.status_code == 200
        assert response.json()["authenticated"] is True
        mock_integrations.assert_awaited_once_with("legacy-id")

    @patch(
        "app.api.v1.endpoints.bot.get_integration_details",
        new_callable=AsyncMock,
    )
    @patch(
        "app.api.v1.endpoints.bot.get_user_integration_records",
        new_callable=AsyncMock,
    )
    @patch(
        "app.api.v1.endpoints.bot.PlatformLinkService.get_user_by_platform_id",
        new_callable=AsyncMock,
    )
    @patch("app.api.v1.endpoints.bot.require_bot_api_key", new_callable=AsyncMock)
    async def test_settings_renders_connected_integrations(
        self,
        mock_auth: AsyncMock,
        mock_get_user: AsyncMock,
        mock_integrations: AsyncMock,
        mock_details: AsyncMock,
        client: AsyncClient,
    ):
        mock_get_user.return_value = {"user_id": "uid1", "_id": "uid1", "name": "Alice"}
        mock_integrations.return_value = [
            {"integration_id": "slack", "status": "connected"},
            {"integration_id": "missing", "status": "created"},
            {"status": "connected", "no_id": True},
        ]
        details = MagicMock()
        details.name = "Slack"
        details.icon_url = "https://img.example.com/slack.png"
        mock_details.side_effect = [details, None]
        response = await client.get(f"{BOT_BASE}/settings/discord/u1")
        assert response.status_code == 200
        assert response.json()["connected_integrations"] == [
            {
                "name": "Slack",
                "logo_url": "https://img.example.com/slack.png",
                "status": "connected",
            }
        ]
        assert mock_details.await_args_list == [call("slack"), call("missing")]

    @patch(
        "app.api.v1.endpoints.bot.get_user_integration_records",
        new_callable=AsyncMock,
        side_effect=RuntimeError("integration lookup failed"),
    )
    @patch(
        "app.api.v1.endpoints.bot.PlatformLinkService.get_user_by_platform_id",
        new_callable=AsyncMock,
    )
    @patch("app.api.v1.endpoints.bot.require_bot_api_key", new_callable=AsyncMock)
    async def test_settings_integration_lookup_error_returns_empty_list(
        self,
        mock_auth: AsyncMock,
        mock_get_user: AsyncMock,
        mock_integrations: AsyncMock,
        client: AsyncClient,
    ):
        mock_get_user.return_value = {"user_id": "uid1", "_id": "uid1", "name": "Alice"}
        response = await client.get(f"{BOT_BASE}/settings/discord/u1")
        assert response.status_code == 200
        assert response.json()["connected_integrations"] == []
        assert response.json()["authenticated"] is True

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
        assert response.json() == {
            "authenticated": False,
            "user_name": None,
            "account_created_at": None,
            "profile_image_url": None,
            "connected_integrations": [],
        }

    @patch("app.api.v1.endpoints.bot.require_bot_api_key", new_callable=AsyncMock)
    async def test_settings_invalid_platform(self, mock_auth: AsyncMock, client: AsyncClient):
        response = await client.get(f"{BOT_BASE}/settings/badplatform/u1")
        assert response.status_code == 400

    async def test_settings_no_api_key(self, client: AsyncClient):
        response = await client.get(f"{BOT_BASE}/settings/discord/u1")
        assert response.status_code == 401


# ---------------------------------------------------------------------------
# POST /bot/unlink
# ---------------------------------------------------------------------------


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
        assert response.json() == {"success": True}
        mock_get_user.assert_awaited_once_with("discord", "u1")
        mock_unlink.assert_awaited_once_with("uid1", "discord")
        mock_redis.client.delete.assert_awaited_once_with("bot_user:discord:u1")

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
    async def test_unlink_legacy_user_dict_uses_id(
        self,
        mock_auth: AsyncMock,
        mock_get_user: AsyncMock,
        mock_unlink: AsyncMock,
        mock_redis: MagicMock,
        client: AsyncClient,
    ):
        mock_get_user.return_value = {"_id": "legacy-id"}
        mock_redis.client = AsyncMock()
        response = await client.post(
            f"{BOT_BASE}/unlink",
            headers={
                "X-Bot-Platform": "telegram",
                "X-Bot-Platform-User-Id": "tg1",
            },
        )
        assert response.status_code == 200
        mock_unlink.assert_awaited_once_with("legacy-id", "telegram")
        mock_redis.client.delete.assert_awaited_once_with("bot_user:telegram:tg1")

    @patch("app.api.v1.endpoints.bot.require_bot_api_key", new_callable=AsyncMock)
    async def test_unlink_missing_headers(self, mock_auth: AsyncMock, client: AsyncClient):
        response = await client.post(f"{BOT_BASE}/unlink")
        assert response.status_code == 400
        assert response.json()["detail"] == "Missing platform headers"

    @patch("app.api.v1.endpoints.bot.require_bot_api_key", new_callable=AsyncMock)
    async def test_unlink_missing_platform_header(self, mock_auth: AsyncMock, client: AsyncClient):
        response = await client.post(
            f"{BOT_BASE}/unlink",
            headers={"X-Bot-Platform-User-Id": "u1"},
        )
        assert response.status_code == 400
        assert response.json()["detail"] == "Missing platform headers"

    @patch("app.api.v1.endpoints.bot.require_bot_api_key", new_callable=AsyncMock)
    async def test_unlink_missing_platform_user_id_header(
        self, mock_auth: AsyncMock, client: AsyncClient
    ):
        response = await client.post(
            f"{BOT_BASE}/unlink",
            headers={"X-Bot-Platform": "discord"},
        )
        assert response.status_code == 400
        assert response.json()["detail"] == "Missing platform headers"

    @patch("app.api.v1.endpoints.bot.require_bot_api_key", new_callable=AsyncMock)
    async def test_unlink_invalid_platform(self, mock_auth: AsyncMock, client: AsyncClient):
        response = await client.post(
            f"{BOT_BASE}/unlink",
            headers={
                "X-Bot-Platform": "badplatform",
                "X-Bot-Platform-User-Id": "u1",
            },
        )
        assert response.status_code == 400
        assert response.json()["detail"] == "Invalid platform"

    @patch(
        "app.api.v1.endpoints.bot.PlatformLinkService.unlink_account",
        new_callable=AsyncMock,
    )
    @patch(
        "app.api.v1.endpoints.bot.PlatformLinkService.get_user_by_platform_id",
        new_callable=AsyncMock,
    )
    @patch("app.api.v1.endpoints.bot.require_bot_api_key", new_callable=AsyncMock)
    async def test_unlink_account_not_linked(
        self,
        mock_auth: AsyncMock,
        mock_get_user: AsyncMock,
        mock_unlink: AsyncMock,
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
        assert response.json()["detail"] == "Account not linked"
        mock_unlink.assert_not_awaited()

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


class TestBotChatStream:
    """POST /api/v1/bot/chat-stream"""

    @pytest.fixture
    def chat_mocks(self):
        """Patch every service seam the chat-stream handler touches.

        subscribe_stream is a plain MagicMock whose return_value each test swaps
        for the async-generator object of its choice.
        """
        with (
            patch("app.api.v1.endpoints.bot.require_bot_api_key", new_callable=AsyncMock) as auth,
            patch(
                "app.api.v1.endpoints.bot.PlatformLinkService.get_user_by_platform_id",
                new_callable=AsyncMock,
            ) as get_user,
            patch(
                "app.api.v1.endpoints.bot.BotService.enforce_rate_limit",
                new_callable=AsyncMock,
            ) as enforce_rate_limit,
            patch(
                "app.api.v1.endpoints.bot.BotService.get_or_create_session",
                new_callable=AsyncMock,
                return_value="conv-1",
            ) as get_or_create_session,
            patch(
                "app.api.v1.endpoints.bot.BotService.load_conversation_history",
                new_callable=AsyncMock,
                return_value=[],
            ) as load_history,
            patch(
                "app.api.v1.endpoints.bot.create_bot_session_token",
                return_value="sess-token-1",
            ) as session_token,
            patch(
                "app.api.v1.endpoints.bot.stream_manager.start_stream",
                new_callable=AsyncMock,
            ) as start_stream,
            patch(
                "app.api.v1.endpoints.bot.spawn_background_task",
            ) as spawn,
            patch(
                "app.api.v1.endpoints.bot.run_chat_stream_background",
                new_callable=AsyncMock,
            ) as background,
            # Plain MagicMock, not AsyncMock: the endpoint iterates
            # `async for chunk in stream_manager.subscribe_stream(...)`, so the
            # call must return an async iterable directly (an AsyncMock would
            # return a coroutine, which is not async-iterable).
            patch(
                "app.api.v1.endpoints.bot.stream_manager.subscribe_stream",
                new_callable=MagicMock,
            ) as subscribe,
        ):
            get_user.return_value = BOT_USER
            spawn.side_effect = lambda coro, **kwargs: coro.close() or None
            subscribe.return_value = _sse_frames()
            yield SimpleNamespace(
                auth=auth,
                get_user=get_user,
                enforce_rate_limit=enforce_rate_limit,
                get_or_create_session=get_or_create_session,
                load_history=load_history,
                session_token=session_token,
                start_stream=start_stream,
                spawn=spawn,
                background=background,
                subscribe=subscribe,
            )

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
    async def test_chat_stream_validation_error(self, mock_auth: AsyncMock, client: AsyncClient):
        response = await client.post(f"{BOT_BASE}/chat-stream", json={})
        assert response.status_code == 422

    async def test_chat_stream_unlinked_user_emits_not_authenticated(
        self, client: AsyncClient, chat_mocks
    ):
        chat_mocks.get_user.return_value = None
        response = await client.post(
            f"{BOT_BASE}/chat-stream",
            json={"message": "hello", "platform": "discord", "platform_user_id": "u1"},
        )
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/event-stream")
        assert response.text == 'data: {"error": "not_authenticated"}\n\n'
        chat_mocks.get_or_create_session.assert_not_awaited()

    async def test_chat_stream_translates_frames_for_bot_clients(
        self, client: AsyncClient, chat_mocks
    ):
        chat_mocks.load_history.return_value = [{"role": "user", "content": "prior msg"}]
        chat_mocks.subscribe.return_value = _sse_frames(
            'data: {"response": "hello bot"}\n\n',
            "data: [DONE]\n\n",
        )
        response = await client.post(
            f"{BOT_BASE}/chat-stream",
            json={
                "message": "hello bot",
                "platform": "discord",
                "platform_user_id": "u1",
                "channel_id": "ch1",
            },
        )
        assert response.status_code == 200
        expected = (
            'data: {"session_token": "sess-token-1"}\n\n'
            ": keepalive\n\n"
            'data: {"text": "hello bot"}\n\n'
            'data: {"done": true, "conversation_id": "conv-1"}\n\n'
        )
        assert response.text == expected

        chat_mocks.get_or_create_session.assert_awaited_once_with("discord", "u1", "ch1", BOT_USER)
        chat_mocks.load_history.assert_awaited_once_with("conv-1", "uid1")
        chat_mocks.start_stream.assert_awaited_once()
        stream_id, conversation_id, user_id = chat_mocks.start_stream.await_args.args
        assert isinstance(stream_id, str) and stream_id
        assert conversation_id == "conv-1"
        assert user_id == "uid1"

        background_kwargs = chat_mocks.background.call_args.kwargs
        assert background_kwargs["stream_id"] == stream_id
        assert background_kwargs["conversation_id"] == "conv-1"
        assert background_kwargs["source"] == "discord"
        assert background_kwargs["user"] == BOT_USER
        body = background_kwargs["body"]
        assert body.message == "hello bot"
        assert body.conversation_id == "conv-1"
        assert body.fileIds == []
        assert body.fileData == []
        assert body.messages == [
            {"role": "user", "content": "prior msg"},
            {"role": "user", "content": "hello bot"},
        ]
        chat_mocks.spawn.assert_called_once()
        assert isinstance(chat_mocks.spawn.call_args.args[0], CoroutineType)
        assert callable(chat_mocks.spawn.call_args.kwargs["on_done"])

    async def test_chat_stream_forwards_file_attachments(self, client: AsyncClient, chat_mocks):
        chat_mocks.subscribe.return_value = _sse_frames("data: [DONE]\n\n")
        response = await client.post(
            f"{BOT_BASE}/chat-stream",
            json={
                "message": "check this",
                "platform": "whatsapp",
                "platform_user_id": "wa1",
                "file_ids": ["f1", "f2"],
                "file_data": [
                    {
                        "fileId": "f1",
                        "url": "https://cdn.example/a.pdf",
                        "filename": "a.pdf",
                        "type": "application/pdf",
                    }
                ],
            },
        )
        assert response.status_code == 200
        body = chat_mocks.background.call_args.kwargs["body"]
        assert body.fileIds == ["f1", "f2"]
        assert body.fileData[0].fileId == "f1"
        assert body.fileData[0].url == "https://cdn.example/a.pdf"

    async def test_chat_stream_drops_web_only_fields(self, client: AsyncClient, chat_mocks):
        chat_mocks.subscribe.return_value = _sse_frames(
            'data: {"response": "x", "conversation_description": "d", '
            '"user_message_id": "u", "bot_message_id": "b", "stream_id": "s", '
            '"tool_data": {"tool_name": "anything"}, "tool_output": "o", '
            '"follow_up_actions": []}\n\n',
            'data: {"response": "kept"}\n\n',
            "data: [DONE]\n\n",
        )
        response = await client.post(
            f"{BOT_BASE}/chat-stream",
            json={"message": "hi", "platform": "discord", "platform_user_id": "u1"},
        )
        assert response.text == (
            'data: {"session_token": "sess-token-1"}\n\n'
            ": keepalive\n\n"
            'data: {"text": "kept"}\n\n'
            'data: {"done": true, "conversation_id": "conv-1"}\n\n'
        )

    async def test_chat_stream_error_frame_ends_stream(self, client: AsyncClient, chat_mocks):
        chat_mocks.subscribe.return_value = _sse_frames(
            'data: {"response": "partial"}\n\n',
            'data: {"error": "provider down"}\n\n',
            'data: {"response": "after"}\n\n',
            "data: [DONE]\n\n",
        )
        response = await client.post(
            f"{BOT_BASE}/chat-stream",
            json={"message": "hi", "platform": "discord", "platform_user_id": "u1"},
        )
        assert 'data: {"text": "partial"}\n\n' in response.text
        assert 'data: {"error": "provider down"}\n\n' in response.text
        assert "after" not in response.text
        assert "done" not in response.text

    async def test_chat_stream_rate_limit_notice_free_plan(self, client: AsyncClient, chat_mocks):
        chat_mocks.subscribe.return_value = _sse_frames(
            'data: {"tool_data": {"tool_name": "rate_limit_data", "data": '
            '{"feature": "audio_transcription", "current_plan": "free"}}}\n\n',
            'data: {"response": "still streaming"}\n\n',
            "data: [DONE]\n\n",
        )
        response = await client.post(
            f"{BOT_BASE}/chat-stream",
            json={"message": "hi", "platform": "discord", "platform_user_id": "u1"},
        )
        notice = (
            "\n\n⏳ You've reached your audio transcription limit. Please try again later. "
            f"[Upgrade to Pro]({settings.FRONTEND_URL}/pricing) for higher limits.\n\n"
        )
        assert f"data: {json.dumps({'text': notice})}\n\n" in response.text
        assert 'data: {"text": "still streaming"}\n\n' in response.text

    async def test_chat_stream_rate_limit_notice_pro_plan(self, client: AsyncClient, chat_mocks):
        chat_mocks.subscribe.return_value = _sse_frames(
            'data: {"tool_data": {"tool_name": "rate_limit_data", "data": '
            '{"feature": "chat_messages", "current_plan": "pro"}}}\n\n',
            "data: [DONE]\n\n",
        )
        response = await client.post(
            f"{BOT_BASE}/chat-stream",
            json={"message": "hi", "platform": "discord", "platform_user_id": "u1"},
        )
        assert "Upgrade to Pro" not in response.text
        assert "chat messages limit" in response.text

    async def test_chat_stream_approval_payload_frame(self, client: AsyncClient, chat_mocks):
        chat_mocks.subscribe.return_value = _sse_frames(
            'data: {"tool_data": {"tool_name": "approval_request", "data": '
            '{"approval_id": "a1", "request": "Approve?"}}}\n\n',
            "data: [DONE]\n\n",
        )
        response = await client.post(
            f"{BOT_BASE}/chat-stream",
            json={"message": "hi", "platform": "discord", "platform_user_id": "u1"},
        )
        assert (
            'data: {"approval": {"approval_id": "a1", "request": "Approve?"}}\n\n' in response.text
        )

    async def test_chat_stream_forward_keepalive_and_comment_frames(
        self, client: AsyncClient, chat_mocks
    ):
        chat_mocks.subscribe.return_value = _sse_frames(
            'data: {"keepalive": true}\n\n',
            ": comment\n\n",
            "data: [DONE]\n\n",
        )
        response = await client.post(
            f"{BOT_BASE}/chat-stream",
            json={"message": "hi", "platform": "discord", "platform_user_id": "u1"},
        )
        assert 'data: {"keepalive": true}\n\n' in response.text
        assert ": comment\n\n" in response.text

    async def test_chat_stream_strips_id_prefix(self, client: AsyncClient, chat_mocks):
        chat_mocks.subscribe.return_value = _sse_frames(
            'id: 123-456\ndata: {"response": "x"}\n\n',
            "data: [DONE]\n\n",
        )
        response = await client.post(
            f"{BOT_BASE}/chat-stream",
            json={"message": "hi", "platform": "discord", "platform_user_id": "u1"},
        )
        assert 'data: {"text": "x"}\n\n' in response.text

    async def test_chat_stream_drops_non_data_and_malformed_frames(
        self, client: AsyncClient, chat_mocks
    ):
        chat_mocks.subscribe.return_value = _sse_frames(
            "garbage: not-an-sse-frame\n\n",
            "data: {not-valid-json\n\n",
            "data: [DONE]\n\n",
        )
        response = await client.post(
            f"{BOT_BASE}/chat-stream",
            json={"message": "hi", "platform": "discord", "platform_user_id": "u1"},
        )
        assert response.text == (
            'data: {"session_token": "sess-token-1"}\n\n'
            ": keepalive\n\n"
            'data: {"done": true, "conversation_id": "conv-1"}\n\n'
        )

    async def test_chat_stream_subscription_error_yields_error_frame(
        self, client: AsyncClient, chat_mocks
    ):
        async def _failing(*args: object, **kwargs: object):
            yield 'data: {"response": "partial"}\n\n'
            raise RuntimeError("redis down")

        chat_mocks.subscribe.return_value = _failing()
        response = await client.post(
            f"{BOT_BASE}/chat-stream",
            json={"message": "hi", "platform": "discord", "platform_user_id": "u1"},
        )
        assert 'data: {"text": "partial"}\n\n' in response.text
        assert 'data: {"error": "Stream error occurred"}\n\n' in response.text

    async def test_chat_stream_normalizes_legacy_user_dict(self, client: AsyncClient, chat_mocks):
        chat_mocks.get_user.return_value = {"_id": "legacy-id"}
        chat_mocks.subscribe.return_value = _sse_frames("data: [DONE]\n\n")
        response = await client.post(
            f"{BOT_BASE}/chat-stream",
            json={"message": "hi", "platform": "discord", "platform_user_id": "u1"},
        )
        assert response.status_code == 200
        chat_mocks.get_or_create_session.assert_awaited_once_with(
            "discord", "u1", None, {"_id": "legacy-id", "user_id": "legacy-id"}
        )
        chat_mocks.load_history.assert_awaited_once_with("conv-1", "legacy-id")

    async def test_chat_stream_failure_callback_guards_cancelled_tasks(
        self, client: AsyncClient, chat_mocks
    ):
        chat_mocks.subscribe.return_value = _sse_frames("data: [DONE]\n\n")
        response = await client.post(
            f"{BOT_BASE}/chat-stream",
            json={"message": "hi", "platform": "discord", "platform_user_id": "u1"},
        )
        assert response.status_code == 200
        on_done = chat_mocks.spawn.call_args.kwargs["on_done"]

        cancelled_task = MagicMock()
        cancelled_task.cancelled.return_value = True
        on_done(cancelled_task)
        cancelled_task.exception.assert_not_called()

        failed_task = MagicMock()
        failed_task.cancelled.return_value = False
        failed_task.exception.return_value = RuntimeError("boom")
        on_done(failed_task)
        failed_task.exception.assert_called_once_with()

        clean_task = MagicMock()
        clean_task.cancelled.return_value = False
        clean_task.exception.return_value = None
        on_done(clean_task)
        clean_task.exception.assert_called_once_with()

    async def test_chat_stream_uses_state_user_when_authenticated(self, chat_mocks):
        request = _make_request(
            bot_api_key_valid=True,
            user={"user_id": "state-uid", "_id": "state-uid"},
            authenticated=True,
        )
        request.is_disconnected = AsyncMock(return_value=False)
        chat_mocks.subscribe.return_value = _sse_frames("data: [DONE]\n\n")
        response = await bot_chat_stream(
            request,
            BotChatRequest(message="hi", platform="discord", platform_user_id="u1"),
        )
        chunks = [chunk async for chunk in response.body_iterator]
        assert 'data: {"done": true, "conversation_id": "conv-1"}\n\n' in chunks[-1]
        chat_mocks.get_user.assert_not_awaited()
        chat_mocks.get_or_create_session.assert_awaited_once_with(
            "discord", "u1", None, {"user_id": "state-uid", "_id": "state-uid"}
        )

    async def test_chat_stream_cancelled_error_propagates(self, chat_mocks):
        async def _cancelled(*args: object, **kwargs: object):
            yield 'data: {"response": "x"}\n\n'
            raise asyncio.CancelledError()

        chat_mocks.subscribe.return_value = _cancelled()
        request = _make_request(
            bot_api_key_valid=True,
            user={"user_id": "uid1", "_id": "uid1"},
            authenticated=True,
        )
        request.is_disconnected = AsyncMock(return_value=False)
        response = await bot_chat_stream(
            request,
            BotChatRequest(message="hi", platform="discord", platform_user_id="u1"),
        )
        with pytest.raises(asyncio.CancelledError):
            async for _ in response.body_iterator:
                pass

    async def test_chat_stream_client_disconnect_breaks_early(self, chat_mocks):
        chat_mocks.subscribe.return_value = _sse_frames('data: {"response": "x"}\n\n')
        request = _make_request(
            bot_api_key_valid=True,
            user={"user_id": "uid1", "_id": "uid1"},
            authenticated=True,
        )
        request.is_disconnected = AsyncMock(return_value=True)
        response = await bot_chat_stream(
            request,
            BotChatRequest(message="hi", platform="discord", platform_user_id="u1"),
        )
        chunks = [chunk async for chunk in response.body_iterator]
        assert chunks == [
            'data: {"session_token": "sess-token-1"}\n\n',
            ": keepalive\n\n",
        ]


# ---------------------------------------------------------------------------
# POST /bot/transcribe — voice / audio transcription for bot adapters
# ---------------------------------------------------------------------------


class TestBotTranscribe:
    """POST /api/v1/bot/transcribe"""

    async def test_transcribe_no_api_key(self, client: AsyncClient):
        response = await client.post(
            f"{BOT_BASE}/transcribe",
            files={"file": ("voice.ogg", b"fake-audio-bytes", "audio/ogg")},
        )
        assert response.status_code == 401

    @patch("app.api.v1.endpoints.bot.require_bot_api_key", new_callable=AsyncMock)
    async def test_transcribe_unauthenticated_user(
        self, mock_auth: AsyncMock, unauthed_client: AsyncClient
    ):
        response = await unauthed_client.post(
            f"{BOT_BASE}/transcribe",
            files={"file": ("voice.ogg", b"fake-audio-bytes", "audio/ogg")},
        )
        assert response.status_code == 401

    @patch(
        "app.api.v1.endpoints.bot.transcribe_audio",
        new_callable=AsyncMock,
        return_value="hello transcript",
    )
    @patch("app.api.v1.endpoints.bot.require_bot_api_key", new_callable=AsyncMock)
    async def test_transcribe_success(
        self, mock_auth: AsyncMock, mock_transcribe: AsyncMock, client: AsyncClient
    ):
        response = await client.post(
            f"{BOT_BASE}/transcribe",
            files={"file": ("voice.ogg", b"fake-audio-bytes", "audio/ogg")},
        )
        assert response.status_code == 200
        assert response.json() == {"text": "hello transcript"}
        mock_transcribe.assert_awaited_once_with(
            audio_bytes=b"fake-audio-bytes",
            filename="voice.ogg",
            content_type="audio/ogg",
        )

    @patch(
        "app.api.v1.endpoints.bot.transcribe_audio",
        new_callable=AsyncMock,
        return_value="default name",
    )
    async def test_transcribe_default_filename(self, mock_transcribe: AsyncMock):
        # A multipart part without a filename is parsed as a form field, not an
        # UploadFile, so the `filename or "voice-note"` fallback is only
        # reachable by driving the (decorated) endpoint function directly.
        file = SimpleNamespace(
            content_type="audio/ogg",
            filename=None,
            read=AsyncMock(return_value=b"fake-audio-bytes"),
        )
        result = await transcribe_bot_audio(
            _make_request(bot_api_key_valid=True),
            file=file,
            content_length=None,
            user=BOT_USER,
        )
        assert result.text == "default name"
        mock_transcribe.assert_awaited_once_with(
            audio_bytes=b"fake-audio-bytes", filename="voice-note", content_type="audio/ogg"
        )

    @patch("app.api.v1.endpoints.bot.require_bot_api_key", new_callable=AsyncMock)
    async def test_transcribe_unsupported_format(self, mock_auth: AsyncMock, client: AsyncClient):
        response = await client.post(
            f"{BOT_BASE}/transcribe",
            files={"file": ("voice.ogg", b"fake-audio-bytes", "audio/x-unsupported")},
        )
        assert response.status_code == 415
        assert "Unsupported audio content type: audio/x-unsupported" in response.json()["detail"]

    @patch("app.api.v1.endpoints.bot.require_bot_api_key", new_callable=AsyncMock)
    async def test_transcribe_413_from_content_length_header(
        self, mock_auth: AsyncMock, client: AsyncClient
    ):
        response = await client.post(
            f"{BOT_BASE}/transcribe",
            files={"file": ("voice.ogg", b"fake-audio-bytes", "audio/ogg")},
            headers={"content-length": str(MAX_AUDIO_BYTES + 1)},
        )
        assert response.status_code == 413
        assert response.json()["detail"] == "Audio exceeds the 25 MB limit."

    @patch("app.api.v1.endpoints.bot.require_bot_api_key", new_callable=AsyncMock)
    async def test_transcribe_413_from_actual_payload_size(
        self, mock_auth: AsyncMock, client: AsyncClient
    ):
        response = await client.post(
            f"{BOT_BASE}/transcribe",
            files={"file": ("voice.ogg", b"x" * (MAX_AUDIO_BYTES + 1), "audio/ogg")},
            headers={"content-length": "100"},
        )
        assert response.status_code == 413
        assert response.json()["detail"] == "Audio exceeds the 25 MB limit."

    @patch(
        "app.api.v1.endpoints.bot.transcribe_audio",
        new_callable=AsyncMock,
        side_effect=RuntimeError("whisper is down"),
    )
    @patch("app.api.v1.endpoints.bot.require_bot_api_key", new_callable=AsyncMock)
    async def test_transcribe_provider_failure_returns_502(
        self, mock_auth: AsyncMock, mock_transcribe: AsyncMock, client: AsyncClient
    ):
        response = await client.post(
            f"{BOT_BASE}/transcribe",
            files={"file": ("voice.ogg", b"fake-audio-bytes", "audio/ogg")},
        )
        assert response.status_code == 502
        assert response.json()["detail"] == "Transcription failed"


# ---------------------------------------------------------------------------
# BotChatRequest — file attachments
# ---------------------------------------------------------------------------


class TestBotChatRequestFiles:
    """Pydantic validation for the new file_ids / file_data fields."""

    def test_accepts_file_ids_and_data(self):
        req = BotChatRequest(
            message="please analyze",
            platform="whatsapp",
            platform_user_id="1234567890",
            file_ids=["f1", "f2"],
            file_data=[
                {
                    "fileId": "f1",
                    "url": "https://cdn.example/a.pdf",
                    "filename": "a.pdf",
                    "type": "application/pdf",
                }
            ],
        )
        assert req.file_ids == ["f1", "f2"]
        assert req.file_data is not None
        assert req.file_data[0].fileId == "f1"
        assert req.file_data[0].url == "https://cdn.example/a.pdf"

    def test_defaults_to_none_when_omitted(self):
        req = BotChatRequest(message="hi", platform="whatsapp", platform_user_id="123")
        assert req.file_ids is None
        assert req.file_data is None
