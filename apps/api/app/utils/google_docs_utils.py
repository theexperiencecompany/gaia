"""Utility functions for Google Docs operations."""

import re

from app.models.integrations.google_docs import GoogleDocsDocument, GoogleDocsHeading

# Mapping of Google Docs heading styles to levels
HEADING_STYLE_MAP = {
    "HEADING_1": 1,
    "HEADING_2": 2,
    "HEADING_3": 3,
    "HEADING_4": 4,
    "HEADING_5": 5,
    "HEADING_6": 6,
}

_MARKDOWN_HEADING_RE = re.compile(r"^(#+)\s+([^\n]+)")


def extract_headings_from_document(
    document: GoogleDocsDocument, include_levels: list[int]
) -> list[GoogleDocsHeading]:
    """Extract headings from document body content."""
    headings: list[GoogleDocsHeading] = []

    for element in document.body.content:
        paragraph = element.paragraph
        if paragraph is None:
            continue

        named_style = paragraph.paragraphStyle.namedStyleType if paragraph.paragraphStyle else None
        # Extract text content first
        full_text = "".join(
            text_element.textRun.content
            for text_element in paragraph.elements
            if text_element.textRun is not None
        ).strip()

        # Check if it's a heading (Native Style OR Markdown)
        level = HEADING_STYLE_MAP.get(named_style) if named_style is not None else None

        if level is None and full_text.startswith("#"):
            # Check for markdown style headings (e.g. "# Heading")
            match = _MARKDOWN_HEADING_RE.match(full_text)
            if match:
                level = len(match.group(1))
                # Update text to use content without hash marks
                full_text = match.group(2)

        if level and level in include_levels and full_text:
            headings.append(
                GoogleDocsHeading(level=level, text=full_text, start_index=element.startIndex)
            )

    return headings


def generate_toc_text(headings: list[GoogleDocsHeading], title: str) -> str:
    """Generate formatted TOC text from headings."""
    if not headings:
        return f"{title}\n\n(No headings found in document)\n\n"

    lines = [f"{title}", "=" * len(title), ""]

    for heading in headings:
        level = heading.level
        text = heading.text
        # Indent based on heading level
        indent = "  " * (level - 1)
        # Use bullet style based on level
        if level == 1:
            lines.append(f"{indent}• {text}")
        else:
            lines.append(f"{indent}○ {text}")

    lines.append("")  # Empty line at end
    lines.append("")  # Extra spacing

    return "\n".join(lines)
