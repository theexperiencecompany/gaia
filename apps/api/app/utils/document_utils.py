"""
Document generation utilities with temporary file management.
"""

import asyncio
import os
import tempfile
from contextlib import asynccontextmanager
from typing import Any, Dict, Literal, Optional
from typing_extensions import TypedDict
from uuid import uuid4

import pypandoc

from app.config.loggers import app_logger as logger
from app.services.upload_service import upload_file_to_cloudinary


# Simplified PDF configuration
class PDFConfig(TypedDict, total=False):
    """Simplified PDF configuration with commonly used options."""

    margins: str  # e.g., "0.5in", "1cm"
    font_family: str  # e.g., "Times New Roman", "Arial"
    line_spacing: float  # e.g., 1.0, 1.5, 2.0
    paper_size: Literal["letter", "a4"]
    document_class: Literal["article", "report"]
    table_of_contents: bool
    number_sections: bool


class DocumentProcessor:
    """Document processing utility with temporary file management."""

    def __init__(
        self,
        filename: str,
        format: str,
        is_plain_text: bool = True,
        upload_to_cloudinary: bool = False,
        title: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
        font_size: Optional[int] = None,
        pdf_config: Optional[PDFConfig] = None,
    ):
        self.filename = filename
        self.format = format
        self.is_plain_text = is_plain_text
        self.upload_to_cloudinary = upload_to_cloudinary
        self.title = title
        self.metadata = metadata
        self.font_size = font_size
        self.pdf_config = pdf_config

        self.output_filename = f"{filename}.{format}"
        self.temp_path: Optional[str] = None
        self.cloudinary_url: Optional[str] = None

    @asynccontextmanager
    async def create_temp_file(self):
        """Context manager for temporary file creation and cleanup."""
        # Use secure temporary directory
        temp_dir = tempfile.gettempdir()
        self.temp_path = os.path.join(temp_dir, self.output_filename)

        try:
            logger.info(f"Creating temporary file: {self.temp_path}")
            yield self.temp_path
        finally:
            # Clean up temporary file
            if self.temp_path and os.path.exists(self.temp_path):
                try:
                    os.remove(self.temp_path)
                    logger.info(f"Cleaned up temporary file: {self.temp_path}")
                except Exception as e:
                    logger.warning(
                        f"Failed to clean up temporary file {self.temp_path}: {e}"
                    )

    async def generate_document(self, content: str) -> Dict[str, Any]:
        """
        Generate document with the provided content.

        Args:
            content: The content to write to the document

        Returns:
            Dictionary with generation results including file path and optional cloudinary URL
        """
        async with self.create_temp_file() as temp_path:
            if self.is_plain_text:
                await self._write_plain_text(temp_path, content)
            else:
                await self._generate_formatted_document(temp_path, content)

            result = {
                "filename": self.output_filename,
                "temp_path": temp_path,
                "is_plain_text": self.is_plain_text,
                "title": self.title,
                "metadata": self.metadata,
                "font_size": self.font_size,
                "pdf_config": self.pdf_config,
            }

            # Upload to Cloudinary if requested
            if self.upload_to_cloudinary:
                self.cloudinary_url = await self._upload_to_cloudinary(temp_path)
                result["cloudinary_url"] = self.cloudinary_url

            return result

    async def _write_plain_text(self, temp_path: str, content: str) -> None:
        """Write content directly to file for plain text documents."""
        await asyncio.to_thread(self._write_file_sync, temp_path, content)
        logger.info(f"Generated plain text document: {temp_path}")

    def _write_file_sync(self, temp_path: str, content: str) -> None:
        """Synchronous file writing helper."""
        with open(temp_path, "w", encoding="utf-8") as f:
            f.write(content)

    async def _generate_formatted_document(self, temp_path: str, content: str) -> None:
        """Generate formatted document using pypandoc."""
        extra_args = []

        if self.title:
            extra_args.extend(["-M", f"title={self.title}"])

        if self.metadata:
            for key, value in self.metadata.items():
                extra_args.extend(["-M", f"{key}={value}"])

        if self.format == "pdf":
            await self._configure_pdf_args(extra_args)

        # Generate document using pypandoc asynchronously
        await asyncio.to_thread(
            pypandoc.convert_text,
            source=content,
            to=self.format,
            format="md",
            outputfile=temp_path,
            extra_args=extra_args,
        )
        logger.info(f"Generated formatted document: {temp_path}")

    async def _configure_pdf_args(self, extra_args: list) -> None:
        """Configure PDF-specific arguments."""
        # Determine font size - use parameter if provided, otherwise default to 14pt
        pdf_font_size = self.font_size if self.font_size else 14

        # Base PDF configuration
        extra_args.extend(
            [
                "--pdf-engine=xelatex",
                "-V",
                f"fontsize={pdf_font_size}pt",
                "-V",
                "colorlinks=true",
                "-V",
                "linkcolor=blue",
                "-V",
                "urlcolor=blue",
                "-V",
                "citecolor=green",
            ]
        )

        # Apply pdf_config if provided
        if self.pdf_config:
            if "margins" in self.pdf_config:
                extra_args.extend(
                    ["-V", f"geometry:margin={self.pdf_config['margins']}"]
                )
            if "font_family" in self.pdf_config:
                extra_args.extend(["-V", f"mainfont={self.pdf_config['font_family']}"])
            if "line_spacing" in self.pdf_config:
                extra_args.extend(
                    ["-V", f"linestretch={self.pdf_config['line_spacing']}"]
                )
            if "paper_size" in self.pdf_config:
                extra_args.extend(["-V", f"papersize={self.pdf_config['paper_size']}"])
            if "document_class" in self.pdf_config:
                extra_args.extend(
                    ["-V", f"documentclass={self.pdf_config['document_class']}"]
                )

            # Handle boolean configurations
            if self.pdf_config.get("table_of_contents", False):
                extra_args.extend(["-V", "toc=true"])
            if self.pdf_config.get("number_sections", False):
                extra_args.extend(["-V", "numbersections=true"])

            # Set default margins if not specified
            if "margins" not in self.pdf_config:
                extra_args.extend(["-V", "geometry:margin=0.5in"])
        else:
            # Default configuration if no pdf_config provided
            extra_args.extend(["-V", "geometry:margin=0.5in"])

    async def _upload_to_cloudinary(self, temp_path: str) -> str:
        """Upload file to Cloudinary and return URL."""

        try:
            cloudinary_url = await asyncio.to_thread(
                upload_file_to_cloudinary,
                file_path=temp_path,
                public_id=f"{uuid4()}_{self.output_filename}",
            )
            logger.info(f"Uploaded to Cloudinary: {cloudinary_url}")
            return cloudinary_url
        except Exception as e:
            logger.error(f"Failed to upload to Cloudinary: {e}")
            raise


