"""A checked composition laid out as the brief: numbered sections, data blocks, and everything left out."""

from dataclasses import replace
from datetime import date

import pytest

from app.constants.briefing import BriefAction, BriefOutcome
from app.models.brief_candidate_models import BriefCandidate
from app.models.brief_composition_models import (
    BriefComposition,
    ChartBlock,
    ChartKind,
    NoteBlock,
    ProgressBlock,
    QuoteBlock,
    SectionBlock,
)
from app.models.brief_pool_models import (
    DataSeries,
    GoalOrigin,
    GoalState,
    QuoteSpan,
    SeriesPoint,
    SeriesShape,
)
from app.models.briefing_models import BriefPoolItem
from app.models.scout_models import Signal
from app.services.briefing.fact_pool.pool import FactPool, PoolContext
from app.services.briefing.sections import _data_block, carried_ids, lay_out, sources_shown

_SIGNAL = Signal(
    integration_id="linear",
    app="Linear",
    external_id="ENG-12",
    kind="issue assigned to you",
    title="Fix the login redirect",
    why="due tomorrow",
)
_SERIES = DataSeries(
    id="gmail_sorted",
    label="Mail sorted since yesterday",
    unit="emails",
    source="gmail",
    app="Gmail",
    shape=SeriesShape.CATEGORICAL,
    points=[SeriesPoint(x="Junk", y=22), SeriesPoint(x="Needs a reply", y=9)],
)
_QUOTE = QuoteSpan(
    id="q1",
    text="Can you confirm by Friday?",
    author="Maya",
    source="gmail",
    app="Gmail",
    item_id=1,
)
_GOAL = GoalState(id="g1", statement="Ship v3", origin=GoalOrigin.MEMORY, done=2, open=1)
POOL = FactPool(
    items={
        1: BriefCandidate(
            source="gmail",
            app="Gmail",
            state="you",
            title="Re: term sheet",
            todo_id="t1",
            people=["Maya"],
        ),
        2: BriefCandidate(
            source="gaia",
            app="GAIA",
            state="failed",
            title="CRM sync failed",
            action=BriefAction.RETRY,
            held_id="h2",
        ),
        3: BriefCandidate(
            source="gaia",
            app="GAIA",
            state="lookback",
            title="Investor update",
            outcome=BriefOutcome.SENT,
        ),
        4: BriefCandidate(
            source="linear",
            app="Linear",
            state="you",
            title=_SIGNAL.title,
            detail="issue assigned to you | why: due tomorrow | new today",
            url="https://linear.app/ENG-12",
            signal=_SIGNAL,
        ),
        5: BriefCandidate(
            source="googlecalendar",
            app="Google Calendar",
            state="note",
            title="Board call",
            is_event=True,
        ),
        6: BriefCandidate(
            source="gaia", app="GAIA", state="note", title="Digest: three papers", held_id="h6"
        ),
    },
    series=[_SERIES],
    quotes=[_QUOTE],
    goals=[_GOAL],
    context=PoolContext(
        reader="Ada",
        timezone="UTC",
        today=date(2026, 11, 11),
        calendar_events=1,
        calendar_connected=True,
        calendar_span="today",
        recent_openings=[],
    ),
    criteria={},
)
_COMPOSITION = BriefComposition.model_validate(
    {
        "blocks": [
            {
                "kind": "lead",
                "item": {
                    "id": 1,
                    "action": "reply",
                    "outcome": None,
                    "title": "Term sheet",
                    "detail": None,
                },
                "offer": "Send the reply I drafted",
            },
            {"kind": "quote", "quote_id": "q1"},
            {
                "kind": "items",
                "state": "done",
                "heading": "Worth a look",
                "items": [
                    {
                        "id": 2,
                        "action": None,
                        "outcome": "failed",
                        "title": "CRM sync",
                        "detail": None,
                    },
                    {
                        "id": 3,
                        "action": None,
                        "outcome": "finished",
                        "title": "Investor update",
                        "detail": None,
                    },
                ],
            },
            {
                "kind": "chart",
                "series_ids": ["gmail_sorted"],
                "chart": "bar",
                "title": "Yesterday's mail",
                "takeaway": "Most of it was junk.",
            },
            {"kind": "progress", "goal_id": "g1"},
            {"kind": "note", "text": "A light afternoon after the board call."},
        ]
    }
)


