"""Unit tests for the true-cost backfill's aggregation.

The script's whole point is the arithmetic: which calls count as verified, what
happens to the ones OpenRouter can no longer price, and how that lands as a
per-user-day coverage number. That fold is pure, so it is pinned here without a
Loki or an OpenRouter in sight. The Mongo write it feeds is a repository method
proven a tier down.
"""

from datetime import datetime
import json
from typing import cast

import httpx
import pytest
from scripts.backfill_true_cost import (
    UNVERIFIED,
    GenerationRecord,
    LlmCall,
    _parse_event,
    aggregate_true_cost,
)

from scripts import backfill_true_cost as backfill


def _call(
    generation_id: str | None,
    logged_cost: float,
    *,
    user_id: str = "u1",
    day: str = "2026-08-01",
    background: bool = False,
) -> LlmCall:
    return LlmCall(
        user_id=user_id,
        day=day,
        background=background,
        logged_cost=logged_cost,
        generation_id=generation_id,
    )


def _record(cost: float, provider: str = "Fireworks") -> GenerationRecord:
    return GenerationRecord(total_cost=cost, provider_name=provider)


def test_verified_call_uses_the_real_charge_not_the_table_price() -> None:
    rows = aggregate_true_cost([_call("g1", 0.10)], {"g1": _record(0.25)})

    assert len(rows) == 1
    assert rows[0].logged_cost == 0.10
    assert rows[0].cost_actual == 0.25
    assert rows[0].coverage == 1.0
    assert rows[0].provider_mix == {"Fireworks": 0.25}


def test_background_calls_land_in_the_aux_totals() -> None:
    rows = aggregate_true_cost(
        [_call("g1", 0.10), _call("g2", 0.20, background=True)],
        {"g1": _record(0.25), "g2": _record(0.50)},
    )

    assert rows[0].logged_cost == 0.10
    assert rows[0].cost_actual == 0.25
    assert rows[0].logged_aux_cost == 0.20
    assert rows[0].aux_cost_actual == 0.50


def test_call_without_a_generation_id_keeps_its_logged_cost_and_loses_coverage() -> None:
    rows = aggregate_true_cost([_call(None, 0.40)], {})

    assert rows[0].cost_actual == 0.40
    assert rows[0].coverage == 0.0
    assert rows[0].provider_mix == {UNVERIFIED: 0.40}


def test_dropped_generation_is_unverifiable_not_an_error() -> None:
    """OpenRouter 404s ids it has aged out — cached as ``None``, same treatment
    as an id it was never asked about."""
    cached_404 = aggregate_true_cost([_call("gone", 0.40)], {"gone": None})
    never_asked = aggregate_true_cost([_call("gone", 0.40)], {})

    assert cached_404[0].cost_actual == never_asked[0].cost_actual == 0.40
    assert cached_404[0].coverage == never_asked[0].coverage == 0.0


def test_coverage_is_weighted_by_dollars_not_by_call_count() -> None:
    """Nine cheap unverifiable calls must not bury one verified call that is
    where the money actually went."""
    calls = [_call("big", 9.0), *[_call(None, 0.1) for _ in range(10)]]

    rows = aggregate_true_cost(calls, {"big": _record(12.0)})

    assert rows[0].coverage == pytest.approx(0.9)  # 9.00 verified of 10.00 logged
    assert rows[0].cost_actual == pytest.approx(13.0)  # 12.00 real + 1.00 from the table


def test_provider_mix_sums_to_the_true_total_including_the_unverified_bucket() -> None:
    calls = [_call("g1", 0.1), _call("g2", 0.1), _call(None, 0.5, background=True)]
    generations = {"g1": _record(0.3, "Together"), "g2": _record(0.2, "Fireworks")}

    row = aggregate_true_cost(calls, generations)[0]

    assert row.provider_mix == {"Together": 0.3, "Fireworks": 0.2, UNVERIFIED: 0.5}
    assert sum(row.provider_mix.values()) == row.cost_actual + row.aux_cost_actual


def test_rows_are_split_per_user_and_per_day() -> None:
    calls = [
        _call("g1", 0.1, user_id="u1", day="2026-08-01"),
        _call("g2", 0.1, user_id="u1", day="2026-08-02"),
        _call("g3", 0.1, user_id="u2", day="2026-08-01"),
    ]

    rows = aggregate_true_cost(calls, {k: _record(1.0) for k in ("g1", "g2", "g3")})

    assert [(r.user_id, r.date) for r in rows] == [
        ("u1", "2026-08-01"),
        ("u1", "2026-08-02"),
        ("u2", "2026-08-01"),
    ]


def test_zero_dollar_day_reports_full_coverage_instead_of_dividing_by_zero() -> None:
    rows = aggregate_true_cost([_call(None, 0.0)], {})

    assert rows[0].coverage == 1.0


