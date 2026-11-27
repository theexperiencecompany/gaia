"""What the writer is told about each signal: its memory as of before today, and the move."""

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock
from zoneinfo import ZoneInfo

import pytest
from tests.factories import make_user_id

from app.db.repositories.signal_memory import signal_memory_repository
from app.models.scout_models import (
    PeopleRole,
    RememberedSignal,
    Signal,
    SignalImportance,
    SignalMemoryDocument,
)
from app.services.briefing.candidates.app_signals import app_signal_candidates
from app.services.briefing.clock import UserClock
from app.services.briefing.fact_pool.render import item_line
from app.services.briefing.scouts.facts import memory_note
from app.services.briefing.scouts.memory import remember

USER_ID = make_user_id()
NOW = datetime(2026, 10, 22, 6, 0, tzinfo=UTC)
CLOCK = UserClock(tz=ZoneInfo("UTC"), now_local=NOW, date_str="2026-10-22", day_of_year=295)


def _signal(external_id: str, *, app: str = "Linear", state: str | None = "Todo") -> Signal:
    return Signal(
        integration_id=app.lower(),
        app=app,
        external_id=external_id,
        kind="issue",
        title=f"Issue {external_id}",
        state=state,
    )


def _memory(
    external_id: str,
    *,
    first_seen: datetime = NOW,
    times_shown: int = 0,
    last_shown: datetime | None = None,
    last_state: str | None = None,
) -> SignalMemoryDocument:
    return SignalMemoryDocument(
        user_id=USER_ID,
        integration_id="linear",
        external_id=external_id,
        first_seen=first_seen,
        times_shown=times_shown,
        last_shown=last_shown,
        last_state=last_state,
    )


@pytest.fixture
def store(monkeypatch: pytest.MonkeyPatch) -> dict[str, AsyncMock]:
    seams = {"find_for": AsyncMock(return_value=[]), "record_seen": AsyncMock()}
    for name, mock in seams.items():
        monkeypatch.setattr(signal_memory_repository, name, mock)
    return seams


class TestRemember:
    async def test_each_signal_carries_its_memory_from_before_today(
        self, store: dict[str, AsyncMock]
    ) -> None:
        moved, same, new = _signal("1", state="Done"), _signal("2"), _signal("3")
        store["find_for"].return_value = [
            _memory("1", last_state="Todo", times_shown=2),
            _memory("2", last_state="Todo"),
        ]

        remembered = await remember(USER_ID, [moved, same, new], NOW)

        assert [(r.signal.external_id, r.previous_state) for r in remembered] == [
            ("1", "Todo"),
            ("2", None),
            ("3", None),
        ]
        assert remembered[0].memory is not None and remembered[0].memory.times_shown == 2
        assert remembered[2].memory is None
        store["find_for"].assert_awaited_once_with(USER_ID, [moved, same, new])
        store["record_seen"].assert_awaited_once_with(USER_ID, [moved, same, new], NOW)


def _line(remembered: RememberedSignal, clock: UserClock = CLOCK) -> str:
    """Say one signal as both the composition and the voice read it."""
    [candidate] = app_signal_candidates([remembered], clock, clock.day_start())
    return item_line(1, candidate, clock)


_READ_ONLY = "GAIA can only read Linear: no offer on it"


