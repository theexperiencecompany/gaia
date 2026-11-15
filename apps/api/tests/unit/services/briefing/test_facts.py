"""The facts the voice is shown: one line per item and event, the figures its prose may quote and its slots."""

from datetime import UTC, datetime
from zoneinfo import ZoneInfo

import pytest

from app.constants.briefing import (
    CALENDAR_UNAVAILABLE,
    NO_CALENDAR_CONNECTED,
    BriefAction,
    BriefOutcome,
)
from app.models.brief_candidate_models import BriefCandidate
from app.models.brief_composition_models import BriefBlock, ChartBlock, ChartKind, SectionBlock
from app.models.brief_pool_models import (
    DataSeries,
    GoalOrigin,
    GoalState,
    SeriesPoint,
    SeriesShape,
)
from app.models.briefing_models import BriefingEvent, BriefingItem, BriefingSection
from app.models.scout_models import Signal, SignalMemoryDocument
from app.services.briefing.artifacts import ArtifactFact
from app.services.briefing.context import CalendarGap, CalendarUnread, UserClock
from app.services.briefing.facts import (
    TODAY,
    WEEK_AHEAD,
    BriefSpan,
    FactSources,
    WeekRecap,
    build_facts,
    user_todos_note,
)
from app.services.briefing.sections import Chosen
from app.services.briefing.slots import BriefFact, CountSlot, SeriesField

pytestmark = pytest.mark.unit

_TZ = ZoneInfo("Asia/Kolkata")
_NOW = datetime(2026, 11, 11, 2, 30, tzinfo=UTC)
_CLOCK = UserClock(tz=_TZ, now_local=_NOW.astimezone(_TZ), date_str="2026-11-11", day_of_year=315)
_SERIES = DataSeries(
    id="gmail_sorted",
    label="Mail sorted",
    unit="emails",
    source="gmail",
    app="Gmail",
    shape=SeriesShape.CATEGORICAL,
    points=[SeriesPoint(x="Junk", y=22), SeriesPoint(x="Needs a reply", y=9)],
)


def _chosen(*picked: tuple[BriefingItem, BriefCandidate]) -> Chosen:
    return Chosen(
        sections=[BriefingSection(numeral="I", title="Waiting", items=[i for i, _ in picked])],
        picked=[[(n, c) for n, (_, c) in enumerate(picked, start=1)]],
    )


def _sources(
    *,
    artifacts: dict[str, ArtifactFact] | None = None,
    open_todos: int = 0,
    calendar: list[BriefingEvent] | CalendarUnread | None = None,
    event_ids: list[int] | None = None,
    span: BriefSpan = TODAY,
    blocks: list[BriefBlock] | None = None,
) -> FactSources:
    return FactSources(
        artifacts=artifacts or {},
        open_todos=open_todos,
        calendar=[] if calendar is None else calendar,
        event_ids=event_ids or [],
        span=span,
        todos_note=None,
        blocks=blocks or [],
    )


class TestTheFactLines:
    def test_an_item_line_says_its_app_when_it_is_due_its_detail_and_how_many_asked(self) -> None:
        item = BriefingItem(
            text="Reply to Maya", kind="you", app="Gmail", count=3, action=BriefAction.REPLY
        )
        candidate = BriefCandidate(
            source="gmail",
            app="Gmail",
            state="you",
            title="Re: term sheet",
            detail="needs sign-off",
            due_at=datetime(2026, 11, 13, 9, 0, tzinfo=UTC),
            count=3,
        )

        facts = build_facts(_chosen((item, candidate)), _sources(open_todos=4), _CLOCK)

        assert facts.values.counts == {CountSlot.NEEDS_YOU: 1, CountSlot.OPEN_TODOS: 4}
        assert facts.values.facts[1] == BriefFact(
            title="Reply to Maya",
            time="Fri Nov 13",
            count=3,
            kind="you",
            words="Re: term sheet needs sign-off",
        )
        assert facts.block.splitlines()[:3] == [
            "[COUNTS] [[count:needs_you]] (1) · [[count:open_todos]] (4)",
            "[Waiting]",
            "- fact 1 | Waiting on you: Reply to Maya | in Gmail | time: [[fact:1.time]] "
            "(Fri Nov 13) | detail: needs sign-off | [[fact:1.count]] (3) todos on this one subject",
        ]

    def test_the_users_own_todo_has_no_deliverable_and_reads_as_a_plain_line(self) -> None:
        """Replay of 2026-11-14: placing an own todo raised KeyError on its todo id."""
        item = BriefingItem(
            text="Sort the garage", kind="you", action=BriefAction.ATTEND, todo_id="own-1"
        )
        candidate = BriefCandidate(
            source="gaia", app="GAIA", state="you", title="Sort the garage", todo_id="own-1"
        )

        facts = build_facts(_chosen((item, candidate)), _sources(), _CLOCK)

        assert "- fact 1 | Waiting on you: Sort the garage\n" in f"{facts.block}\n"
        assert facts.deliverables == {}


