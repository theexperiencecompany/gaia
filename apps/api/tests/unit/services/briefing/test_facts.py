"""The facts the voice is shown: one line per item and event, the figures its prose may quote and its slots."""

from datetime import UTC, datetime
from zoneinfo import ZoneInfo

import pytest
from tests.factories import make_user_id

from app.agents.prompts.brief_fact_prompts import (
    CALENDAR_UNAVAILABLE,
    NO_CALENDAR_CONNECTED,
    SHOWN_NOT_TOTAL,
    SIGNALS_HEADER,
)
from app.constants.briefing import (
    BriefAction,
    BriefOutcome,
)
from app.models.brief_candidate_models import BriefCandidate, CandidateOrigin, HeldResult
from app.models.brief_composition_models import BriefBlock, ChartBlock, ChartKind, SectionBlock
from app.models.brief_item_models import ItemState
from app.models.brief_payload_models import (
    BriefingEvent,
    BriefingItem,
    BriefingSection,
    UnreadSource,
)
from app.models.brief_pool_models import (
    DataSeries,
    GoalOrigin,
    GoalState,
    SeriesPoint,
    SeriesShape,
)
from app.models.brief_slot_models import CountName, SeriesField
from app.models.scout_models import (
    ScoutSkipReason,
    Signal,
    SignalImportance,
    SignalMemoryDocument,
)
from app.services.briefing.artifacts import ArtifactFact
from app.services.briefing.calendar_read import CalendarGap, CalendarRead
from app.services.briefing.candidates.calendar import calendar_candidates
from app.services.briefing.clock import UserClock
from app.services.briefing.composition.compose import pool_values
from app.services.briefing.fact_pool.pool import FactPool, PoolContext
from app.services.briefing.facts import (
    TODAY,
    WEEK_AHEAD,
    BriefSpan,
    Facts,
    FactSources,
    WeekRecap,
    build_facts,
    user_todos_note,
)
from app.services.briefing.sections import Chosen
from app.services.briefing.slots import BriefFact, slot_problems

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


_CONTEXT = PoolContext(
    reader="Ada", clock=_CLOCK, calendar=0, calendar_span="today", done_since=_NOW
)


def _facts(chosen: Chosen, sources: FactSources, *uncharted: DataSeries) -> Facts:
    """Build the facts over a pool of what the brief placed, its events and series, as a run does."""
    items = {i: c for picked in chosen.picked for i, c in picked} | sources.event_items
    charted = [s for b in sources.blocks if isinstance(b, ChartBlock) for s in b.series]
    recapped = sources.recap.series if sources.recap else []
    pool = FactPool(
        items=items,
        series=[*charted, *recapped, *uncharted],
        quotes=[],
        goals=[],
        context=_CONTEXT,
        criteria={},
    )
    return build_facts(chosen, sources, pool_values(pool), _CLOCK)


def _hours(series_id: str, ys: list[float]) -> DataSeries:
    return DataSeries(
        id=series_id,
        label=series_id,
        unit="hours",
        source="gaia",
        app="GAIA",
        shape=SeriesShape.TIME_SERIES,
        points=[SeriesPoint(x=f"2026-11-{5 + n:02d}", y=y) for n, y in enumerate(ys)],
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
    calendar: list[BriefingEvent] | CalendarRead | None = None,
    event_ids: list[int] | None = None,
    span: BriefSpan = TODAY,
    blocks: list[BriefBlock] | None = None,
) -> FactSources:
    read = calendar if isinstance(calendar, CalendarRead) else CalendarRead(events=calendar or [])
    events = calendar_candidates(read.events, _CLOCK.date_str)
    return FactSources(
        artifacts=artifacts or {},
        open_todos=open_todos,
        calendar=read,
        event_items=dict(zip(event_ids or [], events, strict=False)),
        span=span,
        todos_note=None,
        blocks=blocks or [],
    )


