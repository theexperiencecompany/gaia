"""Unit tests for the true-cost backfill's aggregation.

The script's whole point is the arithmetic: which calls count as verified, what
happens to the ones OpenRouter can no longer price, and how that lands as a
per-user-day coverage number. That fold is pure, so it is pinned here without a
Loki or an OpenRouter in sight. The Mongo write it feeds is a repository method
proven a tier down.
"""

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


def test_a_sticky_flip_replay_is_background_even_without_the_background_flag() -> None:
    # The events already in Loki predate the fix on this branch: the old code
    # booked the discarded replay as the user's foreground spend, so they carry
    # sticky_flip_discarded=true and no background flag. Keying off `background`
    # alone would replay exactly the mistake this branch removes into
    # cost_actual, splitting the 30-day history by the old rule and everything
    # after the deploy by the new one.
    line = (
        '{"llm_event": "llm_call", "time": "2026-08-01T12:30:00Z", "user_id": "u1", '
        '"sticky_flip_discarded": true, "cost_usd": 0.125, "generation_id": "gen-abc"}'
    )

    call = _parse_event(line)

    assert call is not None
    assert call.background is True


def test_a_sticky_flip_replay_lands_in_the_aux_totals_not_the_users_costs() -> None:
    # The end that matters: a pre-deploy replay's dollars must be COGS, not
    # spend attributed to the user who never received its answer.
    replay = _parse_event(
        '{"llm_event": "llm_call", "time": "2026-08-01T12:30:00Z", "user_id": "u1", '
        '"sticky_flip_discarded": true, "cost_usd": 0.20, "generation_id": "g2"}'
    )
    foreground = _parse_event(
        '{"llm_event": "llm_call", "time": "2026-08-01T12:00:00Z", "user_id": "u1", '
        '"cost_usd": 0.10, "generation_id": "g1"}'
    )
    assert replay is not None and foreground is not None

    (row,) = aggregate_true_cost(
        [foreground, replay],
        {
            "g1": GenerationRecord(total_cost=0.15, provider_name="alpha"),
            "g2": GenerationRecord(total_cost=0.30, provider_name="alpha"),
        },
    )

    assert row.cost_actual == 0.15
    assert row.aux_cost_actual == 0.30
    assert row.logged_cost == 0.10
    assert row.logged_aux_cost == 0.20


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


@pytest.mark.parametrize("poison", ["NaN", "Infinity", "-Infinity", "-0.5"])
def test_a_cost_that_is_not_a_real_number_drops_the_line(poison: str) -> None:
    """json.loads accepts NaN and Infinity. One such line summed into a day would
    make every figure that day feeds NaN — including what --apply writes."""
    line = (
        '{"llm_event": "llm_call", "user_id": "u1", "time": "2026-08-25T10:00:00Z", '
        f'"cost_usd": {poison}, "generation_id": "g1"}}'
    )
    assert backfill._parse_event(line) is None


def test_a_missing_cost_is_zero_not_a_dropped_line() -> None:
    """No cost_usd at all is an unpriced call, not a corrupt one: it still counts
    toward coverage and tokens."""
    line = '{"llm_event": "llm_call", "user_id": "u1", "time": "2026-08-25T10:00:00Z"}'
    call = backfill._parse_event(line)
    assert call is not None
    assert call.logged_cost == 0.0