class TestASignalsLine:
    def test_a_signal_says_its_kind_state_and_memory(self) -> None:
        remembered = RememberedSignal(
            signal=_signal("9").model_copy(update={"importance": SignalImportance.HIGH}),
            memory=_memory("9", first_seen=NOW - timedelta(days=1)),
            previous_state="Backlog",
        )

        assert _line(remembered) == (
            "1. [Linear] found by its scout, important: Issue 9 | issue | Linear shows it as Todo"
            " | first seen yesterday, never mentioned, moved from Backlog to Todo | " + _READ_ONLY
        )

    @pytest.mark.regression
    def test_a_date_says_what_it_means_beside_due(self) -> None:
        """Regression: "due Tue Nov 24" on a lead was its next follow-up, and read as a reply's age."""
        signal = _signal("6").model_copy(
            update={
                "due_at": datetime(2026, 10, 24, 17, 0, tzinfo=UTC),
                "due_label": "next follow-up scheduled",
            }
        )

        assert "| due Sat Oct 24 (next follow-up scheduled) |" in _line(
            RememberedSignal(signal=signal)
        )

    def test_every_detail_a_signal_carries_is_on_its_line(self) -> None:
        signal = _signal("5").model_copy(
            update={
                "due_at": datetime(2026, 10, 24, 17, 0, tzinfo=UTC),
                "people": ["Priya", "Sam"],
                "url": "https://linear.app/acme/issue/ENG-5",
                "why": "blocks the release",
            }
        )
        remembered = RememberedSignal(
            signal=signal, memory=_memory("5", times_shown=0, last_shown=NOW)
        )

        assert _line(remembered) == (
            "1. [Linear] found by its scout: Issue 5 | issue | Linear shows it as Todo"
            " | why: blocks the release"
            " | first seen today, never mentioned | due Sat Oct 24"
            " | names Priya, Sam (the app does not say their part in it) | linkable | " + _READ_ONLY
        )

    def test_the_people_an_app_names_are_said_in_the_part_it_gives_them(self) -> None:
        signal = _signal("7").model_copy(
            update={"people": ["Priya", "Sam"], "people_role": PeopleRole.ASSIGNEE}
        )

        assert "| assignee: Priya, Sam |" in _line(RememberedSignal(signal=signal))

    def test_the_person_who_is_the_user_is_marked_so_the_voice_says_you(self) -> None:
        signal = _signal("7").model_copy(
            update={
                "people": ["Aryan", "Sam"],
                "people_role": PeopleRole.REVIEWER,
                "people_you": ["Aryan"],
            }
        )

        assert "| reviewer: Aryan (this is the user: say you, never their name), Sam |" in _line(
            RememberedSignal(signal=signal)
        )

    def test_a_sighting_stamped_after_now_still_reads_as_today(self) -> None:
        later = NOW + timedelta(hours=2)
        remembered = RememberedSignal(
            signal=_signal("6"),
            memory=_memory("6", first_seen=later, times_shown=1, last_shown=later),
        )

        assert "| first seen today, mentioned 1 time(s), last today |" in _line(remembered)


class TestDaysAreTheUsers:
    def test_ago_and_due_dates_are_counted_on_the_users_own_days(self) -> None:
        """Regression: a Kolkata user's item created at 1:30 AM local read as created yesterday."""
        kolkata = ZoneInfo("Asia/Kolkata")
        clock = UserClock(
            tz=kolkata, now_local=NOW.astimezone(kolkata), date_str="2026-10-22", day_of_year=295
        )
        signal = _signal("11").model_copy(
            update={
                "created_at": datetime(2026, 10, 21, 20, 0, tzinfo=UTC),
                "due_at": datetime(2026, 10, 22, 19, 0, tzinfo=UTC),
            }
        )

        line = _line(RememberedSignal(signal=signal), clock)

        assert "| due Fri Oct 23 |" in line
        assert "| new: created today |" in line


class TestWhatIsNew:
    """A first sighting is new only when the app dates the item's creation inside the last day."""

    def test_an_old_item_seen_for_the_first_time_is_not_new(self) -> None:
        signal = _signal("110").model_copy(
            update={
                "created_at": datetime(2025, 6, 18, 9, 0, tzinfo=UTC),
                "updated_at": datetime(2025, 6, 18, 9, 30, tzinfo=UTC),
            }
        )

        note = memory_note(RememberedSignal(signal=signal), CLOCK)

        assert note == (
            "first seen today, created 2025-06-18 (491 days ago), last updated 491 days ago"
        )

    def test_an_item_the_app_dates_only_by_its_last_update_says_that_update(self) -> None:
        """Two GitHub threads updated this week read as undated, so stale issues outranked them."""
        signal = _signal("27213240598").model_copy(update={"updated_at": NOW - timedelta(days=3)})

        assert memory_note(RememberedSignal(signal=signal), CLOCK) == (
            "first seen today, last updated 3 days ago"
        )

    def test_an_item_created_within_the_day_is_new(self) -> None:
        signal = _signal("7").model_copy(update={"created_at": NOW - timedelta(hours=20)})

        assert memory_note(RememberedSignal(signal=signal), CLOCK) == "new: created yesterday"

    def test_an_item_the_app_does_not_date_is_never_called_new(self) -> None:
        assert (
            memory_note(RememberedSignal(signal=_signal("8")), CLOCK)
            == "first seen today, created date unknown"
        )

    def test_an_item_created_a_full_day_ago_is_not_new(self) -> None:
        signal = _signal("9").model_copy(update={"created_at": NOW - timedelta(days=1)})

        assert memory_note(RememberedSignal(signal=signal), CLOCK) == (
            "first seen today, created 2026-10-21 (yesterday)"
        )

    def test_an_item_seen_before_but_never_mentioned_keeps_its_created_date(self) -> None:
        """Replay: an issue created a week before its first brief was voiced as a new one."""
        signal = _signal("12").model_copy(
            update={"created_at": datetime(2026, 10, 14, 4, 30, tzinfo=UTC)}
        )
        remembered = RememberedSignal(
            signal=signal, memory=_memory("12", first_seen=NOW - timedelta(days=1))
        )

        assert memory_note(remembered, CLOCK) == (
            "first seen yesterday, never mentioned, created 2026-10-14 (8 days ago)"
        )