class TestTheFactLines:
    def test_an_item_line_says_its_app_when_it_is_due_its_detail_and_how_many_asked(self) -> None:
        item = BriefingItem(
            text="Reply to Maya", kind=ItemState.YOU, app="Gmail", count=3, action=BriefAction.REPLY
        )
        candidate = BriefCandidate(
            origin=CandidateOrigin.TRACKED,
            source="gmail",
            app="Gmail",
            state=ItemState.YOU,
            title="Re: term sheet",
            detail="needs sign-off",
            due_at=datetime(2026, 11, 13, 9, 0, tzinfo=UTC),
            count=3,
        )

        facts = _facts(_chosen((item, candidate)), _sources(open_todos=4))

        assert facts.values.counts == {CountName.NEEDS_YOU: 1, CountName.OPEN_TODOS: 4}
        assert facts.values.facts[1] == BriefFact(
            title="Reply to Maya",
            time="Fri Nov 13",
            time_is_day=True,
            count=3,
            kind=ItemState.YOU,
            words="Re: term sheet needs sign-off",
        )
        assert facts.block.splitlines()[:3] == [
            "[COUNTS] [[count:needs_you]] (1) · [[count:gaia_todos]] (4)",
            "[Waiting]",
            "1. [Gmail] waiting on you: Reply to Maya | needs sign-off | due [[fact:1.time]] "
            "(Fri Nov 13) | [[fact:1.count]] (3) todos on this one subject",
        ]

    def test_the_users_own_todo_has_no_deliverable_and_reads_as_a_plain_line(self) -> None:
        """Replay of 2026-11-14: placing an own todo raised KeyError on its todo id."""
        item = BriefingItem(
            text="Sort the garage", kind=ItemState.YOU, action=BriefAction.ATTEND, todo_id="own-1"
        )
        candidate = BriefCandidate(
            origin=CandidateOrigin.TRACKED,
            source="gaia",
            app="GAIA",
            state=ItemState.YOU,
            title="Sort the garage",
            todo_id="own-1",
        )

        facts = _facts(_chosen((item, candidate)), _sources())

        assert "1. [GAIA] waiting on you: Sort the garage\n" in f"{facts.block}\n"
        assert facts.deliverables == {}

    def test_tracked_work_waiting_on_the_user_says_the_question_it_asks_them(self) -> None:
        item = BriefingItem(
            text="Venue", kind=ItemState.YOU, todo_id="t1", action=BriefAction.REPLY
        )
        candidate = BriefCandidate(
            origin=CandidateOrigin.TRACKED,
            source="gaia",
            app="GAIA",
            state=ItemState.YOU,
            title="Venue",
            detail="Lisbon or Porto?",
        )
        art = ArtifactFact(snippet="", chars=0, action=True)

        facts = _facts(_chosen((item, candidate)), _sources(artifacts={"t1": art}))

        assert (
            "1. [GAIA] waiting on you: Venue | Lisbon or Porto?"
            " | artifact holds ~0 chars | waiting on you"
        ) in facts.block


class TestWhatTheVoiceMayLink:
    @staticmethod
    def _work(todo_id: str | None, url: str | None) -> tuple[BriefingItem, BriefCandidate]:
        return (
            BriefingItem(
                text="Deck", kind=ItemState.GAIA, todo_id=todo_id, outcome=BriefOutcome.STARTED
            ),
            BriefCandidate(
                origin=CandidateOrigin.TRACKED,
                source="gaia",
                app="GAIA",
                state=ItemState.GAIA,
                title="Deck",
                url=url,
            ),
        )

    @pytest.mark.parametrize(
        ("todo_id", "url", "chars", "linked"),
        [
            ("t1", None, 900, True),
            (None, "https://docs.example/deck", 0, True),
            ("t1", None, 0, False),
        ],
        ids=["a-deliverable", "an-address", "an-empty-deliverable"],
    )
    def test_a_fact_is_linkable_when_it_opens_a_deliverable_or_an_address(
        self, todo_id: str | None, url: str | None, chars: int, linked: bool
    ) -> None:
        art = ArtifactFact(snippet="", chars=chars, action=False)

        facts = _facts(_chosen(self._work(todo_id, url)), _sources(artifacts={"t1": art}))

        assert ("| linkable" in facts.block) is linked


