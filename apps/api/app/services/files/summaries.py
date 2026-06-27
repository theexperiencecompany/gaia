"""Shape and render the summaries produced for user-uploaded files.

`generate_file_summary` returns one of three shapes depending on the file type
(plain string for images/text, per-page models for documents). These helpers
normalize that into the `(description, page_wise_summary)` pair stored in Mongo
and render the human-readable `<file>.summary.md` sidecar.
"""

from typing import Any

from fastapi import HTTPException

from app.models.files_models import DocumentSummaryModel
from shared.py.wide_events import log

# Raw output of `generate_file_summary`.
GeneratedSummary = str | list[DocumentSummaryModel] | DocumentSummaryModel

# Normalized page-wise summary as persisted in Mongo.
PageWiseSummary = list[dict[str, Any]] | dict[str, Any] | None


def process_summary(summary: GeneratedSummary) -> tuple[str, PageWiseSummary]:
    """Normalize a generated summary into `(description, page_wise_summary)`.

    - str            → (text, None)
    - list[pages]    → (joined page summaries, [page dicts])
    - single page    → (page summary, page dict)
    """
    if isinstance(summary, str):
        return summary, None
    if isinstance(summary, list):
        pages = [page.model_dump(mode="json") for page in summary]
        description = "".join(page.summary for page in summary)
        return description, pages
    if isinstance(summary, DocumentSummaryModel):
        return summary.summary, summary.model_dump(mode="json")

    log.error("[files] generator returned an unrecognized summary shape")
    raise HTTPException(status_code=400, detail="Invalid file description format")


def render_summary_markdown(
    filename: str,
    content_type: str,
    description: str | None,
    page_wise_summary: PageWiseSummary,
) -> str:
    """Render a file's stored summary into the markdown sidecar body.

    Pure projection of the Mongo-stored summary — the short description plus,
    when present, the per-page content/summaries. No recompute.
    """
    parts: list[str] = [f"# Summary: {filename}", "", f"- Type: `{content_type}`", ""]
    if description:
        parts += ["## Overview", "", description.strip(), ""]

    if isinstance(page_wise_summary, list):
        for page in page_wise_summary:
            data = page.get("data", {})
            parts += [f"## Page {data.get('page_number', '?')}", ""]
            if page.get("summary"):
                parts += [f"**Summary:** {page['summary'].strip()}", ""]
            if data.get("content"):
                parts += [str(data["content"]).strip(), ""]
    elif isinstance(page_wise_summary, dict):
        content = page_wise_summary.get("data", {}).get("content")
        if content:
            parts += ["## Content", "", str(content).strip(), ""]

    return "\n".join(parts).rstrip() + "\n"