def test_gap_is_the_dollars_the_price_table_missed() -> None:
    row = aggregate_true_cost(
        [_call("g1", 0.10), _call("g2", 0.20, background=True)],
        {"g1": _record(0.25), "g2": _record(0.50)},
    )[0]

    assert row.gap == pytest.approx(0.45)


def test_parse_event_reads_a_wide_event_line() -> None:
    line = (
        '{"llm_event": "llm_call", "time": "2026-08-01T12:30:00Z", "user_id": "u1", '
        '"background": true, "cost_usd": 0.125, "generation_id": "gen-abc"}'
    )

    call = _parse_event(line)

    assert call == LlmCall(
        user_id="u1",
        day="2026-08-01",
        background=True,
        logged_cost=0.125,
        generation_id="gen-abc",
    )


def test_parse_event_rejects_lines_that_are_not_llm_calls() -> None:
    assert _parse_event("not json at all") is None
    assert _parse_event('{"llm_event": "budget_stop", "user_id": "u1", "time": "x"}') is None
    assert _parse_event('{"llm_event": "llm_call", "time": "2026-08-01T00:00:00Z"}') is None


def test_parse_event_treats_a_missing_generation_id_as_unverifiable() -> None:
    line = '{"llm_event": "llm_call", "time": "2026-08-01T00:00:00Z", "user_id": "u1"}'

    call = _parse_event(line)

    assert call is not None
    assert call.generation_id is None
    assert call.logged_cost == 0.0


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
    monkeypatch.setattr(backfill, "_LOKI_PAGE", 3)
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

    calls = await backfill._fetch_day(cast(httpx.AsyncClient, client), "http://loki", _DAY)

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
    monkeypatch.setattr(backfill, "_LOKI_PAGE", 3)
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

    calls = await backfill._fetch_day(cast(httpx.AsyncClient, client), "http://loki", _DAY)

    assert [c.generation_id for c in calls] == ["g0", "g1", "g2", "g3", "later"]
    assert client.starts == [_DAY_START_NANOS, base + 2, base + 5]


async def test_more_lines_than_a_page_at_one_nanosecond_refuses_the_day(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Loki cannot page inside one timestamp. A group larger than the page can
    never be drained, so the day is refused rather than written short."""
    monkeypatch.setattr(backfill, "_LOKI_PAGE", 3)
    base = _DAY_START_NANOS + 60_000_000_000
    client = _FakeLokiClient([(base, _event_line(f"g{i}")) for i in range(4)])

    with pytest.raises(backfill.UndrainableTimestampError, match=_DAY):
        await backfill._fetch_day(cast(httpx.AsyncClient, client), "http://loki", _DAY)


async def test_exhausting_the_page_budget_refuses_the_day(monkeypatch: pytest.MonkeyPatch) -> None:
    """Forty full pages is a prefix of the day, not the day. Writing it would
    understate cost_actual, coverage and the provider mix, so the day is refused."""
    monkeypatch.setattr(backfill, "_LOKI_PAGE", 2)
    monkeypatch.setattr(backfill, "_LOKI_MAX_PAGES", 3)
    base = _DAY_START_NANOS + 60_000_000_000
    # 3 pages x 2 lines fill the budget; the seventh line is still unread.
    client = _FakeLokiClient([(base + i, _event_line(f"g{i}")) for i in range(7)])

    with pytest.raises(backfill.PageBudgetExhaustedError, match=_DAY):
        await backfill._fetch_day(cast(httpx.AsyncClient, client), "http://loki", _DAY)


async def test_identical_lines_at_the_boundary_are_each_kept_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Two identical lines can share a nanosecond — the same model call logged
    twice is indistinguishable by text. The next page must skip only as many as
    were already taken, not every line that looks like them."""
    monkeypatch.setattr(backfill, "_LOKI_PAGE", 2)
    base = _DAY_START_NANOS + 60_000_000_000
    twin = _event_line("twin")
    client = _FakeLokiClient([(base, twin), (base, twin), (base + 5, _event_line("later"))])

    calls = await backfill._fetch_day(cast(httpx.AsyncClient, client), "http://loki", _DAY)

    assert [c.generation_id for c in calls] == ["twin", "twin", "later"]


async def test_paging_stops_once_a_page_comes_back_short(monkeypatch: pytest.MonkeyPatch) -> None:
    """A page under the limit is the last one — asking again costs a round trip
    and, on the old whole-second cursor, re-read events it had already folded."""
    monkeypatch.setattr(backfill, "_LOKI_PAGE", 3)
    client = _FakeLokiClient([(_DAY_START_NANOS, _event_line("g1"))])

    calls = await backfill._fetch_day(cast(httpx.AsyncClient, client), "http://loki", _DAY)

    assert [c.generation_id for c in calls] == ["g1"]
    assert len(client.starts) == 1
