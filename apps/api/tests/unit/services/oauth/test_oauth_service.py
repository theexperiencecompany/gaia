"""Unit tests for OAuth service operations."""

from unittest.mock import AsyncMock, MagicMock, patch

from bson import ObjectId
from fastapi import HTTPException
import pytest
from tests.factories import make_integration_config

from app.models.integration_models import UserIntegrationDocument
from app.models.user_models import BioStatus, UserDocument
from app.services.oauth.oauth_service import (
    check_integration_status,
    check_multiple_integrations_status,
    get_all_integrations_status,
    handle_oauth_connection,
    store_user_info,
)
from app.services.triggers.subscription_service import (
    resync_subscriptions_for_trigger_names,
)
from app.services.workflow.integration_pause import (
    resume_workflows_for_reconnected_integration,
)


def _ui_doc(integration_id: str, status: str) -> UserIntegrationDocument:
    """Build a UserIntegrationDocument as list_for_user would return it."""
    return UserIntegrationDocument(user_id="user123", integration_id=integration_id, status=status)


# ---------------------------------------------------------------------------
# store_user_info
# ---------------------------------------------------------------------------


class TestStoreUserInfo:
    async def test_raises_400_when_email_is_empty(self, mock_user_repo):
        with pytest.raises(HTTPException) as exc_info:
            await store_user_info("Test", "", "https://pic.example.com/pic.jpg")
        assert exc_info.value.status_code == 400
        assert "Email is required" in exc_info.value.detail

    async def test_raises_400_when_email_is_none(self, mock_user_repo):
        with pytest.raises(HTTPException) as exc_info:
            await store_user_info("Test", None, "https://pic.example.com/pic.jpg")
        assert exc_info.value.status_code == 400

    async def test_updates_existing_user_with_picture(self, mock_user_repo, mock_track_login):
        uid = str(ObjectId())
        mock_user_repo.get_by_email.return_value = UserDocument(
            id=uid,
            email="alice@test.com",
            name="Alice",
            picture="https://old-pic.example.com/old.jpg",
        )

        result = await store_user_info(
            "Alice Updated", "alice@test.com", "https://new-pic.example.com/new.jpg"
        )

        assert result == (uid, False)
        mock_user_repo.update.assert_awaited_once()
        doc_id, update = mock_user_repo.update.call_args.args
        assert doc_id == uid
        fields = update.model_dump(exclude_unset=True)
        assert fields["picture"] == "https://new-pic.example.com/new.jpg"

    @pytest.mark.regression
    async def test_login_never_overwrites_a_stored_name(self, mock_user_repo, mock_track_login):
        """The user corrected their name in settings; WorkOS still sends its own
        guess on every login and used to clobber the correction."""
        uid = str(ObjectId())
        mock_user_repo.get_by_email.return_value = UserDocument(
            id=uid,
            email="alice@test.com",
            name="Alice Wonderland",
            picture="https://existing.example.com/pic.jpg",
        )

        await store_user_info("alice", "alice@test.com", "https://new-pic.example.com/new.jpg")

        fields = mock_user_repo.update.call_args.args[1].model_dump(exclude_unset=True)
        assert "name" not in fields
        assert mock_track_login.call_args.kwargs["name"] == "Alice Wonderland"

    async def test_login_fills_an_empty_stored_name(self, mock_user_repo, mock_track_login):
        uid = str(ObjectId())
        mock_user_repo.get_by_email.return_value = UserDocument(
            id=uid,
            email="alice@test.com",
            name="   ",
            picture="https://existing.example.com/pic.jpg",
        )

        await store_user_info("Alice Wonderland", "alice@test.com", None)

        fields = mock_user_repo.update.call_args.args[1].model_dump(exclude_unset=True)
        assert fields["name"] == "Alice Wonderland"
        assert mock_track_login.call_args.kwargs["name"] == "Alice Wonderland"

    async def test_updates_existing_user_without_picture_keeps_existing(
        self, mock_user_repo, mock_track_login
    ):
        uid = str(ObjectId())
        mock_user_repo.get_by_email.return_value = UserDocument(
            id=uid,
            email="alice@test.com",
            name="Alice",
            picture="https://existing.example.com/pic.jpg",
        )

        result = await store_user_info("Alice Updated", "alice@test.com", None)

        assert result == (uid, False)
        # Nothing to write: no new picture URL and the stored name wins, so the
        # login must not touch the document at all.
        mock_user_repo.update.assert_not_awaited()

    async def test_updates_existing_user_without_picture_sets_empty_when_no_existing(
        self, mock_user_repo, mock_track_login
    ):
        uid = str(ObjectId())
        mock_user_repo.get_by_email.return_value = UserDocument(
            id=uid,
            email="alice@test.com",
            name="Alice",  # no picture
        )

        result = await store_user_info("Alice Updated", "alice@test.com", None)

        assert result == (uid, False)
        fields = mock_user_repo.update.call_args.args[1].model_dump(exclude_unset=True)
        assert fields["picture"] == ""

    async def test_creates_new_user_with_picture(
        self,
        mock_user_repo,
        mock_track_signup,
        mock_send_welcome_email,
        mock_add_marketing_contact,
    ):
        uid = str(ObjectId())
        mock_user_repo.get_by_email.return_value = None
        mock_user_repo.create.return_value = UserDocument(
            id=uid, name="Bob", email="bob@test.com", picture="https://pic.example.com/bob.jpg"
        )

        result = await store_user_info("Bob", "bob@test.com", "https://pic.example.com/bob.jpg")

        assert result == (uid, True)
        created = mock_user_repo.create.call_args.args[0]
        assert created.name == "Bob"
        assert created.email == "bob@test.com"
        assert created.picture == "https://pic.example.com/bob.jpg"

    async def test_creates_new_user_without_picture_defaults_to_empty(
        self,
        mock_user_repo,
        mock_track_signup,
        mock_send_welcome_email,
        mock_add_marketing_contact,
    ):
        uid = str(ObjectId())
        mock_user_repo.get_by_email.return_value = None
        mock_user_repo.create.return_value = UserDocument(id=uid, name="Bob", email="bob@test.com")

        result = await store_user_info("Bob", "bob@test.com", None)

        assert result == (uid, True)
        assert mock_user_repo.create.call_args.args[0].picture == ""

    @pytest.mark.regression
    async def test_new_user_without_a_workos_name_gets_one_derived_from_the_email(
        self,
        mock_user_repo,
        mock_track_signup,
        mock_send_welcome_email,
        mock_add_marketing_contact,
    ):
        """WorkOS has no first/last name for email-code signups; storing "" left
        the user (and every greeting, email and prompt) nameless forever."""
        uid = str(ObjectId())
        mock_user_repo.get_by_email.return_value = None
        mock_user_repo.create.return_value = UserDocument(id=uid)

        await store_user_info("", "aryan.randeriya@test.com", None)

        assert mock_user_repo.create.call_args.args[0].name == "Aryan Randeriya"
        assert mock_track_signup.call_args.kwargs["name"] == "Aryan Randeriya"
        mock_send_welcome_email.assert_awaited_once_with(
            "aryan.randeriya@test.com", "Aryan Randeriya"
        )
        mock_add_marketing_contact.assert_awaited_once_with(
            "aryan.randeriya@test.com", "Aryan Randeriya"
        )

    async def test_new_user_keeps_the_workos_name_when_there_is_one(
        self,
        mock_user_repo,
        mock_track_signup,
        mock_send_welcome_email,
        mock_add_marketing_contact,
    ):
        mock_user_repo.get_by_email.return_value = None
        mock_user_repo.create.return_value = UserDocument(id=str(ObjectId()))

        await store_user_info("Bob Vance", "bob.vance@test.com", None)

        assert mock_user_repo.create.call_args.args[0].name == "Bob Vance"

    async def test_new_user_tracks_signup(
        self,
        mock_user_repo,
        mock_track_signup,
        mock_send_welcome_email,
        mock_add_marketing_contact,
    ):
        mock_user_repo.get_by_email.return_value = None
        created = UserDocument(id=str(ObjectId()))
        mock_user_repo.create.return_value = created

        await store_user_info("Bob", "bob@test.com", None)

        mock_track_signup.assert_called_once_with(
            user_id=created.id,
            email="bob@test.com",
            name="Bob",
            signup_method="workos",
        )

    async def test_new_user_sends_welcome_email(
        self,
        mock_user_repo,
        mock_track_signup,
        mock_send_welcome_email,
        mock_add_marketing_contact,
    ):
        mock_user_repo.get_by_email.return_value = None
        mock_user_repo.create.return_value = UserDocument(id=str(ObjectId()))

        await store_user_info("Bob", "bob@test.com", None)

        mock_send_welcome_email.assert_awaited_once_with("bob@test.com", "Bob")

    async def test_new_user_adds_contact_to_resend(
        self,
        mock_user_repo,
        mock_track_signup,
        mock_send_welcome_email,
        mock_add_marketing_contact,
    ):
        mock_user_repo.get_by_email.return_value = None
        mock_user_repo.create.return_value = UserDocument(id=str(ObjectId()))

        await store_user_info("Bob", "bob@test.com", None)

        mock_add_marketing_contact.assert_awaited_once_with("bob@test.com", "Bob")

    async def test_new_user_signup_tracking_failure_does_not_raise(
        self,
        mock_user_repo,
        mock_track_signup,
        mock_send_welcome_email,
        mock_add_marketing_contact,
    ):
        uid = str(ObjectId())
        mock_user_repo.get_by_email.return_value = None
        mock_user_repo.create.return_value = UserDocument(id=uid)
        mock_track_signup.side_effect = Exception("PostHog unavailable")

        # Should not raise
        result = await store_user_info("Bob", "bob@test.com", None)
        assert result == (uid, True)

    async def test_new_user_welcome_email_failure_does_not_raise(
        self,
        mock_user_repo,
        mock_track_signup,
        mock_send_welcome_email,
        mock_add_marketing_contact,
    ):
        uid = str(ObjectId())
        mock_user_repo.get_by_email.return_value = None
        mock_user_repo.create.return_value = UserDocument(id=uid)
        mock_send_welcome_email.side_effect = Exception("SMTP error")

        result = await store_user_info("Bob", "bob@test.com", None)
        assert result == (uid, True)

    async def test_new_user_resend_failure_does_not_raise(
        self,
        mock_user_repo,
        mock_track_signup,
        mock_send_welcome_email,
        mock_add_marketing_contact,
    ):
        uid = str(ObjectId())
        mock_user_repo.get_by_email.return_value = None
        mock_user_repo.create.return_value = UserDocument(id=uid)
        mock_add_marketing_contact.side_effect = Exception("Resend API error")

        result = await store_user_info("Bob", "bob@test.com", None)
        assert result == (uid, True)


