"""Markdown section helpers for a GAIA task's notes.

Notes are markdown split into sections by "## Heading" lines. These helpers locate a
section by heading, case-insensitively (a template section's heading is written back
in the template's casing), and say what keeps a notes write from being a recall doc.
"""

import re

from app.constants.task_notes import (
    CANVAS_PROMPT_MAX_CHARS,
    CANVAS_SECTIONS,
    CANVAS_STANDING_RULES_SECTION,
    STANDING_RULES_MAX_CHARS,
)

_HEADING_RE = re.compile(r"^## (.+?)[ \t]*$", re.MULTILINE)
# A section that is a run log in all but name: "Activity Log (append)", "Timeline", "History".
_ACTIVITY_HEADING_RE = re.compile(
    r"^(activity|timeline|history|changelog|run log|log)\b", re.IGNORECASE
)
_ANY_DATED_BLOCK_RE = re.compile(r"^### \d{4}-\d{2}-\d{2}", re.MULTILINE)
# The template's "<!-- ... -->" guidance for whoever writes the section.
HTML_COMMENT_RE = re.compile(r"<!--.*?-->", re.DOTALL)
_TEMPLATE_HEADINGS = {section.casefold(): section for section in CANVAS_SECTIONS}


def bounded_canvas(canvas: str) -> str:
    """Trim an oversized canvas to its head and tail, within CANVAS_PROMPT_MAX_CHARS.

    Standing rules are the user's instructions, so they move to the top whole and
    only the rest is trimmed: Key Details/Current State sit at its top and the
    latest notes at its bottom, so its middle is dropped behind a marker.
    """
    if len(canvas) <= CANVAS_PROMPT_MAX_CHARS:
        return canvas
    rest, rules = remove_section(canvas, CANVAS_STANDING_RULES_SECTION)
    head = f"## {CANVAS_STANDING_RULES_SECTION}\n{rules}\n\n" if rules else ""
    limit = CANVAS_PROMPT_MAX_CHARS - len(head)
    if len(rest) <= limit:
        return head + rest
    half = max(limit // 2, 0)
    trimmed = len(rest) - 2 * half
    tail = rest[len(rest) - half :]
    return f"{head}{rest[:half]}\n[middle of canvas trimmed: {trimmed} characters]\n{tail}"


def _section_span(text: str, heading: str) -> tuple[int, int, int] | None:
    """(heading_start, body_start, section_end) for a "## {heading}" line, trailing blanks allowed."""
    pattern = re.compile(rf"(?:^|(?<=\n))## {re.escape(heading)}[ \t]*(?=\n|\Z)", re.IGNORECASE)
    match = pattern.search(text)
    if match is None:
        return None
    body_start = match.end()
    next_heading = re.compile(r"\n## ").search(text, body_start)
    section_end = next_heading.start() if next_heading else len(text)
    return match.start(), body_start, section_end


def section_body(text: str | None, heading: str) -> str | None:
    """Body of "## {heading}" without its HTML comments, stripped; None when the section is absent."""
    if text is None:
        return None
    span = _section_span(text, heading)
    if span is None:
        return None
    _, body_start, section_end = span
    return HTML_COMMENT_RE.sub("", text[body_start:section_end]).strip()


def written_lines(text: str | None) -> str:
    """Return the lines written in a notes file, without the template's comments and headings."""
    if not text:
        return ""
    kept = (line.strip() for line in HTML_COMMENT_RE.sub("", text).splitlines())
    return "\n".join(line for line in kept if line and not line.startswith("#"))


def with_section_appended(text: str, heading: str, addition: str) -> str:
    """Add addition at the end of "## {heading}", which goes at the end of text when absent."""
    span = _section_span(text, heading)
    if span is None:
        return text.rstrip("\n") + f"\n\n## {heading}\n{addition}\n"
    section_end = span[2]
    return text[:section_end].rstrip("\n") + f"\n\n{addition}\n" + text[section_end:]


def remove_section(text: str | None, heading: str) -> tuple[str, str | None]:
    """Cut "## {heading}" out of text; return the rest and its stripped body, None when absent.

    A task with no notes at all is an empty canvas, not a missing one, so a None text
    comes back as "" with no body: callers write the rest back and neither has to invent
    a placeholder of its own.
    """
    if text is None:
        return "", None
    span = _section_span(text, heading)
    if span is None:
        return text, None
    heading_start, body_start, section_end = span
    body = text[body_start:section_end].strip()
    before = text[:heading_start].rstrip("\n")
    after = text[section_end:]
    # Keep one blank line between the previous section and the next heading.
    if before and after.startswith("\n## "):
        after = "\n" + after
    return before + after, body


def _template_casing(heading: str) -> str:
    """Return a template section's heading in the template's casing; any other heading as is."""
    return _TEMPLATE_HEADINGS.get(heading.casefold(), heading)


def _headings(canvas: str) -> list[str]:
    return [_template_casing(match.group(1)) for match in _HEADING_RE.finditer(canvas)]


def _with_template_casing(canvas: str) -> str:
    """Rewrite every template section's heading line in the template's casing."""

    def recased(match: re.Match[str]) -> str:
        heading = match.group(1)
        canonical = _template_casing(heading)
        return match.group(0) if canonical == heading else f"## {canonical}"

    return _HEADING_RE.sub(recased, canvas)


def with_missing_sections(canvas: str) -> str:
    """Add every template section the canvas lacks, empty, before the next template section it has.

    Template headings are written back in the template's casing first.
    """
    canvas = _with_template_casing(canvas)
    present = set(_headings(canvas))
    if present.issuperset(CANVAS_SECTIONS):
        return canvas
    text = canvas.rstrip("\n")
    for index, section in enumerate(CANVAS_SECTIONS):
        if section in present:
            continue
        follower = next((s for s in CANVAS_SECTIONS[index + 1 :] if s in present), None)
        span = _section_span(text, follower) if follower else None
        if span is None:
            text += f"\n\n## {section}"
        else:
            text = f"{text[: span[0]]}## {section}\n\n{text[span[0] :]}"
    return text + "\n"


def canvas_problems(canvas: str) -> list[str]:
    """List what keeps a canvas from being a recall doc: repeated sections, activity, long rules."""
    headings = _headings(canvas)
    problems: list[str] = []
    for heading in dict.fromkeys(headings):
        if _ACTIVITY_HEADING_RE.match(heading):
            problems.append(f'drop "## {heading}": GAIA keeps the run log in log.md itself')
        elif (count := headings.count(heading)) > 1:
            problems.append(f'merge the {count} "## {heading}" sections into one')
    if _ANY_DATED_BLOCK_RE.search(canvas):
        problems.append(
            'drop the dated "### YYYY-MM-DD" entries: GAIA keeps the run log in log.md itself'
        )
    rules = section_body(canvas, CANVAS_STANDING_RULES_SECTION)
    if rules and len(rules) > STANDING_RULES_MAX_CHARS:
        problems.append(
            f'shorten "## {CANVAS_STANDING_RULES_SECTION}" to {STANDING_RULES_MAX_CHARS} '
            "characters: one line per rule, merged where they overlap"
        )
    return problems
