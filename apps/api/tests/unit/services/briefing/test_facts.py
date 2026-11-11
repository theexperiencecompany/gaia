"""The facts block the model voices, and the values its slots render, built from the chosen sections."""

from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from app.constants.briefing import BriefAction, BriefOutcome
from app.models.brief_candidate_models import BriefCandidate, CandidateKind
from app.models.briefing_models import BriefingEvent, BriefingItem, BriefingSection
from app.models.scout_models import Signal
from app.services.briefing.artifacts import ArtifactFact
from app.services.briefing.context import UserClock
from app.services.briefing.facts import TODAY, WEEK_AHEAD, CalendarSpan, FactSources, build_facts
from app.services.briefing.sections import Chosen
from app.services.briefing.slots import BriefFact, CountSlot

NOW = datetime(2026, 10, 14, 1, 35, tzinfo=UTC)
TZ = ZoneInfo("Asia/Kolkata")
CLOCK = UserClock(tz=TZ, now_local=NOW.astimezone(TZ), date_str="2026-10-14", day_of_year=287)


def _candidate(title: str, **fields: object) -> BriefCandidate:
    defaults: dict[str, object] = {
        "source": "gaia",
        "app": "GAIA",
        "kind": CandidateKind.NEEDS_YOU,
        "state": "you",
        "title": title,
    }
    return BriefCandidate.model_validate({**defaults, **fields})


def _section(items: list[BriefingItem]) -> BriefingSection:
    return BriefingSection(numeral="I", title="Needs you", items=items)


def _sources(
    *,
    artifacts: dict[str, ArtifactFact] | None = None,
    calendar: list[BriefingEvent] | None = None,
    event_ids: list[int] | None = None,
    span: CalendarSpan = TODAY,
    todos_note: str | None = None,
    open_todos: int = 0,
) -> FactSources:
    return FactSources(
        artifacts=artifacts or {},
        calendar=calendar or [],
        event_ids=event_ids or [],
        span=span,
        todos_note=todos_note,
        open_todos=open_todos,
    )


def _ask(text: str, **fields: object) -> BriefingItem:
    return BriefingItem.model_validate(
        {"text": text, "action": BriefAction.REPLY, "kind": "you", **fields}
    )


class TestTheFactLine:
    def test_a_line_names_the_app_the_due_time_the_detail_and_how_many_requests_it_stands_for(
        self,
    ) -> None:
        item = _ask("Send the invoice", app="Gmail", count=2)
        candidate = _candidate("Send the invoice", due_at=NOW, detail="to Acme")
        chosen = Chosen(sections=[_section([item])], picked=[[(1, candidate)]])

        facts = build_facts(chosen, _sources(), CLOCK)

        assert facts.block.splitlines() == [
            "[COUNTS] needs_you: 1",
            "[Needs you]",
            "- fact 1 | Waiting on you: Send the invoice | in Gmail | time: today"
            " | detail: to Acme | 2 requests, one item",
            "The user's calendar has nothing today (or no calendar is connected).",
        ]
        assert facts.values.facts[1] == BriefFact(title="Send the invoice", time="today", count=2)

    def test_a_due_date_on_another_day_names_its_weekday_and_date(self) -> None:
        item = _ask("Pay the invoice")
        candidate = _candidate("Pay the invoice", due_at=NOW + timedelta(days=2))
        chosen = Chosen(sections=[_section([item])], picked=[[(1, candidate)]])

        facts = build_facts(chosen, _sources(), CLOCK)

        assert facts.values.facts[1].time == "Fri Oct 16"
        assert "| time: Fri Oct 16" in facts.block

    def test_a_line_without_an_app_time_or_detail_is_only_its_state_and_title(self) -> None:
        item = BriefingItem(text="Investor update", outcome=BriefOutcome.FINISHED, kind="lookback")
        candidate = _candidate("Investor update", kind=CandidateKind.GAIA_DID, state="lookback")
        chosen = Chosen(sections=[_section([item])], picked=[[(4, candidate)]])

        facts = build_facts(chosen, _sources(), CLOCK)

        assert "- fact 4 | Done: Investor update\n" in f"{facts.block}\n"
        assert facts.values.facts[4] == BriefFact(title="Investor update", time=None, count=1)

    def test_an_app_signal_is_a_fact_but_not_a_line_and_the_items_after_it_still_are(self) -> None:
        signal = Signal(
            integration_id="linear",
            app="Linear",
            external_id="ENG-42",
            kind="issue assigned to you",
            title="Fix the login redirect",
        )
        items = [_ask("Fix the login redirect", app="Linear"), _ask("Reply to Dan")]
        picked = [
            (1, _candidate("Fix the login redirect", signal=signal)),
            (2, _candidate("Reply to Dan", detail="about the lease")),
        ]
        chosen = Chosen(sections=[_section(items)], picked=[picked])

        facts = build_facts(chosen, _sources(), CLOCK)

        assert facts.values.facts[1].title == "Fix the login redirect"
        assert "fact 1" not in facts.block
        assert "- fact 2 | Waiting on you: Reply to Dan | detail: about the lease" in facts.block


