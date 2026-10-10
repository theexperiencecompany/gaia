"""Unit tests for the Composio callback service: resolve the account, record the connection.

Every collaborator is patched at the module seam; the route's redirect mapping lives
in tests/unit/api/test_oauth_endpoint.py.
"""

from unittest.mock import AsyncMock, MagicMock, patch

from fastapi import BackgroundTasks
import pytest
from tests.factories import make_integration_config

from app.constants.log_tags import LogTag
from app.services.analytics_service import AnalyticsEvents
from app.services.oauth.composio_callback import (
    ConnectionCompleted,
    ConnectionRejected,
    complete_composio_connection,
    stored_connected_account_id,
)

MODULE = "app.services.oauth.composio_callback"
STATE = {"user_id": "uid1", "integration_id": "gmail", "redirect_path": "/integrations"}


@pytest.fixture
def mock_log():
    with patch(f"{MODULE}.log") as log:
        yield log


@pytest.fixture
def mock_repo():
    with patch(f"{MODULE}.user_integration_repository") as repo:
        repo.get_for_user = AsyncMock(return_value=None)
        yield repo


@pytest.fixture
def mock_composio():
    with patch(f"{MODULE}.get_composio_service") as get_service:
        yield get_service.return_value


@pytest.fixture
def mock_config():
    with patch(f"{MODULE}.get_integration_by_config", return_value=None) as get_config:
        yield get_config


@pytest.fixture
def mock_handle():
    with patch(f"{MODULE}.handle_oauth_connection", new_callable=AsyncMock) as handle:
        yield handle


@pytest.fixture
def mock_capture():
    with patch(f"{MODULE}.capture_event") as capture:
        yield capture


@pytest.fixture
def background_tasks() -> BackgroundTasks:
    return BackgroundTasks()


def _account(user_id: str | None = "uid1", config_id: str = "config1") -> MagicMock:
    account = MagicMock()
    account.auth_config.id = config_id
    account.user_id = user_id
    return account


def _integration() -> MagicMock:
    integration = make_integration_config(integration_id="gmail")
    integration.provider = "google"
    return integration


@pytest.mark.unit
class TestStoredConnectedAccountId:
    async def test_returns_the_id_minted_at_initiate(self, mock_repo, mock_log):
        record = MagicMock()
        record.connected_account_id = "acc_from_initiate"
        mock_repo.get_for_user.return_value = record

        result = await stored_connected_account_id(STATE)

        assert result == "acc_from_initiate"
        mock_repo.get_for_user.assert_awaited_once_with("uid1", "gmail")
        mock_log.set_ns.assert_called_once_with(
            "oauth", connected_account_id_source="stored_record"
        )

    async def test_no_record_is_none_and_reported_as_missing(self, mock_repo, mock_log):
        result = await stored_connected_account_id(STATE)

        assert result is None
        mock_repo.get_for_user.assert_awaited_once_with("uid1", "gmail")
        mock_log.set_ns.assert_called_once_with("oauth", connected_account_id_source="missing")

    async def test_a_record_without_an_account_id_is_missing_too(self, mock_repo, mock_log):
        record = MagicMock()
        record.connected_account_id = None
        mock_repo.get_for_user.return_value = record

        result = await stored_connected_account_id(STATE)

        assert result is None
        mock_log.set_ns.assert_called_once_with("oauth", connected_account_id_source="missing")


