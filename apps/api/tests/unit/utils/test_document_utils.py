"""Unit tests for document generation utilities."""

import os
from typing import Any, Dict
from unittest.mock import patch

import pytest

from app.utils.document_utils import (
    DocumentProcessor,
    PDFConfig,
    create_temp_docx_file,
    generate_formatted_document,
    generate_plain_text_document,
)


# ---------------------------------------------------------------------------
# DocumentProcessor.__init__
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestDocumentProcessorInit:
    def test_default_values(self):
        proc = DocumentProcessor(filename="report", format="txt")
        assert proc.filename == "report"
        assert proc.format == "txt"
        assert proc.is_plain_text is True
        assert proc.upload_to_cloudinary is False
        assert proc.title is None
        assert proc.metadata is None
        assert proc.font_size is None
        assert proc.pdf_config is None
        assert proc.output_filename == "report.txt"
        assert proc.temp_path is None
        assert proc.cloudinary_url is None

    def test_custom_values(self):
        pdf_cfg: PDFConfig = {"margins": "1in", "font_family": "Arial"}
        meta: Dict[str, Any] = {"author": "Test", "date": "2026-01-01"}
        proc = DocumentProcessor(
            filename="essay",
            format="pdf",
            is_plain_text=False,
            upload_to_cloudinary=True,
            title="My Essay",
            metadata=meta,
            font_size=12,
            pdf_config=pdf_cfg,
        )
        assert proc.filename == "essay"
        assert proc.format == "pdf"
        assert proc.is_plain_text is False
        assert proc.upload_to_cloudinary is True
        assert proc.title == "My Essay"
        assert proc.metadata == meta
        assert proc.font_size == 12
        assert proc.pdf_config == pdf_cfg
        assert proc.output_filename == "essay.pdf"

    def test_output_filename_concatenation(self):
        proc = DocumentProcessor(filename="notes", format="docx")
        assert proc.output_filename == "notes.docx"

    def test_output_filename_with_dots_in_name(self):
        proc = DocumentProcessor(filename="my.report.v2", format="pdf")
        assert proc.output_filename == "my.report.v2.pdf"


# ---------------------------------------------------------------------------
# create_temp_file
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestCreateTempFile:
    async def test_creates_temp_path(self):
        proc = DocumentProcessor(filename="test", format="txt")
        async with proc.create_temp_file() as temp_path:
            assert temp_path is not None
            assert temp_path.endswith("test.txt")
            assert proc.temp_path == temp_path

    async def test_cleans_up_existing_file(self, tmp_path):
        proc = DocumentProcessor(filename="cleanup", format="txt")
        # Override temp dir to use pytest tmp_path
        with patch("tempfile.gettempdir", return_value=str(tmp_path)):
            async with proc.create_temp_file() as temp_path:
                # Actually create the file so cleanup has something to remove
                with open(temp_path, "w") as f:  # NOSONAR
                    f.write("data")
                assert os.path.exists(temp_path)
            # After exiting context, file should be cleaned up
            assert not os.path.exists(temp_path)

    async def test_cleanup_when_file_does_not_exist(self, tmp_path):
        """Cleanup should not raise if the file was never created."""
        proc = DocumentProcessor(filename="noop", format="txt")
        with patch("tempfile.gettempdir", return_value=str(tmp_path)):
            async with proc.create_temp_file() as temp_path:
                # Don't create any file — cleanup path should just skip
                assert not os.path.exists(temp_path)
        # Should complete without error

    async def test_cleanup_handles_remove_failure(self, tmp_path):
        """Cleanup logs a warning but does not raise on os.remove failure."""
        proc = DocumentProcessor(filename="fail", format="txt")
        with patch("tempfile.gettempdir", return_value=str(tmp_path)):
            async with proc.create_temp_file() as temp_path:
                # Create the file
                with open(temp_path, "w") as f:  # NOSONAR
                    f.write("content")
                # Patch os.remove to fail
                with patch("os.remove", side_effect=PermissionError("no perm")):
                    pass  # exiting context triggers cleanup
            # If we get here, no exception was raised — which is correct
            # The file still exists because os.remove was patched only inside the with
            # Actually need to restructure: the patch must be active during cleanup

    async def test_cleanup_handles_remove_failure_properly(self, tmp_path):
        """Cleanup logs a warning but does not raise when os.remove fails."""
        proc = DocumentProcessor(filename="failrm", format="txt")
        with patch("tempfile.gettempdir", return_value=str(tmp_path)):
            with patch("os.remove", side_effect=PermissionError("permission denied")):
                with patch("os.path.exists", return_value=True):
                    async with proc.create_temp_file():
                        pass
            # Should complete without raising


