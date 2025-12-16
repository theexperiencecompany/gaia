from typing import Annotated, Optional

from app.config.loggers import chat_logger as logger
from app.db.chroma.chromadb import ChromaClient
from app.db.mongodb.collections import files_collection
from app.decorators import with_doc, with_rate_limiting
from app.templates.docstrings.file_tool_docs import QUERY_FILE
from langchain_core.documents import Document
from langchain_core.runnables import RunnableConfig
from langchain_core.tools import tool


@tool
@with_rate_limiting("file_analysis")
@with_doc(QUERY_FILE)
async def query_file(
    query: Annotated[
        str,
        "",
    ],
    file_id: Annotated[
        Optional[str],
        "The ID of the file to query. If not provided, it will search all files.",
    ],
    config: RunnableConfig,
) -> str:
    try:
        configurable = config.get("configurable")

        if not configurable:
            logger.error("Configurable is not set in the config.")
            raise ValueError("Configurable is not set in the config.")

        conversation_id = configurable["thread_id"]

        similar_documents = await _get_similar_documents(
            query=query,
            conversation_id=conversation_id,
            file_id=file_id,
            user_id=configurable["user_id"],
        )

        logger.info(f"Similar documents found: {similar_documents}")

        document_ids = list(
            set(
                [
                    document.metadata.get("file_id")
                    for document, score in similar_documents
                ]
            )
        )

        logger.info(f"Document IDs: {document_ids}")

        documents = await files_collection.find(
            filter={
                "file_id": {"$in": document_ids},
                "user_id": configurable["user_id"],
            },
        ).to_list(length=None)

        logger.info(f"Documents found: {documents}")

        return _construct_content(
            documents=documents,
            similar_documents=similar_documents,
        )

    except Exception as e:
        logger.error(f"Error in querying document: {str(e)}")
        raise e


async def _get_similar_documents(
    query: str,
    conversation_id: str,
    user_id: str,
    file_id: Optional[str] = None,
) -> list[tuple[Document, float]]:
    """
    Helper function to retrieve documents similar to the query from ChromaDB.

    This function performs a semantic similarity search within ChromaDB to find documents
    that match the provided query. It uses filters to limit results to the user's documents
    and specific conversation context.

    Args:
        query: The search query string to find similar documents
        conversation_id: The ID of the current conversation to filter documents
        user_id: The ID of the user who owns the documents
        file_id: Optional file ID to limit search to a specific file

    Returns:
        list: List of similar documents with their metadata and similarity scores
    """
    chroma_documents_collection = await ChromaClient.get_langchain_client(
        collection_name="documents"
    )

    if not chroma_documents_collection:
        logger.error("ChromaDB client is not available.")
        return []

    filters = {
        "$and": [
            {"user_id": user_id},
            # {"conversation_id": conversation_id},
        ]
    }

    if file_id:
        filters["$and"].append({"file_id": file_id})

    return await chroma_documents_collection.asimilarity_search_with_score(
        query=query,
        filter=filters,
        k=5,
    )


def _construct_content(
    documents: list, similar_documents: list[tuple[Document, float]]
) -> str:
    """
    Helper function to construct a formatted response from similar documents.

    This function takes the document metadata from MongoDB and similar document sections
    from ChromaDB to build a human-readable response. It handles different document formats
    and extracts the relevant content, organizing it by document ID and page number.

    Args:
        documents: List of document metadata from MongoDB
        similar_documents: List of similar document sections from ChromaDB with similarity scores

    Returns:
        str: Formatted content string containing relevant document sections with proper
             attribution and structure for easy reading
    """
    content = ""

    for similar_document, score in similar_documents:
        document_id = similar_document.metadata["file_id"]
        document = next(
            (doc for doc in documents if str(doc["file_id"]) == str(document_id)),
            None,
        )

        if not document:
            logger.error(f"Document with ID {document_id} not found.")
            continue

        document_content = document["page_wise_summary"]
        description = document["description"]

        if not document_content:
            content += f"Document ID: {document_id}\n"
            content += f"Description: {description}\n\n"
        elif isinstance(document_content, str):
            content += f"Document ID: {document_id}\n"
            content += f"Description: {document_content}\n\n"
        elif isinstance(document_content, list):
            target_page_number = similar_document.metadata["page_number"]
            for page in document_content:
                if page["data"]["page_number"] == target_page_number:
                    content += f"Document ID: {document_id}\n"
                    content += f"Page Number: {target_page_number}\n"
                    content += f"Description: {page['data']['content']}\n\n"
                    break
        elif isinstance(document_content, dict):
            content += f"Document ID: {document_id}\n"
            content += f"Description: {document_content.get('data', {}).get('content', 'Description not available!')}\n\n"
        else:
            logger.error(
                f"Unexpected document description type: {type(document['description'])}"
            )
            content += f"Document ID: {document_id}\n"
            content += "Description: Invalid format\n\n"

    logger.info(f"Constructed content: {content}")

    return content
