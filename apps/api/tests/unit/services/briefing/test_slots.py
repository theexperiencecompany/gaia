"""The brief's slots are filled from the facts, and a slot the facts cannot fill is named."""

import pytest

from app.services.briefing.slots import (
    BriefFact,
    CountSlot,
    SlotError,
    SlotValues,
    referenced_facts,
    render_slots,
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
        ("written", "problem"),
        [
            ("[[count:done]] done", f"[[count:done]] is not a count the facts list {_OFFERED}"),
            ("[[count:weeks]]", f"[[count:weeks]] is not a count the facts list {_OFFERED}"),
            ("[[count:events.time]]", "[[count:events.time]]: a count slot has no field"),
            ("[[fact:4]] is ready", "fact:4 is no fact shown today"),
            ("[[fact:deck]] is ready", "fact:deck is no fact shown today"),
            ("at [[fact:3.time]]", "[[fact:3.time]]: fact 3 has no time"),
            ("[[fact:9.count]] of them", "[[fact:9.count]]: fact 9 has no count"),
            (
                "[[fact:9.people]]",
                "[[fact:9.people]]: a fact slot is [[fact:N]], [[fact:N.time]] or [[fact:N.count]]",
            ),
            ("the [deck](fact:12)", "fact:12 is no fact shown today"),
        ],
    )
    def test_a_slot_naming_nothing_shown_is_named(self, written: str, problem: str) -> None:
        assert slot_problems("message", written, _VALUES) == [f"the message: {problem}"]

    @pytest.mark.parametrize(
        "written",
        [
            "[the deck|[[fact:7]]]",
            "[[fact:7|the deck]]",
            "[the deck] (fact:7)",
            "[[fact: 7]]",
            "see fact:7",
        ],
    )
    def test_a_mangled_slot_is_named_as_malformed(self, written: str) -> None:
        problems = slot_problems("message", written, _VALUES)

        assert any("has a malformed slot" in problem for problem in problems), problems

    @pytest.mark.parametrize(
        ("written", "typed"),
        [
            ("Sequoia at 11:00", "'11:00'"),
            ("you have 3 approvals", "'3'"),
            ("the [Q5 deck](fact:7)", "'Q5'"),
        ],
    )
    def test_a_figure_typed_outside_a_slot_is_named(self, written: str, typed: str) -> None:
        assert slot_problems("lede", written, _VALUES) == [
            f"the lede types {typed} itself; every count, time and date is a slot, "
            "and any other figure is said in words"
        ]

    def test_a_figure_as_it_stands_in_a_title_may_be_typed(self) -> None:
        assert slot_problems("message", "the (Q4) deck, then the [Q4 deck](fact:7).", _VALUES) == []

    def test_a_typed_web_address_is_named(self) -> None:
        problems = slot_problems("message", "open https://linear.app/acme now", _VALUES)

        assert problems == [
            "the message writes the address 'https://linear.app/acme'; link a phrase with (fact:N)"
        ]

    def test_a_figure_inside_a_slot_is_not_typed_by_the_model(self) -> None:
        assert slot_problems("message", "[[fact:7]] at [[fact:9.time]]", _VALUES) == []
