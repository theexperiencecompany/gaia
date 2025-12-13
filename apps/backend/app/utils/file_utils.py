"""
Document summarization system using LlamaIndex for PDF/DOCX and LlamaCloud for images/text.
This module integrates with ChromaDB for vector storage and retrieval.
"""

import base64
import os
import tempfile
from typing import List, Union

from llama_cloud_services import LlamaParse
from llama_cloud_services.parse.utils import ResultType

from app.agents.llm.client import init_llm
from app.config.loggers import app_logger as logger
from app.config.settings import settings
from app.models.files_models import DocumentPageModel, DocumentSummaryModel


class DocumentProcessor:
    """Document processing and summarization using LlamaIndex and LlamaCloud."""

    def __init__(self):
        """Initialize the document processor with necessary components."""
        # Initialize LlamaCloud client
        self.parser = LlamaParse(
            result_type=ResultType.MD,
            api_key=settings.LLAMA_INDEX_KEY or "",
        )
        self.llm = init_llm()

    async def process_file(
        self, file_content: bytes, content_type: str, filename: str
    ) -> Union[str, List[DocumentSummaryModel], DocumentSummaryModel]:
        """
        Process and summarize a file based on its content type.

        Args:
            file_content: Raw file bytes
            file_url: URL of the uploaded file
            content_type: MIME type of the file
            filename: Name of the file

        Returns:
            Appropriate summary based on file type
        """
        try:
            if content_type.startswith("image/"):
                return await self.process_image(file_content)
            elif content_type == "application/pdf":
                return await self.process_doc(file_content)
            elif (
                content_type
                == "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
            ):
                return await self.process_doc(file_content, suffix=".docx")
            elif content_type.startswith("text/"):
                return await self.process_text(file_content)
            else:
                ext = os.path.splitext(filename)[1].lower()
                return f"File of type {ext} (no content extraction available)"
        except Exception as e:
            logger.error(f"Failed to process file {filename}: {str(e)}", exc_info=True)
            return f"File processing failed for {filename}"

    async def process_image(self, image_data: bytes) -> str:
        """
        Process and summarize an image using LlamaCloud's vision model.

        Args:
            image_data: Raw image bytes
            image_url: URL of the image

        Returns:
            Summary of the image content
        """
        try:
            # Convert the image to base64 for the LLM
            base64_image = base64.b64encode(image_data).decode("utf-8")

            # Process with vision model
            response = await self.llm.ainvoke(
                input=[
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "text",
                                "text": """
                                Provide a concise summary of the content in this image. Assume it is part of a document like a PDF or DOCX, and ensure the summary is relevant for semantic search and accurately describes the image.

                                Note: Only respond with the summary text, without any additional information or context.""",
                            },
                            {
                                "type": "image_url",
                                "image_url": {
                                    "url": f"data:image/jpeg;base64,{base64_image}"
                                },
                            },
                        ],
                    }
                ],
            )

            description = response
            if not isinstance(description, str):
                description = str(description)
            return description

        except Exception as e:
            logger.error(f"Failed to process image: {str(e)}", exc_info=True)
            return "Image description could not be generated."

    async def process_doc(
        self,
        data: bytes,
        suffix: str = ".pdf",
    ) -> List[DocumentSummaryModel]:
        """
        Process a PDF file using LlamaIndex, extract page images, and generate summaries.

        Args:
            pdf_data: Raw PDF file bytes
            filename: Name of the PDF file

        Returns:
            List of DocumentSummaryModel with page images and summaries
        """
        try:
            # Save PDF to temporary file for LlamaIndex processing
            with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as temp_file:
                temp_path = temp_file.name
                temp_file.write(data)

            result = await self.parser.aparse(
                file_path=temp_path,
            )

            # Clean up temporary file
            os.remove(temp_path)

            if isinstance(result, list):
                result = result[0]

            md_documents = await result.aget_markdown_documents(split_by_page=True)

            summarized_pages = await self.llm.abatch(
                inputs=[
                    [
                        {
                            "role": "user",
                            "content": [
                                {
                                    "type": "text",
                                    "text": f"""Provide a concise summary of the content in given text. Assume it is part of a document like a PDF or DOCX, and ensure the summary is relevant for semantic search and accurately describes the content.
                                    Note: Only respond with the summary text, without any additional information or context.
                                    CONTENT:{md_documents[i].text}""",
                                },
                            ],
                        }
                    ]
                    for i in range(len(md_documents))
                ]
            )

            return [
                DocumentSummaryModel(
                    data=DocumentPageModel(
                        page_number=i + 1,
                        content=md_documents[i].text,
                    ),
                    summary=str(summarized_pages[i]),
                )
                for i in range(len(md_documents))
            ]

        except Exception as e:
            logger.error(f"Failed to process PDF: {str(e)}", exc_info=True)
            return []

    async def process_text(self, text_data: bytes) -> DocumentSummaryModel:
        """
        Process and summarize a text file.

        Args:
            text_data: Raw text file bytes

        Returns:
            Summary of the text content
        """
        try:
            # Decode text
            text_content = text_data.decode("utf-8", errors="replace")

            # Generate summary
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
            logger.error(f"Failed to process text: {str(e)}", exc_info=True)
            raise e

    async def _generate_text_summary(self, text: str) -> str:
        """Generate a summary for text content using LlamaCloud."""
        try:
            response = await self.llm.ainvoke(
                input=[
                    {
                        "role": "system",
                        "content": "You are an expert document summarizer. Create concise summaries that capture key information.",
                    },
                    {
                        "role": "user",
                        "content": f"Summarize the following text in a concise way that preserves the most important information:\n\n{text}",
                    },
                ],
            )

            return str(response)

        except Exception as e:
            logger.error(f"Failed to generate summary: {str(e)}", exc_info=True)
            return "Summary could not be generated."


# Function to implement file description generation interface compatible with existing code
async def generate_file_summary(
    file_content: bytes, content_type: str, filename: str
) -> Union[str, List[DocumentSummaryModel], DocumentSummaryModel]:
    """
    Generate a description for a file based on its content type.
    Compatible with existing code interface.

    Args:
        file_content: Raw file bytes
        file_url: URL of the uploaded file
        content_type: MIME type of the file
        filename: Name of the file

    Returns:
        Description of the file content or DocumentSummaryModel instances
    """
    processor = DocumentProcessor()
    return await processor.process_file(
        file_content=file_content,
        content_type=content_type,
        filename=filename,
    )
