"""Unit tests for bot API endpoints.

Tests the bot endpoints with mocked service layer to verify
routing, status codes, response bodies, and auth checks.
"""

from collections.abc import AsyncGenerator
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Literal
from unittest.mock import AsyncMock, MagicMock, call, patch

import httpx
from httpx import AsyncClient
import pytest

from app.api.v1.endpoints.bot import _bot_turn_refused
from app.db.redis import redis_cache
from app.models.bot_models import BotChatRequest
from app.models.conversation_send_models import BotMessageAccepted
from app.models.payment_models import (
    PlanType,
)
from app.models.user_models import AuthenticatedUser, UserDocument
from app.models.work_cancel_models import ConversationStopResponse, WorkCancelled
from app.services.audio_transcription_service import AudioTooLargeError
from shared.py.analytics import UserId
from shared.py.analytics.catalog.bots import BotAudioTranscribed, BotSessionReset
from shared.py.analytics.catalog.chat import ChatMessageRefused
from shared.py.analytics.catalog.integrations import IntegrationDisconnected

BOT_BASE = "/api/v1/bot"
USER_ID = "6812f0b3c9a14e2b7d5a91cc"
MIDDLEWARE_USER_ID = "6812f0b3c9a14e2b7d5a91cd"
LOOKUP_USER_ID = "6812f0b3c9a14e2b7d5a91ce"


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
    bot endpoints — not the paywall itself (see TestBotTurnRefused for that). A test that needs FREE re-patches PLAN_PATCH inside its own
    with block, which nests inside (and correctly overrides) this one.
    """
    with patch(PLAN_PATCH, new_callable=AsyncMock, return_value=PlanType.PRO):
        yield


# ---------------------------------------------------------------------------
# POST /bot/reset-session
# ---------------------------------------------------------------------------


class TestResetSession:
    """POST /api/v1/bot/reset-session."""

    @patch("app.api.v1.endpoints.bot.capture")
    @patch("app.api.v1.endpoints.bot.reset_bot_session", new_callable=AsyncMock)
    @patch(
        "app.utils.auth_utils.user_repository.get_by_platform_id",
        new_callable=AsyncMock,
    )
    @patch("app.api.v1.endpoints.bot.require_bot_api_key", new_callable=AsyncMock)
    async def test_reset_session_success(
        self,
        mock_auth: AsyncMock,
        mock_get_user: AsyncMock,
        mock_reset: AsyncMock,
        mock_capture: MagicMock,
        client: AsyncClient,
    ):
        mock_get_user.return_value = UserDocument(id=USER_ID)
        mock_reset.return_value = "new-convo-id"
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
        mock_capture.assert_called_once_with(UserId(USER_ID), BotSessionReset(platform="discord"))

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


class TestStopSession:
    """POST /api/v1/bot/stop: stop the session's conversation, keep the session."""

    @patch("app.api.v1.endpoints.bot.reset_bot_session", new_callable=AsyncMock)
    @patch("app.api.v1.endpoints.bot.stop_bot_session", new_callable=AsyncMock)
    @patch(
        "app.utils.auth_utils.user_repository.get_by_platform_id",
        new_callable=AsyncMock,
    )
    @patch("app.api.v1.endpoints.bot.require_bot_api_key", new_callable=AsyncMock)
    async def test_stop_stops_the_conversation_and_never_resets(
        self,
        mock_auth: AsyncMock,
        mock_get_user: AsyncMock,
        mock_stop: AsyncMock,
        mock_reset: AsyncMock,
        bot_log: MagicMock,
        client: AsyncClient,
    ):
        mock_get_user.return_value = UserDocument(id=USER_ID)
        mock_stop.return_value = ConversationStopResponse(
            conversation_id="conv-1",
            work=WorkCancelled(executor_stopped=True, executor_task_id="t1"),
        )

        response = await client.post(
            f"{BOT_BASE}/stop",
            json={"platform": "telegram", "platform_user_id": "u1", "channel_id": "ch1"},
        )

        assert response.status_code == 200
        assert response.json()["conversation_id"] == "conv-1"
        assert response.json()["work"]["executor_task_id"] == "t1"
        # The caller resolves like every bot route: the platform account's linked user.
        mock_get_user.assert_awaited_once_with("telegram", "u1")
        platform, platform_user_id, channel_id, user = mock_stop.await_args.args
        assert (platform, platform_user_id, channel_id) == ("telegram", "u1", "ch1")
        assert (user.user_id, user.auth_provider) == (USER_ID, "bot:telegram")
        assert mock_stop.await_args.kwargs == {"is_dm": False}
        mock_reset.assert_not_awaited()
        assert bot_log.set.call_args_list == [
            call(operation="stop_session", platform="telegram"),
            call(user={"id": USER_ID}),
            call(bot={"conversation_id": "conv-1"}, outcome="success", stopped_work=True),
        ]

    @patch("app.api.v1.endpoints.bot.stop_bot_session", new_callable=AsyncMock)
    async def test_stop_without_the_bot_key_is_refused_and_stops_nothing(
        self, mock_stop: AsyncMock, client: AsyncClient
    ):
        response = await client.post(
            f"{BOT_BASE}/stop", json={"platform": "discord", "platform_user_id": "u1"}
        )

        assert response.status_code == 401
        assert response.json()["code"] == "BOT_API_KEY_INVALID"
        mock_stop.assert_not_awaited()

    @patch(
        "app.utils.auth_utils.user_repository.get_by_platform_id",
        new_callable=AsyncMock,
    )
    @patch("app.api.v1.endpoints.bot.require_bot_api_key", new_callable=AsyncMock)
    async def test_an_unlinked_account_is_refused(
        self, mock_auth: AsyncMock, mock_get_user: AsyncMock, client: AsyncClient
    ):
        mock_get_user.return_value = None

        response = await client.post(
            f"{BOT_BASE}/stop", json={"platform": "discord", "platform_user_id": "u1"}
        )

        assert response.status_code == 401


