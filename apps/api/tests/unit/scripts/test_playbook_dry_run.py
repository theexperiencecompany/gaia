"""playbook_dry_run: each shipped recipe replayed for one user, reads only, against their next event."""

from __future__ import annotations

import argparse
from datetime import UTC
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.models.calendar_models import GoogleCalendarEventResource
from app.scripts import playbook_dry_run as script
from app.services.system_workflows.definitions import SYSTEM_RECIPES
from app.services.workflow.playbook.dry_run import DryRun
from app.services.workflow.playbook.evaluator import PlaybookUser
from app.services.workflow.playbook.runner import PlaybookRunResult
from app.services.workflow.playbook.workflow_hash import workflow_hash

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
        assert kwargs["trigger"] == {
            "trigger_type": "integration",
            "trigger_data": {
                "event_id": "evt_9",
                "calendar_id": "dana@acme.com",
                "summary": "1:1",
                "start_time": None,
                "html_link": None,
            },
        }
        assert kwargs["user"] == PlaybookUser(email="dana@acme.com", name="Dana", timezone="UTC")
        assert kwargs["conversation_id"] == "dry_run_wf_1"
        assert run.await_args.args[0].created_at.tzinfo is UTC
        playbook = run.await_args.args[0]
        assert (playbook.workflow_id, playbook.user_id) == ("wf_1", "u1")
        assert playbook.authored_run == f"recipe:{REMINDER}"
        assert playbook.workflow_hash == workflow_hash("p", [])
        assert playbook.steps == SYSTEM_RECIPES[REMINDER]().steps

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

        with (
            first,
            second,
            third,
            fourth,
            pytest.raises(SystemExit) as stopped,
        ):
            await script._run(argparse.Namespace(user_id="u1", key=REMINDER))

        assert str(stopped.value) == (
            "the user has no upcoming calendar event to dry-run a calendar recipe on"
        )

    async def test_it_reads_the_users_next_events_and_prints_what_each_recipe_did(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        workflow = MagicMock(id="wf_1", prompt="p", steps=[])
        event = GoogleCalendarEventResource(id="evt_9", summary="1:1")
        run = AsyncMock(
            return_value=PlaybookRunResult(
                ok=True, text="Heads-up.", completed=["event (get) -> x" * 200], llm_calls=1
            )
        )
        first, second, third, fourth = _patches(workflow, [event], run)

        with first, second, third, fourth as _, patch(f"{MODULE}.datetime") as clock:
            clock.now.return_value.isoformat.return_value = "2026-11-03T10:00:00+00:00"
            await script._run(argparse.Namespace(user_id="u1", key=REMINDER))
            calendar = script.get_calendar_events
            lookup = script.get_user_by_id

        calendar.assert_awaited_once_with(
            user_id="u1", time_min="2026-11-03T10:00:00+00:00", max_results=5
        )
        assert clock.now.call_args_list == [((UTC,),), ((UTC,),)]
        lookup.assert_awaited_once_with("u1")
        out = capsys.readouterr().out
        assert (
            f"== {REMINDER} (wf_1)\ntrigger: "
            '{"trigger_type": "integration", "trigger_data": {"event_id": "evt_9", '
            '"calendar_id": "primary", "summary": "1:1", "start_time": null, "html_link": null}}\n'
        ) in out
        assert "  step: " + ("event (get) -> x" * 200)[:400] + "\n" in out
        assert "  model calls: 1; flagged: no\n" in out
        assert "  narration (not delivered):\nHeads-up.\n" in out

    async def test_a_flagged_run_says_why_and_a_stopped_one_says_where(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        workflow = MagicMock(id="wf_1", prompt="p", steps=[])
        event = GoogleCalendarEventResource(id="evt_9")
        run = AsyncMock(
            side_effect=[
                PlaybookRunResult(ok=False, failure="no such event"),
                PlaybookRunResult(ok=True, text="t", suspect="came back empty"),
            ]
        )
        first, second, third, fourth = _patches(workflow, [event], run)

        with first, second, third, fourth:
            failed = await script._run(argparse.Namespace(user_id="u1", key=None))

        out = capsys.readouterr().out
        assert failed == 1
        assert "  STOPPED: no such event\n" in out
        assert "flagged: came back empty\n" in out

    async def test_a_missing_workflow_skips_only_that_recipe(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        workflow = MagicMock(id="wf_2", prompt="p", steps=[])
        run = AsyncMock(return_value=PlaybookRunResult(ok=True, text="t"))
        first, second, third, fourth = _patches(
            workflow, [GoogleCalendarEventResource(id="e")], run
        )

        with first, second, third, fourth as _, patch(f"{MODULE}.workflow_repository") as repo:
            repo.find_system_workflow = AsyncMock(side_effect=[None, workflow])
            await script._run(argparse.Namespace(user_id="u1", key=None))

        assert repo.find_system_workflow.await_args_list[0].args == (
            "u1",
            sorted(SYSTEM_RECIPES)[0],
        )
        assert run.await_count == 1
        assert f"== {sorted(SYSTEM_RECIPES)[0]}: the user has no such workflow; skipped" in (
            capsys.readouterr().out
        )

    async def test_an_unknown_user_stops_with_the_id(self) -> None:
        with (
            patch(f"{MODULE}.get_user_by_id", AsyncMock(return_value=None)),
            pytest.raises(SystemExit, match="no user u404"),
        ):
            await script._run(argparse.Namespace(user_id="u404", key=None))

    async def test_a_user_with_no_name_or_timezone_replays_in_utc(self) -> None:
        user = MagicMock(email=None, timezone=None)
        user.name = None
        workflow = MagicMock(id="wf_1", prompt="p", steps=[])
        run = AsyncMock(return_value=PlaybookRunResult(ok=True, text="t"))
        first, second, third, fourth = _patches(
            workflow, [GoogleCalendarEventResource(id="e")], run
        )

        with (
            first,
            second,
            third,
            fourth,
            patch(f"{MODULE}.get_user_by_id", AsyncMock(return_value=user)),
        ):
            await script._run(argparse.Namespace(user_id="u1", key=REMINDER))

        assert run.await_args.kwargs["user"] == PlaybookUser(email="", name="", timezone="UTC")

    async def test_every_stopped_recipe_is_counted(self) -> None:
        workflow = MagicMock(id="wf_1", prompt="p", steps=[])
        run = AsyncMock(return_value=PlaybookRunResult(ok=False, failure="stopped"))
        first, second, third, fourth = _patches(
            workflow, [GoogleCalendarEventResource(id="e")], run
        )

        with first, second, third, fourth:
            failed = await script._run(argparse.Namespace(user_id="u1", key=None))

        assert failed == len(SYSTEM_RECIPES)
