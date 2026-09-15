"""The two bubbles GAIA opens with after onboarding, and the chips merged in.

Post-onboarding, not a pitch: bubble one opens the door and sells the two
routines, bubble two hands over addressed by the job they gave. The only
model-written part is the starting jobs, merged by ``with_starting_jobs``; with
no jobs the escape hatch is the only chip, never invented ones.
"""

from app.models.user_models import OnboardingPreferences
from app.services.onboarding.first_conversation import (
    CALENDAR_INTEGRATION_ID,
    CONNECT_OPTIONS,
    CONNECT_OPTIONS_TOOL_NAME,
    GMAIL_INTEGRATION_ID,
    INTEGRATIONS_PATH,
    SOMETHING_ELSE_CHIP,
    compose_first_conversation,
    connect_link,
    with_starting_jobs,
)

JOBS = ["Find investors", "Fix my marketing", "Hire someone", "Write my pitch"]


def _prefs(profession: str | None = "founder") -> OnboardingPreferences:
    return OnboardingPreferences(profession=profession, needs=[], other_need=None)


class TestOpeningBubble:
    def test_welcome_handover_then_the_two_routines_as_one_bulleted_bubble(self) -> None:
        composed = compose_first_conversation(_prefs("founder"), None)
        assert composed.opening == [
            "Okay, you're in.",
            "Anything you'd rather not do yourself, hand it to me.",
            "Two things worth switching on now.\n"
            "- Gmail: every morning your mail comes back sorted, replies drafted.\n"
            "- Calendar: I brief you before every meeting.",
        ]
        assert composed.lines == [*composed.opening, composed.question]

    def test_a_linked_platform_is_named_on_the_handover_line(self) -> None:
        composed = compose_first_conversation(_prefs("founder"), "telegram")
        assert composed.opening[1] == (
            "Anything you'd rather not do yourself, hand it to me. I'm on your Telegram too."
        )

    def test_imessage_keeps_its_capitalisation_and_unknown_platforms_are_capitalised(self) -> None:
        assert (
            "I'm on your iMessage too." in compose_first_conversation(_prefs(), "imessage").lines[1]
        )
        assert "I'm on your Signal too." in compose_first_conversation(_prefs(), "signal").lines[1]

    def test_every_line_of_every_bubble_is_short(self) -> None:
        """A bubble may hold a bulleted list, but each line stays skimmable."""
        for bubble in compose_first_conversation(_prefs("founder"), "telegram").lines:
            for line in bubble.splitlines():
                assert len(line.split()) <= 16, line

    def test_the_buttons_open_each_app_and_the_full_page(self) -> None:
        """Rendered by the web as a row of buttons outside the bubble, same tab."""
        tool = compose_first_conversation(_prefs("founder"), None).connect_tool_data()
        assert tool["tool_name"] == CONNECT_OPTIONS_TOOL_NAME == "connect_options"
        assert tool["data"] == {"options": CONNECT_OPTIONS}
        assert [o["href"] for o in CONNECT_OPTIONS] == [
            connect_link(GMAIL_INTEGRATION_ID),
            connect_link(CALENDAR_INTEGRATION_ID),
            INTEGRATIONS_PATH,
        ]
        assert [o.get("integration_id") for o in CONNECT_OPTIONS] == [
            GMAIL_INTEGRATION_ID,
            CALENDAR_INTEGRATION_ID,
            None,
        ]


class TestHandoverBubble:
    def test_a_picked_job_is_addressed_by_its_phrase(self) -> None:
        assert compose_first_conversation(_prefs("founder"), None).question == (
            "You're a founder. What's first?"
        )
        assert compose_first_conversation(_prefs("sales"), None).question == (
            "You're in sales. What's first?"
        )
        assert compose_first_conversation(_prefs("engineering"), None).question == (
            "You're an engineer. What's first?"
        )

    def test_a_typed_sentence_is_turned_to_the_second_person(self) -> None:
        assert compose_first_conversation(_prefs("I run a bakery."), None).question == (
            "You run a bakery. What's first?"
        )
        assert compose_first_conversation(_prefs("I'm a plumber"), None).question == (
            "You're a plumber. What's first?"
        )

    def test_a_typed_title_gets_an_article_and_loses_its_capital(self) -> None:
        assert compose_first_conversation(_prefs("Plumber"), None).question == (
            "You're a plumber. What's first?"
        )
        assert compose_first_conversation(_prefs("An Architect"), None).question == (
            "You're an architect. What's first?"
        )

    def test_every_first_person_opener_is_turned(self) -> None:
        cases = {
            "I am a nurse": "You are a nurse. What's first?",
            "We run a shop": "You run a shop. What's first?",
            "We're a two person studio": "You're a two person studio. What's first?",
        }
        for typed, expected in cases.items():
            assert compose_first_conversation(_prefs(typed), None).question == expected

    def test_trailing_punctuation_and_articles_are_dropped_and_vowels_get_an(self) -> None:
        assert compose_first_conversation(_prefs("Engineer!"), None).question == (
            "You're an engineer. What's first?"
        )
        assert compose_first_conversation(_prefs("The Baker."), None).question == (
            "You're a baker. What's first?"
        )
        assert compose_first_conversation(_prefs("a Barista"), None).question == (
            "You're a barista. What's first?"
        )
        # Only the article goes; a multi-word title keeps every other word.
        assert compose_first_conversation(_prefs("The head baker"), None).question == (
            "You're a head baker. What's first?"
        )
        # Only end punctuation is dropped, never a trailing letter of the job.
        assert compose_first_conversation(_prefs("Founder at SpaceX"), None).question == (
            "You're a founder at SpaceX. What's first?"
        )
        # Every vowel earns "an"; anything else, including x, gets "a".
        for typed, expected in {
            "Illustrator": "an illustrator",
            "Optometrist": "an optometrist",
            "Urban planner": "an urban planner",
        }.items():
            assert compose_first_conversation(_prefs(typed), None).question == (
                f"You're {expected}. What's first?"
            )
        assert compose_first_conversation(_prefs("X-ray technician"), None).question == (
            "You're a x-ray technician. What's first?"
        )

    def test_other_or_skipped_gets_the_plain_question(self) -> None:
        for profession in ("other", "Other", None):
            assert compose_first_conversation(_prefs(profession), None).question == (
                "What's first?"
            )

    def test_nothing_in_the_thread_recites_the_answers(self) -> None:
        for line in compose_first_conversation(_prefs(), "telegram").lines:
            assert "So:" not in line
            assert "You said" not in line


class TestChips:
    def test_without_jobs_the_only_chip_is_the_escape_hatch(self) -> None:
        assert compose_first_conversation(_prefs(), None).follow_ups == [SOMETHING_ELSE_CHIP]

    def test_the_jobs_lead_and_the_escape_hatch_closes(self) -> None:
        composed = compose_first_conversation(_prefs(), None)
        updated = with_starting_jobs(composed, JOBS)
        assert updated.lines == composed.lines
        assert updated.follow_ups == [*JOBS, SOMETHING_ELSE_CHIP]
        assert composed.follow_ups == [SOMETHING_ELSE_CHIP]

    def test_the_chips_are_copied_not_shared(self) -> None:
        jobs = list(JOBS)
        updated = with_starting_jobs(compose_first_conversation(_prefs(), None), jobs)
        jobs.append("Ship it")
        assert updated.follow_ups == [*JOBS, SOMETHING_ELSE_CHIP]
