"""Unit tests for OAuth service operations."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from bson import ObjectId
from fastapi import HTTPException

from app.models.user_models import BioStatus
from app.services.oauth.oauth_service import (
    check_integration_status,
    check_multiple_integrations_status,
    get_all_integrations_status,
    handle_oauth_connection,
    store_user_info,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_users_collection():
    with patch("app.services.oauth.oauth_service.users_collection") as mock_col:
        yield mock_col


@pytest.fixture
def mock_user_integrations_collection():
    with patch(
        "app.services.oauth.oauth_service.user_integrations_collection"
    ) as mock_col:
        mock_cursor = AsyncMock()
        mock_cursor.to_list = AsyncMock(return_value=[])
        mock_col.find = MagicMock(return_value=mock_cursor)
        yield mock_col


@pytest.fixture
def mock_token_repository():
    with patch("app.services.oauth.oauth_service.token_repository") as mock_repo:
        yield mock_repo


@pytest.fixture
def mock_composio_service():
    mock_service = AsyncMock()
    mock_service.check_connection_status = AsyncMock(return_value={})
    with patch(
        "app.services.oauth.oauth_service.get_composio_service",
        return_value=mock_service,
    ):
        yield mock_service


@pytest.fixture
def mock_delete_cache():
    with patch(
        "app.services.oauth.oauth_service.delete_cache", new_callable=AsyncMock
    ) as mock_dc:
        yield mock_dc


@pytest.fixture
def mock_update_user_integration_status():
    with patch(
        "app.services.oauth.oauth_service.update_user_integration_status",
        new_callable=AsyncMock,
    ) as mock_fn:
        yield mock_fn


@pytest.fixture
def mock_websocket_manager():
    with patch("app.services.oauth.oauth_service.websocket_manager") as mock_ws:
        mock_ws.broadcast_to_user = AsyncMock()
        yield mock_ws


@pytest.fixture
def mock_redis_pool_manager():
    mock_pool = AsyncMock()
    mock_pool.enqueue_job = AsyncMock()
    with patch("app.services.oauth.oauth_service.RedisPoolManager") as mock_rpm:
        mock_rpm.get_pool = AsyncMock(return_value=mock_pool)
        yield mock_pool


@pytest.fixture
def mock_track_signup():
    with patch("app.services.oauth.oauth_service.track_signup") as mock_ts:
        yield mock_ts


@pytest.fixture
def mock_send_welcome_email():
    with patch(
        "app.services.oauth.oauth_service.send_welcome_email",
        new_callable=AsyncMock,
    ) as mock_swe:
        yield mock_swe


@pytest.fixture
def mock_add_contact_to_resend():
    with patch(
        "app.services.oauth.oauth_service.add_contact_to_resend",
        new_callable=AsyncMock,
    ) as mock_acr:
        yield mock_acr


@pytest.fixture
def mock_fetch_and_store_provider_metadata():
    with patch(
        "app.services.oauth.oauth_service.fetch_and_store_provider_metadata",
        new_callable=AsyncMock,
    ) as mock_fn:
        yield mock_fn


@pytest.fixture
def mock_provision_system_workflows():
    with patch(
        "app.services.oauth.oauth_service.provision_system_workflows",
        new_callable=AsyncMock,
    ) as mock_fn:
        yield mock_fn


@pytest.fixture(autouse=True)
def bypass_cacheable():
    """Bypass the @Cacheable decorator so tests call the real function.

    The Cacheable wrapper (defined in app.decorators.caching) closes over
    get_cache / set_cache imported from app.db.redis.  Patching them there
    ensures every cached call goes straight through to the wrapped function.
    """
    with (
        patch(
            "app.db.redis.redis_cache.get", new_callable=AsyncMock, return_value=None
        ),
        patch("app.db.redis.redis_cache.set", new_callable=AsyncMock),
    ):
        yield


def _make_integration_config(
    integration_id: str = "gmail",
    name: str = "Gmail",
    managed_by: str = "composio",
    associated_triggers: list | None = None,
    metadata_config: object | None = None,
):
    """Build a lightweight mock integration config object."""
    config = MagicMock()
    config.id = integration_id
    config.name = name
    config.managed_by = managed_by
    config.associated_triggers = associated_triggers or []
    config.metadata_config = metadata_config
    return config


# ---------------------------------------------------------------------------
# store_user_info
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestStoreUserInfo:
    async def test_raises_400_when_email_is_empty(self, mock_users_collection):
        with pytest.raises(HTTPException) as exc_info:
            await store_user_info("Test", "", "https://pic.example.com/pic.jpg")
        assert exc_info.value.status_code == 400
        assert "Email is required" in exc_info.value.detail

    async def test_raises_400_when_email_is_none(self, mock_users_collection):
        with pytest.raises(HTTPException) as exc_info:
            await store_user_info("Test", None, "https://pic.example.com/pic.jpg")
        assert exc_info.value.status_code == 400

    async def test_updates_existing_user_with_picture(self, mock_users_collection):
        oid = ObjectId()
        existing_user = {
            "_id": oid,
            "email": "alice@test.com",
            "name": "Alice",
            "picture": "https://old-pic.example.com/old.jpg",
        }
        mock_users_collection.find_one = AsyncMock(return_value=existing_user)
        mock_users_collection.update_one = AsyncMock()

        result = await store_user_info(
            "Alice Updated", "alice@test.com", "https://new-pic.example.com/new.jpg"
        )

        assert result == oid
        mock_users_collection.update_one.assert_awaited_once()
        call_args = mock_users_collection.update_one.call_args
        update_data = call_args[0][1]["$set"]
        assert update_data["name"] == "Alice Updated"
        assert update_data["picture"] == "https://new-pic.example.com/new.jpg"
        assert "updated_at" in update_data

    async def test_updates_existing_user_without_picture_keeps_existing(
        self, mock_users_collection
    ):
        oid = ObjectId()
        existing_user = {
            "_id": oid,
            "email": "alice@test.com",
            "name": "Alice",
            "picture": "https://existing.example.com/pic.jpg",
        }
        mock_users_collection.find_one = AsyncMock(return_value=existing_user)
        mock_users_collection.update_one = AsyncMock()

        result = await store_user_info("Alice Updated", "alice@test.com", None)

        assert result == oid
        call_args = mock_users_collection.update_one.call_args
        update_data = call_args[0][1]["$set"]
        # Should NOT set picture when no new URL provided and user has existing pic
        assert "picture" not in update_data

    async def test_updates_existing_user_without_picture_sets_empty_when_no_existing(
        self, mock_users_collection
    ):
        oid = ObjectId()
        existing_user = {
            "_id": oid,
            "email": "alice@test.com",
            "name": "Alice",
            # No "picture" field
        }
        mock_users_collection.find_one = AsyncMock(return_value=existing_user)
        mock_users_collection.update_one = AsyncMock()

        result = await store_user_info("Alice Updated", "alice@test.com", None)

        assert result == oid
        call_args = mock_users_collection.update_one.call_args
        update_data = call_args[0][1]["$set"]
        assert update_data["picture"] == ""

    async def test_creates_new_user_with_picture(
        self,
        mock_users_collection,
        mock_track_signup,
        mock_send_welcome_email,
        mock_add_contact_to_resend,
    ):
        mock_users_collection.find_one = AsyncMock(return_value=None)
        inserted_id = ObjectId()
        mock_result = MagicMock()
        mock_result.inserted_id = inserted_id
        mock_users_collection.insert_one = AsyncMock(return_value=mock_result)

        result = await store_user_info(
            "Bob", "bob@test.com", "https://pic.example.com/bob.jpg"
        )

        assert result == inserted_id
        call_args = mock_users_collection.insert_one.call_args
        user_data = call_args[0][0]
        assert user_data["name"] == "Bob"
        assert user_data["email"] == "bob@test.com"
        assert user_data["picture"] == "https://pic.example.com/bob.jpg"
        assert "created_at" in user_data
        assert "updated_at" in user_data

    async def test_creates_new_user_without_picture_defaults_to_empty(
        self,
        mock_users_collection,
        mock_track_signup,
        mock_send_welcome_email,
        mock_add_contact_to_resend,
    ):
        mock_users_collection.find_one = AsyncMock(return_value=None)
        inserted_id = ObjectId()
        mock_result = MagicMock()
        mock_result.inserted_id = inserted_id
        mock_users_collection.insert_one = AsyncMock(return_value=mock_result)

        result = await store_user_info("Bob", "bob@test.com", None)

        assert result == inserted_id
        call_args = mock_users_collection.insert_one.call_args
        user_data = call_args[0][0]
        assert user_data["picture"] == ""

    async def test_new_user_tracks_signup(
        self,
        mock_users_collection,
        mock_track_signup,
        mock_send_welcome_email,
        mock_add_contact_to_resend,
    ):
        mock_users_collection.find_one = AsyncMock(return_value=None)
        mock_result = MagicMock()
        mock_result.inserted_id = ObjectId()
        mock_users_collection.insert_one = AsyncMock(return_value=mock_result)

        await store_user_info("Bob", "bob@test.com", None)

        mock_track_signup.assert_called_once_with(
            user_id="bob@test.com",
            email="bob@test.com",
            name="Bob",
            signup_method="workos",
        )

    async def test_new_user_sends_welcome_email(
        self,
        mock_users_collection,
        mock_track_signup,
        mock_send_welcome_email,
        mock_add_contact_to_resend,
    ):
        mock_users_collection.find_one = AsyncMock(return_value=None)
        mock_result = MagicMock()
        mock_result.inserted_id = ObjectId()
        mock_users_collection.insert_one = AsyncMock(return_value=mock_result)

        await store_user_info("Bob", "bob@test.com", None)

        mock_send_welcome_email.assert_awaited_once_with("bob@test.com", "Bob")

    async def test_new_user_adds_contact_to_resend(
        self,
        mock_users_collection,
        mock_track_signup,
        mock_send_welcome_email,
        mock_add_contact_to_resend,
    ):
        mock_users_collection.find_one = AsyncMock(return_value=None)
        mock_result = MagicMock()
        mock_result.inserted_id = ObjectId()
        mock_users_collection.insert_one = AsyncMock(return_value=mock_result)

        await store_user_info("Bob", "bob@test.com", None)

        mock_add_contact_to_resend.assert_awaited_once_with("bob@test.com", "Bob")

    async def test_new_user_signup_tracking_failure_does_not_raise(
        self,
        mock_users_collection,
        mock_track_signup,
        mock_send_welcome_email,
        mock_add_contact_to_resend,
    ):
        mock_users_collection.find_one = AsyncMock(return_value=None)
        mock_result = MagicMock()
        mock_result.inserted_id = ObjectId()
        mock_users_collection.insert_one = AsyncMock(return_value=mock_result)
        mock_track_signup.side_effect = Exception("PostHog unavailable")

        # Should not raise
        result = await store_user_info("Bob", "bob@test.com", None)
        assert result == mock_result.inserted_id

    async def test_new_user_welcome_email_failure_does_not_raise(
        self,
        mock_users_collection,
        mock_track_signup,
        mock_send_welcome_email,
        mock_add_contact_to_resend,
    ):
        mock_users_collection.find_one = AsyncMock(return_value=None)
        mock_result = MagicMock()
        mock_result.inserted_id = ObjectId()
        mock_users_collection.insert_one = AsyncMock(return_value=mock_result)
        mock_send_welcome_email.side_effect = Exception("SMTP error")

        result = await store_user_info("Bob", "bob@test.com", None)
        assert result == mock_result.inserted_id

    async def test_new_user_resend_failure_does_not_raise(
        self,
        mock_users_collection,
        mock_track_signup,
        mock_send_welcome_email,
        mock_add_contact_to_resend,
    ):
        mock_users_collection.find_one = AsyncMock(return_value=None)
        mock_result = MagicMock()
        mock_result.inserted_id = ObjectId()
        mock_users_collection.insert_one = AsyncMock(return_value=mock_result)
        mock_add_contact_to_resend.side_effect = Exception("Resend API error")

        result = await store_user_info("Bob", "bob@test.com", None)
        assert result == mock_result.inserted_id


# ---------------------------------------------------------------------------
# get_all_integrations_status
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestGetAllIntegrationsStatus:
    """Tests for get_all_integrations_status.

    Note: The @Cacheable decorator is bypassed in tests via the autouse
    bypass_cacheable fixture, so each call hits the real function body.
    """

    async def test_unavailable_integrations_marked_false(
        self,
        mock_user_integrations_collection,
        mock_composio_service,
        mock_token_repository,
    ):
        """Integrations with available=False should always return False."""
        unavailable = MagicMock()
        unavailable.available = False
        unavailable.id = "disabled_integration"
        unavailable.managed_by = "composio"

        with patch(
            "app.services.oauth.oauth_service.OAUTH_INTEGRATIONS",
            [unavailable],
        ):
            result = await get_all_integrations_status("user123")

        assert result["disabled_integration"] is False

    async def test_integration_connected_in_mongodb(
        self,
        mock_user_integrations_collection,
        mock_composio_service,
        mock_token_repository,
    ):
        """If user_integrations has status='connected', result should be True."""
        mock_cursor = AsyncMock()
        mock_cursor.to_list = AsyncMock(
            return_value=[
                {"integration_id": "notion", "status": "connected"},
            ]
        )
        mock_user_integrations_collection.find = MagicMock(return_value=mock_cursor)

        integration = MagicMock()
        integration.id = "notion"
        integration.available = True
        integration.managed_by = "composio"
        integration.provider = "notion"
        integration.composio_config = MagicMock()

        with patch(
            "app.services.oauth.oauth_service.OAUTH_INTEGRATIONS",
            [integration],
        ):
            result = await get_all_integrations_status("user123")

        assert result["notion"] is True

    async def test_integration_disconnected_in_mongodb(
        self,
        mock_user_integrations_collection,
        mock_composio_service,
        mock_token_repository,
    ):
        """If user_integrations has status != 'connected', result should be False."""
        mock_cursor = AsyncMock()
        mock_cursor.to_list = AsyncMock(
            return_value=[
                {"integration_id": "notion", "status": "created"},
            ]
        )
        mock_user_integrations_collection.find = MagicMock(return_value=mock_cursor)

        integration = MagicMock()
        integration.id = "notion"
        integration.available = True
        integration.managed_by = "composio"
        integration.provider = "notion"
        integration.composio_config = MagicMock()

        with patch(
            "app.services.oauth.oauth_service.OAUTH_INTEGRATIONS",
            [integration],
        ):
            result = await get_all_integrations_status("user123")

        assert result["notion"] is False

    async def test_mcp_integration_not_in_mongo_returns_false(
        self,
        mock_user_integrations_collection,
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
            "app.services.oauth.oauth_service.OAUTH_INTEGRATIONS",
            [integration],
        ):
            result = await get_all_integrations_status("user123")

        assert result["deepwiki"] is False

    async def test_composio_integration_falls_back_to_composio_check(
        self,
        mock_user_integrations_collection,
        mock_composio_service,
        mock_token_repository,
    ):
        """Composio integrations not in MongoDB should query Composio service."""
        mock_composio_service.check_connection_status = AsyncMock(
            return_value={"twitter": True}
        )

        integration = MagicMock()
        integration.id = "twitter"
        integration.available = True
        integration.managed_by = "composio"
        integration.provider = "twitter"

        with patch(
            "app.services.oauth.oauth_service.OAUTH_INTEGRATIONS",
            [integration],
        ):
            result = await get_all_integrations_status("user123")

        assert result["twitter"] is True
        mock_composio_service.check_connection_status.assert_awaited_once()

    async def test_composio_batch_check_failure_returns_false(
        self,
        mock_user_integrations_collection,
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

        with patch(
            "app.services.oauth.oauth_service.OAUTH_INTEGRATIONS",
            [integration],
        ):
            result = await get_all_integrations_status("user123")

        assert result["twitter"] is False

    async def test_self_managed_integration_with_valid_token(
        self,
        mock_user_integrations_collection,
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
                "app.services.oauth.oauth_service.OAUTH_INTEGRATIONS",
                [integration],
            ),
            patch(
                "app.services.oauth.oauth_service.get_integration_scopes",
                return_value=[
                    "https://www.googleapis.com/auth/calendar.events",
                    "https://www.googleapis.com/auth/calendar.readonly",
                ],
            ),
        ):
            result = await get_all_integrations_status("user123")

        assert result["googlecalendar"] is True

    async def test_self_managed_integration_with_missing_scopes(
        self,
        mock_user_integrations_collection,
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
                "app.services.oauth.oauth_service.OAUTH_INTEGRATIONS",
                [integration],
            ),
            patch(
                "app.services.oauth.oauth_service.get_integration_scopes",
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
        mock_user_integrations_collection,
        mock_composio_service,
        mock_token_repository,
    ):
        """Self-managed with no token at all should return False."""
        mock_token_repository.get_token = AsyncMock(
            side_effect=Exception("Token not found")
        )

        integration = MagicMock()
        integration.id = "googlecalendar"
        integration.available = True
        integration.managed_by = "self"
        integration.provider = "google"

        with (
            patch(
                "app.services.oauth.oauth_service.OAUTH_INTEGRATIONS",
                [integration],
            ),
            patch(
                "app.services.oauth.oauth_service.get_integration_scopes",
                return_value=["https://www.googleapis.com/auth/calendar.events"],
            ),
        ):
            result = await get_all_integrations_status("user123")

        assert result["googlecalendar"] is False

    async def test_custom_integrations_in_mongo_included(
        self,
        mock_user_integrations_collection,
        mock_composio_service,
        mock_token_repository,
    ):
        """Custom integrations in MongoDB not in OAUTH_INTEGRATIONS are still included."""
        mock_cursor = AsyncMock()
        mock_cursor.to_list = AsyncMock(
            return_value=[
                {"integration_id": "custom_tool", "status": "connected"},
            ]
        )
        mock_user_integrations_collection.find = MagicMock(return_value=mock_cursor)

        with patch(
            "app.services.oauth.oauth_service.OAUTH_INTEGRATIONS",
            [],
        ):
            result = await get_all_integrations_status("user123")

        assert result["custom_tool"] is True

    async def test_mixed_integrations(
        self,
        mock_user_integrations_collection,
        mock_composio_service,
        mock_token_repository,
    ):
        """Test a mix of connected, disconnected, and unavailable integrations."""
        mock_cursor = AsyncMock()
        mock_cursor.to_list = AsyncMock(
            return_value=[
                {"integration_id": "notion", "status": "connected"},
            ]
        )
        mock_user_integrations_collection.find = MagicMock(return_value=mock_cursor)

        # Composio returns twitter as connected
        mock_composio_service.check_connection_status = AsyncMock(
            return_value={"slack": False}
        )

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
            "app.services.oauth.oauth_service.OAUTH_INTEGRATIONS",
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


@pytest.mark.unit
class TestCheckIntegrationStatus:
    async def test_returns_true_for_connected_integration(self):
        with patch(
            "app.services.oauth.oauth_service.get_all_integrations_status",
            new_callable=AsyncMock,
            return_value={"gmail": True, "notion": False},
        ):
            result = await check_integration_status("gmail", "user123")
        assert result is True

    async def test_returns_false_for_disconnected_integration(self):
        with patch(
            "app.services.oauth.oauth_service.get_all_integrations_status",
            new_callable=AsyncMock,
            return_value={"gmail": True, "notion": False},
        ):
            result = await check_integration_status("notion", "user123")
        assert result is False

    async def test_returns_false_for_unknown_integration(self):
        with patch(
            "app.services.oauth.oauth_service.get_all_integrations_status",
            new_callable=AsyncMock,
            return_value={"gmail": True},
        ):
            result = await check_integration_status("unknown", "user123")
        assert result is False

    async def test_returns_false_on_exception(self):
        with patch(
            "app.services.oauth.oauth_service.get_all_integrations_status",
            new_callable=AsyncMock,
            side_effect=Exception("DB error"),
        ):
            result = await check_integration_status("gmail", "user123")
        assert result is False


# ---------------------------------------------------------------------------
# check_multiple_integrations_status
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestCheckMultipleIntegrationsStatus:
    async def test_returns_status_for_requested_integrations(self):
        with patch(
            "app.services.oauth.oauth_service.get_all_integrations_status",
            new_callable=AsyncMock,
            return_value={"gmail": True, "notion": False, "slack": True},
        ):
            result = await check_multiple_integrations_status(
                ["gmail", "notion"], "user123"
            )

        assert result == {"gmail": True, "notion": False}

    async def test_unknown_integrations_default_to_false(self):
        with patch(
            "app.services.oauth.oauth_service.get_all_integrations_status",
            new_callable=AsyncMock,
            return_value={"gmail": True},
        ):
            result = await check_multiple_integrations_status(
                ["gmail", "unknown"], "user123"
            )

        assert result == {"gmail": True, "unknown": False}

    async def test_returns_all_false_on_exception(self):
        with patch(
            "app.services.oauth.oauth_service.get_all_integrations_status",
            new_callable=AsyncMock,
            side_effect=Exception("Service error"),
        ):
            result = await check_multiple_integrations_status(
                ["gmail", "notion"], "user123"
            )

        assert result == {"gmail": False, "notion": False}

    async def test_empty_list_returns_empty_dict(self):
        with patch(
            "app.services.oauth.oauth_service.get_all_integrations_status",
            new_callable=AsyncMock,
            return_value={"gmail": True},
        ):
            result = await check_multiple_integrations_status([], "user123")

        assert result == {}


# ---------------------------------------------------------------------------
# handle_oauth_connection
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestHandleOAuthConnection:
    async def test_invalidates_cache_and_updates_integration_status(
        self,
        mock_delete_cache,
        mock_update_user_integration_status,
    ):
        """Core behavior: invalidate cache and update integration status."""
        config = _make_integration_config(
            integration_id="notion",
            name="Notion",
        )
        background_tasks = MagicMock()

        await handle_oauth_connection(
            user_id="user123",
            integration_config=config,
            connected_account_id="acc_123",
            background_tasks=background_tasks,
        )

        mock_delete_cache.assert_awaited_once_with("OAUTH_STATUS:user123")
        mock_update_user_integration_status.assert_awaited_once_with(
            "user123", "notion", "connected"
        )

    async def test_sets_up_triggers_when_present(
        self,
        mock_delete_cache,
        mock_update_user_integration_status,
    ):
        """If integration has associated_triggers, schedule trigger setup."""
        mock_trigger = MagicMock()
        config = _make_integration_config(
            integration_id="notion",
            associated_triggers=[mock_trigger],
        )
        background_tasks = MagicMock()

        with patch(
            "app.services.oauth.oauth_service.get_composio_service"
        ) as mock_get_cs:
            mock_cs = MagicMock()
            mock_get_cs.return_value = mock_cs

            await handle_oauth_connection(
                user_id="user123",
                integration_config=config,
                connected_account_id="acc_123",
                background_tasks=background_tasks,
            )

        background_tasks.add_task.assert_any_call(
            mock_cs.handle_subscribe_trigger,
            user_id="user123",
            triggers=[mock_trigger],
        )

    async def test_does_not_setup_triggers_when_empty(
        self,
        mock_delete_cache,
        mock_update_user_integration_status,
    ):
        """If no associated_triggers, do not call get_composio_service for triggers."""
        config = _make_integration_config(
            integration_id="notion",
            associated_triggers=[],
        )
        background_tasks = MagicMock()

        await handle_oauth_connection(
            user_id="user123",
            integration_config=config,
            connected_account_id="acc_123",
            background_tasks=background_tasks,
        )

        # No trigger-related background task should be queued
        for call in background_tasks.add_task.call_args_list:
            func = call[0][0] if call[0] else None
            # Ensure no handle_subscribe_trigger was added
            if func and hasattr(func, "__name__"):
                assert func.__name__ != "handle_subscribe_trigger"

    async def test_gmail_connection_queues_email_processing(
        self,
        mock_users_collection,
        mock_delete_cache,
        mock_update_user_integration_status,
        mock_redis_pool_manager,
    ):
        """Gmail integration should queue email processing via ARQ."""
        mock_users_collection.find_one = AsyncMock(
            return_value={
                "_id": ObjectId("507f1f77bcf86cd799439011"),
                "onboarding": {"completed": False},
            }
        )
        config = _make_integration_config(integration_id="gmail")
        background_tasks = MagicMock()

        await handle_oauth_connection(
            user_id="user123",
            integration_config=config,
            connected_account_id="acc_123",
            background_tasks=background_tasks,
        )

        mock_redis_pool_manager.enqueue_job.assert_awaited_once_with(
            "process_gmail_emails_to_memory", "user123"
        )

    async def test_gmail_connection_updates_bio_status_when_no_gmail(
        self,
        mock_users_collection,
        mock_delete_cache,
        mock_update_user_integration_status,
        mock_websocket_manager,
        mock_redis_pool_manager,
    ):
        """Gmail connection should update bio_status from no_gmail to processing."""
        user_id = "507f1f77bcf86cd799439011"
        mock_users_collection.find_one = AsyncMock(
            return_value={
                "_id": ObjectId(user_id),
                "onboarding": {
                    "completed": True,
                    "bio_status": BioStatus.NO_GMAIL,
                },
            }
        )
        mock_users_collection.update_one = AsyncMock()
        config = _make_integration_config(integration_id="gmail")
        background_tasks = MagicMock()

        await handle_oauth_connection(
            user_id=user_id,
            integration_config=config,
            connected_account_id="acc_123",
            background_tasks=background_tasks,
        )

        mock_users_collection.update_one.assert_awaited_once()
        call_args = mock_users_collection.update_one.call_args
        update_data = call_args[0][1]["$set"]
        assert update_data["onboarding.bio_status"] == BioStatus.PROCESSING

    async def test_gmail_connection_sends_websocket_update(
        self,
        mock_users_collection,
        mock_delete_cache,
        mock_update_user_integration_status,
        mock_websocket_manager,
        mock_redis_pool_manager,
    ):
        """Gmail with no_gmail bio_status should broadcast WebSocket update."""
        user_id = "507f1f77bcf86cd799439011"
        mock_users_collection.find_one = AsyncMock(
            return_value={
                "_id": ObjectId(user_id),
                "onboarding": {
                    "completed": True,
                    "bio_status": "no_gmail",
                },
            }
        )
        mock_users_collection.update_one = AsyncMock()
        config = _make_integration_config(integration_id="gmail")
        background_tasks = MagicMock()

        await handle_oauth_connection(
            user_id=user_id,
            integration_config=config,
            connected_account_id="acc_123",
            background_tasks=background_tasks,
        )

        mock_websocket_manager.broadcast_to_user.assert_awaited_once()
        call_args = mock_websocket_manager.broadcast_to_user.call_args
        assert call_args.kwargs["user_id"] == user_id
        assert call_args.kwargs["message"]["type"] == "bio_status_update"

    async def test_gmail_connection_skips_bio_update_when_already_completed(
        self,
        mock_users_collection,
        mock_delete_cache,
        mock_update_user_integration_status,
        mock_redis_pool_manager,
    ):
        """If bio_status is 'completed', don't update to processing."""
        mock_users_collection.find_one = AsyncMock(
            return_value={
                "_id": ObjectId("507f1f77bcf86cd799439011"),
                "onboarding": {
                    "completed": True,
                    "bio_status": BioStatus.COMPLETED,
                },
            }
        )
        mock_users_collection.update_one = AsyncMock()
        config = _make_integration_config(integration_id="gmail")
        background_tasks = MagicMock()

        await handle_oauth_connection(
            user_id="user123",
            integration_config=config,
            connected_account_id="acc_123",
            background_tasks=background_tasks,
        )

        mock_users_collection.update_one.assert_not_awaited()

    async def test_gmail_connection_skips_bio_when_onboarding_not_completed(
        self,
        mock_users_collection,
        mock_delete_cache,
        mock_update_user_integration_status,
        mock_redis_pool_manager,
    ):
        """If onboarding not completed, don't update bio_status."""
        mock_users_collection.find_one = AsyncMock(
            return_value={
                "_id": ObjectId("507f1f77bcf86cd799439011"),
                "onboarding": {
                    "completed": False,
                    "bio_status": BioStatus.NO_GMAIL,
                },
            }
        )
        mock_users_collection.update_one = AsyncMock()
        config = _make_integration_config(integration_id="gmail")
        background_tasks = MagicMock()

        await handle_oauth_connection(
            user_id="user123",
            integration_config=config,
            connected_account_id="acc_123",
            background_tasks=background_tasks,
        )

        mock_users_collection.update_one.assert_not_awaited()

    async def test_gmail_arq_queue_failure_does_not_raise(
        self,
        mock_users_collection,
        mock_delete_cache,
        mock_update_user_integration_status,
    ):
        """ARQ enqueue failure should be logged, not raised."""
        mock_users_collection.find_one = AsyncMock(
            return_value={
                "_id": ObjectId("507f1f77bcf86cd799439011"),
                "onboarding": {"completed": False},
            }
        )
        config = _make_integration_config(integration_id="gmail")
        background_tasks = MagicMock()

        with patch("app.services.oauth.oauth_service.RedisPoolManager") as mock_rpm:
            mock_pool = AsyncMock()
            mock_pool.enqueue_job = AsyncMock(side_effect=Exception("Redis down"))
            mock_rpm.get_pool = AsyncMock(return_value=mock_pool)

            # Should not raise
            await handle_oauth_connection(
                user_id="user123",
                integration_config=config,
                connected_account_id="acc_123",
                background_tasks=background_tasks,
            )

    async def test_non_gmail_connection_skips_email_processing(
        self,
        mock_delete_cache,
        mock_update_user_integration_status,
    ):
        """Non-Gmail integrations should not queue email processing."""
        config = _make_integration_config(integration_id="notion")
        background_tasks = MagicMock()

        with patch("app.services.oauth.oauth_service.RedisPoolManager") as mock_rpm:
            await handle_oauth_connection(
                user_id="user123",
                integration_config=config,
                connected_account_id="acc_123",
                background_tasks=background_tasks,
            )

            mock_rpm.get_pool.assert_not_called()

    async def test_metadata_config_queues_metadata_fetch(
        self,
        mock_delete_cache,
        mock_update_user_integration_status,
        mock_fetch_and_store_provider_metadata,
    ):
        """If integration has metadata_config, schedule background metadata fetch."""
        mock_metadata = MagicMock()
        config = _make_integration_config(
            integration_id="slack",
            name="Slack",
            metadata_config=mock_metadata,
        )
        background_tasks = MagicMock()

        await handle_oauth_connection(
            user_id="user123",
            integration_config=config,
            connected_account_id="acc_123",
            background_tasks=background_tasks,
        )

        # fetch_and_store_provider_metadata should be added as a background task
        background_tasks.add_task.assert_any_call(
            mock_fetch_and_store_provider_metadata,
            user_id="user123",
            integration_id="slack",
        )

    async def test_no_metadata_config_skips_metadata_fetch(
        self,
        mock_delete_cache,
        mock_update_user_integration_status,
    ):
        """If no metadata_config, should not schedule metadata fetch."""
        config = _make_integration_config(
            integration_id="notion",
            metadata_config=None,
        )
        background_tasks = MagicMock()

        await handle_oauth_connection(
            user_id="user123",
            integration_config=config,
            connected_account_id="acc_123",
            background_tasks=background_tasks,
        )

        # No fetch_and_store_provider_metadata call
        for call in background_tasks.add_task.call_args_list:
            func_called = call[0][0]
            func_name = getattr(func_called, "__name__", str(func_called))
            assert "fetch_and_store_provider_metadata" not in func_name

    async def test_gmail_provisions_system_workflows(
        self,
        mock_users_collection,
        mock_delete_cache,
        mock_update_user_integration_status,
        mock_provision_system_workflows,
        mock_redis_pool_manager,
    ):
        """Gmail connection should provision system workflows."""
        mock_users_collection.find_one = AsyncMock(
            return_value={
                "_id": ObjectId("507f1f77bcf86cd799439011"),
                "onboarding": {"completed": False},
            }
        )
        config = _make_integration_config(integration_id="gmail", name="Gmail")
        background_tasks = MagicMock()

        await handle_oauth_connection(
            user_id="user123",
            integration_config=config,
            connected_account_id="acc_123",
            background_tasks=background_tasks,
        )

        background_tasks.add_task.assert_any_call(
            mock_provision_system_workflows,
            user_id="user123",
            integration_id="gmail",
            integration_display_name="Gmail",
        )

    async def test_googlecalendar_provisions_system_workflows(
        self,
        mock_delete_cache,
        mock_update_user_integration_status,
        mock_provision_system_workflows,
    ):
        """Google Calendar connection should provision system workflows."""
        config = _make_integration_config(
            integration_id="googlecalendar",
            name="Google Calendar",
        )
        background_tasks = MagicMock()

        await handle_oauth_connection(
            user_id="user123",
            integration_config=config,
            connected_account_id="acc_123",
            background_tasks=background_tasks,
        )

        background_tasks.add_task.assert_any_call(
            mock_provision_system_workflows,
            user_id="user123",
            integration_id="googlecalendar",
            integration_display_name="Google Calendar",
        )

    async def test_non_gmail_non_calendar_skips_system_workflow_provisioning(
        self,
        mock_delete_cache,
        mock_update_user_integration_status,
    ):
        """Non-Gmail/Calendar integrations should not provision system workflows."""
        config = _make_integration_config(
            integration_id="notion",
            name="Notion",
        )
        background_tasks = MagicMock()

        with patch(
            "app.services.oauth.oauth_service.provision_system_workflows"
        ) as mock_psw:
            await handle_oauth_connection(
                user_id="user123",
                integration_config=config,
                connected_account_id="acc_123",
                background_tasks=background_tasks,
            )

            # provision_system_workflows should NOT appear in any background task
            for call in background_tasks.add_task.call_args_list:
                assert call[0][0] is not mock_psw

    async def test_cache_invalidation_failure_does_not_raise(
        self,
        mock_update_user_integration_status,
    ):
        """Cache invalidation failure should be logged, not raised."""
        config = _make_integration_config(integration_id="notion")
        background_tasks = MagicMock()

        with patch(
            "app.services.oauth.oauth_service.delete_cache",
            new_callable=AsyncMock,
            side_effect=Exception("Redis down"),
        ):
            # Should not raise
            await handle_oauth_connection(
                user_id="user123",
                integration_config=config,
                connected_account_id="acc_123",
                background_tasks=background_tasks,
            )

    async def test_integration_status_update_failure_does_not_raise(
        self,
        mock_delete_cache,
    ):
        """Integration status update failure should be logged, not raised."""
        config = _make_integration_config(integration_id="notion")
        background_tasks = MagicMock()

        with patch(
            "app.services.oauth.oauth_service.update_user_integration_status",
            new_callable=AsyncMock,
            side_effect=Exception("MongoDB down"),
        ):
            # Should not raise
            await handle_oauth_connection(
                user_id="user123",
                integration_config=config,
                connected_account_id="acc_123",
                background_tasks=background_tasks,
            )

    async def test_websocket_failure_does_not_block_flow(
        self,
        mock_users_collection,
        mock_delete_cache,
        mock_update_user_integration_status,
        mock_redis_pool_manager,
    ):
        """WebSocket broadcast failure should not block the OAuth flow."""
        mock_users_collection.find_one = AsyncMock(
            return_value={
                "_id": ObjectId("507f1f77bcf86cd799439011"),
                "onboarding": {
                    "completed": True,
                    "bio_status": BioStatus.NO_GMAIL,
                },
            }
        )
        mock_users_collection.update_one = AsyncMock()
        config = _make_integration_config(integration_id="gmail")
        background_tasks = MagicMock()

        with patch("app.services.oauth.oauth_service.websocket_manager") as mock_ws:
            mock_ws.broadcast_to_user = AsyncMock(
                side_effect=Exception("WS connection lost")
            )

            # Should not raise
            await handle_oauth_connection(
                user_id="user123",
                integration_config=config,
                connected_account_id="acc_123",
                background_tasks=background_tasks,
            )
