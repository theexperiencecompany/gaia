"""Tests for app/api/v1/endpoints/platform_links.py"""

from unittest.mock import AsyncMock, patch

import pytest
from httpx import AsyncClient

BASE = "/api/v1/platform-links"


# ---------------------------------------------------------------------------
# GET /platform-links
# ---------------------------------------------------------------------------


class TestGetPlatformLinks:
    @pytest.mark.asyncio
    async def test_success(self, client: AsyncClient) -> None:
        links = {
            "discord": {
                "platform": "discord",
                "platformUserId": "123",
                "username": "user",
                "displayName": "User",
                "connectedAt": "2024-01-01T00:00:00Z",
            }
        }
        with patch(
            "app.api.v1.endpoints.platform_links.PlatformLinkService.get_linked_platforms",
            new_callable=AsyncMock,
            return_value=links,
        ):
            resp = await client.get(BASE)

        assert resp.status_code == 200
        assert "discord" in resp.json()["platform_links"]

    @pytest.mark.asyncio
    async def test_unauthenticated(self, unauthed_client: AsyncClient) -> None:
        resp = await unauthed_client.get(BASE)
        assert resp.status_code == 401


# ---------------------------------------------------------------------------
# POST /platform-links/{platform}
# ---------------------------------------------------------------------------


class TestLinkPlatform:
    @pytest.mark.asyncio
    async def test_invalid_platform(self, client: AsyncClient) -> None:
        resp = await client.post(f"{BASE}/invalid_platform", json={"token": "tok123"})
        assert resp.status_code == 400
        assert "Invalid platform" in resp.json()["detail"]

    @pytest.mark.asyncio
    async def test_expired_token(self, client: AsyncClient) -> None:
        mock_redis = AsyncMock()
        mock_redis.hgetall = AsyncMock(return_value={})

        with patch("app.api.v1.endpoints.platform_links.redis_cache") as mock_cache:
            mock_cache.client = mock_redis
            resp = await client.post(f"{BASE}/discord", json={"token": "expired_tok"})

        assert resp.status_code == 400
        assert "expired" in resp.json()["detail"].lower()

    @pytest.mark.asyncio
    async def test_missing_platform_user_id(self, client: AsyncClient) -> None:
        mock_redis = AsyncMock()
        mock_redis.hgetall = AsyncMock(
            return_value={"platform": "discord", "platform_user_id": ""}
        )
        mock_redis.delete = AsyncMock()

        with patch("app.api.v1.endpoints.platform_links.redis_cache") as mock_cache:
            mock_cache.client = mock_redis
            resp = await client.post(f"{BASE}/discord", json={"token": "tok_no_uid"})

        assert resp.status_code == 400
        assert "Invalid token data" in resp.json()["detail"]

    @pytest.mark.asyncio
    async def test_platform_mismatch(self, client: AsyncClient) -> None:
        mock_redis = AsyncMock()
        mock_redis.hgetall = AsyncMock(
            return_value={"platform": "slack", "platform_user_id": "U123"}
        )
        mock_redis.delete = AsyncMock()

        with patch("app.api.v1.endpoints.platform_links.redis_cache") as mock_cache:
            mock_cache.client = mock_redis
            resp = await client.post(f"{BASE}/discord", json={"token": "tok_mismatch"})

        assert resp.status_code == 400
        assert "mismatch" in resp.json()["detail"].lower()

    @pytest.mark.asyncio
    async def test_successful_link(self, client: AsyncClient) -> None:
        mock_redis = AsyncMock()
        mock_redis.hgetall = AsyncMock(
            return_value={
                "platform": "discord",
                "platform_user_id": "DISC123",
                "username": "testuser",
                "display_name": "Test User",
            }
        )
        mock_redis.delete = AsyncMock()

        link_result = {
            "status": "linked",
            "platform": "discord",
            "platform_user_id": "DISC123",
            "connected_at": "2024-01-01T00:00:00Z",
        }

        with (
            patch("app.api.v1.endpoints.platform_links.redis_cache") as mock_cache,
            patch(
                "app.api.v1.endpoints.platform_links.PlatformLinkService.link_account",
                new_callable=AsyncMock,
                return_value=link_result,
            ),
        ):
            mock_cache.client = mock_redis
            resp = await client.post(f"{BASE}/discord", json={"token": "valid_tok"})

        assert resp.status_code == 200
        assert resp.json()["status"] == "linked"

    @pytest.mark.asyncio
    async def test_link_conflict(self, client: AsyncClient) -> None:
        """ValueError from link_account returns 409."""
        mock_redis = AsyncMock()
        mock_redis.hgetall = AsyncMock(
            return_value={
                "platform": "discord",
                "platform_user_id": "DISC_DUP",
            }
        )
        mock_redis.delete = AsyncMock()

        with (
            patch("app.api.v1.endpoints.platform_links.redis_cache") as mock_cache,
            patch(
                "app.api.v1.endpoints.platform_links.PlatformLinkService.link_account",
                new_callable=AsyncMock,
                side_effect=ValueError("already linked"),
            ),
        ):
            mock_cache.client = mock_redis
            resp = await client.post(f"{BASE}/discord", json={"token": "dup_tok"})

        assert resp.status_code == 409

    @pytest.mark.asyncio
    async def test_unauthenticated(self, unauthed_client: AsyncClient) -> None:
        resp = await unauthed_client.post(f"{BASE}/discord", json={"token": "t"})
        assert resp.status_code == 401


