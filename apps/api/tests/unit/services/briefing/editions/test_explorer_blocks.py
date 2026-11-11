"""The drawn blocks every edition renders: each fact said by code, the calendar placed among them."""

from typing import Any

import pytest
from tests.factories import make_brief_item

from app.constants.briefing import EDITION_ROWS_SHOWN, BriefAction, BriefOutcome
from app.models.brief_composition_models import SectionBlock
from app.models.briefing_models import BriefingPayload
from app.services.briefing.editions.explorer_blocks import _data_block, build_blocks, read_sources

_EVENT = {"date": "2026-11-10", "start": "09:30", "title": "Standup"}


def _series(xs: list[str], ys: list[float], **fields: Any) -> dict[str, Any]:
    return {
        "id": fields.get("id", "s"),
        "label": fields.get("label", "Emails received"),
        "unit": fields.get("unit", "emails"),
        "source": fields.get("source", "gmail"),
        "app": "Gmail",
        "shape": fields.get("shape", "time_series"),
        "points": [{"x": x, "y": y} for x, y in zip(xs, ys, strict=True)],
    }


def _days(first: int, n: int, month: str = "11") -> list[str]:
    return [f"2026-{month}-{d:02d}" for d in range(first, first + n)]


def _built(blocks: list[dict[str, Any]], **fields: Any) -> list[dict[str, Any]]:
    payload = BriefingPayload.model_validate(
        {
            "kicker": "",
            "date": "2026-11-10",
            "headline": "",
            "lede": "",
            "mood": "clear",
            "caption": "",
            "template_family": "swiss",
            "blocks": blocks,
            **fields,
        }
    )
    return [
        dict(b)
        for b in build_blocks(payload.blocks, payload.sections, payload.calendar, payload.date)
    ]


def _chart(*series: dict[str, Any], kind: str = "line") -> dict[str, Any]:
    return {
        "kind": "chart",
        "chart": kind,
        "title": "Mail",
        "takeaway": "Up.",
        "series": list(series),
    }


@pytest.mark.unit
class TestItems:
    def test_an_ask_opens_with_its_verb_and_a_report_with_its_outcome(self) -> None:
        section = {
            "numeral": "I",
            "title": "Today",
            "items": [
                make_brief_item(
                    "Priya", "you", action=BriefAction.REPLY, source="slack", app="Slack"
                ),
                make_brief_item("Payout", "lookback", outcome=BriefOutcome.LANDED, source="gaia"),
            ],
        }

        [block] = _built([{"kind": "items", "section": 0}], sections=[section])

        assert [(i["verb"], i["outcome"], i["logo"]) for i in block["items"]] == [
            ("Reply", None, "slack"),
            (None, "Landed", None),
        ]

    def test_an_app_without_a_registered_mark_prints_none(self) -> None:
        section = {
            "numeral": "I",
            "title": "x",
            "items": [make_brief_item("Ticket", "you", action=BriefAction.READ, source="jira")],
        }

        [block] = _built([{"kind": "items", "section": 0}], sections=[section])

        assert block["items"][0]["logo"] is None

    def test_a_group_shows_its_first_rows_and_counts_the_rest(self) -> None:
        items = [make_brief_item(f"Thing {n}", "you", action=BriefAction.READ) for n in range(5)]

        [block] = _built(
            [{"kind": "items", "section": 0}],
            sections=[{"numeral": "I", "title": "x", "items": items}],
        )

        assert len(block["items"]) == EDITION_ROWS_SHOWN
        assert block["more"] == 5 - EDITION_ROWS_SHOWN

    def test_the_lead_carries_gaias_offer(self) -> None:
        lead = make_brief_item("Renewal", "you", action=BriefAction.APPROVE, offer="I'll draft it.")

        [block] = _built(
            [{"kind": "lead", "section": 0}],
            sections=[{"numeral": "I", "title": "First up", "items": [lead]}],
        )

        assert (block["item"]["verb"], block["offer"]) == ("Approve", "I'll draft it.")


_CAL_NOTE = {"kind": "note", "text": "n"}
_CAL_SECTIONS = [
    {
        "numeral": "I",
        "title": "First",
        "items": [make_brief_item("A", "you", action=BriefAction.READ)],
    },
    {"numeral": "II", "title": "Group", "items": [make_brief_item("B", "lookback")]},
]


