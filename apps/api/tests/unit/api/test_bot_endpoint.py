"""Unit tests for bot API endpoints.

Tests the bot endpoints with mocked service layer to verify
routing, status codes, response bodies, and auth checks.
"""

import asyncio
from collections.abc import AsyncGenerator
from datetime import UTC, datetime
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, call, patch
from uuid import UUID

from fastapi import HTTPException
import httpx
from httpx import AsyncClient
from prometheus_client import REGISTRY
import pytest

from app.api.v1.endpoints import bot as bot_module
from app.api.v1.endpoints.bot import (
    _bot_rate_limit_notice,
    _bot_upgrade_url,
    _bot_upgrade_url_once,
    bot_chat_stream,
)
from app.constants.cache import BOT_UPGRADE_LINK_TTL
from app.core.stream_manager import with_heartbeat
from app.db.redis import redis_cache
from app.models.bot_models import BotChatRequest, BotWebStreamPayload
from app.models.payment_models import (
    CreateSubscriptionResponse,
    PlanDuration,
    PlanResponse,
    PlanType,
    ProCheckout,
)
from app.models.user_models import AuthenticatedUser, UserDocument
from app.services.analytics_service import AnalyticsEvents
from shared.py.wide_events import log, log_context

BOT_BASE = "/api/v1/bot"


async def _never_upgrade() -> str:
    """Fail if called: a stream with no rate-limit card must never resolve an upgrade URL."""
    raise AssertionError("the upgrade URL was resolved for a stream with no rate-limit card")


PLAN_PATCH = "app.services.platform_link_service.payment_service.get_cached_plan_type"


def _CHAT_BODY(platform: str) -> dict[str, str]:
    return {"message": "hello", "platform": platform, "platform_user_id": "u1"}


def _make_request(bot_api_key_valid: bool = True, **extra_state: object) -> MagicMock:
    """Build a fake Request whose .state carries bot auth attributes."""
    state = MagicMock()
    state.bot_api_key_valid = bot_api_key_valid
    state.bot_platform = extra_state.get("bot_platform")
    state.bot_platform_user_id = extra_state.get("bot_platform_user_id")
    state.user = extra_state.get("user")
    state.authenticated = extra_state.get("authenticated", False)
    return state


@pytest.fixture(autouse=True)
def _no_real_redis_cost_budget():
    """Null the Redis client to force the documented fail-open (cost reads 0.0).

    get_cost uses the real client; under randomized test order a stale
    connection can raise RuntimeError: Event loop is closed instead of the
    RedisError/OSError it actually catches — an unhandled 500, not a flaky
    assertion.
    """
    original = redis_cache.redis
    redis_cache.redis = None
    yield
    redis_cache.redis = original


@pytest.fixture(autouse=True)
def _pro_plan_by_default():
    """GAIA is paid-only: default every test in this file to a paying user.

    Most of these tests exercise chat mechanics, quota metering, or unrelated
    bot endpoints — not the paywall itself (see TestBotChatStreamSubscriptionGate
    for that). A test that needs FREE re-patches PLAN_PATCH inside its own
    with block, which nests inside (and correctly overrides) this one.
    """
    with patch(PLAN_PATCH, new_callable=AsyncMock, return_value=PlanType.PRO):
        yield


# ---------------------------------------------------------------------------
# POST /bot/reset-session
# ---------------------------------------------------------------------------


