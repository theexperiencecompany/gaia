"""playbook_dry_run: each shipped recipe replayed for one user, reads only, against their next event."""

from __future__ import annotations

import argparse
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.models.calendar_models import GoogleCalendarEventResource
from app.scripts import playbook_dry_run as script
from app.services.workflow.playbook.dry_run import DryRun
from app.services.workflow.playbook.runner import PlaybookRunResult

MODULE = "app.scripts.playbook_dry_run"
REMINDER = "calendar:meeting_reminder"


def _patches(workflow: MagicMock | None, events: list[GoogleCalendarEventResource], run: AsyncMock):
    user = MagicMock(email="dana@acme.com", timezone="UTC")
    user.name = "Dana"
    repo = MagicMock()
    repo.find_system_workflow = AsyncMock(return_value=workflow)
    return (
        patch(f"{MODULE}.get_user_by_id", AsyncMock(return_value=user)),
        patch(f"{MODULE}.workflow_repository", repo),
        patch(f"{MODULE}.get_calendar_events", AsyncMock(return_value=MagicMock(events=events))),
        patch(f"{MODULE}.run_playbook", run),
    )


@pytest.mark.unit
class TestPlaybookDryRun:
    async def test_the_recipe_replays_as_a_dry_run_on_the_users_next_event(self) -> None:
        workflow = MagicMock(id="wf_1", prompt="p", steps=[])
        event = GoogleCalendarEventResource(id="evt_9", calendarId="dana@acme.com", summary="1:1")
        run = AsyncMock(return_value=PlaybookRunResult(ok=True, text="Heads-up."))
        first, second, third, fourth = _patches(workflow, [event], run)

        with first, second, third, fourth:
            failed = await script._run(argparse.Namespace(user_id="u1", key=REMINDER))

        assert failed == 0
        kwargs = run.await_args.kwargs
        assert isinstance(kwargs["dry_run"], DryRun)
        assert kwargs["trigger"]["trigger_data"]["event_id"] == "evt_9"
        assert kwargs["trigger"]["trigger_data"]["calendar_id"] == "dana@acme.com"
        assert run.await_args.args[0].workflow_id == "wf_1"

    async def test_a_stopped_replay_is_counted_as_failed(self) -> None:
        workflow = MagicMock(id="wf_1", prompt="p", steps=[])
        event = GoogleCalendarEventResource(id="evt_9", summary="1:1")
        run = AsyncMock(return_value=PlaybookRunResult(ok=False, failure="no such event"))
        first, second, third, fourth = _patches(workflow, [event], run)

        with first, second, third, fourth:
            failed = await script._run(argparse.Namespace(user_id="u1", key=REMINDER))

        assert failed == 1

    async def test_a_user_without_the_workflow_is_skipped_without_a_replay(self) -> None:
        run = AsyncMock()
        first, second, third, fourth = _patches(None, [], run)

        with first, second, third, fourth:
            failed = await script._run(argparse.Namespace(user_id="u1", key=REMINDER))

        assert failed == 0
        run.assert_not_awaited()

    async def test_no_upcoming_event_stops_with_the_reason(self) -> None:
        workflow = MagicMock(id="wf_1", prompt="p", steps=[])
        first, second, third, fourth = _patches(workflow, [], AsyncMock())

        with first, second, third, fourth, pytest.raises(SystemExit, match="no upcoming"):
            await script._run(argparse.Namespace(user_id="u1", key=REMINDER))
