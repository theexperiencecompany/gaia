"""The brief's slots are filled from the facts, and a slot the facts cannot fill is named."""

from datetime import UTC, date, datetime

import pytest
from tests.briefing_helpers import user_clock

from app.constants.todos import TodoCompleter
from app.models.brief_candidate_models import BriefCandidate, CandidateOrigin
from app.models.brief_item_models import ItemState
from app.models.brief_pool_models import DataSeries, SeriesPoint, SeriesShape
from app.models.brief_slot_models import CountName, SeriesField
from app.services.briefing.slots import (
    BriefFact,
    SlotError,
    SlotValues,
    candidate_fact,
    figures_in,
    referenced_facts,
    render_slots,
    series_figures,
    slot_problems,
    unslotted,
)

pytestmark = pytest.mark.unit

_VALUES = SlotValues(
    facts={
        3: BriefFact(title="Approve the Acme MSA renewal", count=3),
        7: BriefFact(title="Q4 board deck"),
        9: BriefFact(title="Sequoia partner meeting", time="11:00 AM"),
    },
    counts={CountName.NEEDS_YOU: 2, CountName.EVENTS: 1},
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

    def test_a_fact_is_linked_once_however_often_its_phrase_is_written(self) -> None:
        written = "the [deck](fact:7) is done, [open it](fact:7)"

        assert render_slots(written, _VALUES, {7: _DECK}) == f"the [deck]({_DECK}) is done, open it"

    def test_a_phrase_on_a_fact_with_no_address_stays_text(self) -> None:
        assert render_slots("the [deck](fact:7) and [the MSA](fact:3)", _VALUES, {}) == (
            "the deck and the MSA"
        )

    @pytest.mark.parametrize(
        ("written", "rendered"),
        [
            ("were due [[fact:1.time]] and [[fact:2.time]].", "were due Fri Nov 13."),
            (
                "due [[fact:1.time]], [[fact:2.time]] and [[fact:3.time]], respectively.",
                "due Fri Nov 13.",
            ),
            ("both due [[fact:1.time]] / [[fact:2.time]].", "both due Fri Nov 13."),
            ("due [[fact:1.time]] and [[fact:4.time]].", "due Fri Nov 13 and Sat Nov 14."),
            ("due [[fact:1.time]], respectively.", "due Fri Nov 13, respectively."),
        ],
        ids=["two alike", "three alike, respectively", "two alike, slashed", "different", "one"],
    )
    def test_a_list_of_slots_that_render_alike_says_the_value_once(
        self, written: str, rendered: str
    ) -> None:
        """Replay of Dhruv's Nov 14: "were due Fri Nov 13 and Fri Nov 13"."""
        values = SlotValues(
            facts={
                n: BriefFact(title=f"Task {n}", time="Sat Nov 14" if n == 4 else "Fri Nov 13")
                for n in range(1, 5)
            },
            counts={},
        )

        assert render_slots(written, values, {}) == rendered

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

    def test_a_fact_standing_for_two_requests_voices_its_count(self) -> None:
        values = SlotValues(facts={4: BriefFact(title="Reply to Dan", count=2)}, counts={})

        assert render_slots("[[fact:4]] x[[fact:4.count]]", values, {}) == "Reply to Dan x2"

    def test_the_facts_a_text_speaks_of_are_every_fact_a_slot_names(self) -> None:
        written = "[[fact:3]], at [[fact:9.time]], the [deck](fact:7), [[count:needs_you]]"

        assert referenced_facts(written) == {3, 7, 9}


class TestProblems:
    @pytest.mark.parametrize(
        ("written", "problem"),
        [
            ("[[count:needs_you.total]]", "[[count:needs_you.total]]: a count slot has no field"),
            (
                "[[count:done]]",
                "[[count:done]] is not a count the facts list (offered: needs_you, events)",
            ),
            ("[[fact:7.time]]", "[[fact:7.time]]: fact 7 has no time"),
            ("[[fact:7.count]]", "[[fact:7.count]]: fact 7 has no count"),
            (
                "[[fact:7.when]]",
                "[[fact:7.when]]: a fact slot is [[fact:N]], [[fact:N.time]] or [[fact:N.count]]",
            ),
        ],
        ids=["count-with-field", "count-not-offered", "no-time", "no-count", "unknown-field"],
    )
    def test_a_slot_the_facts_cannot_fill_is_named_exactly(
        self, written: str, problem: str
    ) -> None:
        assert slot_problems("lede", f"Then {written}.", _VALUES) == [f"the lede: {problem}"]

    def test_a_figure_typed_from_a_series_value_names_the_series_slot_that_writes_it(
        self,
    ) -> None:
        values = SlotValues(
            facts={},
            counts={},
            series={"hours": {SeriesField.PEAK_AT: "9:00", SeriesField.PEAK: "4"}},
        )

        assert slot_problems("lede", "Busiest at 9 sharp.", values) == [
            "the lede types '9' itself; write [[series:hours.peak_at]] where it says 9, "
            "with nothing of '9:00' beside it"
        ]

    def test_a_title_said_in_words_beside_its_slot_is_named_by_its_field(self) -> None:
        assert slot_problems("lede", "The Q4 board deck is ready: [[fact:7]].", _VALUES) == [
            "the lede names 'Q4 board deck' in words and again with [[fact:7]]; keep one"
        ]

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

    def test_a_day_with_no_counts_says_none_were_offered(self) -> None:
        values = SlotValues(facts={}, counts={CountName.DONE: 0})

        assert slot_problems("message", "[[count:done]] done", values) == [
            "the message: [[count:done]] is not a count the facts list (offered: none today)"
        ]

    def test_a_malformed_slot_is_named_with_the_shapes_that_work(self) -> None:
        assert slot_problems("message", "see fact:7", _VALUES) == [
            "the message has a malformed slot 'fact:7'; write [[count:name]], [[fact:N]], "
            "[[fact:N.time]], [[fact:N.count]], [[series:ID.field]] or [the phrase](fact:N) exactly"
        ]

    def test_a_figure_glued_to_a_slot_is_named_as_typed_without_the_slot(self) -> None:
        assert slot_problems("message", "[[count:events]]x2", _VALUES) == [
            "the message types 'x2', a figure no fact carries; say it in words, from the "
            "facts, or leave it out"
        ]

    def test_every_typed_figure_is_listed(self) -> None:
        assert slot_problems("message", "8 then 4", _VALUES) == [
            "the message types '8', a figure no fact carries; say it in words, from the "
            "facts, or leave it out",
            "the message types '4', a figure no fact carries; say it in words, from the "
            "facts, or leave it out",
        ]

    def test_a_title_word_wrapped_in_punctuation_still_licenses_the_bare_figure(self) -> None:
        values = SlotValues(facts={1: BriefFact(title='Review the "(Q3)" plan')}, counts={})

        assert slot_problems("message", "the Q3 plan", values) == []

    def test_a_figure_as_it_stands_in_a_title_may_be_typed(self) -> None:
        assert slot_problems("message", "the (Q4) deck, then the [Q4 deck](fact:7).", _VALUES) == []

    def test_a_title_figure_said_in_the_plural_is_the_same_figure(self) -> None:
        """Replay: a weekly failed outright for writing "1:1s" about its 1:1 events."""
        values = SlotValues(facts={1: BriefFact(title="1:1 with Dana")}, counts={})

        assert slot_problems("message", "Three 1:1s, then a demo.", values) == []
        assert slot_problems("message", "Two 2:1s.", values) != []

    def test_a_typed_web_address_is_named(self) -> None:
        problems = slot_problems("message", "open https://linear.app/acme now", _VALUES)

        assert problems == [
            "the message writes the address 'https://linear.app/acme'; link a phrase with (fact:N)"
        ]

    def test_a_count_slot_names_no_fact(self) -> None:
        assert referenced_facts("[[count:12]] and [[fact:3]]") == {3}

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


class TestACountOfOneIsSaidInTheSingular:
    def test_a_plural_verb_after_a_count_that_renders_one_is_named(self) -> None:
        """Sim 11-25: "1 of your GAIA todos are overdue" went out."""
        written = "[[count:events]] of your meetings are moved."

        assert slot_problems("message", written, _VALUES) == [
            "the message says [[count:events]] (1) with 'are'; a count of one takes the "
            "singular: 'is'"
        ]

    @pytest.mark.parametrize(
        "written",
        [
            "[[count:needs_you]] of your asks are waiting.",
            "[[count:events]] meeting is moved.",
            "[[count:events]] meeting moved; the others are fine.",
        ],
    )
    def test_a_count_and_its_verb_that_agree_are_left_alone(self, written: str) -> None:
        assert slot_problems("message", written, _VALUES) == []


class TestADayIsNotSaidAsAClockTime:
    def test_at_before_a_time_slot_that_renders_a_due_day_is_named(self) -> None:
        """Sim 12-02: "so is your dentist appointment at today" went out."""
        due = datetime(2026, 11, 11, 12, 0, tzinfo=UTC)
        values = SlotValues(facts={5: candidate_fact(_candidate(due_at=due), _CLOCK)}, counts={})

        assert slot_problems("message", "[[fact:5]] is due, at [[fact:5.time]].", values) == [
            "the message says 'at' before [[fact:5.time]], which renders the day 'today'; "
            "a day takes no 'at': drop it"
        ]

    def test_at_before_a_time_slot_that_renders_a_clock_time_is_left_alone(self) -> None:
        candidate = _candidate(time="4:00 PM", due_at=datetime(2026, 11, 11, tzinfo=UTC))
        values = SlotValues(facts={5: candidate_fact(candidate, _CLOCK)}, counts={})

        assert slot_problems("message", "[[fact:5]] at [[fact:5.time]].", values) == []


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
    @pytest.mark.parametrize("typed", ["11:00", "11"])
    def test_a_typed_time_names_the_time_slot(self, typed: str) -> None:
        """E2E: "10:00" and "11 AM" came back typed; sim 12-01: the retry kept "AM" beside the slot."""
        assert slot_problems("message", f"Sequoia at {typed} AM.", _VALUES) == [
            f"the message types {typed!r} itself; write [[fact:9.time]] where it says {typed}, "
            "with nothing of '11:00 AM' beside it"
        ]

    def test_a_typed_date_names_the_due_slot_it_came_from(self) -> None:
        """Replay of Dhruv's 2026-11-14: "overdue from Fri Nov 13" was told no fact carries 13."""
        values = SlotValues(facts={4: BriefFact(title="Brex email", time="Fri Nov 13")}, counts={})

        assert slot_problems("message", "The Brex email is overdue from Fri Nov 13.", values) == [
            "the message types '13' itself; write [[fact:4.time]] where it says 13, "
            "with nothing of 'Fri Nov 13' beside it"
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


class TestATimeSlotIsNotWrittenAround:
    @pytest.mark.parametrize("meridiem", ["PM", "AM", "am", "p.m.", "A.M."])
    def test_a_meridiem_written_after_a_time_slot_is_named(self, meridiem: str) -> None:
        """Live brief: "[[fact:N.time]] PM" rendered "2:00 PM PM" and passed every check."""
        assert slot_problems("lede", f"Sequoia at [[fact:9.time]] {meridiem}.", _VALUES) == [
            f"the lede writes {meridiem!r} after [[fact:9.time]], which already renders "
            "'11:00 AM'; drop it"
        ]

    @pytest.mark.parametrize("echo", ["(11:00 AM)", "11:00 AM"])
    def test_the_figure_a_slot_renders_written_after_it_is_named_alone(self, echo: str) -> None:
        """Live: the voice copied the shown "[[fact:12.time]] (2:00 PM)" and was told to write the slot it had."""
        assert slot_problems("message", f"Sequoia at [[fact:9.time]] {echo}.", _VALUES) == [
            f"the message writes {echo!r} after [[fact:9.time]], which already renders "
            "'11:00 AM'; drop it"
        ]

    def test_a_count_a_slot_renders_written_after_it_is_named(self) -> None:
        assert slot_problems("lede", "[[count:needs_you]] (2) need you.", _VALUES) == [
            "the lede writes '(2)' after [[count:needs_you]], which already renders '2'; drop it"
        ]

    def test_words_after_a_time_slot_are_left_alone(self) -> None:
        assert slot_problems("lede", "Sequoia at [[fact:9.time]] and Amy at noon.", _VALUES) == []


class TestSeriesSlotProblems:
    def test_a_series_nobody_shows_is_named_with_its_slot(self) -> None:
        assert slot_problems("note", "[[series:nobody.total]] emails", _VALUES) == [
            "the note: [[series:nobody.total]]: nobody is no series shown today"
        ]

    def test_a_figure_the_series_does_not_offer_lists_the_ones_it_does(self) -> None:
        values = SlotValues(facts={}, counts={}, series={"gmail_sorted": series_figures(_MAIL)})

        assert slot_problems("note", "[[series:gmail_sorted.latest]]", values) == [
            "the note: [[series:gmail_sorted.latest]]: series gmail_sorted offers "
            "total, peak, peak_at, low, as [[series:gmail_sorted.field]]"
        ]


class TestTypedFigures:
    def test_a_request_count_of_two_stands_as_typed_and_a_single_request_does_not(self) -> None:
        twice = SlotValues(facts={1: BriefFact(title="Reply to Dan", count=2)}, counts={})
        once = SlotValues(facts={1: BriefFact(title="Reply to Dan", count=1)}, counts={})

        assert slot_problems("message", "2 asks wait", twice) == []
        assert slot_problems("message", "1 ask waits", once) == [
            "the message types '1', a figure no fact carries; say it in words, from the "
            "facts, or leave it out"
        ]

    def test_a_held_figure_hyphened_to_a_word_is_the_same_figure(self) -> None:
        """Replay of the weekly: "the 300-user goal" was refused, and the retry dropped the goal."""
        values = SlotValues(facts={}, counts={}, quoted=frozenset({"300"}))

        assert slot_problems("message", "The 300-user goal stalled.", values) == []
        assert slot_problems("message", "A 3-day sprint, 300-user goal.", values) == [
            "the message types '3-day', a figure no fact carries; say it in words, from the "
            "facts, or leave it out"
        ]

    def test_a_typed_figure_is_named_without_the_punctuation_around_it(self) -> None:
        assert slot_problems("message", "up by (8).", _VALUES) == [
            "the message types '8', a figure no fact carries; say it in words, from the "
            "facts, or leave it out"
        ]

    def test_a_time_two_facts_render_names_both_slots(self) -> None:
        values = SlotValues(
            facts={
                1: BriefFact(title="Sync", time="11:00 AM"),
                2: BriefFact(title="Lunch", time="11:00 AM"),
            },
            counts={},
        )

        assert slot_problems("message", "Meet at 11:00 sharp", values) == [
            "the message types '11:00' itself; write [[fact:1.time]] or [[fact:2.time]] where it "
            "says 11:00, with nothing of '11:00 AM' beside it"
        ]

    def test_a_figure_two_facts_render_differently_names_both_values(self) -> None:
        values = SlotValues(
            facts={
                1: BriefFact(title="Sync", time="11:00 AM"),
                2: BriefFact(title="Lunch", time="11:30 AM"),
            },
            counts={},
        )

        assert slot_problems("message", "Meet at 11 sharp", values) == [
            "the message types '11' itself; write [[fact:1.time]] or [[fact:2.time]] where it "
            "says 11, with nothing of '11:00 AM' or '11:30 AM' beside it"
        ]


class TestEchoes:
    def test_a_meridiem_after_a_24_hour_time_is_not_an_echo_of_it(self) -> None:
        values = SlotValues(facts={1: BriefFact(title="Sync", time="14:00")}, counts={})

        assert slot_problems("message", "Sync at [[fact:1.time]] PM", values) == []

    def test_an_unfillable_slot_does_not_hide_a_later_echo(self) -> None:
        assert slot_problems("message", "[[fact:99]] and [[fact:9.time]] 11:00 AM", _VALUES) == [
            "the message: fact:99 is no fact shown today",
            "the message writes '11:00 AM' after [[fact:9.time]], which already renders "
            "'11:00 AM'; drop it",
        ]


class TestUnslotted:
    def test_a_link_keeps_its_phrase_and_a_value_slot_leaves_nothing(self) -> None:
        typed = "Sign [the MSA](fact:3) before [[fact:9.time]] with [[count:needs_you]] left."

        assert unslotted(typed) == "Sign the MSA before  with  left."


class TestFiguresIn:
    def test_each_word_with_a_digit_is_kept_without_the_punctuation_around_it(self) -> None:
        assert figures_in(["up by (8).", "the Q3 plan,", "no figures here"]) == {"8", "Q3"}


_CLOCK = user_clock("Asia/Kolkata", date(2026, 11, 11))


def _candidate(**fields: object) -> BriefCandidate:
    return BriefCandidate.model_validate(
        {"origin": CandidateOrigin.TRACKED, "source": "gaia", "app": "GAIA", "state": "you"}
        | {"title": "Approve the Acme MSA renewal"}
        | fields
    )


class TestAPoolItemsFact:
    def test_it_is_its_title_its_due_day_on_the_users_clock_and_its_count(self) -> None:
        due = datetime(2026, 11, 12, 20, 0, tzinfo=UTC)  # Friday 01:30 in Kolkata

        fact = candidate_fact(_candidate(due_at=due, count=3), _CLOCK)

        assert fact == BriefFact(
            title="Approve the Acme MSA renewal",
            time="Fri Nov 13",
            time_is_day=True,
            count=3,
            app="GAIA",
        )

    def test_it_carries_who_finished_a_done_item(self) -> None:
        candidate = _candidate(state="lookback", finished_by=TodoCompleter.USER)

        assert candidate_fact(candidate, _CLOCK).done_by is TodoCompleter.USER

    def test_a_time_of_its_own_beats_its_due_day(self) -> None:
        candidate = _candidate(time="4:00 PM", due_at=datetime(2026, 11, 11, tzinfo=UTC))

        assert candidate_fact(candidate, _CLOCK).time == "4:00 PM"

    def test_the_briefs_own_wording_its_state_and_its_words_ride_along(self) -> None:
        fact = candidate_fact(
            _candidate(), _CLOCK, title="Acme renewal", kind=ItemState.YOU, words="by Friday"
        )

        assert (fact.title, fact.time, fact.kind, fact.words) == (
            "Acme renewal",
            None,
            ItemState.YOU,
            "by Friday",
        )

    def test_it_says_whether_it_is_linked_goal_work(self) -> None:
        assert candidate_fact(_candidate(), _CLOCK, goal_work=True).goal_work is True
