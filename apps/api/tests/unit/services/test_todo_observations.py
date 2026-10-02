"""observations.md in a run prompt, and the old canvas section carried into it."""

from datetime import date

from app.agents.prompts.todo_prompts import INBOX_DESK_OBSERVATIONS_FILE
from app.constants.todos import OBSERVATIONS_PROMPT_MAX_CHARS
from app.services.todo_observations import bounded_observations, with_carried_lines

TODAY = date(2026, 10, 3)


def test_observations_within_the_cap_reach_the_prompt_whole() -> None:
    whole = "o" * OBSERVATIONS_PROMPT_MAX_CHARS

    assert bounded_observations(whole) == whole


def test_the_seeds_commented_example_is_never_taken_for_a_conclusion() -> None:
    observations = INBOX_DESK_OBSERVATIONS_FILE + "x" * OBSERVATIONS_PROMPT_MAX_CHARS

    shown = bounded_observations(observations)

    assert "<what it is>" not in shown
    assert shown.splitlines()[1:] == ["# Observations", "## Senders", "## Recurring", "## People"]


def test_conclusions_past_the_cap_are_cut_at_a_whole_line() -> None:
    entry = "### a@example.com\n- conclusion: " + "c" * 80 + "\n"
    observations = "## Senders\n" + entry * (OBSERVATIONS_PROMPT_MAX_CHARS // len(entry) + 5)

    shown = bounded_observations(observations)

    assert len(shown) <= OBSERVATIONS_PROMPT_MAX_CHARS
    assert set(shown.splitlines()[1:]) <= set(observations.splitlines())
    assert len(shown) > OBSERVATIONS_PROMPT_MAX_CHARS - len(entry)


def test_a_line_with_no_sub_heading_or_colon_is_carried_under_senders_whole() -> None:
    carried = with_carried_lines(
        "# Observations\n\n## Senders\n", "<!-- c -->\n- digest mail\n", TODAY
    )

    assert carried == (
        "# Observations\n\n## Senders\n\n### digest mail\n- conclusion: digest mail\n"
        "- confidence: low\n- first seen: before 2026-10-03\n"
    )


def test_a_sub_heading_the_file_lacks_becomes_its_own_section() -> None:
    carried = with_carried_lines("# Observations\n", "### Travel\n- airline: monthly", TODAY)

    assert carried == (
        "# Observations\n\n## Travel\n### airline\n- conclusion: monthly\n"
        "- confidence: low\n- first seen: before 2026-10-03\n"
    )
