"""The brief's slots are filled from the facts, and a slot the facts cannot fill is named."""

import pytest

from app.models.brief_pool_models import DataSeries, SeriesPoint, SeriesShape
from app.services.briefing.slots import (
    BriefFact,
    CountSlot,
    SeriesField,
    SlotError,
    SlotValues,
    referenced_facts,
    render_slots,
    series_figures,
    slot_problems,
)

pytestmark = pytest.mark.unit

_VALUES = SlotValues(
    facts={
        3: BriefFact(title="Approve the Acme MSA renewal", count=3),
        7: BriefFact(title="Q4 board deck"),
        9: BriefFact(title="Sequoia partner meeting", time="11:00 AM"),
    },
    counts={CountSlot.NEEDS_YOU: 2, CountSlot.EVENTS: 1},
)
_DECK = "https://heygaia.link/deck"
_OFFERED = "(offered: needs_you, events)"


class TestRendering:
    def test_every_slot_is_filled_from_the_facts(self) -> None:
        written = (
            "[[count:needs_you]] things need you: [[fact:3]] ([[fact:3.count]] requests). "
            "Then [[fact:9]] at [[fact:9.time]], and the [deck](fact:7) is ready."
        )

        assert render_slots(written, _VALUES, {7: _DECK}) == (
            "2 things need you: Approve the Acme MSA renewal (3 requests). "
            f"Then Sequoia partner meeting at 11:00 AM, and the [deck]({_DECK}) is ready."
        )

    def test_the_check_sees_each_filled_value_bracketed_and_each_phrase_as_written(self) -> None:
        written = "[[count:needs_you]] need you, then [[fact:9]] at [[fact:9.time]] and the [deck](fact:7)"

        assert render_slots(written, _VALUES, {7: _DECK}, mark_filled=True) == (
            f"⟦2⟧ need you, then ⟦Sequoia partner meeting⟧ at ⟦11:00 AM⟧ and the [deck]({_DECK})"
        )

    def test_a_fact_is_linked_once_however_often_its_phrase_is_written(self) -> None:
        written = "the [deck](fact:7) is done, [open it](fact:7)"

        assert render_slots(written, _VALUES, {7: _DECK}) == f"the [deck]({_DECK}) is done, open it"

    def test_a_phrase_on_a_fact_with_no_address_stays_text(self) -> None:
        assert render_slots("the [deck](fact:7) and [the MSA](fact:3)", _VALUES, {}) == (
            "the deck and the MSA"
        )

    def test_a_title_holding_a_slot_shape_is_not_filled_again(self) -> None:
        values = SlotValues(facts={1: BriefFact(title="Read [[fact:1]]")}, counts={})

        assert render_slots("[[fact:1]]", values, {}) == "Read [[fact:1]]"

    @pytest.mark.parametrize(
        "written",
        ["[[count:done]]", "[[fact:4]]", "[[fact:3.time]]", "[[fact:9.count]]", "[x](fact:12)"],
    )
    def test_a_slot_the_facts_cannot_fill_raises(self, written: str) -> None:
        with pytest.raises(SlotError):
            render_slots(written, _VALUES, {})

    def test_the_facts_a_text_speaks_of_are_every_fact_a_slot_names(self) -> None:
        written = "[[fact:3]], at [[fact:9.time]], the [deck](fact:7), [[count:needs_you]]"

        assert referenced_facts(written) == {3, 7, 9}


class TestProblems:
    def test_well_formed_prose_has_none(self) -> None:
        written = "[[count:events]] meeting today: [[fact:9]] at [[fact:9.time]]."

        assert slot_problems("message", written, _VALUES) == []

    @pytest.mark.parametrize(
        "written", ["Sequoia at 12:30", "you have 9 approvals", "the [Q5 deck](fact:7)"]
    )
    def test_a_figure_no_fact_carries_is_named(self, written: str) -> None:
        [problem] = slot_problems("lede", written, _VALUES)

        assert problem.startswith("the lede types ")
        assert problem.endswith(
            "a figure no fact carries; say it in words, from the facts, or leave it out"
        )

    def test_a_figure_as_it_stands_in_a_title_may_be_typed(self) -> None:
        assert slot_problems("message", "the (Q4) deck, then the [Q4 deck](fact:7).", _VALUES) == []

    def test_a_typed_web_address_is_named(self) -> None:
        problems = slot_problems("message", "open https://linear.app/acme now", _VALUES)

        assert problems == [
            "the message writes the address 'https://linear.app/acme'; link a phrase with (fact:N)"
        ]

    def test_a_figure_inside_a_slot_is_not_typed_by_the_model(self) -> None:
        assert slot_problems("message", "[[fact:7]] at [[fact:9.time]]", _VALUES) == []


