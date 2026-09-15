"""Unit tests for the cached integration-status reader."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.constants.log_tags import LogTag
from app.models.integration_models import UserIntegrationDocument
from app.services.integrations.integration_status import get_all_integrations_status
from shared.py.wide_events import OAuthContext

pytestmark = pytest.mark.unit


@pytest.fixture(autouse=True)
def bypass_cacheable():
    """Bypass the @Cacheable decorator so tests call the real function.

    The Cacheable wrapper (defined in app.decorators.caching) closes over
    get_cache / set_cache imported from app.db.redis.  Patching them there
    ensures every cached call goes straight through to the wrapped function.
    """
    with (
        patch("app.db.redis.redis_cache.get", new_callable=AsyncMock, return_value=None),
        patch("app.db.redis.redis_cache.set", new_callable=AsyncMock),
    ):
        yield


def _ui_doc(integration_id: str, status: str) -> UserIntegrationDocument:
    """Build a UserIntegrationDocument as list_for_user would return it."""
    return UserIntegrationDocument(user_id="user123", integration_id=integration_id, status=status)


@pytest.fixture
def mock_composio_service():
    mock_service = AsyncMock()
    mock_service.check_connection_status = AsyncMock(return_value={})
    with patch(
        "app.services.integrations.integration_status.get_composio_service",
        return_value=mock_service,
    ):
        yield mock_service


@pytest.fixture
def mock_token_repository():
    with patch("app.services.integrations.integration_status.token_repository") as mock_repo:
        yield mock_repo


@pytest.fixture
def mock_user_integration_repo():
    with patch(
        "app.services.integrations.integration_status.user_integration_repository"
    ) as mock_repo:
        mock_repo.list_for_user = AsyncMock(return_value=[])
        yield mock_repo


class TestGetAllIntegrationsStatus:
    """Tests for get_all_integrations_status.

    Note: The @Cacheable decorator is bypassed in tests via the autouse
    bypass_cacheable fixture, so each call hits the real function body.
    """

    async def test_unavailable_integrations_marked_false(
        self,
        mock_user_integration_repo,
        mock_composio_service,
        mock_token_repository,
    ):
        """Integrations with available=False should always return False."""
        unavailable = MagicMock()
        unavailable.available = False
        unavailable.id = "disabled_integration"
        unavailable.managed_by = "composio"

        with patch(
            "app.services.integrations.integration_status.OAUTH_INTEGRATIONS",
            [unavailable],
        ):
            result = await get_all_integrations_status("user123")

        assert result["disabled_integration"] is False

    async def test_integration_connected_in_mongodb(
        self,
        mock_user_integration_repo,
        mock_composio_service,
        mock_token_repository,
    ):
        """If user_integrations has status='connected', result should be True."""
        mock_user_integration_repo.list_for_user = AsyncMock(
            return_value=[_ui_doc("notion", "connected")]
        )

        integration = MagicMock()
        integration.id = "notion"
        integration.available = True
        integration.managed_by = "composio"
        integration.provider = "notion"
        integration.composio_config = MagicMock()

        with patch(
            "app.services.integrations.integration_status.OAUTH_INTEGRATIONS",
            [integration],
        ):
            result = await get_all_integrations_status("user123")

        assert result["notion"] is True

    async def test_integration_disconnected_in_mongodb(
        self,
        mock_user_integration_repo,
        mock_composio_service,
        mock_token_repository,
    ):
        """If user_integrations has status != 'connected', result should be False."""
        mock_user_integration_repo.list_for_user = AsyncMock(
            return_value=[_ui_doc("notion", "created")]
        )

        integration = MagicMock()
        integration.id = "notion"
        integration.available = True
        integration.managed_by = "composio"
        integration.provider = "notion"
        integration.composio_config = MagicMock()

        with patch(
            "app.services.integrations.integration_status.OAUTH_INTEGRATIONS",
            [integration],
        ):
            result = await get_all_integrations_status("user123")

        assert result["notion"] is False

    async def test_mcp_integration_not_in_mongo_returns_false(
        self,
        mock_user_integration_repo,
        mock_composio_service,
        mock_token_repository,
    ):
        """MCP integrations not in MongoDB should return False."""
        integration = MagicMock()
        integration.id = "deepwiki"
        integration.available = True
        integration.managed_by = "mcp"
        integration.provider = "deepwiki"

        with patch(
            "app.services.integrations.integration_status.OAUTH_INTEGRATIONS",
            [integration],
        ):
            result = await get_all_integrations_status("user123")

        assert result["deepwiki"] is False

    async def test_composio_integration_falls_back_to_composio_check(
        self,
        mock_user_integration_repo,
        mock_composio_service,
        mock_token_repository,
    ):
        """Composio integrations not in MongoDB should query Composio service."""
        mock_composio_service.check_connection_status = AsyncMock(return_value={"twitter": True})

        integration = MagicMock()
        integration.id = "twitter"
        integration.available = True
        integration.managed_by = "composio"
        integration.provider = "twitter"

        with patch(
            "app.services.integrations.integration_status.OAUTH_INTEGRATIONS",
            [integration],
        ):
            result = await get_all_integrations_status("user123")

        assert result["twitter"] is True
        # Batched by provider, for this user.
        mock_composio_service.check_connection_status.assert_awaited_once_with(
            ["twitter"], "user123"
        )
        mock_user_integration_repo.list_for_user.assert_awaited_once_with("user123", limit=100)

    async def test_a_provider_composio_does_not_report_is_not_connected(
        self,
        mock_user_integration_repo,
        mock_composio_service,
        mock_token_repository,
    ):
        """A provider missing from the batch answer reads as not connected, never as unknown."""
        mock_composio_service.check_connection_status = AsyncMock(return_value={})

        integration = MagicMock()
        integration.id = "twitter"
        integration.available = True
        integration.managed_by = "composio"
        integration.provider = "twitter"

        with patch(
            "app.services.integrations.integration_status.OAUTH_INTEGRATIONS",
            [integration],
        ):
            result = await get_all_integrations_status("user123")

        assert result == {"twitter": False}

    async def test_composio_batch_check_failure_returns_false(
        self,
        mock_user_integration_repo,
        mock_composio_service,
        mock_token_repository,
    ):
        """If Composio batch check raises, all Composio integrations are False."""
        mock_composio_service.check_connection_status = AsyncMock(
            side_effect=Exception("Composio API error")
        )

        integration = MagicMock()
        integration.id = "twitter"
        integration.available = True
        integration.managed_by = "composio"
        integration.provider = "twitter"

        with (
            patch(
                "app.services.integrations.integration_status.OAUTH_INTEGRATIONS",
                [integration],
            ),
            patch("app.services.integrations.integration_status.log") as log,
        ):
            result = await get_all_integrations_status("user123")

        assert result["twitter"] is False
        log.error.assert_called_once_with(
            f"{LogTag.OAUTH} Error batch checking Composio integrations",
            error="Composio API error",
            error_type="Exception",
            user_id="user123",
        )
        log.set.assert_called_once_with(oauth=OAuthContext(operation="status"), result_count=1)

    async def test_self_managed_integration_with_valid_token(
        self,
        mock_user_integration_repo,
        mock_composio_service,
        mock_token_repository,
    ):
        """Self-managed integrations check token repository for scopes."""
        mock_token_repository.get_token = AsyncMock(
            return_value={
                "scope": "https://www.googleapis.com/auth/calendar.events https://www.googleapis.com/auth/calendar.readonly",
            }
        )

        integration = MagicMock()
        integration.id = "googlecalendar"
        integration.available = True
        integration.managed_by = "self"
        integration.provider = "google"

        with (
            patch(
                "app.services.integrations.integration_status.OAUTH_INTEGRATIONS",
                [integration],
            ),
            patch(
                "app.services.integrations.integration_status.get_integration_scopes",
                return_value=[
                    "https://www.googleapis.com/auth/calendar.events",
                    "https://www.googleapis.com/auth/calendar.readonly",
                ],
            ) as scopes,
        ):
            result = await get_all_integrations_status("user123")

        assert result["googlecalendar"] is True
        # The token is read for this user's Google account and renewed if stale,
        # and the scopes it must carry are the integration's own.
        mock_token_repository.get_token.assert_awaited_once_with(
            "user123", "google", renew_if_expired=True
        )
        scopes.assert_called_once_with("googlecalendar")

    async def test_a_token_without_any_scope_grants_nothing(
        self,
        mock_user_integration_repo,
        mock_composio_service,
        mock_token_repository,
    ):
        mock_token_repository.get_token = AsyncMock(return_value={})

        integration = MagicMock()
        integration.id = "googlecalendar"
        integration.available = True
        integration.managed_by = "self"
        integration.provider = "google"

        with (
            patch(
                "app.services.integrations.integration_status.OAUTH_INTEGRATIONS",
                [integration],
            ),
            patch(
                "app.services.integrations.integration_status.get_integration_scopes",
                return_value=["https://www.googleapis.com/auth/calendar.events"],
            ),
        ):
            result = await get_all_integrations_status("user123")

        assert result["googlecalendar"] is False

    async def test_self_managed_integration_with_missing_scopes(
        self,
        mock_user_integration_repo,
        mock_composio_service,
        mock_token_repository,
    ):
        """Self-managed with partial scopes should return False."""
        mock_token_repository.get_token = AsyncMock(
            return_value={
                "scope": "https://www.googleapis.com/auth/calendar.readonly",
            }
        )

        integration = MagicMock()
        integration.id = "googlecalendar"
        integration.available = True
        integration.managed_by = "self"
        integration.provider = "google"

        with (
            patch(
                "app.services.integrations.integration_status.OAUTH_INTEGRATIONS",
                [integration],
            ),
            patch(
                "app.services.integrations.integration_status.get_integration_scopes",
                return_value=[
                    "https://www.googleapis.com/auth/calendar.events",
                    "https://www.googleapis.com/auth/calendar.readonly",
                ],
            ),
        ):
            result = await get_all_integrations_status("user123")

        assert result["googlecalendar"] is False

    async def test_self_managed_integration_with_no_token(
        self,
        mock_user_integration_repo,
        mock_composio_service,
        mock_token_repository,
    ):
        """Self-managed with no token at all should return False."""
        mock_token_repository.get_token = AsyncMock(side_effect=Exception("Token not found"))

        integration = MagicMock()
        integration.id = "googlecalendar"
        integration.available = True
        integration.managed_by = "self"
        integration.provider = "google"

        with (
            patch(
                "app.services.integrations.integration_status.OAUTH_INTEGRATIONS",
                [integration],
            ),
            patch(
                "app.services.integrations.integration_status.get_integration_scopes",
                return_value=["https://www.googleapis.com/auth/calendar.events"],
            ),
        ):
            result = await get_all_integrations_status("user123")

        assert result["googlecalendar"] is False

    async def test_custom_integrations_in_mongo_included(
        self,
        mock_user_integration_repo,
        mock_composio_service,
        mock_token_repository,
    ):
        """Custom integrations in MongoDB not in OAUTH_INTEGRATIONS are still included."""
        mock_user_integration_repo.list_for_user = AsyncMock(
            return_value=[_ui_doc("custom_tool", "connected")]
        )

        with patch(
            "app.services.integrations.integration_status.OAUTH_INTEGRATIONS",
            [],
        ):
            result = await get_all_integrations_status("user123")

        assert result["custom_tool"] is True

    async def test_mixed_integrations(
        self,
        mock_user_integration_repo,
        mock_composio_service,
        mock_token_repository,
    ):
        """Test a mix of connected, disconnected, and unavailable integrations."""
        mock_user_integration_repo.list_for_user = AsyncMock(
            return_value=[_ui_doc("notion", "connected")]
        )

        # Composio returns twitter as connected
        mock_composio_service.check_connection_status = AsyncMock(return_value={"slack": False})

        notion = MagicMock()
        notion.id = "notion"
        notion.available = True
        notion.managed_by = "composio"
        notion.provider = "notion"

        slack = MagicMock()
        slack.id = "slack"
        slack.available = True
        slack.managed_by = "composio"
        slack.provider = "slack"

        disabled = MagicMock()
        disabled.id = "disabled"
        disabled.available = False
        disabled.managed_by = "composio"
        disabled.provider = "disabled"

        mcp_int = MagicMock()
        mcp_int.id = "deepwiki"
        mcp_int.available = True
        mcp_int.managed_by = "mcp"

        with patch(
            "app.services.integrations.integration_status.OAUTH_INTEGRATIONS",
            [notion, slack, disabled, mcp_int],
        ):
            result = await get_all_integrations_status("user123")

        assert result["notion"] is True
        assert result["slack"] is False
        assert result["disabled"] is False
        assert result["deepwiki"] is False


# ---------------------------------------------------------------------------
# check_integration_status
# ---------------------------------------------------------------------------
