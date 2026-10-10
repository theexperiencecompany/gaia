"""Unit tests for the Composio callback service: resolve the account, record the connection.

Every collaborator is patched at the module seam; the route's redirect mapping lives
in tests/unit/api/test_oauth_endpoint.py.
"""

from unittest.mock import AsyncMock, MagicMock, patch

from bson import ObjectId
from fastapi import BackgroundTasks
from pymongo.errors import PyMongoError
import pytest
from tests.factories import make_integration_config

from app.constants.log_tags import LogTag
from app.services.integrations.integration_account_lifecycle import AccountLimitReached
from app.services.oauth.composio_callback import (
    ConnectionCompleted,
    ConnectionRejected,
    complete_composio_connection,
)
from shared.py.analytics import UserId
from shared.py.analytics.catalog.integrations import IntegrationConnected

MODULE = "app.services.oauth.composio_callback"
USER_ID = "507f1f77bcf86cd799439011"
OTHER_USER_ID = "507f1f77bcf86cd799439012"


@pytest.fixture
def mock_log():
    with patch(f"{MODULE}.log") as log:
        yield log


@pytest.fixture(autouse=True)
def mock_repo():
    with patch(f"{MODULE}.user_integration_repository") as repo:
        repo.get_for_user = AsyncMock(return_value=None)
        repo.has_connected_before = AsyncMock(return_value=False)
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
    with patch(f"{MODULE}.capture") as capture:
        yield capture


@pytest.fixture
def background_tasks() -> BackgroundTasks:
    return BackgroundTasks()


def _account(user_id: str | ObjectId | None = USER_ID, config_id: str = "config1") -> MagicMock:
    account = MagicMock()
    account.auth_config.id = config_id
    account.user_id = user_id
    return account


def _integration() -> MagicMock:
    integration = make_integration_config(integration_id="gmail")
    integration.provider = "google"
    return integration