# ---------------------------------------------------------------------------
# get_all_integrations_status
# ---------------------------------------------------------------------------


class TestGetAllIntegrationsStatus:
    """Tests for get_all_integrations_status.

    Note: The @Cacheable decorator is bypassed in tests via the autouse
    bypass_cacheable fixture, so each call hits the real function body.
    """

    async def test_reads_only_this_users_integrations_and_tokens(
        self,
        mock_user_integration_repo,
        mock_composio_service,
        mock_token_repository,
    ):
        """Every read is scoped to the caller. Widened or aimed at the wrong id,
        one user's integration page answers with another user's connections."""
        mock_token_repository.get_token = AsyncMock(return_value={"scope": "calendar.events"})

        integration = MagicMock()
        integration.id = "googlecalendar"
        integration.available = True
        integration.managed_by = "self"
        integration.provider = "google"

        with (
            patch("app.services.oauth.oauth_service.OAUTH_INTEGRATIONS", [integration]),
            patch(
                "app.services.oauth.oauth_service.get_integration_scopes",
                return_value=["calendar.events"],
            ),
        ):
            result = await get_all_integrations_status("user123")

        assert result == {"googlecalendar": True}
        mock_user_integration_repo.list_for_user.assert_awaited_once_with("user123", limit=100)
        mock_token_repository.get_token.assert_awaited_once_with(
            "user123", "google", renew_if_expired=True
        )

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
            "app.services.oauth.oauth_service.OAUTH_INTEGRATIONS",
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
            "app.services.oauth.oauth_service.OAUTH_INTEGRATIONS",
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
            "app.services.oauth.oauth_service.OAUTH_INTEGRATIONS",
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
            "app.services.oauth.oauth_service.OAUTH_INTEGRATIONS",
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
            "app.services.oauth.oauth_service.OAUTH_INTEGRATIONS",
            [integration],
        ):
            result = await get_all_integrations_status("user123")

        assert result["twitter"] is True
        mock_composio_service.check_connection_status.assert_awaited_once()

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

        with patch(
            "app.services.oauth.oauth_service.OAUTH_INTEGRATIONS",
            [integration],
        ):
            result = await get_all_integrations_status("user123")

        assert result["twitter"] is False

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
        mock_user_integration_repo,
        mock_composio_service,
        mock_token_repository,
    ):
        """Custom integrations in MongoDB not in OAUTH_INTEGRATIONS are still included."""
        mock_user_integration_repo.list_for_user = AsyncMock(
            return_value=[_ui_doc("custom_tool", "connected")]
        )

        with patch(
            "app.services.oauth.oauth_service.OAUTH_INTEGRATIONS",
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


class TestCheckMultipleIntegrationsStatus:
    async def test_returns_status_for_requested_integrations(self):
        with patch(
            "app.services.oauth.oauth_service.get_all_integrations_status",
            new_callable=AsyncMock,
            return_value={"gmail": True, "notion": False, "slack": True},
        ):
            result = await check_multiple_integrations_status(["gmail", "notion"], "user123")

        assert result == {"gmail": True, "notion": False}

    async def test_unknown_integrations_default_to_false(self):
        with patch(
            "app.services.oauth.oauth_service.get_all_integrations_status",
            new_callable=AsyncMock,
            return_value={"gmail": True},
        ):
            result = await check_multiple_integrations_status(["gmail", "unknown"], "user123")

        assert result == {"gmail": True, "unknown": False}

    async def test_returns_all_false_on_exception(self):
        with patch(
            "app.services.oauth.oauth_service.get_all_integrations_status",
            new_callable=AsyncMock,
            side_effect=Exception("Service error"),
        ):
            result = await check_multiple_integrations_status(["gmail", "notion"], "user123")

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


class TestHandleOAuthConnection:
    async def test_invalidates_cache_and_updates_integration_status(
        self,
        mock_update_user_integration_status,
    ):
        """Core behavior: update integration status (cache invalidation is handled by decorator)."""
        config = make_integration_config(
            integration_id="notion",
            name="Notion",
        )
        background_tasks = MagicMock()

        await handle_oauth_connection(
            user_id="user123",
            integration_config=config,
            background_tasks=background_tasks,
        )

        mock_update_user_integration_status.assert_awaited_once_with(
            "user123", "notion", "connected", connected_account_id=None
        )

    async def test_sets_up_triggers_when_present(
        self,
        mock_update_user_integration_status,
    ):
        """If integration has associated_triggers, schedule trigger setup."""
        mock_trigger = MagicMock()
        config = make_integration_config(
            integration_id="notion",
            associated_triggers=[mock_trigger],
        )
        background_tasks = MagicMock()

        with patch("app.services.oauth.oauth_service.get_composio_service") as mock_get_cs:
            mock_cs = MagicMock()
            mock_get_cs.return_value = mock_cs

            await handle_oauth_connection(
                user_id="user123",
                integration_config=config,
                background_tasks=background_tasks,
            )

        background_tasks.add_task.assert_any_call(
            mock_cs.handle_subscribe_trigger,
            user_id="user123",
            triggers=[mock_trigger],
        )

    async def test_does_not_setup_triggers_when_empty(
        self,
        mock_update_user_integration_status,
    ):
        """If no associated_triggers, do not call get_composio_service for triggers."""
        config = make_integration_config(
            integration_id="notion",
            associated_triggers=[],
        )
        background_tasks = MagicMock()

        await handle_oauth_connection(
            user_id="user123",
            integration_config=config,
            background_tasks=background_tasks,
        )

        # No trigger-related background task should be queued
        for call in background_tasks.add_task.call_args_list:
            func = call[0][0] if call[0] else None
            # Ensure no handle_subscribe_trigger was added
            if func and hasattr(func, "__name__"):
                assert func.__name__ != "handle_subscribe_trigger"

    async def test_gmail_connection_enqueues_personalization(
        self,
        mock_user_repo,
        mock_update_user_integration_status,
        mock_redis_pool_manager,
        mock_enqueue_personalization,
    ):
        """Connecting Gmail is what triggers the personalization pipeline."""
        user_id = "507f1f77bcf86cd799439011"
        mock_user_repo.get.return_value = UserDocument(onboarding={"completed": True})
        config = make_integration_config(integration_id="gmail")
        background_tasks = MagicMock()

        await handle_oauth_connection(
            user_id=user_id,
            integration_config=config,
            background_tasks=background_tasks,
        )

        mock_enqueue_personalization.assert_awaited_once_with(user_id)
        # The pipeline queues memory ingestion itself, after its own inbox scan,
        # so queuing it here too would contend for Gmail capacity.
        mock_redis_pool_manager.enqueue_job.assert_not_awaited()

    async def test_gmail_connection_queues_memory_ingestion_when_pipeline_skipped(
        self,
        mock_user_repo,
        mock_update_user_integration_status,
        mock_redis_pool_manager,
        mock_enqueue_personalization,
    ):
        """A reconnect whose pipeline already ran still refreshes memory."""
        user_id = "507f1f77bcf86cd799439011"
        mock_enqueue_personalization.return_value = None
        mock_user_repo.get.return_value = UserDocument(onboarding={"completed": True})
        config = make_integration_config(integration_id="gmail")
        background_tasks = MagicMock()

        await handle_oauth_connection(
            user_id=user_id,
            integration_config=config,
            background_tasks=background_tasks,
        )

        mock_redis_pool_manager.enqueue_job.assert_awaited_once_with(
            "process_gmail_emails_to_memory", user_id
        )

    async def test_gmail_connection_updates_bio_status_when_no_gmail(
        self,
        mock_user_repo,
        mock_update_user_integration_status,
        mock_websocket_manager,
        mock_redis_pool_manager,
        mock_enqueue_personalization,
    ):
        """Gmail connection should update bio_status from no_gmail to processing."""
        user_id = "507f1f77bcf86cd799439011"
        mock_user_repo.get.return_value = UserDocument(
            onboarding={"completed": True, "bio_status": BioStatus.NO_GMAIL}
        )
        config = make_integration_config(integration_id="gmail")
        background_tasks = MagicMock()

        await handle_oauth_connection(
            user_id=user_id,
            integration_config=config,
            background_tasks=background_tasks,
        )

        mock_user_repo.set_bio_status.assert_awaited_once_with(user_id, BioStatus.PROCESSING)

    async def test_gmail_connection_sends_websocket_update(
        self,
        mock_user_repo,
        mock_update_user_integration_status,
        mock_websocket_manager,
        mock_redis_pool_manager,
        mock_enqueue_personalization,
    ):
        """Gmail with no_gmail bio_status should broadcast WebSocket update."""
        user_id = "507f1f77bcf86cd799439011"
        mock_user_repo.get.return_value = UserDocument(
            onboarding={"completed": True, "bio_status": "no_gmail"}
        )
        config = make_integration_config(integration_id="gmail")
        background_tasks = MagicMock()

        await handle_oauth_connection(
            user_id=user_id,
            integration_config=config,
            background_tasks=background_tasks,
        )

        mock_websocket_manager.broadcast_to_user.assert_awaited_once()
        call_args = mock_websocket_manager.broadcast_to_user.call_args
        assert call_args.kwargs["user_id"] == user_id
        assert call_args.kwargs["message"]["type"] == "bio_status_update"

    async def test_gmail_connection_skips_bio_update_when_already_completed(
        self,
        mock_user_repo,
        mock_update_user_integration_status,
        mock_redis_pool_manager,
        mock_enqueue_personalization,
    ):
        """If bio_status is 'completed', don't update to processing."""
        mock_user_repo.get.return_value = UserDocument(
            onboarding={"completed": True, "bio_status": BioStatus.COMPLETED}
        )
        config = make_integration_config(integration_id="gmail")
        background_tasks = MagicMock()

        await handle_oauth_connection(
            user_id="user123",
            integration_config=config,
            background_tasks=background_tasks,
        )

        mock_user_repo.set_bio_status.assert_not_awaited()

    async def test_gmail_connection_skips_bio_when_onboarding_not_completed(
        self,
        mock_user_repo,
        mock_update_user_integration_status,
        mock_redis_pool_manager,
        mock_enqueue_personalization,
    ):
        """If onboarding not completed, don't update bio_status."""
        mock_user_repo.get.return_value = UserDocument(
            onboarding={"completed": False, "bio_status": BioStatus.NO_GMAIL}
        )
        config = make_integration_config(integration_id="gmail")
        background_tasks = MagicMock()

        await handle_oauth_connection(
            user_id="user123",
            integration_config=config,
            background_tasks=background_tasks,
        )

        mock_user_repo.set_bio_status.assert_not_awaited()

    async def test_gmail_arq_queue_failure_does_not_raise(
        self,
        mock_user_repo,
        mock_update_user_integration_status,
        mock_enqueue_personalization,
    ):
        """ARQ enqueue failure should be logged, not raised."""
        mock_enqueue_personalization.return_value = None
        mock_user_repo.get.return_value = UserDocument(onboarding={"completed": True})
        config = make_integration_config(integration_id="gmail")
        background_tasks = MagicMock()

        with patch("app.services.oauth.oauth_service.RedisPoolManager") as mock_rpm:
            mock_pool = AsyncMock()
            mock_pool.enqueue_job = AsyncMock(side_effect=Exception("Redis down"))
            mock_rpm.get_pool = AsyncMock(return_value=mock_pool)

            # Should not raise
            await handle_oauth_connection(
                user_id="user123",
                integration_config=config,
                background_tasks=background_tasks,
            )

    async def test_non_gmail_connection_skips_email_processing(
        self,
        mock_update_user_integration_status,
    ):
        """Non-Gmail integrations should not queue email processing."""
        config = make_integration_config(integration_id="notion")
        background_tasks = MagicMock()

        with patch("app.services.oauth.oauth_service.RedisPoolManager") as mock_rpm:
            await handle_oauth_connection(
                user_id="user123",
                integration_config=config,
                background_tasks=background_tasks,
            )

            mock_rpm.get_pool.assert_not_called()

    async def test_metadata_config_queues_metadata_fetch(
        self,
        mock_update_user_integration_status,
        mock_fetch_and_store_provider_metadata,
    ):
        """If integration has metadata_config, schedule background metadata fetch."""
        mock_metadata = MagicMock()
        config = make_integration_config(
            integration_id="slack",
            name="Slack",
            metadata_config=mock_metadata,
        )
        background_tasks = MagicMock()

        await handle_oauth_connection(
            user_id="user123",
            integration_config=config,
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
        mock_update_user_integration_status,
    ):
        """If no metadata_config, should not schedule metadata fetch."""
        config = make_integration_config(
            integration_id="notion",
            metadata_config=None,
        )
        background_tasks = MagicMock()

        await handle_oauth_connection(
            user_id="user123",
            integration_config=config,
            background_tasks=background_tasks,
        )

        # No fetch_and_store_provider_metadata call
        for call in background_tasks.add_task.call_args_list:
            func_called = call[0][0]
            func_name = getattr(func_called, "__name__", str(func_called))
            assert "fetch_and_store_provider_metadata" not in func_name

    async def test_gmail_provisions_system_workflows(
        self,
        mock_user_repo,
        mock_update_user_integration_status,
        mock_provision_system_workflows,
        mock_redis_pool_manager,
        mock_enqueue_personalization,
    ):
        """Gmail connection should provision system workflows."""
        mock_user_repo.get.return_value = UserDocument(onboarding={"completed": False})
        config = make_integration_config(integration_id="gmail", name="Gmail")
        background_tasks = MagicMock()

        await handle_oauth_connection(
            user_id="user123",
            integration_config=config,
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
        mock_update_user_integration_status,
        mock_provision_system_workflows,
    ):
        """Google Calendar connection should provision system workflows."""
        config = make_integration_config(
            integration_id="googlecalendar",
            name="Google Calendar",
        )
        background_tasks = MagicMock()

        await handle_oauth_connection(
            user_id="user123",
            integration_config=config,
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
        mock_update_user_integration_status,
    ):
        """Non-Gmail/Calendar integrations should not provision system workflows."""
        config = make_integration_config(
            integration_id="notion",
            name="Notion",
        )
        background_tasks = MagicMock()

        with patch("app.services.oauth.oauth_service.provision_system_workflows") as mock_psw:
            await handle_oauth_connection(
                user_id="user123",
                integration_config=config,
                background_tasks=background_tasks,
            )

            # provision_system_workflows should NOT appear in any background task
            for call in background_tasks.add_task.call_args_list:
                assert call[0][0] is not mock_psw

    async def test_reconnecting_schedules_the_workflow_resume_for_that_user_and_integration(
        self,
        mock_update_user_integration_status,
    ):
        """Reconnecting is what un-pauses the workflows this integration's expiry
        stopped. Scheduled for the wrong user or integration, the user's workflows
        stay dark and someone else's come back."""
        config = make_integration_config(integration_id="notion", name="Notion")
        background_tasks = MagicMock()

        await handle_oauth_connection(
            user_id="user123",
            integration_config=config,
            background_tasks=background_tasks,
        )

        background_tasks.add_task.assert_any_call(
            resume_workflows_for_reconnected_integration,
            "user123",
            "notion",
        )

    async def test_reconnect_resyncs_todo_subscriptions_for_this_integrations_triggers(
        self,
        mock_update_user_integration_status,
    ):
        """A reconnect strands the todo subscriptions on this integration's
        triggers exactly as it strands workflow triggers. They must be resynced
        for the reconnecting user against the set of trigger slugs — dropped or
        nulled, the todo watches stay dead on a fresh connected account with no
        signal to the user."""
        trigger = MagicMock()
        trigger.workflow_trigger_schema.slug = "notion_page_added"
        config = make_integration_config(
            integration_id="notion",
            associated_triggers=[trigger],
        )
        background_tasks = MagicMock()

        with patch("app.services.oauth.oauth_service.get_composio_service"):
            await handle_oauth_connection(
                user_id="user123",
                integration_config=config,
                background_tasks=background_tasks,
            )

        background_tasks.add_task.assert_any_call(
            resync_subscriptions_for_trigger_names,
            "user123",
            {"notion_page_added"},
        )

    async def test_integration_status_update_failure_does_not_raise(
        self,
    ):
        """Integration status update failure should be logged, not raised."""
        config = make_integration_config(integration_id="notion")
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
                background_tasks=background_tasks,
            )

    async def test_websocket_failure_does_not_block_flow(
        self,
        mock_user_repo,
        mock_update_user_integration_status,
        mock_redis_pool_manager,
        mock_enqueue_personalization,
    ):
        """WebSocket broadcast failure should not block the OAuth flow."""
        mock_user_repo.get.return_value = UserDocument(
            onboarding={"completed": True, "bio_status": BioStatus.NO_GMAIL}
        )
        config = make_integration_config(integration_id="gmail")
        background_tasks = MagicMock()

        with patch("app.services.oauth.oauth_service.websocket_manager") as mock_ws:
            mock_ws.broadcast_to_user = AsyncMock(side_effect=Exception("WS connection lost"))

            # Should not raise
            await handle_oauth_connection(
                user_id="user123",
                integration_config=config,
                background_tasks=background_tasks,
            )


# ---------------------------------------------------------------------------
# _returning_user_profile
# ---------------------------------------------------------------------------
