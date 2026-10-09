"""observations.md: the evidence a tracked todo keeps for the patterns it learned.

Under each "## " section, one block per pattern: a "### <pattern>" line, then
"- <key>: <value>" lines (conclusion, confidence, first seen, last seen, daily
counts, earlier). Conclusions change as the evidence under them accumulates.
"""

from datetime import date

from app.constants.todos import (
    OBSERVATION_CONCLUSION,
    OBSERVATION_CONFIDENCE,
    OBSERVATION_FIRST_SEEN,
    OBSERVATIONS_PROMPT_MAX_CHARS,
    OBSERVATIONS_SENDERS_SECTION,
)
from app.services.canvas_markdown import HTML_COMMENT_RE, with_section_appended

_CONCLUSION_PREFIXES = (f"- {OBSERVATION_CONCLUSION}:", f"- {OBSERVATION_CONFIDENCE}:")
# A line carried over from the old canvas section has no evidence behind it yet.
_CARRIED_CONFIDENCE = "low"


def bounded_observations(observations: str) -> str:
    """Return observations.md for a prompt: whole when it fits, else its headings and conclusions."""
    if len(observations) <= OBSERVATIONS_PROMPT_MAX_CHARS:
        return observations
    note = (
        f"[only the conclusions of {len(observations)} characters; read observations.md "
        "before you write it]"
    )
    kept = [
        line
        for line in HTML_COMMENT_RE.sub("", observations).splitlines()
        if line.startswith(("#", *_CONCLUSION_PREFIXES))
    ]
    conclusions = "\n".join(kept)
    room = OBSERVATIONS_PROMPT_MAX_CHARS - len(note) - 1
    if len(conclusions) > room:
        conclusions = conclusions[:room].rpartition("\n")[0]
    return f"{note}\n{conclusions}"


def with_carried_lines(observations: str, canvas_section: str, today: date) -> str:
    """Add each line of the old one-line-per-pattern canvas section to observations.md as a block.

    A line lands under the section its "### " sub-heading names, Senders when it has none.
    """
    section = OBSERVATIONS_SENDERS_SECTION
    blocks: dict[str, list[str]] = {}
    for raw_line in HTML_COMMENT_RE.sub("", canvas_section).splitlines():
        line = raw_line.strip()
        if line.startswith("### "):
            section = line.removeprefix("### ").strip()
        elif line:
            pattern, _, conclusion = line.removeprefix("- ").partition(": ")
            blocks.setdefault(section, []).append(
                f"### {pattern}\n"
                f"- {OBSERVATION_CONCLUSION}: {conclusion or pattern}\n"
                f"- {OBSERVATION_CONFIDENCE}: {_CARRIED_CONFIDENCE}\n"
                f"- {OBSERVATION_FIRST_SEEN}: before {today.isoformat()}"
            )
    for heading, entries in blocks.items():
        observations = with_section_appended(observations, heading, "\n\n".join(entries))
    return observations
