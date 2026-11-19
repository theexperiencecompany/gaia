"""Quotes cut verbatim from people's own words, and goals with the todos that name what they are about."""

from datetime import UTC, date, datetime, timedelta

import bson
from tests.factories import make_todo

from app.constants.briefing import GOAL_WORK_STALLED_AFTER, QUOTE_MAX_CHARS, QUOTE_MIN_CHARS
from app.constants.todos import GAIA_TRACKED_LABEL, TodoCompleter
from app.models.brief_candidate_models import BriefCandidate, CandidateOrigin
from app.models.brief_item_models import ItemState
from app.models.brief_pool_models import GoalOrigin, GoalState, QuoteSpan
from app.models.scout_models import Signal
from app.services.briefing.fact_pool.goals import goal_states
from app.services.briefing.fact_pool.quotes import quote_spans, verbatim_span
from app.services.briefing.goals import StatedGoal

MAYA = (
    "Can you confirm the 1x non-participating preference by Friday? Our partners meet Monday "
    "and I want to walk in with your answer. Also, the board deck looks great, thank you for "
    "turning it around so fast, it made the Tuesday review far easier than it could have been."
)


def _message(
    text: str | None, people: list[str], title: str = "Re: term sheet", *, author: str | None = None
) -> BriefCandidate:
    """Return a message the scout read; its author is the first person named unless one is given."""
    signal = Signal(
        integration_id="gmail",
        app="Gmail",
        external_id=title,
        kind="email waiting on your reply",
        title=title,
        people=people,
        url="https://mail.google.com/x",
        text=text,
        author=author if author is not None else (people[0] if people else None),
    )
    return BriefCandidate(
        origin=CandidateOrigin.APP_SIGNAL,
        source="gmail",
        app="Gmail",
        state=ItemState.YOU,
        title=title,
        people=people,
        signal=signal,
    )


class TestAQuoteIsItsAuthorsAlone:
    def test_words_whose_author_the_app_does_not_name_are_never_quoted(self) -> None:
        """Audit: the first person on an item was taken as the author of words read elsewhere."""
        unattributed = _message(MAYA, ["Ravi Rao", "Maya Chen"], author="")
        unattributed.signal = unattributed.signal.model_copy(update={"author": None})

        assert quote_spans({1: unattributed}) == []

    def test_the_author_is_the_texts_own_not_the_first_person_named(self) -> None:
        item = _message(MAYA, ["Ravi Rao", "Maya Chen"], author="Maya Chen")

        assert [q.author for q in quote_spans({1: item})] == ["Maya Chen"]


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


class TestVerbatimSpanBoundaries:
    def test_a_message_exactly_as_long_as_the_cap_is_quoted_whole(self) -> None:
        text = "x" * QUOTE_MAX_CHARS

        assert verbatim_span(text) == text

    def test_a_message_exactly_as_long_as_the_floor_is_quoted_and_one_less_is_not(self) -> None:
        assert verbatim_span("x" * QUOTE_MIN_CHARS) == "x" * QUOTE_MIN_CHARS
        assert verbatim_span("x" * (QUOTE_MIN_CHARS - 1)) is None

    def test_a_sentence_ending_exactly_at_the_cap_is_kept(self) -> None:
        first = "x" * (QUOTE_MAX_CHARS - 1) + "."

        assert verbatim_span(f"{first} And then some more.") == first

    def test_a_sentence_ending_exactly_at_the_floor_is_kept(self) -> None:
        first = "x" * (QUOTE_MIN_CHARS - 1) + "."

        assert verbatim_span(f"{first} {'y' * QUOTE_MAX_CHARS}.") == first

    def test_the_cut_is_the_last_sentence_end_that_fits_not_the_first_or_second(self) -> None:
        sentences = "One sentence is long enough here. Two follows it. Three follows too."

        assert verbatim_span(f"{sentences} {'z' * QUOTE_MAX_CHARS}") == sentences