@pytest.mark.unit
class TestCalendarPlacement:
    def test_the_calendar_follows_the_first_group_of_items(self) -> None:
        kinds = [
            b["kind"]
            for b in _built(
                [
                    {"kind": "lead", "section": 0},
                    _CAL_NOTE,
                    {"kind": "items", "section": 1},
                    _CAL_NOTE,
                ],
                sections=_CAL_SECTIONS,
                calendar=[_EVENT],
            )
        ]

        assert kinds == ["lead", "note", "items", "calendar", "note"]

    def test_with_no_group_the_calendar_follows_the_lead(self) -> None:
        kinds = [
            b["kind"]
            for b in _built(
                [{"kind": "lead", "section": 0}, _CAL_NOTE],
                sections=_CAL_SECTIONS,
                calendar=[_EVENT],
            )
        ]

        assert kinds == ["lead", "calendar", "note"]

    def test_with_neither_the_calendar_opens_the_brief(self) -> None:
        kinds = [b["kind"] for b in _built([_CAL_NOTE], calendar=[_EVENT])]

        assert kinds == ["calendar", "note"]

    def test_an_empty_calendar_adds_no_block(self) -> None:
        assert [b["kind"] for b in _built([_CAL_NOTE])] == ["note"]

    def test_an_all_day_event_has_no_time_and_a_later_days_names_its_day(self) -> None:
        [block] = _built(
            [],
            calendar=[
                {"date": "2026-11-10", "start": None, "title": "Offsite"},
                {"date": "2026-11-12", "start": "14:00", "title": "Board"},
            ],
        )

        assert [(e["t12"], e["t24"], e["day"]) for e in block["events"]] == [
            (None, None, None),
            ("2:00 PM", "14:00", "Thu"),
        ]


@pytest.mark.unit
class TestCharts:
    def test_a_week_is_labelled_by_weekday_and_spans_its_days(self) -> None:
        [chart] = _built([_chart(_series(_days(4, 7), [1, 2, 3, 4, 5, 6, 7]))])

        assert chart["x"] == ["Wed", "Thu", "Fri", "Sat", "Sun", "Mon", "Tue"]
        assert chart["range"] == "Wed 4 – Tue 10 Nov"

    def test_a_longer_run_is_labelled_by_date_across_months(self) -> None:
        days = [*_days(27, 5, "10"), *_days(1, 9)]

        [chart] = _built([_chart(_series(days, list(range(14))))])

        assert (chart["x"][0], chart["x"][-1]) == ("27 Oct", "9 Nov")
        assert chart["range"] == "27 Oct – 9 Nov"

    def test_a_week_across_months_names_both(self) -> None:
        days = [*_days(29, 3, "10"), *_days(1, 4)]

        [chart] = _built([_chart(_series(days, [1] * 7))])

        assert chart["range"] == "Thu 29 Oct – Wed 4 Nov"

    def test_categories_have_no_date_range(self) -> None:
        series = _series(["Gmail", "Slack"], [3, 4], shape="categorical")

        [chart] = _built([_chart(series, kind="bar")])

        assert (chart["x"], chart["range"]) == (["Gmail", "Slack"], None)

    def test_values_print_whole_or_to_one_decimal_with_their_total(self) -> None:
        [chart] = _built([_chart(_series(_days(4, 5), [5.5, 4, 6, 0.25, 3]))])

        assert chart["series"][0]["shown"] == ["5.5", "4", "6", "0.2", "3"]
        assert chart["series"][0]["total"] == "18.8"

    def test_a_shared_unit_is_the_charts_and_mixed_units_are_none(self) -> None:
        days = _days(4, 5)
        same = _built([_chart(_series(days, [1] * 5, id="a"), _series(days, [2] * 5, id="b"))])
        mixed = _built(
            [_chart(_series(days, [1] * 5, id="a"), _series(days, [2] * 5, id="b", unit="hours"))]
        )

        assert (same[0]["unit"], mixed[0]["unit"]) == ("emails", None)

    def test_a_series_carries_its_apps_mark_and_gaias_none(self) -> None:
        days = _days(4, 5)

        [chart] = _built(
            [_chart(_series(days, [1] * 5, id="a"), _series(days, [1] * 5, id="b", source="gaia"))]
        )

        assert [s["logo"] for s in chart["series"]] == ["gmail", None]


@pytest.mark.unit
class TestDataBlocks:
    def test_progress_counts_done_of_every_linked_todo(self) -> None:
        goal = {"id": "g", "statement": "Hire eight", "origin": "memory", "done": 5, "open": 3}

        [block] = _built([{"kind": "progress", "goal": goal}])

        assert block == {"kind": "progress", "statement": "Hire eight", "done": 5, "total": 8}

    def test_a_quote_keeps_its_author_and_app(self) -> None:
        quote = {
            "id": "q",
            "text": "Hold it.",
            "author": "Dana",
            "source": "gmail",
            "app": "Gmail",
            "item_id": 1,
        }

        [block] = _built([{"kind": "quote", "quote": quote}])

        assert block == {
            "kind": "quote",
            "text": "Hold it.",
            "author": "Dana",
            "app": "Gmail",
            "logo": "gmail",
        }


