"""Unit tests for app.agents.tools.document_tool."""

from typing import Any, Dict
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

FAKE_USER_ID = "507f1f77bcf86cd799439011"

MODULE = "app.agents.tools.document_tool"


def _make_config(user_id: str = FAKE_USER_ID) -> Dict[str, Any]:
    """Return a minimal RunnableConfig-like dict."""
    return {"metadata": {"user_id": user_id}}


def _writer_mock() -> MagicMock:
    return MagicMock()


def _make_doc_result(**overrides: Any) -> Dict[str, Any]:
    """Return a sample result dict from DocumentProcessor.generate_document."""
    defaults: Dict[str, Any] = {
        "filename": "test_document.pdf",
        "cloudinary_url": "https://res.cloudinary.com/demo/test.pdf",
        "is_plain_text": False,
        "title": "Test Document",
        "metadata": {"author": "Test User"},
        "font_size": 12,
        "pdf_config": None,
    }
    defaults.update(overrides)
    return defaults


# ---------------------------------------------------------------------------
# Tests: generate_document
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestGenerateDocument:
    """Tests for the generate_document tool."""

    @patch(f"{MODULE}.get_stream_writer")
    @patch(f"{MODULE}.DocumentProcessor")
    async def test_happy_path_pdf(
        self,
        mock_processor_cls: MagicMock,
        mock_writer_factory: MagicMock,
    ) -> None:
        """Successfully generates a PDF document."""
        writer = _writer_mock()
        mock_writer_factory.return_value = writer

        doc_result = _make_doc_result()
        mock_instance = MagicMock()
        mock_instance.generate_document = AsyncMock(return_value=doc_result)
        mock_processor_cls.return_value = mock_instance

        from app.agents.tools.document_tool import generate_document

        result = await generate_document.coroutine(
            config=_make_config(),
            content="# Hello World\nThis is my document.",
            filename="test_document",
            format="pdf",
            is_plain_text=False,
            title="Test Document",
        )

        assert "SUCCESS" in result
        assert "test_document.pdf" in result
        mock_processor_cls.assert_called_once()
        mock_instance.generate_document.assert_awaited_once_with(
            "# Hello World\nThis is my document."
        )
        writer.assert_called()

    @patch(f"{MODULE}.get_stream_writer")
    @patch(f"{MODULE}.DocumentProcessor")
    async def test_happy_path_plain_text(
        self,
        mock_processor_cls: MagicMock,
        mock_writer_factory: MagicMock,
    ) -> None:
        """Successfully generates a plain text file."""
        writer = _writer_mock()
        mock_writer_factory.return_value = writer

        doc_result = _make_doc_result(
            filename="script.py",
            is_plain_text=True,
            title=None,
            font_size=None,
        )
        mock_instance = MagicMock()
        mock_instance.generate_document = AsyncMock(return_value=doc_result)
        mock_processor_cls.return_value = mock_instance

        from app.agents.tools.document_tool import generate_document

        result = await generate_document.coroutine(
            config=_make_config(),
            content="print('hello')",
            filename="script",
            format="txt",
            is_plain_text=True,
        )

        assert "SUCCESS" in result
        mock_processor_cls.assert_called_once_with(
            filename="script",
            format="txt",
            is_plain_text=True,
            upload_to_cloudinary=True,
            title=None,
            metadata=None,
            font_size=None,
            pdf_config=None,
        )

    @patch(f"{MODULE}.get_stream_writer")
    @patch(f"{MODULE}.DocumentProcessor")
    async def test_streams_document_data_to_writer(
        self,
        mock_processor_cls: MagicMock,
        mock_writer_factory: MagicMock,
    ) -> None:
        """Verifies document_data is streamed to frontend."""
        writer = _writer_mock()
        mock_writer_factory.return_value = writer

        doc_result = _make_doc_result()
        mock_instance = MagicMock()
        mock_instance.generate_document = AsyncMock(return_value=doc_result)
        mock_processor_cls.return_value = mock_instance

        from app.agents.tools.document_tool import generate_document

        await generate_document.coroutine(
            config=_make_config(),
            content="content",
            filename="test",
            format="pdf",
            is_plain_text=False,
        )

        # Check writer was called with document_data payload
        calls = writer.call_args_list
        doc_data_calls = [c for c in calls if "document_data" in c[0][0]]
        assert len(doc_data_calls) == 1
        payload = doc_data_calls[0][0][0]["document_data"]
        assert payload["filename"] == "test_document.pdf"
        assert payload["url"] == "https://res.cloudinary.com/demo/test.pdf"

    @patch(f"{MODULE}.get_stream_writer")
    @patch(f"{MODULE}.DocumentProcessor")
    async def test_generation_failure_raises(
        self,
        mock_processor_cls: MagicMock,
        mock_writer_factory: MagicMock,
    ) -> None:
        """When document generation fails, an exception is raised."""
        mock_writer_factory.return_value = _writer_mock()
        mock_instance = MagicMock()
        mock_instance.generate_document = AsyncMock(
            side_effect=Exception("Pandoc not found")
        )
        mock_processor_cls.return_value = mock_instance

        from app.agents.tools.document_tool import generate_document

        with pytest.raises(Exception, match="Generation failed: Pandoc not found"):
            await generate_document.coroutine(
                config=_make_config(),
                content="content",
                filename="test",
                format="pdf",
                is_plain_text=False,
            )

    @patch(f"{MODULE}.get_stream_writer")
    @patch(f"{MODULE}.DocumentProcessor")
    async def test_with_pdf_config(
        self,
        mock_processor_cls: MagicMock,
        mock_writer_factory: MagicMock,
    ) -> None:
        """Passes pdf_config and font_size to the processor."""
        mock_writer_factory.return_value = _writer_mock()

        doc_result = _make_doc_result(font_size=14)
        mock_instance = MagicMock()
        mock_instance.generate_document = AsyncMock(return_value=doc_result)
        mock_processor_cls.return_value = mock_instance

        pdf_cfg = {"margins": "1in", "font_family": "Arial", "paper_size": "a4"}

        from app.agents.tools.document_tool import generate_document

        await generate_document.coroutine(
            config=_make_config(),
            content="content",
            filename="report",
            format="pdf",
            is_plain_text=False,
            title="My Report",
            font_size=14,
            pdf_config=pdf_cfg,
        )

        call_kwargs = mock_processor_cls.call_args.kwargs
        assert call_kwargs["font_size"] == 14
        assert call_kwargs["pdf_config"] == pdf_cfg
        assert call_kwargs["title"] == "My Report"

    @patch(f"{MODULE}.get_stream_writer")
    @patch(f"{MODULE}.DocumentProcessor")
    async def test_with_metadata(
        self,
        mock_processor_cls: MagicMock,
        mock_writer_factory: MagicMock,
    ) -> None:
        """Passes metadata through to processor."""
        mock_writer_factory.return_value = _writer_mock()

        meta = {"author": "Test User", "version": "1.0"}
        doc_result = _make_doc_result(metadata=meta)
        mock_instance = MagicMock()
        mock_instance.generate_document = AsyncMock(return_value=doc_result)
        mock_processor_cls.return_value = mock_instance

        from app.agents.tools.document_tool import generate_document

        await generate_document.coroutine(
            config=_make_config(),
            content="doc content",
            filename="test",
            format="docx",
            is_plain_text=False,
            metadata=meta,
        )

        call_kwargs = mock_processor_cls.call_args.kwargs
        assert call_kwargs["metadata"] == meta
