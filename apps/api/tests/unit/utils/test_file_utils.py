"""Unit tests for app.utils.file_utils (DocumentProcessor & generate_file_summary)."""

import base64
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.models.files_models import DocumentPageModel, DocumentSummaryModel
from app.utils.file_utils import DocumentProcessor, generate_file_summary


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _mock_llm(
    invoke_return: Any = "Mock summary", batch_return: Any = None
) -> AsyncMock:
    """Return an AsyncMock LLM with configurable ainvoke/abatch responses."""
    llm = AsyncMock()
    llm.ainvoke = AsyncMock(return_value=invoke_return)
    llm.abatch = AsyncMock(return_value=batch_return or [])
    return llm


def _make_md_document(text: str) -> MagicMock:
    doc = MagicMock()
    doc.text = text
    return doc


# ---------------------------------------------------------------------------
# DocumentProcessor.__init__ is patched in all tests to avoid real
# LlamaParse / LLM initialization.
# ---------------------------------------------------------------------------


@pytest.fixture
def processor() -> DocumentProcessor:
    """Return a DocumentProcessor with mocked parser and llm."""
    with (
        patch("app.utils.file_utils.LlamaParse"),
        patch("app.utils.file_utils.init_llm", return_value=_mock_llm()),
    ):
        proc = DocumentProcessor()
    return proc


# ---------------------------------------------------------------------------
# process_file — routing by content type
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestProcessFileRouting:
    """Verify that process_file routes to the correct sub-processor."""

    async def test_image_routes_to_process_image(
        self, processor: DocumentProcessor
    ) -> None:
        processor.process_image = AsyncMock(return_value="image desc")  # type: ignore[method-assign]
        result = await processor.process_file(b"imgdata", "image/png", "photo.png")
        processor.process_image.assert_awaited_once_with(b"imgdata")
        assert result == "image desc"

    @pytest.mark.parametrize("content_type", ["image/jpeg", "image/gif", "image/webp"])
    async def test_various_image_types_route_to_process_image(
        self, processor: DocumentProcessor, content_type: str
    ) -> None:
        processor.process_image = AsyncMock(return_value="ok")  # type: ignore[method-assign]
        await processor.process_file(b"data", content_type, "file.img")
        processor.process_image.assert_awaited_once()

    async def test_pdf_routes_to_process_doc(
        self, processor: DocumentProcessor
    ) -> None:
        processor.process_doc = AsyncMock(return_value=[])  # type: ignore[method-assign]
        await processor.process_file(b"pdfdata", "application/pdf", "doc.pdf")
        processor.process_doc.assert_awaited_once_with(b"pdfdata")

    async def test_docx_routes_to_process_doc_with_suffix(
        self, processor: DocumentProcessor
    ) -> None:
        processor.process_doc = AsyncMock(return_value=[])  # type: ignore[method-assign]
        ctype = (
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        )
        await processor.process_file(b"docxdata", ctype, "doc.docx")
        processor.process_doc.assert_awaited_once_with(b"docxdata", suffix=".docx")

    async def test_text_routes_to_process_text(
        self, processor: DocumentProcessor
    ) -> None:
        processor.process_text = AsyncMock(  # type: ignore[method-assign]
            return_value=DocumentSummaryModel(
                data=DocumentPageModel(page_number=1, content="hello"),
                summary="summary",
            )
        )
        await processor.process_file(b"hello", "text/plain", "readme.txt")
        processor.process_text.assert_awaited_once_with(b"hello")

    @pytest.mark.parametrize("content_type", ["text/csv", "text/html", "text/markdown"])
    async def test_various_text_types_route_to_process_text(
        self, processor: DocumentProcessor, content_type: str
    ) -> None:
        processor.process_text = AsyncMock(  # type: ignore[method-assign]
            return_value=DocumentSummaryModel(
                data=DocumentPageModel(page_number=1, content="c"),
                summary="s",
            )
        )
        await processor.process_file(b"data", content_type, "file.txt")
        processor.process_text.assert_awaited_once()

    async def test_unknown_type_returns_fallback_string(
        self, processor: DocumentProcessor
    ) -> None:
        result = await processor.process_file(
            b"binary", "application/octet-stream", "data.bin"
        )
        assert isinstance(result, str)
        assert ".bin" in result
        assert "no content extraction" in result

    async def test_exception_returns_error_string(
        self, processor: DocumentProcessor
    ) -> None:
        processor.process_image = AsyncMock(side_effect=RuntimeError("boom"))  # type: ignore[method-assign]
        result = await processor.process_file(b"img", "image/png", "bad.png")
        assert isinstance(result, str)
        assert "File processing failed" in result
        assert "bad.png" in result


