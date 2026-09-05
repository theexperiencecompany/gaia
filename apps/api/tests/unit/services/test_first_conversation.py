"""The two bubbles GAIA opens with after onboarding, and the chips merged in.

Post-onboarding, not a pitch: bubble one opens the door and sells the two
routines, bubble two hands over addressed by the job they gave. The only
model-written part is the starting jobs, merged by ``with_starting_jobs``; with
no jobs the escape hatch is the only chip, never invented ones.
"""

from app.models.user_models import OnboardingPreferences
from app.services.onboarding.first_conversation import (
    CALENDAR_INTEGRATION_ID,
    GMAIL_INTEGRATION_ID,
    INTEGRATIONS_PATH,
    LINKS_LINE,
    ROUTINES_LINE,
    SOMETHING_ELSE_CHIP,
    compose_first_conversation,
    connect_link,
    with_starting_jobs,
)

JOBS = ["Find investors", "Fix my marketing", "Hire someone", "Write my pitch"]


def _prefs(profession: str | None = "founder") -> OnboardingPreferences:
    return OnboardingPreferences(profession=profession, needs=[], other_need=None)


class TestOpeningBubble:
    def test_a_linked_platform_is_named_then_the_routines_then_the_links(self) -> None:
        composed = compose_first_conversation(_prefs(), "telegram")
        assert composed.lines[0] == (
            f"Okay, you're in. I'm on your Telegram, so text me there anytime. {ROUTINES_LINE}"
            f"\n\n{LINKS_LINE}"
        )

    def test_no_platform_opens_the_door_and_moves_on(self) -> None:
        composed = compose_first_conversation(_prefs(), None)
        assert composed.lines[0] == f"Okay, you're in. {ROUTINES_LINE}\n\n{LINKS_LINE}"

    def test_imessage_keeps_its_capitalisation_and_unknown_platforms_are_capitalised(self) -> None:
        assert "I'm on your iMessage," in compose_first_conversation(_prefs(), "imessage").lines[0]
        assert "I'm on your Signal," in compose_first_conversation(_prefs(), "signal").lines[0]

    def test_the_routines_line_sells_exactly_the_two_built_ins(self) -> None:
        assert ROUTINES_LINE == (
            "Two things worth switching on now: connect Gmail and every morning your mail "
            "comes back sorted, replies drafted. Add Calendar and I brief you before every meeting."
        )

    def test_the_links_open_each_app_and_the_full_page(self) -> None:
        assert (
            f"[Connect Gmail]({connect_link(GMAIL_INTEGRATION_ID)}) · "
            f"[Connect Calendar]({connect_link(CALENDAR_INTEGRATION_ID)}) · "
            f"[All integrations]({INTEGRATIONS_PATH})"
        ) == LINKS_LINE
        assert connect_link("gmail") == "/integrations?connect=gmail"


class TestHandoverBubble:
    def test_a_picked_job_is_addressed_by_its_phrase(self) -> None:
        assert compose_first_conversation(_prefs("founder"), None).lines[1] == (
            "Since you're a founder, what are we starting with?"
        )
        assert compose_first_conversation(_prefs("sales"), None).lines[1] == (
            "Since you're in sales, what are we starting with?"
        )
        assert compose_first_conversation(_prefs("engineering"), None).lines[1] == (
            "Since you're an engineer, what are we starting with?"
        )

    def test_a_typed_sentence_is_turned_to_the_second_person(self) -> None:
        assert compose_first_conversation(_prefs("I run a bakery."), None).lines[1] == (
            "Since you run a bakery, what are we starting with?"
        )
        assert compose_first_conversation(_prefs("I'm a plumber"), None).lines[1] == (
            "Since you're a plumber, what are we starting with?"
        )

    def test_a_typed_title_gets_an_article_and_loses_its_capital(self) -> None:
        assert compose_first_conversation(_prefs("Plumber"), None).lines[1] == (
            "Since you're a plumber, what are we starting with?"
        )
        assert compose_first_conversation(_prefs("An Architect"), None).lines[1] == (
            "Since you're an architect, what are we starting with?"
        )

    def test_other_or_skipped_gets_the_plain_question(self) -> None:
        for profession in ("other", "Other", None):
            assert compose_first_conversation(_prefs(profession), None).lines[1] == (
                "So, what are we starting with?"
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