class TestLayOut:
    def test_lead_and_items_become_numbered_sections_and_the_rest_carry_their_data(self) -> None:
        laid = lay_out(_COMPOSITION, POOL)

        assert [(s.numeral, s.title) for s in laid.chosen.sections] == [
            ("I", "First up"),
            ("II", "Worth a look"),
        ]
        assert laid.blocks == [
            SectionBlock(kind="lead", section=0),
            QuoteBlock(quote=_QUOTE),
            SectionBlock(kind="items", section=1),
            ChartBlock(
                chart=ChartKind.BAR,
                title="Yesterday's mail",
                takeaway="Most of it was junk.",
                series=[_SERIES],
            ),
            ProgressBlock(goal=_GOAL),
            NoteBlock(text="A light afternoon after the board call."),
        ]
        assert [[i for i, _ in picked] for picked in laid.chosen.picked] == [[1], [2, 3]]

    def test_a_placed_item_reads_the_side_the_composer_put_it_on_in_its_producers_words(
        self,
    ) -> None:
        lead, worth = lay_out(_COMPOSITION, POOL).chosen.sections

        [term_sheet] = lead.items
        assert (term_sheet.text, term_sheet.action, term_sheet.kind, term_sheet.offer) == (
            "Term sheet",
            BriefAction.REPLY,
            "you",
            "Send the reply I drafted",
        )
        assert (term_sheet.todo_id, term_sheet.people) == ("t1", ["Maya"])
        crm, investor = worth.items
        # Reported, the failed sync reads as a note; the producer's outcome beats the composer's.
        assert (crm.outcome, crm.action, crm.kind, crm.offer) == (
            BriefOutcome.FAILED,
            None,
            "note",
            None,
        )
        assert (investor.outcome, investor.kind) == (BriefOutcome.SENT, "lookback")

    def test_a_placed_item_says_where_it_came_from_how_many_asked_and_what_it_was_told(
        self,
    ) -> None:
        pool = replace(
            POOL,
            items={
                **POOL.items,
                7: BriefCandidate(
                    source="gmail",
                    app="Gmail",
                    state="you",
                    title="Three asks",
                    count=3,
                    url="https://mail.example/t7",
                ),
            },
        )
        composition = BriefComposition.model_validate(
            {
                "blocks": [
                    {
                        "kind": "items",
                        "state": "needs_you",
                        "heading": "Waiting",
                        "items": [
                            {
                                "id": 7,
                                "action": "reply",
                                "outcome": None,
                                "title": " Three asks ",
                                "detail": "  one thread, three nudges ",
                            },
                            {
                                "id": 6,
                                "action": "read",
                                "outcome": None,
                                "title": "Digest",
                                "detail": "   ",
                            },
                            {
                                "id": 2,
                                "action": "retry",
                                "outcome": None,
                                "title": "CRM sync",
                                "detail": None,
                            },
                        ],
                    }
                ]
            }
        )

        [section] = lay_out(composition, pool).chosen.sections

        asks, digest, sync = section.items
        assert (asks.text, asks.detail, asks.count, asks.app, asks.source, asks.url) == (
            "Three asks",
            "one thread, three nudges",
            3,
            "Gmail",
            "gmail",
            "https://mail.example/t7",
        )
        assert (digest.detail, digest.kind) == (None, "you")
        assert (sync.kind, sync.detail) == ("failed", None)

    def test_a_pool_item_left_out_keeps_the_todo_it_names(self) -> None:
        pool = replace(
            POOL,
            items={
                7: BriefCandidate(
                    source="gaia", app="GAIA", state="note", title="Left", todo_id="t7"
                )
            },
        )

        laid = lay_out(BriefComposition(blocks=[]), pool)

        assert [(i.title, i.todo_id) for i in laid.uncomposed] == [("Left", "t7")]

    def test_a_section_block_is_not_a_data_block(self) -> None:
        lead = _COMPOSITION.blocks[0]

        with pytest.raises(
            ValueError, match="^a lead block is laid out as a section, not as data$"
        ):
            _data_block(lead, POOL)

    def test_everything_left_out_is_kept_for_the_page_but_the_calendar(self) -> None:
        laid = lay_out(_COMPOSITION, POOL)

        assert laid.uncomposed == [
            BriefPoolItem(
                title="Fix the login redirect",
                detail="due tomorrow",
                kind="you",
                app="Linear",
                url="https://linear.app/ENG-12",
            ),
            BriefPoolItem(title="Digest: three papers", kind="note", app="GAIA"),
        ]

    def test_every_held_result_in_the_pool_is_carried_composed_or_not(self) -> None:
        assert carried_ids(POOL.items, ["h9"]) == ["h2", "h6", "h9"]


class TestSourcesShown:
    def test_only_apps_the_brief_shows_something_from_are_named(self) -> None:
        laid = lay_out(_COMPOSITION, POOL)

        assert sources_shown(laid, POOL.items) == ["Gmail", "Google Calendar"]

    def test_a_charted_series_and_a_quote_name_their_apps(self) -> None:
        series = _SERIES.model_copy(update={"id": "gh_prs", "source": "github", "app": "GitHub"})
        quote = _QUOTE.model_copy(update={"source": "slack", "app": "Slack"})
        own = _SERIES.model_copy(update={"id": "runs", "source": "gaia", "app": "GAIA"})
        pool = replace(POOL, series=[series, own], quotes=[quote])
        composition = BriefComposition.model_validate(
            {
                "blocks": [
                    {
                        "kind": "chart",
                        "series_ids": ["gh_prs", "runs"],
                        "chart": "bar",
                        "title": "Pull requests",
                        "takeaway": "Two merged.",
                    },
                    {"kind": "quote", "quote_id": "q1"},
                ]
            }
        )

        assert sources_shown(lay_out(composition, pool), pool.items) == [
            "Google Calendar",
            "GitHub",
            "Slack",
        ]
