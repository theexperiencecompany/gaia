"""Markdown section helpers for tracked-todo canvases.

Canvases are markdown split into sections by "## Heading" lines. These helpers
locate a section by heading, case-insensitively (a template section's heading is
written back in the template's casing), and split legacy canvases (which carried
activity inside the canvas) into the canvas.md / activity.md pair.
"""

from datetime import UTC, datetime
import re

from app.constants.todos import (
    CANVAS_PROMPT_MAX_CHARS,
    CANVAS_SECTIONS,
    CANVAS_STANDING_RULES_SECTION,
    STANDING_RULES_MAX_CHARS,
)

LEGACY_ACTIVITY_SECTIONS = ("Activity Log", "Timeline")
# Activity entries the old append mode dumped into the canvas: "### 2026-08-20" blocks.
_DATED_BLOCK_RE = re.compile(r"(?:^|\n)(### \d{4}-\d{2}-\d{2}.*?)(?=\n### |\Z)", re.DOTALL)
# A Timeline line: "- <iso timestamp> <text>" — sortable by the timestamp prefix.
_TIMELINE_LINE_RE = re.compile(r"^- (\d{4}-\d{2}-\d{2}T\S+) ")
_DATED_BLOCK_HEADER_RE = re.compile(r"### (\d{4}-\d{2}-\d{2})")
_HEADING_RE = re.compile(r"^## (.+?)[ \t]*$", re.MULTILINE)
_SECTION_START_RE = re.compile(r"(?=\n## )")
# A section that is a run log in all but name: "Activity Log (append)", "Timeline", "History".
_ACTIVITY_HEADING_RE = re.compile(
    r"^(activity|timeline|history|changelog|run log|log)\b", re.IGNORECASE
)
_ANY_DATED_BLOCK_RE = re.compile(r"^### \d{4}-\d{2}-\d{2}", re.MULTILINE)
# The template's "<!-- ... -->" guidance for whoever writes the section.
_HTML_COMMENT_RE = re.compile(r"<!--.*?-->", re.DOTALL)
_TEMPLATE_HEADINGS = {section.casefold(): section for section in CANVAS_SECTIONS}


def bounded_canvas(canvas: str) -> str:
    """Trim an oversized canvas to its head and tail, within CANVAS_PROMPT_MAX_CHARS.

    Standing rules are the user's instructions, so they move to the top whole and
    only the rest is trimmed: Key Details/Current State sit at its top and the
    latest notes at its bottom, so its middle is dropped behind a marker.
    """
    if len(canvas) <= CANVAS_PROMPT_MAX_CHARS:
        return canvas
    rest, rules = _remove_section(canvas, CANVAS_STANDING_RULES_SECTION)
    head = f"## {CANVAS_STANDING_RULES_SECTION}\n{rules}\n\n" if rules else ""
    limit = CANVAS_PROMPT_MAX_CHARS - len(head)
    if len(rest) <= limit:
        return head + rest
    half = max(limit, 0) // 2
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
    return _HTML_COMMENT_RE.sub("", text[body_start:section_end]).strip()


def _remove_section(text: str, heading: str) -> tuple[str, str | None]:
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


def _rescue_dated_blocks(text: str) -> tuple[str, list[str]]:
    """Pull every "### YYYY-MM-DD" block out of whichever section holds it."""
    blocks: list[str] = []
    segments: list[str] = []
    for segment in _SECTION_START_RE.split(text):
        found = [m.group(1).strip() for m in _DATED_BLOCK_RE.finditer(segment)]
        if found:
            blocks.extend(found)
            segment = _DATED_BLOCK_RE.sub("", segment).rstrip() + "\n"
        segments.append(segment)
    return ("".join(segments), blocks) if blocks else (text, [])


def _block_date(block: str) -> datetime | None:
    """Midnight UTC of a "### YYYY-MM-DD" block header, else None."""
    match = _DATED_BLOCK_HEADER_RE.match(block.strip())
    if match is None:
        return None
    try:
        return datetime.strptime(match.group(1), "%Y-%m-%d").replace(tzinfo=UTC)
    except ValueError:
        return None


def _line_timestamp(line: str) -> datetime | None:
    """Timestamp of a "- <iso timestamp> <text>" line, else None."""
    match = _TIMELINE_LINE_RE.match(line)
    if match is None:
        return None
    try:
        stamp = datetime.fromisoformat(match.group(1))
    except ValueError:
        return None
    return stamp if stamp.tzinfo is not None else stamp.replace(tzinfo=UTC)


