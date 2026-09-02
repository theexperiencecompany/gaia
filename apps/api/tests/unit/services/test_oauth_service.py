"""Unit tests for OAuth service operations."""

from unittest.mock import AsyncMock, MagicMock, patch

from bson import ObjectId
from fastapi import HTTPException
import pytest

from app.constants.log_tags import LogTag
from app.models.integration_models import UserIntegrationDocument
from app.models.user_models import BioStatus, UserDocument
from app.services.oauth.oauth_service import (
    _handle_gmail_connection,
    _refresh_bio_status_for_reconnect,
    _returning_user_profile,
    _run_signup_side_effects,
    _setup_integration_triggers,
    check_integration_status,
    check_multiple_integrations_status,
    get_all_integrations_status,
    handle_oauth_connection,
    store_user_info,
)
from app.services.workflow.integration_pause import (
    resume_workflows_for_reconnected_integration,
)
from app.services.workflow.trigger_service import TriggerService
from tests.helpers import captured_wide_event


class LoguruErrorSpy:
    """Records every real-time error line with the ``exception=`` flag it carried.

    ``log.error(..., exc_info=True)`` pops ``exc_info`` before the wide event
    sees it, so whether the traceback is attached to the line is observable
    only at the loguru sink — and a swallowed failure without its traceback is
    exactly the one nobody can diagnose.
    """

    def __init__(self) -> None:
        self.errors: list[tuple[str, object]] = []
        self._exception: object = None

    def opt(self, **kwargs: object) -> "LoguruErrorSpy":
        self._exception = kwargs.get("exception")
        return self

    def bind(self, **kwargs: object) -> "LoguruErrorSpy":
        return self

    def error(self, message: str) -> None:
        self.errors.append((message, self._exception))

    def warning(self, message: str) -> None: ...

    def info(self, message: str) -> None: ...

    def debug(self, message: str) -> None: ...

    def critical(self, message: str) -> None: ...

    def log(self, level: str, message: str) -> None: ...


def _ui_doc(integration_id: str, status: str) -> UserIntegrationDocument:
    """Build a UserIntegrationDocument as list_for_user would return it."""
    return UserIntegrationDocument(user_id="user123", integration_id=integration_id, status=status)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_user_repo():
    with patch("app.services.oauth.oauth_service.user_repository") as mock_repo:
        mock_repo.get_by_email = AsyncMock()
        mock_repo.get = AsyncMock()
        mock_repo.update = AsyncMock()
        mock_repo.create = AsyncMock()
        mock_repo.set_bio_status = AsyncMock()
        yield mock_repo


@pytest.fixture
def mock_user_integration_repo():
    with patch("app.services.oauth.oauth_service.user_integration_repository") as mock_repo:
        mock_repo.list_for_user = AsyncMock(return_value=[])
        yield mock_repo


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
def mock_redis_pool_manager(route_enqueue_via_pool):
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
def mock_track_login():
    with patch("app.services.oauth.oauth_service.track_login") as mock_tl:
        yield mock_tl


@pytest.fixture
def mock_send_welcome_email():
    with patch(
        "app.services.oauth.oauth_service.send_welcome_email",
        new_callable=AsyncMock,
    ) as mock_swe:
        yield mock_swe