class TestWhatProseMayQuote:
    def test_the_figures_in_every_items_own_words_may_be_quoted(self) -> None:
        first = (
            BriefingItem(text="Q3 plan", kind="you", todo_id="t1", action=BriefAction.REPLY),
            BriefCandidate(
                source="gaia", app="GAIA", state="you", title="Q3 plan", detail="due by 5pm"
            ),
        )
        second = (
            BriefingItem(text="Q4 plan", kind="you", action=BriefAction.REPLY),
            BriefCandidate(source="gaia", app="GAIA", state="you", title="Q4 plan"),
        )
        art = ArtifactFact(snippet="42 slides", chars=900, action=False)

        facts = build_facts(_chosen(first, second), _sources(artifacts={"t1": art}), _CLOCK)

        assert facts.values.quoted == {"Q3", "5pm", "42", "Q4"}

    def test_a_signals_own_reason_state_and_text_may_be_quoted_too(self) -> None:
        signal = Signal(
            integration_id="linear",
            app="Linear",
            external_id="ENG-12",
            kind="issue",
            title="Fix login",
            why="due in 2 days",
            state="P1 open",
            text="repro on build 88",
        )
        item = BriefingItem(text="Fix login", kind="you", action=BriefAction.REPLY)
        candidate = BriefCandidate(
            source="linear", app="Linear", state="you", title="Fix login 4", signal=signal
        )

        facts = build_facts(_chosen((item, candidate)), _sources(), _CLOCK)

        assert facts.values.quoted == {"4", "2", "P1", "88"}


class TestTheCalendarAndTheCharts:
    def test_a_charts_figures_are_what_the_series_slots_render(self) -> None:
        chart = ChartBlock(chart=ChartKind.BAR, title="Mail", takeaway="Junk.", series=[_SERIES])

        facts = build_facts(Chosen(sections=[], picked=[]), _sources(blocks=[chart]), _CLOCK)

        assert facts.values.series["gmail_sorted"][SeriesField.TOTAL] == "31"

    def test_events_and_their_ids_must_pair_up(self) -> None:
        event = BriefingEvent(date="2026-11-11", start="15:00", title="Board call")

        with pytest.raises(ValueError, match="zip"):
            build_facts(
                Chosen(sections=[], picked=[]),
                _sources(calendar=[event], event_ids=[]),
                _CLOCK,
            )

    def test_the_calendar_note_lists_each_event_by_its_fact_and_time(self) -> None:
        events = [
            BriefingEvent(date="2026-11-11", start="15:00", title="Board call"),
            BriefingEvent(date="2026-11-11", start=None, title="Offsite"),
        ]
        span = BriefSpan(heading="This week", empty="Nothing.", no_items="None.")

        facts = build_facts(
            Chosen(sections=[], picked=[]),
            _sources(calendar=events, event_ids=[7, 8], span=span),
            _CLOCK,
        )

        assert facts.block.splitlines()[-3:] == [
            "This week:",
            "- fact 7 | [[fact:7.time]] (3:00 PM): Board call",
            "- fact 8 | all day: Offsite",
        ]

    def test_with_no_calendar_connected_the_note_says_so_not_that_it_is_empty(self) -> None:
        unconnected = _sources(calendar=CalendarUnread(CalendarGap.NOT_CONNECTED))

        facts = build_facts(Chosen(sections=[], picked=[]), unconnected, _CLOCK)

        assert facts.block.splitlines()[-1] == NO_CALENDAR_CONNECTED
        assert TODAY.empty not in facts.block

    def test_a_calendar_that_did_not_answer_is_never_an_empty_day(self) -> None:
        """Regression: a calendar read that failed told the voice the day was free."""
        unread = _sources(calendar=CalendarUnread(CalendarGap.UNAVAILABLE))

        facts = build_facts(Chosen(sections=[], picked=[]), unread, _CLOCK)

        assert facts.block.splitlines()[-1] == CALENDAR_UNAVAILABLE
        assert TODAY.empty not in facts.block