# ---------------------------------------------------------------------------
# process_image
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestProcessImage:
    async def test_success_returns_description(
        self, processor: DocumentProcessor
    ) -> None:
        processor.llm = _mock_llm(invoke_return="A scenic mountain view")
        result = await processor.process_image(b"\x89PNG\r\n")
        assert result == "A scenic mountain view"

    async def test_non_string_response_converted(
        self, processor: DocumentProcessor
    ) -> None:
        processor.llm = _mock_llm(invoke_return=12345)
        result = await processor.process_image(b"img")
        assert result == "12345"

    async def test_base64_encoding_in_prompt(
        self, processor: DocumentProcessor
    ) -> None:
        """Verify the image is base64-encoded in the LLM prompt."""
        raw = b"\x89PNG\r\n\x1a\n"
        expected_b64 = base64.b64encode(raw).decode("utf-8")
        processor.llm = _mock_llm(invoke_return="desc")

        await processor.process_image(raw)

        call_args = processor.llm.ainvoke.call_args
        content_blocks = call_args[1]["input"][0]["content"]
        image_block = [b for b in content_blocks if b["type"] == "image_url"][0]
        assert expected_b64 in image_block["image_url"]["url"]

    async def test_exception_returns_fallback(
        self, processor: DocumentProcessor
    ) -> None:
        processor.llm = _mock_llm()
        processor.llm.ainvoke.side_effect = RuntimeError("LLM down")
        result = await processor.process_image(b"data")
        assert "could not be generated" in result


# ---------------------------------------------------------------------------
# process_doc
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestProcessDoc:
    async def test_success_returns_list_of_summaries(
        self, processor: DocumentProcessor
    ) -> None:
        md_doc_1 = _make_md_document("Page 1 content")
        md_doc_2 = _make_md_document("Page 2 content")

        mock_parse_result = AsyncMock()
        mock_parse_result.aget_markdown_documents = AsyncMock(
            return_value=[md_doc_1, md_doc_2]
        )
        processor.parser = AsyncMock()
        processor.parser.aparse = AsyncMock(return_value=mock_parse_result)
        processor.llm = _mock_llm(batch_return=["Summary 1", "Summary 2"])

        result = await processor.process_doc(b"pdf-bytes")

        assert len(result) == 2
        assert isinstance(result[0], DocumentSummaryModel)
        assert result[0].data.page_number == 1
        assert result[0].data.content == "Page 1 content"
        assert result[0].summary == "Summary 1"
        assert result[1].data.page_number == 2

    async def test_aparse_returns_list_unwraps_first(
        self, processor: DocumentProcessor
    ) -> None:
        """When aparse returns a list, the first element is used."""
        md_doc = _make_md_document("Content")
        inner_result = AsyncMock()
        inner_result.aget_markdown_documents = AsyncMock(return_value=[md_doc])

        processor.parser = AsyncMock()
        processor.parser.aparse = AsyncMock(return_value=[inner_result])
        processor.llm = _mock_llm(batch_return=["Sum"])

        result = await processor.process_doc(b"data")

        assert len(result) == 1
        assert result[0].data.content == "Content"

    async def test_docx_suffix_used(self, processor: DocumentProcessor) -> None:
        """Verify temp file uses .docx suffix when specified."""
        md_doc = _make_md_document("Doc content")
        mock_result = AsyncMock()
        mock_result.aget_markdown_documents = AsyncMock(return_value=[md_doc])
        processor.parser = AsyncMock()
        processor.parser.aparse = AsyncMock(return_value=mock_result)
        processor.llm = _mock_llm(batch_return=["Sum"])

        with patch("app.utils.file_utils.tempfile.NamedTemporaryFile") as mock_tmp:
            mock_file = MagicMock()
            mock_file.name = "/tmp/fake.docx"  # noqa: S108
            mock_file.__enter__ = MagicMock(return_value=mock_file)
            mock_file.__exit__ = MagicMock(return_value=False)
            mock_tmp.return_value = mock_file

            with patch("app.utils.file_utils.os.remove"):
                await processor.process_doc(b"data", suffix=".docx")

            mock_tmp.assert_called_once_with(suffix=".docx", delete=False)

    async def test_exception_returns_empty_list(
        self, processor: DocumentProcessor
    ) -> None:
        processor.parser = AsyncMock()
        processor.parser.aparse = AsyncMock(side_effect=RuntimeError("parse fail"))

        result = await processor.process_doc(b"bad-pdf")

        assert result == []

    async def test_temp_file_cleaned_up(self, processor: DocumentProcessor) -> None:
        """os.remove is called even on success."""
        md_doc = _make_md_document("Content")
        mock_result = AsyncMock()
        mock_result.aget_markdown_documents = AsyncMock(return_value=[md_doc])
        processor.parser = AsyncMock()
        processor.parser.aparse = AsyncMock(return_value=mock_result)
        processor.llm = _mock_llm(batch_return=["Sum"])

        with patch("app.utils.file_utils.os.remove") as mock_remove:
            await processor.process_doc(b"data")
            mock_remove.assert_called_once()


