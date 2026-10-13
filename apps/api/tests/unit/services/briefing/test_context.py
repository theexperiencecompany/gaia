"""What the briefing run sees: clocks, goals, tracked work, look-back, winback.

Repositories and the memory engine are the faked seams; every assertion is on
the block or state the run would hand the agent.
"""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock
from zoneinfo import ZoneInfo

import pytest

from app.constants.briefing import WINBACK_THRESHOLD
from app.constants.todos import BLOCKING_LABEL, FAILED_LABEL, GAIA_TRACKED_LABEL
from app.models.briefing_models import BriefingModel, BriefingPayload
from app.models.todo_models import TodoDocument
from app.services.briefing import context

_USER = "user-1"


def _todo(todo_id: str, title: str, *labels: str) -> TodoDocument:
    return TodoDocument(id=todo_id, user_id=_USER, title=title, labels=list(labels))


def _brief(mood: str, *, opened: bool = False, items: list[str] | None = None) -> BriefingModel:
    return BriefingModel(
        user_id=_USER,
        date="2026-10-12",
        payload=BriefingPayload(
            kicker="K",
            date="2026-10-12",
            headline="H",
            lede="L",
            mood=mood,
            caption="C",
            sections=[
                {"numeral": "I", "title": "T", "items": [{"text": t} for t in (items or [])]}
            ],
        ),
        opened_at=datetime.now(UTC) if opened else None,
        created_at=datetime(2026, 10, 12, 8, tzinfo=UTC),
    )


class TestClock:
    def test_missing_timezone_is_utc(self) -> None:
        assert context.resolve_clock(None).tz == ZoneInfo("UTC")

    def test_unknown_timezone_fails_loud(self) -> None:
        with pytest.raises(Exception, match="Nowhere/City"):
            context.resolve_clock("Nowhere/City")

    def test_day_start_is_local_midnight_in_utc(self) -> None:
        tz = ZoneInfo("Asia/Kolkata")
        clock = context.UserClock(
            tz=tz,
            now_local=datetime(2026, 10, 13, 9, 30, tzinfo=tz),
            date_str="2026-10-13",
            day_of_year=286,
        )

        assert context.day_start_utc(clock) == datetime(2026, 10, 12, 18, 30, tzinfo=UTC)
        assert context.day_start_utc(clock, days_ago=1) == datetime(
            2026, 10, 11, 18, 30, tzinfo=UTC
        )


class TestGoalBlock:
    @pytest.fixture
    def recall(self, monkeypatch: pytest.MonkeyPatch) -> AsyncMock:
        recall = AsyncMock(return_value=SimpleNamespace(memories=[]))
        monkeypatch.setattr(context, "memory_engine", SimpleNamespace(recall=recall))
        monkeypatch.setattr(context, "entry_to_note", str)
        return recall

    @pytest.mark.parametrize("focus", ["", "  ", "nothing", "N/A", "idk"])
    async def test_junk_focus_and_no_memories_is_no_goal(
        self, recall: AsyncMock, focus: str
    ) -> None:
        block, has_goal = await context.format_goal_block(_USER, {"onboarding": {"focus": focus}})

        assert has_goal is False
        assert "No stated goal" in block

    async def test_stated_focus_and_recalled_memories_are_both_shown(
        self, recall: AsyncMock
    ) -> None:
        recall.return_value = SimpleNamespace(
            memories=["Raising a seed round", "Raising a seed round"]
        )

        block, has_goal = await context.format_goal_block(
            _USER, {"onboarding": {"focus": "Close 10 customers"}}
        )

        assert has_goal is True
        assert block.splitlines() == ["Stated goal: Close 10 customers", "- Raising a seed round"]

    async def test_recall_failure_still_briefs_from_the_stated_goal(
        self, recall: AsyncMock
    ) -> None:
        recall.side_effect = RuntimeError("vector store down")

        block, has_goal = await context.format_goal_block(
            _USER, {"onboarding": {"focus": "Ship v2"}}
        )

        assert (block, has_goal) == ("Stated goal: Ship v2", True)