# ---------------------------------------------------------------------------
# POST /bot/messages — accept a message; the reply follows on the events stream
# ---------------------------------------------------------------------------


class TestBotSendMessage:
    """POST /api/v1/bot/messages."""

    @patch("app.api.v1.endpoints.bot.submit_bot_message", new_callable=AsyncMock)
    @patch("app.api.v1.endpoints.bot.BotService.enforce_rate_limit", new_callable=AsyncMock)
    @patch(
        "app.utils.auth_utils.user_repository.get_by_platform_id",
        new_callable=AsyncMock,
        return_value=UserDocument(id=USER_ID),
    )
    @patch("app.api.v1.endpoints.bot.require_bot_api_key", new_callable=AsyncMock)
    async def test_an_entitled_message_is_accepted_for_the_linked_user(
        self,
        mock_auth: AsyncMock,
        mock_get_user: AsyncMock,
        mock_limit: AsyncMock,
        mock_submit: AsyncMock,
        client: AsyncClient,
    ):
        mock_submit.return_value = BotMessageAccepted(
            conversation_id="conv-1", message_id="m-1", seq=7, session_token="tok"
        )

        response = await client.post(f"{BOT_BASE}/messages", json=_CHAT_BODY("discord"))

        assert response.status_code == 202
        assert response.json() == {
            "conversation_id": "conv-1",
            "message_id": "m-1",
            "seq": 7,
            "session_token": "tok",
        }
        mock_limit.assert_awaited_once_with("discord", "u1")
        body, user = mock_submit.await_args.args
        assert (body.message, body.platform, body.platform_user_id) == ("hello", "discord", "u1")
        assert user.user_id == USER_ID

    @patch("app.api.v1.endpoints.bot.submit_bot_message", new_callable=AsyncMock)
    async def test_a_message_without_the_bot_key_is_refused(
        self, mock_submit: AsyncMock, client: AsyncClient
    ):
        response = await client.post(f"{BOT_BASE}/messages", json=_CHAT_BODY("discord"))

        assert response.status_code == 401
        assert response.json()["code"] == "BOT_API_KEY_INVALID"
        mock_submit.assert_not_awaited()

    @patch("app.api.v1.endpoints.bot.submit_bot_message", new_callable=AsyncMock)
    @patch("app.api.v1.endpoints.bot.BotService.enforce_rate_limit", new_callable=AsyncMock)
    @patch("app.api.v1.endpoints.bot.require_bot_api_key", new_callable=AsyncMock)
    async def test_an_unlinked_account_is_told_to_link(
        self,
        mock_auth: AsyncMock,
        mock_limit: AsyncMock,
        mock_submit: AsyncMock,
        unlinked: None,
        client: AsyncClient,
    ):
        response = await client.post(f"{BOT_BASE}/messages", json=_CHAT_BODY("discord"))

        assert response.status_code == 401
        assert response.json()["code"] == "BOT_ACCOUNT_NOT_LINKED"
        mock_submit.assert_not_awaited()

    @pytest.mark.parametrize(
        ("platform", "reason"),
        [("imessage", "plan_required"), ("discord", "subscription_required")],
    )
    @patch("app.api.v1.endpoints.bot.capture")
    @patch("app.api.v1.endpoints.bot.submit_bot_message", new_callable=AsyncMock)
    async def test_a_free_user_is_refused_with_a_402_and_nothing_is_sent(
        self,
        mock_submit: AsyncMock,
        mock_capture: MagicMock,
        client: AsyncClient,
        platform: str,
        reason: Literal["plan_required", "subscription_required"],
    ):
        with (
            patch("app.api.v1.endpoints.bot.require_bot_api_key", new_callable=AsyncMock),
            patch("app.api.v1.endpoints.bot.BotService.enforce_rate_limit", new_callable=AsyncMock),
            patch(
                "app.utils.auth_utils.user_repository.get_by_platform_id",
                new_callable=AsyncMock,
                return_value=UserDocument(id=USER_ID),
            ),
            patch(PLAN_PATCH, new_callable=AsyncMock, return_value=PlanType.FREE),
            patch("app.api.v1.endpoints.bot.is_paid", new_callable=AsyncMock, return_value=False),
        ):
            response = await client.post(f"{BOT_BASE}/messages", json=_CHAT_BODY(platform))

        assert response.status_code == 402
        mock_submit.assert_not_awaited()
        mock_capture.assert_called_once_with(
            UserId(USER_ID), ChatMessageRefused(platform=platform, reason=reason)
        )


