"""Reading a day of ``llm_call`` events out of Loki, exactly once.

Loki caps a response and offers no cursor, so a busy day is read in pages that
must re-open AT the last nanosecond seen and skip exactly the lines already
taken from it. Every test here is about that boundary: one nanosecond read
twice inflates the busiest days, and one read short drops them. The machinery is
shared by both backfills, so a regression here is wrong twice over.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import json
from typing import cast

import httpx
import pytest

from scripts import _loki

pytestmark = pytest.mark.asyncio


@dataclass(frozen=True)
class _Row:
    """The minimum a caller's parsed row needs for these tests: an identity that
    survives paging, so a dropped or doubled line is visible in the result."""

    generation_id: str


def _event_line(generation_id: str) -> str:
    return json.dumps({"llm_event": "llm_call", "generation_id": generation_id})


def _parse(line: str) -> _Row | None:
    payload = json.loads(line)
    if payload.get("llm_event") != "llm_call":
        return None
    return _Row(generation_id=str(payload["generation_id"]))


class _FakeLokiClient:
    """A faithful-enough Loki: one ordered event stream, served ``limit`` at a
    time from an INCLUSIVE ``start``, which is the behaviour the cursor has to
    be right about."""

    def __init__(self, events: list[tuple[int, str]]) -> None:
        self._events = events
        self.starts: list[int] = []

    async def get(
        self, url: str, *, params: dict[str, object], headers: dict[str, str]
    ) -> httpx.Response:
        start = int(cast(int, params["start"]))
        end = int(cast(int, params["end"]))
        limit = int(cast(int, params["limit"]))
        self.starts.append(start)
        window = [(str(at), line) for at, line in self._events if start <= at < end][:limit]
        return httpx.Response(
            200,
            json={"data": {"result": [{"values": window}] if window else []}},
            request=httpx.Request("GET", url),
        )


def _event_line(generation_id: str) -> str:
    return json.dumps(
        {
            "llm_event": "llm_call",
            "time": "2026-08-01T00:00:00Z",
            "user_id": "u1",
            "cost_usd": 1.0,
            "generation_id": generation_id,
        }
    )


#: The day the fixtures below sit in, as Loki would timestamp its first instant.
_DAY = "2026-08-01"
_DAY_START_NANOS = int(datetime.fromisoformat(f"{_DAY}T00:00:00+00:00").timestamp() * 1_000_000_000)


async def test_paging_does_not_re_read_the_second_it_stopped_inside(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A full page whose last events share one wall-clock second must not be
    served again by the next page.

    Loki's ``start`` is inclusive and its timestamps are nanoseconds. A cursor
    that keeps only whole seconds restarts the next page at the TOP of the
    second the previous page ended in, so every event in that second is folded
    twice and ``cost_actual`` comes out inflated for exactly the busiest
    user-days (a production day clears the 5,000-event page size).
    """
    monkeypatch.setattr(_loki, "LOKI_PAGE", 3)
    base = _DAY_START_NANOS
    # The page boundary falls INSIDE one second: every event here carries the
    # same whole second, so a second-resolution cursor cannot move past them.
    client = _FakeLokiClient(
        [
            (base, _event_line("g1")),
            (base + 400_000_000, _event_line("g2")),
            (base + 500_000_000, _event_line("g3")),
            (base + 900_000_000, _event_line("g4")),
        ]
    )

    calls = await _loki.fetch_day(cast(httpx.AsyncClient, client), "http://loki", _DAY, _parse)

    # Each event exactly once — a re-read would fold g1..g3 twice and double
    # their dollars into cost_actual.
    assert [c.generation_id for c in calls] == ["g1", "g2", "g3", "g4"]
    # The second request resumes one nanosecond past the last event returned,
    # not at the start of its second.
    # The second request re-opens AT the last nanosecond returned (inclusive) and skips
    # the line it already took there, not at the start of its second.
    assert client.starts == [base, base + 500_000_000]


