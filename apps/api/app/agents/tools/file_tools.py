from typing import Annotated

from langchain_core.documents import Document
from langchain_core.runnables import RunnableConfig
from langchain_core.tools import tool

from app.constants.files import CHROMA_DOCUMENTS_COLLECTION
from app.db.chroma.chromadb import ChromaClient
from app.db.mongodb.collections import files_collection
from app.decorators import with_doc, with_rate_limiting
from app.templates.docstrings.file_tool_docs import SEARCH_UPLOADED_FILES
from shared.py.wide_events import log


@tool
@with_rate_limiting("file_analysis")
@with_doc(SEARCH_UPLOADED_FILES)
async def search_uploaded_files(
    query: Annotated[
        str,
        "",
    ],
    file_id: Annotated[
        str | None,
        "Optional: restrict the search to one uploaded file by its ID. "
        "Omit to search across all files uploaded in this conversation.",
    ],
    config: RunnableConfig,
) -> str:
    try:
        log.set(tool={"name": "search_uploaded_files", "action": "query"})
        configurable = config.get("configurable")

        if not configurable:
            log.error("Configurable is not set in the config.")
            raise ValueError("Configurable is not set in the config.")

        conversation_id = configurable["thread_id"]

        similar_documents = await _get_similar_documents(
            query=query,
            conversation_id=conversation_id,
            file_id=file_id,
            user_id=configurable["user_id"],
        )

        log.info(f"Similar documents found: {similar_documents}")

        document_ids = list(
            set([document.metadata.get("file_id") for document, score in similar_documents])
        )

        log.info(f"Document IDs: {document_ids}")

        documents = await files_collection.find(
            filter={
                "file_id": {"$in": document_ids},
                "user_id": configurable["user_id"],
            },
        ).to_list(length=None)

        log.info(f"Documents found: {documents}")

        return _construct_content(
            documents=documents,
            similar_documents=similar_documents,
        )

    except Exception as e:
        log.error(f"Error in querying document: {e!s}")
        raise e


async def _get_similar_documents(
    query: str,
    conversation_id: str,
    user_id: str,
    file_id: str | None = None,
) -> list[tuple[Document, float]]:
    """Semantic search over files uploaded in this conversation, scored by similarity.

    Scope is resolved from MongoDB (files carrying this ``conversation_id``) and
    applied as a ``file_id`` filter on the vector search — so the tool can never
    surface a file from another conversation, regardless of ChromaDB metadata.
    """
    chroma_documents_collection = await ChromaClient.get_langchain_client(
        collection_name=CHROMA_DOCUMENTS_COLLECTION
    )

    if not chroma_documents_collection:
        log.error("ChromaDB client is not available.")
        return []

    conversation_files = await files_collection.find(
        {"user_id": user_id, "conversation_id": conversation_id},
        projection={"_id": 0, "file_id": 1},
    ).to_list(length=None)
    conversation_file_ids = [doc["file_id"] for doc in conversation_files if doc.get("file_id")]
    if not conversation_file_ids:
        return []

    if file_id is not None:
        if file_id not in conversation_file_ids:
            return []
        target_file_ids = [file_id]
    else:
        target_file_ids = conversation_file_ids

    filters = {
        "$and": [
            {"user_id": user_id},
            {"file_id": {"$in": target_file_ids}},
        ]
    }

    return await chroma_documents_collection.asimilarity_search_with_score(
        query=query,
        filter=filters,
        k=5,
    )


def _construct_content(documents: list, similar_documents: list[tuple[Document, float]]) -> str:
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
            log.error(f"Document with ID {document_id} not found.")
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
            log.error(f"Unexpected document description type: {type(document['description'])}")
            content += f"Document ID: {document_id}\n"
            content += "Description: Invalid format\n\n"

    log.info(f"Constructed content: {content}")

    return content