_WEEK = [f"2026-11-{d:02d}" for d in range(5, 12)]
_MEETINGS = DataSeries(
    id="calendar_meeting_hours",
    label="Meeting hours",
    unit="hours",
    source="googlecalendar",
    app="Google Calendar",
    shape=SeriesShape.TIME_SERIES,
    points=[SeriesPoint(x=x, y=y) for x, y in zip(_WEEK, [2, 1.5, 2, 0, 0, 2.5, 7], strict=True)],
)
_MAIL = DataSeries(
    id="gmail_sorted",
    label="Mail sorted since yesterday",
    unit="emails",
    source="gmail",
    app="Gmail",
    shape=SeriesShape.CATEGORICAL,
    points=[SeriesPoint(x="Needs a reply", y=9), SeriesPoint(x="Junk", y=22)],
)


class TestSeriesSlots:
    def test_a_time_series_renders_its_total_latest_peak_its_day_and_low(self) -> None:
        assert series_figures(_MEETINGS) == {
            SeriesField.TOTAL: "15",
            SeriesField.PEAK: "7",
            SeriesField.PEAK_AT: "Wednesday",
            SeriesField.LOW: "0",
            SeriesField.LATEST: "7",
        }

    def test_a_categorical_series_peaks_at_a_category_and_has_no_latest(self) -> None:
        figures = series_figures(_MAIL)

        assert (figures[SeriesField.PEAK_AT], figures[SeriesField.TOTAL]) == ("Junk", "31")
        assert SeriesField.LATEST not in figures

    def test_a_series_slot_is_filled_from_its_figures(self) -> None:
        values = SlotValues(
            facts={}, counts={}, series={s.id: series_figures(s) for s in (_MEETINGS, _MAIL)}
        )
        written = (
            "[[series:calendar_meeting_hours.peak_at]] holds [[series:calendar_meeting_hours.peak]]"
            " hours; [[series:gmail_sorted.peak]] emails were [[series:gmail_sorted.peak_at]]."
        )

        assert slot_problems("takeaway", written, values) == []
        assert render_slots(written, values, {}) == (
            "Wednesday holds 7 hours; 22 emails were Junk."
        )

    @pytest.mark.parametrize(
        "written",
        [
            "[[series:gmail_sorted]] emails",
            "[[series:gmail_sorted.latest]] emails",
            "[[series:nobody.total]] emails",
        ],
    )
    def test_a_series_slot_without_a_figure_the_series_offers_raises(self, written: str) -> None:
        values = SlotValues(facts={}, counts={}, series={"gmail_sorted": series_figures(_MAIL)})

        with pytest.raises(SlotError):
            render_slots(written, values, {})
        assert slot_problems("note", written, values)

    def test_a_half_slot_on_a_series_is_malformed(self) -> None:
        values = SlotValues(facts={}, counts={}, series={"gmail_sorted": series_figures(_MAIL)})

        [problem] = slot_problems("note", "[[series:gmail_sorted.peak]", values)

        assert "malformed slot" in problem


class TestATypedFigureNamesItsSlot:
    def test_a_typed_time_names_the_time_slot(self) -> None:
        """E2E busy day: "10:00" came back typed; the retry was only told to use a slot."""
        assert slot_problems("message", "Sequoia at 11:00.", _VALUES) == [
            "the message types '11:00' itself; write [[fact:9.time]] where it says 11:00"
        ]

    @pytest.mark.parametrize(
        "written", ["You have 2 asks today.", "The renewal stands for 3 requests."]
    )
    def test_a_count_a_slot_renders_stands_as_typed(self, written: str) -> None:
        """E2E busy day: "3" and "4" were refused on both attempts, true counts its slots render."""
        assert slot_problems("message", written, _VALUES) == []

    def test_a_series_figure_stands_as_typed_and_another_figure_does_not(self) -> None:
        values = SlotValues(
            facts={}, counts={}, series={"calendar_meeting_hours": series_figures(_MEETINGS)}
        )

        assert slot_problems("caption", "Today holds 7 hours of meetings.", values) == []
        assert slot_problems("caption", "Today holds 8 hours.", values) == [
            "the caption types '8', a figure no fact carries; say it in words, from the facts, "
            "or leave it out"
        ]

    def test_a_figure_quoted_from_the_facts_own_words_may_be_typed(self) -> None:
        """Live brief: the lede quoted Maya's "1x non-participating" preference and was refused."""
        values = SlotValues(facts={}, counts={}, quoted=frozenset({"1x"}))

        assert slot_problems("lede", "Maya wants the 1x preference confirmed.", values) == []
        assert slot_problems("lede", "Maya wants the 2x preference.", values) != []