class TestEachCountClaimsOnlyItsOwn:
    def test_only_held_results_are_while_away_and_an_event_or_backlog_never_waits(self) -> None:
        """Regression: every placed note was counted as come in while away, a calendar lead too."""
        held = BriefCandidate(
            source="gaia", app="GAIA", state="note", title="Digest: 3 papers", held_id="h1"
        )
        signal = BriefCandidate(source="linear", app="Linear", state="you", title="ENG-12 merged")
        event = BriefCandidate(
            source="googlecalendar",
            app="Google Calendar",
            state="note",
            title="Board",
            is_event=True,
        )
        backlog = BriefCandidate(
            source="gaia", app="GAIA", state="you", title="Plan Q1", backlog=True
        )
        waiting = BriefCandidate(source="gmail", app="Gmail", state="you", title="Reply to Maya")
        placed = [
            (BriefingItem(text="Board", kind="you", action=BriefAction.ATTEND), event),
            (BriefingItem(text="Digest", kind="note", outcome=BriefOutcome.FINISHED), held),
            (BriefingItem(text="ENG-12", kind="note", outcome=BriefOutcome.CHANGED), signal),
            (BriefingItem(text="Plan Q1", kind="you", action=BriefAction.ATTEND), backlog),
            (BriefingItem(text="Maya", kind="you", action=BriefAction.REPLY), waiting),
        ]

        facts = build_facts(_chosen(*placed), _sources(), _CLOCK)

        assert facts.values.counts == {CountSlot.NEEDS_YOU: 1, CountSlot.WHILE_AWAY: 1}
        assert "- fact 4 | On their list, undated: Plan Q1" in facts.block


class TestARepeatIsSaidAsStillOpen:
    _SHOWN = SignalMemoryDocument(
        user_id="u1",
        integration_id="gaia",
        external_id="todo:t1",
        first_seen=datetime(2026, 11, 8, 3, tzinfo=UTC),
        times_shown=3,
        last_shown=datetime(2026, 11, 10, 3, tzinfo=UTC),
        last_state="you",
    )

    def test_a_signal_is_left_to_its_own_block_and_the_items_after_it_still_get_lines(
        self,
    ) -> None:
        signal = Signal(
            integration_id="linear", app="Linear", external_id="E-1", kind="issue", title="E-1"
        )
        app_item = BriefCandidate(
            source="linear", app="Linear", state="you", title="E-1", signal=signal
        )
        shown = BriefCandidate(
            source="gaia", app="GAIA", state="you", title="Approve the MSA", memory=self._SHOWN
        )
        placed = [
            (BriefingItem(text="E-1", kind="you", action=BriefAction.REVIEW), app_item),
            (BriefingItem(text="Approve the MSA", kind="you", action=BriefAction.APPROVE), shown),
        ]

        facts = build_facts(_chosen(*placed), _sources(), _CLOCK)

        assert "fact 1 |" not in facts.block
        assert (
            "- fact 2 | Waiting on you: Approve the MSA | already shown, still open"
            " (first seen 3 days ago, mentioned 3 time(s), last yesterday)"
        ) in facts.block

    def test_a_repeat_with_a_deliverable_is_said_as_still_open_too(self) -> None:
        shown = BriefCandidate(
            source="gaia",
            app="GAIA",
            state="gaia",
            title="Investor list",
            todo_id="t1",
            memory=self._SHOWN.model_copy(update={"last_state": "gaia"}),
        )
        item = BriefingItem(
            text="Investor list", kind="gaia", todo_id="t1", outcome=BriefOutcome.STARTED
        )

        facts = build_facts(
            _chosen((item, shown)),
            _sources(artifacts={"t1": ArtifactFact(snippet="12 vetted", chars=900, action=False)}),
            _CLOCK,
        )

        assert "already shown, still open (first seen 3 days ago" in facts.block


