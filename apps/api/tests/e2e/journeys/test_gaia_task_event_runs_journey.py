"""Journey: how the app events a GAIA task listens for become its runs.

An "only when" check skips an email the user can see was skipped, and turning it off lets
the next one run. An email in the user's quiet hours waits for them to end. Emails close
together ride one run. A run an email started that breaks is retried with the email. An
event from an app other than Gmail runs the task through its own trigger.
"""

from __future__ import annotations

from datetime import timedelta

import pytest

from tests.e2e._harness.tasks_driver import TasksDriver
from tests.e2e._harness.tasks_views import Breaks, Finishes, Reports, RunOutcome

pytestmark = pytest.mark.e2e

TITLE = "Keep on top of the landlord's emails"
LANDLORD = "landlord@flatlets.com"
ONLY_DEPOSIT = "The email is about the deposit."
HANDLED = "Answered the landlord."


class TestAnOnlyWhenCheck:
    async def test_a_skipped_email_shows_on_the_task_and_turning_the_check_off_runs_the_next(
        self, tasks: TasksDriver
    ) -> None:
        await tasks.connect_app("gmail")
        task = await tasks.hand_to_gaia(TITLE, first_look="3d")
        await tasks.watch_emails_from(task.id, LANDLORD, only_when=ONLY_DEPOSIT)

        await tasks.new_email(
            subject="Bins go out Tuesday", sender=LANDLORD, gate_passes=False, delivery_id="1"
        )
        skipped = await tasks.get(task.id)
        assert skipped is not None and skipped.skipped_events
        assert await tasks.woken_by_events(task.id) == 0

        await tasks.turn_off_only_when(task.id)
        await tasks.new_email(
            subject="Recycling too", sender=LANDLORD, gate_passes=False, delivery_id="2"
        )
        await tasks.run_due(task.id, Finishes(HANDLED))

        assert [(r.outcome, r.by_event) for r in await tasks.runs(task.id)] == [
            (RunOutcome.SUCCEEDED, True)
        ]


class TestQuietHours:
    async def test_an_email_in_quiet_hours_runs_when_they_end(self, tasks: TasksDriver) -> None:
        await tasks.keep_quiet_hours(start_hour=9, end_hour=12)
        await tasks.connect_app("gmail")
        task = await tasks.hand_to_gaia(TITLE, first_look="3d")
        await tasks.watch_emails_from(task.id, LANDLORD, only_when=ONLY_DEPOSIT)

        await tasks.new_email(
            subject="Re: deposit", sender=LANDLORD, gate_passes=True, delivery_id="3"
        )
        assert await tasks.runs(task.id) == []
        assert (await tasks.armed_times(task.id))[0].hour == 12
        await tasks.run_due(task.id, Finishes(HANDLED))

        runs = await tasks.runs(task.id)
        assert [(r.outcome, r.by_event) for r in runs] == [(RunOutcome.SUCCEEDED, True)]
        assert tasks.last_run_was_shown("Re: deposit")


class TestEmailsCloseTogether:
    async def test_later_emails_ride_one_run_together(self, tasks: TasksDriver) -> None:
        await tasks.connect_app("gmail")
        task = await tasks.hand_to_gaia(TITLE, first_look="3d")
        await tasks.watch_emails_from(task.id, LANDLORD, batch_for=timedelta(hours=1))

        await tasks.new_email(subject="Re: deposit", sender=LANDLORD, delivery_id="4")
        await tasks.run_due(task.id, Reports("Read the deposit email."))
        await tasks.new_email(subject="The boiler", sender=LANDLORD, delivery_id="5")
        await tasks.new_email(subject="The keys", sender=LANDLORD, delivery_id="6")
        await tasks.run_due(task.id, Reports("Read the boiler and keys emails."))

        runs = await tasks.runs(task.id)
        assert [(r.outcome, r.by_event) for r in runs] == [(RunOutcome.SUCCEEDED, True)] * 2
        assert tasks.last_run_was_shown("The boiler") and tasks.last_run_was_shown("The keys")
        assert await tasks.woken_by_events(task.id) == 3


class TestARunAnEmailStartedBreaks:
    async def test_it_is_retried_with_the_email(self, tasks: TasksDriver) -> None:
        await tasks.connect_app("gmail")
        task = await tasks.hand_to_gaia(TITLE, first_look="3d")
        await tasks.watch_emails_from(task.id, LANDLORD)

        await tasks.new_email(subject="Re: deposit", sender=LANDLORD, delivery_id="7")
        await tasks.run_due(task.id, Breaks())
        await tasks.run_due(task.id, Finishes(HANDLED))

        runs = await tasks.runs(task.id)
        assert [(r.outcome, r.by_event) for r in runs] == [
            (RunOutcome.FAILED, True),
            (RunOutcome.SUCCEEDED, True),
        ]
        assert tasks.last_run_was_shown("Re: deposit")


class TestAnEventFromGitHub:
    async def test_a_pull_request_on_the_watched_repo_runs_the_task_and_another_repo_does_not(
        self, tasks: TasksDriver
    ) -> None:
        await tasks.connect_app("github")
        task = await tasks.hand_to_gaia("Review new pull requests on the site", first_look="3d")
        await tasks.watch_pull_requests(task.id, "acme/site")

        await tasks.new_pull_request(task.id, title="Fix the footer", number=42)
        await tasks.new_pull_request(
            task.id, title="Bump a dependency", number=7, on_watched_repo=False
        )
        await tasks.run_due(task.id, Finishes("Reviewed the footer fix."))

        runs = await tasks.runs(task.id)
        assert [(r.outcome, r.by_event) for r in runs] == [(RunOutcome.SUCCEEDED, True)]
        assert tasks.last_run_was_shown("Fix the footer")
