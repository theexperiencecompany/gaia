"""Tests for app/api/v1/endpoints/platform_links.py.

The endpoints are thin orchestration: resolve the user id, validate the
platform, and hand the request to PlatformLinkService. These tests pin the
full HTTP contract — exact response bodies, exact service/redis arguments,
and the wide-event log lines — so a wrong argument, a missing audit line, or
a malformed URL fails at the boundary instead of silently degrading.
"""

from collections.abc import Iterator
from contextlib import contextmanager
from unittest.mock import AsyncMock, Mock, call, patch

from fastapi import FastAPI
from httpx import AsyncClient
import pytest

from app.api.v1.endpoints.platform_links import _require_user_id
from app.constants.cache import PLATFORM_LINK_TOKEN_PREFIX
from app.models.platform_models import PlatformLinkResult
from app.utils.errors import AppError
from tests.conftest import FAKE_USER

BASE = "/api/v1/platform-links"
USER_ID = FAKE_USER["user_id"]


@contextmanager
def _override_current_user(test_app: FastAPI, value: object) -> Iterator[None]:
    """Replace the auth dependency for one request, restoring it afterwards.

    The endpoint's own `if not current_user` guard is unreachable through
    ``unauthed_client`` (the dependency raises first), so this is how the
    guard's 401 response is exercised.
    """
    from app.api.v1.dependencies.oauth_dependencies import get_current_user

    original = test_app.dependency_overrides.get(get_current_user)
    test_app.dependency_overrides[get_current_user] = lambda: value
    try:
        yield
    finally:
        if original is None:
            test_app.dependency_overrides.pop(get_current_user, None)
        else:
            test_app.dependency_overrides[get_current_user] = original


def _redis_mock(token_data: dict) -> Mock:
    """Redis client mock: hgetall returns the token data, delete consumes it."""
    redis = Mock()
    redis.hgetall = AsyncMock(return_value=token_data)
    redis.delete = AsyncMock()
    return redis


# ---------------------------------------------------------------------------
# _require_user_id
# ---------------------------------------------------------------------------


class TestRequireUserId:
    """_require_user_id: extract the user id or fail the request."""

    def test_returns_user_id_when_present(self) -> None:
        assert _require_user_id({"user_id": USER_ID}) == USER_ID

    def test_missing_user_id_raises_500(self) -> None:
        with pytest.raises(AppError) as exc_info:
            _require_user_id({})
        assert exc_info.value.status_code == 500
        assert exc_info.value.message == "user_id must be a string"
        assert exc_info.value.why == "authenticated session resolved without a string user_id"
        assert exc_info.value.fix == "re-authenticate and retry; report if it persists"

    def test_non_string_user_id_raises_500(self) -> None:
        with pytest.raises(AppError) as exc_info:
            _require_user_id({"user_id": 123})
        assert exc_info.value.status_code == 500
        assert exc_info.value.message == "user_id must be a string"


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
        with (
            patch(
                "app.api.v1.endpoints.platform_links.PlatformLinkService.get_linked_platforms",
                new_callable=AsyncMock,
                return_value=links,
            ) as get_linked_platforms,
            patch("app.api.v1.endpoints.platform_links.log") as mock_log,
        ):
            resp = await client.get(BASE)

        assert resp.status_code == 200
        assert resp.json() == {"platform_links": links}
        get_linked_platforms.assert_awaited_once_with(USER_ID)
        assert mock_log.set.call_args_list == [
            call(user={"id": USER_ID}, operation="get_platform_links"),
            call(outcome="success", result_count=1),
        ]

    @pytest.mark.asyncio
    async def test_unauthenticated(self, unauthed_client: AsyncClient) -> None:
        resp = await unauthed_client.get(BASE)
        assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_falsy_current_user_returns_401(
        self, client: AsyncClient, test_app: FastAPI
    ) -> None:
        with _override_current_user(test_app, None):
            resp = await client.get(BASE)
        assert resp.status_code == 401
        assert resp.json()["detail"] == "Not authenticated"


