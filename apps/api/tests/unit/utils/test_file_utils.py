"""Unit tests for app.utils.file_utils (DocumentProcessor & generate_file_summary)."""

import base64
import io
import re
import time
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

from langchain_core.messages import AIMessage
from PIL import Image
import pytest

from app.constants.files import SUMMARY_LLM_MAX_CONCURRENCY
from app.constants.llm import HELPER_MAX_OUTPUT_TOKENS
from app.models.files_models import DocumentPageModel, DocumentSummaryModel
from app.utils import file_utils, local_document_parser
from app.utils.file_utils import DocumentProcessor, generate_file_summary

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _mock_llm(invoke_return: Any = "Mock summary", batch_return: Any = None) -> AsyncMock:
    """Return an AsyncMock LLM with configurable ainvoke/abatch responses.

    ``ainvoke_llm`` returns the model's ``AIMessage`` and callers read ``.text``,
    so a plain-string ``invoke_return`` is wrapped in an ``AIMessage`` to match
    that contract.
    """
    llm = AsyncMock()
    ainvoke_return = (
        AIMessage(content=invoke_return) if isinstance(invoke_return, str) else invoke_return
    )
    llm.ainvoke = AsyncMock(return_value=ainvoke_return)
    llm.abatch = AsyncMock(return_value=batch_return or [])
    # ainvoke_llm wraps the model in with_llm_retry(model) -> model.with_retry(...);
    # pass through so the configured ainvoke/abatch responses are used.
    llm.with_retry = MagicMock(return_value=llm)
    return llm


def _make_md_document(text: str) -> MagicMock:
    doc = MagicMock()
    doc.text = text
    return doc


def _encode_image(fmt: str, size: tuple[int, int] = (16, 16)) -> bytes:
    """Real image bytes — ImageCodec decodes them, so fake payloads won't do."""
    buf = io.BytesIO()
    Image.new("RGB", size, "red").save(buf, format=fmt)
    return buf.getvalue()


def _mock_vision(description: str | None):
    """Patch the one vision call ``process_image`` makes."""
    return patch("app.utils.file_utils.describe_image", AsyncMock(return_value=description))


def _strip_ws(text: str) -> str:
    """Collapse whitespace so chunk boundaries (which may absorb blank lines) don't matter."""
    return re.sub(r"\s+", "", text)


def _slow_block(seconds: float = 0.2) -> None:
    """Block in a thread (async tests call this via ``asyncio.to_thread``), so a
    patched parser can exceed ``asyncio.wait_for`` and trigger a timeout."""
    time.sleep(seconds)


# ---------------------------------------------------------------------------
# DocumentProcessor.__init__ is patched in all tests to avoid real
# LlamaParse / LLM initialization.
# ---------------------------------------------------------------------------


@pytest.fixture
def processor() -> DocumentProcessor:
    """Return a DocumentProcessor with mocked parser and llm."""
    with (
        patch("app.utils.file_utils.LlamaParse"),
        patch("app.utils.file_utils.get_helper_llm", return_value=_mock_llm()),
    ):
        proc = DocumentProcessor(user_id="u-test")
    return proc