@pytest.mark.unit
def test_the_calendar_spans_the_days_timed_starts_beyond_the_rows_it_shows() -> None:
    events = [
        {"date": "2026-11-10", "start": None, "title": "Offsite"},
        *({"date": "2026-11-10", "start": t, "title": t} for t in ("09:30", "11:00", "15:30")),
    ]

    [block] = _built([], calendar=events)

    assert len(block["events"]) == EDITION_ROWS_SHOWN
    assert (block["first"], block["last"]) == ("09:30", "15:30")


@pytest.mark.unit
def test_an_app_the_brief_read_carries_its_mark_and_one_without_a_registered_mark_none() -> None:
    assert read_sources(["GitHub", "Google Calendar", "Stripe"]) == [
        {"name": "GitHub", "logo": "github"},
        {"name": "Google Calendar", "logo": "googlecalendar"},
        {"name": "Stripe", "logo": None},
    ]


@pytest.mark.unit
class TestEveryFieldABlockPrints:
    def test_a_placed_item_says_its_title_detail_app_and_mark(self) -> None:
        item = make_brief_item(
            "Priya", "you", action=BriefAction.REPLY, source="slack", app="Slack", detail="in #ops"
        )

        [block] = _built(
            [{"kind": "items", "section": 0}],
            sections=[{"numeral": "I", "title": "Today", "items": [item]}],
        )

        assert block["items"] == [
            {
                "verb": "Reply",
                "outcome": None,
                "title": "Priya",
                "detail": "in #ops",
                "logo": "slack",
                "app": "Slack",
            }
        ]

    def test_a_calendar_row_says_its_time_title_place_and_mark(self) -> None:
        [block] = _built(
            [],
            calendar=[
                {"date": "2026-11-10", "start": "09:30", "title": "Standup", "location": "Room 4"},
                {"date": "2026-11-10", "start": "10:00", "title": "Sync", "location": ""},
            ],
        )

        assert block["events"] == [
            {
                "t12": "9:30 AM",
                "t24": "09:30",
                "day": None,
                "title": "Standup",
                "detail": "Room 4",
                "logo": "googlecalendar",
            },
            {
                "t12": "10:00 AM",
                "t24": "10:00",
                "day": None,
                "title": "Sync",
                "detail": None,
                "logo": "googlecalendar",
            },
        ]

    def test_a_chart_series_says_its_name_app_mark_unit_values_and_total(self) -> None:
        series = _series(_days(5, 3), [2, 1.5, 0], label="Emails received")

        [block] = _built([_chart(series)])

        assert block["series"] == [
            {
                "name": "Emails received",
                "app": "Gmail",
                "logo": "gmail",
                "unit": "emails",
                "values": [2, 1.5, 0],
                "shown": ["2", "1.5", "0"],
                "total": "3.5",
            }
        ]


@pytest.mark.unit
class TestWholeBlocks:
    def test_a_chart_block_is_its_kind_chart_title_takeaway_and_the_rest(self) -> None:
        [block] = _built([_chart(_series(_days(5, 3), [1, 2, 3]), kind="bar")])

        assert (block["kind"], block["chart"], block["title"], block["takeaway"]) == (
            "chart",
            "bar",
            "Mail",
            "Up.",
        )

    def test_a_group_says_its_numeral_and_heading_and_zero_more_when_it_fits(self) -> None:
        items = [make_brief_item(f"Thing {n}", "you", action=BriefAction.READ) for n in range(3)]

        [block] = _built(
            [{"kind": "items", "section": 0}],
            sections=[{"numeral": "II", "title": "Worth a look", "items": items}],
        )

        assert (block["numeral"], block["heading"], block["more"]) == ("II", "Worth a look", 0)

    def test_a_note_is_its_text(self) -> None:
        assert _built([{"kind": "note", "text": "A light afternoon."}]) == [
            {"kind": "note", "text": "A light afternoon."}
        ]

    def test_a_section_block_is_not_a_data_block(self) -> None:
        with pytest.raises(ValueError, match="^a lead block is drawn from its section$"):
            _data_block(SectionBlock(kind="lead", section=0))

    def test_a_calendar_counts_the_events_beyond_its_rows_and_none_when_all_show(self) -> None:
        many = [
            {"date": "2026-11-10", "start": f"{h:02d}:00", "title": f"E{h}"}
            for h in range(9, 9 + EDITION_ROWS_SHOWN + 2)
        ]
        few = many[:EDITION_ROWS_SHOWN]

        [crowded] = _built([], calendar=many)
        [roomy] = _built([], calendar=few)

        assert (crowded["more"], roomy["more"]) == (2, 0)