class TestTheDeliverablesAndLinks:
    def test_an_item_with_an_artifact_reads_with_its_summary_and_size_and_links_it(self) -> None:
        item = BriefingItem(
            text="Deck", outcome=BriefOutcome.FINISHED, kind="lookback", todo_id="t1"
        )
        candidate = _candidate("Deck", kind=CandidateKind.GAIA_DID, todo_id="t1")
        chosen = Chosen(sections=[_section([item])], picked=[[(1, candidate)]])
        artifacts = {"t1": ArtifactFact(snippet="Ten slides", chars=10, action=False)}

        facts = build_facts(chosen, _sources(artifacts=artifacts), CLOCK)

        assert (
            "- fact 1 | Done: Deck | summary: Ten slides | artifact holds ~10 chars | linkable"
            in facts.block.splitlines()
        )
        assert facts.sections == chosen.sections
        assert (facts.deliverables, facts.addresses) == ({1: "t1"}, {})

    def test_an_empty_artifact_has_nothing_to_open_so_the_apps_own_link_serves(self) -> None:
        item = _ask("Sync failed", todo_id="t2")
        candidate = _candidate("Sync failed", todo_id="t2", url="https://app.example/sync")
        chosen = Chosen(sections=[_section([item])], picked=[[(1, candidate)]])
        artifacts = {"t2": ArtifactFact(snippet="", chars=0, action=True)}

        facts = build_facts(chosen, _sources(artifacts=artifacts), CLOCK)

        assert (
            "- fact 1 | Waiting on you: Sync failed | artifact holds ~0 chars | waiting on you"
            " | linkable" in facts.block.splitlines()
        )
        assert (facts.deliverables, facts.addresses) == ({}, {1: "https://app.example/sync"})

    def test_an_item_with_no_todo_never_opens_a_deliverable(self) -> None:
        item = _ask("Reply to Dan")
        candidate = _candidate("Reply to Dan")
        chosen = Chosen(sections=[_section([item])], picked=[[(1, candidate)]])

        facts = build_facts(chosen, _sources(), CLOCK)

        assert (facts.deliverables, facts.addresses) == ({}, {})
        assert "linkable" not in facts.block


