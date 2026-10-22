"""What the writer is told about each signal: its memory as of before today, and the move."""

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock

import pytest

from app.models.scout_models import (
    RememberedSignal,
    Signal,
    SignalImportance,
    SignalMemoryDocument,
)
from app.services.briefing.scouts import memory
from app.services.briefing.scouts.facts import signals_block
from app.services.briefing.scouts.memory import remember

USER_ID = "64f1c0ffee0000000000abcd"
NOW = datetime(2026, 10, 22, 6, 0, tzinfo=UTC)


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
        monkeypatch.setattr(memory.signal_memory_repository, name, mock)
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
        store["record_seen"].assert_awaited_once_with(USER_ID, [moved, same, new], NOW)


class TestTheFactsBlock:
    def test_signals_are_grouped_per_app_important_first_with_their_memory(self) -> None:
        urgent = _signal("9").model_copy(update={"importance": SignalImportance.HIGH})
        remembered = [
            RememberedSignal(signal=_signal("1", app="Jira")),
            RememberedSignal(
                signal=_signal("2"),
                memory=_memory(
                    "2",
                    first_seen=NOW - timedelta(days=4),
                    times_shown=3,
                    last_shown=NOW - timedelta(days=1),
                ),
            ),
            RememberedSignal(
                signal=urgent,
                memory=_memory("9", first_seen=NOW - timedelta(days=1)),
                previous_state="Backlog",
            ),
        ]

        assert signals_block(remembered, NOW).splitlines() == [
            "[ACROSS THEIR APPS] 3 item(s) in 2 app(s)",
            "[Jira] 1 item(s)",
            "- other | issue: Issue 1 | state: Todo | new today",
            "[Linear] 2 item(s)",
            "- important | issue: Issue 9 | state: Todo | first seen yesterday, never mentioned,"
            " moved from Backlog to Todo",
            "- other | issue: Issue 2 | state: Todo | first seen 4 days ago, mentioned 3 time(s),"
            " last yesterday",
        ]

    def test_no_signals_is_no_block(self) -> None:
        assert signals_block([], NOW) == ""