@pytest.fixture
def mock_add_marketing_contact():
    with patch(
        "app.services.oauth.oauth_service.add_marketing_contact",
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
def mock_enqueue_personalization():
    """Gmail connect enqueues the personalization pipeline; a job id means it ran."""
    with patch(
        "app.services.oauth.oauth_service.enqueue_gmail_personalization",
        new_callable=AsyncMock,
        return_value="personalization-job-1",
    ) as mock_fn:
        yield mock_fn


@pytest.fixture
def mock_schedule_user_provision():
    with patch("app.services.oauth.oauth_service.schedule_user_provision") as mock_fn:
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
        patch("app.db.redis.redis_cache.get", new_callable=AsyncMock, return_value=None),
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
        config = _make_integration_config(
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
        config = _make_integration_config(
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
        config = _make_integration_config(
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
        config = _make_integration_config(integration_id="gmail")
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
        config = _make_integration_config(integration_id="gmail")
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
        config = _make_integration_config(integration_id="gmail")
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
        config = _make_integration_config(integration_id="gmail")
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
        config = _make_integration_config(integration_id="gmail")
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
        config = _make_integration_config(integration_id="gmail")
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
                background_tasks=background_tasks,
            )

    async def test_non_gmail_connection_skips_email_processing(
        self,
        mock_update_user_integration_status,
    ):
        """Non-Gmail integrations should not queue email processing."""
        config = _make_integration_config(integration_id="notion")
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
        config = _make_integration_config(
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
        config = _make_integration_config(
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
        config = _make_integration_config(integration_id="gmail", name="Gmail")
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
        config = _make_integration_config(
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
        config = _make_integration_config(
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
        config = _make_integration_config(integration_id="notion", name="Notion")
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

    async def test_integration_status_update_failure_does_not_raise(
        self,
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
        config = _make_integration_config(integration_id="gmail")
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


class TestReturningUserProfile:
    def test_a_blank_stored_name_is_filled_from_the_login_name(self):
        """A user with no stored name gets the one this login carries — and that
        same name is what analytics must report, not a placeholder."""
        existing_user = UserDocument(
            id=str(ObjectId()), email="alice@test.com", name=None, picture="https://p/x.jpg"
        )

        update_fields, stored_name = _returning_user_profile(existing_user, "Alice", None)

        assert update_fields == {"name": "Alice"}
        assert stored_name == "Alice"


# ---------------------------------------------------------------------------
# _run_signup_side_effects
# ---------------------------------------------------------------------------


class TestRunSignupSideEffects:
    """Every outbound effect is swallowed so it cannot fail the signup, which
    makes the wide event the only place the failure is visible. A blank or
    misattributed entry there is a signup silently missing its email."""

    async def test_a_posthog_failure_is_recorded_and_the_rest_still_runs(
        self,
        mock_track_signup,
        mock_send_welcome_email,
        mock_add_marketing_contact,
        mock_schedule_user_provision,
    ):
        user_id = str(ObjectId())
        mock_track_signup.side_effect = RuntimeError("PostHog unavailable")

        async with captured_wide_event() as event:
            await _run_signup_side_effects(user_id, "bob@test.com", "Bob")

        assert event["errors"] == [
            {
                "msg": f"{LogTag.OAUTH} Failed to track signup in PostHog for",
                "email": "bob@test.com",
                "error": "PostHog unavailable",
                "error_type": "RuntimeError",
            }
        ]
        mock_send_welcome_email.assert_awaited_once_with("bob@test.com", "Bob")
        mock_add_marketing_contact.assert_awaited_once_with("bob@test.com", "Bob")
        mock_schedule_user_provision.assert_called_once_with(user_id)

    async def test_a_welcome_email_failure_is_recorded_and_the_rest_still_runs(
        self,
        mock_track_signup,
        mock_send_welcome_email,
        mock_add_marketing_contact,
        mock_schedule_user_provision,
    ):
        user_id = str(ObjectId())
        mock_send_welcome_email.side_effect = RuntimeError("SMTP error")

        async with captured_wide_event() as event:
            await _run_signup_side_effects(user_id, "bob@test.com", "Bob")

        assert event["errors"] == [
            {
                "msg": f"{LogTag.OAUTH} Failed to send welcome email to",
                "email": "bob@test.com",
                "error": "SMTP error",
                "error_type": "RuntimeError",
            }
        ]
        mock_add_marketing_contact.assert_awaited_once_with("bob@test.com", "Bob")
        mock_schedule_user_provision.assert_called_once_with(user_id)

    async def test_a_marketing_contact_failure_is_recorded_and_provisioning_still_runs(
        self,
        mock_track_signup,
        mock_send_welcome_email,
        mock_add_marketing_contact,
        mock_schedule_user_provision,
    ):
        user_id = str(ObjectId())
        mock_add_marketing_contact.side_effect = RuntimeError("Resend API error")

        async with captured_wide_event() as event:
            await _run_signup_side_effects(user_id, "bob@test.com", "Bob")

        assert event["errors"] == [
            {
                "msg": f"{LogTag.OAUTH} Failed to add marketing contact for",
                "email": "bob@test.com",
                "error": "Resend API error",
                "error_type": "RuntimeError",
            }
        ]
        mock_schedule_user_provision.assert_called_once_with(user_id)


# ---------------------------------------------------------------------------
# _refresh_bio_status_for_reconnect
# ---------------------------------------------------------------------------


class TestRefreshBioStatusForReconnect:
    USER_ID = "507f1f77bcf86cd799439011"

    @staticmethod
    def _no_gmail_user() -> UserDocument:
        return UserDocument(onboarding={"completed": True, "bio_status": BioStatus.NO_GMAIL})

    async def test_broadcasts_the_processing_status_to_that_user(
        self, mock_user_repo, mock_websocket_manager
    ):
        """The frontend re-runs the bio only on this exact payload — a renamed
        key or field leaves the card stuck on the no-Gmail placeholder."""
        await _refresh_bio_status_for_reconnect(self.USER_ID, self._no_gmail_user())

        mock_user_repo.set_bio_status.assert_awaited_once_with(self.USER_ID, BioStatus.PROCESSING)
        mock_websocket_manager.broadcast_to_user.assert_awaited_once_with(
            user_id=self.USER_ID,
            message={
                "type": "bio_status_update",
                "data": {"bio_status": BioStatus.PROCESSING},
            },
        )

    async def test_an_empty_user_id_is_never_broadcast(
        self, mock_user_repo, mock_websocket_manager
    ):
        """Broadcasting to "" fans the update out to nobody at best; the guard is
        what keeps it off the socket layer entirely."""
        await _refresh_bio_status_for_reconnect("", self._no_gmail_user())

        mock_websocket_manager.broadcast_to_user.assert_not_awaited()

    async def test_a_websocket_failure_is_a_warning_carrying_the_cause(
        self, mock_user_repo, mock_websocket_manager
    ):
        mock_websocket_manager.broadcast_to_user.side_effect = RuntimeError("WS connection lost")

        async with captured_wide_event() as event:
            await _refresh_bio_status_for_reconnect(self.USER_ID, self._no_gmail_user())

        # The status write landed; only the live notification was lost, so this
        # is a warning and never an error.
        mock_user_repo.set_bio_status.assert_awaited_once_with(self.USER_ID, BioStatus.PROCESSING)
        assert event["warnings"] == [
            {
                "msg": f"{LogTag.OAUTH} Failed to send WebSocket update",
                "error": "WS connection lost",
                "error_type": "RuntimeError",
                "user_id": self.USER_ID,
            }
        ]
        assert "errors" not in event

    async def test_a_failed_status_write_is_an_error_with_its_traceback(
        self, mock_user_repo, mock_websocket_manager
    ):
        mock_user_repo.set_bio_status.side_effect = RuntimeError("mongo down")
        spy = LoguruErrorSpy()

        async with captured_wide_event() as event:
            with patch("shared.py.wide_events._loguru", spy):
                await _refresh_bio_status_for_reconnect(self.USER_ID, self._no_gmail_user())

        message = f"{LogTag.OAUTH} Error updating bio_status for user"
        assert event["errors"] == [
            {
                "msg": message,
                "user_id": self.USER_ID,
                "error": "mongo down",
                "error_type": "RuntimeError",
            }
        ]
        assert spy.errors == [(message, True)]
        mock_websocket_manager.broadcast_to_user.assert_not_awaited()


# ---------------------------------------------------------------------------
# _handle_gmail_connection
# ---------------------------------------------------------------------------


class TestHandleGmailConnection:
    USER_ID = "507f1f77bcf86cd799439011"

    async def test_reads_the_connecting_users_own_document(
        self, mock_user_repo, mock_redis_pool_manager, mock_enqueue_personalization
    ):
        """Read the wrong document and a completed onboarding is invisible, so
        the reconnect never refreshes the bio."""
        mock_user_repo.get.return_value = UserDocument(onboarding={"completed": True})

        await _handle_gmail_connection(self.USER_ID)

        mock_user_repo.get.assert_awaited_once_with(self.USER_ID)
        mock_enqueue_personalization.assert_awaited_once_with(self.USER_ID)

    async def test_a_failed_user_load_is_recorded_and_the_pipeline_still_runs(
        self, mock_user_repo, mock_redis_pool_manager, mock_enqueue_personalization
    ):
        """Losing the document only costs the bio refresh — the personalization
        pipeline is what the connect was for and must still be queued."""
        mock_user_repo.get.side_effect = RuntimeError("mongo down")
        spy = LoguruErrorSpy()

        async with captured_wide_event() as event:
            with patch("shared.py.wide_events._loguru", spy):
                await _handle_gmail_connection(self.USER_ID)

        message = f"{LogTag.OAUTH} Failed to load user_doc for"
        assert event["errors"] == [
            {
                "msg": message,
                "user_id": self.USER_ID,
                "error": "mongo down",
                "error_type": "RuntimeError",
            }
        ]
        assert spy.errors == [(message, True)]
        mock_user_repo.set_bio_status.assert_not_awaited()
        mock_enqueue_personalization.assert_awaited_once_with(self.USER_ID)

    async def test_a_failed_ingestion_queue_is_recorded_with_its_traceback(
        self, mock_user_repo, mock_redis_pool_manager, mock_enqueue_personalization
    ):
        mock_user_repo.get.return_value = UserDocument(onboarding={"completed": True})
        mock_enqueue_personalization.return_value = None
        mock_redis_pool_manager.enqueue_job.side_effect = RuntimeError("Redis down")
        spy = LoguruErrorSpy()

        async with captured_wide_event() as event:
            with patch("shared.py.wide_events._loguru", spy):
                await _handle_gmail_connection(self.USER_ID)

        message = f"{LogTag.OAUTH} Failed to queue Gmail processing"
        assert event["errors"] == [
            {
                "msg": message,
                "error": "Redis down",
                "error_type": "RuntimeError",
                "user_id": self.USER_ID,
            }
        ]
        assert spy.errors == [(message, True)]


# ---------------------------------------------------------------------------
# _setup_integration_triggers
# ---------------------------------------------------------------------------


class TestSetupIntegrationTriggers:
    def test_resyncs_this_users_workflow_triggers_for_the_reconnected_integration(self):
        """A reconnect strands the workflow triggers registered against the old
        connected account; the resync is what keeps existing workflows firing."""
        workflow_trigger = MagicMock()
        workflow_trigger.workflow_trigger_schema.slug = "gmail_new_email"
        plain_trigger = MagicMock()
        plain_trigger.workflow_trigger_schema = None
        config = _make_integration_config(
            integration_id="gmail",
            associated_triggers=[workflow_trigger, plain_trigger],
        )
        background_tasks = MagicMock()

        with patch("app.services.oauth.oauth_service.get_composio_service"):
            _setup_integration_triggers("user123", config, background_tasks)

        background_tasks.add_task.assert_any_call(
            TriggerService.resync_user_workflow_triggers,
            "user123",
            ["gmail_new_email"],
        )