class TestWhatProseMayQuote:
    def test_the_date_an_items_standing_says_may_be_quoted(self) -> None:
        item = BriefingItem(text="Pitch prep", kind=ItemState.GAIA, outcome=BriefOutcome.STARTED)
        candidate = BriefCandidate(
            origin=CandidateOrigin.TRACKED,
            source="gaia",
            app="GAIA",
            state=ItemState.GAIA,
            title="Pitch prep",
            standing="GAIA looks at it again Tue Nov 17",
        )

        facts = _facts(_chosen((item, candidate)), _sources())

        assert facts.values.quoted == {"17"}
        assert facts.block.splitlines()[2] == (
            "1. [GAIA] open: Pitch prep | stands: GAIA looks at it again Tue Nov 17"
        )

    def test_the_figures_in_every_items_own_words_may_be_quoted(self) -> None:
        first = (
            BriefingItem(
                text="Q3 plan", kind=ItemState.YOU, todo_id="t1", action=BriefAction.REPLY
            ),
            BriefCandidate(
                origin=CandidateOrigin.TRACKED,
                source="gaia",
                app="GAIA",
                state=ItemState.YOU,
                title="Q3 plan",
                detail="due by 5pm",
            ),
        )
        second = (
            BriefingItem(text="Q4 plan", kind=ItemState.YOU, action=BriefAction.REPLY),
            BriefCandidate(
                origin=CandidateOrigin.TRACKED,
                source="gaia",
                app="GAIA",
                state=ItemState.YOU,
                title="Q4 plan",
            ),
        )
        art = ArtifactFact(snippet="42 slides", chars=900, action=False)

        facts = _facts(_chosen(first, second), _sources(artifacts={"t1": art}))

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
        item = BriefingItem(text="Fix login", kind=ItemState.YOU, action=BriefAction.REPLY)
        candidate = BriefCandidate(
            origin=CandidateOrigin.APP_SIGNAL,
            source="linear",
            app="Linear",
            state=ItemState.YOU,
            title="Fix login 4",
            signal=signal,
        )

        facts = _facts(_chosen((item, candidate)), _sources())

        assert facts.values.quoted == {"4", "2", "P1", "88"}


class TestTheCalendarAndTheCharts:
    def test_a_charts_figures_are_what_the_series_slots_render(self) -> None:
        chart = ChartBlock(chart=ChartKind.BAR, title="Mail", takeaway="Junk.", series=[_SERIES])

        facts = _facts(Chosen(sections=[], picked=[]), _sources(blocks=[chart]))

        assert facts.values.series["gmail_sorted"][SeriesField.TOTAL] == "31"

    def test_the_voice_is_offered_the_figures_of_every_charted_series_alone(self) -> None:
        meetings = _hours("meetings", [2, 1, 4])
        focus = _hours("focus", [3, 3, 1])
        chart = ChartBlock(
            chart=ChartKind.STACKED_BAR,
            title="This week",
            takeaway="Thursday was heaviest.",
            series=[meetings, focus],
        )

        facts = _facts(Chosen(sections=[], picked=[]), _sources(blocks=[chart]), _SERIES)

        assert list(facts.values.series) == ["meetings", "focus"]
        assert facts.values.series["meetings"][SeriesField.TOTAL] == "7"
        assert facts.values.series["meetings"][SeriesField.PEAK] == "4"
        assert facts.values.series["focus"][SeriesField.LATEST] == "1"

    def test_events_and_their_ids_must_pair_up(self) -> None:
        event = BriefingEvent(date="2026-11-11", start="15:00", title="Board call")

        with pytest.raises(ValueError, match="zip"):
            _facts(Chosen(sections=[], picked=[]), _sources(calendar=[event], event_ids=[]))

    def test_the_calendar_note_lists_each_event_by_its_fact_and_time(self) -> None:
        events = [
            BriefingEvent(date="2026-11-11", start="15:00", title="Board call"),
            BriefingEvent(date="2026-11-11", start=None, title="Offsite"),
        ]
        span = BriefSpan(heading="This week", empty="Nothing.", no_items="None.", words="this week")

        facts = _facts(
            Chosen(sections=[], picked=[]), _sources(calendar=events, event_ids=[7, 8], span=span)
        )

        assert facts.block.splitlines()[-3:] == [
            "This week:",
            "7. [Google Calendar] calendar event: Board call | at [[fact:7.time]] (3:00 PM)"
            " | action attend",
            "8. [Google Calendar] calendar event: Offsite | all day | action attend",
        ]

    @pytest.mark.parametrize("days", [2, 7], ids=["two-days", "a-week"])
    def test_a_span_of_several_days_lists_its_events_under_each_days_count(self, days: int) -> None:
        events = [
            BriefingEvent(date="2026-11-12", start="15:00", title="Board call"),
            BriefingEvent(date="2026-11-12", start=None, title="Offsite"),
            BriefingEvent(date="2026-11-13", start="09:30", title="Dentist"),
        ]
        span = BriefSpan(
            heading="The days ahead", empty="Nothing.", no_items="None.", words="ahead", days=days
        )

        facts = _facts(
            Chosen(sections=[], picked=[]),
            _sources(calendar=events, event_ids=[7, 8, 9], span=span),
        )

        assert facts.block.splitlines()[-6:] == [
            "The days ahead, 3 event(s):",
            "Thu Nov 12, 2 event(s), the week's busiest:",
            "7. [Google Calendar] calendar event: Board call | at [[fact:7.time]] (3:00 PM)"
            " | action attend",
            "8. [Google Calendar] calendar event: Offsite | all day | action attend",
            "Fri Nov 13, 1 event(s):",
            "9. [Google Calendar] calendar event: Dentist | at [[fact:9.time]] (9:30 AM)"
            " | action attend",
        ]

    def test_days_with_as_many_events_as_each_other_have_no_busiest(self) -> None:
        events = [
            BriefingEvent(date="2026-11-12", start="15:00", title="Board call"),
            BriefingEvent(date="2026-11-13", start=None, title="Offsite"),
        ]

        facts = _facts(
            Chosen(sections=[], picked=[]),
            _sources(calendar=events, event_ids=[7, 8], span=WEEK_AHEAD),
        )

        assert facts.block.splitlines()[-5:] == [
            "The week ahead, 2 event(s):",
            "Thu Nov 12, 1 event(s):",
            "7. [Google Calendar] calendar event: Board call | at [[fact:7.time]] (3:00 PM)"
            " | action attend",
            "Fri Nov 13, 1 event(s):",
            "8. [Google Calendar] calendar event: Offsite | all day | action attend",
        ]

    def test_with_no_calendar_connected_the_note_says_so_not_that_it_is_empty(self) -> None:
        unconnected = _sources(calendar=CalendarRead(gap=CalendarGap.NOT_CONNECTED))

        facts = _facts(Chosen(sections=[], picked=[]), unconnected)

        assert facts.block.splitlines()[-1] == NO_CALENDAR_CONNECTED
        assert TODAY.empty not in facts.block

    def test_a_calendar_that_did_not_answer_is_never_an_empty_day(self) -> None:
        """Regression: a calendar read that failed told the voice the day was free."""
        unread = _sources(calendar=CalendarRead(gap=CalendarGap.UNAVAILABLE))

        facts = _facts(Chosen(sections=[], picked=[]), unread)

        assert facts.block.splitlines()[-1] == CALENDAR_UNAVAILABLE
        assert TODAY.empty not in facts.block


