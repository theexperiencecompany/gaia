"""HIL preferences service — the thin seam over the user repository.

Preferences decide *which* tools are gated, so a misread here is a gate that
silently stops asking. The write-shape guarantees (per-tool ``$setField`` writes,
dotted MCP names staying flat keys, partial updates leaving siblings alone) live
on ``UserRepository`` now and are contract-tested against real Mongo in
``tests/contracts/test_users_repository.py`` — what remains here is the service's
own behavior: default resolution and reading back after a write.
"""

from unittest.mock import AsyncMock, patch

import pytest

from app.models.hil_models import HILPreferences
from app.services.analytics_service import AnalyticsEvents
from app.services.hil.preferences import (
    get_hil_preferences,
    set_tool_override,
    update_hil_preferences,
)

from .conftest import USER_ID

MODULE = "app.services.hil.preferences"


def _user_with(prefs: object) -> AsyncMock:
    user = AsyncMock()
    user.hil_preferences = prefs
    return user


@pytest.fixture
def user_repo():
    with patch(f"{MODULE}.user_repository") as repo:
        repo.get = AsyncMock(return_value=_user_with({}))
        repo.set_hil_preference_fields = AsyncMock()
        repo.set_hil_tool_override = AsyncMock()
        yield repo


@pytest.fixture(autouse=True)
def _neutralize_captures():
    """Silence analytics captures for tests not asserting on them.

    ``capture_event`` resolves the PostHog provider at call time, which is not
    registered in this test module's import chain — capture-specific tests
    patch the call explicitly and assert on it.
    """
    with patch(f"{MODULE}.capture_event"):
        yield


class TestReads:
    async def test_stored_preferences_are_parsed_into_the_model(self, user_repo) -> None:
        user_repo.get.return_value = _user_with(
            {"mode": "always_ask", "tool_overrides": {"send": True}}
        )

        prefs = await get_hil_preferences(USER_ID)

        assert prefs.mode == "always_ask"
        assert prefs.tool_overrides == {"send": True}
        user_repo.get.assert_awaited_once_with(USER_ID)

    async def test_a_user_who_never_set_preferences_gets_the_defaults(self, user_repo) -> None:
        # A brand-new user has no `hil_preferences` key at all. Crashing here would break
        # every tool call for everyone who has not opened settings.
        user_repo.get.return_value = _user_with(None)

        assert await get_hil_preferences(USER_ID) == HILPreferences()

    async def test_a_missing_user_document_does_not_crash_the_gate(self, user_repo) -> None:
        user_repo.get.return_value = None

        assert await get_hil_preferences(USER_ID) == HILPreferences()


class TestWrites:
    async def test_a_partial_update_passes_through_and_reads_back(self, user_repo) -> None:
        user_repo.get.return_value = _user_with({"mode": "auto"})

        with patch(f"{MODULE}.get_hil_preferences", new_callable=AsyncMock) as mock_get:
            mock_get.return_value = HILPreferences(mode="auto")
            prefs = await update_hil_preferences(USER_ID, mode="auto")

        mock_get.assert_awaited_once_with(USER_ID)
        user_repo.set_hil_preference_fields.assert_awaited_once_with(
            USER_ID, mode="auto", tool_overrides=None
        )
        assert prefs.mode == "auto", "the caller gets the post-write state, not the input"

    async def test_an_empty_override_map_is_a_real_instruction(self, user_repo) -> None:
        # {} means "reset every tool to its default" and must reach the repository —
        # only a fully-absent argument is a no-op (decided inside the repository).
        await update_hil_preferences(USER_ID, tool_overrides={})

        user_repo.set_hil_preference_fields.assert_awaited_once_with(
            USER_ID, mode=None, tool_overrides={}
        )

    async def test_a_tool_override_passes_through_and_reads_back(self, user_repo) -> None:
        user_repo.get.return_value = _user_with({"tool_overrides": {"GMAIL_SEND_EMAIL": True}})

        prefs = await set_tool_override(USER_ID, "GMAIL_SEND_EMAIL", True)

        user_repo.set_hil_tool_override.assert_awaited_once_with(USER_ID, "GMAIL_SEND_EMAIL", True)
        assert prefs.tool_overrides == {"GMAIL_SEND_EMAIL": True}


class TestCaptures:
    async def test_a_mode_change_is_captured(self, user_repo) -> None:
        user_repo.get.return_value = _user_with({"mode": "auto"})

        with patch(f"{MODULE}.capture_event") as mock_capture:
            await update_hil_preferences(USER_ID, mode="always_ask")

        mock_capture.assert_called_once_with(
            USER_ID,
            AnalyticsEvents.SETTINGS_PREFERENCES_CHANGED,
            {"setting": "hil_approvals", "mode": "always_ask"},
        )

    async def test_a_tool_overrides_only_update_is_not_captured(self, user_repo) -> None:
        with patch(f"{MODULE}.capture_event") as mock_capture:
            await update_hil_preferences(USER_ID, tool_overrides={})

        mock_capture.assert_not_called()

    async def test_a_tool_override_is_captured(self, user_repo) -> None:
        with patch(f"{MODULE}.capture_event") as mock_capture:
            await set_tool_override(USER_ID, "GMAIL_SEND_EMAIL", True)

        mock_capture.assert_called_once_with(
            USER_ID,
            AnalyticsEvents.SETTINGS_PREFERENCES_CHANGED,
            {
                "setting": "tool_approval",
                "tool_name": "GMAIL_SEND_EMAIL",
                "require_approval": True,
            },
        )

    async def test_clearing_a_tool_override_is_captured_as_not_requiring_approval(
        self, user_repo
    ) -> None:
        with patch(f"{MODULE}.capture_event") as mock_capture:
            await set_tool_override(USER_ID, "GMAIL_SEND_EMAIL", None)

        mock_capture.assert_called_once_with(
            USER_ID,
            AnalyticsEvents.SETTINGS_PREFERENCES_CHANGED,
            {
                "setting": "tool_approval",
                "tool_name": "GMAIL_SEND_EMAIL",
                "require_approval": False,
            },
        )
