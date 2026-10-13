"""Unit tests for app.workers.tasks.signup_email_tasks.

The two ESP round-trips a signup owes the new user, moved onto the worker queue
so a restart mid-send cannot drop them. Both failure paths are swallowed so
neither delivery can fail the other, which makes the wide event the only place a
lost email is visible — a blank or misattributed entry there is a signup
silently missing its welcome email.

Durability is three separate claims, each tested here: the enqueue is deduped by
a per-user job id so a re-run cannot double-send; a landed delivery stamps the
user, which is what makes a re-run a no-op; and a delivery that never landed
leaves its stamp absent, which is what the recovery sweep selects on.
"""

import asyncio
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.constants.email import WELCOME_EMAIL_RESEND_WINDOW, SignupDelivery
from app.constants.log_tags import LogTag
from app.models.user_models import UserDocument
from app.services.email.signup_delivery import enqueue_signup_emails, signup_email_job_id
from app.workers.tasks.signup_email_tasks import deliver_signup_emails
from tests.helpers import captured_wide_event

MODULE = "app.workers.tasks.signup_email_tasks"

USER_ID = "507f1f77bcf86cd799439011"
OTHER_USER_ID = "507f1f77bcf86cd799439012"


def _user(**overrides) -> UserDocument:
    """Build the stored signup row the job reads; no stamps means both deliveries are owed."""
    fields: dict = {
        "id": USER_ID,
        "email": "bob@test.com",
        "name": "Bob",
        "created_at": datetime.now(UTC),
    }
    fields.update(overrides)
    return UserDocument(**fields)


@pytest.fixture
def stored_user():
    with patch(f"{MODULE}.user_repository.get", AsyncMock(return_value=_user())) as mock_get:
        yield mock_get


@pytest.fixture
def mock_stamp():
    with patch(
        f"{MODULE}.user_repository.stamp_signup_deliveries", new_callable=AsyncMock
    ) as mock_fn:
        yield mock_fn


@pytest.fixture
def mock_send_welcome_email():
    with patch(f"{MODULE}.send_welcome_email", new_callable=AsyncMock) as mock_fn:
        yield mock_fn


@pytest.fixture
def mock_add_marketing_contact():
    with patch(f"{MODULE}.add_marketing_contact", new_callable=AsyncMock) as mock_fn:
        yield mock_fn


@pytest.fixture
def hung_esp_call():
    """Return an ESP stub that accepts the call and never answers."""

    async def _hang(*_args: str, **_kwargs: str) -> None:
        await asyncio.Event().wait()

    return _hang


def _stamps(mock_stamp: AsyncMock) -> list[tuple[str, SignupDelivery]]:
    """Every (user, delivery) pair stamped across all calls, flattened.

    The row being stamped matters as much as the delivery: a stamp written
    against the wrong user retires a debt that was never paid, and the real
    user stays unstamped and keeps coming back through the sweep forever.
    """
    return [
        (call.args[0], delivery) for call in mock_stamp.await_args_list for delivery in call.args[1]
    ]


class _DedupingPool:
    """Stands in for ArqRedis: an enqueue whose _job_id is already known is dropped and returns None."""

    def __init__(self) -> None:
        self.job_ids: list[str] = []

    async def enqueue_job(self, function: str, *args: str, **kwargs: str) -> MagicMock | None:
        job_id = kwargs["_job_id"]
        if job_id in self.job_ids:
            return None
        self.job_ids.append(job_id)
        return MagicMock(function=function, args=args)


class TestEnqueueSignupEmails:
    async def test_a_second_enqueue_for_the_same_user_is_a_no_op(self):
        """The deterministic job id must stop a later sweep or retried callback from producing a second job."""
        pool = _DedupingPool()

        first = await enqueue_signup_emails(pool, USER_ID)
        second = await enqueue_signup_emails(pool, USER_ID)

        assert first is not None
        assert second is None
        assert pool.job_ids == [signup_email_job_id(USER_ID)]

    async def test_a_different_user_gets_its_own_job(self):
        pool = _DedupingPool()

        await enqueue_signup_emails(pool, USER_ID)
        await enqueue_signup_emails(pool, OTHER_USER_ID)

        assert pool.job_ids == [
            signup_email_job_id(USER_ID),
            signup_email_job_id(OTHER_USER_ID),
        ]