class TestDocumentProcessorInit:
    """Every other test in this file reassigns ``processor.llm``, so what
    ``__init__`` actually wired up is only proven here."""

    async def test_summarization_runs_on_the_helper_llm_the_constructor_built(self) -> None:
        helper = _mock_llm(batch_return=[AIMessage(content="Summary 1")])
        with (
            patch("app.utils.file_utils.LlamaParse"),
            patch("app.utils.file_utils.get_helper_llm", return_value=helper) as get_llm,
        ):
            proc = DocumentProcessor(user_id="u-test")

        result = await proc._summarize_chunks(["Page one"])

        get_llm.assert_called_once_with()
        assert proc.llm is helper
        helper.abatch.assert_awaited_once()
        assert [r.summary for r in result] == ["Summary 1"]

    def test_the_processor_llm_carries_the_helper_output_cap(self) -> None:
        """The real factory, not a stand-in: the point of ``get_helper_llm`` over
        ``get_default_llm`` is the 8k output cap, and a mocked factory would
        assert the mock rather than the cap. Only the key is pinned — the
        hermetic conftest blanks it, and building the client dials nothing."""
        with (
            patch("app.utils.file_utils.LlamaParse"),
            patch("app.agents.llm.client.settings.OPENROUTER_API_KEY", new="sk-unit-test"),
        ):
            proc = DocumentProcessor(user_id="u-test")

        assert proc.llm.max_tokens == HELPER_MAX_OUTPUT_TOKENS
        # Named explicitly so the assertion above cannot pass by coincidence if
        # the two factories' caps ever converge.
        assert HELPER_MAX_OUTPUT_TOKENS == 8_000

    def test_user_id_is_held_for_cost_attribution(self) -> None:
        with (
            patch("app.utils.file_utils.LlamaParse"),
            patch("app.utils.file_utils.get_helper_llm", return_value=_mock_llm()),
        ):
            proc = DocumentProcessor(user_id="u-billed")

        assert proc.user_id == "u-billed"


# ---------------------------------------------------------------------------
# process_file — routing by content type
# ---------------------------------------------------------------------------


class TestProcessFileRouting:
    """Verify that process_file routes to the correct sub-processor."""

    async def test_image_routes_to_process_image(self, processor: DocumentProcessor) -> None:
        processor.process_image = AsyncMock(return_value="image desc")  # type: ignore[method-assign]  # instance method stubbed with unittest.mock
        result = await processor.process_file(b"imgdata", "image/png", "photo.png")
        processor.process_image.assert_awaited_once_with(b"imgdata")
        assert result == "image desc"

    @pytest.mark.parametrize("content_type", ["image/jpeg", "image/gif", "image/webp"])
    async def test_various_image_types_route_to_process_image(
        self, processor: DocumentProcessor, content_type: str
    ) -> None:
        processor.process_image = AsyncMock(return_value="ok")  # type: ignore[method-assign]  # instance method stubbed with unittest.mock
        await processor.process_file(b"data", content_type, "file.img")
        processor.process_image.assert_awaited_once()

    async def test_pdf_routes_to_process_doc(self, processor: DocumentProcessor) -> None:
        processor.process_doc = AsyncMock(return_value=[])  # type: ignore[method-assign]  # instance method stubbed with unittest.mock
        await processor.process_file(b"pdfdata", "application/pdf", "doc.pdf")
        processor.process_doc.assert_awaited_once_with(b"pdfdata")

    async def test_text_routes_to_process_text(self, processor: DocumentProcessor) -> None:
        processor.process_text = AsyncMock(  # type: ignore[method-assign]  # instance method stubbed with unittest.mock
            return_value=DocumentSummaryModel(
                data=DocumentPageModel(page_number=1, content="hello"),
                summary="summary",
            )
        )
        await processor.process_file(b"hello", "text/plain", "readme.txt")
        processor.process_text.assert_awaited_once_with(b"hello")

    @pytest.mark.parametrize("content_type", ["text/html", "text/markdown"])
    async def test_various_text_types_route_to_process_text(
        self, processor: DocumentProcessor, content_type: str
    ) -> None:
        processor.process_text = AsyncMock(  # type: ignore[method-assign]  # instance method stubbed with unittest.mock
            return_value=DocumentSummaryModel(
                data=DocumentPageModel(page_number=1, content="c"),
                summary="s",
            )
        )
        await processor.process_file(b"data", content_type, "file.txt")
        processor.process_text.assert_awaited_once()

    @pytest.mark.parametrize(
        ("content_type", "suffix"),
        [
            (file_utils.DOCX_MIME, ".docx"),
            (file_utils.DOC_MIME, ".doc"),
            (file_utils.XLSX_MIME, ".xlsx"),
            (file_utils.PPTX_MIME, ".pptx"),
            (file_utils.CSV_MIME, ".csv"),
            (file_utils.RTF_MIME, ".rtf"),
            (file_utils.EPUB_MIME, ".epub"),
            (file_utils.ODT_MIME, ".odt"),
            (file_utils.ODS_MIME, ".ods"),
            (file_utils.ODP_MIME, ".odp"),
        ],
    )
    async def test_office_and_csv_types_route_to_process_office_document(
        self, processor: DocumentProcessor, content_type: str, suffix: str
    ) -> None:
        processor.process_office_document = AsyncMock(return_value=[])  # type: ignore[method-assign]  # instance method stubbed with unittest.mock
        await processor.process_file(b"data", content_type, f"file{suffix}")
        processor.process_office_document.assert_awaited_once_with(b"data", suffix=suffix)

    async def test_json_routes_to_process_text(self, processor: DocumentProcessor) -> None:
        """JSON is text; it routes to process_text, not the office parser."""
        processor.process_text = AsyncMock(  # type: ignore[method-assign]  # instance method stubbed with unittest.mock
            return_value=DocumentSummaryModel(
                data=DocumentPageModel(page_number=1, content='{"a": 1}'),
                summary="summary",
            )
        )
        await processor.process_file(b'{"a": 1}', "application/json", "data.json")
        processor.process_text.assert_awaited_once_with(b'{"a": 1}')

    async def test_unknown_type_returns_fallback_string(self, processor: DocumentProcessor) -> None:
        result = await processor.process_file(b"binary", "application/octet-stream", "data.bin")
        assert isinstance(result, str)
        assert ".bin" in result
        assert "no content extraction" in result

    async def test_exception_returns_error_string(self, processor: DocumentProcessor) -> None:
        processor.process_image = AsyncMock(side_effect=RuntimeError("boom"))  # type: ignore[method-assign]  # instance method stubbed with unittest.mock
        result = await processor.process_file(b"img", "image/png", "bad.png")
        assert isinstance(result, str)
        assert "File processing failed" in result
        assert "bad.png" in result


