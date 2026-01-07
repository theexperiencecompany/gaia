"""Utility functions for Google Docs operations."""

from typing import Any, Dict, List

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
    doc_content: Dict[str, Any], include_levels: List[int]
) -> List[Dict[str, Any]]:
    """Extract headings from document body content."""
    headings = []

    body = doc_content.get("body", {})
    content = body.get("content", [])

    for element in content:
        if "paragraph" not in element:
            continue

        paragraph = element["paragraph"]
        paragraph_style = paragraph.get("paragraphStyle", {})
        named_style = paragraph_style.get("namedStyleType", "")
        # Extract text content first
        text_parts = []
        for text_element in paragraph.get("elements", []):
            if "textRun" in text_element:
                text_parts.append(text_element["textRun"]["content"])
        full_text = "".join(text_parts).strip()

        # Check if it's a heading (Native Style OR Markdown)
        level = None

        if named_style in HEADING_STYLE_MAP:
            level = HEADING_STYLE_MAP[named_style]
        elif full_text.startswith("#"):
            # Check for markdown style headings (e.g. "# Heading")
            import re

            match = re.match(r"^(#+)\s+(.+)$", full_text)
            if match:
                level = len(match.group(1))
                # Update text to use content without hash marks
                full_text = match.group(2)

        if level and level in include_levels and full_text:
            headings.append(
                {
                    "level": level,
                    "text": full_text,
                    "start_index": element.get("startIndex", 0),
                }
            )

    return headings


def generate_toc_text(headings: List[Dict[str, Any]], title: str) -> str:
    """Generate formatted TOC text from headings."""
    if not headings:
        return f"{title}\n\n(No headings found in document)\n\n"

    lines = [f"{title}", "=" * len(title), ""]

    for heading in headings:
        level = heading["level"]
        text = heading["text"]
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
