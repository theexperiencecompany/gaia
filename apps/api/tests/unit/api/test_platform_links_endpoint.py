"""Tests for app/api/v1/endpoints/platform_links.py"""

from unittest.mock import AsyncMock, patch

from httpx import AsyncClient
import pytest

from app.api.v1.middleware.tiered_rate_limiter import RateLimitExceededException
from app.models.payment_models import PlanType
from app.models.platform_models import DisconnectPlatformResponse, PlatformLinkResult
from app.services.analytics_service import AnalyticsEvents
from app.services.photon.photon_client import PhotonUser
from app.services.platform_link_service import IMESSAGE_REGISTRATION_FEATURE_KEY
from app.utils.errors import AppError
from tests.conftest import FAKE_USER

BASE = "/api/v1/platform-links"
FAKE_USER_ID = FAKE_USER["user_id"]


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
        mock_redis.hgetall = AsyncMock(return_value={"platform": "discord", "platform_user_id": ""})
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
            ),
            patch("app.api.v1.endpoints.platform_links.capture_context_event") as mock_capture,
        ):
            mock_cache.client = mock_redis
            resp = await client.post(f"{BASE}/discord", json={"token": "valid_tok"})

        assert resp.status_code == 200
        assert resp.json()["status"] == "linked"
        mock_capture.assert_called_once_with(
            AnalyticsEvents.INTEGRATION_CONNECTED,
            {"integration_id": "discord", "is_new_link": False},
        )

    @pytest.mark.asyncio
    async def test_link_new_platform_captures_is_new_link_true(self, client: AsyncClient) -> None:
        """A fresh link reports is_new_link=True in the capture payload."""
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
        link_result = PlatformLinkResult(
            status="linked",
            platform="discord",
            platform_user_id="DISC123",
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
                "app.api.v1.endpoints.platform_links.notify_account_linked", new_callable=AsyncMock
            ),
            patch("app.api.v1.endpoints.platform_links.capture_context_event") as mock_capture,
        ):
            mock_cache.client = mock_redis
            resp = await client.post(f"{BASE}/discord", json={"token": "valid_tok"})

        assert resp.status_code == 200
        mock_capture.assert_called_once_with(
            AnalyticsEvents.INTEGRATION_CONNECTED,
            {"integration_id": "discord", "is_new_link": True},
        )

    @pytest.mark.asyncio
    async def test_successful_link_schedules_account_sync_for_user(
        self, client: AsyncClient
    ) -> None:
        mock_redis = AsyncMock()
        mock_redis.hgetall = AsyncMock(
            return_value={"platform": "discord", "platform_user_id": "DISC123"}
        )
        mock_redis.delete = AsyncMock()
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
            ),
            patch(
                "app.api.v1.endpoints.platform_links.schedule_account_sync"
            ) as mock_schedule_sync,
        ):
            mock_cache.client = mock_redis
            resp = await client.post(f"{BASE}/discord", json={"token": "valid_tok"})

        assert resp.status_code == 200
        # The workspace projection must sync THIS user's files, not a null id.
        mock_schedule_sync.assert_called_once_with(FAKE_USER_ID)

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
    async def test_successful_disconnect_clears_cache(self, client: AsyncClient) -> None:
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
            patch("app.services.platform_link_service.redis_cache") as mock_cache,
            patch("app.services.platform_link_service.capture_context_event") as mock_capture,
        ):
            mock_cache.client = mock_redis
            resp = await client.delete(f"{BASE}/discord")

        assert resp.status_code == 200
        assert resp.json()["status"] == "disconnected"
        mock_redis.delete.assert_called_once_with("bot_user:discord:DISC999")
        mock_capture.assert_called_once_with(
            AnalyticsEvents.INTEGRATION_DISCONNECTED, {"integration_id": "discord"}
        )

    @pytest.mark.asyncio
    async def test_disconnect_resolves_the_link_for_the_authenticated_user(
        self, client: AsyncClient
    ) -> None:
        with (
            patch(
                "app.api.v1.endpoints.platform_links.disconnect_platform_account",
                new_callable=AsyncMock,
                return_value=DisconnectPlatformResponse(status="disconnected", platform="discord"),
            ) as mock_disconnect,
            patch("app.api.v1.endpoints.platform_links.schedule_account_sync"),
        ):
            resp = await client.delete(f"{BASE}/discord")

        assert resp.status_code == 200
        # The unlink must run against THIS user's account, for THIS platform.
        assert mock_disconnect.await_args.args == (FAKE_USER_ID, "discord")

    @pytest.mark.asyncio
    async def test_disconnect_schedules_account_sync_for_the_user(
        self, client: AsyncClient
    ) -> None:
        with (
            patch(
                "app.api.v1.endpoints.platform_links.disconnect_platform_account",
                new_callable=AsyncMock,
                return_value=DisconnectPlatformResponse(status="disconnected", platform="discord"),
            ),
            patch(
                "app.api.v1.endpoints.platform_links.schedule_account_sync"
            ) as mock_schedule_sync,
        ):
            resp = await client.delete(f"{BASE}/discord")

        assert resp.status_code == 200
        mock_schedule_sync.assert_called_once_with(FAKE_USER_ID)

    @pytest.mark.asyncio
    async def test_disconnect_propagates_service_apperror_with_why_and_fix(
        self, client: AsyncClient
    ) -> None:
        """The service's AppError reaches the client with status, message, why AND fix.

        The endpoint re-raises AppError rather than rebuilding an HTTPException,
        so the structured guidance the service attached survives to the client.
        """
        with (
            patch(
                "app.api.v1.endpoints.platform_links.disconnect_platform_account",
                new_callable=AsyncMock,
                side_effect=AppError(
                    message="Platform not linked",
                    why="No link record exists for this user and platform",
                    fix="Check account/linked-accounts for what is actually connected",
                    status_code=404,
                ),
            ),
            patch("app.api.v1.endpoints.platform_links.schedule_account_sync"),
        ):
            resp = await client.delete(f"{BASE}/discord")

        assert resp.status_code == 404
        assert resp.json() == {
            "message": "Platform not linked",
            "why": "No link record exists for this user and platform",
            "fix": "Check account/linked-accounts for what is actually connected",
        }

    @pytest.mark.asyncio
    async def test_disconnect_records_success_outcome(self, client: AsyncClient) -> None:
        with (
            patch(
                "app.api.v1.endpoints.platform_links.disconnect_platform_account",
                new_callable=AsyncMock,
                return_value=DisconnectPlatformResponse(status="disconnected", platform="discord"),
            ),
            patch("app.api.v1.endpoints.platform_links.schedule_account_sync"),
            patch("app.api.v1.endpoints.platform_links.log") as mock_log,
        ):
            resp = await client.delete(f"{BASE}/discord")

        assert resp.status_code == 200
        mock_log.set.assert_any_call(outcome="success")

    @pytest.mark.asyncio
    async def test_disconnect_no_existing_entry_returns_404(self, client: AsyncClient) -> None:
        """Disconnecting a never-linked platform is an error, not a silent no-op."""
        with patch(
            "app.services.platform_link_service.PlatformLinkService.get_linked_platforms",
            new_callable=AsyncMock,
            return_value={},
        ):
            resp = await client.delete(f"{BASE}/discord")

        assert resp.status_code == 404

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
# POST /platform-links/{platform}/connect
# ---------------------------------------------------------------------------