# ---------------------------------------------------------------------------
# process_image
# ---------------------------------------------------------------------------


class TestProcessImage:
    async def test_success_returns_description(self, processor: DocumentProcessor) -> None:
        with _mock_vision("A scenic mountain view"):
            result = await processor.process_image(_encode_image("PNG"))
        assert result == "A scenic mountain view"

    async def test_the_mime_is_sniffed_from_the_bytes_not_assumed(
        self, processor: DocumentProcessor
    ) -> None:
        """Every `image/*` upload used to be labelled `image/jpeg`, whatever it
        actually was. A block whose mime_type contradicts its payload is rejected
        outright by the provider, so a PNG upload silently lost its summary."""
        with _mock_vision("desc") as vision:
            await processor.process_image(_encode_image("PNG"))

        assert vision.call_args.args[1] == "image/png"

    async def test_the_image_reaching_the_model_is_the_uploaded_one(
        self, processor: DocumentProcessor
    ) -> None:
        raw = _encode_image("PNG")
        with _mock_vision("desc") as vision:
            await processor.process_image(raw)

        assert base64.b64decode(vision.call_args.args[0]) == raw

    async def test_a_failed_vision_call_returns_the_fallback(
        self, processor: DocumentProcessor
    ) -> None:
        with _mock_vision(None):
            result = await processor.process_image(_encode_image("PNG"))
        assert "could not be generated" in result

    async def test_undecodable_bytes_return_the_fallback(
        self, processor: DocumentProcessor
    ) -> None:
        """A corrupt or mislabelled upload must not raise out of file processing."""
        with _mock_vision("desc") as vision:
            result = await processor.process_image(b"this is not an image")

        assert "could not be generated" in result
        vision.assert_not_called()


