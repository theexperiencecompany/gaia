"""Unit tests for the signup-delivery recovery sweep.

Queueing the welcome email made the *job* durable; it did not make the *intent*
durable. A Redis hiccup at signup loses the enqueue outright, and nothing in the
system then records that the user is still owed a founder email and a place in
the nurture audience. This sweep is that record's collector: it re-enqueues for
anyone whose stamps are still missing.

Two properties carry the whole design and are asserted here. The lookback window
is a safety bound, not a tuning knob — every account that predates these stamps
carries neither, so an unbounded sweep would mail the entire user base on its
first run. And the enqueue is deduped per user, so a sweep overlapping signup's
own enqueue adds nothing.
"""

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

from app.constants.email import (
    SIGNUP_EMAIL_SWEEP_LOOKBACK_DAYS,
    SIGNUP_EMAIL_SWEEP_MAX_USERS_PER_RUN,
)
from app.services.email.signup_delivery import signup_email_job_id
from app.workers.tasks.signup_email_tasks import sweep_undelivered_signup_emails
from tests.helpers import captured_wide_event

MODULE = "app.workers.tasks.signup_email_tasks"

USER_ID = "507f1f77bcf86cd799439011"
OTHER_USER_ID = "507f1f77bcf86cd799439012"
THIRD_USER_ID = "507f1f77bcf86cd799439013"


def _pool() -> MagicMock:
    pool = MagicMock()
    pool.enqueue_job = AsyncMock(return_value=MagicMock())
    return pool


def _candidates(*user_ids: str):
    return patch(
        f"{MODULE}.user_repository.find_undelivered_signup_ids",
        AsyncMock(return_value=list(user_ids)),
    )


class TestSweepUndeliveredSignupEmails:
    async def test_a_lost_enqueue_is_finished_later(self):
        """The signup whose enqueue never reached Redis: no job, no stamps, and
        until this sweep ran, no record anywhere that anything was owed."""
        pool = _pool()
        with (
            _candidates(USER_ID, OTHER_USER_ID),
            patch(f"{MODULE}.RedisPoolManager.get_pool", AsyncMock(return_value=pool)),
        ):
            await sweep_undelivered_signup_emails({})

        assert pool.enqueue_job.await_count == 2
        assert [call.args for call in pool.enqueue_job.await_args_list] == [
            ("deliver_signup_emails", USER_ID),
            ("deliver_signup_emails", OTHER_USER_ID),
        ]

    async def test_the_run_reports_how_many_of_how_many_it_recovered(self):
        """Three owed, one already queued, so two were actually recovered.

        The two counts are deliberately different here. Equal numbers would let
        a swapped, doubled or negated counter still read as correct, and this
        summary is the only signal that says whether the backlog is draining —
        a sweep silently recovering nothing looks exactly like one with
        nothing to do.
        """
        pool = _pool()
        # Third candidate dedups against a job signup already queued.
        pool.enqueue_job = AsyncMock(side_effect=[MagicMock(), MagicMock(), None])
        with (
            _candidates(USER_ID, OTHER_USER_ID, THIRD_USER_ID),
            patch(f"{MODULE}.RedisPoolManager.get_pool", AsyncMock(return_value=pool)),
        ):
            async with captured_wide_event() as event:
                result = await sweep_undelivered_signup_emails({})

        assert result == "sweep_undelivered_signup_emails enqueued 2 of 3 undelivered signup(s)"
        assert event["signup_delivery_candidates"] == 3
        assert event["enqueued"] == 2

    async def test_each_candidate_is_enqueued_exactly_once_per_user(self):
        """Deduped on the same per-user id signup itself uses, so a sweep that
        overlaps a still-queued signup job cannot produce a second send."""
        pool = _pool()
        with (
            _candidates(USER_ID, OTHER_USER_ID),
            patch(f"{MODULE}.RedisPoolManager.get_pool", AsyncMock(return_value=pool)),
        ):
            await sweep_undelivered_signup_emails({})

        assert [call.kwargs["_job_id"] for call in pool.enqueue_job.await_args_list] == [
            signup_email_job_id(USER_ID),
            signup_email_job_id(OTHER_USER_ID),
        ]

    async def test_a_deduped_enqueue_is_not_counted_as_recovered(self):
        """ARQ returns None when the job is already queued. Counting that as a
        recovery would report the backlog as drained while it still is not."""
        pool = _pool()
        pool.enqueue_job = AsyncMock(return_value=None)
        with (
            _candidates(USER_ID),
            patch(f"{MODULE}.RedisPoolManager.get_pool", AsyncMock(return_value=pool)),
        ):
            result = await sweep_undelivered_signup_emails({})

        assert result == "sweep_undelivered_signup_emails enqueued 0 of 1 undelivered signup(s)"

    async def test_the_lookback_window_bounds_which_signups_are_swept(self):
        """Without this bound the first run mails every user who ever signed up:
        they all predate the stamps, so they all read as undelivered."""
        pool = _pool()
        before = datetime.now(UTC)
        with (
            _candidates() as find,
            patch(f"{MODULE}.RedisPoolManager.get_pool", AsyncMock(return_value=pool)),
        ):
            await sweep_undelivered_signup_emails({})
        after = datetime.now(UTC)

        created_since = find.call_args.args[0]
        assert (
            before - timedelta(days=SIGNUP_EMAIL_SWEEP_LOOKBACK_DAYS)
            <= created_since
            <= after - timedelta(days=SIGNUP_EMAIL_SWEEP_LOOKBACK_DAYS)
        )

    async def test_candidates_are_capped_per_run(self):
        pool = _pool()
        with (
            _candidates() as find,
            patch(f"{MODULE}.RedisPoolManager.get_pool", AsyncMock(return_value=pool)),
        ):
            await sweep_undelivered_signup_emails({})

        assert find.call_args.kwargs["limit"] == SIGNUP_EMAIL_SWEEP_MAX_USERS_PER_RUN

    async def test_nothing_owed_means_nothing_enqueued(self):
        pool = _pool()
        with (
            _candidates(),
            patch(f"{MODULE}.RedisPoolManager.get_pool", AsyncMock(return_value=pool)),
        ):
            await sweep_undelivered_signup_emails({})

        pool.enqueue_job.assert_not_awaited()
