"""
Document processing and summarization. PDF/DOCX/XLSX/PPTX/CSV are extracted
locally (no network call) via ``local_document_parser``; scanned/image-based
PDFs fall back to LlamaParse, which is the only path here that can OCR them.
The default LLM summarizes images, text, and every extracted chunk. Summaries
are embedded into ChromaDB for retrieval.
"""

import asyncio
from pathlib import Path
from typing import Union, cast

from langchain_core.messages import BaseMessage
from langchain_text_splitters import MarkdownTextSplitter
from llama_cloud_services import LlamaParse
from llama_cloud_services.parse.utils import ResultType

from app.agents.llm.client import ainvoke_llm, get_helper_llm, metered_config, with_llm_retry
from app.agents.llm.vision import describe_image
from app.agents.prompts.image_prompts import DOCUMENT_IMAGE_SUMMARY_PROMPT
from app.config.settings import settings
from app.constants.files import (
    CSV_MIME,
    DOC_MIME,
    DOCX_MIME,
    EPUB_MIME,
    LOCAL_EXTRACTION_TIMEOUT_SECONDS,
    MAX_CHUNK_CHARS,
    MAX_INDEXED_CHUNKS,
    OCR_EXTRACTION_TIMEOUT_SECONDS,
    ODP_MIME,
    ODS_MIME,
    ODT_MIME,
    PDF_MIME,
    PPTX_MIME,
    RTF_MIME,
    SUMMARY_LLM_MAX_CONCURRENCY,
    XLSX_MIME,
)
from app.constants.log_tags import LogTag
from app.models.files_models import DocumentPageModel, DocumentSummaryModel
from app.utils import local_document_parser
from app.utils.image_codec import ImageCodec, InvalidImageError
from shared.py.wide_events import log

_IMAGE_SUMMARY_UNAVAILABLE = "Image description could not be generated."


def _chunk_markdown(markdown: str, max_chunk_chars: int = MAX_CHUNK_CHARS) -> list[str]:
    """Split flat Markdown into size-bounded chunks for summarization/embedding.

    MarkdownTextSplitter guarantees the size bound and prefers natural cut
    points (heading > paragraph > line > character) over arbitrary offsets.
    """
    splitter = MarkdownTextSplitter(chunk_size=max_chunk_chars, chunk_overlap=0)
    return splitter.split_text(markdown)


