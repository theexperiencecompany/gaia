"""The two bubbles GAIA opens with after onboarding, and the chips merged in.

Post-onboarding, not a pitch: nothing here reads the answers back, and the only
personalised part is the model-written starting jobs, merged by
``with_starting_jobs``. With no jobs there are no chips, never invented ones.
"""

from app.services.onboarding.first_conversation import (
    CALENDAR_INTEGRATION_ID,
    GMAIL_INTEGRATION_ID,
    HANDOVER_LINE,
    INTEGRATIONS_PATH,
    OPENING_LINE,
    compose_first_conversation,
    connect_link,
    with_starting_jobs,
)

JOBS = ["Find investors", "Fix my marketing", "Hire someone", "Write my pitch"]


class TestComposeFirstConversation:
    def test_it_is_exactly_the_routines_bubble_and_the_handover(self) -> None:
        composed = compose_first_conversation()
        assert composed.lines == [OPENING_LINE, HANDOVER_LINE]
        assert composed.follow_ups == []

    def test_the_opening_bubble_sells_the_two_routines_then_links_them(self) -> None:
        text, links = OPENING_LINE.split("\n\n")
        assert text == (
            "Connect Gmail and every morning your mail comes back sorted, replies drafted. "
            "Add Calendar and I brief you before every meeting."
        )
        assert links == (
            f"[Connect Gmail]({connect_link(GMAIL_INTEGRATION_ID)}) · "
            f"[Connect Calendar]({connect_link(CALENDAR_INTEGRATION_ID)}) · "
            f"[All integrations]({INTEGRATIONS_PATH})"
        )

    def test_a_connect_link_opens_that_app_on_the_integrations_page(self) -> None:
        assert connect_link("gmail") == "/integrations?connect=gmail"
        assert connect_link("googlecalendar") == "/integrations?connect=googlecalendar"

    def test_the_handover_is_one_closed_question(self) -> None:
        assert HANDOVER_LINE == "What are we starting with?"

    def test_nothing_in_the_thread_recites_the_answers(self) -> None:
        for line in compose_first_conversation().lines:
            assert "So:" not in line
            assert "You said" not in line


class TestWithStartingJobs:
    def test_the_jobs_ride_the_last_bubble_and_the_lines_are_untouched(self) -> None:
        composed = compose_first_conversation()
        updated = with_starting_jobs(composed, JOBS)
        assert updated.lines == composed.lines
        assert updated.follow_ups == JOBS
        assert composed.follow_ups == []

    def test_the_chips_are_copied_not_shared(self) -> None:
        jobs = list(JOBS)
        updated = with_starting_jobs(compose_first_conversation(), jobs)
        jobs.append("Ship it")
        assert updated.follow_ups == JOBS