# ---------------------------------------------------------------------------
# process_doc
# ---------------------------------------------------------------------------


class TestProcessDoc:
    """process_doc handles PDFs only -- DOCX/XLSX/PPTX/CSV go through process_office_document."""

    async def test_text_based_pdf_uses_local_extraction(self, processor: DocumentProcessor) -> None:
        """Text-based PDFs are extracted locally via pdf_inspector, not LlamaParse."""
        processor.parser = AsyncMock()
        processor.llm = _mock_llm(
            batch_return=[AIMessage(content="Summary 1"), AIMessage(content="Summary 2")]
        )

        with (
            patch(
                "app.utils.file_utils.local_document_parser.classify_pdf",
                return_value=local_document_parser.PdfClassification(needs_ocr=False),
            ),
            patch(
                "app.utils.file_utils.local_document_parser.extract_pdf_pages",
                return_value=["Page 1 content", "Page 2 content"],
            ) as mock_extract,
        ):
            result = await processor.process_doc(b"pdf-bytes")

        mock_extract.assert_called_once()
        processor.parser.aparse.assert_not_called()
        assert len(result) == 2
        assert isinstance(result[0], DocumentSummaryModel)
        assert result[0].data.page_number == 1
        assert result[0].data.content == "Page 1 content"
        assert result[0].summary == "Summary 1"
        assert result[1].data.page_number == 2

    async def test_scanned_pdf_falls_back_to_llamaparse(self, processor: DocumentProcessor) -> None:
        """Scanned/image-based PDFs still go through LlamaParse for OCR."""
        md_doc = _make_md_document("OCR'd content")
        mock_parse_result = AsyncMock()
        mock_parse_result.aget_markdown_documents = AsyncMock(return_value=[md_doc])
        processor.parser = AsyncMock()
        processor.parser.aparse = AsyncMock(return_value=mock_parse_result)
        processor.llm = _mock_llm(batch_return=[AIMessage(content="Summary")])

        with (
            patch(
                "app.utils.file_utils.local_document_parser.classify_pdf",
                return_value=local_document_parser.PdfClassification(needs_ocr=True),
            ),
            patch("app.utils.file_utils.local_document_parser.extract_pdf_pages") as mock_extract,
        ):
            result = await processor.process_doc(b"scanned-pdf-bytes")

        mock_extract.assert_not_called()
        processor.parser.aparse.assert_awaited_once()
        assert len(result) == 1
        assert result[0].data.content == "OCR'd content"

    async def test_aparse_returns_list_unwraps_first(self, processor: DocumentProcessor) -> None:
        """When aparse returns a list, the first element is used (OCR fallback path)."""
        md_doc = _make_md_document("Content")
        inner_result = AsyncMock()
        inner_result.aget_markdown_documents = AsyncMock(return_value=[md_doc])

        processor.parser = AsyncMock()
        processor.parser.aparse = AsyncMock(return_value=[inner_result])
        processor.llm = _mock_llm(batch_return=[AIMessage(content="Sum")])

        with patch(
            "app.utils.file_utils.local_document_parser.classify_pdf",
            return_value=local_document_parser.PdfClassification(needs_ocr=True),
        ):
            result = await processor.process_doc(b"data")

        assert len(result) == 1
        assert result[0].data.content == "Content"

    async def test_extraction_failure_propagates(self, processor: DocumentProcessor) -> None:
        """Extraction errors propagate to the caller instead of being swallowed."""
        with patch(
            "app.utils.file_utils.local_document_parser.classify_pdf",
            side_effect=RuntimeError("parse fail"),
        ):
            with pytest.raises(RuntimeError, match="parse fail"):
                await processor.process_doc(b"bad-pdf")

    async def test_local_extraction_receives_bytes_not_a_temp_file(
        self, processor: DocumentProcessor
    ) -> None:
        """The bytes are handed to pdf_inspector directly; no temp file is written."""
        processor.llm = _mock_llm(batch_return=[AIMessage(content="Sum")])

        with (
            patch(
                "app.utils.file_utils.local_document_parser.classify_pdf",
                return_value=local_document_parser.PdfClassification(needs_ocr=False),
            ) as mock_classify,
            patch(
                "app.utils.file_utils.local_document_parser.extract_pdf_pages",
                return_value=["content"],
            ) as mock_extract,
        ):
            await processor.process_doc(b"pdf-bytes")

        mock_classify.assert_called_once_with(b"pdf-bytes")
        mock_extract.assert_called_once_with(b"pdf-bytes")

    async def test_local_extraction_timeout_propagates(self, processor: DocumentProcessor) -> None:
        """A local-extraction timeout surfaces as TimeoutError, not a silent hang."""
        with (
            patch("app.utils.file_utils.LOCAL_EXTRACTION_TIMEOUT_SECONDS", 0.01),
            patch(
                "app.utils.file_utils.local_document_parser.classify_pdf",
                side_effect=lambda _data: _slow_block(),
            ),
        ):
            with pytest.raises(TimeoutError):
                await processor.process_doc(b"slow-pdf")