def _extract_entries(body: str) -> tuple[list[tuple[datetime, str]], list[str]]:
    """Split a legacy activity body into dated entries and undated lines."""
    dated: list[tuple[datetime, str]] = []
    undated: list[str] = []
    remainder: list[str] = []
    pos = 0  # pragma: no mutate — used only as a slice start; None == 0 there
    for match in _DATED_BLOCK_RE.finditer(body):
        remainder.append(body[pos : match.start()])
        block = match.group(1).strip()
        stamp = _block_date(block)
        if stamp is None:
            undated.append(block)
        else:
            dated.append((stamp, block))
        pos = match.end()
    remainder.append(body[pos:])
    for line in "\n".join(remainder).splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        stamp = _line_timestamp(stripped)
        if stamp is None:
            undated.append(stripped)
        else:
            dated.append((stamp, stripped))
    return dated, undated


def split_legacy_canvas(canvas: str) -> tuple[str, str | None]:
    """Move Activity Log, Timeline, and dated blocks in any section out of the canvas.

    Returns (new_canvas, activity or None). Dated entries from all three sources
    merge oldest-first; undated lines follow in original order. Idempotent: nothing
    to move comes back unchanged.
    """
    text, activity = _remove_section(canvas, "Activity Log")
    text, rescued = _rescue_dated_blocks(text)
    text, timeline = _remove_section(text, "Timeline")
    if text == canvas:
        return canvas, None
    dated: list[tuple[datetime, str]] = []
    undated: list[str] = []
    if activity:
        activity_dated, activity_undated = _extract_entries(activity)
        dated.extend(activity_dated)
        undated.extend(activity_undated)
    for block in rescued:
        stamp = _block_date(block)
        if stamp is None:
            undated.append(block)
        else:
            dated.append((stamp, block))
    if timeline:
        timeline_dated, timeline_undated = _extract_entries(timeline)
        dated.extend(timeline_dated)
        undated.extend(timeline_undated)
    merged = [entry for _, entry in sorted(dated, key=lambda item: item[0])]
    merged.extend(undated)
    if not text.endswith("\n"):
        text += "\n"
    return text, "\n\n".join(merged) if merged else None


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
        present.add(section)
    return text + "\n"


def canvas_problems(canvas: str) -> list[str]:
    """List what keeps a canvas from being a recall doc: repeated sections, activity, long rules."""
    headings = _headings(canvas)
    problems: list[str] = []
    for heading in dict.fromkeys(headings):
        if _ACTIVITY_HEADING_RE.match(heading):
            problems.append(f'move "## {heading}" into activity.md')
        elif (count := headings.count(heading)) > 1:
            problems.append(f'merge the {count} "## {heading}" sections into one')
    if _ANY_DATED_BLOCK_RE.search(canvas):
        problems.append('move the dated "### YYYY-MM-DD" entries into activity.md')
    rules = section_body(canvas, CANVAS_STANDING_RULES_SECTION) or ""
    if len(rules) > STANDING_RULES_MAX_CHARS:
        problems.append(
            f'shorten "## {CANVAS_STANDING_RULES_SECTION}" to {STANDING_RULES_MAX_CHARS} '
            "characters: one line per rule, merged where they overlap"
        )
    return problems


def _merge_duplicate_sections(canvas: str) -> str:
    """Fold every repeat of a "## " section into its first occurrence."""
    headings = _headings(canvas)
    if len(set(headings)) == len(headings):
        return canvas
    preamble, *segments = _SECTION_START_RE.split(f"\n{canvas}")
    bodies: dict[str, list[str]] = {}
    for segment in segments:
        # Every segment after the split is "\n## <heading>\n<body>".
        heading_line, _, body = segment.removeprefix("\n").partition("\n")
        heading = _template_casing(heading_line.removeprefix("## ").rstrip())
        bodies.setdefault(heading, []).append(body.strip("\n"))
    sections = [
        "\n".join([f"## {heading}", *(part for part in parts if part)])
        for heading, parts in bodies.items()
    ]
    return "\n\n".join(filter(None, [preamble.strip("\n"), *sections])) + "\n"


def normalize_canvas(canvas: str) -> tuple[str, str | None]:
    """Repair a canvas into the template's shape; return (canvas, activity moved out or None).

    Activity-like sections and dated blocks move to activity.md, repeated sections
    merge, and missing template sections are added. Idempotent.
    """
    text, moved = split_legacy_canvas(canvas)
    moved_parts = [moved] if moved else []
    for heading in dict.fromkeys(_headings(text)):
        if _ACTIVITY_HEADING_RE.match(heading):
            while _section_span(text, heading) is not None:
                text, body = _remove_section(text, heading)
                if body:
                    moved_parts.append(body)
    text = with_missing_sections(_merge_duplicate_sections(text))
    if not text.endswith("\n"):
        text += "\n"
    return text, "\n\n".join(moved_parts) if moved_parts else None