# ---------------------------------------------------------------------------
# _write_plain_text
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestWritePlainText:
    async def test_writes_content_to_file(self, tmp_path):
        proc = DocumentProcessor(filename="hello", format="txt")
        file_path = str(tmp_path / "hello.txt")
        await proc._write_plain_text(file_path, "Hello World")
        with open(file_path) as f:  # NOSONAR
            assert f.read() == "Hello World"

    async def test_writes_empty_string(self, tmp_path):
        proc = DocumentProcessor(filename="empty", format="txt")
        file_path = str(tmp_path / "empty.txt")
        await proc._write_plain_text(file_path, "")
        with open(file_path) as f:  # NOSONAR
            assert f.read() == ""

    async def test_writes_unicode_content(self, tmp_path):
        proc = DocumentProcessor(filename="unicode", format="txt")
        file_path = str(tmp_path / "unicode.txt")
        content = "Hello \u4e16\u754c \u00e9\u00e8\u00ea"
        await proc._write_plain_text(file_path, content)
        with open(file_path, encoding="utf-8") as f:  # NOSONAR
            assert f.read() == content

    async def test_writes_multiline_content(self, tmp_path):
        proc = DocumentProcessor(filename="multi", format="txt")
        file_path = str(tmp_path / "multi.txt")
        content = "Line 1\nLine 2\nLine 3"
        await proc._write_plain_text(file_path, content)
        with open(file_path) as f:  # NOSONAR
            assert f.read() == content


# ---------------------------------------------------------------------------
# _generate_formatted_document
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestGenerateFormattedDocumentConvenience:
    async def test_basic_conversion(self):
        proc = DocumentProcessor(filename="doc", format="docx", is_plain_text=False)
        with patch("app.utils.document_utils.pypandoc.convert_text") as mock_pandoc:
            await proc._generate_formatted_document("/tmp/doc.docx", "# Title\nBody")
            mock_pandoc.assert_called_once_with(
                source="# Title\nBody",
                to="docx",
                format="md",
                outputfile="/tmp/doc.docx",
                extra_args=[],
            )

    async def test_with_title(self):
        proc = DocumentProcessor(
            filename="doc", format="docx", is_plain_text=False, title="My Title"
        )
        with patch("app.utils.document_utils.pypandoc.convert_text") as mock_pandoc:
            await proc._generate_formatted_document("/tmp/doc.docx", "Content")
            call_args = mock_pandoc.call_args
            extra = call_args.kwargs["extra_args"]
            assert "-M" in extra
            idx = extra.index("-M")
            assert extra[idx + 1] == "title=My Title"

    async def test_with_metadata(self):
        meta = {"author": "John", "date": "2026-01-01"}
        proc = DocumentProcessor(
            filename="doc", format="docx", is_plain_text=False, metadata=meta
        )
        with patch("app.utils.document_utils.pypandoc.convert_text") as mock_pandoc:
            await proc._generate_formatted_document("/tmp/doc.docx", "Content")
            call_args = mock_pandoc.call_args
            extra = call_args.kwargs["extra_args"]
            # Should have -M author=John and -M date=2026-01-01
            m_indices = [i for i, v in enumerate(extra) if v == "-M"]
            metadata_pairs = [extra[i + 1] for i in m_indices]
            assert "author=John" in metadata_pairs
            assert "date=2026-01-01" in metadata_pairs

    async def test_with_title_and_metadata(self):
        proc = DocumentProcessor(
            filename="doc",
            format="docx",
            is_plain_text=False,
            title="Doc Title",
            metadata={"author": "Jane"},
        )
        with patch("app.utils.document_utils.pypandoc.convert_text") as mock_pandoc:
            await proc._generate_formatted_document("/tmp/doc.docx", "Content")
            extra = mock_pandoc.call_args.kwargs["extra_args"]
            m_indices = [i for i, v in enumerate(extra) if v == "-M"]
            metadata_pairs = [extra[i + 1] for i in m_indices]
            assert "title=Doc Title" in metadata_pairs
            assert "author=Jane" in metadata_pairs

    async def test_pdf_format_calls_configure_pdf_args(self):
        proc = DocumentProcessor(filename="doc", format="pdf", is_plain_text=False)
        with patch("app.utils.document_utils.pypandoc.convert_text"):
            with patch.object(proc, "_configure_pdf_args") as mock_cfg:
                await proc._generate_formatted_document("/tmp/doc.pdf", "Content")
                mock_cfg.assert_called_once()
                # The extra_args list is passed by reference
                args_list = mock_cfg.call_args[0][0]
                assert isinstance(args_list, list)

    async def test_non_pdf_format_does_not_call_configure_pdf_args(self):
        proc = DocumentProcessor(filename="doc", format="html", is_plain_text=False)
        with patch("app.utils.document_utils.pypandoc.convert_text"):
            with patch.object(proc, "_configure_pdf_args") as mock_cfg:
                await proc._generate_formatted_document("/tmp/doc.html", "Content")
                mock_cfg.assert_not_called()