# ---------------------------------------------------------------------------
# POST /platform-links/{platform}
# ---------------------------------------------------------------------------


class TestLinkPlatform:
    @pytest.mark.asyncio
    async def test_invalid_platform(self, client: AsyncClient) -> None:
        resp = await client.post(f"{BASE}/invalid_platform", json={"token": "tok123"})
        assert resp.status_code == 400
        assert resp.json()["detail"] == "Invalid platform"

    @pytest.mark.asyncio
    async def test_expired_token(self, client: AsyncClient) -> None:
        mock_redis = _redis_mock({})

        with (
            patch("app.api.v1.endpoints.platform_links.redis_cache") as mock_cache,
            patch("app.api.v1.endpoints.platform_links.log") as mock_log,
        ):
            mock_cache.client = mock_redis
            resp = await client.post(f"{BASE}/discord", json={"token": "expired_tok"})

        assert resp.status_code == 400
        assert (
            resp.json()["detail"]
            == "Invalid or expired link token. Please request a new link from the bot."
        )
        mock_redis.hgetall.assert_awaited_once_with(
            f"{PLATFORM_LINK_TOKEN_PREFIX}:expired_tok"
        )
        mock_redis.delete.assert_not_called()
        mock_log.audit.assert_called_once_with(
            "platform account link rejected",
            actor=USER_ID,
            provider="discord",
            reason="unknown_or_expired_token",
        )
        assert mock_log.set.call_args_list == [
            call(user={"id": USER_ID}, operation="link_platform", platform="discord")
        ]

    @pytest.mark.asyncio
    async def test_missing_platform_user_id(self, client: AsyncClient) -> None:
        mock_redis = _redis_mock({"platform": "discord", "platform_user_id": ""})

        with (
            patch("app.api.v1.endpoints.platform_links.redis_cache") as mock_cache,
            patch("app.api.v1.endpoints.platform_links.log") as mock_log,
        ):
            mock_cache.client = mock_redis
            resp = await client.post(f"{BASE}/discord", json={"token": "tok_no_uid"})

        assert resp.status_code == 400
        assert resp.json()["detail"] == "Invalid token data"
        mock_redis.hgetall.assert_awaited_once_with(
            f"{PLATFORM_LINK_TOKEN_PREFIX}:tok_no_uid"
        )
        mock_redis.delete.assert_awaited_once_with(
            f"{PLATFORM_LINK_TOKEN_PREFIX}:tok_no_uid"
        )
        mock_log.audit.assert_called_once_with(
            "platform account link rejected",
            actor=USER_ID,
            provider="discord",
            reason="malformed_token_data",
        )

    @pytest.mark.asyncio
    async def test_token_without_platform_user_id_key(self, client: AsyncClient) -> None:
        """A token whose platform_user_id key is absent (not just empty) is rejected."""
        mock_redis = _redis_mock({"platform": "discord"})

        with patch("app.api.v1.endpoints.platform_links.redis_cache") as mock_cache:
            mock_cache.client = mock_redis
            resp = await client.post(f"{BASE}/discord", json={"token": "tok_no_key"})

        assert resp.status_code == 400
        assert resp.json()["detail"] == "Invalid token data"
        mock_redis.delete.assert_awaited_once_with(
            f"{PLATFORM_LINK_TOKEN_PREFIX}:tok_no_key"
        )

    @pytest.mark.asyncio
    async def test_platform_mismatch(self, client: AsyncClient) -> None:
        mock_redis = _redis_mock(
            {"platform": "slack", "platform_user_id": "U123"}
        )

        with (
            patch("app.api.v1.endpoints.platform_links.redis_cache") as mock_cache,
            patch("app.api.v1.endpoints.platform_links.log") as mock_log,
        ):
            mock_cache.client = mock_redis
            resp = await client.post(f"{BASE}/discord", json={"token": "tok_mismatch"})

        assert resp.status_code == 400
        assert (
            resp.json()["detail"]
            == "Platform mismatch. This token was not generated for this platform."
        )
        mock_redis.delete.assert_awaited_once_with(
            f"{PLATFORM_LINK_TOKEN_PREFIX}:tok_mismatch"
        )
        mock_log.audit.assert_called_once_with(
            "platform account link rejected",
            actor=USER_ID,
            resource="U123",
            provider="discord",
            reason="platform_mismatch",
        )

    @pytest.mark.asyncio
    async def test_successful_link(self, client: AsyncClient) -> None:
        mock_redis = _redis_mock(
            {
                "platform": "discord",
                "platform_user_id": "DISC123",
                "username": "testuser",
                "display_name": "Test User",
            }
        )

        # is_new_link=False keeps this on the re-link path, so the assertions stay
        # about the response and not about the "connected" greeting side effect.
        link_result = PlatformLinkResult(
            status="linked",
            platform="discord",
            platform_user_id="DISC123",
            connected_at="2024-01-01T00:00:00Z",
            is_new_link=False,
        )

        with (
            patch("app.api.v1.endpoints.platform_links.redis_cache") as mock_cache,
            patch(
                "app.api.v1.endpoints.platform_links.PlatformLinkService.link_account",
                new_callable=AsyncMock,
                return_value=link_result,
            ) as link_account,
            patch("app.api.v1.endpoints.platform_links.log") as mock_log,
        ):
            mock_cache.client = mock_redis
            resp = await client.post(f"{BASE}/discord", json={"token": "valid_tok"})

        assert resp.status_code == 200
        assert resp.json() == {
            "status": "linked",
            "platform": "discord",
            "platform_user_id": "DISC123",
            "connected_at": "2024-01-01T00:00:00Z",
        }
        mock_redis.hgetall.assert_awaited_once_with(
            f"{PLATFORM_LINK_TOKEN_PREFIX}:valid_tok"
        )
        mock_redis.delete.assert_awaited_once_with(
            f"{PLATFORM_LINK_TOKEN_PREFIX}:valid_tok"
        )
        link_account.assert_awaited_once_with(
            USER_ID,
            "discord",
            "DISC123",
            profile={"username": "testuser", "display_name": "Test User"},
        )
        mock_log.audit.assert_not_called()
        assert mock_log.set.call_args_list == [
            call(user={"id": USER_ID}, operation="link_platform", platform="discord"),
            call(outcome="success"),
        ]

    @pytest.mark.asyncio
    async def test_successful_link_without_profile(self, client: AsyncClient) -> None:
        """A token with no username/display_name reaches the service with profile=None."""
        mock_redis = _redis_mock({"platform": "discord", "platform_user_id": "DISC123"})

        link_result = PlatformLinkResult(
            status="linked",
            platform="discord",
            platform_user_id="DISC123",
            connected_at="2024-01-01T00:00:00Z",
            is_new_link=False,
        )

        with (
            patch("app.api.v1.endpoints.platform_links.redis_cache") as mock_cache,
            patch(
                "app.api.v1.endpoints.platform_links.PlatformLinkService.link_account",
                new_callable=AsyncMock,
                return_value=link_result,
            ) as link_account,
        ):
            mock_cache.client = mock_redis
            resp = await client.post(f"{BASE}/discord", json={"token": "bare_tok"})

        assert resp.status_code == 200
        link_account.assert_awaited_once_with(
            USER_ID, "discord", "DISC123", profile=None
        )

    @pytest.mark.asyncio
    async def test_new_link_fires_greeting(self, client: AsyncClient) -> None:
        """is_new_link=True notifies the user and stays out of the HTTP payload."""
        mock_redis = _redis_mock({"platform": "discord", "platform_user_id": "DISC_NEW"})

        link_result = PlatformLinkResult(
            status="linked",
            platform="discord",
            platform_user_id="DISC_NEW",
            connected_at="2024-01-01T00:00:00Z",
            is_new_link=True,
        )

        with (
            patch("app.api.v1.endpoints.platform_links.redis_cache") as mock_cache,
            patch(
                "app.api.v1.endpoints.platform_links.PlatformLinkService.link_account",
                new_callable=AsyncMock,
                return_value=link_result,
            ),
            patch(
                "app.api.v1.endpoints.platform_links.notify_account_linked",
                new_callable=AsyncMock,
            ) as notify,
        ):
            mock_cache.client = mock_redis
            resp = await client.post(f"{BASE}/discord", json={"token": "new_tok"})

        assert resp.status_code == 200
        assert resp.json() == {
            "status": "linked",
            "platform": "discord",
            "platform_user_id": "DISC_NEW",
            "connected_at": "2024-01-01T00:00:00Z",
        }
        notify.assert_awaited_once_with("discord", USER_ID)

    @pytest.mark.asyncio
    async def test_link_conflict(self, client: AsyncClient) -> None:
        """ValueError from link_account returns 409 with the message."""
        mock_redis = _redis_mock(
            {"platform": "discord", "platform_user_id": "DISC_DUP"}
        )

        with (
            patch("app.api.v1.endpoints.platform_links.redis_cache") as mock_cache,
            patch(
                "app.api.v1.endpoints.platform_links.PlatformLinkService.link_account",
                new_callable=AsyncMock,
                side_effect=ValueError("already linked"),
            ),
            patch("app.api.v1.endpoints.platform_links.log") as mock_log,
        ):
            mock_cache.client = mock_redis
            resp = await client.post(f"{BASE}/discord", json={"token": "dup_tok"})

        assert resp.status_code == 409
        assert resp.json()["detail"] == "already linked"
        mock_log.audit.assert_called_once_with(
            "platform account link rejected",
            actor=USER_ID,
            resource="DISC_DUP",
            provider="discord",
            error_type="ValueError",
            error="already linked",
        )
        assert mock_log.set.call_args_list == [
            call(user={"id": USER_ID}, operation="link_platform", platform="discord")
        ]

    @pytest.mark.asyncio
    async def test_unauthenticated(self, unauthed_client: AsyncClient) -> None:
        resp = await unauthed_client.post(f"{BASE}/discord", json={"token": "t"})
        assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_falsy_current_user_returns_401(
        self, client: AsyncClient, test_app: FastAPI
    ) -> None:
        with _override_current_user(test_app, None):
            resp = await client.post(f"{BASE}/discord", json={"token": "t"})
        assert resp.status_code == 401
        assert resp.json()["detail"] == "Not authenticated"