class TestEachCountClaimsOnlyItsOwn:
    def test_only_held_results_are_while_away_and_an_event_or_backlog_never_waits(self) -> None:
        """Regression: every placed note was counted as come in while away, a calendar lead too."""
        held = BriefCandidate(
            origin=HeldResult(id="h1"),
            source="gaia",
            app="GAIA",
            state=ItemState.NOTE,
            title="Digest: 3 papers",
        )
        signal = BriefCandidate(
            origin=CandidateOrigin.TRACKED,
            source="linear",
            app="Linear",
            state=ItemState.YOU,
            title="ENG-12 merged",
        )
        event = BriefCandidate(
            origin=CandidateOrigin.EVENT,
            source="googlecalendar",
            app="Google Calendar",
            state=ItemState.NOTE,
            title="Board",
        )
        backlog = BriefCandidate(
            origin=CandidateOrigin.BACKLOG,
            source="gaia",
            app="GAIA",
            state=ItemState.YOU,
            title="Plan Q1",
        )
        waiting = BriefCandidate(
            origin=CandidateOrigin.TRACKED,
            source="gmail",
            app="Gmail",
            state=ItemState.YOU,
            title="Reply to Maya",
        )
        placed = [
            (BriefingItem(text="Board", kind=ItemState.YOU, action=BriefAction.ATTEND), event),
            (BriefingItem(text="Digest", kind=ItemState.NOTE, outcome=BriefOutcome.FINISHED), held),
            (
                BriefingItem(text="ENG-12", kind=ItemState.NOTE, outcome=BriefOutcome.CHANGED),
                signal,
            ),
            (BriefingItem(text="Plan Q1", kind=ItemState.YOU, action=BriefAction.ATTEND), backlog),
            (BriefingItem(text="Maya", kind=ItemState.YOU, action=BriefAction.REPLY), waiting),
        ]

        facts = _facts(_chosen(*placed), _sources())

        assert facts.values.counts == {CountName.NEEDS_YOU: 1, CountName.WHILE_AWAY: 1}
        assert "4. [GAIA] on their list, undated: Plan Q1\n" in f"{facts.block}\n"

    def test_done_and_in_progress_count_one_each_of_their_own_kind(self) -> None:
        done = BriefCandidate(
            origin=CandidateOrigin.TRACKED,
            source="gaia",
            app="GAIA",
            state=ItemState.LOOKBACK,
            title="Filed taxes",
        )
        running = BriefCandidate(
            origin=CandidateOrigin.TRACKED,
            source="gaia",
            app="GAIA",
            state=ItemState.GAIA,
            title="Venue search",
        )
        placed = [
            (
                BriefingItem(
                    text="Filed taxes", kind=ItemState.LOOKBACK, outcome=BriefOutcome.FINISHED
                ),
                done,
            ),
            (
                BriefingItem(text="Venue", kind=ItemState.GAIA, outcome=BriefOutcome.STARTED),
                running,
            ),
            (
                BriefingItem(text="Venue 2", kind=ItemState.GAIA, outcome=BriefOutcome.STARTED),
                running,
            ),
        ]

        facts = _facts(_chosen(*placed), _sources())

        assert facts.values.counts == {CountName.DONE: 1, CountName.IN_PROGRESS: 2}

    def test_the_spans_events_are_counted(self) -> None:
        events = [
            BriefingEvent(date="2026-11-11", start="15:00", title="Board call"),
            BriefingEvent(date="2026-11-11", start=None, title="Offsite"),
        ]

        facts = _facts(Chosen(sections=[], picked=[]), _sources(calendar=events, event_ids=[7, 8]))

        assert facts.values.counts == {CountName.EVENTS: 2}