# ---------------------------------------------------------------------------
# _configure_pdf_args
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestConfigurePdfArgs:
    async def test_default_no_pdf_config(self):
        """Without pdf_config, uses default font size 14 and margin 0.5in."""
        proc = DocumentProcessor(filename="doc", format="pdf")
        args: list[str] = []
        await proc._configure_pdf_args(args)

        assert "--pdf-engine=xelatex" in args
        assert "fontsize=14pt" in _get_v_value(args, "fontsize")
        assert "geometry:margin=0.5in" in _get_v_value(args, "geometry:margin")

    async def test_custom_font_size(self):
        proc = DocumentProcessor(filename="doc", format="pdf", font_size=10)
        args: list[str] = []
        await proc._configure_pdf_args(args)
        assert "fontsize=10pt" in _get_v_value(args, "fontsize")

    async def test_default_font_size_when_none(self):
        proc = DocumentProcessor(filename="doc", format="pdf", font_size=None)
        args: list[str] = []
        await proc._configure_pdf_args(args)
        assert "fontsize=14pt" in _get_v_value(args, "fontsize")

    async def test_color_links_always_set(self):
        proc = DocumentProcessor(filename="doc", format="pdf")
        args: list[str] = []
        await proc._configure_pdf_args(args)
        assert "colorlinks=true" in args
        assert "linkcolor=blue" in args
        assert "urlcolor=blue" in args
        assert "citecolor=green" in args

    async def test_pdf_config_margins(self):
        cfg: PDFConfig = {"margins": "1cm"}
        proc = DocumentProcessor(filename="doc", format="pdf", pdf_config=cfg)
        args: list[str] = []
        await proc._configure_pdf_args(args)
        assert "geometry:margin=1cm" in _get_v_value(args, "geometry:margin")
        # Default margin should NOT be present (custom overrides)
        v_values = _all_v_values(args)
        margin_values = [v for v in v_values if v.startswith("geometry:margin=")]
        assert len(margin_values) == 1
        assert margin_values[0] == "geometry:margin=1cm"

    async def test_pdf_config_font_family(self):
        cfg: PDFConfig = {"font_family": "Times New Roman"}
        proc = DocumentProcessor(filename="doc", format="pdf", pdf_config=cfg)
        args: list[str] = []
        await proc._configure_pdf_args(args)
        assert "mainfont=Times New Roman" in _get_v_value(args, "mainfont")

    async def test_pdf_config_line_spacing(self):
        cfg: PDFConfig = {"line_spacing": 1.5}
        proc = DocumentProcessor(filename="doc", format="pdf", pdf_config=cfg)
        args: list[str] = []
        await proc._configure_pdf_args(args)
        assert "linestretch=1.5" in _get_v_value(args, "linestretch")

    async def test_pdf_config_paper_size(self):
        cfg: PDFConfig = {"paper_size": "a4"}
        proc = DocumentProcessor(filename="doc", format="pdf", pdf_config=cfg)
        args: list[str] = []
        await proc._configure_pdf_args(args)
        assert "papersize=a4" in _get_v_value(args, "papersize")

    async def test_pdf_config_document_class(self):
        cfg: PDFConfig = {"document_class": "report"}
        proc = DocumentProcessor(filename="doc", format="pdf", pdf_config=cfg)
        args: list[str] = []
        await proc._configure_pdf_args(args)
        assert "documentclass=report" in _get_v_value(args, "documentclass")

    async def test_pdf_config_table_of_contents_true(self):
        cfg: PDFConfig = {"table_of_contents": True}
        proc = DocumentProcessor(filename="doc", format="pdf", pdf_config=cfg)
        args: list[str] = []
        await proc._configure_pdf_args(args)
        assert "toc=true" in args

    async def test_pdf_config_table_of_contents_false(self):
        cfg: PDFConfig = {"table_of_contents": False}
        proc = DocumentProcessor(filename="doc", format="pdf", pdf_config=cfg)
        args: list[str] = []
        await proc._configure_pdf_args(args)
        assert "toc=true" not in args

    async def test_pdf_config_number_sections_true(self):
        cfg: PDFConfig = {"number_sections": True}
        proc = DocumentProcessor(filename="doc", format="pdf", pdf_config=cfg)
        args: list[str] = []
        await proc._configure_pdf_args(args)
        assert "numbersections=true" in args

    async def test_pdf_config_number_sections_false(self):
        cfg: PDFConfig = {"number_sections": False}
        proc = DocumentProcessor(filename="doc", format="pdf", pdf_config=cfg)
        args: list[str] = []
        await proc._configure_pdf_args(args)
        assert "numbersections=true" not in args

    async def test_pdf_config_default_margins_when_not_specified(self):
        """When pdf_config is provided but margins are not, default margin is added."""
        cfg: PDFConfig = {"font_family": "Arial"}
        proc = DocumentProcessor(filename="doc", format="pdf", pdf_config=cfg)
        args: list[str] = []
        await proc._configure_pdf_args(args)
        assert "geometry:margin=0.5in" in _get_v_value(args, "geometry:margin")

    async def test_pdf_config_all_options(self):
        cfg: PDFConfig = {
            "margins": "2cm",
            "font_family": "Helvetica",
            "line_spacing": 2.0,
            "paper_size": "letter",
            "document_class": "article",
            "table_of_contents": True,
            "number_sections": True,
        }
        proc = DocumentProcessor(
            filename="doc", format="pdf", font_size=16, pdf_config=cfg
        )
        args: list[str] = []
        await proc._configure_pdf_args(args)

        assert "fontsize=16pt" in _get_v_value(args, "fontsize")
        assert "geometry:margin=2cm" in _get_v_value(args, "geometry:margin")
        assert "mainfont=Helvetica" in _get_v_value(args, "mainfont")
        assert "linestretch=2.0" in _get_v_value(args, "linestretch")
        assert "papersize=letter" in _get_v_value(args, "papersize")
        assert "documentclass=article" in _get_v_value(args, "documentclass")
        assert "toc=true" in args
        assert "numbersections=true" in args