@pytest.mark.unit
class TestCompleteComposioConnectionRejections:
    async def test_account_not_found(
        self, mock_composio, mock_config, mock_handle, mock_capture, mock_log, background_tasks
    ):
        mock_composio.get_connected_account_by_id.return_value = None

        outcome = await complete_composio_connection(
            "acc1", expected_user_id="uid1", background_tasks=background_tasks
        )

        assert outcome == ConnectionRejected(reason="account_not_found")
        mock_composio.get_connected_account_by_id.assert_called_once_with("acc1")
        mock_log.error.assert_called_once_with(
            f"{LogTag.OAUTH} Connected account not found", connected_account_id="acc1"
        )
        mock_config.assert_not_called()
        mock_handle.assert_not_awaited()
        mock_capture.assert_not_called()

    async def test_user_missing(
        self, mock_composio, mock_config, mock_handle, mock_capture, mock_log, background_tasks
    ):
        mock_composio.get_connected_account_by_id.return_value = _account(user_id=None)

        outcome = await complete_composio_connection(
            "acc1", expected_user_id="uid1", background_tasks=background_tasks
        )

        assert outcome == ConnectionRejected(reason="user_missing")
        mock_log.error.assert_called_once_with(
            f"{LogTag.OAUTH} User ID missing for account", connected_account_id="acc1"
        )
        mock_config.assert_not_called()
        mock_handle.assert_not_awaited()
        mock_capture.assert_not_called()

    async def test_config_missing(
        self, mock_composio, mock_config, mock_handle, mock_capture, mock_log, background_tasks
    ):
        mock_composio.get_connected_account_by_id.return_value = _account(config_id="config1")

        outcome = await complete_composio_connection(
            "acc1", expected_user_id="uid1", background_tasks=background_tasks
        )

        assert outcome == ConnectionRejected(reason="config_missing")
        mock_config.assert_called_once_with("config1")
        mock_log.error.assert_called_once_with(
            f"{LogTag.OAUTH} Integration config not found",
            auth_config_id="config1",
            connected_account_id="acc1",
        )
        # Nothing is known about the user yet, so nothing is set on the event.
        mock_log.set.assert_not_called()
        mock_log.set_ns.assert_not_called()
        mock_handle.assert_not_awaited()
        mock_capture.assert_not_called()

    async def test_user_mismatch(
        self, mock_composio, mock_config, mock_handle, mock_capture, mock_log, background_tasks
    ):
        """Refuse another user's account, but name both parties in the event so the attempt is traceable."""
        mock_composio.get_connected_account_by_id.return_value = _account(user_id="uid_other")
        mock_config.return_value = _integration()

        outcome = await complete_composio_connection(
            "acc1", expected_user_id="uid1", background_tasks=background_tasks
        )

        assert outcome == ConnectionRejected(reason="user_mismatch")
        mock_log.set.assert_called_once_with(user={"id": "uid_other"})
        mock_log.set_ns.assert_called_once_with("oauth", provider="google", integration_id="gmail")
        mock_log.error.assert_called_once_with(
            f"{LogTag.OAUTH} User ID mismatch between state and account",
            state_user_id="uid1",
            account_user_id="uid_other",
            connected_account_id="acc1",
        )
        mock_handle.assert_not_awaited()
        mock_capture.assert_not_called()


@pytest.mark.unit
class TestCompleteComposioConnectionSuccess:
    async def test_records_the_connection_and_reports_it(
        self, mock_composio, mock_config, mock_handle, mock_capture, mock_log, background_tasks
    ):
        mock_composio.get_connected_account_by_id.return_value = _account(
            user_id="uid1", config_id="config1"
        )
        integration = _integration()
        mock_config.return_value = integration

        outcome = await complete_composio_connection(
            "acc1", expected_user_id="uid1", background_tasks=background_tasks
        )

        assert outcome == ConnectionCompleted(
            user_id="uid1", integration_id="gmail", provider="google"
        )
        mock_composio.get_connected_account_by_id.assert_called_once_with("acc1")
        mock_config.assert_called_once_with("config1")
        mock_handle.assert_awaited_once_with(
            user_id="uid1",
            integration_config=integration,
            background_tasks=background_tasks,
            connected_account_id="acc1",
        )
        # Explicit user id: Composio redirects the browser here without a WorkOS
        # session, so a context capture would land on an anonymous profile.
        mock_capture.assert_called_once_with(
            "uid1",
            AnalyticsEvents.INTEGRATION_CONNECTED,
            {"integration_id": "gmail", "provider": "google"},
        )
        mock_log.set.assert_called_once_with(user={"id": "uid1"})
        mock_log.set_ns.assert_called_once_with("oauth", provider="google", integration_id="gmail")
        mock_log.info.assert_called_once_with(
            f"{LogTag.OAUTH} Composio connection successful",
            user_id="uid1",
            integration_id="gmail",
            connected_account_id="acc1",
        )
        mock_log.error.assert_not_called()

    async def test_a_non_string_account_user_id_is_matched_as_a_string(
        self, mock_composio, mock_config, mock_handle, mock_capture, mock_log, background_tasks
    ):
        """Compare and record the account's user id as text, as the state token carries it."""
        mock_composio.get_connected_account_by_id.return_value = _account(user_id=1234)
        mock_config.return_value = _integration()

        outcome = await complete_composio_connection(
            "acc1", expected_user_id="1234", background_tasks=background_tasks
        )

        assert outcome == ConnectionCompleted(
            user_id="1234", integration_id="gmail", provider="google"
        )
        mock_log.set.assert_called_once_with(user={"id": "1234"})
        mock_handle.assert_awaited_once_with(
            user_id="1234",
            integration_config=mock_config.return_value,
            background_tasks=background_tasks,
            connected_account_id="acc1",
        )
        mock_capture.assert_called_once_with(
            "1234",
            AnalyticsEvents.INTEGRATION_CONNECTED,
            {"integration_id": "gmail", "provider": "google"},
        )