# ---------------------------------------------------------------------------
# process_office_document (DOCX/XLSX/PPTX/CSV)
# ---------------------------------------------------------------------------


class TestProcessOfficeDocument:
    """These tests mock only the anydoc boundary; the real _chunk_markdown runs,
    so chunking logic (including the heading-split path) gets real coverage."""

    async def test_success_returns_list_of_summaries(self, processor: DocumentProcessor) -> None:
        """Markdown short enough to fit the size bound stays a single chunk."""
        processor.llm = _mock_llm(batch_return=[AIMessage(content="Summary 1")])

        with patch(
            "app.utils.file_utils.local_document_parser.extract_office_document",
            return_value="# Heading One\ncontent one\n\n# Heading Two\ncontent two",
        ) as mock_extract:
            result = await processor.process_office_document(b"xlsx-bytes", suffix=".xlsx")

        mock_extract.assert_called_once()
        assert len(result) == 1
        assert result[0].data.content == "# Heading One\ncontent one\n\n# Heading Two\ncontent two"
        assert result[0].summary == "Summary 1"
        assert result[0].data.page_number == 1

    async def test_docx_never_touches_llamaparse(self, processor: DocumentProcessor) -> None:
        """DOCX is extracted locally via anydoc, same as XLSX/PPTX/CSV."""
        processor.parser = AsyncMock()
        processor.llm = _mock_llm(batch_return=[AIMessage(content="Sum")])

        with patch(
            "app.utils.file_utils.local_document_parser.extract_office_document",
            return_value="flat content, no headings",
        ):
            result = await processor.process_office_document(b"data", suffix=".docx")

        processor.parser.aparse.assert_not_called()
        assert len(result) == 1
        assert result[0].data.content == "flat content, no headings"

    async def test_preamble_before_first_heading_is_kept(
        self, processor: DocumentProcessor
    ) -> None:
        """Regression: text before the first heading must not be dropped."""
        processor.llm = _mock_llm(batch_return=[AIMessage(content="s0")])

        with patch(
            "app.utils.file_utils.local_document_parser.extract_office_document",
            return_value="CONFIDENTIAL preamble\n\n# Section One\nbody one\n\n# Section Two\nbody two",
        ):
            result = await processor.process_office_document(b"data", suffix=".docx")

        assert len(result) == 1
        assert "CONFIDENTIAL preamble" in result[0].data.content
        assert "Section One" in result[0].data.content

    async def test_empty_document_returns_no_chunks(self, processor: DocumentProcessor) -> None:
        """An empty/whitespace-only extraction must not trigger an LLM call."""
        processor.llm = _mock_llm()

        with patch(
            "app.utils.file_utils.local_document_parser.extract_office_document",
            return_value="   \n\n  ",
        ):
            result = await processor.process_office_document(b"data", suffix=".csv")

        assert result == []
        processor.llm.abatch.assert_not_called()

    async def test_extraction_receives_bytes_and_suffix(self, processor: DocumentProcessor) -> None:
        """anydoc gets the raw bytes plus the format-carrying suffix; no temp file."""
        processor.llm = _mock_llm(batch_return=[AIMessage(content="Sum")])

        with patch(
            "app.utils.file_utils.local_document_parser.extract_office_document",
            return_value="content",
        ) as mock_extract:
            await processor.process_office_document(b"xlsx-bytes", suffix=".xlsx")

        mock_extract.assert_called_once_with(b"xlsx-bytes", ".xlsx")

    async def test_extraction_failure_propagates(self, processor: DocumentProcessor) -> None:
        with patch(
            "app.utils.file_utils.local_document_parser.extract_office_document",
            side_effect=RuntimeError("anydoc fail"),
        ):
            with pytest.raises(RuntimeError, match="anydoc fail"):
                await processor.process_office_document(b"bad-bytes", suffix=".pptx")

    async def test_office_extraction_timeout_propagates(self, processor: DocumentProcessor) -> None:
        """A local office-extraction timeout surfaces as TimeoutError."""
        with (
            patch("app.utils.file_utils.LOCAL_EXTRACTION_TIMEOUT_SECONDS", 0.01),
            patch(
                "app.utils.file_utils.local_document_parser.extract_office_document",
                side_effect=lambda _data, _suffix: _slow_block(),
            ),
        ):
            with pytest.raises(TimeoutError):
                await processor.process_office_document(b"slow-xlsx", suffix=".xlsx")


