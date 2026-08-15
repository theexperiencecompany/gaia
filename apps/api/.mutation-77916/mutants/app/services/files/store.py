"""Durable and indexed storage for uploaded files.

Three backends, one per concern:
- Cloudinary — the durable blob copy.
- MongoDB (via `file_repository`) — authoritative file metadata + summary.
- ChromaDB `documents` — the vector index powering `search_uploaded_files`.

ChromaDB writes are best-effort: a failure degrades search but must never fail
the upload, so the blob + metadata are still persisted.
"""

import asyncio
import io
from typing import cast
import uuid

import cloudinary
import cloudinary.uploader
from fastapi import HTTPException
from langchain_core.documents import Document

from app.constants.files import CHROMA_DOCUMENTS_COLLECTION
from app.db.chroma.chromadb import ChromaClient
from app.db.repositories.files import file_repository
from app.models.files_models import FileDocument
from app.services.files.summaries import GeneratedSummary
from shared.py.wide_events import log


async def upload_to_cloudinary(content: bytes, resource_type: str, public_id: str) -> str:
    """Upload bytes to Cloudinary and return the durable secure URL."""
    result = await asyncio.to_thread(
        cloudinary.uploader.upload,
        io.BytesIO(content),
        resource_type=resource_type,
        public_id=public_id,
        overwrite=True,
    )
    url = result.get("secure_url")
    if not url:
        log.error("[files] cloudinary upload returned no secure_url")
        raise HTTPException(status_code=500, detail="Invalid response from file upload service")
    # cloudinary ships no type stubs; secure_url is documented as a string.
    return cast(str, url)


def destroy_in_cloudinary(public_id: str) -> None:
    """Best-effort delete of a Cloudinary blob."""
    try:
        result = cloudinary.uploader.destroy(public_id)
        if result.get("result") != "ok":
            log.warning("[files] cloudinary delete did not confirm", result=result)
    except Exception as e:
        log.error(
            "[files] cloudinary delete failed",
            error=str(e),
            error_type=type(e).__name__,
            exc_info=True,
        )


async def insert_metadata(document: FileDocument) -> None:
    """Persist a file's metadata document."""
    await file_repository.create(document)


def _build_index_documents(
    file_id: str,
    user_id: str,
    filename: str,
    content_type: str,
    summary: GeneratedSummary,
    conversation_id: str | None,
) -> tuple[list[Document], list[str]]:
    """Turn a generated summary into ChromaDB documents + their ids.

    Multi-page documents are indexed one vector per page (each under a fresh id);
    everything else is a single vector keyed by `file_id`.
    """
    base_metadata = {
        "file_id": file_id,
        "user_id": user_id,
        "filename": filename,
        "type": content_type,
    }
    if conversation_id:
        base_metadata["conversation_id"] = conversation_id

    if isinstance(summary, list):
        documents: list[Document] = []
        ids: list[str] = []
        for page in summary:
            documents.append(
                Document(
                    page_content=page.summary,
                    metadata={**base_metadata, "page_number": page.data.page_number},
                )
            )
            ids.append(str(uuid.uuid4()))
        return documents, ids

    page_content = summary if isinstance(summary, str) else summary.summary
    return [Document(page_content=page_content, metadata=base_metadata)], [file_id]


async def index_file(
    file_id: str,
    user_id: str,
    filename: str,
    content_type: str,
    summary: GeneratedSummary,
    conversation_id: str | None = None,
) -> None:
    """Index a file's summary into ChromaDB. Best-effort — logs and swallows failures."""
    try:
        collection = await ChromaClient.get_langchain_client(
            collection_name=CHROMA_DOCUMENTS_COLLECTION
        )
        documents, ids = _build_index_documents(
            file_id, user_id, filename, content_type, summary, conversation_id
        )
        await collection.aadd_documents(ids=ids, documents=documents)
        log.info(
            "[files] indexed in vector store ( vector(s))",
            file_id=file_id,
            documents_count=len(documents),
        )
    except Exception as e:
        log.error(
            "[files] failed to index in vector store",
            file_id=file_id,
            error=str(e),
            error_type=type(e).__name__,
            user_id=user_id,
            conversation_id=conversation_id,
            exc_info=True,
        )


async def reindex_file(
    file_id: str,
    user_id: str,
    filename: str,
    content_type: str,
    summary: GeneratedSummary,
    conversation_id: str | None = None,
) -> None:
    """Replace a file's existing vectors with a freshly indexed summary."""
    await delete_from_index(file_id)
    await index_file(file_id, user_id, filename, content_type, summary, conversation_id)


async def delete_from_index(file_id: str) -> None:
    """Best-effort removal of a file's vectors from ChromaDB."""
    try:
        collection = await ChromaClient.get_langchain_client(
            collection_name=CHROMA_DOCUMENTS_COLLECTION
        )
        await collection.adelete(ids=[file_id])
        log.info("[files] removed from vector store", file_id=file_id)
    except Exception as e:
        log.warning(
            "[files] failed to remove from vector store",
            file_id=file_id,
            error=str(e),
            error_type=type(e).__name__,
        )
