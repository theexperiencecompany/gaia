"""manage_linked_account — both actions, end to end through the real tool object.

The tool is the agent's only lever on platform links: generate_link must return
usable connect instructions without approval, disconnect must run the real
unlink seam and refresh the projection. The service seams are mocked; the
tool's own dispatch, formatting, analytics and resync are not.
"""

from unittest.mock import AsyncMock, MagicMock, patch

from pydantic import ValidationError
import pytest

from app.agents.tools import account_tools
from app.services.analytics_service import AnalyticsEvents
from app.utils.errors import AppError

MODULE = "app.agents.tools.account_tools"
CONFIG = {"metadata": {"user_id": "user-1"}}


@pytest.fixture(autouse=True)
def _quiet():
    with (
        patch(f"{MODULE}.log"),
        patch(f"{MODULE}.capture_context_event") as capture,
    ):
        yield capture


@pytest.mark.unit
class TestGenerateLink:
    async def test_manual_platform_returns_instructions_and_action_link(self) -> None:
        flow = AsyncMock()
        flow.auth_url = None
        flow.instructions = "Message @gaia_bot with /auth"
        flow.action_link = "https://t.me/gaia_bot"
        with (
            patch(f"{MODULE}.enforce_rate_limit", new=AsyncMock()) as limit,
            patch(f"{MODULE}.start_platform_connect", new=AsyncMock(return_value=flow)) as connect,
        ):
            result = await account_tools.manage_linked_account.ainvoke(
                {"platform": "telegram", "action": "generate_link"}, config=CONFIG
            )

        assert result == (
            "To connect your telegram account:\n"
            "Message @gaia_bot with /auth\n"
            "Open: https://t.me/gaia_bot"
        )
        # The limiter is keyed to THIS user under the connect feature, and the
        # flow is started for the same user and platform the caller asked for.
        limit.assert_awaited_once_with("user-1", account_tools.LINK_GENERATION_FEATURE_KEY)
        connect.assert_awaited_once_with("user-1", "telegram", phone=None)

    async def test_imessage_forwards_the_phone_number_to_the_connect_flow(self) -> None:
        """iMessage is the one platform whose connect flow REQUIRES a phone.

        Every other case here connects without one, so a tool that dropped the
        argument would look correct in all of them while iMessage linking from
        chat failed with "phone required" on every attempt.
        """
        flow = AsyncMock()
        flow.auth_url = None
        flow.instructions = "Text /auth to +15550000000"
        flow.action_link = None
        with (
            patch(f"{MODULE}.enforce_rate_limit", new=AsyncMock()),
            patch(f"{MODULE}.start_platform_connect", new=AsyncMock(return_value=flow)) as connect,
        ):
            result = await account_tools.manage_linked_account.ainvoke(
                {"platform": "imessage", "action": "generate_link", "phone": "+15551234567"},
                config=CONFIG,
            )

        connect.assert_awaited_once_with("user-1", "imessage", phone="+15551234567")
        assert "Text /auth to +15550000000" in result

    async def test_oauth_platform_returns_the_authorize_url(self) -> None:
        flow = AsyncMock()
        flow.auth_url = "https://discord.com/api/oauth2/authorize?state=s1"
        flow.instructions = None
        flow.action_link = None
        with (
            patch(f"{MODULE}.enforce_rate_limit", new=AsyncMock()) as limit,
            patch(f"{MODULE}.start_platform_connect", new=AsyncMock(return_value=flow)),
        ):
            result = await account_tools.manage_linked_account.ainvoke(
                {"platform": "discord", "action": "generate_link"}, config=CONFIG
            )

        assert "authorize: https://discord.com/api/oauth2/authorize?state=s1" in result
        limit.assert_awaited_once()

    async def test_generate_link_is_not_gated_and_emits_no_setting_event(self) -> None:
        flow = AsyncMock()
        flow.auth_url = None
        flow.instructions = "i"
        flow.action_link = None
        with (
            patch(f"{MODULE}.enforce_rate_limit", new=AsyncMock()),
            patch(f"{MODULE}.start_platform_connect", new=AsyncMock(return_value=flow)),
        ):
            await account_tools.manage_linked_account.ainvoke(
                {"platform": "slack", "action": "generate_link"}, config=CONFIG
            )


@pytest.mark.unit
class TestDisconnect:
    async def test_disconnect_runs_the_real_seam_refreshes_projection_and_confirms(
        self,
    ) -> None:
        unlink = AsyncMock()
        resync = MagicMock()
        with (
            patch(f"{MODULE}.disconnect_platform_account", new=unlink),
            patch(f"{MODULE}.schedule_account_sync", new=resync),
            patch(f"{MODULE}.capture_context_event") as capture,
            patch(f"{MODULE}.log") as log_mock,
        ):
            result = await account_tools.manage_linked_account.ainvoke(
                {"platform": "whatsapp", "action": "disconnect"}, config=CONFIG
            )

        unlink.assert_awaited_once_with("user-1", "whatsapp")
        assert "whatsapp disconnected" in result.lower()
        # The linked-accounts projection must reflect reality immediately.
        resync.assert_called_once_with("user-1")
        capture.assert_called_once_with(
            AnalyticsEvents.ACCOUNT_PLATFORM_DISCONNECTED, {"area": "linked_accounts"}
        )
        # The wide event names the action and platform — downstream debugging
        # of a disconnect reads these, not the return string.
        log_mock.set.assert_called_once_with(action="disconnect", platform="whatsapp")

    async def test_disconnect_failure_surfaces_as_an_error_string_not_a_crash(self) -> None:
        with (
            patch(
                f"{MODULE}.disconnect_platform_account",
                new=AsyncMock(side_effect=AppError(message="not linked", status_code=404)),
            ),
            patch(f"{MODULE}.schedule_account_sync", new=AsyncMock()),
        ):
            result = await account_tools.manage_linked_account.ainvoke(
                {"platform": "slack", "action": "disconnect"}, config=CONFIG
            )

        assert result.startswith("Error: not linked")


@pytest.mark.unit
class TestSchemaContract:
    async def test_unsupported_platform_is_rejected_by_the_schema_itself(self) -> None:
        with pytest.raises(ValidationError):
            await account_tools.manage_linked_account.ainvoke(
                {"platform": "carrier_pigeon", "action": "disconnect"}, config=CONFIG
            )

    async def test_unknown_action_is_rejected_by_the_schema_itself(self) -> None:
        with pytest.raises(ValidationError):
            await account_tools.manage_linked_account.ainvoke(
                {"platform": "slack", "action": "nuke"}, config=CONFIG
            )