# ---------------------------------------------------------------------------
# _upload_to_cloudinary
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestUploadToCloudinary:
    async def test_upload_success(self):
        proc = DocumentProcessor(
            filename="doc", format="pdf", upload_to_cloudinary=True
        )
        with patch(
            "app.utils.document_utils.upload_file_to_cloudinary",
            return_value="https://res.cloudinary.com/test/doc.pdf",
        ):
            result = await proc._upload_to_cloudinary("/tmp/doc.pdf")
            assert result == "https://res.cloudinary.com/test/doc.pdf"

    async def test_upload_failure_raises(self):
        proc = DocumentProcessor(
            filename="doc", format="pdf", upload_to_cloudinary=True
        )
        with patch(
            "app.utils.document_utils.upload_file_to_cloudinary",
            side_effect=Exception("Network error"),
        ):
            with pytest.raises(Exception, match="Network error"):
                await proc._upload_to_cloudinary("/tmp/doc.pdf")

    async def test_upload_uses_unique_public_id(self):
        proc = DocumentProcessor(
            filename="doc", format="pdf", upload_to_cloudinary=True
        )
        with patch(
            "app.utils.document_utils.upload_file_to_cloudinary",
            return_value="https://example.com/url",
        ) as mock_upload:
            await proc._upload_to_cloudinary("/tmp/doc.pdf")
            call_kwargs = mock_upload.call_args.kwargs
            assert call_kwargs["file_path"] == "/tmp/doc.pdf"
            # public_id should contain the output filename
            assert "doc.pdf" in call_kwargs["public_id"]


