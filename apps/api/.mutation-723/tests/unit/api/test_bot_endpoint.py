"""Unit tests for bot API endpoints.

Tests the bot endpoints with mocked service layer to verify
routing, status codes, response bodies, and auth checks.
"""

from unittest.mock import AsyncMock, MagicMock, patch

from fastapi import HTTPException
from httpx import AsyncClient
import pytest

from app.models.payment_models import PlanType

BOT_BASE = "/api/v1/bot"
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
    async def test_settings_invalid_platform(self, mock_auth: AsyncMock, client: AsyncClient):
        response = await client.get(f"{BOT_BASE}/settings/badplatform/u1")
        assert response.status_code == 400


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
        assert response.json()["success"] is True

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
    async def test_chat_stream_validation_error(self, mock_auth: AsyncMock, client: AsyncClient):
        response = await client.post(f"{BOT_BASE}/chat-stream", json={})
        assert response.status_code == 422

    @patch("app.api.v1.endpoints.bot.BotService.enforce_rate_limit", new_callable=AsyncMock)
    @patch("app.api.v1.endpoints.bot.require_bot_api_key", new_callable=AsyncMock)
    async def test_chat_stream_unlinked_user_gets_not_authenticated_frame(
        self, mock_auth: AsyncMock, mock_limit: AsyncMock, client: AsyncClient
    ):
        with patch(
            "app.api.v1.endpoints.bot.PlatformLinkService.get_user_by_platform_id",
            new_callable=AsyncMock,
            return_value=None,
        ):
            response = await client.post(f"{BOT_BASE}/chat-stream", json=_CHAT_BODY("imessage"))

        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/event-stream")
        assert response.text == 'data: {"error": "not_authenticated"}\n\n'

    @patch("app.api.v1.endpoints.bot.enforce_tiered_limit", new_callable=AsyncMock)
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
                "app.api.v1.endpoints.bot.PlatformLinkService.get_user_by_platform_id",
                new_callable=AsyncMock,
                return_value={"_id": "u1"},
            ),
            patch(PLAN_PATCH, new_callable=AsyncMock, return_value=PlanType.FREE) as mock_plan,
        ):
            response = await client.post(f"{BOT_BASE}/chat-stream", json=_CHAT_BODY("imessage"))

        assert response.status_code == 200
        assert response.text == 'data: {"error": "plan_required"}\n\n'
        mock_plan.assert_awaited_once_with("u1")
        mock_tiered.assert_not_awaited()

    @pytest.mark.parametrize(
        ("platform", "plan"),
        [("imessage", PlanType.PRO), ("telegram", PlanType.FREE)],
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
                "app.api.v1.endpoints.bot.PlatformLinkService.get_user_by_platform_id",
                new_callable=AsyncMock,
                return_value={"_id": "u1"},
            ),
            patch(PLAN_PATCH, new_callable=AsyncMock, return_value=plan),
            patch(
                "app.api.v1.endpoints.bot.enforce_tiered_limit",
                new_callable=AsyncMock,
                side_effect=HTTPException(status_code=418),
            ) as mock_tiered,
        ):
            response = await client.post(f"{BOT_BASE}/chat-stream", json=_CHAT_BODY(platform))

        assert response.status_code == 418
        mock_tiered.assert_awaited_once_with("u1", "chat_messages")


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

    # NOTE: The deeper transcribe path (mime allowlist, Whisper invocation) is
    # tested directly in tests/unit/services/test_audio_transcription_service.py.
    # We cannot easily flip request.state.authenticated=True in the unit
    # harness because the test_app strips the BotAuthMiddleware, and
    # require_bot_api_key isn't injected via Depends. Service-level tests cover
    # the rest; an e2e fixture would be needed to cover the full route.


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

    `bot_chat_stream` resolves its caller from a platform link inside the body,
    so it can never be metered by `@tiered_rate_limit`. Before it called
    `enforce_tiered_limit` explicitly it went entirely unmetered: a free user had
    no message limit through Telegram/Discord/Slack/WhatsApp, and because
    `record_activity` fires from the limiter, bot turns never reached
    `usage_daily` either — leaving those users off the heatmap, streak and badge.
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
                "app.api.v1.endpoints.bot.PlatformLinkService.get_user_by_platform_id",
                new_callable=AsyncMock,
                return_value={"user_id": "u_bot_1", "email": "bot@gaia.local"},
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

    @pytest.mark.regression
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

    @pytest.mark.regression
    async def test_a_bot_turn_checks_the_daily_cost_wall_too(self, client: AsyncClient):
        """Web chat charges TWO walls: how many messages, and how expensive the
        day has been. Metering only the first left a bot user over budget with a
        stream that opened and died partway instead of a clean refusal."""
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
            patch("app.api.v1.endpoints.bot.enforce_daily_cost_budget", cost_wall),
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
                "app.api.v1.endpoints.bot.PlatformLinkService.get_user_by_platform_id",
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