class TestQuoteSpans:
    def test_each_persons_words_become_a_quote_on_the_item_they_belong_to(self) -> None:
        items = {
            3: _message(MAYA, ["Maya Chen", "Sam"]),
            4: _message("Can we move the offsite to the week after Diwali?", ["Priya Raman"]),
            5: _message(None, ["Arjun"]),
            6: _message("A message nobody signed, which has no author.", []),
            7: BriefCandidate(
                origin=CandidateOrigin.TRACKED,
                source="gaia",
                app="GAIA",
                state=ItemState.LOOKBACK,
                title="Deck",
            ),
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

    def test_an_item_with_nothing_to_quote_does_not_end_the_search(self) -> None:
        items = {
            1: BriefCandidate(
                origin=CandidateOrigin.TRACKED,
                source="gaia",
                app="GAIA",
                state=ItemState.LOOKBACK,
                title="Deck",
            ),
            2: _message("ok thanks", ["Priya Raman"]),
            3: _message("Can we move the offsite to the week after Diwali?", ["Priya Raman"]),
        }

        assert [(q.id, q.item_id) for q in quote_spans(items)] == [("q1", 3)]


_NOW = datetime(2026, 11, 15, 9, tzinfo=UTC)
_SINCE = date(2026, 11, 9)


class TestGoalStates:
    def test_todos_naming_what_a_goal_is_about_are_its_linked_work(self) -> None:
        goals = [
            StatedGoal("Launch the GAIA mobile app by December", GoalOrigin.MEMORY, ("GAIA",)),
            StatedGoal("Raise a seed round", GoalOrigin.MEMORY, ("Accel", "Sequoia")),
        ]
        todos = [
            make_todo(
                "GAIA App Store screenshots",
                GAIA_TRACKED_LABEL,
                completed=True,
                completed_by=TodoCompleter.GAIA,
            ),
            make_todo("TestFlight build for gaia", completed=True, completed_by=TodoCompleter.USER),
            make_todo("GAIA privacy labels"),
            make_todo("Send the deck to Accel"),
            # "Sequoia" inside another word is not the name.
            make_todo("Sequoiadendron seeds for the garden"),
            make_todo("Book the dentist"),
        ]

        mobile, seed = goal_states(goals, todos, _NOW, _SINCE)

        assert mobile == GoalState(
            id="g1",
            statement="Launch the GAIA mobile app by December",
            origin=GoalOrigin.MEMORY,
            done=2,
            done_by_gaia=1,
            done_by_you=1,
            since="2026-11-09",
            open=1,
            linked=[
                "GAIA App Store screenshots",
                "TestFlight build for gaia",
                "GAIA privacy labels",
            ],
        )
        # Stored with the brief, so it must be a value Mongo holds.
        bson.encode(mobile.model_dump())
        assert (seed.id, seed.done, seed.open, seed.linked) == (
            "g2",
            0,
            1,
            ["Send the deck to Accel"],
        )

    def test_open_work_untouched_a_week_or_more_is_stuck_and_the_rest_is_not(self) -> None:
        goal = StatedGoal("Launch Atlas", GoalOrigin.MEMORY, terms=("Atlas",))
        todos = [
            make_todo("Atlas pricing", updated_at=_NOW - GOAL_WORK_STALLED_AFTER),
            make_todo(
                "Atlas press list", updated_at=_NOW - GOAL_WORK_STALLED_AFTER + timedelta(hours=1)
            ),
            make_todo("Atlas launch post"),
            make_todo("Atlas landing page", completed=True, updated_at=_NOW - timedelta(days=30)),
        ]

        [state] = goal_states([goal], todos, _NOW, _SINCE)

        assert state.stalled == ["Atlas pricing"]

    def test_a_goal_that_names_nothing_has_no_linked_work(self) -> None:
        [goal] = goal_states(
            [StatedGoal("Close 10 customers", GoalOrigin.ONBOARDING)],
            [make_todo("Customer call")],
            _NOW,
            _SINCE,
        )

        assert (goal.origin, goal.done, goal.open, goal.linked) == (
            GoalOrigin.ONBOARDING,
            0,
            0,
            [],
        )
