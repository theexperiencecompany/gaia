"""Rebuilding the ``llm_calls`` ledger from log history.

The backfill writes rows that look exactly like live ones and are summed
alongside them, so its transform is billing-adjacent: a doubled row inflates
COGS, a dropped one hides it, and a re-run that duplicates history is worse than
not running at all. Every test here pins one of those.
"""

from __future__ import annotations

from datetime import UTC, datetime
import json

import pytest
from scripts._openrouter import GenerationRecord
from scripts.backfill_llm_calls import (
    EARLIEST_DAY,
    Anomalies,
    LedgerEvent,
    build_document,
    normalise_model,
    parse_event,
    price_event,
    render,
    select_events,
    summarise,
    wanted_days,
)


def _line(**fields: object) -> str:
    payload: dict[str, object] = {
        "llm_event": "llm_call",
        "time": "2026-08-20T10:00:00Z",
        "user_id": "u1",
        "agent_name": "comms_agent",
        "model": "deepseek/deepseek-v4-flash",
        "input_tokens": 100,
        "output_tokens": 20,
        "cost_usd": 0.004,
    }
    payload.update(fields)
    return json.dumps(payload)


def _event(**fields: object) -> LedgerEvent:
    parsed = parse_event(_line(**fields))
    assert parsed is not None
    return parsed


class TestParsing:
    def test_a_wide_event_becomes_a_ledger_event(self) -> None:
        event = _event(generation_id="gen-1", cached_tokens=40, reasoning_tokens=7)

        assert event.user_id == "u1"
        assert event.agent_name == "comms_agent"
        assert event.generation_id == "gen-1"
        assert (event.input_tokens, event.output_tokens) == (100, 20)
        assert (event.cached_tokens, event.reasoning_tokens) == (40, 7)
        assert event.created_at == datetime(2026, 8, 20, 10, 0, tzinfo=UTC)

    def test_lines_that_are_not_llm_calls_are_dropped(self) -> None:
        assert parse_event('{"llm_event": "other"}') is None
        assert parse_event("not json at all") is None

    @pytest.mark.parametrize("poison", ["NaN", "Infinity", "-Infinity", "-0.5"])
    def test_a_cost_that_is_not_a_real_number_drops_the_line(self, poison: str) -> None:
        """``json.loads`` accepts NaN and Infinity, and either one poisons every
        sum it reaches — including the total this script reports."""
        line = _line().replace('"cost_usd": 0.004', f'"cost_usd": {poison}')

        assert parse_event(line) is None

    def test_a_sticky_flip_replay_is_background_even_without_the_flag(self) -> None:
        """Replay events predate the ``background`` field, so the older marker is
        the only signal those rows carry — and they were never charged."""
        event = _event(sticky_flip_discarded=True)

        assert event.background is True
        assert build_document(event, None).charge_to_budget is False


class TestModelNormalisation:
    def test_a_model_id_doubled_with_no_separator_collapses(self) -> None:
        """The shape that actually occurs. Verified on live Loki, 2026-08-14:
        the alias was concatenated onto itself with NO separator, so a
        slash-based rule never fires — and 9,209 rows fell through to the
        unknown-model branch, preserving dead pre-Aug-24 table prices."""
        doubled = "deepseek/deepseek-v4-flash-0731deepseek/deepseek-v4-flash-0731"

        assert normalise_model(doubled) == "deepseek/deepseek-v4-flash-0731"

    def test_a_doubled_id_is_priced_from_the_table_not_kept_at_its_logged_cost(self) -> None:
        """The consequence of the miss: an id the table cannot match falls to
        "unknown model, keep logged cost", which silently preserves whatever the
        table said back then. Normalising first is what makes the unknown-model
        branch mean what it says."""
        doubled = "deepseek/deepseek-v4-flash-0731deepseek/deepseek-v4-flash-0731"
        event = _event(model=doubled, cost_usd=0.99)

        assert event.model == "deepseek/deepseek-v4-flash-0731"
        assert price_event(event, None).source == "table"

    def test_a_doubled_model_id_collapses_to_one(self) -> None:
        """A lane that applied its alias on top of an already-aliased id logged
        the vendor/name twice. Left alone it is a second row in every group-by
        and matches no pricing entry."""
        assert normalise_model("deepseek/v4/deepseek/v4") == "deepseek/v4"

    def test_a_normal_model_id_is_left_alone(self) -> None:
        assert normalise_model("deepseek/deepseek-v4-flash") == "deepseek/deepseek-v4-flash"
        assert normalise_model("gemini-3-pro") == "gemini-3-pro"

    def test_a_repeated_looking_id_that_is_not_doubled_is_left_alone(self) -> None:
        assert normalise_model("a/b/c") == "a/b/c"