class TestTheEmptyBriefAndTheLead:
    def test_a_brief_with_no_items_tells_the_voice_not_to_claim_any_work(self) -> None:
        facts = build_facts(Chosen(sections=[], picked=[]), _sources(), _CLOCK)

        assert (
            "No tracked work, results or app items need them today. Do not claim anything ran, "
            "finished, or is pending beyond what is stated here."
        ) in facts.block.splitlines()
        assert facts.lead is None

    def test_a_weekly_with_no_items_says_so_of_the_week_not_of_today(self) -> None:
        facts = build_facts(Chosen(sections=[], picked=[]), _sources(span=WEEK_AHEAD), _CLOCK)

        assert (
            "The digest holds no items from this week. Do not claim anything ran, finished, or "
            "is pending beyond what is stated here."
        ) in facts.block.splitlines()
        assert "today" not in facts.block

    def test_an_event_is_a_fact_timed_on_the_users_day(self) -> None:
        event = BriefingEvent(date="2026-11-11", start="15:00", title="Board call")

        facts = build_facts(
            Chosen(sections=[], picked=[]), _sources(calendar=[event], event_ids=[7]), _CLOCK
        )

        assert facts.values.facts == {7: BriefFact(title="Board call", time="3:00 PM")}

    def test_the_lead_is_the_first_item_of_the_section_the_composition_leads_with(self) -> None:
        def item(text: str) -> tuple[BriefingItem, BriefCandidate]:
            return (
                BriefingItem(text=text, kind="you", action=BriefAction.REPLY),
                BriefCandidate(source="gaia", app="GAIA", state="you", title=text),
            )

        sections = [
            BriefingSection(numeral="I", title="Waiting", items=[item("a")[0], item("b")[0]]),
            BriefingSection(numeral="II", title="First", items=[item("c")[0], item("d")[0]]),
        ]
        picked = [
            [(1, item("a")[1]), (2, item("b")[1])],
            [(5, item("c")[1]), (6, item("d")[1])],
        ]
        blocks: list[BriefBlock] = [
            SectionBlock(kind="items", section=0),
            SectionBlock(kind="lead", section=1),
        ]

        facts = build_facts(Chosen(sections, picked), _sources(blocks=blocks), _CLOCK)

        assert facts.lead == 5


class TestTheWeekRecap:
    """The weekly's recap: each GAIA count series as a slotted total, and each goal's week."""

    _FINISHED = DataSeries(
        id="gaia_finished",
        label="Tasks GAIA finished",
        unit="tasks",
        source="gaia",
        app="GAIA",
        shape=SeriesShape.TIME_SERIES,
        points=[SeriesPoint(x="2026-11-09", y=4), SeriesPoint(x="2026-11-10", y=2)],
    )
    _UNITLESS = _FINISHED.model_copy(update={"id": "runs", "label": "Runs", "unit": None})

    def test_totals_and_goals_read_as_slotted_lines_and_quotable_titles(self) -> None:
        item = BriefingItem(text="Q3 board pack", kind="you", action=BriefAction.REVIEW)
        candidate = BriefCandidate(source="gaia", app="GAIA", state="you", title="Q3 board pack")
        goals = [
            GoalState(
                id="g1",
                statement="Ship Atlas",
                origin=GoalOrigin.MEMORY,
                done=2,
                open=2,
                linked=["Atlas v11 build", "Atlas docs", "Atlas pricing", "Atlas press"],
                stalled=["Atlas pricing", "Atlas press"],
            ),
            GoalState(
                id="g2", statement="Run a marathon", origin=GoalOrigin.ONBOARDING, done=0, open=0
            ),
        ]
        sources = FactSources(
            artifacts={},
            open_todos=0,
            calendar=[],
            event_ids=[],
            span=WEEK_AHEAD,
            todos_note=None,
            recap=WeekRecap(series=[self._FINISHED, self._UNITLESS], goals=goals),
        )

        facts = build_facts(_chosen((item, candidate)), sources, _CLOCK)

        lines = facts.block.splitlines()
        start = lines.index(
            "[THE WEEK IN NUMBERS] (voice these as one grouped recap of the week, never as a list)"
        )
        assert lines[start + 1 : start + 6] == [
            "- Tasks GAIA finished: [[series:gaia_finished.total]] (6 tasks)",
            "- Runs: [[series:runs.total]] (6)",
            "[GOALS THIS WEEK]",
            '- "Ship Atlas": moved forward, 2 finished (2 by an event, or no one recorded),'
            " 2 open: Atlas v11 build; Atlas docs | stuck a week or more: Atlas pricing; Atlas press",
            '- "Run a marathon": nothing linked to it finished, 0 finished, 0 open',
        ]
        assert facts.values.series["gaia_finished"][SeriesField.TOTAL] == "6"
        assert {"Q3", "v11"} <= facts.values.quoted


class TestTheOwnTodosNote:
    def test_overdue_todos_are_counted_by_their_slot_and_never_listed(self) -> None:
        assert user_todos_note(80, 70) == (
            "The user's own open todos are counted in [COUNTS]; never voice that list as clear or"
            " empty. [[count:overdue_todos]] of them are past due: say that count in one plain"
            " line, never list them."
        )

    def test_with_none_past_due_the_note_says_nothing_of_it(self) -> None:
        assert user_todos_note(80) == (
            "The user's own open todos are counted in [COUNTS]; never voice that list as clear or"
            " empty."
        )