# ---------------------------------------------------------------------------
# _summarize_chunks
# ---------------------------------------------------------------------------


class TestSummarizeChunks:
    """Direct coverage of blank-filtering, truncation, and abatch wiring beyond
    what process_doc / process_office_document exercise incidentally."""

    async def test_blank_chunks_are_filtered_with_page_numbers_preserved(
        self, processor: DocumentProcessor
    ) -> None:
        processor.llm = _mock_llm(
            batch_return=[AIMessage(content="Summary 1"), AIMessage(content="Summary 3")]
        )

        result = await processor._summarize_chunks(["Page one", "   ", "Page three"])

        assert [r.data.page_number for r in result] == [1, 3]
        assert [r.data.content for r in result] == ["Page one", "Page three"]
        assert [r.summary for r in result] == ["Summary 1", "Summary 3"]

    async def test_all_blank_chunks_return_empty_without_an_llm_call(
        self, processor: DocumentProcessor
    ) -> None:
        processor.llm = _mock_llm()

        result = await processor._summarize_chunks(["", "   \n  "])

        assert result == []
        processor.llm.abatch.assert_not_called()

    async def test_no_chunks_returns_empty_without_an_llm_call(
        self, processor: DocumentProcessor
    ) -> None:
        processor.llm = _mock_llm()

        result = await processor._summarize_chunks([])

        assert result == []
        processor.llm.abatch.assert_not_called()

    async def test_truncates_at_max_indexed_chunks_and_appends_a_note(
        self, processor: DocumentProcessor, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(file_utils, "MAX_INDEXED_CHUNKS", 2)
        processor.llm = _mock_llm(batch_return=[AIMessage(content="s0"), AIMessage(content="s1")])

        chunks = ["chunk0", "chunk1", "chunk2"]
        result = await processor._summarize_chunks(chunks)

        assert len(result) == 3  # 2 indexed + 1 truncation note
        assert [r.data.page_number for r in result[:2]] == [1, 2]
        note = result[2]
        assert note.data.page_number == len(chunks) + 1
        assert note.data.content == note.summary
        assert "only the first 2 of 3" in note.summary

    async def test_passes_max_concurrency_to_abatch(self, processor: DocumentProcessor) -> None:
        processor.llm = _mock_llm(batch_return=[AIMessage(content="s0")])

        await processor._summarize_chunks(["chunk0"])

        _, kwargs = processor.llm.abatch.call_args
        assert kwargs["config"] == {"max_concurrency": SUMMARY_LLM_MAX_CONCURRENCY}


# ---------------------------------------------------------------------------
# _chunk_markdown
# ---------------------------------------------------------------------------


class TestChunkMarkdown:
    """MarkdownTextSplitter owns the actual cut-point logic; these assert the
    invariants _chunk_markdown promises (size bound, content preservation),
    not the library's internal choices."""

    def test_short_markdown_stays_a_single_chunk(self) -> None:
        """Multiple headings don't force a split when the whole doc fits the bound."""
        md = "# One\nbody one\n\n# Two\nbody two\n\n# Three\nbody three"
        assert file_utils._chunk_markdown(md) == [md]

    def test_oversized_markdown_is_split_within_the_size_bound(self) -> None:
        md = (
            "# One\n" + ("a" * 2000) + "\n\n# Two\n" + ("b" * 2000) + "\n\n# Three\n" + ("c" * 2000)
        )
        chunks = file_utils._chunk_markdown(md, max_chunk_chars=3000)
        assert len(chunks) > 1
        assert all(len(c) <= 3000 for c in chunks)
        assert _strip_ws("".join(chunks)) == _strip_ws(md)

    def test_preamble_before_first_heading_is_preserved(self) -> None:
        md = "intro text before any heading\n\n# One\nbody one\n\n# Two\nbody two"
        chunks = file_utils._chunk_markdown(md)
        assert "intro text before any heading" in "".join(chunks)

    def test_falls_back_to_fixed_size_slices_without_headings(self) -> None:
        md = "x" * 7000
        chunks = file_utils._chunk_markdown(md, max_chunk_chars=3000)
        assert all(len(c) <= 3000 for c in chunks)
        assert sum(len(c) for c in chunks) == 7000

    def test_empty_or_whitespace_markdown_returns_no_chunks(self) -> None:
        assert file_utils._chunk_markdown("") == []
        assert file_utils._chunk_markdown("   \n\n  ") == []


# ---------------------------------------------------------------------------
# process_text
# ---------------------------------------------------------------------------


class TestProcessText:
    async def test_success_returns_document_summary(self, processor: DocumentProcessor) -> None:
        processor.llm = _mock_llm(invoke_return="Text summary")

        result = await processor.process_text(b"Hello, this is plain text.")

        assert isinstance(result, DocumentSummaryModel)
        assert result.data.page_number == 1
        assert result.data.content == "Hello, this is plain text."
        assert result.summary == "Text summary"

    async def test_utf8_decode_errors_replaced(self, processor: DocumentProcessor) -> None:
        """Invalid UTF-8 bytes are replaced, not raised."""
        processor.llm = _mock_llm(invoke_return="summary")
        raw = b"hello \xff\xfe world"
        result = await processor.process_text(raw)
        # The content should contain replacement characters, not raise
        assert isinstance(result, DocumentSummaryModel)
        assert "hello" in result.data.content

    async def test_llm_failure_falls_through_to_fallback_summary(
        self, processor: DocumentProcessor
    ) -> None:
        """_generate_text_summary catches LLM errors and returns a fallback string,
        so process_text succeeds but the summary is the fallback message."""
        processor.llm = _mock_llm()
        processor.llm.ainvoke.side_effect = RuntimeError("LLM error")

        result = await processor.process_text(b"some text")
        assert isinstance(result, DocumentSummaryModel)
        assert "could not be generated" in result.summary

    async def test_model_validation_error_is_reraised(self, processor: DocumentProcessor) -> None:
        """If DocumentSummaryModel construction fails, the error propagates."""
        processor.llm = _mock_llm(invoke_return="summary")

        with patch(
            "app.utils.file_utils.DocumentSummaryModel",
            side_effect=RuntimeError("validation boom"),
        ):
            with pytest.raises(RuntimeError, match="validation boom"):
                await processor.process_text(b"data")

    async def test_text_truncated_to_4000_chars_for_summary(
        self, processor: DocumentProcessor
    ) -> None:
        """The summary prompt receives at most 4000 characters."""
        processor.llm = _mock_llm(invoke_return="summary")
        long_text = ("x" * 5000).encode("utf-8")

        await processor.process_text(long_text)

        # Verify _generate_text_summary was called with truncated text
        call_args = processor.llm.ainvoke.call_args
        user_content = call_args[0][0][1]["content"]
        # The text in the prompt should be <= 4000 chars from the source
        # (the prompt wrapping adds more, but the source slice is 4000)
        assert "x" * 4000 in user_content
        assert "x" * 4001 not in user_content

    async def test_summary_uses_the_helper_llm_wired_at_construction(self) -> None:
        """A freshly built processor summarizes with get_helper_llm's model."""
        helper = _mock_llm(invoke_return="Helper summary")
        with (
            patch("app.utils.file_utils.LlamaParse"),
            patch("app.utils.file_utils.get_helper_llm", return_value=helper),
        ):
            proc = DocumentProcessor(user_id="u-test")

        result = await proc.process_text(b"some text")

        assert isinstance(result, DocumentSummaryModel)
        assert result.summary == "Helper summary"
        helper.ainvoke.assert_awaited_once()


# ---------------------------------------------------------------------------
# _generate_text_summary
# ---------------------------------------------------------------------------


class TestGenerateTextSummary:
    async def test_returns_string_summary(self, processor: DocumentProcessor) -> None:
        processor.llm = _mock_llm(invoke_return="A concise summary")
        result = await processor._generate_text_summary("Some text to summarize")
        assert result == "A concise summary"

    async def test_list_content_blocks_flattened(self, processor: DocumentProcessor) -> None:
        """Gemini returns content as a list of blocks; ``.text`` flattens it to a string."""
        processor.llm = _mock_llm(
            invoke_return=AIMessage(
                content=[
                    {"type": "text", "text": "A concise "},
                    {"type": "text", "text": "summary"},
                ]
            )
        )
        result = await processor._generate_text_summary("text")
        assert result == "A concise summary"

    async def test_exception_returns_fallback(self, processor: DocumentProcessor) -> None:
        processor.llm = _mock_llm()
        processor.llm.ainvoke.side_effect = RuntimeError("LLM down")
        result = await processor._generate_text_summary("text")
        assert "could not be generated" in result


# ---------------------------------------------------------------------------
# generate_file_summary (module-level convenience function)
# ---------------------------------------------------------------------------


class TestGenerateFileSummary:
    @patch("app.utils.file_utils.DocumentProcessor")
    async def test_delegates_to_processor(self, mock_proc_cls: MagicMock) -> None:
        mock_instance = AsyncMock()
        mock_instance.process_file = AsyncMock(return_value="summary result")
        mock_proc_cls.return_value = mock_instance

        result = await generate_file_summary(
            file_content=b"data",
            content_type="text/plain",
            filename="readme.txt",
            user_id="u-test",
        )

        mock_instance.process_file.assert_awaited_once_with(
            file_content=b"data",
            content_type="text/plain",
            filename="readme.txt",
        )
        assert result == "summary result"

    @patch("app.utils.file_utils.DocumentProcessor")
    async def test_creates_new_processor_each_call(self, mock_proc_cls: MagicMock) -> None:
        mock_instance = AsyncMock()
        mock_instance.process_file = AsyncMock(return_value="")
        mock_proc_cls.return_value = mock_instance

        await generate_file_summary(b"a", "text/plain", "a.txt", user_id="u-test")
        await generate_file_summary(b"b", "text/plain", "b.txt", user_id="u-test")

        assert mock_proc_cls.call_count == 2