class TestTheCountsAndMustMention:
    def test_every_kind_of_item_and_event_is_counted_in_its_own_slot(self) -> None:
        items = [
            _ask("Reply to Dan"),
            BriefingItem(text="Deck", outcome=BriefOutcome.FINISHED, kind="lookback"),
            BriefingItem(text="Report", outcome=BriefOutcome.FINISHED, kind="lookback"),
            BriefingItem(text="Digest", outcome=BriefOutcome.STARTED, kind="gaia"),
            BriefingItem(text="Crawl", outcome=BriefOutcome.STARTED, kind="gaia"),
            BriefingItem(text="Scrape", outcome=BriefOutcome.STARTED, kind="gaia"),
            BriefingItem(text="Payout", outcome=BriefOutcome.LANDED, kind="note"),
        ]
        picked = [(i, _candidate(item.text)) for i, item in enumerate(items, start=1)]
        events = [
            BriefingEvent(date="2026-10-14", start="11:00", title="Sequoia"),
            BriefingEvent(date="2026-10-14", title="Diwali"),
        ]
        sources = _sources(calendar=events, event_ids=[8, 9])

        facts = build_facts(Chosen(sections=[_section(items)], picked=[picked]), sources, CLOCK)

        assert facts.block.splitlines()[0] == (
            "[COUNTS] needs_you: 1 · done: 2 · in_progress: 3 · while_away: 1 · events: 2"
        )
        assert facts.values.counts == {
            CountSlot.NEEDS_YOU: 1,
            CountSlot.DONE: 2,
            CountSlot.IN_PROGRESS: 3,
            CountSlot.WHILE_AWAY: 1,
            CountSlot.EVENTS: 2,
        }
        assert [facts.values.facts[i].title for i in (8, 9)] == ["Sequoia", "Diwali"]

    def test_open_todos_count_only_when_the_brief_read_them(self) -> None:
        chosen = Chosen(sections=[], picked=[])

        without = build_facts(chosen, _sources(), CLOCK)
        with_todos = build_facts(chosen, _sources(open_todos=3), CLOCK)

        assert CountSlot.OPEN_TODOS not in without.values.counts
        assert "[COUNTS]" not in without.block
        assert with_todos.values.counts == {CountSlot.OPEN_TODOS: 3}
        assert with_todos.block.splitlines()[0] == "[COUNTS] open_todos: 3"

    def test_what_waits_on_the_user_and_every_event_must_be_mentioned(self) -> None:
        items = [
            _ask("Reply to Dan"),
            BriefingItem(text="Sync failed", action=BriefAction.RETRY, kind="failed"),
            BriefingItem(text="Payout landed", outcome=BriefOutcome.LANDED, kind="note"),
        ]
        picked = [(1, _candidate("a")), (2, _candidate("b")), (3, _candidate("c"))]
        chosen = Chosen(sections=[_section(items)], picked=[picked])
        sources = _sources(
            calendar=[BriefingEvent(date="2026-10-14", start="11:00", title="Sequoia")],
            event_ids=[4],
        )

        facts = build_facts(chosen, sources, CLOCK)

        assert facts.must_mention == frozenset({1, 2, 4})

    def test_with_nothing_chosen_the_block_says_so_and_does_not_invent_work(self) -> None:
        facts = build_facts(
            Chosen(sections=[], picked=[]), _sources(todos_note="Todos: none."), CLOCK
        )

        assert facts.block.splitlines() == [
            "GAIA has no tracked work and no background work ran. Do not claim anything "
            "ran, finished, or is pending beyond what is stated here.",
            "Todos: none.",
            "The user's calendar has nothing today (or no calendar is connected).",
        ]


class TestTheCalendarNote:
    def test_each_event_is_a_fact_with_its_time_and_another_days_names_its_weekday(self) -> None:
        events = [
            BriefingEvent(date="2026-10-14", start="11:00", title="Sequoia"),
            BriefingEvent(date="2026-10-14", title="Diwali"),
            BriefingEvent(date="2026-10-16", start="15:00", title="Pitch to Accel"),
        ]
        sources = _sources(calendar=events, event_ids=[7, 8, 9], span=WEEK_AHEAD)

        facts = build_facts(Chosen(sections=[], picked=[]), sources, CLOCK)

        assert facts.block.splitlines()[-4:] == [
            "The week ahead:",
            "- fact 7 | 11:00 AM: Sequoia",
            "- fact 8 | all day: Diwali",
            "- fact 9 | Fri 3:00 PM: Pitch to Accel",
        ]
        assert [facts.values.facts[i].time for i in (7, 8, 9)] == [
            "11:00 AM",
            None,
            "Fri 3:00 PM",
        ]


class TestAnInconsistentSelectionFailsLoudly:
    def test_a_section_without_its_picked_candidates(self) -> None:
        chosen = Chosen(sections=[_section([_ask("Reply to Dan")])], picked=[])

        with pytest.raises(ValueError, match="zip"):
            build_facts(chosen, _sources(), CLOCK)

    def test_an_item_without_its_candidate(self) -> None:
        chosen = Chosen(sections=[_section([_ask("Reply to Dan")])], picked=[[]])

        with pytest.raises(ValueError, match="zip"):
            build_facts(chosen, _sources(), CLOCK)

    def test_an_event_without_its_pool_id(self) -> None:
        sources = _sources(
            calendar=[BriefingEvent(date="2026-10-14", title="Sequoia")], event_ids=[]
        )

        with pytest.raises(ValueError, match="zip"):
            build_facts(Chosen(sections=[], picked=[]), sources, CLOCK)
