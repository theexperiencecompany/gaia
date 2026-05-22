from typing import Annotated, Any

from langchain_core.runnables import RunnableConfig
from langchain_core.tools import tool
from langgraph.config import get_stream_writer

from app.decorators import with_doc, with_rate_limiting
from app.templates.docstrings.document_tool_docs import (
    GENERATE_DOCUMENT,
)
from app.utils.document_utils import DocumentProcessor, PDFConfig
from shared.py.wide_events import log


@tool
@with_doc(docstring=GENERATE_DOCUMENT)
@with_rate_limiting("document_generation")
async def generate_document(
    config: RunnableConfig,
    content: Annotated[str, "Document content in markdown format"],
    filename: Annotated[str, "Output filename (without extension)"],
    format: Annotated[
        str,
        """Output format: 'txt', 'html', 'pdf', 'docx', 'odt', 'epub'
        For code/data: always use 'txt'.
        For formatted documents: use 'pdf' for printing, 'html' for web viewing, 'docx' for editing.
        """,
    ],
    is_plain_text: Annotated[
        bool,
        "ALWAYS True for: code files (py,js,html,css,json,xml,sql,etc), text files, data files, config files. ONLY False for: pdf,docx,odt,epub - documents requiring special formatting",
    ],
    title: Annotated[str | None, "Document title - ONLY used when is_plain_text=False"] = None,
    metadata: Annotated[
        dict[str, Any] | None,
        "Additional metadata - ONLY used when is_plain_text=False",
    ] = None,
    font_size: Annotated[
        int | None,
        "Font size in points (e.g., 12, 14, 50) - ONLY used for PDF generation",
    ] = None,
    pdf_config: Annotated[
        PDFConfig | None,
        """Simple PDF configuration options - ONLY used for PDF generation. Supports:
        - margins: str (e.g., '0.5in', '1cm') - page margins
        - font_family: str (e.g., 'Times New Roman', 'Arial') - main font
        - line_spacing: float (e.g., 1.0, 1.5, 2.0) - line spacing multiplier
        - paper_size: 'letter' or 'a4' - paper size
        - document_class: 'article' or 'report' - document type
        - table_of_contents: bool - include table of contents
        - number_sections: bool - number sections and subsections
        Note: Colored links are always enabled for better PDF readability.
        """,
    ] = None,
) -> str:
    try:
        log.set(tool={"name": "generate_document", "action": "generate"})
        processor = DocumentProcessor(
            filename=filename,
            format=format,
            is_plain_text=is_plain_text,
            upload_to_cloudinary=True,
            title=title,
            metadata=metadata,
            font_size=font_size,
            pdf_config=pdf_config,
        )

        result = await processor.generate_document(content)

        # Return the successfully processed events
        writer = get_stream_writer()

        # Send document data to frontend via writer
        writer(
            {
                "document_data": {
                    "filename": result["filename"],
                    "url": result.get("cloudinary_url"),
                    "is_plain_text": result["is_plain_text"],
                    "title": result["title"],
                    "metadata": result["metadata"],
                    "font_size": result["font_size"],
                    "pdf_config": result["pdf_config"],
                },
            }
        )

        log.info("Document generated and uploaded successfully")
        log.info(f"Document URL: {result.get('cloudinary_url')}")

        return f"SUCCESS: Document '{result['filename']}' has been generated and uploaded. The file is now available to the user through the frontend interface."

    except Exception as e:
        log.error(f"Error generating document: {e!s}")
        raise Exception(f"Generation failed: {e!s}")
