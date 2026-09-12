"""Markdown section helpers for tracked-todo canvases.

Canvases are `## Heading` sectioned markdown. These helpers locate a section
by exact heading, and split legacy canvases (which carried activity inside
the canvas) into the canvas.md / activity.md pair.
"""

from datetime import UTC, datetime
import re

LEGACY_ACTIVITY_SECTIONS = ("Activity Log", "Timeline")
_LEARNINGS_SECTION = "Learnings"
# Activity entries the old append mode dumped under Learnings: "### 2026-08-20" blocks.
_DATED_BLOCK_RE = re.compile(r"(?:^|\n)(### \d{4}-\d{2}-\d{2}.*?)(?=\n### |\Z)", re.DOTALL)
# A Timeline line: "- <iso timestamp> <text>" — sortable by the timestamp prefix.
_TIMELINE_LINE_RE = re.compile(r"^- (\d{4}-\d{2}-\d{2}T\S+) ")
_DATED_BLOCK_HEADER_RE = re.compile(r"### (\d{4}-\d{2}-\d{2})")


def _section_span(text: str, heading: str) -> tuple[int, int, int] | None:
    """(heading_start, body_start, section_end) for an exact `## {heading}` line."""
    pattern = re.compile(rf"(?:^|(?<=\n))## {re.escape(heading)}(?=\n|\Z)")
    match = pattern.search(text)
    if match is None:
        return None
    body_start = match.end()
    next_heading = re.compile(r"\n## ").search(text, body_start)
    section_end = next_heading.start() if next_heading else len(text)
    return match.start(), body_start, section_end


def section_body(text: str, heading: str) -> str | None:
    """Body of `## {heading}` (stripped), or None when the section is absent."""
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


def _rescue_dated_blocks_from_learnings(text: str) -> tuple[str, list[str]]:
    span = _section_span(text, _LEARNINGS_SECTION)
    if span is None:
        return text, []
    _, body_start, section_end = span
    body = text[body_start:section_end]
    blocks = [m.group(1).strip() for m in _DATED_BLOCK_RE.finditer(body)]
    if not blocks:
        return text, []
    remaining = _DATED_BLOCK_RE.sub("", body).strip()
    rebuilt = (
        text[:body_start] + ("\n" + remaining + "\n" if remaining else "\n") + text[section_end:]
    )
    return rebuilt, blocks


def _block_date(block: str) -> datetime | None:
    """Midnight UTC of a `### YYYY-MM-DD` block header, else None."""
    match = _DATED_BLOCK_HEADER_RE.match(block.strip())
    if match is None:
        return None
    try:
        return datetime.strptime(match.group(1), "%Y-%m-%d").replace(tzinfo=UTC)
    except ValueError:
        return None


def _line_timestamp(line: str) -> datetime | None:
    """Timestamp of a `- <iso timestamp> <text>` line, else None."""
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
    pos = 0
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
    """Move `## Activity Log`, `## Timeline`, and dated blocks stranded under
    `## Learnings` out of the canvas. Returns (new_canvas, activity or None).
    Dated entries from all three sources merge oldest-first; undated lines
    follow in original order. Idempotent: nothing to move comes back unchanged."""
    text, activity = _remove_section(canvas, "Activity Log")
    text, rescued = _rescue_dated_blocks_from_learnings(text)
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
