"""GAIA's notes on a task (notes.md): the template a task starts from and what it is seeded with."""

from collections.abc import Sequence

from app.constants.todos import (
    CANVAS_DONE_WHEN_SECTION,
    CANVAS_EVIDENCE_SECTION,
    CANVAS_STANDING_RULES_SECTION,
)
from app.services.canvas_markdown import with_section_appended

CANVAS_TEMPLATE = """# {title}

## Standing rules
<!-- the user's instructions for how this task behaves, one line each with the date given; every run obeys them over its defaults; never removed unless the user retracts one -->

## Done when
<!-- the checkable conditions that make this done, one per line; every run checks them before closing -->

## Evidence
<!-- where proof of each condition will show up and how to check it (a connected service, a thread, a page, the user's word) -->

## Key Details
<!-- email addresses, thread IDs, calendar IDs, issue IDs: everything needed to take action -->

## Current State
<!-- what is true RIGHT NOW; rewrite after every action -->

## Context
<!-- accumulated context from signals, related information, decisions made, open questions -->

## Learnings
<!-- written on completion: what worked, what did not, timing insights, reusable patterns -->
"""


def with_ownership(canvas: str, done_when: Sequence[str], evidence: str | None) -> str:
    """Write the task's done conditions and its evidence source into their sections."""
    conditions = [c.strip() for c in done_when if c.strip()]
    if conditions:
        lines = "\n".join(f"- {c}" for c in conditions)
        canvas = with_section_appended(canvas, CANVAS_DONE_WHEN_SECTION, lines)
    if evidence and evidence.strip():
        canvas = with_section_appended(canvas, CANVAS_EVIDENCE_SECTION, evidence.strip())
    return canvas


def starting_canvas(title: str, standing_rules: Sequence[str] = ()) -> str:
    """Render the template canvas with standing rules the task starts out obeying."""
    canvas = CANVAS_TEMPLATE.format(title=title)
    heading = f"## {CANVAS_STANDING_RULES_SECTION}\n"
    # Rules go under the section's comment line; it is the last such heading, as a title can read like it.
    after_comment = canvas.index("\n", canvas.rindex(heading) + len(heading)) + 1
    rules = "".join(f"- {rule}\n" for rule in standing_rules)
    return canvas[:after_comment] + rules + canvas[after_comment:]