class TestTrackedWork:
    async def test_open_todos_are_sorted_by_state_and_only_gaia_completions_count(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            context.todo_repository,
            "list_completed_since",
            AsyncMock(
                return_value=[
                    _todo("c1", "Research", GAIA_TRACKED_LABEL),
                    _todo("c2", "Groceries"),
                ]
            ),
        )
        monkeypatch.setattr(
            context.todo_repository,
            "list_active_tracked",
            AsyncMock(
                return_value=[
                    _todo("f1", "Sync", GAIA_TRACKED_LABEL, FAILED_LABEL, BLOCKING_LABEL),
                    _todo("b1", "Reply", GAIA_TRACKED_LABEL, BLOCKING_LABEL),
                    _todo("r1", "Plan", GAIA_TRACKED_LABEL),
                ]
            ),
        )

        work = await context.gather_tracked_work(_USER, datetime.now(UTC))

        assert [d.id for d in work.completed] == ["c1"]
        assert [d.id for d in work.failed] == ["f1"]
        assert [d.id for d in work.blocked] == ["b1"]
        assert [d.id for d in work.running] == ["r1"]
        assert not work.is_empty

    async def test_open_todo_summary_counts_all_and_names_five(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        docs = [_todo(f"t{i}", f"Todo {i}") for i in range(7)]
        monkeypatch.setattr(
            context.todo_repository, "list_open_user_todos", AsyncMock(return_value=docs)
        )

        count, titles = await context.user_open_todo_summary(_USER)

        assert count == 7
        assert titles == [f"Todo {i}" for i in range(5)]


class TestLookback:
    async def test_first_look_back_with_nothing_done(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(
            context.todo_repository, "list_completed_since", AsyncMock(return_value=[])
        )
        monkeypatch.setattr(
            context.workflow_executions_repository, "list_since", AsyncMock(return_value=[])
        )

        block = await context.format_lookback_block(_USER, None, datetime.now(UTC))

        assert "No prior briefing" in block
        assert "Nothing was completed" in block
        assert "Background workflow runs" not in block

    async def test_yesterdays_plan_is_compared_to_what_finished(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            context.todo_repository,
            "list_completed_since",
            AsyncMock(return_value=[_todo("c1", "Deck", GAIA_TRACKED_LABEL), _todo("c2", "Gym")]),
        )
        monkeypatch.setattr(
            context.workflow_executions_repository,
            "list_since",
            AsyncMock(return_value=[SimpleNamespace(status="success", summary="3 drafts")]),
        )

        block = await context.format_lookback_block(
            _USER, _brief("clear", items=["Finish the deck"]).payload, datetime.now(UTC)
        )

        assert "- Finish the deck" in block
        assert "- GAIA finished: Deck" in block
        assert "- You finished: Gym" in block
        assert "- Workflow [success]: 3 drafts" in block


class TestWinback:
    @pytest.fixture
    def briefs(self, monkeypatch: pytest.MonkeyPatch) -> AsyncMock:
        listing = AsyncMock(return_value=[])
        monkeypatch.setattr(context.briefing_repository, "list_recent", listing)
        return listing

    @pytest.fixture
    def active_since(self, monkeypatch: pytest.MonkeyPatch) -> AsyncMock:
        signal = AsyncMock(return_value=False)
        monkeypatch.setattr(context.dormancy, "reactivation_signal_since", signal)
        return signal

    async def test_no_briefs_is_not_winback(
        self, briefs: AsyncMock, active_since: AsyncMock
    ) -> None:
        state = await context.compute_winback_state(_USER)

        assert (state.unacknowledged, state.is_winback, state.should_back_off) == (0, False, False)

    async def test_ignored_briefs_up_to_the_threshold_flip_to_winback(
        self, briefs: AsyncMock, active_since: AsyncMock
    ) -> None:
        briefs.return_value = [_brief("clear") for _ in range(WINBACK_THRESHOLD)] + [
            _brief("clear", opened=True)
        ]

        state = await context.compute_winback_state(_USER)

        assert state.unacknowledged == WINBACK_THRESHOLD
        assert state.is_winback
        assert not state.should_back_off

    async def test_activity_after_a_brief_acknowledges_it(
        self, briefs: AsyncMock, active_since: AsyncMock
    ) -> None:
        briefs.return_value = [_brief("clear") for _ in range(WINBACK_THRESHOLD + 1)]
        active_since.side_effect = [False, True]

        state = await context.compute_winback_state(_USER)

        assert state.unacknowledged == 1
        assert not state.is_winback

    async def test_a_sent_winback_that_is_still_ignored_backs_off(
        self, briefs: AsyncMock, active_since: AsyncMock
    ) -> None:
        briefs.return_value = [_brief("winback")] + [
            _brief("clear") for _ in range(WINBACK_THRESHOLD)
        ]

        state = await context.compute_winback_state(_USER)

        assert state.should_back_off

    async def test_naive_created_at_is_read_as_utc(
        self, briefs: AsyncMock, active_since: AsyncMock
    ) -> None:
        brief = _brief("clear")
        brief.created_at = datetime(2026, 10, 12, 8)
        briefs.return_value = [brief]

        await context.compute_winback_state(_USER)

        assert active_since.await_args.args[1] == datetime(2026, 10, 12, 8, tzinfo=UTC)