# ---------------------------------------------------------------------------
# DELETE /platform-links/{platform}
# ---------------------------------------------------------------------------


class TestDisconnectPlatform:
    @pytest.mark.asyncio
    async def test_invalid_platform(self, client: AsyncClient) -> None:
        resp = await client.delete(f"{BASE}/badplatform")
        assert resp.status_code == 400

    @pytest.mark.asyncio
    async def test_successful_disconnect_clears_cache(
        self, client: AsyncClient
    ) -> None:
        existing = {"discord": {"platformUserId": "DISC999", "username": "u"}}
        mock_redis = AsyncMock()
        mock_redis.delete = AsyncMock()

        with (
            patch(
                "app.api.v1.endpoints.platform_links.PlatformLinkService.get_linked_platforms",
                new_callable=AsyncMock,
                return_value=existing,
            ),
            patch(
                "app.api.v1.endpoints.platform_links.PlatformLinkService.unlink_account",
                new_callable=AsyncMock,
                return_value={"status": "disconnected", "platform": "discord"},
            ),
            patch("app.api.v1.endpoints.platform_links.redis_cache") as mock_cache,
        ):
            mock_cache.client = mock_redis
            resp = await client.delete(f"{BASE}/discord")

        assert resp.status_code == 200
        assert resp.json()["status"] == "disconnected"
        mock_redis.delete.assert_called_once_with("bot_user:discord:DISC999")

    @pytest.mark.asyncio
    async def test_disconnect_no_existing_entry(self, client: AsyncClient) -> None:
        """When platform_entry is None, skip cache deletion."""
        with (
            patch(
                "app.api.v1.endpoints.platform_links.PlatformLinkService.get_linked_platforms",
                new_callable=AsyncMock,
                return_value={},
            ),
            patch(
                "app.api.v1.endpoints.platform_links.PlatformLinkService.unlink_account",
                new_callable=AsyncMock,
                return_value={"status": "disconnected", "platform": "discord"},
            ),
            patch("app.api.v1.endpoints.platform_links.redis_cache") as mock_cache,
        ):
            mock_cache.client = AsyncMock()
            resp = await client.delete(f"{BASE}/discord")

        assert resp.status_code == 200
        mock_cache.client.delete.assert_not_called()

    @pytest.mark.asyncio
    async def test_unlink_not_found(self, client: AsyncClient) -> None:
        """ValueError from unlink_account returns 404."""
        with (
            patch(
                "app.api.v1.endpoints.platform_links.PlatformLinkService.get_linked_platforms",
                new_callable=AsyncMock,
                return_value={},
            ),
            patch(
                "app.api.v1.endpoints.platform_links.PlatformLinkService.unlink_account",
                new_callable=AsyncMock,
                side_effect=ValueError("not linked"),
            ),
        ):
            resp = await client.delete(f"{BASE}/discord")

        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_unauthenticated(self, unauthed_client: AsyncClient) -> None:
        resp = await unauthed_client.delete(f"{BASE}/discord")
        assert resp.status_code == 401


