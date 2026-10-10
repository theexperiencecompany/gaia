"""Unit tests for Google Docs heading extraction and TOC generation."""

from app.models.integrations.google_docs import GoogleDocsDocument, GoogleDocsHeading
from app.utils.google_docs_utils import (
    extract_headings_from_document,
    generate_toc_text,
)


def _doc(*paragraphs: dict[str, object]) -> GoogleDocsDocument:
    return GoogleDocsDocument.model_validate({"body": {"content": list(paragraphs)}})


def _paragraph(text: str, style: str | None = None, start_index: int = 0) -> dict[str, object]:
    element: dict[str, object] = {"paragraph": {"elements": [{"textRun": {"content": text}}]}}
    if start_index:
        element["startIndex"] = start_index
    if style:
        element["paragraph"] = {
            "elements": [{"textRun": {"content": text}}],
            "paragraphStyle": {"namedStyleType": style},
        }
    return element


def test_extracts_native_headings_at_requested_levels() -> None:
    doc = _doc(
        _paragraph("Intro", "NORMAL_TEXT"),
        _paragraph("Section A", "HEADING_1", start_index=7),
        _paragraph("Sub", "HEADING_2", start_index=20),
    )
    headings = extract_headings_from_document(doc, include_levels=[1, 2])

    assert headings == [
        GoogleDocsHeading(level=1, text="Section A", start_index=7),
        GoogleDocsHeading(level=2, text="Sub", start_index=20),
    ]


def test_extracts_markdown_headings() -> None:
    doc = _doc(_paragraph("## Markdown Heading"))
    headings = extract_headings_from_document(doc, include_levels=[2])

    assert headings == [GoogleDocsHeading(level=2, text="Markdown Heading", start_index=0)]


def test_native_heading_style_wins_over_a_markdown_prefix() -> None:
    doc = _doc(_paragraph("# Not markdown", "HEADING_2", start_index=3))

    assert extract_headings_from_document(doc, include_levels=[1, 2]) == [
        GoogleDocsHeading(level=2, text="# Not markdown", start_index=3)
    ]


def test_joins_runs_and_skips_non_paragraph_elements() -> None:
    doc = GoogleDocsDocument.model_validate(
        {
            "body": {
                "content": [
                    {"sectionBreak": {}},
                    {
                        "startIndex": 4,
                        "paragraph": {
                            "paragraphStyle": {"namedStyleType": "HEADING_1"},
                            "elements": [
                                {"textRun": {"content": "Two "}},
                                {"inlineObjectElement": {"inlineObjectId": "kix.1"}},
                                {"textRun": {"content": "runs\n"}},
                            ],
                        },
                    },
                    {"startIndex": 9, "paragraph": {"elements": []}},
                ]
            }
        }
    )

    assert extract_headings_from_document(doc, include_levels=[1]) == [
        GoogleDocsHeading(level=1, text="Two runs", start_index=4)
    ]


def test_skips_unrequested_levels_and_empty_text() -> None:
    doc = _doc(_paragraph("Heading 3", "HEADING_3"), _paragraph("   ", "HEADING_1"))
    assert extract_headings_from_document(doc, include_levels=[1]) == []


def test_generate_toc_text() -> None:
    headings = [
        GoogleDocsHeading(level=1, text="Intro", start_index=0),
        GoogleDocsHeading(level=2, text="Details", start_index=5),
        GoogleDocsHeading(level=3, text="Deep", start_index=9),
    ]
    toc = generate_toc_text(headings, "Report")

    assert toc == "Report\n======\n\n• Intro\n  ○ Details\n    ○ Deep\n\n"


def test_generate_toc_text_without_headings() -> None:
    assert generate_toc_text([], "Report") == "Report\n\n(No headings found in document)\n\n"
