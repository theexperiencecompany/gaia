"""What a sentence about one fact may claim of it: the fact's own state and its own figures."""

import pytest

from app.constants.todos import TodoCompleter
from app.models.brief_item_models import ItemState
from app.services.briefing.claims import claim_problems, points_back
from app.services.briefing.slots import BriefFact, SlotValues

pytestmark = pytest.mark.unit

_FAILED_SAID_DONE = (
    "the message says fact 1 'done', but its state is failed; say where it stands as its line does"
)
_VALUES = SlotValues(
    facts={
        1: BriefFact(title="Stripe payout", kind=ItemState.FAILED),
        2: BriefFact(title="Board call", time="3:00 PM"),
    },
    counts={},
)


class TestAStateTheFactDoesNotHold:
    def test_a_failed_item_called_done_is_named(self) -> None:
        assert claim_problems("message", "[The payout](fact:1) is done.", _VALUES) == [
            _FAILED_SAID_DONE
        ]

    def test_a_state_word_the_facts_own_question_asks_may_be_said(self) -> None:
        """Dhruv replay 11-05 and 11-08: quoting "have you completed" sent the brief plain."""
        values = SlotValues(
            facts={
                4: BriefFact(
                    title="PostHog OAuth test",
                    kind=ItemState.YOU,
                    words="Have you completed one of the Infisical access options?",
                )
            },
            counts={},
        )
        written = "I need to know whether you completed an Infisical option: [review it](fact:4)."

        assert claim_problems("message", written, values) == []

    def test_the_facts_own_word_is_quoted_whatever_its_case(self) -> None:
        values = SlotValues(
            facts={
                4: BriefFact(title="Deploy", kind=ItemState.YOU, words="Is it Done on staging?")
            },
            counts={},
        )

        assert claim_problems("message", "Is [the deploy](fact:4) done on staging?", values) == []

    def test_a_problem_in_one_sentence_stays_named_after_a_clean_one(self) -> None:
        text = "[The payout](fact:1) is done. Nothing else today."

        assert claim_problems("message", text, _VALUES) == [_FAILED_SAID_DONE]

    def test_a_sentence_that_negates_may_say_it_is_not_done(self) -> None:
        assert claim_problems("message", "[The payout](fact:1) is not done.", _VALUES) == []

    @pytest.mark.parametrize(
        "before",
        [
            "Nothing else today.",
            "[The payout](fact:1) and [[fact:2]] both wait.",
            "[Another](fact:9) is done.",
        ],
        ids=["about-no-fact", "about-two-facts", "about-an-unknown-fact"],
    )
    def test_a_sentence_not_held_to_one_known_fact_never_hides_the_next(self, before: str) -> None:
        text = f"{before} [The payout](fact:1) is done."

        assert claim_problems("message", text, _VALUES) == [_FAILED_SAID_DONE]


class TestAFigureOfAnotherFact:
    def test_another_facts_time_is_named(self) -> None:
        assert claim_problems("message", "[The payout](fact:1) lands at 3:00 PM.", _VALUES) == [
            "the message says '3:00' of fact 1, but that is another fact's, not fact 1's; "
            "say only what its own line holds"
        ]

    def test_a_facts_own_count_may_be_said_though_another_fact_holds_that_figure(self) -> None:
        values = SlotValues(
            facts={
                1: BriefFact(title="Reply to Maya", count=3, kind=ItemState.YOU),
                2: BriefFact(title="3 invoices"),
            },
            counts={},
        )

        assert claim_problems("message", "[Maya](fact:1) wrote 3 times.", values) == []

    @pytest.mark.parametrize(
        ("own", "written"),
        [
            (BriefFact(title="Invoice 42"), "[[fact:1]] for invoice 42 is ready."),
            (BriefFact(title="Board call", time="4:30 PM"), "[[fact:1]] starts at 4:30 PM."),
            (BriefFact(title="Reply to Maya", count=5), "[[fact:1]] holds 5 asks."),
        ],
        ids=["its-title", "its-time", "its-count"],
    )
    def test_a_facts_own_figure_may_be_said_though_another_facts_line_says_it_too(
        self, own: BriefFact, written: str
    ) -> None:
        other = BriefFact(title="Seats", time="4:30 PM", words="42 seats, 5 left")
        values = SlotValues(facts={1: own, 2: other}, counts={})

        assert claim_problems("message", written, values) == []

    def test_a_figure_that_names_another_fact_by_its_title_is_not_pinned_on_the_slotted_one(
        self,
    ) -> None:
        """Replay (Dhruv 11-14): naming "Mercury 2FA setup" beside fact 6's due time was rejected."""
        values = SlotValues(
            facts={
                6: BriefFact(
                    title="Investigate PostHog event-budget loop alert", time="Fri Nov 13"
                ),
                9: BriefFact(title="Verify Mercury 2FA setup in Surat", time="Fri Nov 13"),
            },
            counts={},
        )
        text = (
            "The PostHog event-budget alert was due [[fact:6.time]], and the Mercury 2FA setup "
            "in Surat was due then too."
        )

        assert claim_problems("message", text, values) == []