class DocumentProcessor:
    """Document processing and summarization: local extraction first, LlamaParse for OCR."""

    def __init__(self, user_id: str) -> None:
        """Initialize the document processor. The LlamaParse client is built
        lazily -- only scanned/image-based PDFs need it as an OCR fallback.

        ``user_id`` is whose COGS this processor's LLM spend is attributed to.
        Held here rather than passed through every branch: one upload fans out
        to an image description or a summary per PDF page, and each of those is
        a billable call that must name the same user.
        """
        self._parser: LlamaParse | None = None
        self.user_id = user_id
        self.llm = get_helper_llm()

    @property
    def parser(self) -> LlamaParse:
        """LlamaCloud client, constructed on first use."""
        if self._parser is None:
            self._parser = LlamaParse(
                result_type=ResultType.MD,
                api_key=settings.LLAMA_INDEX_KEY or "",
            )
        return self._parser

    @parser.setter
    def parser(self, value: LlamaParse) -> None:
        self._parser = value

    async def process_file(
        self, file_content: bytes, content_type: str, filename: str
    ) -> Union[str, list[DocumentSummaryModel], DocumentSummaryModel]:
        """Process and summarize a file based on its content type.

        Args:
            file_content: Raw file bytes
            content_type: MIME type of the file
            filename: Name of the file

        Returns:
            Appropriate summary based on file type
        """
        log.set(filename=filename, content_type=content_type)
        try:
            if content_type.startswith("image/"):
                return await self.process_image(file_content)
            if content_type == PDF_MIME:
                return await self.process_doc(file_content)
            if content_type == DOCX_MIME:
                return await self.process_office_document(file_content, suffix=".docx")
            if content_type == DOC_MIME:
                return await self.process_office_document(file_content, suffix=".doc")
            if content_type == XLSX_MIME:
                return await self.process_office_document(file_content, suffix=".xlsx")
            if content_type == PPTX_MIME:
                return await self.process_office_document(file_content, suffix=".pptx")
            if content_type == CSV_MIME:
                return await self.process_office_document(file_content, suffix=".csv")
            if content_type == RTF_MIME:
                return await self.process_office_document(file_content, suffix=".rtf")
            if content_type == EPUB_MIME:
                return await self.process_office_document(file_content, suffix=".epub")
            if content_type == ODT_MIME:
                return await self.process_office_document(file_content, suffix=".odt")
            if content_type == ODS_MIME:
                return await self.process_office_document(file_content, suffix=".ods")
            if content_type == ODP_MIME:
                return await self.process_office_document(file_content, suffix=".odp")
            if content_type.startswith("text/"):
                return await self.process_text(file_content)
            if content_type == "application/json":
                return await self.process_text(file_content)
            ext = Path(filename).suffix.lower()
            return f"File of type {ext} (no content extraction available)"
        except Exception as e:
            log.error(
                f"{LogTag.TOOL} Failed to process file",
                filename=filename,
                error=str(e),
                error_type=type(e).__name__,
                exc_info=True,
            )
            return f"File processing failed for {filename}"

    async def process_image(self, image_data: bytes) -> str:
        """Summarize an uploaded image for retrieval.

        Runs on the same codec and vision call as every other image path, so the
        MIME the provider is told about is sniffed from the bytes rather than
        assumed: a PNG or WEBP upload used to be labelled ``image/jpeg``, which
        the provider rejects outright.
        """
        try:
            inline = await ImageCodec.from_bytes(image_data)
        except InvalidImageError as e:
            log.error(
                f"{LogTag.TOOL} Failed to process image", error=str(e), error_type=type(e).__name__
            )
            return _IMAGE_SUMMARY_UNAVAILABLE

        description = await describe_image(
            inline.base64,
            inline.mime_type,
            prompt=DOCUMENT_IMAGE_SUMMARY_PROMPT,
            label="file_image_summary",
            user_id=self.user_id,
        )
        return description or _IMAGE_SUMMARY_UNAVAILABLE

    async def process_doc(self, data: bytes) -> list[DocumentSummaryModel]:
        """Parse a PDF into per-page chunks and summarize each with the default model.

        Classified first (pdf_inspector): text-based PDFs are extracted
        locally, one native call for the whole document; scanned/image-based
        PDFs fall back to LlamaParse for OCR. Extraction errors propagate to
        the caller (``process_file``) instead of being swallowed here,
        matching ``process_text``.
        """
        chunks = await self._extract_pdf_chunks(data)
        return await self._summarize_chunks(chunks)

    async def process_office_document(self, data: bytes, suffix: str) -> list[DocumentSummaryModel]:
        """Extract a DOCX/XLSX/PPTX/CSV file locally via anydoc and summarize each chunk."""
        markdown = await asyncio.wait_for(
            asyncio.to_thread(local_document_parser.extract_office_document, data, suffix),
            timeout=LOCAL_EXTRACTION_TIMEOUT_SECONDS,
        )
        chunks = _chunk_markdown(markdown)
        return await self._summarize_chunks(chunks)

    async def _extract_pdf_chunks(self, data: bytes) -> list[str]:
        """Extract PDF text locally when possible; fall back to LlamaParse for OCR.

        The local calls are synchronous, CPU-bound native code, so they run
        on a thread to avoid blocking the event loop; a timeout bounds
        worst-case time (e.g. a decompression-bomb PDF) but note that the
        underlying native call itself has no cooperative cancellation and
        keeps running in its thread until it finishes, even past a timeout.
        """
        classification = await asyncio.wait_for(
            asyncio.to_thread(local_document_parser.classify_pdf, data),
            timeout=LOCAL_EXTRACTION_TIMEOUT_SECONDS,
        )
        if not classification.needs_ocr:
            return await asyncio.wait_for(
                asyncio.to_thread(local_document_parser.extract_pdf_pages, data),
                timeout=LOCAL_EXTRACTION_TIMEOUT_SECONDS,
            )

        return await asyncio.wait_for(
            self._extract_pdf_ocr(data),
            timeout=OCR_EXTRACTION_TIMEOUT_SECONDS,
        )

    async def _extract_pdf_ocr(self, data: bytes) -> list[str]:
        """OCR a scanned/image-based PDF via the LlamaParse cloud API."""
        result = await self.parser.aparse(
            file_path=data,
            extra_info={"file_name": "upload.pdf"},
        )
        if isinstance(result, list):
            result = result[0]
        md_documents = await result.aget_markdown_documents(split_by_page=True)
        return [doc.text for doc in md_documents]

    async def _summarize_chunks(self, chunks: list[str]) -> list[DocumentSummaryModel]:
        """Summarize extracted chunks with the default model for retrieval.

        Blank chunks (e.g. empty PDF pages) are skipped, not summarized — a
        summary of nothing is hallucinated content in the search index. At
        most MAX_INDEXED_CHUNKS are indexed; a trailing note entry records
        any truncation so retrieval knows the index is partial. Original
        chunk positions are preserved as page numbers.
        """
        numbered = [(i, chunk) for i, chunk in enumerate(chunks) if chunk.strip()]
        if not numbered:
            return []

        dropped = len(numbered) - MAX_INDEXED_CHUNKS
        if dropped > 0:
            log.set(
                indexed_chunks=MAX_INDEXED_CHUNKS,
                total_chunks=len(numbered),
                dropped_chunks=dropped,
            )
            log.info(f"{LogTag.TOOL} Document indexing truncated")
            numbered = numbered[:MAX_INDEXED_CHUNKS]

        # with_llm_retry adds the same transient-error retry every other LLM
        # call gets; max_concurrency keeps one big document from firing
        # hundreds of calls at once.
        summarized_chunks = await with_llm_retry(self.llm).abatch(
            inputs=[
                [
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "text",
                                "text": f"""Provide a concise summary of the content in given text. Assume it is part of a document like a PDF or DOCX, and ensure the summary is relevant for semantic search and accurately describes the content.
                                Note: Only respond with the summary text, without any additional information or context.
                                CONTENT:{chunk}""",
                            },
                        ],
                    }
                ]
                for _, chunk in numbered
            ],
            config={"max_concurrency": SUMMARY_LLM_MAX_CONCURRENCY},
        )

        summaries = [
            DocumentSummaryModel(
                data=DocumentPageModel(
                    page_number=position + 1,
                    content=chunk,
                ),
                summary=summarized.text,
            )
            for (position, chunk), summarized in zip(numbered, summarized_chunks, strict=True)
        ]
        if dropped > 0:
            note = (
                f"Note: only the first {MAX_INDEXED_CHUNKS} of {len(chunks)} sections of this "
                "document were indexed for search. The full file is available in the workspace."
            )
            summaries.append(
                DocumentSummaryModel(
                    data=DocumentPageModel(page_number=len(chunks) + 1, content=note),
                    summary=note,
                )
            )
        return summaries

    async def process_text(self, text_data: bytes) -> DocumentSummaryModel:
        """Process and summarize a text file."""
        try:
            text_content = text_data.decode("utf-8", errors="replace")

            summary = await self._generate_text_summary(
                text_content[:4000]
            )  # Limit to avoid token issues

            return DocumentSummaryModel(
                data=DocumentPageModel(
                    page_number=1,
                    content=text_content,
                ),
                summary=summary,
            )

        except Exception as e:
            log.error(
                f"{LogTag.TOOL} Failed to process text",
                error=str(e),
                error_type=type(e).__name__,
                exc_info=True,
            )
            raise

    async def _generate_text_summary(self, text: str) -> str:
        """Generate a summary for text content using the default LLM."""
        try:
            response = await ainvoke_llm(
                self.llm,
                [
                    {
                        "role": "system",
                        "content": "You are an expert document summarizer. Create concise summaries that capture key information.",
                    },
                    {
                        "role": "user",
                        "content": f"Summarize the following text in a concise way that preserves the most important information:\n\n{text}",
                    },
                ],
                label="file_text_summary",
                config=metered_config(self.user_id),
            )

            # ainvoke_llm is typed -> Any (its return shape varies by call
            # site); this call always resolves to a chat-model response message.
            return cast(BaseMessage, response).text.strip()

        except Exception as e:
            log.error(
                f"{LogTag.TOOL} Failed to generate summary",
                error=str(e),
                error_type=type(e).__name__,
                exc_info=True,
            )
            return "Summary could not be generated."


async def generate_file_summary(
    file_content: bytes, content_type: str, filename: str, *, user_id: str
) -> Union[str, list[DocumentSummaryModel], DocumentSummaryModel]:
    """Generate a description for a file based on its content type.

    Args:
        file_content: Raw file bytes
        content_type: MIME type of the file
        filename: Name of the file
        user_id: Whose COGS the summarization spend is attributed to. Required,
            not optional: this path runs one LLM call per image and per PDF page,
            and an omitted id records that spend against nobody.

    Returns:
        Description of the file content or DocumentSummaryModel instances
    """
    processor = DocumentProcessor(user_id=user_id)
    return await processor.process_file(
        file_content=file_content,
        content_type=content_type,
        filename=filename,
    )