class TestTheAppsBlock:
    @staticmethod
    def _placed(
        app: str, n: int, importance: SignalImportance, url: str | None = None
    ) -> tuple[BriefingItem, BriefCandidate]:
        signal = Signal(
            integration_id=app.lower(),
            app=app,
            external_id=f"E-{n}",
            kind="issue",
            title=f"Issue {n}",
            importance=importance,
        )
        return (
            BriefingItem(text=f"Issue {n}", kind=ItemState.YOU, action=BriefAction.REVIEW),
            BriefCandidate(
                origin=CandidateOrigin.APP_SIGNAL,
                source=app.lower(),
                app=app,
                state=ItemState.YOU,
                title=f"Issue {n}",
                importance=importance,
                due_at=datetime(2026, 11, 13, 9, 0, tzinfo=UTC),
                url=url,
                signal=signal,
            ),
        )

    def test_signals_are_grouped_per_app_important_first_on_the_shared_line_with_slots(
        self,
    ) -> None:
        placed = [
            self._placed("Linear", 1, SignalImportance.NORMAL, "https://linear.app/i/1"),
            self._placed("Jira", 2, SignalImportance.NORMAL),
            self._placed("Linear", 3, SignalImportance.HIGH),
        ]

        facts = _facts(_chosen(*placed), _sources())

        assert facts.signals.splitlines() == [
            f"{SIGNALS_HEADER} 3 item(s) shown from 2 app(s). {SHOWN_NOT_TOTAL}",
            "[Jira] 1 item(s) shown",
            "2. [Jira] waiting on you: Issue 2 | due [[fact:2.time]] (Fri Nov 13)",
            "[Linear] 2 item(s) shown",
            "3. [Linear] waiting on you, important: Issue 3 | due [[fact:3.time]] (Fri Nov 13)",
            "1. [Linear] waiting on you: Issue 1 | due [[fact:1.time]] (Fri Nov 13) | linkable",
        ]

    def test_no_signal_placed_is_no_block(self) -> None:
        item = BriefingItem(text="Q4 plan", kind=ItemState.YOU, action=BriefAction.REPLY)
        candidate = BriefCandidate(
            origin=CandidateOrigin.TRACKED,
            source="gaia",
            app="GAIA",
            state=ItemState.YOU,
            title="Q4 plan",
        )

        assert _facts(_chosen((item, candidate)), _sources()).signals == ""


