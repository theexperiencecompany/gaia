"""The facts the voice is shown: one line per item and event, the figures its prose may quote and its slots."""

from datetime import UTC, datetime
from zoneinfo import ZoneInfo

import pytest

from app.constants.briefing import BriefAction
from app.models.brief_candidate_models import BriefCandidate
from app.models.brief_composition_models import BriefBlock, ChartBlock, ChartKind, SectionBlock
from app.models.brief_pool_models import DataSeries, SeriesPoint, SeriesShape
from app.models.briefing_models import BriefingEvent, BriefingItem, BriefingSection
from app.models.scout_models import Signal
from app.services.briefing.artifacts import ArtifactFact
from app.services.briefing.context import UserClock
from app.services.briefing.facts import TODAY, CalendarSpan, FactSources, build_facts
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
    calendar: list[BriefingEvent] | None = None,
    event_ids: list[int] | None = None,
    span: CalendarSpan = TODAY,
    blocks: list[BriefBlock] | None = None,
) -> FactSources:
    return FactSources(
        artifacts=artifacts or {},
        open_todos=open_todos,
        calendar=calendar or [],
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
        assert facts.values.facts[1] == BriefFact(title="Reply to Maya", time="Fri Nov 13", count=3)
        assert facts.block.splitlines()[:3] == [
            "[COUNTS] [[count:needs_you]] (1) · [[count:open_todos]] (4)",
            "[Waiting]",
            "- fact 1 | Waiting on you: Reply to Maya | in Gmail | time: [[fact:1.time]] "
            "(Fri Nov 13) | detail: needs sign-off | [[fact:1.count]] (3) requests, one item",
        ]


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
        span = CalendarSpan(heading="This week", empty="Nothing.")

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


class TestTheEmptyBriefAndTheLead:
    def test_a_brief_with_no_items_tells_the_voice_not_to_claim_any_work(self) -> None:
        facts = build_facts(Chosen(sections=[], picked=[]), _sources(), _CLOCK)

        assert (
            "The brief holds no items today. Do not claim anything ran, finished, or is pending "
            "beyond what is stated here."
        ) in facts.block.splitlines()
        assert facts.lead is None

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
