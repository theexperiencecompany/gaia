"""Checking a run's claim that an integration was missing, before acting on it.

The rest of this module derives requirements from a workflow's declared steps.
``confirm_disconnected`` is the one function whose input comes from a run instead
— and a run is a model, so its claim is the thing under test here.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.workflow.integration_requirements import confirm_disconnected

MODULE = "app.services.workflow.integration_requirements"
STATUS_TARGET = "app.services.oauth.oauth_service.get_all_integrations_status"
USER_ID = "507f1f77bcf86cd799439011"


@pytest.mark.unit
class TestConfirmDisconnected:
    async def test_it_keeps_only_the_integrations_that_are_really_missing(self) -> None:
        with (
            patch(STATUS_TARGET, AsyncMock(return_value={"gmail": True, "github": False})),
            patch(f"{MODULE}.get_integration_by_id", return_value=MagicMock()),
        ):
            assert await confirm_disconnected(USER_ID, ["gmail", "github"]) == ["github"]

    async def test_it_drops_an_integration_gaia_does_not_have(self) -> None:
        """A hallucinated id must not pause anything: there is nothing for the
        user to go and connect."""
        with (
            patch(STATUS_TARGET, AsyncMock(return_value={})),
            patch(f"{MODULE}.get_integration_by_id", return_value=None),
        ):
            assert await confirm_disconnected(USER_ID, ["notarealtool"]) == []

    async def test_it_reports_each_integration_once(self) -> None:
        with (
            patch(STATUS_TARGET, AsyncMock(return_value={"github": False})),
            patch(f"{MODULE}.get_integration_by_id", return_value=MagicMock()),
        ):
            assert await confirm_disconnected(USER_ID, ["github", "github"]) == ["github"]

    async def test_no_claim_asks_the_status_service_nothing(self) -> None:
        with patch(STATUS_TARGET, AsyncMock()) as status:
            assert await confirm_disconnected(USER_ID, []) == []
        status.assert_not_awaited()