# ---------------------------------------------------------------------------
# DELETE /platform-links/{platform}
# ---------------------------------------------------------------------------


class TestDisconnectPlatform:
    @pytest.mark.asyncio
    async def test_invalid_platform(self, client: AsyncClient) -> None:
        resp = await client.delete(f"{BASE}/badplatform")
        assert resp.status_code == 400
        assert resp.json()["detail"] == "Invalid platform"

    @pytest.mark.asyncio
    async def test_successful_disconnect_clears_cache(self, client: AsyncClient) -> None:
        existing = {"discord": {"platformUserId": "DISC999", "username": "u"}}
        mock_redis = Mock()
        mock_redis.delete = AsyncMock()

        with (
            patch(
                "app.api.v1.endpoints.platform_links.PlatformLinkService.get_linked_platforms",
                new_callable=AsyncMock,
                return_value=existing,
            ) as get_linked_platforms,
            patch(
                "app.api.v1.endpoints.platform_links.PlatformLinkService.unlink_account",
                new_callable=AsyncMock,
                return_value={"status": "disconnected", "platform": "discord"},
            ) as unlink_account,
            patch("app.api.v1.endpoints.platform_links.redis_cache") as mock_cache,
            patch("app.api.v1.endpoints.platform_links.log") as mock_log,
        ):
            mock_cache.client = mock_redis
            resp = await client.delete(f"{BASE}/discord")

        assert resp.status_code == 200
        assert resp.json() == {"status": "disconnected", "platform": "discord"}
        get_linked_platforms.assert_awaited_once_with(USER_ID)
        unlink_account.assert_awaited_once_with(USER_ID, "discord")
        mock_redis.delete.assert_awaited_once_with("bot_user:discord:DISC999")
        mock_log.audit.assert_called_once_with(
            "platform account unlinked",
            actor=USER_ID,
            resource="DISC999",
            provider="discord",
        )
        assert mock_log.set.call_args_list == [
            call(
                user={"id": USER_ID},
                operation="disconnect_platform",
                platform="discord",
            ),
            call(outcome="success"),
        ]

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
            patch("app.api.v1.endpoints.platform_links.log") as mock_log,
        ):
            mock_cache.client = AsyncMock()
            resp = await client.delete(f"{BASE}/discord")

        assert resp.status_code == 200
        mock_cache.client.delete.assert_not_called()
        mock_log.audit.assert_called_once_with(
            "platform account unlinked",
            actor=USER_ID,
            resource=None,
            provider="discord",
        )

    @pytest.mark.asyncio
    async def test_unlink_not_found(self, client: AsyncClient) -> None:
        """ValueError from unlink_account returns 404 with the message.

        The existing entry is present so the audit still names the platform
        user id whose unlink was rejected.
        """
        with (
            patch(
                "app.api.v1.endpoints.platform_links.PlatformLinkService.get_linked_platforms",
                new_callable=AsyncMock,
                return_value={"discord": {"platformUserId": "DISC999"}},
            ),
            patch(
                "app.api.v1.endpoints.platform_links.PlatformLinkService.unlink_account",
                new_callable=AsyncMock,
                side_effect=ValueError("not linked"),
            ),
            patch("app.api.v1.endpoints.platform_links.log") as mock_log,
        ):
            resp = await client.delete(f"{BASE}/discord")

        assert resp.status_code == 404
        assert resp.json()["detail"] == "not linked"
        mock_log.audit.assert_called_once_with(
            "platform account unlink rejected",
            actor=USER_ID,
            resource="DISC999",
            provider="discord",
            error_type="ValueError",
            error="not linked",
        )

    @pytest.mark.asyncio
    async def test_unauthenticated(self, unauthed_client: AsyncClient) -> None:
        resp = await unauthed_client.delete(f"{BASE}/discord")
        assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_falsy_current_user_returns_401(
        self, client: AsyncClient, test_app: FastAPI
    ) -> None:
        with _override_current_user(test_app, None):
            resp = await client.delete(f"{BASE}/discord")
        assert resp.status_code == 401
        assert resp.json()["detail"] == "Not authenticated"


