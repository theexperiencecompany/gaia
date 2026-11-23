"""What the brief looks back on: the last brief's plan against what finished, and briefs left unread.

The briefing, todo and workflow repositories and the activity read are the faked seams.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from tests.briefing_factories import make_brief_item, make_briefing_payload
from tests.briefing_helpers import user_clock
from tests.factories import make_todo, make_user_id

from app.constants.briefing import WINBACK_THRESHOLD, BriefingKind
from app.constants.todos import GAIA_TRACKED_LABEL, TodoCompleter
from app.db.repositories.briefings import briefing_repository
from app.db.repositories.todos import todo_repository
from app.db.repositories.workflow_executions import workflow_executions_repository
from app.db.repositories.workflows import workflow_repository
from app.models.brief_document_models import BriefingModel
from app.models.brief_payload_models import BriefingMood
from app.models.todo_models import TodoDocument
from app.models.user_models import UserDocument
from app.models.workflow_execution_models import WorkflowExecutionDocument
from app.services.briefing import wind_down
from app.services.briefing.lookback import (
    Lookback,
    compute_winback_state,
    format_lookback_block,
    lookback_since,
)
from app.services.briefing.work import read_work

USER_ID = make_user_id()
# Tuesday 13 Oct 2026, 09:00 in Kolkata.
CLOCK = user_clock("Asia/Kolkata", date(2026, 10, 13), 9)
_WINBACK_USER = UserDocument(id=USER_ID)


async def _lookback(last: BriefingModel | None, since: datetime) -> str:
    reads = await read_work(USER_ID, since)
    return await format_lookback_block(USER_ID, reads, Lookback(last, since), CLOCK)


def _finished_at_cutoff(*docs: TodoDocument) -> AsyncMock:
    """Stand in for list_completed_since: each todo completed right at the cutoff it was read from."""
    return AsyncMock(
        side_effect=lambda _user_id, since: [
            d.model_copy(update={"completed": True, "completed_at": since}) for d in docs
        ]
    )


def _brief(mood: BriefingMood, *, items: list[str] | None = None) -> BriefingModel:
    return BriefingModel(
        user_id=USER_ID,
        date="2026-10-12",
        payload=make_briefing_payload(
            date="2026-10-12",
            mood=mood,
            sections=[
                {"numeral": "I", "title": "T", "items": [make_brief_item(t) for t in items or []]}
            ],
        ),
        created_at=datetime(2026, 10, 12, 8, tzinfo=UTC),
    )


def _sent_days_ago(brief: BriefingModel, days: int) -> BriefingModel:
    brief.created_at = datetime(2026, 10, 12, 8, tzinfo=UTC) - timedelta(days=days)
    return brief


def _execution(status: str, summary: str | None) -> WorkflowExecutionDocument:
    return WorkflowExecutionDocument.model_validate(
        {
            "execution_id": "e1",
            "workflow_id": "w1",
            "user_id": USER_ID,
            "status": status,
            "started_at": datetime(2026, 10, 13, tzinfo=UTC),
            "summary": summary,
        }
    )


class TestFormatLookbackBlock:
    @pytest.fixture
    def reads(self, monkeypatch: pytest.MonkeyPatch) -> SimpleNamespace:
        reads = SimpleNamespace(
            completed=AsyncMock(return_value=[]),
            executions=AsyncMock(return_value=[]),
            briefing_workflows=AsyncMock(
                return_value=[SimpleNamespace(id="wf-daily"), SimpleNamespace(id="wf-weekly")]
            ),
        )
        monkeypatch.setattr(todo_repository, "list_completed_since", reads.completed)
        for name in ("list_active_tracked", "list_open_user_todos"):
            monkeypatch.setattr(todo_repository, name, AsyncMock(return_value=[]))
        monkeypatch.setattr(workflow_executions_repository, "list_since", reads.executions)
        monkeypatch.setattr(workflow_repository, "find_system_workflows", reads.briefing_workflows)
        return reads

    async def test_the_whole_block_reads_plan_then_done_then_runs(
        self, reads: SimpleNamespace
    ) -> None:
        reads.completed.side_effect = _finished_at_cutoff(
            make_todo("Deck", GAIA_TRACKED_LABEL, completed_by=TodoCompleter.GAIA),
            make_todo("", GAIA_TRACKED_LABEL, id="c2"),
            make_todo("Gym"),
            make_todo("", id="c4"),
            # Audit: GAIA's tracked work the user closed, or an event closed, read "GAIA finished".
            make_todo("Pay Acme", GAIA_TRACKED_LABEL, completed_by=TodoCompleter.USER),
            make_todo("Sam's yes", GAIA_TRACKED_LABEL, completed_by=TodoCompleter.TRIGGER),
            make_todo("Old lead", GAIA_TRACKED_LABEL, completed_by=TodoCompleter.SYSTEM),
        ).side_effect
        reads.executions.return_value = [
            _execution("success", "3 drafts"),
            _execution("failed", None),
        ]
        since = datetime(2026, 10, 13, tzinfo=UTC)
        yesterday = _brief(BriefingMood.CLEAR, items=["Finish the deck", "Book flights"])
        yesterday.created_at = since

        block = await _lookback(yesterday, since)

        assert block == (
            # Audit: it said the user was told GAIA would "focus on" every item, done or not.
            "Your last brief, yesterday, told the user about:\n"
            "- note: Finish the deck\n"
            "- note: Book flights\n\n"
            "Actually completed since then:\n"
            "- GAIA finished: Deck\n"
            "- The user finished: Gym\n"
            "- The user finished: untitled\n"
            "- The user finished: Pay Acme\n"
            "- Closed (who closed it is not recorded): untitled\n"
            "- Closed when an event it watched fired: Sam's yes\n\n"
            "Background workflow runs since then:\n"
            "- Workflow [success]: 3 drafts\n"
            "- Workflow [failed]"
        )
        reads.completed.assert_awaited_once_with(USER_ID, since=since)
        # The briefing workflows' own runs are not background work to report.
        reads.briefing_workflows.assert_awaited_once_with(
            USER_ID, ("daily_briefing", "weekly_digest")
        )
        reads.executions.assert_awaited_once_with(
            USER_ID, since, exclude_workflow_ids=["wf-daily", "wf-weekly"], limit=20
        )

    async def test_a_first_look_back_with_nothing_done_says_both_plainly(
        self, reads: SimpleNamespace
    ) -> None:
        block = await _lookback(None, datetime.now(UTC))

        assert block == (
            "No prior briefing — this is the first look-back.\n\n"
            "Nothing was completed since the last briefing."
        )

    async def test_only_the_users_own_completions_still_count_as_done(
        self, reads: SimpleNamespace
    ) -> None:
        reads.completed.side_effect = _finished_at_cutoff(make_todo("Gym")).side_effect

        block = await _lookback(None, datetime.now(UTC))

        assert block.endswith("Actually completed since then:\n- The user finished: Gym")

    async def test_a_brief_days_ago_is_named_by_its_day_not_as_yesterday(
        self, reads: SimpleNamespace
    ) -> None:
        friday = _brief(BriefingMood.CLEAR, items=["Finish the deck"])
        friday.date = "2026-10-09"

        block = await _lookback(friday, friday.created_at)

        assert block.startswith(
            "Your last brief, on Friday Oct 9, told the user about:\n- note: Finish the deck"
        )
        assert "Yesterday" not in block

    async def test_a_brief_older_than_the_look_back_is_named_but_not_quoted(
        self, reads: SimpleNamespace
    ) -> None:
        old = _brief(BriefingMood.CLEAR, items=["Finish the deck"])
        old.date = "2026-09-20"
        old.created_at = datetime(2026, 9, 20, 2, tzinfo=UTC)
        since = lookback_since(CLOCK, old)

        block = await _lookback(old, since)

        assert since == CLOCK.day_start(days_ago=7)
        assert block.startswith("The last brief went out on Sunday Sep 20, over 7 days ago")
        assert "Finish the deck" not in block


class TestLookbackSince:
    def test_with_no_brief_before_it_starts_at_yesterdays_midnight(self) -> None:
        assert lookback_since(CLOCK, None) == CLOCK.day_start(days_ago=1)

    def test_it_starts_when_the_last_brief_went_out(self) -> None:
        friday = _brief(BriefingMood.CLEAR)
        friday.created_at = datetime(2026, 10, 9, 2, 30, tzinfo=UTC)

        assert lookback_since(CLOCK, friday) == friday.created_at


class TestComputeWinbackState:
    @pytest.fixture
    def briefs(self, monkeypatch: pytest.MonkeyPatch) -> AsyncMock:
        listing = AsyncMock(return_value=[])
        monkeypatch.setattr(briefing_repository, "list_recent", listing)
        return listing

    @pytest.fixture
    def last_active(self, monkeypatch: pytest.MonkeyPatch) -> AsyncMock:
        read = AsyncMock(return_value=None)
        monkeypatch.setattr(wind_down, "latest_activity_since", read)
        return read

    async def test_the_last_ten_daily_briefs_are_read_and_each_ack_checked_for_this_user(
        self, briefs: AsyncMock, last_active: AsyncMock
    ) -> None:
        briefs.return_value = [_brief(BriefingMood.CLEAR)]

        await compute_winback_state(_WINBACK_USER)

        briefs.assert_awaited_once_with(USER_ID, limit=10, kind=BriefingKind.DAILY)
        assert last_active.await_args.args[0] == USER_ID

    async def test_no_briefs_is_not_winback(
        self, briefs: AsyncMock, last_active: AsyncMock
    ) -> None:
        state = await compute_winback_state(_WINBACK_USER)

        assert (state.unacknowledged, state.is_winback, state.should_back_off) == (0, False, False)
        assert state.last_was_winback is False
        last_active.assert_not_awaited()

    async def test_ignored_briefs_up_to_the_threshold_flip_to_winback(
        self, briefs: AsyncMock, last_active: AsyncMock
    ) -> None:
        briefs.return_value = [
            _sent_days_ago(_brief(BriefingMood.CLEAR), d) for d in range(WINBACK_THRESHOLD)
        ]

        state = await compute_winback_state(_WINBACK_USER)

        assert state.unacknowledged == WINBACK_THRESHOLD
        assert state.is_winback
        assert not state.should_back_off

    async def test_activity_after_a_brief_acknowledges_it(
        self, briefs: AsyncMock, last_active: AsyncMock
    ) -> None:
        briefs.return_value = [
            _sent_days_ago(_brief(BriefingMood.CLEAR), d) for d in range(WINBACK_THRESHOLD + 1)
        ]
        # Active between the second-newest brief and the newest one.
        last_active.return_value = datetime(2026, 10, 11, 9, tzinfo=UTC)

        state = await compute_winback_state(_WINBACK_USER)

        assert state.unacknowledged == 1
        assert not state.is_winback

    async def test_last_activity_is_read_once_from_the_oldest_brief(
        self, briefs: AsyncMock, last_active: AsyncMock
    ) -> None:
        briefs.return_value = [_sent_days_ago(_brief(BriefingMood.CLEAR), d) for d in range(5)]

        await compute_winback_state(_WINBACK_USER)

        last_active.assert_awaited_once_with(USER_ID, datetime(2026, 10, 8, 8, tzinfo=UTC))

    async def test_a_sent_winback_that_is_still_ignored_backs_off(
        self, briefs: AsyncMock, last_active: AsyncMock
    ) -> None:
        briefs.return_value = [_brief(BriefingMood.WINBACK)] + [
            _sent_days_ago(_brief(BriefingMood.CLEAR), d + 1) for d in range(WINBACK_THRESHOLD)
        ]

        state = await compute_winback_state(_WINBACK_USER)

        assert state.should_back_off

    async def test_naive_created_at_is_read_as_utc(
        self, briefs: AsyncMock, last_active: AsyncMock
    ) -> None:
        brief = _brief(BriefingMood.CLEAR)
        brief.created_at = datetime(2026, 10, 12, 8)
        briefs.return_value = [brief]
        last_active.return_value = datetime(2026, 10, 12, 8, tzinfo=UTC)

        state = await compute_winback_state(_WINBACK_USER)

        assert last_active.await_args.args[1] == datetime(2026, 10, 12, 8, tzinfo=UTC)
        assert state.unacknowledged == 0