async def test_paging_drains_every_line_that_shares_the_boundary_nanosecond(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Several lines can carry the same nanosecond. When a page ends inside such
    a group, the next page must re-open AT that nanosecond and skip only the
    lines already taken — advancing by one nanosecond would drop the rest of the
    group, and their dollars with it."""
    monkeypatch.setattr(_loki, "LOKI_PAGE", 3)
    base = _DAY_START_NANOS + 3_600_000_000_000
    client = _FakeLokiClient(
        [
            (base, _event_line("g0")),
            (base + 1, _event_line("g1")),
            (base + 2, _event_line("g2")),
            (base + 2, _event_line("g3")),
            (base + 5, _event_line("later")),
        ]
    )

    calls = await _loki.fetch_day(cast(httpx.AsyncClient, client), "http://loki", _DAY, _parse)

    assert [c.generation_id for c in calls] == ["g0", "g1", "g2", "g3", "later"]
    assert client.starts == [_DAY_START_NANOS, base + 2, base + 5]


async def test_more_lines_than_a_page_at_one_nanosecond_refuses_the_day(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Loki cannot page inside one timestamp. A group larger than the page can
    never be drained, so the day is refused rather than written short."""
    monkeypatch.setattr(_loki, "LOKI_PAGE", 3)
    base = _DAY_START_NANOS + 60_000_000_000
    client = _FakeLokiClient([(base, _event_line(f"g{i}")) for i in range(4)])

    with pytest.raises(_loki.UndrainableTimestampError, match=_DAY):
        await _loki.fetch_day(cast(httpx.AsyncClient, client), "http://loki", _DAY, _parse)


async def test_exhausting_the_page_budget_refuses_the_day(monkeypatch: pytest.MonkeyPatch) -> None:
    """Forty full pages is a prefix of the day, not the day. Writing it would
    understate cost_actual, coverage and the provider mix, so the day is refused."""
    monkeypatch.setattr(_loki, "LOKI_PAGE", 2)
    monkeypatch.setattr(_loki, "LOKI_MAX_PAGES", 3)
    base = _DAY_START_NANOS + 60_000_000_000
    # 3 pages x 2 lines fill the budget; the seventh line is still unread.
    client = _FakeLokiClient([(base + i, _event_line(f"g{i}")) for i in range(7)])

    with pytest.raises(_loki.PageBudgetExhaustedError, match=_DAY):
        await _loki.fetch_day(cast(httpx.AsyncClient, client), "http://loki", _DAY, _parse)


async def test_identical_lines_at_the_boundary_are_each_kept_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Two identical lines can share a nanosecond — the same model call logged
    twice is indistinguishable by text. The next page must skip only as many as
    were already taken, not every line that looks like them."""
    monkeypatch.setattr(_loki, "LOKI_PAGE", 2)
    base = _DAY_START_NANOS + 60_000_000_000
    twin = _event_line("twin")
    client = _FakeLokiClient([(base, twin), (base, twin), (base + 5, _event_line("later"))])

    calls = await _loki.fetch_day(cast(httpx.AsyncClient, client), "http://loki", _DAY, _parse)

    assert [c.generation_id for c in calls] == ["twin", "twin", "later"]


async def test_paging_stops_once_a_page_comes_back_short(monkeypatch: pytest.MonkeyPatch) -> None:
    """A page under the limit is the last one — asking again costs a round trip
    and, on the old whole-second cursor, re-read events it had already folded."""
    monkeypatch.setattr(_loki, "LOKI_PAGE", 3)
    client = _FakeLokiClient([(_DAY_START_NANOS, _event_line("g1"))])

    calls = await _loki.fetch_day(cast(httpx.AsyncClient, client), "http://loki", _DAY, _parse)

    assert [c.generation_id for c in calls] == ["g1"]
    assert len(client.starts) == 1