class TestResetSession:
    """POST /api/v1/bot/reset-session."""

    @patch("app.api.v1.endpoints.bot.capture_event")
    @patch("app.api.v1.endpoints.bot.BotService")
    @patch(
        "app.services.bot_service.BotService.load_conversation_history",
        new=AsyncMock(return_value=[]),
    )
    @patch(
        "app.utils.auth_utils.user_repository.get_by_platform_id",
        new_callable=AsyncMock,
    )
    @patch("app.api.v1.endpoints.bot.require_bot_api_key", new_callable=AsyncMock)
    async def test_reset_session_success(
        self,
        mock_auth: AsyncMock,
        mock_get_user: AsyncMock,
        mock_bot_svc: MagicMock,
        mock_capture: MagicMock,
        client: AsyncClient,
    ):
        mock_get_user.return_value = UserDocument(id="uid1")
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
        mock_get_user.assert_awaited_once_with("discord", "u1")
        # Bot routes are auth-excluded — the id must be explicit or the event
        # lands on an anonymous profile.
        mock_capture.assert_called_once_with(
            "uid1",
            AnalyticsEvents.BOT_SESSION_RESET,
            {"platform": "discord"},
        )

    @patch(
        "app.utils.auth_utils.user_repository.get_by_platform_id",
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
    async def test_reset_session_validation_error(self, mock_auth: AsyncMock, client: AsyncClient):
        response = await client.post(f"{BOT_BASE}/reset-session", json={})
        assert response.status_code == 422


# ---------------------------------------------------------------------------
# _resolve_bot_caller — the user every bot turn acts as
# ---------------------------------------------------------------------------


class TestResolveBotCaller:
    """One seam, every bot route that needs a user.

    A wrong answer here runs the turn as, or attributes it to, a different account.
    """

    async def test_the_middleware_user_wins_when_the_request_is_authenticated(self):
        from app.api.v1.endpoints.bot import _resolve_bot_caller

        middleware_user = AuthenticatedUser(user_id="uid_from_middleware")
        request = MagicMock()
        request.state = _make_request(user=middleware_user, authenticated=True)
        with patch("app.api.v1.endpoints.bot.resolve_bot_user", new_callable=AsyncMock) as lookup:
            assert await _resolve_bot_caller(request, "discord", "u1") is middleware_user
        lookup.assert_not_awaited()

    async def test_an_unauthenticated_state_user_falls_back_to_the_platform_link(self):
        """request.state.user alone is not trusted — authenticated must be set too."""
        from app.api.v1.endpoints.bot import _resolve_bot_caller

        linked = AuthenticatedUser(user_id="uid_from_lookup", auth_provider="bot:discord")
        request = MagicMock()
        request.state = _make_request(
            user=AuthenticatedUser(user_id="uid_from_middleware"), authenticated=False
        )
        with patch(
            "app.api.v1.endpoints.bot.resolve_bot_user",
            new_callable=AsyncMock,
            return_value=linked,
        ) as lookup:
            assert await _resolve_bot_caller(request, "discord", "u1") is linked
        lookup.assert_awaited_once_with("discord", "u1")

    async def test_a_state_user_with_no_authenticated_flag_falls_back_to_the_platform_link(self):
        from app.api.v1.endpoints.bot import _resolve_bot_caller

        request = MagicMock()
        request.state = SimpleNamespace(user=AuthenticatedUser(user_id="uid_from_middleware"))
        with patch(
            "app.api.v1.endpoints.bot.resolve_bot_user", new_callable=AsyncMock, return_value=None
        ) as lookup:
            assert await _resolve_bot_caller(request, "discord", "u1") is None
        lookup.assert_awaited_once_with("discord", "u1")

    async def test_a_state_value_that_is_not_an_authenticated_user_is_not_trusted(self):
        from app.api.v1.endpoints.bot import _resolve_bot_caller

        request = MagicMock()
        request.state = _make_request(user={"user_id": "forged"}, authenticated=True)
        with patch(
            "app.api.v1.endpoints.bot.resolve_bot_user", new_callable=AsyncMock, return_value=None
        ) as lookup:
            assert await _resolve_bot_caller(request, "telegram", "tg9") is None
        lookup.assert_awaited_once_with("telegram", "tg9")

    async def test_an_unlinked_platform_account_resolves_to_nobody(self):
        from app.api.v1.endpoints.bot import _resolve_bot_caller

        request = MagicMock()
        request.state = _make_request()
        with patch(
            "app.api.v1.endpoints.bot.resolve_bot_user", new_callable=AsyncMock, return_value=None
        ):
            assert await _resolve_bot_caller(request, "discord", "u1") is None


# ---------------------------------------------------------------------------
# GET /bot/auth-status/{platform}/{platform_user_id}
# ---------------------------------------------------------------------------


class TestCheckAuthStatus:
    """GET /api/v1/bot/auth-status/{platform}/{platform_user_id}."""

    @patch(
        "app.utils.auth_utils.user_repository.get_by_platform_id",
        new_callable=AsyncMock,
    )
    @patch("app.api.v1.endpoints.bot.require_bot_api_key", new_callable=AsyncMock)
    async def test_auth_status_authenticated(
        self,
        mock_auth: AsyncMock,
        mock_get_user: AsyncMock,
        client: AsyncClient,
    ):
        mock_get_user.return_value = UserDocument(id="uid1")
        response = await client.get(f"{BOT_BASE}/auth-status/discord/u1")
        assert response.status_code == 200
        data = response.json()
        assert data["authenticated"] is True
        assert data["platform"] == "discord"
        assert data["platform_user_id"] == "u1"
        # The bot keys PostHog on this id. Returning only the boolean is what
        # left bot events on a parallel `discord:<id>` profile.
        assert data["user_id"] == "uid1"
        mock_get_user.assert_awaited_once_with("discord", "u1")

    @patch(
        "app.utils.auth_utils.user_repository.get_by_platform_id",
        new_callable=AsyncMock,
    )
    @patch("app.api.v1.endpoints.bot.require_bot_api_key", new_callable=AsyncMock)
    async def test_auth_status_falls_back_to_mongo_id(
        self,
        mock_auth: AsyncMock,
        mock_get_user: AsyncMock,
        client: AsyncClient,
    ):
        """The linked document's id is the answer — the same distinct_id the chat route uses."""
        mock_get_user.return_value = UserDocument(id="507f1f77bcf86cd799439011")
        response = await client.get(f"{BOT_BASE}/auth-status/discord/u1")
        assert response.status_code == 200
        assert response.json()["user_id"] == "507f1f77bcf86cd799439011"

    @patch(
        "app.utils.auth_utils.user_repository.get_by_platform_id",
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
        # No link means no GAIA identity yet; the bot must fall back to the
        # platform id rather than attribute to an empty string.
        assert data["user_id"] is None

    @patch("app.api.v1.endpoints.bot.require_bot_api_key", new_callable=AsyncMock)
    async def test_auth_status_invalid_platform(self, mock_auth: AsyncMock, client: AsyncClient):
        response = await client.get(f"{BOT_BASE}/auth-status/invalid_plat/u1")
        assert response.status_code == 400

    async def test_auth_status_no_api_key(self, client: AsyncClient):
        response = await client.get(f"{BOT_BASE}/auth-status/discord/u1")
        assert response.status_code == 401


# ---------------------------------------------------------------------------
# GET /bot/settings/{platform}/{platform_user_id}
# ---------------------------------------------------------------------------


class TestGetSettings:
    """GET /api/v1/bot/settings/{platform}/{platform_user_id}."""

    @patch(
        "app.api.v1.endpoints.bot.get_user_integration_records",
        new_callable=AsyncMock,
    )
    @patch(
        "app.utils.auth_utils.user_repository.get_by_platform_id",
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
        mock_get_user.return_value = UserDocument(
            id="uid1", name="Alice", picture="https://img.example.com/a.png", created_at=None
        )
        mock_integrations.return_value = []
        response = await client.get(f"{BOT_BASE}/settings/discord/u1")
        assert response.status_code == 200
        data = response.json()
        assert data["authenticated"] is True
        assert data["user_name"] == "Alice"
        assert data["profile_image_url"] == "https://img.example.com/a.png"
        mock_get_user.assert_awaited_once_with("discord", "u1")
        # Whose integrations were fetched. Unasserted, a null user id here
        # returns another account's settings — or none — and still 200s.
        mock_integrations.assert_awaited_once_with("uid1")

    @patch(
        "app.api.v1.endpoints.bot.get_user_integration_records",
        new_callable=AsyncMock,
        return_value=[],
    )
    @patch(
        "app.utils.auth_utils.user_repository.get_by_platform_id",
        new_callable=AsyncMock,
    )
    @patch("app.api.v1.endpoints.bot.require_bot_api_key", new_callable=AsyncMock)
    async def test_settings_report_the_account_creation_time_as_iso(
        self,
        mock_auth: AsyncMock,
        mock_get_user: AsyncMock,
        mock_integrations: AsyncMock,
        client: AsyncClient,
    ):
        mock_get_user.return_value = UserDocument(
            id="uid1", created_at=datetime(2025, 1, 2, 3, 4, 5, tzinfo=UTC)
        )
        response = await client.get(f"{BOT_BASE}/settings/discord/u1")
        assert response.status_code == 200
        assert response.json()["account_created_at"] == "2025-01-02T03:04:05+00:00"

    @patch("app.api.v1.endpoints.bot.get_integration_details", new_callable=AsyncMock)
    @patch(
        "app.api.v1.endpoints.bot.get_user_integration_records",
        new_callable=AsyncMock,
    )
    @patch(
        "app.utils.auth_utils.user_repository.get_by_platform_id",
        new_callable=AsyncMock,
    )
    @patch("app.api.v1.endpoints.bot.require_bot_api_key", new_callable=AsyncMock)
    async def test_settings_lists_each_integration_record_with_its_status(
        self,
        mock_auth: AsyncMock,
        mock_get_user: AsyncMock,
        mock_integrations: AsyncMock,
        mock_details: AsyncMock,
        client: AsyncClient,
    ):
        mock_get_user.return_value = UserDocument(id="uid1", name="Alice", created_at=None)
        # The records arrive as dumped documents, exactly as the service returns them.
        mock_integrations.return_value = [
            {"id": "r1", "user_id": "uid1", "integration_id": "gmail", "status": "connected"},
            {"id": "r2", "user_id": "uid1", "integration_id": "notion", "status": "created"},
        ]
        details = {
            "gmail": MagicMock(icon_url="https://icons/gmail.png"),
            "notion": MagicMock(icon_url="https://icons/notion.png"),
        }
        details["gmail"].name = "Gmail"
        details["notion"].name = "Notion"
        mock_details.side_effect = lambda integration_id: details[integration_id]

        response = await client.get(f"{BOT_BASE}/settings/discord/u1")

        assert response.status_code == 200
        assert response.json()["connected_integrations"] == [
            {"name": "Gmail", "logo_url": "https://icons/gmail.png", "status": "connected"},
            {"name": "Notion", "logo_url": "https://icons/notion.png", "status": "created"},
        ]

    @patch(
        "app.utils.auth_utils.user_repository.get_by_platform_id",
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
    async def test_settings_invalid_platform(self, mock_auth: AsyncMock, client: AsyncClient):
        response = await client.get(f"{BOT_BASE}/settings/badplatform/u1")
        assert response.status_code == 400


# ---------------------------------------------------------------------------
# POST /bot/unlink
# ---------------------------------------------------------------------------


class TestUnlinkAccount:
    """POST /api/v1/bot/unlink."""

    @patch("app.api.v1.endpoints.bot.capture_event")
    @patch("app.api.v1.endpoints.bot.redis_cache")
    @patch(
        "app.api.v1.endpoints.bot.PlatformLinkService.unlink_account",
        new_callable=AsyncMock,
    )
    @patch(
        "app.utils.auth_utils.user_repository.get_by_platform_id",
        new_callable=AsyncMock,
    )
    @patch("app.api.v1.endpoints.bot.require_bot_api_key", new_callable=AsyncMock)
    async def test_unlink_success(
        self,
        mock_auth: AsyncMock,
        mock_get_user: AsyncMock,
        mock_unlink: AsyncMock,
        mock_redis: MagicMock,
        mock_capture: MagicMock,
        client: AsyncClient,
    ):
        mock_get_user.return_value = UserDocument(id="uid1")
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
        mock_get_user.assert_awaited_once_with("discord", "u1")
        # The same event name the web-side unlink emits — one action, one name.
        mock_capture.assert_called_once_with(
            "uid1",
            AnalyticsEvents.INTEGRATION_DISCONNECTED,
            {"integration_id": "discord"},
        )

    @patch("app.api.v1.endpoints.bot.require_bot_api_key", new_callable=AsyncMock)
    async def test_unlink_missing_headers(self, mock_auth: AsyncMock, client: AsyncClient):
        response = await client.post(f"{BOT_BASE}/unlink")
        assert response.status_code == 400

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

    @patch(
        "app.utils.auth_utils.user_repository.get_by_platform_id",
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


class TestBotChatStream:
    """POST /api/v1/bot/chat-stream."""

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

    # The four the body never touches are patched with `new=`, which injects no
    # parameter — the signature would otherwise cross ruff's positional-argument
    # limit purely with mocks nothing asserts on.
    @patch("app.api.v1.endpoints.bot.spawn_background_task", new=MagicMock())
    @patch("app.api.v1.endpoints.bot.run_chat_stream_background", new=AsyncMock())
    @patch(
        "app.api.v1.endpoints.bot.create_bot_session_token",
        new=MagicMock(return_value="tok"),
    )
    @patch(
        "app.utils.auth_utils.user_repository.get_by_platform_id",
        new_callable=AsyncMock,
    )
    @patch("app.api.v1.endpoints.bot.stream_manager")
    @patch("app.api.v1.endpoints.bot.BotService")
    @patch(
        "app.services.bot_service.BotService.load_conversation_history",
        new=AsyncMock(return_value=[]),
    )
    @patch("app.services.bot_service.capture_event")
    @patch("app.api.v1.endpoints.bot.require_bot_api_key", new=AsyncMock())
    async def test_chat_stream_captures_message_submitted(
        self,
        mock_capture: MagicMock,
        mock_bot_svc: MagicMock,
        mock_sm: MagicMock,
        mock_get_user: AsyncMock,
        client: AsyncClient,
    ):
        """Attributed via capture_event since bot routes are auth-excluded and the request context has no identity."""
        mock_get_user.return_value = UserDocument(id="uid1")
        mock_bot_svc.enforce_rate_limit = AsyncMock()
        mock_bot_svc.get_or_create_session = AsyncMock(return_value="conv-1")
        mock_bot_svc.load_conversation_history = AsyncMock(return_value=[])
        mock_sm.start_stream = AsyncMock()

        async def _empty_stream():
            if False:  # pragma: no cover
                yield

        mock_sm.subscribe_stream.return_value = _empty_stream()

        response = await client.post(
            f"{BOT_BASE}/chat-stream",
            json={
                "message": "hello",
                "platform": "discord",
                "platform_user_id": "u1",
            },
        )
        assert response.status_code == 200
        await response.aread()

        mock_capture.assert_called_once_with(
            "uid1",
            AnalyticsEvents.CHAT_MESSAGE_SUBMITTED,
            {"source": "discord", "has_files": False},
        )

    # The four the body never touches are patched with `new=`, which injects no
    # parameter — the signature would otherwise cross ruff's positional-argument
    # limit purely with mocks nothing asserts on.
    @patch("app.api.v1.endpoints.bot.spawn_background_task", new=MagicMock())
    @patch("app.api.v1.endpoints.bot.run_chat_stream_background", new=AsyncMock())
    @patch(
        "app.api.v1.endpoints.bot.create_bot_session_token",
        new=MagicMock(return_value="tok"),
    )
    @patch(
        "app.utils.auth_utils.user_repository.get_by_platform_id",
        new_callable=AsyncMock,
    )
    @patch("app.api.v1.endpoints.bot.stream_manager")
    @patch("app.api.v1.endpoints.bot.BotService")
    @patch(
        "app.services.bot_service.BotService.load_conversation_history",
        new=AsyncMock(return_value=[]),
    )
    @patch("app.services.bot_service.capture_event")
    @patch("app.api.v1.endpoints.bot.require_bot_api_key", new=AsyncMock())
    async def test_chat_stream_captures_has_files(
        self,
        mock_capture: MagicMock,
        mock_bot_svc: MagicMock,
        mock_sm: MagicMock,
        mock_get_user: AsyncMock,
        client: AsyncClient,
    ):
        """A message carrying attachments reports has_files=True."""
        mock_get_user.return_value = UserDocument(id="uid1")
        mock_bot_svc.enforce_rate_limit = AsyncMock()
        mock_bot_svc.get_or_create_session = AsyncMock(return_value="conv-1")
        mock_bot_svc.load_conversation_history = AsyncMock(return_value=[])
        mock_sm.start_stream = AsyncMock()

        async def _empty_stream():
            if False:  # pragma: no cover
                yield

        mock_sm.subscribe_stream.return_value = _empty_stream()

        response = await client.post(
            f"{BOT_BASE}/chat-stream",
            json={
                "message": "hello with file",
                "platform": "discord",
                "platform_user_id": "u1",
                "file_ids": ["file-1"],
            },
        )
        assert response.status_code == 200
        await response.aread()

        mock_capture.assert_called_once_with(
            "uid1",
            AnalyticsEvents.CHAT_MESSAGE_SUBMITTED,
            {"source": "discord", "has_files": True},
        )

    @patch("app.api.v1.endpoints.bot.BotService.enforce_rate_limit", new_callable=AsyncMock)
    @patch("app.api.v1.endpoints.bot.require_bot_api_key", new_callable=AsyncMock)
    async def test_chat_stream_unlinked_user_gets_not_authenticated_frame(
        self, mock_auth: AsyncMock, mock_limit: AsyncMock, client: AsyncClient
    ):
        with patch(
            "app.utils.auth_utils.user_repository.get_by_platform_id",
            new_callable=AsyncMock,
            return_value=None,
        ):
            response = await client.post(f"{BOT_BASE}/chat-stream", json=_CHAT_BODY("imessage"))

        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/event-stream")
        # GAIA is paid-only: an unlinked user is told to link AND subscribe, via
        # a `notice` frame ahead of the untouched not_authenticated error frame
        # (the /auth-link flow it triggers is unchanged).
        assert response.text == (
            'data: {"notice": {"text": "GAIA is paid only. Link your account '
            'with /auth, then subscribe to GAIA Pro to chat."}}\n\n'
            'data: {"error": "not_authenticated"}\n\n'
        )

    @patch("app.services.bot_service.enforce_tiered_limit", new_callable=AsyncMock)
    @patch("app.api.v1.endpoints.bot.BotService.enforce_rate_limit", new_callable=AsyncMock)
    @patch("app.api.v1.endpoints.bot.require_bot_api_key", new_callable=AsyncMock)
    async def test_chat_stream_free_user_on_premium_platform_gets_plan_required_frame(
        self,
        mock_auth: AsyncMock,
        mock_limit: AsyncMock,
        mock_tiered: AsyncMock,
        client: AsyncClient,
    ):
        with (
            patch(
                "app.utils.auth_utils.user_repository.get_by_platform_id",
                new_callable=AsyncMock,
                return_value=UserDocument(id="u1"),
            ),
            patch(PLAN_PATCH, new_callable=AsyncMock, return_value=PlanType.FREE) as mock_plan,
        ):
            response = await client.post(f"{BOT_BASE}/chat-stream", json=_CHAT_BODY("imessage"))

        assert response.status_code == 200
        assert response.text == 'data: {"error": "plan_required"}\n\n'
        mock_plan.assert_awaited_once_with("u1")
        mock_tiered.assert_not_awaited()

    @patch("app.api.v1.endpoints.bot.capture_event")
    @patch("app.services.bot_service.enforce_tiered_limit", new_callable=AsyncMock)
    @patch("app.api.v1.endpoints.bot.BotService.enforce_rate_limit", new_callable=AsyncMock)
    @patch("app.api.v1.endpoints.bot.require_bot_api_key", new_callable=AsyncMock)
    async def test_a_refused_turn_is_not_counted_as_a_submitted_message(
        self,
        mock_auth: AsyncMock,
        mock_limit: AsyncMock,
        mock_tiered: AsyncMock,
        mock_capture: MagicMock,
        client: AsyncClient,
    ):
        """Counting a plan-gate refusal would inflate bot volume and make it incomparable to web, which captures after its own gates."""
        with (
            patch(
                "app.utils.auth_utils.user_repository.get_by_platform_id",
                new_callable=AsyncMock,
                return_value=UserDocument(id="u1"),
            ),
            patch(PLAN_PATCH, new_callable=AsyncMock, return_value=PlanType.FREE),
        ):
            await client.post(f"{BOT_BASE}/chat-stream", json=_CHAT_BODY("imessage"))

        captured = [call.args[1] for call in mock_capture.call_args_list]
        assert AnalyticsEvents.CHAT_MESSAGE_SUBMITTED not in captured
        assert AnalyticsEvents.CHAT_MESSAGE_REFUSED in captured
        refusal = next(
            call
            for call in mock_capture.call_args_list
            if call.args[1] == AnalyticsEvents.CHAT_MESSAGE_REFUSED
        )
        assert refusal.args[0] == "u1"
        assert refusal.args[2] == {"platform": "imessage", "reason": "plan_required"}

    @pytest.mark.parametrize(
        # A PAYING user reaches quota regardless of whether the platform is
        # premium-gated (imessage) or not (telegram).
        ("platform", "plan"),
        [("imessage", PlanType.PRO), ("telegram", PlanType.PRO)],
    )
    @patch("app.api.v1.endpoints.bot.BotService.enforce_rate_limit", new_callable=AsyncMock)
    @patch("app.api.v1.endpoints.bot.require_bot_api_key", new_callable=AsyncMock)
    async def test_chat_stream_plan_gate_passes_through_to_quota(
        self,
        mock_auth: AsyncMock,
        mock_limit: AsyncMock,
        client: AsyncClient,
        platform: str,
        plan: PlanType,
    ):
        with (
            patch(
                "app.utils.auth_utils.user_repository.get_by_platform_id",
                new_callable=AsyncMock,
                return_value=UserDocument(id="u1"),
            ),
            patch(PLAN_PATCH, new_callable=AsyncMock, return_value=plan),
            patch(
                "app.services.bot_service.enforce_tiered_limit",
                new_callable=AsyncMock,
                side_effect=HTTPException(status_code=418),
            ) as mock_tiered,
        ):
            response = await client.post(f"{BOT_BASE}/chat-stream", json=_CHAT_BODY(platform))

        assert response.status_code == 418
        mock_tiered.assert_awaited_once_with("u1", "chat_messages")

    @patch("app.api.v1.endpoints.bot.spawn_background_task", new=MagicMock())
    @patch("app.api.v1.endpoints.bot.run_chat_stream_background", new=AsyncMock())
    @patch(
        "app.api.v1.endpoints.bot.create_bot_session_token",
        new=MagicMock(return_value="tok"),
    )
    @patch(
        "app.utils.auth_utils.user_repository.get_by_platform_id",
        new_callable=AsyncMock,
    )
    @patch("app.api.v1.endpoints.bot.stream_manager")
    @patch("app.api.v1.endpoints.bot.BotService")
    @patch(
        "app.services.bot_service.BotService.load_conversation_history",
        new=AsyncMock(return_value=[]),
    )
    @patch("app.api.v1.endpoints.bot.capture_event")
    @patch("app.api.v1.endpoints.bot.require_bot_api_key", new=AsyncMock())
    async def test_a_served_turn_stamps_the_wide_event_with_who_where_and_outcome(
        self,
        mock_capture: MagicMock,
        mock_bot_svc: MagicMock,
        mock_sm: MagicMock,
        mock_get_user: AsyncMock,
    ):
        """user.id joins a bot turn to the same human's web traffic in Loki, and outcome separates served from gated turns."""
        mock_get_user.return_value = UserDocument(id="uid1")
        mock_bot_svc.enforce_rate_limit = AsyncMock()
        mock_bot_svc.get_or_create_session = AsyncMock(return_value="conv-1")
        mock_bot_svc.load_conversation_history = AsyncMock(return_value=[])
        mock_sm.start_stream = AsyncMock()

        body = BotChatRequest(message="hello", platform="discord", platform_user_id="u1")
        request = MagicMock()
        request.state = _make_request()

        async with log_context("bot_chat_stream_test"):
            response = await bot_chat_stream(request, body)
            event = dict(log.get())

        assert response.status_code == 200
        assert event["operation"] == "bot_chat_stream"
        assert event["user"] == {"id": "uid1"}
        assert event["platform"] == "discord"
        assert event["outcome"] == "success"

    @patch("app.api.v1.endpoints.bot.spawn_background_task", new=MagicMock())
    @patch("app.api.v1.endpoints.bot.run_chat_stream_background", new=AsyncMock())
    @patch(
        "app.api.v1.endpoints.bot.create_bot_session_token",
        new=MagicMock(return_value="tok"),
    )
    @patch(
        "app.utils.auth_utils.user_repository.get_by_platform_id",
        new_callable=AsyncMock,
    )
    @patch("app.api.v1.endpoints.bot.stream_manager")
    @patch("app.api.v1.endpoints.bot.BotService")
    @patch(
        "app.services.bot_service.BotService.load_conversation_history",
        new=AsyncMock(return_value=[]),
    )
    @patch("app.api.v1.endpoints.bot.capture_event")
    @patch("app.api.v1.endpoints.bot.require_bot_api_key", new=AsyncMock())
    async def test_enforce_rate_limit_receives_platform_and_platform_user_id_in_order(
        self,
        mock_capture: MagicMock,
        mock_bot_svc: MagicMock,
        mock_sm: MagicMock,
        mock_get_user: AsyncMock,
    ):
        """BotService.enforce_rate_limit is the flat per-platform anti-spam gate; it must see platform and platform_user_id positionally in that order."""
        mock_get_user.return_value = UserDocument(id="uid1")
        mock_bot_svc.enforce_rate_limit = AsyncMock()
        mock_bot_svc.get_or_create_session = AsyncMock(return_value="conv-1")
        mock_bot_svc.load_conversation_history = AsyncMock(return_value=[])
        mock_sm.start_stream = AsyncMock()

        body = BotChatRequest(message="hi", platform="whatsapp", platform_user_id="wa_777")
        request = MagicMock()
        request.state = _make_request()

        response = await bot_chat_stream(request, body)

        assert response.status_code == 200
        mock_bot_svc.enforce_rate_limit.assert_awaited_once_with("whatsapp", "wa_777")

    @patch("app.api.v1.endpoints.bot.spawn_background_task", new=MagicMock())
    @patch("app.api.v1.endpoints.bot.run_chat_stream_background", new=AsyncMock())
    @patch(
        "app.api.v1.endpoints.bot.create_bot_session_token",
        new=MagicMock(return_value="tok"),
    )
    @patch(
        "app.utils.auth_utils.user_repository.get_by_platform_id",
        new_callable=AsyncMock,
    )
    @patch("app.api.v1.endpoints.bot.stream_manager")
    @patch("app.api.v1.endpoints.bot.BotService")
    @patch(
        "app.services.bot_service.BotService.load_conversation_history",
        new=AsyncMock(return_value=[]),
    )
    @patch("app.api.v1.endpoints.bot.capture_event")
    @patch("app.api.v1.endpoints.bot.require_bot_api_key", new=AsyncMock())
    async def test_a_middleware_resolved_user_skips_the_platform_link_lookup(
        self,
        mock_capture: MagicMock,
        mock_bot_svc: MagicMock,
        mock_sm: MagicMock,
        mock_get_user: AsyncMock,
    ):
        """When BotAuthMiddleware already authenticated the user, the handler must use it as-is rather than re-resolving through PlatformLinkService."""
        mock_bot_svc.enforce_rate_limit = AsyncMock()
        mock_bot_svc.get_or_create_session = AsyncMock(return_value="conv-1")
        mock_bot_svc.load_conversation_history = AsyncMock(return_value=[])
        mock_sm.start_stream = AsyncMock()

        body = BotChatRequest(
            message="hi", platform="discord", platform_user_id="disc_1", channel_id="chan-9"
        )
        request = MagicMock()
        request.state = _make_request(
            user=AuthenticatedUser(user_id="uid_from_middleware"),
            authenticated=True,
        )

        response = await bot_chat_stream(request, body)

        assert response.status_code == 200
        mock_get_user.assert_not_awaited()
        mock_bot_svc.get_or_create_session.assert_awaited_once_with(
            "discord",
            "disc_1",
            "chan-9",
            AuthenticatedUser(user_id="uid_from_middleware"),
            is_dm=False,
        )

    @patch("app.api.v1.endpoints.bot.spawn_background_task", new=MagicMock())
    @patch("app.api.v1.endpoints.bot.run_chat_stream_background", new=AsyncMock())
    @patch(
        "app.api.v1.endpoints.bot.create_bot_session_token",
        new=MagicMock(return_value="tok"),
    )
    @patch(
        "app.utils.auth_utils.user_repository.get_by_platform_id",
        new_callable=AsyncMock,
    )
    @patch("app.api.v1.endpoints.bot.stream_manager")
    @patch("app.api.v1.endpoints.bot.BotService")
    @patch(
        "app.services.bot_service.BotService.load_conversation_history",
        new=AsyncMock(return_value=[]),
    )
    @patch("app.api.v1.endpoints.bot.capture_event")
    @patch("app.api.v1.endpoints.bot.require_bot_api_key", new=AsyncMock())
    async def test_a_state_user_without_authenticated_flag_still_falls_back(
        self,
        mock_capture: MagicMock,
        mock_bot_svc: MagicMock,
        mock_sm: MagicMock,
        mock_get_user: AsyncMock,
    ):
        """request.state.user alone is not enough — authenticated must also be true, or a stale/partial state object would be trusted."""
        mock_get_user.return_value = UserDocument(id="uid_from_lookup")
        mock_bot_svc.enforce_rate_limit = AsyncMock()
        mock_bot_svc.get_or_create_session = AsyncMock(return_value="conv-1")
        mock_bot_svc.load_conversation_history = AsyncMock(return_value=[])
        mock_sm.start_stream = AsyncMock()

        body = BotChatRequest(message="hi", platform="discord", platform_user_id="disc_1")
        request = MagicMock()
        request.state = _make_request(
            user=AuthenticatedUser(user_id="uid_from_middleware"),
            authenticated=False,
        )

        response = await bot_chat_stream(request, body)

        assert response.status_code == 200
        mock_get_user.assert_awaited_once_with("discord", "disc_1")

    @patch("app.api.v1.endpoints.bot.spawn_background_task", new=MagicMock())
    @patch("app.api.v1.endpoints.bot.run_chat_stream_background", new=AsyncMock())
    @patch(
        "app.api.v1.endpoints.bot.create_bot_session_token",
        new=MagicMock(return_value="tok"),
    )
    @patch(
        "app.utils.auth_utils.user_repository.get_by_platform_id",
        new_callable=AsyncMock,
    )
    @patch("app.api.v1.endpoints.bot.stream_manager")
    @patch("app.api.v1.endpoints.bot.BotService")
    @patch(
        "app.services.bot_service.BotService.load_conversation_history",
        new=AsyncMock(return_value=[]),
    )
    @patch("app.api.v1.endpoints.bot.capture_event", new=MagicMock())
    @patch("app.api.v1.endpoints.bot.require_bot_api_key", new=AsyncMock())
    async def test_a_state_with_no_authenticated_attribute_falls_back(
        self,
        mock_bot_svc: MagicMock,
        mock_sm: MagicMock,
        mock_get_user: AsyncMock,
    ):
        """A request no auth middleware touched has no authenticated flag at all; that is the unauthenticated case, not a crash."""
        mock_get_user.return_value = UserDocument(id="uid_from_lookup")
        mock_bot_svc.enforce_rate_limit = AsyncMock()
        mock_bot_svc.get_or_create_session = AsyncMock(return_value="conv-1")
        mock_bot_svc.load_conversation_history = AsyncMock(return_value=[])
        mock_sm.start_stream = AsyncMock()

        body = BotChatRequest(message="hi", platform="discord", platform_user_id="disc_1")
        request = MagicMock()
        request.state = _make_request(user=AuthenticatedUser(user_id="uid_from_middleware"))
        del request.state.authenticated

        response = await bot_chat_stream(request, body)

        assert response.status_code == 200
        mock_get_user.assert_awaited_once_with("discord", "disc_1")

    @patch("app.api.v1.endpoints.bot.spawn_background_task")
    @patch("app.api.v1.endpoints.bot.run_chat_stream_background")
    @patch("app.api.v1.endpoints.bot.create_bot_session_token")
    @patch(
        "app.utils.auth_utils.user_repository.get_by_platform_id",
        new_callable=AsyncMock,
    )
    @patch("app.api.v1.endpoints.bot.stream_manager")
    @patch("app.api.v1.endpoints.bot.BotService")
    @patch(
        "app.services.bot_service.BotService.load_conversation_history",
        new=AsyncMock(return_value=[]),
    )
    @patch("app.api.v1.endpoints.bot.capture_event", new=MagicMock())
    @patch("app.api.v1.endpoints.bot.require_bot_api_key", new=AsyncMock())
    async def test_the_background_stream_is_wired_with_the_exact_session_and_body(
        self,
        mock_bot_svc: MagicMock,
        mock_sm: MagicMock,
        mock_get_user: AsyncMock,
        mock_session_token: MagicMock,
        mock_run_background: MagicMock,
        mock_spawn: MagicMock,
    ):
        """A wrong platform, user, or conversation id here silently streams to (or authenticates) the wrong session."""
        mock_bot_svc.enforce_rate_limit = AsyncMock()
        mock_bot_svc.get_or_create_session = AsyncMock(return_value="conv-77")
        mock_bot_svc.load_conversation_history = AsyncMock(return_value=[])
        mock_sm.start_stream = AsyncMock()
        mock_get_user.return_value = UserDocument(id="uid-1")
        mock_session_token.return_value = "tok-77"

        body = BotChatRequest(message="hello", platform="telegram", platform_user_id="tg_1")
        request = MagicMock()
        request.state = _make_request()

        response = await bot_chat_stream(request, body)

        assert response.status_code == 200
        mock_session_token.assert_called_once_with(
            user_id="uid-1",
            platform="telegram",
            platform_user_id="tg_1",
            expires_minutes=15,
        )
        mock_sm.start_stream.assert_awaited_once()
        start_stream_call = mock_sm.start_stream.call_args
        stream_id = start_stream_call.args[0]
        assert str(UUID(stream_id)) == stream_id
        assert start_stream_call.args[1:] == ("conv-77", "uid-1")

        run_call = mock_run_background.call_args
        assert run_call.kwargs["stream_id"] == stream_id
        assert run_call.kwargs["conversation_id"] == "conv-77"
        assert run_call.kwargs["source"] == "telegram"
        assert run_call.kwargs["user"] == AuthenticatedUser(
            user_id="uid-1", auth_provider="bot:telegram", bot_authenticated=True
        )
        message_request = run_call.kwargs["body"]
        assert message_request.message == "hello"
        assert message_request.conversation_id == "conv-77"
        spawn_call = mock_spawn.call_args
        assert spawn_call.kwargs["on_done"].__name__ == "_log_stream_failure"


# ---------------------------------------------------------------------------
# The streamed body of POST /bot/chat-stream — translation + keepalive
# ---------------------------------------------------------------------------


class TestBotChatStreamBody:
    """What actually reaches the bot over the wire.

    The tests above stop at the gates (auth, plan, quota, analytics); none of
    them read the response body, so the translator was uncovered. That is the
    gap that let the 2026-08-18 outage ship: the translator drops every
    web-only frame, and nothing checked that anything at all still reached the
    socket while it did so.

    with_heartbeat is exercised for real here — only its interval is shortened,
    so the padding behaviour under test is the shipped implementation.
    """

    @staticmethod
    def _fast_heartbeat(frames: AsyncGenerator[str, None]) -> AsyncGenerator[str, None]:
        return with_heartbeat(frames, interval=0.05)

    @staticmethod
    async def _collect(client: AsyncClient, frames: AsyncGenerator[str, None]) -> str:
        with (
            patch("app.api.v1.endpoints.bot.require_bot_api_key", new=AsyncMock()),
            patch("app.api.v1.endpoints.bot.spawn_background_task", new=MagicMock()),
            patch("app.api.v1.endpoints.bot.run_chat_stream_background", new=AsyncMock()),
            patch(
                "app.api.v1.endpoints.bot.create_bot_session_token",
                new=MagicMock(return_value="tok"),
            ),
            patch(
                "app.api.v1.endpoints.bot.with_heartbeat",
                new=TestBotChatStreamBody._fast_heartbeat,
            ),
            patch(
                "app.utils.auth_utils.user_repository.get_by_platform_id",
                new=AsyncMock(return_value=UserDocument(id="uid1")),
            ),
            patch("app.api.v1.endpoints.bot.BotService") as bot_svc,
            patch(
                "app.services.bot_service.BotService.load_conversation_history",
                new=AsyncMock(return_value=[]),
            ),
            patch("app.api.v1.endpoints.bot.capture_event", new=MagicMock()),
            patch("app.api.v1.endpoints.bot.stream_manager") as sm,
        ):
            bot_svc.enforce_rate_limit = AsyncMock()
            bot_svc.get_or_create_session = AsyncMock(return_value="conv-1")
            bot_svc.load_conversation_history = AsyncMock(return_value=[])
            sm.start_stream = AsyncMock()
            sm.subscribe_stream.return_value = frames

            response = await client.post(f"{BOT_BASE}/chat-stream", json=_CHAT_BODY("discord"))
            assert response.status_code == 200
            # Not decoration: a bot client parses this stream as SSE and will
            # not read a body served under any other media type.
            assert response.headers["content-type"].startswith("text/event-stream")
            return (await response.aread()).decode()

    async def test_a_silent_stretch_of_web_only_frames_still_reaches_the_socket(
        self, client: AsyncClient
    ):
        """The regression: tool work with no frames leaves the connection quiet, and a proxy (nginx's stock proxy_read_timeout is 60s) kills it."""

        async def tool_work() -> AsyncGenerator[str, None]:
            for i in range(3):
                await asyncio.sleep(0.12)
                yield f'data: {{"tool_data": {{"i": {i}}}}}\n\n'
            yield "data: [DONE]\n\n"

        body = await self._collect(client, tool_work())

        assert '"keepalive"' in body, f"nothing kept the socket alive: {body!r}"
        assert "tool_data" not in body, "web-only frames must not reach the bot"

    async def test_text_frames_are_translated_and_the_turn_closes_with_done(
        self, client: AsyncClient
    ):
        async def answer() -> AsyncGenerator[str, None]:
            yield 'data: {"response": "hello "}\n\n'
            yield 'data: {"response": "world"}\n\n'
            yield "data: [DONE]\n\n"

        body = await self._collect(client, answer())

        assert '"text": "hello "' in body
        assert '"text": "world"' in body
        assert '"done": true' in body
        assert '"conversation_id": "conv-1"' in body

    async def test_a_rate_limit_card_reaches_the_bot_as_a_notice_for_this_user(
        self, client: AsyncClient
    ):
        """The web-only rate-limit card converts to a typed notice frame, never reply text, and is minted for the resolved user so its checkout link attributes correctly."""

        async def walled() -> AsyncGenerator[str, None]:
            yield (
                'data: {"tool_data": {"tool_name": "rate_limit_data",'
                ' "data": {"feature": "chat_messages", "current_plan": "free"}}}\n\n'
            )
            yield "data: [DONE]\n\n"

        mint = AsyncMock(return_value="https://pay.example/checkout")
        with patch("app.api.v1.endpoints.bot._bot_upgrade_url", mint):
            body = await self._collect(client, walled())

        # The checkout is minted for the user the request resolved to — a wrong
        # id here bills (or credits) somebody else's account.
        mint.assert_awaited_once_with("uid1")
        frames = [
            json.loads(line[len("data: ") :])
            for line in body.splitlines()
            if line.startswith("data: ")
        ]
        assert {
            "notice": {
                "text": "\u23f3 You've reached your chat messages limit. Please try again "
                "later. [Upgrade to Pro](https://pay.example/checkout) for higher limits."
            }
        } in frames
        assert 'data: {"text"' not in body

    async def test_a_non_rate_limit_card_yields_no_notice_frame(self, client: AsyncClient):
        async def other_card() -> AsyncGenerator[str, None]:
            yield 'data: {"tool_data": {"tool_name": "memory_data", "data": {}}}\n\n'
            yield "data: [DONE]\n\n"

        mint = AsyncMock(return_value=None)
        with patch("app.api.v1.endpoints.bot._bot_rate_limit_notice", mint):
            body = await self._collect(client, other_card())

        card, upgrade_url = mint.await_args.args
        assert card == BotWebStreamPayload.model_validate(
            {"tool_data": {"tool_name": "memory_data", "data": {}}}
        )
        assert callable(upgrade_url)
        assert '"notice"' not in body

    async def test_a_message_boundary_reaches_the_bot_intact(self, client: AsyncClient):
        """A bot needs this frame twice: to close a bubble, and, when discarded, to take back an already-shown handoff preamble."""

        async def retracted_then_replaced() -> AsyncGenerator[str, None]:
            yield 'data: {"response": "let me get that set up"}\n\n'
            yield 'data: {"message_boundary": {"message_id": "m1", "discarded": true}}\n\n'
            yield 'data: {"response": "all set up now."}\n\n'
            yield "data: [DONE]\n\n"

        body = await self._collect(client, retracted_then_replaced())

        frames = [
            json.loads(line[len("data: ") :])
            for line in body.splitlines()
            if line.startswith("data: ")
        ]
        assert {"message_boundary": {"message_id": "m1", "discarded": True}} in frames
        # The boundary is a frame of its own, never reply text — and it must not
        # end the turn: the replacement message comes after it.
        assert {"text": "all set up now."} in frames
        assert {"done": True, "conversation_id": "conv-1"} in frames

    async def test_the_session_token_is_the_first_thing_the_bot_receives(self, client: AsyncClient):
        """The bot stores this to authenticate follow-up calls for the turn."""

        async def answer() -> AsyncGenerator[str, None]:
            yield "data: [DONE]\n\n"

        body = await self._collect(client, answer())

        assert body.index('"session_token": "tok"') < body.index('"done"')

    async def test_a_disconnected_client_stops_forwarding_before_any_frame(
        self, client: AsyncClient
    ):
        """request.is_disconnected() is checked before each chunk; a client gone before the first gets neither text nor done, though the background task still persists the result."""

        async def answer() -> AsyncGenerator[str, None]:
            yield 'data: {"response": "too late"}\n\n'
            yield "data: [DONE]\n\n"

        with patch("starlette.requests.Request.is_disconnected", new=AsyncMock(return_value=True)):
            body = await self._collect(client, answer())

        assert '"text"' not in body
        assert '"done"' not in body
        assert '"session_token": "tok"' in body

    async def test_a_subscription_error_yields_a_generic_error_frame(self, client: AsyncClient):
        """An exception from subscribe_stream must still end the turn with a renderable frame, not a silently dead connection."""

        async def broken() -> AsyncGenerator[str, None]:
            yield 'data: {"response": "partial"}\n\n'
            raise RuntimeError("redis blew up")

        body = await self._collect(client, broken())

        assert '"text": "partial"' in body
        assert '"error": "Stream error occurred"' in body

    @patch("app.api.v1.endpoints.bot.spawn_background_task", new=MagicMock())
    @patch("app.api.v1.endpoints.bot.run_chat_stream_background", new=AsyncMock())
    @patch(
        "app.api.v1.endpoints.bot.create_bot_session_token",
        new=MagicMock(return_value="tok"),
    )
    @patch(
        "app.utils.auth_utils.user_repository.get_by_platform_id",
        new_callable=AsyncMock,
    )
    @patch("app.api.v1.endpoints.bot.stream_manager")
    @patch("app.api.v1.endpoints.bot.BotService")
    @patch(
        "app.services.bot_service.BotService.load_conversation_history",
        new=AsyncMock(return_value=[]),
    )
    @patch("app.api.v1.endpoints.bot.require_bot_api_key", new=AsyncMock())
    async def test_message_request_is_built_for_the_resolved_user(
        self,
        mock_bot_svc: MagicMock,
        mock_sm: MagicMock,
        mock_get_user: AsyncMock,
        client: AsyncClient,
    ):
        """_build_bot_message_request's third argument is whose conversation history loads; swapping it for None or another user's id would silently load the wrong (or no) history."""
        mock_get_user.return_value = UserDocument(id="uid1")
        mock_bot_svc.enforce_rate_limit = AsyncMock()
        mock_bot_svc.get_or_create_session = AsyncMock(return_value="conv-1")
        mock_sm.start_stream = AsyncMock()

        async def _empty_stream():
            if False:  # pragma: no cover
                yield

        mock_sm.subscribe_stream.return_value = _empty_stream()

        built = AsyncMock(return_value=MagicMock())
        with patch("app.api.v1.endpoints.bot.build_bot_message_request", built):
            response = await client.post(f"{BOT_BASE}/chat-stream", json=_CHAT_BODY("discord"))
            assert response.status_code == 200
            await response.aread()

        built.assert_awaited_once()
        _body_arg, conversation_id_arg, user_id_arg = built.await_args.args
        assert conversation_id_arg == "conv-1"
        assert user_id_arg == "uid1"

    @patch("app.api.v1.endpoints.bot.spawn_background_task", new=MagicMock())
    @patch("app.api.v1.endpoints.bot.run_chat_stream_background", new=AsyncMock())
    @patch(
        "app.api.v1.endpoints.bot.create_bot_session_token",
        new=MagicMock(return_value="tok"),
    )
    @patch(
        "app.utils.auth_utils.user_repository.get_by_platform_id",
        new_callable=AsyncMock,
    )
    @patch("app.api.v1.endpoints.bot.stream_manager")
    @patch("app.api.v1.endpoints.bot.BotService")
    @patch(
        "app.services.bot_service.BotService.load_conversation_history",
        new=AsyncMock(return_value=[]),
    )
    @patch("app.api.v1.endpoints.bot.require_bot_api_key", new=AsyncMock())
    async def test_background_failure_logger_is_built_for_this_stream_and_conversation(
        self,
        mock_bot_svc: MagicMock,
        mock_sm: MagicMock,
        mock_get_user: AsyncMock,
        client: AsyncClient,
    ):
        """_bot_stream_failure_logger's two args identify which stream and conversation a background crash belongs to; swapping either for None makes a failure unattributable."""
        mock_get_user.return_value = UserDocument(id="uid1")
        mock_bot_svc.enforce_rate_limit = AsyncMock()
        mock_bot_svc.get_or_create_session = AsyncMock(return_value="conv-1")
        mock_bot_svc.load_conversation_history = AsyncMock(return_value=[])
        mock_sm.start_stream = AsyncMock()

        async def _empty_stream():
            if False:  # pragma: no cover
                yield

        mock_sm.subscribe_stream.return_value = _empty_stream()

        logger_factory = MagicMock(return_value=MagicMock())
        with patch("app.api.v1.endpoints.bot._bot_stream_failure_logger", logger_factory):
            response = await client.post(f"{BOT_BASE}/chat-stream", json=_CHAT_BODY("discord"))
            assert response.status_code == 200
            await response.aread()

        logger_factory.assert_called_once()
        called_stream_id, called_conversation_id = logger_factory.call_args.args
        assert called_conversation_id == "conv-1"
        # stream_id is a fresh uuid4 per request — pin it to the id the stream
        # was actually started under, not just "truthy", so a swap for None
        # (or any other value) is caught.
        started_stream_id = mock_sm.start_stream.await_args.args[0]
        assert called_stream_id == started_stream_id
        assert called_stream_id is not None


# ---------------------------------------------------------------------------
# POST /bot/transcribe — voice / audio transcription for bot adapters
# ---------------------------------------------------------------------------


class TestBotTranscribe:
    """POST /api/v1/bot/transcribe."""

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

    # Mime allowlist and Whisper invocation are covered in
    # test_audio_transcription_service.py; only the route-level success path
    # is exercised here.

    @patch("app.api.v1.endpoints.bot.capture_event")
    @patch("app.api.v1.endpoints.bot.require_bot_api_key", new_callable=AsyncMock)
    async def test_a_paywalled_voice_note_stamps_the_outcome_on_its_own_event(
        self,
        mock_auth: AsyncMock,
        mock_capture: MagicMock,
        client: AsyncClient,
    ):
        """A refused transcribe and a served one must leave different events, since require_active_subscription stamps the gate's own event, not this route's."""
        with (
            patch(
                "app.decorators.entitlements.payment_service.get_cached_plan_type",
                new_callable=AsyncMock,
                return_value=PlanType.FREE,
            ),
            patch("app.api.v1.endpoints.bot.log") as mock_log,
        ):
            response = await client.post(
                f"{BOT_BASE}/transcribe",
                files={"file": ("voice.ogg", b"fake-audio-bytes", "audio/ogg")},
            )

        assert response.status_code == 402
        assert mock_log.set.call_args_list[-1].kwargs == {
            "outcome": "subscription_required",
            "reason": "subscription_required",
        }

    @patch("app.api.v1.endpoints.bot.capture_event")
    @patch(
        "app.api.v1.endpoints.bot.transcribe_audio",
        new_callable=AsyncMock,
        return_value="hello there",
    )
    @patch("app.api.v1.endpoints.bot.require_bot_api_key", new_callable=AsyncMock)
    async def test_a_served_voice_note_stamps_the_opposite_outcome(
        self,
        mock_auth: AsyncMock,
        mock_transcribe: AsyncMock,
        mock_capture: MagicMock,
        client: AsyncClient,
    ):
        """Both sides of the decision, or the ratio is uncomputable."""
        with (
            patch(
                "app.decorators.entitlements.payment_service.get_cached_plan_type",
                new_callable=AsyncMock,
                return_value=PlanType.PRO,
            ),
            patch("app.api.v1.endpoints.bot.log") as mock_log,
        ):
            response = await client.post(
                f"{BOT_BASE}/transcribe",
                files={"file": ("voice.ogg", b"fake-audio-bytes", "audio/ogg")},
            )

        assert response.status_code == 200
        assert mock_log.set.call_args_list[-1].kwargs == {"outcome": "transcribed"}

    @patch("app.api.v1.endpoints.bot.capture_event")
    @patch(
        "app.api.v1.endpoints.bot.transcribe_audio",
        new_callable=AsyncMock,
        return_value="hello there",
    )
    @patch("app.api.v1.endpoints.bot.require_bot_api_key", new_callable=AsyncMock)
    async def test_a_voice_note_stamps_its_operation_and_caller(
        self,
        mock_auth: AsyncMock,
        mock_transcribe: AsyncMock,
        mock_capture: MagicMock,
        client: AsyncClient,
        fake_user: AuthenticatedUser,
    ):
        with (
            patch(
                "app.decorators.entitlements.payment_service.get_cached_plan_type",
                new_callable=AsyncMock,
                return_value=PlanType.PRO,
            ),
            patch("app.api.v1.endpoints.bot.log") as mock_log,
        ):
            response = await client.post(
                f"{BOT_BASE}/transcribe",
                files={"file": ("voice.ogg", b"fake-audio-bytes", "audio/ogg")},
            )

        assert response.status_code == 200
        mock_log.set.assert_any_call(
            operation="bot_transcribe_audio", user={"id": fake_user.user_id}
        )

    @patch("app.api.v1.endpoints.bot.capture_event")
    @patch(
        "app.api.v1.endpoints.bot.transcribe_audio",
        new_callable=AsyncMock,
        return_value="hello there",
    )
    @patch("app.api.v1.endpoints.bot.require_bot_api_key", new_callable=AsyncMock)
    async def test_transcribe_success_captures_shape_not_content(
        self,
        mock_auth: AsyncMock,
        mock_transcribe: AsyncMock,
        mock_capture: MagicMock,
        client: AsyncClient,
        fake_user: dict,
    ):
        """The event carries sizes, never the transcript — it is user speech."""
        audio = b"fake-audio-bytes"
        response = await client.post(
            f"{BOT_BASE}/transcribe",
            files={"file": ("voice.ogg", audio, "audio/ogg")},
        )

        assert response.status_code == 200
        assert response.json()["text"] == "hello there"
        mock_capture.assert_called_once()
        args = mock_capture.call_args.args
        # args[0] is the distinct_id: bot routes are auth-excluded, so a
        # wrong or None id lands the event on an anonymous profile. Five
        # mutants of this argument survived until asserted.
        assert args[0] == fake_user.user_id
        assert args[1] == AnalyticsEvents.BOT_AUDIO_TRANSCRIBED
        assert args[2] == {
            "audio_bytes": len(audio),
            "transcript_length": len("hello there"),
        }
        assert "hello there" not in str(args[2])

    @patch(
        "app.api.v1.endpoints.bot.transcribe_audio",
        new_callable=AsyncMock,
        return_value="hello there",
    )
    @patch("app.api.v1.endpoints.bot.require_bot_api_key", new_callable=AsyncMock)
    async def test_transcribe_free_user_gets_402_and_never_transcribes(
        self,
        mock_auth: AsyncMock,
        mock_transcribe: AsyncMock,
        client: AsyncClient,
    ):
        """Transcription is Whisper spend, so a linked-but-unsubscribed user is turned away, gated imperatively so the bot API key is verified first."""
        with patch(PLAN_PATCH, new_callable=AsyncMock, return_value=PlanType.FREE):
            response = await client.post(
                f"{BOT_BASE}/transcribe",
                files={"file": ("voice.ogg", b"fake-audio-bytes", "audio/ogg")},
            )

        assert response.status_code == 402
        assert response.json()["code"] == "subscription_required"
        mock_transcribe.assert_not_called()

    @patch(
        "app.api.v1.endpoints.bot.transcribe_audio",
        new_callable=AsyncMock,
        return_value="hello there",
    )
    @patch("app.api.v1.endpoints.bot.require_bot_api_key", new_callable=AsyncMock)
    async def test_the_gate_is_asked_about_this_caller_and_this_feature(
        self,
        mock_auth: AsyncMock,
        mock_transcribe: AsyncMock,
        client: AsyncClient,
        fake_user: dict,
    ):
        """The user id makes the gate a gate (asked about nobody, every caller passes), and feature is what the 402 and its metrics key on."""
        with patch(
            "app.api.v1.endpoints.bot.require_active_subscription", new_callable=AsyncMock
        ) as mock_gate:
            response = await client.post(
                f"{BOT_BASE}/transcribe",
                files={"file": ("voice.ogg", b"fake-audio-bytes", "audio/ogg")},
            )

        assert response.status_code == 200
        mock_gate.assert_awaited_once_with(str(fake_user.user_id), feature="bot_transcribe")

    @patch("app.api.v1.endpoints.bot.capture_event")
    @patch(
        "app.api.v1.endpoints.bot.transcribe_audio",
        new_callable=AsyncMock,
        side_effect=RuntimeError("whisper down"),
    )
    @patch("app.api.v1.endpoints.bot.require_bot_api_key", new_callable=AsyncMock)
    async def test_transcribe_failure_captures_nothing(
        self,
        mock_auth: AsyncMock,
        mock_transcribe: AsyncMock,
        mock_capture: MagicMock,
        client: AsyncClient,
    ):
        """Capturing on entry would count every failed transcription as a use."""
        response = await client.post(
            f"{BOT_BASE}/transcribe",
            files={"file": ("voice.ogg", b"fake-audio-bytes", "audio/ogg")},
        )

        assert response.status_code == 502
        mock_capture.assert_not_called()


# ---------------------------------------------------------------------------
# Refusals: the body the bots branch on, and the reason on the wide event
# ---------------------------------------------------------------------------

_LINKED_HEADERS = {"X-Bot-Platform": "discord", "X-Bot-Platform-User-Id": "u1"}
_VOICE_NOTE = {"file": ("voice.ogg", b"fake-audio-bytes", "audio/ogg")}


@pytest.fixture
def bot_log():
    with patch("app.api.v1.endpoints.bot.log") as mock_log:
        yield mock_log


@pytest.fixture
def api_key_ok():
    with patch("app.api.v1.endpoints.bot.require_bot_api_key", new_callable=AsyncMock):
        yield


@pytest.fixture
def unlinked():
    with patch(
        "app.utils.auth_utils.user_repository.get_by_platform_id",
        new_callable=AsyncMock,
        return_value=None,
    ):
        yield


def _chunked_multipart(files: dict) -> tuple[dict[str, str], AsyncGenerator[bytes]]:
    """Encode files as multipart and stream them without a Content-Length, as a chunked client does."""
    encoded = httpx.Request("POST", "http://x", files=files)
    body = encoded.read()

    async def chunks() -> AsyncGenerator[bytes]:
        yield body

    return {"content-type": encoded.headers["content-type"]}, chunks()


class TestBotRefusalsSayWhy:
    """The bots branch on a refusal's code and show its message; ops query the wide event's reason.

    A refusal that loses either still returns the right status, so the status alone proves nothing.
    """

    async def test_a_missing_bot_key_is_refused_with_its_code(
        self, bot_log: MagicMock, client: AsyncClient
    ):
        response = await client.post(f"{BOT_BASE}/unlink", headers=_LINKED_HEADERS)

        assert response.status_code == 401
        assert response.json() == {
            "message": "Invalid or missing bot API key",
            "code": "BOT_API_KEY_INVALID",
        }
        bot_log.fail.assert_called_once_with("bot_api_key_invalid")

    async def test_an_unlinked_account_is_told_to_link_before_resetting(
        self, bot_log: MagicMock, api_key_ok: None, unlinked: None, client: AsyncClient
    ):
        response = await client.post(
            f"{BOT_BASE}/reset-session",
            json={"platform": "discord", "platform_user_id": "u1", "channel_id": "ch1"},
        )

        assert response.status_code == 401
        assert response.json() == {
            "message": "This platform account is not linked to a GAIA account.",
            "code": "BOT_ACCOUNT_NOT_LINKED",
        }
        bot_log.fail.assert_called_once_with("account_not_linked")

    async def test_an_unknown_platform_is_refused(
        self, bot_log: MagicMock, api_key_ok: None, client: AsyncClient
    ):
        response = await client.post(
            f"{BOT_BASE}/unlink",
            headers={"X-Bot-Platform": "badplatform", "X-Bot-Platform-User-Id": "u1"},
        )

        assert response.status_code == 400
        assert response.json() == {"message": "Invalid platform"}
        bot_log.fail.assert_called_once_with("invalid_platform")

    async def test_an_unlink_without_its_platform_headers_is_refused(
        self, bot_log: MagicMock, api_key_ok: None, client: AsyncClient
    ):
        response = await client.post(f"{BOT_BASE}/unlink")

        assert response.status_code == 400
        assert response.json() == {"message": "Missing platform headers"}
        bot_log.fail.assert_called_once_with("missing_platform_headers")

    async def test_unlinking_an_account_that_was_never_linked_is_a_not_found(
        self, bot_log: MagicMock, api_key_ok: None, unlinked: None, client: AsyncClient
    ):
        response = await client.post(f"{BOT_BASE}/unlink", headers=_LINKED_HEADERS)

        assert response.status_code == 404
        assert response.json() == {
            "message": "Account not linked",
            "code": "BOT_ACCOUNT_NOT_LINKED",
        }
        bot_log.fail.assert_called_once_with("account_not_linked")

    async def test_an_unlinked_chat_turn_is_stamped_not_authenticated(
        self, bot_log: MagicMock, api_key_ok: None, unlinked: None, client: AsyncClient
    ):
        with patch(
            "app.api.v1.endpoints.bot.BotService.enforce_rate_limit", new_callable=AsyncMock
        ):
            await client.post(f"{BOT_BASE}/chat-stream", json=_CHAT_BODY("discord"))

        bot_log.set.assert_any_call(outcome="not_authenticated", reason="account_not_linked")

    async def test_a_reset_session_is_stamped_with_the_linked_user(
        self, bot_log: MagicMock, api_key_ok: None, client: AsyncClient
    ):
        with (
            patch(
                "app.utils.auth_utils.user_repository.get_by_platform_id",
                new_callable=AsyncMock,
                return_value=UserDocument(id="uid1"),
            ),
            patch("app.api.v1.endpoints.bot.BotService") as bot_service,
            patch("app.api.v1.endpoints.bot.capture_event"),
        ):
            bot_service.reset_session = AsyncMock(return_value="new-convo-id")
            response = await client.post(
                f"{BOT_BASE}/reset-session",
                json={"platform": "discord", "platform_user_id": "u1", "channel_id": "ch1"},
            )

        assert response.status_code == 200
        bot_log.set.assert_any_call(user={"id": "uid1"})


class TestBotTranscribeRefusals:
    """A voice note the API will not transcribe is refused before any Whisper spend, with why."""

    async def test_a_declared_oversize_upload_is_refused_with_the_limit_in_megabytes(
        self, bot_log: MagicMock, api_key_ok: None, client: AsyncClient
    ):
        with (
            patch("app.api.v1.endpoints.bot.MAX_AUDIO_BYTES", 1024 * 1024),
            patch("app.api.v1.endpoints.bot.transcribe_audio", new_callable=AsyncMock) as whisper,
        ):
            response = await client.post(
                f"{BOT_BASE}/transcribe",
                files={"file": ("voice.ogg", b"x" * (1024 * 1024 + 1), "audio/ogg")},
            )

        assert response.status_code == 413
        assert response.json() == {"message": "Audio exceeds the 1 MB limit."}
        bot_log.fail.assert_called_once_with("audio_too_large")
        whisper.assert_not_awaited()

    async def test_an_oversize_upload_with_no_declared_length_is_refused_once_read(
        self, bot_log: MagicMock, api_key_ok: None, client: AsyncClient
    ):
        headers, body = _chunked_multipart(
            {"file": ("voice.ogg", b"x" * (2 * 1024 * 1024 + 1), "audio/ogg")}
        )
        with (
            patch("app.api.v1.endpoints.bot.MAX_AUDIO_BYTES", 2 * 1024 * 1024),
            patch("app.api.v1.endpoints.bot.transcribe_audio", new_callable=AsyncMock) as whisper,
        ):
            response = await client.post(f"{BOT_BASE}/transcribe", headers=headers, content=body)

        assert response.status_code == 413
        assert response.json() == {"message": "Audio exceeds the 2 MB limit."}
        bot_log.fail.assert_called_once_with("audio_too_large")
        whisper.assert_not_awaited()

    async def test_the_validators_size_verdict_is_a_413_in_its_own_words(
        self, bot_log: MagicMock, api_key_ok: None, client: AsyncClient
    ):
        with patch(
            "app.api.v1.endpoints.bot.validate_audio_payload",
            side_effect=bot_module.AudioTooLargeError("Audio is 9 bytes; max supported is 8."),
        ):
            response = await client.post(f"{BOT_BASE}/transcribe", files=_VOICE_NOTE)

        assert response.status_code == 413
        assert response.json() == {"message": "Audio is 9 bytes; max supported is 8."}
        bot_log.fail.assert_called_once_with("audio_too_large")

    async def test_a_non_audio_upload_is_an_unsupported_format(
        self, bot_log: MagicMock, api_key_ok: None, client: AsyncClient
    ):
        response = await client.post(
            f"{BOT_BASE}/transcribe", files={"file": ("notes.txt", b"hello", "text/plain")}
        )

        assert response.status_code == 415
        assert response.json() == {"message": "Unsupported audio content type: text/plain."}
        bot_log.fail.assert_called_once_with("unsupported_audio_format")

    async def test_a_provider_failure_is_a_502_that_leaks_nothing(
        self, bot_log: MagicMock, api_key_ok: None, client: AsyncClient
    ):
        with patch(
            "app.api.v1.endpoints.bot.transcribe_audio",
            new_callable=AsyncMock,
            side_effect=RuntimeError("openai key sk-live-abc rejected"),
        ):
            response = await client.post(f"{BOT_BASE}/transcribe", files=_VOICE_NOTE)

        assert response.status_code == 502
        assert response.json() == {"message": "Transcription failed"}
        bot_log.fail.assert_called_once_with("transcription_failed")


# ---------------------------------------------------------------------------
# BotChatRequest — file attachments
# ---------------------------------------------------------------------------


class TestBotChatRequestFiles:
    """Pydantic validation for the new file_ids / file_data fields."""

    def test_accepts_file_ids_and_data(self):
        from app.models.bot_models import BotChatRequest

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
        from app.models.bot_models import BotChatRequest

        req = BotChatRequest(message="hi", platform="whatsapp", platform_user_id="123")
        assert req.file_ids is None
        assert req.file_data is None


# ---------------------------------------------------------------------------
# POST /bot/chat-stream — plan metering
# ---------------------------------------------------------------------------


class TestBotChatStreamMetering:
    """A bot turn must charge the same plan quota as a web chat turn.

    bot_chat_stream resolves its caller from a platform link inside the body,
    so it can never be metered by @tiered_rate_limit. Before it called
    enforce_tiered_limit explicitly it went entirely unmetered: a free user had
    no message limit through Telegram/Discord/Slack/WhatsApp, and because
    record_activity fires from the limiter, bot turns never reached
    usage_daily either — leaving those users off the heatmap, streak and badge.
    """

    @staticmethod
    def _patches(limiter: AsyncMock):
        return (
            patch("app.api.v1.endpoints.bot.require_bot_api_key", new_callable=AsyncMock),
            patch(
                "app.api.v1.endpoints.bot.BotService.enforce_rate_limit",
                new_callable=AsyncMock,
            ),
            patch(
                "app.utils.auth_utils.user_repository.get_by_platform_id",
                new_callable=AsyncMock,
                return_value=UserDocument(id="u_bot_1", email="bot@gaia.local"),
            ),
            patch(
                "app.api.v1.endpoints.bot.BotService.get_or_create_session",
                new_callable=AsyncMock,
                return_value="conv_1",
            ),
            patch(
                "app.api.v1.endpoints.bot.BotService.load_conversation_history",
                new_callable=AsyncMock,
                return_value=[],
            ),
            patch("app.api.v1.endpoints.bot.stream_manager", new_callable=MagicMock),
            patch("app.api.v1.endpoints.bot.run_chat_stream_background"),
            patch("app.decorators.rate_limiting.tiered_limiter.check_and_increment", limiter),
        )

    async def test_a_bot_turn_charges_the_chat_messages_quota(self, client: AsyncClient):
        limiter = AsyncMock(return_value={})
        p = self._patches(limiter)
        with p[0], p[1], p[2], p[3], p[4], p[5], p[6], p[7]:
            await client.post(
                f"{BOT_BASE}/chat-stream",
                json={
                    "message": "hi from telegram",
                    "platform": "telegram",
                    "platform_user_id": "tg_42",
                },
            )

        limiter.assert_awaited_once()
        assert limiter.await_args.kwargs["feature_key"] == "chat_messages"
        assert limiter.await_args.kwargs["user_id"] == "u_bot_1"

    async def test_a_bot_turn_checks_the_daily_cost_wall_too(self, client: AsyncClient):
        """Web chat charges two walls — message count and daily cost — metering only the first left a bot user mid-stream instead of cleanly refused."""
        limiter = AsyncMock(return_value={})
        cost_wall = AsyncMock()
        p = self._patches(limiter)
        with (
            p[0],
            p[1],
            p[2],
            p[3],
            p[4],
            p[5],
            p[6],
            p[7],
            patch("app.services.bot_service.enforce_daily_cost_budget", cost_wall),
        ):
            await client.post(
                f"{BOT_BASE}/chat-stream",
                json={
                    "message": "hi",
                    "platform": "telegram",
                    "platform_user_id": "tg_42",
                },
            )

        cost_wall.assert_awaited_once_with("u_bot_1", feature_key="chat_messages")

    async def test_an_unlinked_platform_user_is_not_charged(self, client: AsyncClient):
        """No GAIA account behind the platform id — there is nobody to bill."""
        limiter = AsyncMock(return_value={})
        p = self._patches(limiter)
        with (
            p[0],
            p[1],
            patch(
                "app.utils.auth_utils.user_repository.get_by_platform_id",
                new_callable=AsyncMock,
                return_value=None,
            ),
            p[3],
            p[4],
            p[5],
            p[6],
            p[7],
        ):
            await client.post(
                f"{BOT_BASE}/chat-stream",
                json={
                    "message": "hi",
                    "platform": "telegram",
                    "platform_user_id": "tg_unlinked",
                },
            )

        limiter.assert_not_awaited()


# ---------------------------------------------------------------------------
# POST /bot/chat-stream — the paid-only gate
# ---------------------------------------------------------------------------


@pytest.fixture
def upgrade_link_window_open():
    """Open the once-per-window mint gate, so link tests are about the link.

    _bot_upgrade_url mints once per user per window via a Redis SET NX EX;
    without this, a repeat user id falls through to the pricing-page branch
    and passes for the wrong reason.
    """
    with patch(
        "app.api.v1.endpoints.bot._may_mint_bot_upgrade_link",
        new_callable=AsyncMock,
        return_value=True,
    ):
        yield


@pytest.mark.usefixtures("upgrade_link_window_open")
class TestBotChatStreamSubscriptionGate:
    """GAIA is paid-only: a linked FREE user is refused before any LangGraph run.

    Distinct from platform_requires_upgrade above, which only gates premium
    platforms (iMessage) — this gates every platform. The refusal must reach
    the bot as a real outbound message (a notice frame), not a bare error
    code, because it carries a per-user checkout link.
    """

    @staticmethod
    def _pro_checkout(payment_link: str | None) -> AsyncMock:
        return AsyncMock(
            return_value=ProCheckout(
                plan=PlanResponse(
                    id="plan_pro",
                    dodo_product_id="prod_pro",
                    name="Pro",
                    amount=3000,
                    currency="USD",
                    duration=PlanDuration.MONTHLY,
                    is_active=True,
                    created_at=datetime(2026, 1, 1, tzinfo=UTC),
                    updated_at=datetime(2026, 1, 1, tzinfo=UTC),
                ),
                checkout=CreateSubscriptionResponse(
                    subscription_id="cs_1", payment_link=payment_link, status="pending"
                ),
            )
        )

    @patch("app.api.v1.endpoints.bot.capture_event")
    @patch("app.services.bot_service.enforce_tiered_limit", new_callable=AsyncMock)
    @patch("app.api.v1.endpoints.bot.BotService.enforce_rate_limit", new_callable=AsyncMock)
    @patch("app.api.v1.endpoints.bot.require_bot_api_key", new_callable=AsyncMock)
    async def test_linked_free_user_gets_a_notice_with_their_checkout_link(
        self,
        mock_auth: AsyncMock,
        mock_limit: AsyncMock,
        mock_tiered: AsyncMock,
        mock_capture: MagicMock,
        client: AsyncClient,
    ):
        with (
            patch(
                "app.utils.auth_utils.user_repository.get_by_platform_id",
                new_callable=AsyncMock,
                return_value=UserDocument(id="u1"),
            ),
            patch(PLAN_PATCH, new_callable=AsyncMock, return_value=PlanType.FREE),
            patch(
                "app.api.v1.endpoints.bot.payment_service.create_pro_checkout",
                self._pro_checkout("https://checkout.dodopayments.com/s/cs_1"),
            ),
        ):
            response = await client.post(f"{BOT_BASE}/chat-stream", json=_CHAT_BODY("telegram"))

        assert response.status_code == 200
        assert response.text == (
            'data: {"notice": {"text": "GAIA is paid only. Subscribe to GAIA Pro '
            'to keep chatting: https://checkout.dodopayments.com/s/cs_1"}}\n\n'
            'data: {"done": true, "conversation_id": ""}\n\n'
        )
        # No LangGraph run, and no plan quota charged for a turn that never happened.
        mock_tiered.assert_not_awaited()

    @patch("app.api.v1.endpoints.bot.capture_event")
    @patch("app.services.bot_service.enforce_tiered_limit", new_callable=AsyncMock)
    @patch("app.api.v1.endpoints.bot.BotService.enforce_rate_limit", new_callable=AsyncMock)
    @patch("app.api.v1.endpoints.bot.require_bot_api_key", new_callable=AsyncMock)
    async def test_discount_code_is_appended_when_configured(
        self,
        mock_auth: AsyncMock,
        mock_limit: AsyncMock,
        mock_tiered: AsyncMock,
        mock_capture: MagicMock,
        client: AsyncClient,
    ):
        with (
            patch(
                "app.utils.auth_utils.user_repository.get_by_platform_id",
                new_callable=AsyncMock,
                return_value=UserDocument(id="u1"),
            ),
            patch(PLAN_PATCH, new_callable=AsyncMock, return_value=PlanType.FREE),
            patch(
                "app.api.v1.endpoints.bot.payment_service.create_pro_checkout",
                self._pro_checkout(None),
            ),
            patch("app.api.v1.endpoints.bot.settings.PAYWALL_DISCOUNT_CODE", "SAVE20"),
        ):
            response = await client.post(f"{BOT_BASE}/chat-stream", json=_CHAT_BODY("telegram"))

        assert "Use code SAVE20 for a discount." in response.text

    @patch("app.api.v1.endpoints.bot.capture_event")
    @patch("app.services.bot_service.enforce_tiered_limit", new_callable=AsyncMock)
    @patch("app.api.v1.endpoints.bot.BotService.enforce_rate_limit", new_callable=AsyncMock)
    @patch("app.api.v1.endpoints.bot.require_bot_api_key", new_callable=AsyncMock)
    async def test_the_refusal_is_captured_with_its_own_reason_not_as_submitted(
        self,
        mock_auth: AsyncMock,
        mock_limit: AsyncMock,
        mock_tiered: AsyncMock,
        mock_capture: MagicMock,
        client: AsyncClient,
    ):
        with (
            patch(
                "app.utils.auth_utils.user_repository.get_by_platform_id",
                new_callable=AsyncMock,
                return_value=UserDocument(id="u1"),
            ),
            patch(PLAN_PATCH, new_callable=AsyncMock, return_value=PlanType.FREE),
            patch(
                "app.api.v1.endpoints.bot.payment_service.create_pro_checkout",
                self._pro_checkout(None),
            ),
        ):
            await client.post(f"{BOT_BASE}/chat-stream", json=_CHAT_BODY("telegram"))

        captured = [call.args[1] for call in mock_capture.call_args_list]
        assert AnalyticsEvents.CHAT_MESSAGE_SUBMITTED not in captured
        assert AnalyticsEvents.CHAT_MESSAGE_REFUSED in captured
        refusal = next(
            call
            for call in mock_capture.call_args_list
            if call.args[1] == AnalyticsEvents.CHAT_MESSAGE_REFUSED
        )
        assert refusal.args[0] == "u1"
        assert refusal.args[2] == {"platform": "telegram", "reason": "subscription_required"}


@pytest.mark.usefixtures("upgrade_link_window_open")
class TestBotRateLimitNotice:
    """Rate limits reach bots as text, so the upgrade path has to be a link.

    Bots drop tool_data, so the web's RateLimitCard (and its pricing-modal CTA)
    never renders for them. A checkout link is the only one-tap route a WhatsApp
    or Telegram user has.
    """

    @staticmethod
    def _card(current_plan: str = PlanType.FREE.value) -> BotWebStreamPayload:
        return BotWebStreamPayload.model_validate(
            {
                "tool_data": {
                    "tool_name": "rate_limit_data",
                    "data": {"feature": "chat_messages", "current_plan": current_plan},
                }
            }
        )

    async def test_free_user_gets_a_real_checkout_link(self) -> None:
        checkout = AsyncMock(
            return_value=ProCheckout(
                plan=PlanResponse(
                    id="plan_pro",
                    dodo_product_id="prod_pro",
                    name="Pro",
                    amount=3000,
                    currency="USD",
                    duration=PlanDuration.MONTHLY,
                    is_active=True,
                    created_at=datetime(2026, 1, 1, tzinfo=UTC),
                    updated_at=datetime(2026, 1, 1, tzinfo=UTC),
                ),
                checkout=CreateSubscriptionResponse(
                    subscription_id="cs_1",
                    payment_link="https://checkout.dodopayments.com/s/cs_1",
                    status="payment_link_created",
                ),
            )
        )
        with patch("app.api.v1.endpoints.bot.payment_service.create_pro_checkout", checkout):
            notice = await _bot_rate_limit_notice(self._card(), _bot_upgrade_url_once("user_1"))

        assert notice is not None
        assert "chat messages limit" in notice
        assert "[Upgrade to Pro](https://checkout.dodopayments.com/s/cs_1)" in notice
        checkout.assert_awaited_once_with("user_1")

    async def test_dodo_failure_degrades_to_the_pricing_page(self) -> None:
        """A marketing link must never cost the user their reply."""
        log.reset()
        with patch(
            "app.api.v1.endpoints.bot.payment_service.create_pro_checkout",
            AsyncMock(side_effect=RuntimeError("dodo down")),
        ):
            notice = await _bot_rate_limit_notice(self._card(), _bot_upgrade_url_once("user_1"))

        assert notice is not None
        assert "/pricing)" in notice
        # The fallback is loud: the wide event carries a bounded operation and
        # failure reason (never provider error text), not a silent degrade.
        assert log.get()["warnings"] == [
            {
                "msg": "[PAYMENT] Could not mint bot upgrade link, falling back to pricing page",
                "user": {"id": "user_1"},
                "payment": {"operation": "bot_upgrade_link"},
                "failure_reason": "checkout_unavailable",
                "error_type": "RuntimeError",
            }
        ]

    async def test_pro_user_gets_no_pitch_and_no_session(self) -> None:
        checkout = AsyncMock()
        with patch("app.api.v1.endpoints.bot.payment_service.create_pro_checkout", checkout):
            notice = await _bot_rate_limit_notice(
                self._card(PlanType.PRO.value), _bot_upgrade_url_once("user_1")
            )

        assert notice is not None
        assert "Upgrade" not in notice
        checkout.assert_not_awaited()

    async def test_other_tool_cards_are_left_alone(self) -> None:
        chunk = BotWebStreamPayload.model_validate(
            {"tool_data": {"tool_name": "memory_data", "data": {}}}
        )
        assert await _bot_rate_limit_notice(chunk, _bot_upgrade_url_once("user_1")) is None


class TestBotUpgradeLinkWindow:
    """A bot turn mints at most one Dodo session per user per window.

    Both bot walls — the paid-only gate and the rate-limit notice — repeat for
    every message until the user acts on them, and each mint is a get_plans
    call, a Dodo round-trip and a checkout_sessions insert. Unbounded, a
    lapsed user who keeps typing leaves a trail of throwaway sessions, and the
    newest of them is what checkout_session_repository.get_latest_for_user
    finds when the webhook-race recovery goes looking for the session they
    actually paid on.

    What is gated is the MINT, never the message: a bot has no modal and no
    banner, so going quiet on a blocked turn would read as a broken bot.
    """

    @staticmethod
    def _redis(*set_results: object) -> MagicMock:
        cache = MagicMock()
        cache.client.set = AsyncMock(side_effect=list(set_results))
        return cache

    @staticmethod
    def _checkout(payment_link: str) -> AsyncMock:
        return AsyncMock(
            return_value=ProCheckout(
                plan=PlanResponse(
                    id="plan_pro",
                    dodo_product_id="prod_pro",
                    name="Pro",
                    amount=3000,
                    currency="USD",
                    duration=PlanDuration.MONTHLY,
                    is_active=True,
                    created_at=datetime(2026, 1, 1, tzinfo=UTC),
                    updated_at=datetime(2026, 1, 1, tzinfo=UTC),
                ),
                checkout=CreateSubscriptionResponse(
                    subscription_id="cs_1",
                    payment_link=payment_link,
                    status="payment_link_created",
                ),
            )
        )

    async def test_a_burst_of_blocked_turns_mints_exactly_one_session(self) -> None:
        """SET NX returns None once the key is there — that is the whole gate."""
        checkout = self._checkout("https://checkout.dodopayments.com/s/cs_1")
        # First turn claims the window; the next two find it held.
        with (
            patch("app.api.v1.endpoints.bot.redis_cache", self._redis(True, None, None)),
            patch("app.api.v1.endpoints.bot.payment_service.create_pro_checkout", checkout),
        ):
            urls = [await _bot_upgrade_url("user_1") for _ in range(3)]

        assert checkout.await_count == 1, (
            f"three blocked turns minted {checkout.await_count} Dodo session(s); one is the cap"
        )
        assert urls[0] == "https://checkout.dodopayments.com/s/cs_1"

    async def test_a_turn_outside_the_window_still_gets_a_working_url(self) -> None:
        """The user is never left without a way to pay — only without one tap."""
        checkout = self._checkout("https://checkout.dodopayments.com/s/cs_1")
        with (
            patch("app.api.v1.endpoints.bot.redis_cache", self._redis(None)),
            patch("app.api.v1.endpoints.bot.payment_service.create_pro_checkout", checkout),
        ):
            url = await _bot_upgrade_url("user_1")

        assert url.endswith("/pricing")
        checkout.assert_not_awaited()

    async def test_a_blocked_turn_outside_the_window_still_answers_the_user(self) -> None:
        """A bot has no modal fallback so the notice still goes out, with the pricing page in place of the personalised link when only the mint is gated."""
        checkout = self._checkout("https://checkout.dodopayments.com/s/cs_1")
        with (
            patch("app.api.v1.endpoints.bot.redis_cache", self._redis(None)),
            patch("app.api.v1.endpoints.bot.payment_service.create_pro_checkout", checkout),
        ):
            notice = await _bot_rate_limit_notice(
                BotWebStreamPayload.model_validate(
                    {
                        "tool_data": {
                            "tool_name": "rate_limit_data",
                            "data": {
                                "feature": "chat_messages",
                                "current_plan": PlanType.FREE.value,
                            },
                        }
                    }
                ),
                _bot_upgrade_url_once("user_1"),
            )

        assert notice is not None
        assert "chat messages limit" in notice
        assert "/pricing)" in notice

    async def test_the_window_is_per_user(self) -> None:
        """A shared key would let one lapsed user mute everyone else's link."""
        checkout = self._checkout("https://checkout.dodopayments.com/s/cs_1")
        cache = self._redis(True, True)
        with (
            patch("app.api.v1.endpoints.bot.redis_cache", cache),
            patch("app.api.v1.endpoints.bot.payment_service.create_pro_checkout", checkout),
        ):
            await _bot_upgrade_url("user_1")
            await _bot_upgrade_url("user_2")

        # SET key value NX EX ttl: without NX every turn re-mints, without EX
        # the first turn locks the user out forever. Both survived as mutants
        # under a key-only assertion.
        assert cache.client.set.await_args_list == [
            call("bot:upgrade-link:user_1", "1", nx=True, ex=BOT_UPGRADE_LINK_TTL),
            call("bot:upgrade-link:user_2", "1", nx=True, ex=BOT_UPGRADE_LINK_TTL),
        ]

    async def test_an_unavailable_window_skips_the_mint_and_says_so(self) -> None:
        """Fails CLOSED, unlike the workflow limit-notice gate it copies — a degraded link costs orphan sessions, cheaper than silently burying a real payment."""
        log.reset()
        cache = MagicMock()
        cache.client.set = AsyncMock(side_effect=ConnectionError("redis down"))
        checkout = self._checkout("https://checkout.dodopayments.com/s/cs_1")
        with (
            patch("app.api.v1.endpoints.bot.redis_cache", cache),
            patch("app.api.v1.endpoints.bot.payment_service.create_pro_checkout", checkout),
        ):
            url = await _bot_upgrade_url("user_1")

        assert url.endswith("/pricing")
        checkout.assert_not_awaited()
        assert log.get()["warnings"] == [
            {
                "msg": (
                    "[PAYMENT] Bot upgrade-link window unavailable, falling back to pricing page"
                ),
                "user": {"id": "user_1"},
                "payment": {"operation": "bot_upgrade_link_window"},
                "failure_reason": "window_unavailable",
                "error_type": "ConnectionError",
            }
        ]


class TestForwarderWiring:
    """The handler hands the forwarder the started stream and the bot's own platform; a mismatch here is a bot reading the wrong turn."""

    async def test_the_forwarder_is_given_the_started_stream_and_the_bots_platform(
        self, client: AsyncClient
    ):
        async def nothing() -> AsyncGenerator[str, None]:
            if False:  # pragma: no cover
                yield

        with (
            patch("app.api.v1.endpoints.bot.require_bot_api_key", new=AsyncMock()),
            patch(
                "app.utils.auth_utils.user_repository.get_by_platform_id",
                new=AsyncMock(return_value=UserDocument(id="uid1")),
            ),
            patch("app.api.v1.endpoints.bot.BotService") as bot_svc,
            patch(
                "app.services.bot_service.BotService.load_conversation_history",
                new=AsyncMock(return_value=[]),
            ),
            patch("app.api.v1.endpoints.bot.stream_manager") as sm,
            patch("app.api.v1.endpoints.bot.charge_bot_turn", new=AsyncMock()),
            patch("app.api.v1.endpoints.bot.spawn_background_task", new=MagicMock()),
            patch("app.api.v1.endpoints.bot.run_chat_stream_background", new=MagicMock()) as bg,
            patch(
                "app.api.v1.endpoints.bot.create_bot_session_token",
                new=MagicMock(return_value="tok"),
            ),
            patch(
                "app.api.v1.endpoints.bot._bot_stream_from_redis",
                new=MagicMock(return_value=nothing()),
            ) as forwarder,
            # The background turn is handed the same request-accepted clock the
            # web endpoint passes, so bot TTFT/E2E share the web definition.
            # Dropped or nulled, every bot latency reports an unbounded duration.
            patch("app.api.v1.endpoints.bot.time.perf_counter", return_value=123.5),
        ):
            bot_svc.enforce_rate_limit = AsyncMock()
            bot_svc.get_or_create_session = AsyncMock(return_value="conv-1")
            bot_svc.load_conversation_history = AsyncMock(return_value=[])
            sm.start_stream = AsyncMock()
            response = await client.post(
                f"{BOT_BASE}/chat-stream",
                json={"message": "hello", "platform": "discord", "platform_user_id": "u1"},
            )
            await response.aread()

        started_stream_id = sm.start_stream.await_args.args[0]
        kwargs = forwarder.call_args.kwargs
        assert callable(kwargs.pop("upgrade_url"))
        assert kwargs == {
            "stream_id": started_stream_id,
            "conversation_id": "conv-1",
            "session_token": "tok",
            "platform": "discord",
        }
        assert bg.call_args.kwargs["t0_perf"] == 123.5
        assert bg.call_args.kwargs["stream_id"] == started_stream_id


class TestBotStreamDeliveryMetrics:
    """sse_delivery_seconds is the only record of how a bot stream ended.

    The observation lives in the forwarder's finally, so it fires on every exit —
    clean completion, a dropped client, the generator being closed, an error —
    each under a distinct status. Pinning the clock lands an exact 0.5, so a sign
    error is hundreds off and a nulled start cannot observe at all.
    """

    @staticmethod
    def _observed(status: str) -> float:
        return REGISTRY.get_sample_value("sse_delivery_seconds_sum", {"status": status}) or 0.0

    @staticmethod
    def _forwarder(frames: AsyncGenerator[str, None], *, disconnected: bool = False):
        request = MagicMock()
        request.is_disconnected = AsyncMock(return_value=disconnected)
        return bot_module._bot_stream_from_redis(
            request,
            stream_id="s1",
            conversation_id="conv-1",
            upgrade_url=_never_upgrade,
            session_token="tok",
            platform="discord",
        )

    @staticmethod
    def _pinned_clock():
        return patch("app.api.v1.endpoints.bot.time.perf_counter", side_effect=[100.0, 100.5])

    @staticmethod
    async def _frames(*chunks: str) -> AsyncGenerator[str, None]:
        for chunk in chunks:
            yield chunk

    async def test_clean_completion_records_completed(self) -> None:
        before = self._observed("completed")
        with patch("app.api.v1.endpoints.bot.stream_manager") as sm, self._pinned_clock():
            sm.subscribe_stream.return_value = self._frames(
                'data: {"response": "hi"}\n\n', "data: [DONE]\n\n"
            )
            collected = [f async for f in self._forwarder(sm.subscribe_stream.return_value)]

        assert '"done": true' in "".join(collected)
        assert self._observed("completed") - before == pytest.approx(0.5)

    async def test_client_poll_disconnect_records_disconnected(self) -> None:
        before = self._observed("disconnected")
        with patch("app.api.v1.endpoints.bot.stream_manager") as sm, self._pinned_clock():
            sm.subscribe_stream.return_value = self._frames('data: {"response": "hi"}\n\n')
            collected = [
                f
                async for f in self._forwarder(sm.subscribe_stream.return_value, disconnected=True)
            ]

        assert '"text"' not in "".join(collected)
        assert self._observed("disconnected") - before == pytest.approx(0.5)

    async def test_generator_close_records_abandoned(self) -> None:
        async def frames() -> AsyncGenerator[str, None]:
            yield 'data: {"response": "hi"}\n\n'
            await asyncio.Event().wait()

        before = self._observed("abandoned")
        with patch("app.api.v1.endpoints.bot.stream_manager") as sm, self._pinned_clock():
            sm.subscribe_stream.return_value = frames()
            body = self._forwarder(sm.subscribe_stream.return_value)
            assert await body.__anext__() == 'data: {"session_token": "tok"}\n\n'
            assert await body.__anext__() == ": keepalive\n\n"
            assert await body.__anext__() == 'data: {"text": "hi"}\n\n'
            await body.aclose()

        assert self._observed("abandoned") - before == pytest.approx(0.5)

    async def test_cancellation_records_disconnected(self) -> None:
        async def frames() -> AsyncGenerator[str, None]:
            yield 'data: {"response": "hi"}\n\n'
            await asyncio.Event().wait()

        before = self._observed("disconnected")
        with patch("app.api.v1.endpoints.bot.stream_manager") as sm, self._pinned_clock():
            sm.subscribe_stream.return_value = frames()
            body = self._forwarder(sm.subscribe_stream.return_value)
            for _ in range(3):
                await body.__anext__()
            with pytest.raises(asyncio.CancelledError):
                await body.athrow(asyncio.CancelledError)

        assert self._observed("disconnected") - before == pytest.approx(0.5)

    async def test_stream_error_records_error(self) -> None:
        async def frames() -> AsyncGenerator[str, None]:
            raise RuntimeError("redis down")
            yield  # pragma: no cover - unreachable; makes this an async generator

        before = self._observed("error")
        with patch("app.api.v1.endpoints.bot.stream_manager") as sm, self._pinned_clock():
            sm.subscribe_stream.return_value = frames()
            collected = [f async for f in self._forwarder(sm.subscribe_stream.return_value)]

        # Exact frame: the client parses this by key, so a renamed key or reworded
        # value is a real regression, not a cosmetic one.
        assert 'data: {"error": "Stream error occurred"}\n\n' in collected
        assert self._observed("error") - before == pytest.approx(0.5)


class TestBotStreamFromRedis:
    """The forwarding generator on its own: its boundary, its first bytes, and what it records when the client goes away or the subscription breaks."""

    @staticmethod
    def _request(disconnected: bool = False) -> MagicMock:
        request = MagicMock()
        request.is_disconnected = AsyncMock(return_value=disconnected)
        return request

    @staticmethod
    async def _frames(*chunks: str) -> AsyncGenerator[str, None]:
        for chunk in chunks:
            yield chunk

    @staticmethod
    async def _drain(gen: AsyncGenerator[str, None]) -> list[str]:
        return [frame async for frame in gen]

    async def test_the_boundary_names_the_stream_the_platform_and_the_request_trace(self):
        boundary = MagicMock()
        boundary.return_value.__aenter__ = AsyncMock()
        boundary.return_value.__aexit__ = AsyncMock(return_value=False)
        with (
            patch("app.api.v1.endpoints.bot.log_context", boundary),
            patch("app.api.v1.endpoints.bot.get_trace_id", return_value="trace-1"),
            patch("app.api.v1.endpoints.bot.stream_manager") as sm,
        ):
            sm.subscribe_stream.return_value = self._frames("data: [DONE]\n\n")
            await self._drain(
                bot_module._bot_stream_from_redis(
                    self._request(),
                    stream_id="s1",
                    conversation_id="conv-1",
                    upgrade_url=_never_upgrade,
                    session_token="tok",
                    platform="discord",
                )
            )

        boundary.assert_called_once_with(
            "sse_delivery", trace_id="trace-1", stream_id="s1", platform="discord"
        )
        sm.subscribe_stream.assert_called_once_with("s1")

    async def test_the_session_token_then_a_keepalive_open_every_stream(self):
        with patch("app.api.v1.endpoints.bot.stream_manager") as sm:
            sm.subscribe_stream.return_value = self._frames()
            frames = await self._drain(
                bot_module._bot_stream_from_redis(
                    self._request(),
                    stream_id="s1",
                    conversation_id="conv-1",
                    upgrade_url=_never_upgrade,
                    session_token="tok",
                    platform="discord",
                )
            )

        assert frames == ['data: {"session_token": "tok"}\n\n', ": keepalive\n\n"]

    async def test_a_gone_client_is_recorded_and_nothing_more_is_forwarded(self):
        with (
            patch("app.api.v1.endpoints.bot.stream_manager") as sm,
            patch("app.api.v1.endpoints.bot.log") as log,
        ):
            sm.subscribe_stream.return_value = self._frames('data: {"response": "hi"}\n\n')
            frames = await self._drain(
                bot_module._bot_stream_from_redis(
                    self._request(disconnected=True),
                    stream_id="s1",
                    conversation_id="conv-1",
                    upgrade_url=_never_upgrade,
                    session_token="tok",
                    platform="discord",
                )
            )

        assert len(frames) == 2
        log.set.assert_any_call(client_disconnected=True)

    async def test_a_broken_subscription_is_logged_with_its_ids_and_told_to_the_bot(self):
        async def broken() -> AsyncGenerator[str, None]:
            raise RuntimeError("redis gone")
            yield  # pragma: no cover

        with (
            patch("app.api.v1.endpoints.bot.stream_manager") as sm,
            patch("app.api.v1.endpoints.bot.log") as log,
        ):
            sm.subscribe_stream.return_value = broken()
            frames = await self._drain(
                bot_module._bot_stream_from_redis(
                    self._request(),
                    stream_id="s1",
                    conversation_id="conv-1",
                    upgrade_url=_never_upgrade,
                    session_token="tok",
                    platform="discord",
                )
            )

        assert frames[-1] == 'data: {"error": "Stream error occurred"}\n\n'
        log.error.assert_called_once()
        assert log.error.call_args.kwargs == {
            "stream_id": "s1",
            "conversation_id": "conv-1",
            "error_type": "RuntimeError",
            "error": "redis gone",
        }

    async def test_a_cancelled_delivery_is_recorded_as_the_client_leaving_and_re_raised(self):
        async def cancelled() -> AsyncGenerator[str, None]:
            raise asyncio.CancelledError
            yield  # pragma: no cover

        with (
            patch("app.api.v1.endpoints.bot.stream_manager") as sm,
            patch("app.api.v1.endpoints.bot.log") as log,
        ):
            sm.subscribe_stream.return_value = cancelled()
            delivery = bot_module._bot_stream_from_redis(
                self._request(),
                stream_id="s1",
                conversation_id="conv-1",
                upgrade_url=_never_upgrade,
                session_token="tok",
                platform="discord",
            )
            with pytest.raises(asyncio.CancelledError):
                await self._drain(delivery)

        log.set.assert_any_call(client_disconnected=True)

    async def test_a_comment_or_web_only_frame_does_not_end_the_stream(self):
        with patch("app.api.v1.endpoints.bot.stream_manager") as sm:
            sm.subscribe_stream.return_value = self._frames(
                ": ping\n\n", "event: x\n\n", 'data: {"response": "hi"}\n\n', "data: [DONE]\n\n"
            )
            frames = await self._drain(
                bot_module._bot_stream_from_redis(
                    self._request(),
                    stream_id="s1",
                    conversation_id="conv-1",
                    upgrade_url=_never_upgrade,
                    session_token="tok",
                    platform="discord",
                )
            )

        assert any('"hi"' in frame for frame in frames), frames
        assert '"done": true' in frames[-1]

    async def test_a_broken_subscription_is_logged_under_the_api_tag(self):
        async def broken() -> AsyncGenerator[str, None]:
            raise RuntimeError("redis gone")
            yield  # pragma: no cover

        with (
            patch("app.api.v1.endpoints.bot.stream_manager") as sm,
            patch("app.api.v1.endpoints.bot.log") as log,
        ):
            sm.subscribe_stream.return_value = broken()
            await self._drain(
                bot_module._bot_stream_from_redis(
                    self._request(),
                    stream_id="s1",
                    conversation_id="conv-1",
                    upgrade_url=_never_upgrade,
                    session_token="tok",
                    platform="discord",
                )
            )

        assert "Bot stream subscription error" in log.error.call_args.args[0]