class TestARepeatIsSaidAsStillOpen:
    _SHOWN = SignalMemoryDocument(
        user_id=make_user_id(),
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
            origin=CandidateOrigin.APP_SIGNAL,
            source="linear",
            app="Linear",
            state=ItemState.YOU,
            title="E-1",
            signal=signal,
        )
        shown = BriefCandidate(
            origin=CandidateOrigin.TRACKED,
            source="gaia",
            app="GAIA",
            state=ItemState.YOU,
            title="Approve the MSA",
            memory=self._SHOWN,
        )
        placed = [
            (BriefingItem(text="E-1", kind=ItemState.YOU, action=BriefAction.REVIEW), app_item),
            (
                BriefingItem(
                    text="Approve the MSA", kind=ItemState.YOU, action=BriefAction.APPROVE
                ),
                shown,
            ),
        ]

        facts = _facts(_chosen(*placed), _sources())

        assert "1. [Linear]" not in facts.block
        assert facts.signals.splitlines()[1:] == [
            "[Linear] 1 item(s) shown",
            "1. [Linear] waiting on you: E-1",
        ]
        assert (
            "2. [GAIA] waiting on you: Approve the MSA"
            " | already shown, still open (first seen 3 days ago, mentioned 3 time(s), last yesterday)"
        ) in facts.block

    def test_a_repeat_with_a_deliverable_is_said_as_still_open_too(self) -> None:
        shown = BriefCandidate(
            origin=CandidateOrigin.TRACKED,
            source="gaia",
            app="GAIA",
            state=ItemState.GAIA,
            title="Investor list",
            todo_id="t1",
            memory=self._SHOWN.model_copy(update={"last_state": "gaia"}),
        )
        item = BriefingItem(
            text="Investor list", kind=ItemState.GAIA, todo_id="t1", outcome=BriefOutcome.STARTED
        )

        facts = _facts(
            _chosen((item, shown)),
            _sources(artifacts={"t1": ArtifactFact(snippet="12 vetted", chars=900, action=False)}),
        )

        assert "already shown, still open (first seen 3 days ago" in facts.block


class TestTheEmptyBriefAndTheLead:
    def test_a_brief_with_no_items_tells_the_voice_not_to_claim_any_work(self) -> None:
        facts = _facts(Chosen(sections=[], picked=[]), _sources())

        assert (
            "No tracked work, results or app items need them today. Do not claim anything ran, "
            "finished, or is pending beyond what is stated here."
        ) in facts.block.splitlines()
        assert facts.lead is None

    def test_a_weekly_with_no_items_says_so_of_the_week_not_of_today(self) -> None:
        facts = _facts(Chosen(sections=[], picked=[]), _sources(span=WEEK_AHEAD))

        assert (
            "The digest holds no items from this week. Do not claim anything ran, finished, or "
            "is pending beyond what is stated here."
        ) in facts.block.splitlines()
        assert "today" not in facts.block

    def test_an_event_is_a_fact_timed_on_the_users_day(self) -> None:
        event = BriefingEvent(date="2026-11-11", start="15:00", title="Board call")

        facts = _facts(Chosen(sections=[], picked=[]), _sources(calendar=[event], event_ids=[7]))

        assert facts.values.facts == {7: BriefFact(title="Board call", time="3:00 PM")}

    def test_the_time_an_events_line_says_it_ends_may_be_typed(self) -> None:
        event = BriefingEvent(date="2026-11-11", start="10:30", end="10:45", title="Standup")

        facts = _facts(Chosen(sections=[], picked=[]), _sources(calendar=[event], event_ids=[7]))

        assert slot_problems("message", "Standup runs until 10:45.", facts.values) == []

    def test_the_lead_is_the_first_item_of_the_section_the_composition_leads_with(self) -> None:
        def item(text: str) -> tuple[BriefingItem, BriefCandidate]:
            return (
                BriefingItem(text=text, kind=ItemState.YOU, action=BriefAction.REPLY),
                BriefCandidate(
                    origin=CandidateOrigin.TRACKED,
                    source="gaia",
                    app="GAIA",
                    state=ItemState.YOU,
                    title=text,
                ),
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

        facts = _facts(Chosen(sections, picked), _sources(blocks=blocks))

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
        item = BriefingItem(text="Q3 board pack", kind=ItemState.YOU, action=BriefAction.REVIEW)
        candidate = BriefCandidate(
            origin=CandidateOrigin.TRACKED,
            source="gaia",
            app="GAIA",
            state=ItemState.YOU,
            title="Q3 board pack",
        )
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
            calendar=CalendarRead(),
            event_items={},
            span=WEEK_AHEAD,
            todos_note=None,
            recap=WeekRecap(series=[self._FINISHED, self._UNITLESS], goals=goals),
        )

        facts = _facts(_chosen((item, candidate)), sources)

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

    def test_a_goals_todo_the_brief_places_is_named_as_its_item_not_again_by_title(self) -> None:
        """Replay of the founder's weekly: the stuck video and tweet were named twice."""
        item = BriefingItem(
            text="Atlas pricing sheet", kind=ItemState.YOU, action=BriefAction.REVIEW
        )
        candidate = BriefCandidate(
            origin=CandidateOrigin.BACKLOG,
            source="gaia",
            app="GAIA",
            state=ItemState.YOU,
            title="Atlas pricing",
        )
        goal = GoalState(
            id="g1",
            statement="Ship Atlas",
            origin=GoalOrigin.MEMORY,
            done=0,
            open=2,
            linked=["Atlas pricing", "Atlas press"],
            stalled=["Atlas pricing", "Atlas press"],
        )
        sources = FactSources(
            artifacts={},
            open_todos=0,
            calendar=CalendarRead(),
            event_items={},
            span=WEEK_AHEAD,
            todos_note=None,
            recap=WeekRecap(series=[], goals=[goal]),
        )

        lines = _facts(_chosen((item, candidate)), sources).block.splitlines()

        assert lines[lines.index("[GOALS THIS WEEK]") + 1] == (
            '- "Ship Atlas": nothing linked to it finished, 0 finished, 2 open'
            " | stuck a week or more: Atlas press; also item 1 above (say each only once, as its item)"
        )