# Convenience functions for common use cases
async def generate_plain_text_document(
    filename: str,
    format: str,
    content: str,
    upload_to_cloudinary: bool = False,
) -> Dict[str, Any]:
    """Generate a plain text document."""
    processor = DocumentProcessor(
        filename=filename,
        format=format,
        is_plain_text=True,
        upload_to_cloudinary=upload_to_cloudinary,
    )
    return await processor.generate_document(content)


async def generate_formatted_document(
    filename: str,
    format: str,
    content: str,
    upload_to_cloudinary: bool = False,
    title: Optional[str] = None,
    metadata: Optional[Dict[str, Any]] = None,
    font_size: Optional[int] = None,
    pdf_config: Optional[PDFConfig] = None,
) -> Dict[str, Any]:
    """Generate a formatted document."""
    processor = DocumentProcessor(
        filename=filename,
        format=format,
        is_plain_text=False,
        upload_to_cloudinary=upload_to_cloudinary,
        title=title,
        metadata=metadata,
        font_size=font_size,
        pdf_config=pdf_config,
    )
    return await processor.generate_document(content)


@asynccontextmanager
async def create_temp_docx_file(filename: str, title: Optional[str] = None):
    """
    Context manager for creating temporary DOCX files from markdown content.
    Handles file creation, conversion, and cleanup automatically.

    Args:
        filename: Base filename (without extension)
        title: Document title for metadata

    Yields:
        Tuple[str, callable]: (temp_path, convert_function)
        - temp_path: Path to the temporary DOCX file
        - convert_function: Async function to convert markdown content to DOCX
    """
    processor = DocumentProcessor(
        filename=filename,
        format="docx",
        is_plain_text=False,
        upload_to_cloudinary=False,
        title=title,
    )

    async with processor.create_temp_file() as temp_path:

        async def convert_markdown(content: str) -> str:
            """Convert markdown content to DOCX and return the temp path."""
            if content:
                await processor._generate_formatted_document(temp_path, content)
            else:
                # Create empty DOCX file
                await processor._write_plain_text(temp_path, "")
            return temp_path

        yield temp_path, convert_markdown