# ---------------------------------------------------------------------------
# GET /platform-links/{platform}/connect
# ---------------------------------------------------------------------------


class TestInitiatePlatformConnect:
    @pytest.mark.asyncio
    async def test_invalid_platform(self, client: AsyncClient) -> None:
        resp = await client.get(f"{BASE}/badplatform/connect")
        assert resp.status_code == 400

    @pytest.mark.asyncio
    async def test_discord_oauth(self, client: AsyncClient) -> None:
        with (
            patch("app.api.v1.endpoints.platform_links.settings") as mock_settings,
            patch(
                "app.api.v1.endpoints.platform_links.create_oauth_state",
                new_callable=AsyncMock,
                return_value="state123",
            ),
        ):
            mock_settings.DISCORD_OAUTH_CLIENT_ID = "discord_client_id"
            mock_settings.DISCORD_OAUTH_REDIRECT_URI = "http://localhost/callback"
            resp = await client.get(f"{BASE}/discord/connect")

        assert resp.status_code == 200
        body = resp.json()
        assert body["auth_type"] == "oauth"
        assert "discord.com" in body["auth_url"]
        assert "state123" in body["auth_url"]

    @pytest.mark.asyncio
    async def test_slack_oauth(self, client: AsyncClient) -> None:
        with (
            patch("app.api.v1.endpoints.platform_links.settings") as mock_settings,
            patch(
                "app.api.v1.endpoints.platform_links.create_oauth_state",
                new_callable=AsyncMock,
                return_value="slack_state",
            ),
        ):
            mock_settings.DISCORD_OAUTH_CLIENT_ID = None
            mock_settings.SLACK_OAUTH_CLIENT_ID = "slack_client_id"
            mock_settings.SLACK_OAUTH_REDIRECT_URI = "http://localhost/slack/callback"
            resp = await client.get(f"{BASE}/slack/connect")

        assert resp.status_code == 200
        body = resp.json()
        assert body["auth_type"] == "oauth"
        assert "slack.com" in body["auth_url"]

    @pytest.mark.asyncio
    async def test_telegram_manual(self, client: AsyncClient) -> None:
        with patch("app.api.v1.endpoints.platform_links.settings") as mock_settings:
            mock_settings.DISCORD_OAUTH_CLIENT_ID = None
            mock_settings.SLACK_OAUTH_CLIENT_ID = None
            mock_settings.TELEGRAM_BOT_USERNAME = "my_gaia_bot"
            resp = await client.get(f"{BASE}/telegram/connect")

        assert resp.status_code == 200
        body = resp.json()
        assert body["auth_type"] == "manual"
        assert "my_gaia_bot" in body["instructions"]
        assert body["action_link"] == "https://t.me/my_gaia_bot"

    @pytest.mark.asyncio
    async def test_telegram_default_bot_username(self, client: AsyncClient) -> None:
        with patch("app.api.v1.endpoints.platform_links.settings") as mock_settings:
            mock_settings.DISCORD_OAUTH_CLIENT_ID = None
            mock_settings.SLACK_OAUTH_CLIENT_ID = None
            mock_settings.TELEGRAM_BOT_USERNAME = None
            resp = await client.get(f"{BASE}/telegram/connect")

        assert resp.status_code == 200
        assert "gaia_bot" in resp.json()["instructions"]

    @pytest.mark.asyncio
    async def test_whatsapp_manual(self, client: AsyncClient) -> None:
        """WhatsApp uses manual flow (no OAuth) -> 200 with instructions."""
        with patch("app.api.v1.endpoints.platform_links.settings") as mock_settings:
            mock_settings.DISCORD_OAUTH_CLIENT_ID = None
            mock_settings.SLACK_OAUTH_CLIENT_ID = None
            mock_settings.WHATSAPP_PHONE_NUMBER = "15551234567"
            resp = await client.get(f"{BASE}/whatsapp/connect")

        assert resp.status_code == 200
        body = resp.json()
        assert body["auth_type"] == "manual"
        assert "WhatsApp" in body["instructions"]
        assert body["action_link"] == "https://wa.me/15551234567"

    @pytest.mark.asyncio
    async def test_unauthenticated(self, unauthed_client: AsyncClient) -> None:
        resp = await unauthed_client.get(f"{BASE}/discord/connect")
        assert resp.status_code == 401