class TestInitiatePlatformConnect:
    @pytest.mark.asyncio
    async def test_invalid_platform(self, client: AsyncClient) -> None:
        resp = await client.post(f"{BASE}/badplatform/connect", json={})
        assert resp.status_code == 400

    @pytest.mark.asyncio
    async def test_discord_oauth(self, client: AsyncClient) -> None:
        with (
            patch("app.services.platform_link_service.settings") as mock_settings,
            patch(
                "app.services.platform_link_service.create_oauth_state",
                new_callable=AsyncMock,
                return_value="state123",
            ),
        ):
            mock_settings.DISCORD_OAUTH_CLIENT_ID = "discord_client_id"
            mock_settings.DISCORD_OAUTH_REDIRECT_URI = "http://localhost/callback"
            resp = await client.post(f"{BASE}/discord/connect", json={})

        assert resp.status_code == 200
        body = resp.json()
        assert body["auth_type"] == "oauth"
        assert "discord.com" in body["auth_url"]
        assert "state123" in body["auth_url"]

    @pytest.mark.asyncio
    async def test_slack_oauth(self, client: AsyncClient) -> None:
        with (
            patch("app.services.platform_link_service.settings") as mock_settings,
            patch(
                "app.services.platform_link_service.create_oauth_state",
                new_callable=AsyncMock,
                return_value="slack_state",
            ),
        ):
            mock_settings.DISCORD_OAUTH_CLIENT_ID = None
            mock_settings.SLACK_OAUTH_CLIENT_ID = "slack_client_id"
            mock_settings.SLACK_OAUTH_REDIRECT_URI = "http://localhost/slack/callback"
            resp = await client.post(f"{BASE}/slack/connect", json={})

        assert resp.status_code == 200
        body = resp.json()
        assert body["auth_type"] == "oauth"
        assert "slack.com" in body["auth_url"]

    @pytest.mark.asyncio
    async def test_telegram_manual(self, client: AsyncClient) -> None:
        with patch("app.services.platform_link_service.settings") as mock_settings:
            mock_settings.DISCORD_OAUTH_CLIENT_ID = None
            mock_settings.SLACK_OAUTH_CLIENT_ID = None
            mock_settings.TELEGRAM_BOT_USERNAME = "my_gaia_bot"
            resp = await client.post(f"{BASE}/telegram/connect", json={})

        assert resp.status_code == 200
        body = resp.json()
        assert body["auth_type"] == "manual"
        assert "my_gaia_bot" in body["instructions"]
        assert body["action_link"] == "https://t.me/my_gaia_bot"

    @pytest.mark.asyncio
    async def test_telegram_default_bot_username(self, client: AsyncClient) -> None:
        with patch("app.services.platform_link_service.settings") as mock_settings:
            mock_settings.DISCORD_OAUTH_CLIENT_ID = None
            mock_settings.SLACK_OAUTH_CLIENT_ID = None
            mock_settings.TELEGRAM_BOT_USERNAME = None
            resp = await client.post(f"{BASE}/telegram/connect", json={})

        assert resp.status_code == 200
        assert "gaia_bot" in resp.json()["instructions"]

    @pytest.mark.asyncio
    async def test_whatsapp_manual(self, client: AsyncClient) -> None:
        """WhatsApp uses manual flow (no OAuth) -> 200 with instructions."""
        with patch("app.services.platform_link_service.settings") as mock_settings:
            mock_settings.DISCORD_OAUTH_CLIENT_ID = None
            mock_settings.SLACK_OAUTH_CLIENT_ID = None
            mock_settings.WHATSAPP_PHONE_NUMBER = "15551234567"
            resp = await client.post(f"{BASE}/whatsapp/connect", json={})

        assert resp.status_code == 200
        body = resp.json()
        assert body["auth_type"] == "manual"
        assert "WhatsApp" in body["instructions"]
        assert body["action_link"] == "https://wa.me/15551234567"

    @pytest.mark.asyncio
    async def test_connect_records_outcome_and_auth_type_in_event(
        self, client: AsyncClient
    ) -> None:
        with (
            patch("app.services.platform_link_service.settings") as mock_settings,
            patch("app.api.v1.endpoints.platform_links.log") as mock_log,
        ):
            mock_settings.DISCORD_OAUTH_CLIENT_ID = None
            mock_settings.SLACK_OAUTH_CLIENT_ID = None
            mock_settings.TELEGRAM_BOT_USERNAME = "gaia_bot"
            resp = await client.post(f"{BASE}/telegram/connect", json={})

        assert resp.status_code == 200
        mock_log.set.assert_any_call(outcome="success", auth_type="manual")

    @pytest.mark.asyncio
    async def test_unauthenticated(self, unauthed_client: AsyncClient) -> None:
        resp = await unauthed_client.post(f"{BASE}/discord/connect", json={})
        assert resp.status_code == 401


