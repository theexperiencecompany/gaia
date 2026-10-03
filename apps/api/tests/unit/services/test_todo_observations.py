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


def test_the_truncation_note_names_the_real_length_and_the_full_file() -> None:
    """The note tells the run what it is looking at and where the rest lives.

    Without the character count it cannot tell a long file from a short one, and
    without the file path it has no way to read what was cut.
    """
    entry = "### a@example.com\n- conclusion: alerts, low priority\n"
    observations = "## Senders\n" + entry * (OBSERVATIONS_PROMPT_MAX_CHARS // len(entry) + 5)

    note = bounded_observations(observations).splitlines()[0]

    assert f"only the conclusions of {len(observations)} characters" in note
    assert "read observations.md before you write it]" in note
    assert "XX" not in note


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


def test_a_carried_pattern_without_a_conclusion_states_the_pattern_itself() -> None:
    """An old canvas line that named no treatment still has to record one.

    Or the run reads a conclusion line with nothing after its colon and writes
    the file back that way.
    """
    carried = with_carried_lines(
        "# Observations\n\n## Senders\n", "- airline statements, ~2/month\n", TODAY
    )

    assert "- conclusion: airline statements, ~2/month\n" in carried


def test_several_carried_patterns_under_one_heading_are_kept_apart() -> None:
    """Each pattern is its own block.

    Joined without a blank line they read as one run-on conclusion, and the next
    run's rewrite would carry the merged line forward.
    """
    carried = with_carried_lines(
        "# Observations\n\n## Senders\n",
        "### Recurring\n- airline: monthly\n- hotel: on check-in\n",
        TODAY,
    )

    assert carried == (
        "# Observations\n\n## Senders\n\n## Recurring\n### airline\n- conclusion: monthly\n"
        "- confidence: low\n- first seen: before 2026-10-03"
        "\n\n### hotel\n- conclusion: on check-in\n"
        "- confidence: low\n- first seen: before 2026-10-03\n"
    )


def test_a_sub_heading_the_file_lacks_becomes_its_own_section() -> None:
    carried = with_carried_lines("# Observations\n", "### Travel\n- airline: monthly", TODAY)

    assert carried == (
        "# Observations\n\n## Travel\n### airline\n- conclusion: monthly\n"
        "- confidence: low\n- first seen: before 2026-10-03\n"
    )


def test_a_comment_spanning_lines_does_not_take_the_conclusion_below_it() -> None:
    """The comment is cut out BEFORE the lines are picked, so the line under it survives.

    Cutting it later would leave a comment's first line glued to the conclusion
    and drop a real observation from the prompt.
    """
    body = "- conclusion: alerts, low priority\n"
    observations = "## Senders\n<!-- a note to the reader\nspanning two lines -->\n" + body * 400

    shown = bounded_observations(observations)
    without = bounded_observations("## Senders\n" + body * 400)

    assert "a note to the reader" not in shown
    # The comment costs the prompt nothing: the same conclusions reach it either way.
    assert shown.splitlines()[1:] == without.splitlines()[1:]


def test_a_comment_inside_a_conclusion_leaves_the_conclusion_intact() -> None:
    """A comment in the middle of a line is cut out of that line, not replaced.

    Whatever the run wrote after it is part of the conclusion the prompt carries.
    """
    body = "- conclusion: alerts, low priority\n"
    observations = "## Senders\n- conclusion: GitHub<!-- inline --> notifications\n" + body * 400

    shown = bounded_observations(observations)

    assert "- conclusion: GitHub notifications" in shown
    assert "<!--" not in shown
    assert "inline" not in shown


def _room_for(file_length: int) -> int:
    """Return the characters bounded_observations leaves for the body of a file that long.

    The truncation note embeds the file's own character count, so its length (and the
    room it leaves) is a function of the file's length alone. Holding that fixed is what
    lets a test size a body to land exactly on the room.
    """
    head = "## Senders\n"
    filler = "p" * (file_length - len(head))
    note = bounded_observations(head + filler).splitlines()[0]
    return OBSERVATIONS_PROMPT_MAX_CHARS - len(note) - 1


def test_conclusions_past_the_room_are_cut_so_no_line_is_left_half_written() -> None:
    """A body one character past the room is cut back to its last whole line.

    Cutting at the room and keeping the remainder would leave a truncated
    conclusion in the prompt; a room one character wider would keep it.
    """
    head = "## Senders\n"
    file_length = OBSERVATIONS_PROMPT_MAX_CHARS * 3
    room = _room_for(file_length)

    line = "- conclusion: " + "c" * 19  # 33 characters; 34 counting the newline that joins it
    count = 173
    # The heading is kept as well as the conclusions, so it counts against the room too. The
    # body is sized to sit exactly TWO characters past the room: a room one character wider
    # would have kept the whole body, and this is where the two answers come apart.
    prefix = len(head.strip()) + 1
    pad = room + 2 - prefix - (34 * count - 1)
    body = "\n".join([line] * (count - 1) + ["- conclusion: " + "c" * (19 + pad)])
    observations = head + body + "\n" + "p" * (file_length - len(head) - len(body) - 1)

    shown = bounded_observations(observations)

    assert prefix + len(body) == room + 2
    # The cut happened: the prompt ends on a whole line instead of carrying the overhang.
    assert len("\n".join(shown.splitlines()[1:])) <= room
    assert shown.splitlines()[1:].count(line) == count - 1


def test_conclusions_that_exactly_fill_the_room_are_kept_whole() -> None:
    """A body landing exactly on the room is kept whole.

    The room is what is left after the note and the newline joining them, so
    nothing is dropped for want of a character.
    """
    head = "## Senders\n"
    file_length = OBSERVATIONS_PROMPT_MAX_CHARS * 3
    room = _room_for(file_length)

    line = "- conclusion: " + "c" * 19
    count = 170
    kept = len(head.strip()) + 1 + len("\n".join([line] * count))
    body = "\n".join([line] * (count - 1) + ["- conclusion: " + "c" * (19 + room - kept)])
    observations = head + body + "\n" + "p" * (file_length - len(head) - len(body) - 1)

    shown = bounded_observations(observations)

    assert len("\n".join(shown.splitlines()[1:])) == room
