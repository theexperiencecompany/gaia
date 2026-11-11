"""The pool gathers each producer's candidates for one brief, handing each producer its own inputs.

Faked seams: the producers, so each call's arguments and the numbering of what they return show.
"""

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock
from zoneinfo import ZoneInfo

import pytest
from tests.factories import make_user_id

from app.constants.briefing import GAIA_APP_NAME, GAIA_SOURCE, BriefItemSource
from app.constants.todos import GAIA_TRACKED_LABEL
from app.models.brief_candidate_models import BriefCandidate, CandidateKind
from app.models.brief_models import PendingBriefItemDocument
from app.models.briefing_models import BriefingEvent, UnreadSource
from app.models.scout_models import ScoutOutcome, ScoutResult, ScoutSkipReason
from app.models.todo_models import TodoDocument
from app.services.briefing.candidates import pool as pool_module
from app.services.briefing.candidates.pool import (
    CandidateSources,
    gather_candidates,
    gather_week_candidates,
)
from app.services.briefing.context import CompletedWork, TrackedWork, UserClock, day_start_utc
from app.services.briefing.scouts.service import ScoutSignals

USER_ID = make_user_id()
NOW = datetime(2026, 11, 10, 2, 30, tzinfo=UTC)
SINCE = NOW - timedelta(days=1)
TZ = ZoneInfo("Asia/Kolkata")
CLOCK = UserClock(tz=TZ, now_local=NOW.astimezone(TZ), date_str="2026-11-10", day_of_year=314)


def _candidate(title: str, **fields: object) -> BriefCandidate:
    defaults: dict[str, object] = {
        "source": GAIA_SOURCE,
        "app": GAIA_APP_NAME,
        "kind": CandidateKind.UPDATE,
        "state": "note",
        "title": title,
    }
    return BriefCandidate.model_validate({**defaults, **fields})


def _todo(todo_id: str) -> TodoDocument:
    return TodoDocument(id=todo_id, user_id=USER_ID, title=todo_id, labels=[GAIA_TRACKED_LABEL])


@pytest.fixture
def producers(monkeypatch: pytest.MonkeyPatch) -> dict[str, MagicMock]:
    fakes: dict[str, MagicMock] = {
        "waiting_candidates": MagicMock(return_value=[]),
        "approval_candidates": AsyncMock(return_value=[]),
        "reminder_candidates": AsyncMock(return_value=[]),
        "failed_run_candidates": AsyncMock(return_value=[]),
        "app_signal_candidates": MagicMock(return_value=[]),
        "held_candidates": AsyncMock(return_value=[]),
        "gaia_work_candidates": MagicMock(return_value=[]),
        "calendar_candidates": MagicMock(return_value=[]),
        "user_done_candidates": MagicMock(return_value=[]),
    }
    for name, fake in fakes.items():
        monkeypatch.setattr(pool_module, name, fake)
    return fakes


