"""
Local, offline document-to-Markdown extraction.

Wraps two Rust-backed libraries with no network calls and no API keys:
``pdf_inspector`` classifies and extracts text-based PDFs (one native call
for the whole document); ``anydoc`` converts DOCX/XLSX/PPTX/CSV to Markdown.
Scanned/image-based PDFs are not handled here -- callers should fall back to
a cloud OCR parser for those (see ``DocumentProcessor._extract_pdf_chunks``).

Every function here is synchronous and CPU-bound; callers must offload to a
thread (e.g. ``asyncio.to_thread``) to avoid blocking the event loop. All
functions take raw bytes in memory, so callers never need a temp file.
"""

from dataclasses import dataclass, field

import anydoc
import pdf_inspector


@dataclass
class PdfClassification:
    needs_ocr: bool
    confidence: float = 0.0
    pages_needing_ocr: list[int] = field(default_factory=list)


def classify_pdf(data: bytes) -> PdfClassification:
    """Classify a PDF as locally-extractable (text-based) or needing OCR.

    Uses ``pdf_inspector.classify_pdf_bytes``, which skips building the full
    parse result -- cheaper than a full extraction just to read the type.
    """
    result = pdf_inspector.classify_pdf_bytes(data)
    return PdfClassification(
        needs_ocr=result.pdf_type != "text_based",
        confidence=result.confidence,
        pages_needing_ocr=list(result.pages_needing_ocr),
    )


def extract_pdf_pages(data: bytes) -> list[str]:
    """Extract every page of a text-based PDF to Markdown in a single native call."""
    result = pdf_inspector.extract_pages_markdown_bytes(data)
    return [page.markdown for page in result.pages]


def extract_office_document(data: bytes, suffix: str) -> str:
    """Convert a DOCX/XLSX/PPTX/CSV file to a single Markdown string."""
    return anydoc.to_markdown_bytes(data, format=anydoc.format_from_extension(suffix))