# ---------------------------------------------------------------------------
# iMessage premium gate
# ---------------------------------------------------------------------------

PLAN_PATCH = "app.services.platform_link_service.payment_service.get_cached_plan_type"


class TestImessagePremiumGate:
    @pytest.mark.asyncio
    async def test_free_user_link_returns_429_upsell(self, client: AsyncClient) -> None:
        with patch(PLAN_PATCH, new_callable=AsyncMock, return_value=PlanType.FREE) as mock_plan:
            resp = await client.post(f"{BASE}/imessage", json={"token": "tok123"})

        assert resp.status_code == 429
        mock_plan.assert_awaited_once_with(FAKE_USER_ID)
        detail = resp.json()["detail"]
        assert detail["plan_required"] == "pro"
        assert detail["current_plan"] == "free"

    @pytest.mark.asyncio
    async def test_free_user_connect_returns_429_upsell(self, client: AsyncClient) -> None:
        with patch(PLAN_PATCH, new_callable=AsyncMock, return_value=PlanType.FREE) as mock_plan:
            resp = await client.post(f"{BASE}/imessage/connect", json={"phone": "+15551234567"})

        assert resp.status_code == 429
        mock_plan.assert_awaited_once_with(FAKE_USER_ID)
        assert resp.json()["detail"]["plan_required"] == "pro"

    @pytest.mark.asyncio
    async def test_pro_user_link_passes_gate(self, client: AsyncClient) -> None:
        mock_redis = AsyncMock()
        mock_redis.hgetall = AsyncMock(return_value={})

        with (
            patch(PLAN_PATCH, new_callable=AsyncMock, return_value=PlanType.PRO),
            patch("app.api.v1.endpoints.platform_links.redis_cache") as mock_cache,
        ):
            mock_cache.client = mock_redis
            resp = await client.post(f"{BASE}/imessage", json={"token": "tok123"})

        # Gate passed; the request proceeds to token redemption and fails there.
        assert resp.status_code == 400
        assert "expired" in resp.json()["detail"].lower()

    @pytest.mark.asyncio
    async def test_free_user_can_still_disconnect(self, client: AsyncClient) -> None:
        entry = {
            "platform": "imessage",
            "platformUserId": "+15551234567",
            "username": None,
            "displayName": None,
            "connectedAt": "2026-01-01T00:00:00Z",
        }
        with (
            patch(PLAN_PATCH, new_callable=AsyncMock, return_value=PlanType.FREE),
            patch(
                "app.api.v1.endpoints.platform_links.PlatformLinkService.get_linked_platforms",
                new_callable=AsyncMock,
                return_value={"imessage": entry},
            ),
            patch(
                "app.api.v1.endpoints.platform_links.PlatformLinkService.unlink_account",
                new_callable=AsyncMock,
                return_value=DisconnectPlatformResponse(status="disconnected", platform="imessage"),
            ),
            patch("app.services.platform_link_service.redis_cache") as mock_cache,
        ):
            mock_cache.client = AsyncMock()
            resp = await client.delete(f"{BASE}/imessage")

        assert resp.status_code == 200
        assert resp.json()["status"] == "disconnected"

    @pytest.mark.asyncio
    async def test_pro_user_connect_missing_phone_422(self, client: AsyncClient) -> None:
        with patch(PLAN_PATCH, new_callable=AsyncMock, return_value=PlanType.PRO):
            resp = await client.post(f"{BASE}/imessage/connect", json={})

        assert resp.status_code == 422
        body = resp.json()
        assert body["message"] == (
            "A phone number in E.164 format (e.g. +15551234567) is required for iMessage."
        )
        # The endpoint re-raises AppError, so the actionable fix survives.
        assert body["fix"] == "Pass a phone number in E.164 format (e.g. +15551234567)"

    @pytest.mark.asyncio
    async def test_pro_user_connect_malformed_phone_422(self, client: AsyncClient) -> None:
        with (
            patch(PLAN_PATCH, new_callable=AsyncMock, return_value=PlanType.PRO),
            patch(
                "app.services.platform_link_service.register_shared_user",
                new_callable=AsyncMock,
            ) as mock_register,
        ):
            resp = await client.post(f"{BASE}/imessage/connect", json={"phone": "555-1234"})

        assert resp.status_code == 422
        mock_register.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_connect_phone_never_in_url(self, client: AsyncClient) -> None:
        with patch(PLAN_PATCH, new_callable=AsyncMock, return_value=PlanType.PRO):
            resp = await client.get(f"{BASE}/imessage/connect", params={"phone": "+15551234567"})

        assert resp.status_code == 405

    @pytest.mark.asyncio
    async def test_pro_user_connect_returns_photon_deep_link(self, client: AsyncClient) -> None:
        photon_user = PhotonUser(
            id="pu_123", phoneNumber="+15551234567", assignedPhoneNumber="+14155955082"
        )
        with (
            patch(PLAN_PATCH, new_callable=AsyncMock, return_value=PlanType.PRO),
            patch(
                "app.services.platform_link_service.register_shared_user",
                new_callable=AsyncMock,
                return_value=photon_user,
            ) as mock_register,
            patch(
                "app.services.platform_link_service.register_pending_imessage_number",
                new_callable=AsyncMock,
            ),
            patch("app.services.platform_link_service.log") as mock_log,
        ):
            resp = await client.post(f"{BASE}/imessage/connect", json={"phone": "+15551234567"})

        assert resp.status_code == 200
        mock_log.audit.assert_called_once_with(
            "imessage number registered for linking", actor=FAKE_USER_ID, provider="imessage"
        )
        body = resp.json()
        assert body["auth_type"] == "manual"
        assert body["auth_url"] is None
        assert body["instructions"] == (
            "Text /auth to your GAIA iMessage number from the phone you just registered."
        )
        assert body["action_link"] == "https://spectrum.photon.codes/users/pu_123/redirect"
        mock_register.assert_awaited_once_with("+15551234567")

    @pytest.mark.regression
    @pytest.mark.asyncio
    async def test_pro_user_connect_returns_the_number_to_text(self, client: AsyncClient) -> None:
        """The deep link is an Apple-only `sms:` URL — a desktop browser opens it to a
        blank tab. The number the user has to text must reach the client as data."""
        photon_user = PhotonUser(
            id="pu_123", phoneNumber="+15551234567", assignedPhoneNumber="+14155955082"
        )
        with (
            patch(PLAN_PATCH, new_callable=AsyncMock, return_value=PlanType.PRO),
            patch(
                "app.services.platform_link_service.register_shared_user",
                new_callable=AsyncMock,
                return_value=photon_user,
            ),
            patch(
                "app.services.platform_link_service.register_pending_imessage_number",
                new_callable=AsyncMock,
            ),
        ):
            resp = await client.post(f"{BASE}/imessage/connect", json={"phone": "+15551234567"})

        assert resp.status_code == 200
        assert resp.json()["contact_number"] == "+14155955082"

    @pytest.mark.asyncio
    async def test_pro_user_connect_charges_registration_quota(self, client: AsyncClient) -> None:
        photon_user = PhotonUser(
            id="pu_123", phoneNumber="+15551234567", assignedPhoneNumber="+14155955082"
        )
        with (
            patch(PLAN_PATCH, new_callable=AsyncMock, return_value=PlanType.PRO),
            patch(
                "app.services.platform_link_service.enforce_rate_limit", new_callable=AsyncMock
            ) as mock_limit,
            patch(
                "app.services.platform_link_service.register_shared_user",
                new_callable=AsyncMock,
                return_value=photon_user,
            ),
            patch(
                "app.services.platform_link_service.register_pending_imessage_number",
                new_callable=AsyncMock,
            ),
        ):
            resp = await client.post(f"{BASE}/imessage/connect", json={"phone": "+15551234567"})

        assert resp.status_code == 200
        mock_limit.assert_awaited_once_with(FAKE_USER_ID, IMESSAGE_REGISTRATION_FEATURE_KEY)

    @pytest.mark.asyncio
    async def test_connect_over_registration_quota_returns_429(self, client: AsyncClient) -> None:
        with (
            patch(PLAN_PATCH, new_callable=AsyncMock, return_value=PlanType.PRO),
            patch(
                "app.services.platform_link_service.enforce_rate_limit",
                new_callable=AsyncMock,
                side_effect=RateLimitExceededException(
                    feature=IMESSAGE_REGISTRATION_FEATURE_KEY, current_plan="pro"
                ),
            ),
            patch(
                "app.services.platform_link_service.register_shared_user", new_callable=AsyncMock
            ) as mock_register,
        ):
            resp = await client.post(f"{BASE}/imessage/connect", json={"phone": "+15551234567"})

        assert resp.status_code == 429
        assert resp.json()["detail"]["feature"] == IMESSAGE_REGISTRATION_FEATURE_KEY
        mock_register.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_pro_user_connect_records_the_pending_registration(
        self, client: AsyncClient
    ) -> None:
        """Unrecorded, an abandoned registration holds its pool seat forever."""
        photon_user = PhotonUser(
            id="pu_123", phoneNumber="+15551234567", assignedPhoneNumber="+14155955082"
        )
        with (
            patch(PLAN_PATCH, new_callable=AsyncMock, return_value=PlanType.PRO),
            patch("app.services.platform_link_service.enforce_rate_limit", new_callable=AsyncMock),
            patch(
                "app.services.platform_link_service.register_shared_user",
                new_callable=AsyncMock,
                return_value=photon_user,
            ),
            patch(
                "app.services.platform_link_service.register_pending_imessage_number",
                new_callable=AsyncMock,
            ) as mock_pending,
        ):
            resp = await client.post(f"{BASE}/imessage/connect", json={"phone": "+15551234567"})

        assert resp.status_code == 200
        # Both arguments: a pending record filed under the wrong user is a leak
        # the sweep can still reap, but the swap-on-reconnect path never sees.
        assert mock_pending.await_args.args == (FAKE_USER_ID, "+15551234567")

    @pytest.mark.asyncio
    async def test_other_platform_connect_is_not_throttled(self, client: AsyncClient) -> None:
        with (
            patch(PLAN_PATCH, new_callable=AsyncMock, return_value=PlanType.PRO),
            patch(
                "app.services.platform_link_service.enforce_rate_limit", new_callable=AsyncMock
            ) as mock_limit,
            patch("app.services.platform_link_service.settings") as mock_settings,
        ):
            mock_settings.DISCORD_OAUTH_CLIENT_ID = None
            mock_settings.SLACK_OAUTH_CLIENT_ID = None
            mock_settings.TELEGRAM_BOT_USERNAME = "gaia_bot"
            resp = await client.post(f"{BASE}/telegram/connect", json={})

        assert resp.status_code == 200
        mock_limit.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_free_user_other_platforms_unaffected(self, client: AsyncClient) -> None:
        with (
            patch(PLAN_PATCH, new_callable=AsyncMock, return_value=PlanType.FREE),
            patch("app.services.platform_link_service.settings") as mock_settings,
        ):
            mock_settings.DISCORD_OAUTH_CLIENT_ID = None
            mock_settings.SLACK_OAUTH_CLIENT_ID = None
            mock_settings.TELEGRAM_BOT_USERNAME = "gaia_bot"
            resp = await client.post(f"{BASE}/telegram/connect", json={})

        assert resp.status_code == 200