class TestGatherCandidates:
    async def test_each_producer_reads_its_own_window_for_this_user(
        self, producers: dict[str, MagicMock]
    ) -> None:
        work = TrackedWork(
            completed=[_todo("done")],
            running=[_todo("run")],
            blocked=[_todo("block")],
            failed=[_todo("fail")],
        )
        scouts = ScoutSignals(remembered=[], criteria={}, results=[])
        held = [
            PendingBriefItemDocument(
                id="h1",
                user_id=USER_ID,
                source=BriefItemSource.WORKFLOW,
                source_id="wf-1",
                source_title="Digest",
                conversation_id="conv-1",
                text="3 new papers",
            )
        ]
        events = [BriefingEvent(date="2026-11-10", title="Sequoia")]

        await gather_candidates(
            USER_ID, CLOCK, SINCE, NOW, CandidateSources(work, held, scouts, events)
        )

        day_start = day_start_utc(CLOCK)
        assert producers["approval_candidates"].await_args.args == (
            USER_ID,
            NOW,
            {"block", "fail", "run"},
        )
        assert producers["reminder_candidates"].await_args.args == (
            USER_ID,
            day_start,
            day_start + timedelta(days=1),
        )
        assert producers["failed_run_candidates"].await_args.args == (USER_ID, SINCE)
        assert producers["held_candidates"].await_args.args == (USER_ID, held)
        assert producers["app_signal_candidates"].call_args.args == (scouts.remembered, NOW)
        assert producers["waiting_candidates"].call_args.args == (work,)
        assert producers["gaia_work_candidates"].call_args.args == (work,)
        assert producers["calendar_candidates"].call_args.args == (events,)

    async def test_the_apps_read_are_the_scouts_that_ran_and_the_apps_candidates_came_from(
        self, producers: dict[str, MagicMock]
    ) -> None:
        scouts = ScoutSignals(
            remembered=[],
            criteria={},
            results=[
                ScoutResult(integration_id="linear", app="Linear", outcome=ScoutOutcome.REPLAYED),
                ScoutResult(
                    integration_id="github",
                    app="GitHub",
                    outcome=ScoutOutcome.SKIPPED,
                    skip_reason=ScoutSkipReason.BUDGET,
                ),
                ScoutResult(
                    integration_id="notion", app="Notion", outcome=ScoutOutcome.NOTHING_TO_WATCH
                ),
            ],
        )
        producers["app_signal_candidates"].return_value = [
            _candidate("Fix the redirect", source="linear", app="Linear"),
            _candidate("Reply to Dan", source="gmail", app="Gmail"),
        ]

        gathered = await gather_candidates(
            USER_ID, CLOCK, SINCE, NOW, CandidateSources(TrackedWork(), [], scouts, [])
        )

        assert gathered.sources_read == ["Linear", "Notion", "Gmail"]
        assert gathered.sources_unavailable == [
            UnreadSource(app="GitHub", reason=ScoutSkipReason.BUDGET)
        ]

    async def test_the_pool_is_numbered_from_one_in_producer_order(
        self, producers: dict[str, MagicMock]
    ) -> None:
        producers["waiting_candidates"].return_value = [_candidate("Reply to Dan")]
        producers["approval_candidates"].return_value = [_candidate("Approve the send")]
        producers["calendar_candidates"].return_value = [
            _candidate("Sequoia", kind=CandidateKind.EVENT)
        ]
        sources = CandidateSources(
            TrackedWork(), [], ScoutSignals(remembered=[], criteria={}, results=[]), []
        )

        gathered = await gather_candidates(USER_ID, CLOCK, SINCE, NOW, sources)

        assert {i: c.title for i, c in gathered.pool.items()} == {
            1: "Reply to Dan",
            2: "Approve the send",
            3: "Sequoia",
        }
        assert gathered.has_news is True

    async def test_a_held_result_saying_what_another_candidate_says_is_folded_into_it(
        self, producers: dict[str, MagicMock]
    ) -> None:
        producers["waiting_candidates"].return_value = [_candidate("Reply to  DAN")]
        producers["held_candidates"].return_value = [
            _candidate("reply to dan", held_id="h1"),
            _candidate("Stripe payout landed", held_id="h2"),
            _candidate("stripe payout   landed", held_id="h3"),
        ]
        sources = CandidateSources(
            TrackedWork(), [], ScoutSignals(remembered=[], criteria={}, results=[]), []
        )

        gathered = await gather_candidates(USER_ID, CLOCK, SINCE, NOW, sources)

        assert [c.title for c in gathered.pool.values()] == [
            "Reply to  DAN",
            "Stripe payout landed",
        ]
        assert gathered.duplicate_held_ids == ["h1", "h3"]


class TestGatherWeekCandidates:
    async def test_the_week_reads_failed_runs_what_got_done_and_the_week_ahead(
        self, producers: dict[str, MagicMock]
    ) -> None:
        completed = CompletedWork(gaia=[_todo("g1")], user=[_todo("u1")])
        ahead = [BriefingEvent(date="2026-11-12", title="Offsite")]
        producers["failed_run_candidates"].return_value = [_candidate("CRM sync failed")]
        producers["user_done_candidates"].return_value = [_candidate("Filed VAT")]
        producers["gaia_work_candidates"].return_value = [_candidate("Investor update")]
        producers["calendar_candidates"].return_value = [
            _candidate(
                "Offsite", kind=CandidateKind.EVENT, source="google_calendar", app="Calendar"
            )
        ]

        gathered = await gather_week_candidates(USER_ID, SINCE, completed, ahead)

        assert producers["failed_run_candidates"].await_args.args == (USER_ID, SINCE)
        assert producers["user_done_candidates"].call_args.args == (completed.user,)
        assert producers["gaia_work_candidates"].call_args.args[0].completed == completed.gaia
        assert producers["calendar_candidates"].call_args.args == (ahead,)
        assert [c.title for c in gathered.pool.values()] == [
            "CRM sync failed",
            "Filed VAT",
            "Investor update",
            "Offsite",
        ]
        assert gathered.sources_read == ["Calendar"]
        assert gathered.sources_unavailable == []

    async def test_a_held_duplicate_in_the_week_is_reported_for_clearing(
        self, producers: dict[str, MagicMock]
    ) -> None:
        producers["failed_run_candidates"].return_value = [_candidate("Done thing")]
        producers["user_done_candidates"].return_value = [_candidate("done  thing", held_id="h9")]

        gathered = await gather_week_candidates(USER_ID, SINCE, CompletedWork(), [])

        assert gathered.duplicate_held_ids == ["h9"]