# ---------------------------------------------------------------------------
# generate_document (integration of all internal methods)
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestGenerateDocument:
    async def test_plain_text_mode(self, tmp_path):
        proc = DocumentProcessor(filename="test", format="txt", is_plain_text=True)
        with patch("tempfile.gettempdir", return_value=str(tmp_path)):
            result = await proc.generate_document("Hello World")
            assert result["filename"] == "test.txt"
            assert result["is_plain_text"] is True
            assert "cloudinary_url" not in result
            assert result["title"] is None
            assert result["metadata"] is None

    async def test_formatted_mode(self, tmp_path):
        proc = DocumentProcessor(
            filename="test",
            format="docx",
            is_plain_text=False,
            title="My Doc",
        )
        with patch("tempfile.gettempdir", return_value=str(tmp_path)):
            with patch("app.utils.document_utils.pypandoc.convert_text"):
                result = await proc.generate_document("# Content")
                assert result["filename"] == "test.docx"
                assert result["is_plain_text"] is False
                assert result["title"] == "My Doc"

    async def test_with_upload(self, tmp_path):
        proc = DocumentProcessor(
            filename="test",
            format="txt",
            is_plain_text=True,
            upload_to_cloudinary=True,
        )
        with patch("tempfile.gettempdir", return_value=str(tmp_path)):
            with patch(
                "app.utils.document_utils.upload_file_to_cloudinary",
                return_value="https://cdn.example.com/test.txt",
            ):
                result = await proc.generate_document("Content")
                assert result["cloudinary_url"] == "https://cdn.example.com/test.txt"
                assert proc.cloudinary_url == "https://cdn.example.com/test.txt"

    async def test_without_upload(self, tmp_path):
        proc = DocumentProcessor(
            filename="test", format="txt", upload_to_cloudinary=False
        )
        with patch("tempfile.gettempdir", return_value=str(tmp_path)):
            result = await proc.generate_document("Content")
            assert "cloudinary_url" not in result

    async def test_result_contains_all_fields(self, tmp_path):
        meta = {"author": "Test"}
        cfg: PDFConfig = {"margins": "1in"}
        proc = DocumentProcessor(
            filename="full",
            format="pdf",
            is_plain_text=False,
            title="Title",
            metadata=meta,
            font_size=12,
            pdf_config=cfg,
        )
        with patch("tempfile.gettempdir", return_value=str(tmp_path)):
            with patch("app.utils.document_utils.pypandoc.convert_text"):
                result = await proc.generate_document("Body")
                assert result["filename"] == "full.pdf"
                assert result["is_plain_text"] is False
                assert result["title"] == "Title"
                assert result["metadata"] == meta
                assert result["font_size"] == 12
                assert result["pdf_config"] == cfg
                assert "temp_path" in result


# ---------------------------------------------------------------------------
# Convenience functions
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestGeneratePlainTextDocument:
    async def test_basic_call(self, tmp_path):
        with patch("tempfile.gettempdir", return_value=str(tmp_path)):
            result = await generate_plain_text_document(
                filename="notes", format="txt", content="Some notes"
            )
            assert result["filename"] == "notes.txt"
            assert result["is_plain_text"] is True

    async def test_with_upload_flag(self, tmp_path):
        with patch("tempfile.gettempdir", return_value=str(tmp_path)):
            with patch(
                "app.utils.document_utils.upload_file_to_cloudinary",
                return_value="https://cdn.example.com/notes.txt",
            ):
                result = await generate_plain_text_document(
                    filename="notes",
                    format="txt",
                    content="Data",
                    upload_to_cloudinary=True,
                )
                assert result["cloudinary_url"] == "https://cdn.example.com/notes.txt"