# ---------------------------------------------------------------------------
# process_text
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestProcessText:
    async def test_success_returns_document_summary(
        self, processor: DocumentProcessor
    ) -> None:
        processor.llm = _mock_llm(invoke_return="Text summary")

        result = await processor.process_text(b"Hello, this is plain text.")

        assert isinstance(result, DocumentSummaryModel)
        assert result.data.page_number == 1
        assert result.data.content == "Hello, this is plain text."
        assert result.summary == "Text summary"

    async def test_utf8_decode_errors_replaced(
        self, processor: DocumentProcessor
    ) -> None:
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

    async def test_model_validation_error_is_reraised(
        self, processor: DocumentProcessor
    ) -> None:
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
        user_content = call_args[1]["input"][1]["content"]
        # The text in the prompt should be <= 4000 chars from the source
        # (the prompt wrapping adds more, but the source slice is 4000)
        assert "x" * 4000 in user_content
        assert "x" * 4001 not in user_content


# ---------------------------------------------------------------------------
# _generate_text_summary
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestGenerateTextSummary:
    async def test_returns_string_summary(self, processor: DocumentProcessor) -> None:
        processor.llm = _mock_llm(invoke_return="A concise summary")
        result = await processor._generate_text_summary("Some text to summarize")
        assert result == "A concise summary"

    async def test_non_string_response_converted(
        self, processor: DocumentProcessor
    ) -> None:
        processor.llm = _mock_llm(invoke_return=42)
        result = await processor._generate_text_summary("text")
        assert result == "42"

    async def test_exception_returns_fallback(
        self, processor: DocumentProcessor
    ) -> None:
        processor.llm = _mock_llm()
        processor.llm.ainvoke.side_effect = RuntimeError("LLM down")
        result = await processor._generate_text_summary("text")
        assert "could not be generated" in result


# ---------------------------------------------------------------------------
# generate_file_summary (module-level convenience function)
# ---------------------------------------------------------------------------


@pytest.mark.unit
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
        )

        mock_instance.process_file.assert_awaited_once_with(
            file_content=b"data",
            content_type="text/plain",
            filename="readme.txt",
        )
        assert result == "summary result"

    @patch("app.utils.file_utils.DocumentProcessor")
    async def test_creates_new_processor_each_call(
        self, mock_proc_cls: MagicMock
    ) -> None:
        mock_instance = AsyncMock()
        mock_instance.process_file = AsyncMock(return_value="")
        mock_proc_cls.return_value = mock_instance

        await generate_file_summary(b"a", "text/plain", "a.txt")
        await generate_file_summary(b"b", "text/plain", "b.txt")

        assert mock_proc_cls.call_count == 2
