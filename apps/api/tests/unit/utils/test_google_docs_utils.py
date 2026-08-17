"""Unit tests for Google Docs heading extraction and TOC generation."""

from app.utils.google_docs_utils import (
    extract_headings_from_document,
    generate_toc_text,
)


def _doc(*paragraphs: dict) -> dict:
    return {"body": {"content": list(paragraphs)}}


def _paragraph(text: str, style: str | None = None, start_index: int = 0) -> dict:
    element: dict = {"paragraph": {"elements": [{"textRun": {"content": text}}]}}
    if start_index:
        element["startIndex"] = start_index
    if style:
        element["paragraph"]["paragraphStyle"] = {"namedStyleType": style}
    return element


def test_extracts_native_headings_at_requested_levels() -> None:
    doc = _doc(
        _paragraph("Intro", "NORMAL_TEXT"),
        _paragraph("Section A", "HEADING_1", start_index=7),
        _paragraph("Sub", "HEADING_2", start_index=20),
    )
    headings = extract_headings_from_document(doc, include_levels=[1, 2])

    assert headings == [
        {"level": 1, "text": "Section A", "start_index": 7},
        {"level": 2, "text": "Sub", "start_index": 20},
    ]


def test_extracts_markdown_headings() -> None:
    doc = _doc(_paragraph("## Markdown Heading"))
    headings = extract_headings_from_document(doc, include_levels=[2])

    assert headings == [{"level": 2, "text": "Markdown Heading", "start_index": 0}]


def test_skips_unrequested_levels_and_empty_text() -> None:
    doc = _doc(_paragraph("Heading 3", "HEADING_3"), _paragraph("   ", "HEADING_1"))
    assert extract_headings_from_document(doc, include_levels=[1]) == []


def test_body_without_content_yields_no_headings() -> None:
    """A body with no ``content`` key is an empty document, not a crash."""
    assert extract_headings_from_document({"body": {}}, include_levels=[1]) == []


def test_paragraph_without_elements_yields_no_headings() -> None:
    """A styled paragraph carrying no text runs contributes no heading."""
    doc = _doc({"paragraph": {"paragraphStyle": {"namedStyleType": "HEADING_1"}}})

    assert extract_headings_from_document(doc, include_levels=[1]) == []


def test_generate_toc_text() -> None:
    headings = [
        {"level": 1, "text": "Intro", "start_index": 0},
        {"level": 2, "text": "Details", "start_index": 5},
    ]
    toc = generate_toc_text(headings, "Report")

    assert toc == "Report\n======\n\n• Intro\n  ○ Details\n\n"


def test_generate_toc_text_defaults_missing_level_to_top_level() -> None:
    """A heading with no ``level`` renders as level 1 — unindented, bulleted."""
    toc = generate_toc_text([{"text": "Orphan"}], "Report")

    assert toc == "Report\n======\n\n• Orphan\n\n"