class TestBotTurnRefused:
    """_bot_turn_refused: the Pro-gated platform check, then the paid-only gate."""

    async def test_plan_required_refuses_before_the_subscription_check(self):
        with (
            patch(
                "app.api.v1.endpoints.bot.platform_requires_upgrade",
                new_callable=AsyncMock,
                return_value=True,
            ) as mock_requires_upgrade,
            patch("app.api.v1.endpoints.bot.is_paid", new_callable=AsyncMock) as mock_paid,
            patch("app.api.v1.endpoints.bot._capture_bot_turn_refused") as mock_capture,
        ):
            assert await _bot_turn_refused(USER_ID, "imessage") is True

        mock_requires_upgrade.assert_awaited_once_with(USER_ID, "imessage")
        mock_capture.assert_called_once_with(USER_ID, "imessage", "plan_required")
        mock_paid.assert_not_called()

    async def test_an_unpaid_user_is_refused_as_subscription_required(self):
        with (
            patch(
                "app.api.v1.endpoints.bot.platform_requires_upgrade",
                new_callable=AsyncMock,
                return_value=False,
            ),
            patch(
                "app.api.v1.endpoints.bot.is_paid", new_callable=AsyncMock, return_value=False
            ) as mock_paid,
            patch("app.api.v1.endpoints.bot._capture_bot_turn_refused") as mock_capture,
        ):
            assert await _bot_turn_refused(USER_ID, "discord") is True

        mock_paid.assert_awaited_once_with(USER_ID)
        mock_capture.assert_called_once_with(USER_ID, "discord", "subscription_required")

    async def test_a_user_who_just_paid_passes_off_the_row_not_the_stale_cache(self):
        """A bot turn sent minutes after paying reads FREE from the cache; the gate must ask the database."""
        with (
            patch(
                "app.api.v1.endpoints.bot.platform_requires_upgrade",
                new_callable=AsyncMock,
                return_value=False,
            ),
            patch(
                "app.decorators.entitlements.payment_service.get_cached_plan_type",
                new_callable=AsyncMock,
                return_value=PlanType.FREE,
            ),
            patch(
                "app.decorators.entitlements.payment_service.get_user_subscription_status",
                new_callable=AsyncMock,
                return_value=MagicMock(plan_type=PlanType.PRO),
            ),
            patch("app.decorators.entitlements.invalidate_plan_cache", new_callable=AsyncMock),
            patch("app.api.v1.endpoints.bot._capture_bot_turn_refused") as mock_capture,
        ):
            assert await _bot_turn_refused(USER_ID, "discord") is False

        mock_capture.assert_not_called()


# ---------------------------------------------------------------------------
# _resolve_bot_caller — the user every bot turn acts as
# ---------------------------------------------------------------------------