class TestSelection:
    def test_an_echo_with_neither_tokens_nor_cost_is_not_a_row(self) -> None:
        """A metering hook that fired on a call the provider never billed. Kept,
        it inflates the row count with rows that answer no question."""
        echo = _event(input_tokens=0, output_tokens=0, cached_tokens=0, cost_usd=0)

        assert select_events([echo]) == []

    def test_the_same_call_logged_twice_becomes_one_row(self) -> None:
        """Exact duplicates exist in the history; counted twice they double that
        call's cost in every total the ledger feeds."""
        event = _event(generation_id="gen-1")

        assert len(select_events([event, event])) == 1

    def test_two_genuinely_different_calls_both_survive(self) -> None:
        first = _event(generation_id="gen-1")
        second = _event(generation_id="gen-2")

        assert len(select_events([first, second])) == 2


class TestPricing:
    def test_what_openrouter_billed_beats_everything_else(self) -> None:
        event = _event(cost_usd=0.004, cost_source="provider")
        record = GenerationRecord(total_cost=0.009, provider_name="Baidu")

        priced = price_event(event, record)

        assert priced.cost == 0.009
        assert priced.source == "generation"

    def test_a_provider_priced_event_is_trusted_when_the_generation_is_gone(self) -> None:
        """OpenRouter drops old generations. The figure captured live is the next
        best thing and is still a real provider price."""
        priced = price_event(_event(cost_usd=0.004, cost_source="provider"), None)

        assert priced.cost == 0.004
        assert priced.source == "provider"

    def test_a_table_priced_event_is_recomputed_at_todays_rates(self) -> None:
        """The rate in the table when the call ran is gone; today's is the best
        estimate available, and recomputing keeps the whole month consistent."""
        priced = price_event(_event(cost_source="table"), None)

        assert priced.source == "table"
        assert priced.cost >= 0.0

    def test_an_unknown_model_keeps_its_logged_cost(self) -> None:
        """A missing rate is not a free call. The logged number is kept and
        counted separately so the fallback's share stays visible."""
        priced = price_event(_event(model="a-model-nobody-priced", cost_usd=0.0031), None)

        assert priced.cost == 0.0031
        assert priced.source == "logged"


class TestDocument:
    def test_the_row_is_marked_backfilled_and_keyed_for_re_runs(self) -> None:
        doc = build_document(_event(generation_id="gen-1"), None)

        assert doc.backfilled is True
        assert doc.backfill_key

    def test_the_key_is_the_same_every_run_for_the_same_event(self) -> None:
        """This is what makes ``--apply`` re-runnable: the unique index can only
        absorb a repeat if the key is derived, not generated."""
        line = _line(generation_id="gen-1")
        first, second = parse_event(line), parse_event(line)

        assert first is not None and second is not None
        assert first.backfill_key == second.backfill_key

    def test_two_different_calls_never_share_a_key(self) -> None:
        assert _event(generation_id="gen-1").backfill_key != (
            _event(generation_id="gen-2").backfill_key
        )

    def test_calls_without_a_generation_id_are_keyed_by_their_own_shape(self) -> None:
        """Most background calls have no generation id. Falling back to a
        constant would collapse them all into one row."""
        assert _event(input_tokens=100).backfill_key != _event(input_tokens=101).backfill_key

    def test_the_upstream_is_recorded_when_the_generation_named_one(self) -> None:
        record = GenerationRecord(total_cost=0.009, provider_name="StreamLake")

        assert build_document(_event(generation_id="g"), record).provider == "StreamLake"

    def test_an_executor_thread_still_resolves_to_its_conversation(self) -> None:
        conv = "8f2a1c4e-0b3d-4a71-9c62-5d8e1f0a7b34"
        doc = build_document(_event(thread_id=f"executor_{conv}"), None)

        assert doc.conversation_id == conv
        assert doc.lane_thread == f"executor_{conv}"

    def test_what_the_log_never_carried_is_left_unset(self) -> None:
        """The wide event never logged latency, the ARQ job or the workflow
        execution. Inventing them would make backfilled rows look more precise
        than they are — which is why the rows are marked."""
        doc = build_document(_event(), None)

        assert doc.duration_ms is None
        assert doc.job_id is None
        assert doc.workflow_execution_id is None


