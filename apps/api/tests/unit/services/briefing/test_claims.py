"""What a sentence about one fact may claim of it: the fact's own state and its own figures."""

import pytest

from app.models.brief_item_models import ItemState
from app.services.briefing.claims import claim_problems
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

    @pytest.mark.regression
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