class TestResolveBotCaller:
    """One seam, every bot route that needs a user.

    A wrong answer here runs the turn as, or attributes it to, a different account.
    """

    async def test_the_middleware_user_wins_when_the_request_is_authenticated(self):
        from app.api.v1.endpoints.bot import _resolve_bot_caller

        middleware_user = AuthenticatedUser(user_id=MIDDLEWARE_USER_ID)
        request = MagicMock()
        request.state = _make_request(user=middleware_user, authenticated=True)
        with patch("app.api.v1.endpoints.bot.resolve_bot_user", new_callable=AsyncMock) as lookup:
            assert await _resolve_bot_caller(request, "discord", "u1") is middleware_user
        lookup.assert_not_awaited()

    async def test_an_unauthenticated_state_user_falls_back_to_the_platform_link(self):
        """request.state.user alone is not trusted — authenticated must be set too."""
        from app.api.v1.endpoints.bot import _resolve_bot_caller

        linked = AuthenticatedUser(user_id=LOOKUP_USER_ID, auth_provider="bot:discord")
        request = MagicMock()
        request.state = _make_request(
            user=AuthenticatedUser(user_id=MIDDLEWARE_USER_ID), authenticated=False
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
        request.state = SimpleNamespace(user=AuthenticatedUser(user_id=MIDDLEWARE_USER_ID))
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
        mock_get_user.return_value = UserDocument(id=USER_ID)
        response = await client.get(f"{BOT_BASE}/auth-status/discord/u1")
        assert response.status_code == 200
        data = response.json()
        assert data["authenticated"] is True
        assert data["platform"] == "discord"
        assert data["platform_user_id"] == "u1"
        # The bot keys PostHog on this id. Returning only the boolean is what
        # left bot events on a parallel `discord:<id>` profile.
        assert data["user_id"] == USER_ID
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
            id=USER_ID, name="Alice", picture="https://img.example.com/a.png", created_at=None
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
        mock_integrations.assert_awaited_once_with(USER_ID)

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
            id=USER_ID, created_at=datetime(2025, 1, 2, 3, 4, 5, tzinfo=UTC)
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
        mock_get_user.return_value = UserDocument(id=USER_ID, name="Alice", created_at=None)
        # The records arrive as dumped documents, exactly as the service returns them.
        mock_integrations.return_value = [
            {"id": "r1", "user_id": USER_ID, "integration_id": "gmail", "status": "connected"},
            {"id": "r2", "user_id": USER_ID, "integration_id": "notion", "status": "created"},
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

    @patch("app.api.v1.endpoints.bot.capture")
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
        mock_get_user.return_value = UserDocument(id=USER_ID)
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
            UserId(USER_ID), IntegrationDisconnected(integration_id="discord")
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

    @patch("app.api.v1.endpoints.bot.capture")
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

    @patch("app.api.v1.endpoints.bot.capture")
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

    @patch("app.api.v1.endpoints.bot.capture")
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

    @patch("app.api.v1.endpoints.bot.capture")
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
        fake_user: AuthenticatedUser,
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
        assert args[0] == UserId(fake_user.user_id)
        assert args[1] == BotAudioTranscribed(
            audio_bytes=len(audio), transcript_length=len("hello there")
        )
        assert "hello there" not in str(args[1].to_properties())

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
        fake_user: AuthenticatedUser,
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

    @patch("app.api.v1.endpoints.bot.capture")
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

    async def test_a_reset_session_is_stamped_with_the_linked_user(
        self, bot_log: MagicMock, api_key_ok: None, client: AsyncClient
    ):
        with (
            patch(
                "app.utils.auth_utils.user_repository.get_by_platform_id",
                new_callable=AsyncMock,
                return_value=UserDocument(id=USER_ID),
            ),
            patch(
                "app.api.v1.endpoints.bot.reset_bot_session",
                new=AsyncMock(return_value="new-convo-id"),
            ),
            patch("app.api.v1.endpoints.bot.capture"),
        ):
            response = await client.post(
                f"{BOT_BASE}/reset-session",
                json={"platform": "discord", "platform_user_id": "u1", "channel_id": "ch1"},
            )

        assert response.status_code == 200
        bot_log.set.assert_any_call(user={"id": USER_ID})


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
            side_effect=AudioTooLargeError("Audio is 9 bytes; max supported is 8."),
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