class TestDeliverSignupEmails:
    async def test_both_deliveries_go_out_for_the_new_user(
        self, stored_user, mock_stamp, mock_send_welcome_email, mock_add_marketing_contact
    ):
        result = await deliver_signup_emails({}, USER_ID)

        mock_send_welcome_email.assert_awaited_once_with("bob@test.com", "Bob", user_id=USER_ID)
        mock_add_marketing_contact.assert_awaited_once_with("bob@test.com", "Bob", user_id=USER_ID)
        assert USER_ID in result

    async def test_each_landed_delivery_stamps_the_user(
        self, stored_user, mock_stamp, mock_send_welcome_email, mock_add_marketing_contact
    ):
        """Without the durable stamp, a re-run double-sends and the sweep keeps re-selecting the user."""
        await deliver_signup_emails({}, USER_ID)

        assert sorted(_stamps(mock_stamp)) == sorted(
            [
                (USER_ID, SignupDelivery.WELCOME_EMAIL),
                (USER_ID, SignupDelivery.MARKETING_CONTACT),
            ]
        )

    async def test_an_already_stamped_delivery_is_not_repeated(
        self, mock_stamp, mock_send_welcome_email, mock_add_marketing_contact
    ):
        """The stamp is what stops a re-run (after a worker died mid-send) from mailing the user twice."""
        already = _user(welcome_email_sent_at=datetime.now(UTC))
        with patch(f"{MODULE}.user_repository.get", AsyncMock(return_value=already)):
            await deliver_signup_emails({}, USER_ID)

        mock_send_welcome_email.assert_not_awaited()
        mock_add_marketing_contact.assert_awaited_once_with("bob@test.com", "Bob", user_id=USER_ID)
        assert _stamps(mock_stamp) == [(USER_ID, SignupDelivery.MARKETING_CONTACT)]

    async def test_a_welcome_email_past_the_idempotency_window_is_not_resent(
        self, mock_stamp, mock_send_welcome_email, mock_add_marketing_contact
    ):
        """Resend forgets the welcome key after 24h; a send older than that could be a second copy."""
        stale = _user(created_at=datetime.now(UTC) - timedelta(hours=25))
        with patch(f"{MODULE}.user_repository.get", AsyncMock(return_value=stale)):
            async with captured_wide_event() as event:
                await deliver_signup_emails({}, USER_ID)

        mock_send_welcome_email.assert_not_awaited()
        mock_add_marketing_contact.assert_awaited_once_with("bob@test.com", "Bob", user_id=USER_ID)
        assert event["welcome_email_abandoned"] is True

    async def test_a_welcome_email_exactly_at_the_window_edge_still_goes_out(
        self, mock_stamp, mock_send_welcome_email, mock_add_marketing_contact
    ):
        now = datetime(2026, 9, 14, 12, 0, tzinfo=UTC)
        edge = _user(created_at=now - WELCOME_EMAIL_RESEND_WINDOW)
        with (
            patch(f"{MODULE}.user_repository.get", AsyncMock(return_value=edge)),
            patch(f"{MODULE}.datetime") as mock_datetime,
        ):
            mock_datetime.now.return_value = now
            await deliver_signup_emails({}, USER_ID)

        mock_send_welcome_email.assert_awaited_once_with("bob@test.com", "Bob", user_id=USER_ID)

    async def test_a_fully_delivered_signup_does_no_work_at_all(
        self, mock_stamp, mock_send_welcome_email, mock_add_marketing_contact
    ):
        now = datetime.now(UTC)
        settled = _user(welcome_email_sent_at=now, marketing_contact_added_at=now)
        with patch(f"{MODULE}.user_repository.get", AsyncMock(return_value=settled)):
            async with captured_wide_event() as event:
                await deliver_signup_emails({}, USER_ID)

        mock_send_welcome_email.assert_not_awaited()
        mock_add_marketing_contact.assert_not_awaited()
        mock_stamp.assert_not_awaited()
        # A run that did nothing has to say so. Without the flag the event is
        # indistinguishable from one where both deliveries went out, and the
        # job's whole idempotency claim becomes unobservable in production.
        assert event["skipped"] is True

    async def test_a_deleted_user_is_skipped_rather_than_mailed(
        self, mock_stamp, mock_send_welcome_email, mock_add_marketing_contact
    ):
        mock_get = AsyncMock(return_value=None)
        with patch(f"{MODULE}.user_repository.get", mock_get):
            async with captured_wide_event() as event:
                await deliver_signup_emails({}, USER_ID)

        mock_send_welcome_email.assert_not_awaited()
        mock_add_marketing_contact.assert_not_awaited()
        # The row is fetched by the id the job was queued with — fetching any
        # other row decides this user's deliveries from someone else's stamps.
        mock_get.assert_awaited_once_with(USER_ID)
        # Every field the job records hangs off this attribution. Unset, the
        # run is unattributable and a user's lost welcome email cannot be found
        # in the logs at all, which is the only place it is visible.
        assert event["user"] == {"id": USER_ID}
        assert event["skipped"] is True

    async def test_the_two_esp_calls_run_concurrently(
        self, stored_user, mock_stamp, mock_send_welcome_email, mock_add_marketing_contact
    ):
        """Both round-trips are in flight at once — neither waits on the other."""
        # A two-party barrier only opens if both calls run at the same time; run
        # sequentially, the first waits on a partner that hasn't started and times out.
        barrier = asyncio.Barrier(2)
        rendezvous: set[str] = set()

        async def _welcome(*_args: str, **_kwargs: str) -> None:
            await asyncio.wait_for(barrier.wait(), timeout=1)
            rendezvous.add("welcome_email")

        async def _contact(*_args: str, **_kwargs: str) -> None:
            await asyncio.wait_for(barrier.wait(), timeout=1)
            rendezvous.add("marketing_contact")

        mock_send_welcome_email.side_effect = _welcome
        mock_add_marketing_contact.side_effect = _contact

        await deliver_signup_emails({}, USER_ID)

        assert rendezvous == {"welcome_email", "marketing_contact"}

    async def test_a_hung_welcome_email_is_abandoned_after_the_timeout(
        self,
        stored_user,
        mock_stamp,
        mock_send_welcome_email,
        mock_add_marketing_contact,
        hung_esp_call,
    ):
        """Unbounded, a hung ESP call would block the job for the worker's whole 30-minute timeout."""
        mock_send_welcome_email.side_effect = hung_esp_call

        with patch(f"{MODULE}.SIGNUP_EMAIL_TIMEOUT_SECONDS", 0.01):
            async with captured_wide_event() as event:
                # Two orders of magnitude above the bound: the job returns here
                # only because the timeout abandoned the call, so an unbounded
                # wait fails this line instead of hanging the suite.
                async with asyncio.timeout(2):
                    await deliver_signup_emails({}, USER_ID)

        assert event["errors"] == [
            {
                "msg": f"{LogTag.OAUTH} Failed to send welcome email to",
                "user": {"id": USER_ID},
                "error": "",
                "error_type": "TimeoutError",
            }
        ]
        mock_add_marketing_contact.assert_awaited_once_with("bob@test.com", "Bob", user_id=USER_ID)

    async def test_a_hung_marketing_contact_is_abandoned_after_the_timeout(
        self,
        stored_user,
        mock_stamp,
        mock_send_welcome_email,
        mock_add_marketing_contact,
        hung_esp_call,
    ):
        """The audience call carries its own timeout, not a shared one that could leave it hanging forever."""
        mock_add_marketing_contact.side_effect = hung_esp_call

        with patch(f"{MODULE}.SIGNUP_EMAIL_TIMEOUT_SECONDS", 0.01):
            async with captured_wide_event() as event:
                async with asyncio.timeout(2):
                    await deliver_signup_emails({}, USER_ID)

        assert event["errors"] == [
            {
                "msg": f"{LogTag.OAUTH} Failed to add marketing contact for",
                "user": {"id": USER_ID},
                "error": "",
                "error_type": "TimeoutError",
            }
        ]
        mock_send_welcome_email.assert_awaited_once_with("bob@test.com", "Bob", user_id=USER_ID)

    async def test_a_welcome_email_failure_is_recorded_and_leaves_no_stamp(
        self, stored_user, mock_stamp, mock_send_welcome_email, mock_add_marketing_contact
    ):
        """A missing stamp hands the delivery to the recovery sweep; stamping a failure would retire an unpaid debt."""
        mock_send_welcome_email.side_effect = RuntimeError("SMTP error")

        async with captured_wide_event() as event:
            await deliver_signup_emails({}, USER_ID)

        assert event["errors"] == [
            {
                "msg": f"{LogTag.OAUTH} Failed to send welcome email to",
                "user": {"id": USER_ID},
                "error": "SMTP error",
                "error_type": "RuntimeError",
            }
        ]
        mock_add_marketing_contact.assert_awaited_once_with("bob@test.com", "Bob", user_id=USER_ID)
        assert _stamps(mock_stamp) == [(USER_ID, SignupDelivery.MARKETING_CONTACT)]

    async def test_a_marketing_contact_failure_is_recorded_and_leaves_no_stamp(
        self, stored_user, mock_stamp, mock_send_welcome_email, mock_add_marketing_contact
    ):
        """Before this the wrapper's except branch was unreachable, so a lost contact logged as success."""
        mock_add_marketing_contact.side_effect = RuntimeError("Resend API error")

        async with captured_wide_event() as event:
            await deliver_signup_emails({}, USER_ID)

        assert event["errors"] == [
            {
                "msg": f"{LogTag.OAUTH} Failed to add marketing contact for",
                "user": {"id": USER_ID},
                "error": "Resend API error",
                "error_type": "RuntimeError",
            }
        ]
        mock_send_welcome_email.assert_awaited_once_with("bob@test.com", "Bob", user_id=USER_ID)
        assert _stamps(mock_stamp) == [(USER_ID, SignupDelivery.WELCOME_EMAIL)]

    async def test_a_cancelled_delivery_does_not_strand_the_other_one(
        self, stored_user, mock_stamp, mock_send_welcome_email, mock_add_marketing_contact
    ):
        """Cancellation escapes each delivery's except Exception and must not drop the other round-trip mid-flight."""
        delivered: list[str] = []

        async def _cancelled(*_args: str, **_kwargs: str) -> None:
            raise asyncio.CancelledError

        async def _slow_contact(*_args: str, **_kwargs: str) -> None:
            await asyncio.sleep(0)
            await asyncio.sleep(0)
            delivered.append("marketing_contact")

        mock_send_welcome_email.side_effect = _cancelled
        mock_add_marketing_contact.side_effect = _slow_contact

        await deliver_signup_emails({}, USER_ID)

        assert delivered == ["marketing_contact"]