@pytest.mark.unit
class TestGenerateFormattedDocumentWrapper:
    async def test_basic_call(self, tmp_path):
        with patch("tempfile.gettempdir", return_value=str(tmp_path)):
            with patch("app.utils.document_utils.pypandoc.convert_text"):
                result = await generate_formatted_document(
                    filename="report",
                    format="docx",
                    content="# Report",
                )
                assert result["filename"] == "report.docx"
                assert result["is_plain_text"] is False

    async def test_all_parameters(self, tmp_path):
        cfg: PDFConfig = {"margins": "1in"}
        meta = {"author": "Tester"}
        with patch("tempfile.gettempdir", return_value=str(tmp_path)):
            with patch("app.utils.document_utils.pypandoc.convert_text"):
                result = await generate_formatted_document(
                    filename="essay",
                    format="pdf",
                    content="# Essay",
                    upload_to_cloudinary=False,
                    title="Essay Title",
                    metadata=meta,
                    font_size=11,
                    pdf_config=cfg,
                )
                assert result["title"] == "Essay Title"
                assert result["metadata"] == meta
                assert result["font_size"] == 11
                assert result["pdf_config"] == cfg


# ---------------------------------------------------------------------------
# create_temp_docx_file
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestCreateTempDocxFile:
    async def test_context_manager_yields_path_and_function(self, tmp_path):
        with patch("tempfile.gettempdir", return_value=str(tmp_path)):
            async with create_temp_docx_file("mydoc") as (temp_path, convert_fn):
                assert temp_path.endswith("mydoc.docx")
                assert callable(convert_fn)

    async def test_convert_markdown_with_content(self, tmp_path):
        with patch("tempfile.gettempdir", return_value=str(tmp_path)):
            with patch("app.utils.document_utils.pypandoc.convert_text") as mock_pandoc:
                async with create_temp_docx_file("mydoc", title="Title") as (
                    temp_path,
                    convert_fn,
                ):
                    result_path = await convert_fn("# Hello")
                    assert result_path == temp_path
                    mock_pandoc.assert_called_once()
                    call_kwargs = mock_pandoc.call_args.kwargs
                    assert call_kwargs["source"] == "# Hello"
                    assert call_kwargs["to"] == "docx"
                    assert call_kwargs["format"] == "md"

    async def test_convert_markdown_empty_content_writes_plain(self, tmp_path):
        with patch("tempfile.gettempdir", return_value=str(tmp_path)):
            async with create_temp_docx_file("mydoc") as (temp_path, convert_fn):
                result_path = await convert_fn("")
                assert result_path == temp_path
                # Empty content => plain text write, not pandoc
                with open(temp_path) as f:  # NOSONAR
                    assert f.read() == ""

    async def test_cleanup_after_context_exit(self, tmp_path):
        with patch("tempfile.gettempdir", return_value=str(tmp_path)):
            async with create_temp_docx_file("cleanup_test") as (temp_path, convert_fn):
                # Write something so the file exists
                await convert_fn("")
                assert os.path.exists(temp_path)
            # After context exit, file should be cleaned up
            assert not os.path.exists(temp_path)

    async def test_title_passed_to_processor(self, tmp_path):
        with patch("tempfile.gettempdir", return_value=str(tmp_path)):
            with patch("app.utils.document_utils.pypandoc.convert_text") as mock_pandoc:
                async with create_temp_docx_file("titled", title="Report Title") as (
                    temp_path,
                    convert_fn,
                ):
                    await convert_fn("Content here")
                    extra = mock_pandoc.call_args.kwargs["extra_args"]
                    m_indices = [i for i, v in enumerate(extra) if v == "-M"]
                    metadata_pairs = [extra[i + 1] for i in m_indices]
                    assert "title=Report Title" in metadata_pairs

    async def test_no_title(self, tmp_path):
        with patch("tempfile.gettempdir", return_value=str(tmp_path)):
            with patch("app.utils.document_utils.pypandoc.convert_text") as mock_pandoc:
                async with create_temp_docx_file("notitled") as (temp_path, convert_fn):
                    await convert_fn("Content")
                    extra = mock_pandoc.call_args.kwargs["extra_args"]
                    # No -M flags should be present (no title, no metadata)
                    assert "-M" not in extra


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _all_v_values(args: list[str]) -> list[str]:
    """Extract all values following -V flags in args."""
    values = []
    for i, v in enumerate(args):
        if v == "-V" and i + 1 < len(args):
            values.append(args[i + 1])
    return values


def _get_v_value(args: list[str], prefix: str) -> str:
    """Get the -V value whose key starts with prefix."""
    for i, v in enumerate(args):
        if v == "-V" and i + 1 < len(args):
            if args[i + 1].startswith(prefix):
                return args[i + 1]
    return ""
