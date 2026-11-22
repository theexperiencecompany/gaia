"""What a sentence about one fact may claim of it: the fact's own state and its own figures."""

import pytest

from app.constants.todos import TodoCompleter
from app.models.brief_item_models import ItemState
from app.services.briefing.claims import claim_problems, duration_problems, goal_problems
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


_FOUNDER = SlotValues(
    facts={
        1: BriefFact(title="YC founders outreach sequence", kind=ItemState.YOU),
        2: BriefFact(title="Emails to churned subscribers", kind=ItemState.YOU, goal_work=True),
        3: BriefFact(
            title="Blueprint-grid site redesign", kind=ItemState.YOU, words="updated 4 days ago"
        ),
    },
    counts={},
)


class TestAGoalClaimInOtherWords:
    """Founder's Nov 22: "That's the one that feeds the 300-user goal" of a sequence no goal links."""

    def test_a_sentence_that_points_back_is_held_to_the_last_ones_facts(self) -> None:
        text = "[The sequence](fact:1) waits on you. That's the one that feeds the 300-user goal."

        assert goal_problems("message", text, _FOUNDER) == [
            "the message ties facts 1 to a goal, but they are not linked to one; only a goal's "
            "linked todos are its work, so name them in a sentence that does not speak of the goal"
        ]

    def test_a_goal_word_in_the_named_facts_own_title_is_no_goal_claim(self) -> None:
        """Dhruv replay 11-02 and weekly 11-08: "the daily-goals check-in is in progress" went plain."""
        values = SlotValues(facts={10: BriefFact(title="Daily-goals check-in")}, counts={})
        text = "Meanwhile, the nightly daily-goals check-in is in progress."

        assert goal_problems("message", text, values) == []

    def test_a_goal_sentence_about_its_own_work_or_no_fact_stands(self) -> None:
        text = "Still aiming for 300 users? [The emails](fact:2) are that goal's work."

        assert goal_problems("message", text, _FOUNDER) == []

    def test_every_unlinked_fact_a_goal_sentence_names_is_listed(self) -> None:
        text = "[The sequence](fact:1) and [the redesign](fact:3) feed the 300-user goal."

        assert goal_problems("message", text, _FOUNDER) == [
            "the message ties facts 1, 3 to a goal, but they are not linked to one; only a goal's "
            "linked todos are its work, so name them in a sentence that does not speak of the goal"
        ]


class TestHowLongSomethingStood:
    """Founder's Nov 22: "still sitting unread" and "for a while" of a sequence no line dates."""

    @pytest.mark.parametrize(
        ("text", "claim"),
        [
            ("Your YC founders sequence is still sitting unread", "still"),
            (
                "The outreach sequence has been waiting on your approval for a while.",
                "been waiting",
            ),
            ("[The sequence](fact:1) is in draft. It has sat there for weeks.", "for weeks"),
        ],
    )
    def test_a_duration_said_of_an_undated_fact_is_named(self, text: str, claim: str) -> None:
        assert duration_problems("headline", text, _FOUNDER) == [
            f"the headline says {claim!r} of facts 1, but their lines carry no date; say how "
            "long something stood only where its line dates it"
        ]

    @pytest.mark.parametrize(
        "values",
        [
            SlotValues(
                facts={1: BriefFact(title="YC founders outreach sequence", seen_before=True)},
                counts={},
            ),
            SlotValues(
                facts={
                    1: BriefFact(
                        title="YC founders outreach sequence", time="Mon Nov 16", time_is_day=True
                    )
                },
                counts={},
            ),
        ],
    )
    def test_a_fact_an_earlier_brief_showed_or_its_time_dates_may_be_still_open(
        self, values: SlotValues
    ) -> None:
        assert duration_problems("headline", "The YC founders sequence is still open", values) == []

    @pytest.mark.parametrize(
        "text",
        [
            "[The redesign](fact:3) still has two comments to answer.",
            "[The sequence](fact:1) is still running.",
            "Want me to run [the sequence](fact:1) again?",
            "The day is still clear.",
        ],
    )
    def test_an_age_in_its_line_a_running_state_an_offer_or_no_fact_stands(self, text: str) -> None:
        assert duration_problems("message", text, _FOUNDER) == []

    def test_a_duration_word_the_facts_own_line_says_is_quoted(self) -> None:
        values = SlotValues(
            facts={1: BriefFact(title="Stripe card", words="Still waiting on delivery details")},
            counts={},
        )

        assert (
            duration_problems("message", "[Stripe](fact:1) says it is still waiting.", values) == []
        )

    def test_every_undated_fact_a_duration_sentence_names_is_listed(self) -> None:
        text = "[The sequence](fact:1) and [the emails](fact:2) have waited for weeks."

        assert duration_problems("message", text, _FOUNDER) == [
            "the message says 'for weeks' of facts 1, 2, but their lines carry no date; say how "
            "long something stood only where its line dates it"
        ]

    def test_a_duration_word_the_first_named_facts_line_ends_on_is_quoted(self) -> None:
        values = SlotValues(
            facts={
                1: BriefFact(title="Stripe card", words="Waiting on delivery for a while"),
                2: BriefFact(title="Board deck"),
            },
            counts={},
        )
        text = "[Stripe](fact:1) and [the deck](fact:2) have waited for a while."

        assert duration_problems("message", text, values) == []

    @pytest.mark.parametrize(
        "text",
        [
            "It has sat there for weeks.",
            "[The sequence](fact:1) is in draft. The day has been quiet for weeks.",
        ],
        ids=["points-back-to-nothing", "names-nothing-and-points-nowhere"],
    )
    def test_a_sentence_naming_no_fact_takes_none_unless_it_points_back(self, text: str) -> None:
        assert duration_problems("message", text, _FOUNDER) == []

    @pytest.mark.parametrize(
        ("title", "text"),
        [
            ("QA on Stripe", "Stripe is still pending."),
            ("Pay tax", "Tax to pay is still due."),
        ],
        ids=["two-letter-words-do-not-count", "three-letter-words-count"],
    )
    def test_a_title_named_by_its_words_of_three_letters_or_more(
        self, title: str, text: str
    ) -> None:
        values = SlotValues(facts={1: BriefFact(title=title)}, counts={})

        assert duration_problems("message", text, values) == [
            "the message says 'still' of facts 1, but their lines carry no date; say how "
            "long something stood only where its line dates it"
        ]

    def test_stopwords_never_name_a_fact(self) -> None:
        values = SlotValues(facts={1: BriefFact(title="Reply to the investor")}, counts={})

        assert duration_problems("message", "The investor has waited for a while.", values) == []
