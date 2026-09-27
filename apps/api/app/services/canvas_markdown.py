"""Markdown section helpers for tracked-todo canvases.

Canvases are markdown split into sections by "## Heading" lines. These helpers
locate a section by exact heading, and split legacy canvases (which carried
activity inside the canvas) into the canvas.md / activity.md pair.
"""

from datetime import UTC, datetime
import re

from app.constants.todos import CANVAS_PROMPT_MAX_CHARS, CANVAS_SECTIONS

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


def bounded_canvas(canvas: str) -> str:
    """Trim an oversized canvas to its head and tail, within CANVAS_PROMPT_MAX_CHARS.

    Key Details/Current State sit at the top and the latest notes at the bottom,
    so the middle is dropped behind a marker the agent won't read as a gap.
    """
    if len(canvas) <= CANVAS_PROMPT_MAX_CHARS:
        return canvas
    half = CANVAS_PROMPT_MAX_CHARS // 2
    trimmed = len(canvas) - 2 * half
    return f"{canvas[:half]}\n[middle of canvas trimmed: {trimmed} characters]\n{canvas[-half:]}"


def _section_span(text: str, heading: str) -> tuple[int, int, int] | None:
    """(heading_start, body_start, section_end) for an exact "## {heading}" line."""
    pattern = re.compile(rf"(?:^|(?<=\n))## {re.escape(heading)}(?=\n|\Z)")
    match = pattern.search(text)
    if match is None:
        return None
    body_start = match.end()
    next_heading = re.compile(r"\n## ").search(text, body_start)
    section_end = next_heading.start() if next_heading else len(text)
    return match.start(), body_start, section_end


def section_body(text: str, heading: str) -> str | None:
    """Body of "## {heading}" (stripped), or None when the section is absent."""
    span = _section_span(text, heading)
    if span is None:
        return None
    _, body_start, section_end = span
    return text[body_start:section_end].strip()


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


def _headings(canvas: str) -> list[str]:
    return [match.group(1) for match in _HEADING_RE.finditer(canvas)]


def with_missing_sections(canvas: str) -> str:
    """Append every template section the canvas lacks, empty, in template order."""
    missing = [section for section in CANVAS_SECTIONS if section not in _headings(canvas)]
    if not missing:
        return canvas
    body = canvas.rstrip("\n")
    return body + "".join(f"\n\n## {section}" for section in missing) + "\n"


def canvas_problems(canvas: str) -> list[str]:
    """List what keeps a canvas from being a recall doc: repeated sections, or activity in it."""
    headings = _headings(canvas)
    problems: list[str] = []
    for heading in dict.fromkeys(headings):
        if _ACTIVITY_HEADING_RE.match(heading):
            problems.append(f'move "## {heading}" into activity.md')
        elif (count := headings.count(heading)) > 1:
            problems.append(f'merge the {count} "## {heading}" sections into one')
    if _ANY_DATED_BLOCK_RE.search(canvas):
        problems.append('move the dated "### YYYY-MM-DD" entries into activity.md')
    return problems


def _merge_duplicate_sections(canvas: str) -> str:
    """Fold every repeat of a "## " section into its first occurrence."""
    for heading in dict.fromkeys(_headings(canvas)):
        while _headings(canvas).count(heading) > 1:
            first = _section_span(canvas, heading)
            if first is None:
                break
            rest = canvas[first[2] :]
            rest, repeat_body = _remove_section(rest, heading)
            canvas = canvas[: first[2]].rstrip("\n")
            if repeat_body:
                canvas += f"\n{repeat_body}"
            canvas += ("\n" if rest.startswith("\n") else "\n\n") + rest.lstrip("\n")
    return canvas


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
