"""Utility functions for Google Docs operations."""

from typing import cast

from app.utils.json_helpers import dict_bag, int_bag, text_bag

# Mapping of Google Docs heading styles to levels
HEADING_STYLE_MAP = {
    "HEADING_1": 1,
    "HEADING_2": 2,
    "HEADING_3": 3,
    "HEADING_4": 4,
    "HEADING_5": 5,
    "HEADING_6": 6,
}


def extract_headings_from_document(
    doc_content: dict[str, object], include_levels: list[int]
) -> list[dict[str, object]]:
    """Extract headings from document body content."""
    headings = []

    body = dict_bag(doc_content, "body")
    # The Docs API owns this schema: body.content is a list of structural elements,
    # each paragraph a nested object — bridged at the boundary, not re-checked.
    content = cast(list[dict[str, object]], body.get("content", []))

    for element in content:
        if "paragraph" not in element:
            continue

        paragraph = cast(dict[str, object], element["paragraph"])
        paragraph_style = dict_bag(paragraph, "paragraphStyle")
        named_style = text_bag(paragraph_style, "namedStyleType")
        # Extract text content first
        text_parts = []
        for text_element in cast(list[dict[str, object]], paragraph.get("elements", [])):
            if "textRun" in text_element:
                text_run = cast(dict[str, object], text_element["textRun"])
                text_parts.append(text_bag(text_run, "content"))
        full_text = "".join(text_parts).strip()

        # Check if it's a heading (Native Style OR Markdown)
        level = None

        if named_style in HEADING_STYLE_MAP:
            level = HEADING_STYLE_MAP[named_style]
        elif full_text.startswith("#"):
            # Check for markdown style headings (e.g. "# Heading")
            import re

            match = re.match(r"^(#+)\s+([^\n]+)", full_text)
            if match:
                level = len(match.group(1))
                # Update text to use content without hash marks
                full_text = match.group(2)

        if level and level in include_levels and full_text:
            headings.append(
                {
                    "level": level,
                    "text": full_text,
                    "start_index": int_bag(element, "startIndex"),
                }
            )

    return headings


def generate_toc_text(headings: list[dict[str, object]], title: str) -> str:
    """Generate formatted TOC text from headings."""
    if not headings:
        return f"{title}\n\n(No headings found in document)\n\n"

    lines = [f"{title}", "=" * len(title), ""]

    for heading in headings:
        level = int_bag(heading, "level", 1)
        text = heading["text"]
        # Indent based on heading level
        indent = "  " * max(level - 1, 0)
        # Use bullet style based on level
        if level == 1:
            lines.append(f"{indent}• {text}")
        else:
            lines.append(f"{indent}○ {text}")

    lines.append("")  # Empty line at end
    lines.append("")  # Extra spacing

    return "\n".join(lines)