class TestTheClosingLines:
    def test_an_empty_brief_says_so_then_what_went_unread_the_recap_todos_and_calendar(
        self,
    ) -> None:
        sources = FactSources(
            artifacts={},
            open_todos=0,
            calendar=CalendarRead(),
            event_items={},
            span=WEEK_AHEAD,
            todos_note="The user's own todo list is empty.",
            recap=WeekRecap(series=[TestTheWeekRecap._FINISHED], goals=[]),
            unread=[UnreadSource(app="Linear", reason=ScoutSkipReason.FAILED)],
        )

        facts = _facts(Chosen(sections=[], picked=[]), sources)

        assert facts.block.splitlines() == [
            "The digest holds no items from this week. Do not claim anything ran, finished, or "
            "is pending beyond what is stated here.",
            "Not read this time: Linear. Nothing is known about what they hold today: never say "
            "they hold nothing, or that nothing there needs the user.",
            "[THE WEEK IN NUMBERS] (voice these as one grouped recap of the week, never as a list)",
            "- Tasks GAIA finished: [[series:gaia_finished.total]] (6 tasks)",
            "The user's own todo list is empty.",
            "The user's calendar has nothing in the week ahead.",
        ]


class TestTheOwnTodosNote:
    def test_with_only_gaias_tracked_work_open_the_list_is_never_called_empty(self) -> None:
        assert user_todos_note(0, tracked_open=3) == (
            "The user has no todos of their own outside GAIA's tracked work, which holds "
            "[[count:open_tracked]] open: never call their todo list empty or clear."
        )

    def test_overdue_todos_are_counted_by_their_slot_and_never_listed(self) -> None:
        assert user_todos_note(80, 70) == (
            "The user's own open todos are counted in [COUNTS]; never voice that list as clear or"
            " empty. [[count:overdue_gaia_todos]] of them are past due: say that count in one"
            " plain line that names them as the user's GAIA todos (\"[[count:overdue_gaia_todos]]"
            " of your GAIA todos are overdue\"), never beside another app's items, and never"
            " list them."
        )

    def test_one_overdue_todo_is_exemplified_in_the_singular(self) -> None:
        assert '"[[count:overdue_gaia_todos]] of your GAIA todos is overdue"' in user_todos_note(
            80, 1
        )

    def test_with_none_past_due_the_note_says_nothing_of_it(self) -> None:
        assert user_todos_note(80) == (
            "The user's own open todos are counted in [COUNTS]; never voice that list as clear or"
            " empty."
        )