class TestWindow:
    def test_the_window_never_reaches_before_the_events_carried_costs(self) -> None:
        """Older events have no cost fields, so rows built from them would be
        fiction rather than recovered history."""
        assert all(day >= EARLIEST_DAY for day in wanted_days(365))

    def test_a_short_window_is_still_bounded_by_today(self) -> None:
        days = wanted_days(3)

        assert days == sorted(days)
        assert len(days) <= 3


class TestDryRunReport:
    """The dry run is the only thing anyone reads before deciding to --apply, so
    its per-day raw -> docs -> $ table has to reconcile: the docs column must be
    what would actually be written, and the dollars what would actually be
    booked."""

    def test_the_table_reports_what_would_be_written(self, capsys: pytest.CaptureFixture) -> None:
        events = select_events(
            [
                _event(generation_id="gen-1", cost_source="provider", cost_usd=0.004),
                _event(generation_id="gen-2", cost_source="provider", cost_usd=0.006),
                # An echo and an exact duplicate: counted as raw, never as docs.
                _event(input_tokens=0, output_tokens=0, cached_tokens=0, cost_usd=0),
                _event(generation_id="gen-1", cost_source="provider", cost_usd=0.004),
            ]
        )
        docs = [build_document(event, None) for event in events]
        sources: dict[str, int] = {"provider": 2}

        render([summarise("2026-08-20", raw=4, docs=docs, sources=sources)])

        printed = capsys.readouterr().out
        assert "2026-08-20" in printed
        # 4 raw lines in, 2 real calls out, a cent of spend between them.
        assert "       4       2      0.0100" in printed
        assert "total" in printed

    def test_the_total_line_sums_every_day(self, capsys: pytest.CaptureFixture) -> None:
        docs = [build_document(_event(cost_source="provider", cost_usd=0.01), None)]

        render(
            [
                summarise("2026-08-20", raw=1, docs=docs, sources={"provider": 1}),
                summarise("2026-08-21", raw=1, docs=docs, sources={"provider": 1}),
            ]
        )

        assert "0.0200" in capsys.readouterr().out


class TestAnomalyReport:
    """What the run discarded, and why.

    An aggregate "2,784 dropped" tells an operator nothing about whether the
    run is trustworthy. Each of these buckets is a different judgement the
    script made on their behalf — and the doubled-id count in particular is the
    one that, left invisible, hid 9,209 mis-priced rows behind a plausible
    total.
    """

    def test_every_judgement_the_run_made_is_counted(self) -> None:
        events = [
            _event(generation_id="gen-1"),
            _event(generation_id="gen-1"),  # exact duplicate
            _event(input_tokens=0, output_tokens=0, cached_tokens=0, cost_usd=0),  # echo
            _event(generation_id="gen-2", background=True),  # background lane
            _event(generation_id="gen-3", model="a-model-nobody-priced"),  # unknown model
            _event(
                generation_id="gen-4",
                model="deepseek/deepseek-v4-flash-0731deepseek/deepseek-v4-flash-0731",
            ),  # doubled id
        ]

        anomalies = Anomalies()
        kept = select_events(events, anomalies)
        for event in kept:
            anomalies.observe(event, price_event(event, None))

        assert anomalies.echoes_skipped == 1
        assert anomalies.duplicates_skipped == 1
        assert anomalies.doubled_ids_normalised == 1
        assert anomalies.background_rows == 1
        assert anomalies.unknown_model_rows == 1

    def test_generation_lookups_are_split_into_resolved_and_missing(self) -> None:
        """A 404 is OpenRouter having dropped an old generation — unverifiable,
        not an error. The two must be countable apart or a run that resolved
        nothing looks the same as one that resolved everything."""
        anomalies = Anomalies()

        anomalies.count_lookups({"gen-1": GenerationRecord(total_cost=0.01), "gen-2": None})

        assert anomalies.generations_resolved == 1
        assert anomalies.generations_missing == 1

    def test_the_report_names_every_bucket(self, capsys: pytest.CaptureFixture) -> None:
        anomalies = Anomalies()
        anomalies.echoes_skipped = 3

        anomalies.render()

        printed = capsys.readouterr().out
        for label in (
            "zero-token echoes skipped",
            "doubled model ids normalised",
            "exact duplicates skipped",
            "background rows (never charged)",
            "generation lookups resolved",
            "generation lookups missing",
            "unknown-model rows",
        ):
            assert label in printed
        assert "3" in printed
