"""Quotes cut verbatim from people's own words, and goals with the todos that name what they are about."""

from tests.factories import make_user_id

from app.constants.briefing import QUOTE_MAX_CHARS, QUOTE_MIN_CHARS
from app.models.brief_candidate_models import BriefCandidate
from app.models.brief_pool_models import GoalOrigin, GoalState, QuoteSpan
from app.models.scout_models import Signal
from app.models.todo_models import TodoDocument
from app.services.briefing.context import StatedGoal
from app.services.briefing.fact_pool.goals import goal_states
from app.services.briefing.fact_pool.quotes import quote_spans, verbatim_span

USER_ID = make_user_id()
MAYA = (
    "Can you confirm the 1x non-participating preference by Friday? Our partners meet Monday "
    "and I want to walk in with your answer. Also, the board deck looks great, thank you for "
    "turning it around so fast, it made the Tuesday review far easier than it could have been."
)


def _message(text: str | None, people: list[str], title: str = "Re: term sheet") -> BriefCandidate:
    signal = Signal(
        integration_id="gmail",
        app="Gmail",
        external_id=title,
        kind="email waiting on your reply",
        title=title,
        people=people,
        url="https://mail.google.com/x",
        text=text,
    )
    return BriefCandidate(
        source="gmail", app="Gmail", state="you", title=title, people=people, signal=signal
    )


class TestVerbatimSpan:
    def test_a_long_message_is_cut_at_the_last_sentence_end_that_fits(self) -> None:
        span = verbatim_span(MAYA)

        assert span == (
            "Can you confirm the 1x non-participating preference by Friday? Our partners meet "
            "Monday and I want to walk in with your answer."
        )
        assert span is not None and MAYA.startswith(span) and len(span) <= QUOTE_MAX_CHARS

    def test_a_short_message_is_quoted_whole_with_its_spacing_folded(self) -> None:
        assert verbatim_span("Ship it.\n\n  The numbers look right to me.") == (
            "Ship it. The numbers look right to me."
        )

    def test_words_too_short_or_too_long_to_cut_cleanly_are_not_quoted(self) -> None:
        assert verbatim_span("ok thanks") is None
        assert len("ok thanks") < QUOTE_MIN_CHARS
        assert verbatim_span("word " * 60) is None


class TestQuoteSpans:
    def test_each_persons_words_become_a_quote_on_the_item_they_belong_to(self) -> None:
        items = {
            3: _message(MAYA, ["Maya Chen", "Sam"]),
            4: _message("Can we move the offsite to the week after Diwali?", ["Priya Raman"]),
            5: _message(None, ["Arjun"]),
            6: _message("A message nobody signed, which has no author.", []),
            7: BriefCandidate(source="gaia", app="GAIA", state="lookback", title="Deck"),
        }

        quotes = quote_spans(items)

        assert [(q.id, q.author, q.item_id, q.app) for q in quotes] == [
            ("q1", "Maya Chen", 3, "Gmail"),
            ("q2", "Priya Raman", 4, "Gmail"),
        ]
        assert quotes[1] == QuoteSpan(
            id="q2",
            text="Can we move the offsite to the week after Diwali?",
            author="Priya Raman",
            source="gmail",
            app="Gmail",
            url="https://mail.google.com/x",
            item_id=4,
        )


def _todo(title: str, *, completed: bool = False) -> TodoDocument:
    return TodoDocument(id=title, user_id=USER_ID, title=title, completed=completed)


class TestGoalStates:
    def test_todos_naming_what_a_goal_is_about_are_its_linked_work(self) -> None:
        goals = [
            StatedGoal("Launch the GAIA mobile app by December", GoalOrigin.MEMORY, ("GAIA",)),
            StatedGoal("Raise a seed round", GoalOrigin.MEMORY, ("Accel", "Sequoia")),
        ]
        todos = [
            _todo("GAIA App Store screenshots", completed=True),
            _todo("TestFlight build for gaia", completed=True),
            _todo("GAIA privacy labels"),
            _todo("Send the deck to Accel"),
            # "Sequoia" inside another word is not the name.
            _todo("Sequoiadendron seeds for the garden"),
            _todo("Book the dentist"),
        ]

        mobile, seed = goal_states(goals, todos)

        assert mobile == GoalState(
            id="g1",
            statement="Launch the GAIA mobile app by December",
            origin=GoalOrigin.MEMORY,
            done=2,
            open=1,
            linked=[
                "GAIA App Store screenshots",
                "TestFlight build for gaia",
                "GAIA privacy labels",
            ],
        )
        assert (seed.id, seed.done, seed.open, seed.linked) == (
            "g2",
            0,
            1,
            ["Send the deck to Accel"],
        )

    def test_a_goal_that_names_nothing_has_no_linked_work(self) -> None:
        [goal] = goal_states(
            [StatedGoal("Close 10 customers", GoalOrigin.ONBOARDING)], [_todo("Customer call")]
        )

        assert (goal.origin, goal.done, goal.open, goal.linked) == (
            GoalOrigin.ONBOARDING,
            0,
            0,
            [],
        )