class TestAnotherAppsItemCalledAGaiaTodo:
    _VALUES = SlotValues(
        facts={
            1: BriefFact(title="Sankalp's voice latency numbers", app="Todoist"),
            2: BriefFact(title="Dentist appointment", app="GAIA"),
        },
        counts={},
    )

    def test_another_apps_item_called_a_gaia_todo_is_named(self) -> None:
        """Sim 11-25: "Your GAIA todo, Sankalp's voice latency numbers, is past due." (a Todoist task)."""
        written = "Your GAIA todo, [[fact:1]], is past due."

        assert claim_problems("message", written, self._VALUES) == [
            "the message calls fact 1 a GAIA todo, but it is a Todoist item; name its app as "
            "its line does"
        ]

    def test_a_gaia_todo_called_one_may_be_said(self) -> None:
        assert claim_problems("message", "Your GAIA todo, [[fact:2]], is due.", self._VALUES) == []


class TestCreditForFinishedWork:
    _VALUES = SlotValues(
        facts={
            1: BriefFact(
                title="Voice release changelog",
                kind=ItemState.LOOKBACK,
                done_by=TodoCompleter.USER,
            ),
            2: BriefFact(
                title="Kavya's offer letter review",
                kind=ItemState.LOOKBACK,
                done_by=TodoCompleter.USER,
            ),
            3: BriefFact(
                title="Competitor pricing research",
                kind=ItemState.LOOKBACK,
                done_by=TodoCompleter.GAIA,
            ),
        },
        counts={},
    )

    def test_the_users_work_credited_to_gaia_in_words_is_named(self) -> None:
        """Sim 12-06 weekly: GAIA said "I finished" of two todos the user finished."""
        written = (
            "I finished two tasks this week: the voice release changelog and "
            "Kavya\u2019s offer letter review."
        )

        assert claim_problems("message", written, self._VALUES) == [
            "the message credits GAIA with facts 1, 2, but the user finished them; "
            "say they finished them, as their lines do"
        ]

    def test_the_users_work_credited_to_gaia_by_its_slot_is_named(self) -> None:
        assert claim_problems("message", "I've completed [[fact:1]].", self._VALUES) == [
            "the message credits GAIA with facts 1, but the user finished them; "
            "say they finished them, as their lines do"
        ]

    def test_a_curly_apostrophe_credit_is_read_as_the_plain_one(self) -> None:
        assert claim_problems("message", "I\u2019ve completed [[fact:1]].", self._VALUES) == [
            "the message credits GAIA with facts 1, but the user finished them; "
            "say they finished them, as their lines do"
        ]

    def test_gaias_work_credited_to_the_user_is_named(self) -> None:
        assert claim_problems("message", "You finished [[fact:3]].", self._VALUES) == [
            "the message credits the user with facts 3, but GAIA finished them; "
            "say GAIA finished them, as their lines do"
        ]

    @pytest.mark.parametrize(
        "written",
        [
            "You finished [[fact:1]] and [[fact:2]].",
            "I finished [[fact:3]].",
            "I finished [[fact:3]] and you finished [[fact:1]].",
        ],
        ids=["user-by-user", "gaia-by-gaia", "each-by-its-own"],
    )
    def test_work_credited_to_whoever_finished_it_may_be_said(self, written: str) -> None:
        assert claim_problems("message", written, self._VALUES) == []


class TestPointsBack:
    """A sentence that names no fact and opens on "that" or "it" speaks of the last one's."""

    @pytest.mark.parametrize(
        "text",
        ["That's the one to do first.", "It has sat there for weeks."],
        ids=["that", "it"],
    )
    def test_a_sentence_opening_on_a_pointing_word_and_naming_no_fact_points_back(
        self, text: str
    ) -> None:
        assert points_back(text, _VALUES) is True

    @pytest.mark.parametrize(
        "text",
        [
            "That [payout](fact:1) failed.",
            "That Stripe payout failed.",
            "That payout from Stripe failed.",
            "The day is clear.",
        ],
        ids=["by-slot", "by-title", "by-its-words", "no-pointing-word"],
    )
    def test_a_sentence_naming_a_fact_or_opening_elsewhere_does_not(self, text: str) -> None:
        assert points_back(text, _VALUES) is False

    @pytest.mark.parametrize(
        ("title", "named"),
        [("QA on Stripe", False), ("Pay tax", True)],
        ids=["two-letter-words-do-not-count", "three-letter-words-count"],
    )
    def test_a_title_is_named_by_its_words_of_three_letters_or_more(
        self, title: str, named: bool
    ) -> None:
        values = SlotValues(facts={1: BriefFact(title=title)}, counts={})

        assert points_back("That tax to pay and the QA.", values) is not named

    def test_stopwords_never_name_a_fact(self) -> None:
        values = SlotValues(facts={1: BriefFact(title="Reply to the investor")}, counts={})

        assert points_back("That one is for the investor.", values) is True