@pytest.mark.unit
@pytest.mark.unit
class TestCompleteComposioConnectionRejections:
    async def test_account_not_found(
        self, mock_composio, mock_config, mock_handle, mock_capture, mock_log, background_tasks
    ):
        mock_composio.get_connected_account_by_id.return_value = None

        outcome = await complete_composio_connection(
            "acc1", expected_user_id=USER_ID, background_tasks=background_tasks
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
            "acc1", expected_user_id=USER_ID, background_tasks=background_tasks
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
            "acc1", expected_user_id=USER_ID, background_tasks=background_tasks
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
        mock_composio.get_connected_account_by_id.return_value = _account(user_id=OTHER_USER_ID)
        mock_config.return_value = _integration()

        outcome = await complete_composio_connection(
            "acc1", expected_user_id=USER_ID, background_tasks=background_tasks
        )

        assert outcome == ConnectionRejected(reason="user_mismatch")
        mock_log.set.assert_called_once_with(user={"id": OTHER_USER_ID})
        mock_log.set_ns.assert_called_once_with("oauth", provider="google", integration_id="gmail")
        mock_log.error.assert_called_once_with(
            f"{LogTag.OAUTH} User ID mismatch between state and account",
            state_user_id=USER_ID,
            account_user_id=OTHER_USER_ID,
            connected_account_id="acc1",
        )
        mock_handle.assert_not_awaited()
        mock_capture.assert_not_called()


@pytest.mark.unit
class TestCompleteComposioConnectionAccountLimit:
    async def test_a_connect_over_the_limit_is_rejected_and_not_reported_as_connected(
        self, mock_composio, mock_config, mock_handle, mock_capture, mock_log, background_tasks
    ):
        mock_composio.get_connected_account_by_id.return_value = _account(user_id="uid1")
        mock_config.return_value = _integration()
        mock_handle.return_value = AccountLimitReached(limit=5)

        outcome = await complete_composio_connection(
            "acc1", expected_user_id="uid1", background_tasks=background_tasks
        )

        assert outcome == ConnectionRejected(reason="account_limit")
        mock_capture.assert_not_called()
        mock_log.warning.assert_called_once_with(
            f"{LogTag.OAUTH} Connect rejected at the per-integration account limit",
            limit=5,
            integration_id="gmail",
        )


@pytest.mark.unit
class TestCompleteComposioConnectionSuccess:
    async def test_records_the_connection_and_reports_it(
        self, mock_composio, mock_config, mock_handle, mock_capture, mock_log, background_tasks
    ):
        mock_composio.get_connected_account_by_id.return_value = _account(
            user_id=USER_ID, config_id="config1"
        )
        integration = _integration()
        mock_config.return_value = integration

        outcome = await complete_composio_connection(
            "acc1", expected_user_id=USER_ID, background_tasks=background_tasks
        )

        assert outcome == ConnectionCompleted(
            user_id=USER_ID, integration_id="gmail", provider="google"
        )
        mock_composio.get_connected_account_by_id.assert_called_once_with("acc1")
        mock_config.assert_called_once_with("config1")
        mock_handle.assert_awaited_once_with(
            user_id=USER_ID,
            integration_config=integration,
            background_tasks=background_tasks,
            connected_account_id="acc1",
        )
        mock_capture.assert_called_once_with(
            UserId(USER_ID),
            IntegrationConnected(integration_id="gmail", provider="google", is_reconnect=False),
        )
        mock_log.set.assert_called_once_with(user={"id": USER_ID})
        mock_log.set_ns.assert_called_once_with("oauth", provider="google", integration_id="gmail")
        mock_log.info.assert_called_once_with(
            f"{LogTag.OAUTH} Composio connection successful",
            user_id=USER_ID,
            integration_id="gmail",
            connected_account_id="acc1",
        )
        mock_log.error.assert_not_called()

    @pytest.mark.regression
    async def test_a_reconnect_of_an_integration_connected_before_is_marked(
        self, mock_composio, mock_config, mock_handle, mock_capture, mock_repo, background_tasks
    ):
        mock_composio.get_connected_account_by_id.return_value = _account(
            user_id=USER_ID, config_id="config1"
        )
        mock_config.return_value = _integration()
        mock_repo.has_connected_before.side_effect = lambda user_id, integration_id: (
            (user_id, integration_id) == (USER_ID, "gmail")
        )

        await complete_composio_connection(
            "acc1", expected_user_id=USER_ID, background_tasks=background_tasks
        )

        assert mock_capture.call_args.args[1].is_reconnect is True

    async def test_an_unreadable_connection_history_does_not_fail_the_connect(
        self, mock_composio, mock_config, mock_handle, mock_capture, mock_repo, background_tasks
    ):
        """Whether it is a reconnect is analytics; the user's connect must not hinge on it."""
        mock_composio.get_connected_account_by_id.return_value = _account(
            user_id=USER_ID, config_id="config1"
        )
        mock_config.return_value = _integration()
        mock_repo.has_connected_before.side_effect = PyMongoError("mongo down")

        with patch("app.services.integrations.user_integration_status.log") as status_log:
            outcome = await complete_composio_connection(
                "acc1", expected_user_id=USER_ID, background_tasks=background_tasks
            )

        assert status_log.warning.call_args.kwargs["integration_id"] == "gmail"

        assert outcome == ConnectionCompleted(
            user_id=USER_ID, integration_id="gmail", provider="google"
        )
        mock_handle.assert_awaited_once()
        mock_capture.assert_called_once_with(
            UserId(USER_ID),
            IntegrationConnected(integration_id="gmail", provider="google", is_reconnect=None),
        )

    async def test_a_non_string_account_user_id_is_matched_as_a_string(
        self, mock_composio, mock_config, mock_handle, mock_capture, mock_log, background_tasks
    ):
        """Compare and record the account's user id as text, as the state token carries it."""
        mock_composio.get_connected_account_by_id.return_value = _account(user_id=ObjectId(USER_ID))
        mock_config.return_value = _integration()

        outcome = await complete_composio_connection(
            "acc1", expected_user_id=USER_ID, background_tasks=background_tasks
        )

        assert outcome == ConnectionCompleted(
            user_id=USER_ID, integration_id="gmail", provider="google"
        )
        mock_log.set.assert_called_once_with(user={"id": USER_ID})
        mock_handle.assert_awaited_once_with(
            user_id=USER_ID,
            integration_config=mock_config.return_value,
            background_tasks=background_tasks,
            connected_account_id="acc1",
        )
        mock_capture.assert_called_once_with(
            UserId(USER_ID),
            IntegrationConnected(integration_id="gmail", provider="google", is_reconnect=False),
        )
