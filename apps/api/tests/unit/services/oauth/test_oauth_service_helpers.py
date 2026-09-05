"""Unit tests for the helpers extracted from store_user_info and
handle_oauth_connection. Kept apart from test_oauth_service.py so that file
imports only symbols that exist on the base revision — the regression-proof
lane runs its marked tests there."""

from unittest.mock import MagicMock, patch

from bson import ObjectId
from tests.factories import make_integration_config
from tests.helpers import captured_wide_event

from app.constants.log_tags import LogTag
from app.models.user_models import BioStatus, UserDocument
from app.services.oauth.oauth_service import (
    _handle_gmail_connection,
    _refresh_bio_status_for_reconnect,
    _returning_user_profile,
    _run_signup_side_effects,
    _setup_integration_triggers,
)
from app.services.workflow.trigger_service import TriggerService


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
        config = make_integration_config(
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