# ---------------------------------------------------------------------------
# GET /platform-links/{platform}/connect
# ---------------------------------------------------------------------------


class TestInitiatePlatformConnect:
    @pytest.mark.asyncio
    async def test_invalid_platform(self, client: AsyncClient) -> None:
        resp = await client.get(f"{BASE}/badplatform/connect")
        assert resp.status_code == 400
        assert resp.json()["detail"] == "Invalid platform"

    @pytest.mark.asyncio
    async def test_discord_oauth(self, client: AsyncClient) -> None:
        with (
            patch("app.api.v1.endpoints.platform_links.settings") as mock_settings,
            patch(
                "app.api.v1.endpoints.platform_links.create_oauth_state",
                new_callable=AsyncMock,
                return_value="state123",
            ) as create_state,
            patch("app.api.v1.endpoints.platform_links.log") as mock_log,
        ):
            mock_settings.DISCORD_OAUTH_CLIENT_ID = "discord_client_id"
            mock_settings.DISCORD_OAUTH_REDIRECT_URI = "http://localhost/callback"
            mock_settings.SLACK_OAUTH_CLIENT_ID = None
            resp = await client.get(f"{BASE}/discord/connect")

        assert resp.status_code == 200
        assert resp.json() == {
            "auth_url": (
                "https://discord.com/api/oauth2/authorize"
                "?client_id=discord_client_id"
                "&redirect_uri=http%3A//localhost/callback"
                "&response_type=code"
                "&scope=identify"
                "&state=state123"
            ),
            "auth_type": "oauth",
            "instructions": None,
            "action_link": None,
        }
        create_state.assert_awaited_once_with(
            user_id=USER_ID,
            redirect_path="/settings?section=linked-accounts",
            integration_id="discord",
        )
        assert mock_log.set.call_args_list == [
            call(
                user={"id": USER_ID},
                operation="initiate_platform_connect",
                platform="discord",
            ),
            call(outcome="success", auth_type="oauth"),
        ]

    @pytest.mark.asyncio
    async def test_slack_oauth(self, client: AsyncClient) -> None:
        with (
            patch("app.api.v1.endpoints.platform_links.settings") as mock_settings,
            patch(
                "app.api.v1.endpoints.platform_links.create_oauth_state",
                new_callable=AsyncMock,
                return_value="slack_state",
            ) as create_state,
            patch("app.api.v1.endpoints.platform_links.log") as mock_log,
        ):
            mock_settings.DISCORD_OAUTH_CLIENT_ID = None
            mock_settings.SLACK_OAUTH_CLIENT_ID = "slack_client_id"
            mock_settings.SLACK_OAUTH_REDIRECT_URI = "http://localhost/slack/callback"
            resp = await client.get(f"{BASE}/slack/connect")

        assert resp.status_code == 200
        assert resp.json() == {
            "auth_url": (
                "https://slack.com/oauth/v2/authorize"
                "?client_id=slack_client_id"
                "&redirect_uri=http%3A//localhost/slack/callback"
                "&user_scope=identity.basic"
                "&state=slack_state"
            ),
            "auth_type": "oauth",
            "instructions": None,
            "action_link": None,
        }
        create_state.assert_awaited_once_with(
            user_id=USER_ID,
            redirect_path="/settings?section=linked-accounts",
            integration_id="slack",
        )
        assert mock_log.set.call_args_list == [
            call(
                user={"id": USER_ID},
                operation="initiate_platform_connect",
                platform="slack",
            ),
            call(outcome="success", auth_type="oauth"),
        ]

    @pytest.mark.asyncio
    async def test_telegram_manual(self, client: AsyncClient) -> None:
        with (
            patch("app.api.v1.endpoints.platform_links.settings") as mock_settings,
            patch("app.api.v1.endpoints.platform_links.log") as mock_log,
        ):
            mock_settings.DISCORD_OAUTH_CLIENT_ID = None
            mock_settings.SLACK_OAUTH_CLIENT_ID = None
            mock_settings.TELEGRAM_BOT_USERNAME = "my_gaia_bot"
            resp = await client.get(f"{BASE}/telegram/connect")

        assert resp.status_code == 200
        assert resp.json() == {
            "auth_url": None,
            "auth_type": "manual",
            "instructions": (
                "Open Telegram and message @my_gaia_bot with /auth to link your account."
            ),
            "action_link": "https://t.me/my_gaia_bot",
        }
        assert mock_log.set.call_args_list == [
            call(
                user={"id": USER_ID},
                operation="initiate_platform_connect",
                platform="telegram",
            ),
            call(outcome="success", auth_type="manual"),
        ]

    @pytest.mark.asyncio
    async def test_telegram_default_bot_username(self, client: AsyncClient) -> None:
        with patch("app.api.v1.endpoints.platform_links.settings") as mock_settings:
            mock_settings.DISCORD_OAUTH_CLIENT_ID = None
            mock_settings.SLACK_OAUTH_CLIENT_ID = None
            mock_settings.TELEGRAM_BOT_USERNAME = None
            resp = await client.get(f"{BASE}/telegram/connect")

        assert resp.status_code == 200
        assert resp.json()["instructions"] == (
            "Open Telegram and message @gaia_bot with /auth to link your account."
        )
        assert resp.json()["action_link"] == "https://t.me/gaia_bot"

    @pytest.mark.asyncio
    async def test_whatsapp_manual(self, client: AsyncClient) -> None:
        """WhatsApp uses manual flow (no OAuth) -> 200 with instructions."""
        with (
            patch("app.api.v1.endpoints.platform_links.settings") as mock_settings,
            patch("app.api.v1.endpoints.platform_links.log") as mock_log,
        ):
            mock_settings.DISCORD_OAUTH_CLIENT_ID = None
            mock_settings.SLACK_OAUTH_CLIENT_ID = None
            mock_settings.WHATSAPP_PHONE_NUMBER = "15551234567"
            resp = await client.get(f"{BASE}/whatsapp/connect")

        assert resp.status_code == 200
        assert resp.json() == {
            "auth_url": None,
            "auth_type": "manual",
            "instructions": (
                "Open WhatsApp and send /auth to the GAIA WhatsApp number to link your account."
            ),
            "action_link": "https://wa.me/15551234567",
        }
        assert mock_log.set.call_args_list == [
            call(
                user={"id": USER_ID},
                operation="initiate_platform_connect",
                platform="whatsapp",
            ),
            call(outcome="success", auth_type="manual"),
        ]

    @pytest.mark.asyncio
    async def test_whatsapp_without_phone_number(self, client: AsyncClient) -> None:
        """No phone number configured -> no action link, instructions only."""
        with patch("app.api.v1.endpoints.platform_links.settings") as mock_settings:
            mock_settings.DISCORD_OAUTH_CLIENT_ID = None
            mock_settings.SLACK_OAUTH_CLIENT_ID = None
            mock_settings.WHATSAPP_PHONE_NUMBER = None
            resp = await client.get(f"{BASE}/whatsapp/connect")

        assert resp.status_code == 200
        assert resp.json()["auth_type"] == "manual"
        assert resp.json()["action_link"] is None
        assert resp.json()["auth_url"] is None

    @pytest.mark.asyncio
    async def test_discord_without_oauth_config_returns_501(self, client: AsyncClient) -> None:
        with patch("app.api.v1.endpoints.platform_links.settings") as mock_settings:
            mock_settings.DISCORD_OAUTH_CLIENT_ID = None
            mock_settings.SLACK_OAUTH_CLIENT_ID = None
            resp = await client.get(f"{BASE}/discord/connect")

        assert resp.status_code == 501
        assert resp.json()["detail"] == "discord OAuth not configured"

    @pytest.mark.asyncio
    async def test_slack_without_oauth_config_returns_501(self, client: AsyncClient) -> None:
        # DISCORD_OAUTH_CLIENT_ID left truthy on purpose: a mutated discord
        # guard (== swapped, and -> or) would then take the discord branch
        # for a slack request and answer 200 instead of 501.
        with patch("app.api.v1.endpoints.platform_links.settings") as mock_settings:
            mock_settings.SLACK_OAUTH_CLIENT_ID = None
            resp = await client.get(f"{BASE}/slack/connect")

        assert resp.status_code == 501
        assert resp.json()["detail"] == "slack OAuth not configured"

    @pytest.mark.asyncio
    async def test_unauthenticated(self, unauthed_client: AsyncClient) -> None:
        resp = await unauthed_client.get(f"{BASE}/discord/connect")
        assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_falsy_current_user_returns_401(
        self, client: AsyncClient, test_app: FastAPI
    ) -> None:
        with _override_current_user(test_app, None):
            resp = await client.get(f"{BASE}/discord/connect")
        assert resp.status_code == 401
        assert resp.json()["detail"] == "Not authenticated"
