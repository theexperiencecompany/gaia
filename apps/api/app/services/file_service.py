"""
Service module for file upload functionality with vector search capabilities.
"""

import asyncio
import contextlib
from datetime import UTC, datetime
import io
from typing import Any
import uuid

import cloudinary
import cloudinary.uploader
from fastapi import HTTPException, UploadFile
from langchain_core.documents import Document

from app.agents.workspace.paths import USER_UPLOADED_DIRNAME, safe_upload_filename
from app.db.chroma.chromadb import ChromaClient
from app.db.mongodb.collections import files_collection
from app.db.utils import serialize_document
from app.decorators.caching import CacheInvalidator
from app.models.files_models import DocumentSummaryModel
from app.services.artifact_events import publish_artifact_event, upload_event
from app.services.storage import (
    FsOps,
    JuiceFSUnavailable,
    chmod_path,
    fs_timer,
    session_root,
    write_session_file,
)
from app.utils.file_utils import generate_file_summary
from app.utils.upload_validation import validate_upload
from shared.py.wide_events import log


@CacheInvalidator(
    key_patterns=[
        "files:{user_id}:*",
    ]
)
async def upload_file_service(
    file: UploadFile,
    user_id: str,
    conversation_id: str | None = None,
    content_length: int | None = None,
) -> dict:
    """Upload a file to Cloudinary, generate embeddings, and store metadata in MongoDB and ChromaDB."""
    content, normalized_content_type, resource_type = await validate_upload(
        file=file, content_length=content_length
    )

    file_id = str(uuid.uuid4())
    # validate_upload() guarantees filename is present — narrow the type here
    # without asserting (bandit B101).
    filename = file.filename or ""
    public_id = f"file_{file_id}_{filename.replace(' ', '_')}"
    log.set(
        service="file_service",
        operation="upload",
        user_id=user_id,
        filename=filename,
        content_type=normalized_content_type,
        file_id=file_id,
    )

    try:
        file_size = len(content)

        cloudinary_task = asyncio.to_thread(
            cloudinary.uploader.upload,
            io.BytesIO(content),
            resource_type=resource_type,
            public_id=public_id,
            overwrite=True,
        )

        summary_task = generate_file_summary(
            file_content=content,
            content_type=normalized_content_type,
            filename=filename,
        )

        upload_result, summary_result = await asyncio.gather(
            cloudinary_task,
            summary_task,
        )

        file_url = upload_result.get("secure_url")
        if not file_url:
            log.error("Missing secure_url in Cloudinary upload response")
            raise HTTPException(status_code=500, detail="Invalid response from file upload service")

        summary, formatted_file_content = _process_file_summary(summary_result)

        sandbox_path: str | None = None
        if conversation_id:
            try:
                safe_filename = safe_upload_filename(filename)
            except ValueError as e:
                log.warning(f"[upload] skipping sandbox copy: {e}")
            else:
                sandbox_path = await _persist_upload_to_sandbox(
                    user_id=user_id,
                    conversation_id=conversation_id,
                    safe_filename=safe_filename,
                    content=content,
                    content_type=normalized_content_type,
                )

        current_time = datetime.now(UTC)
        file_metadata = {
            "file_id": file_id,
            "filename": filename,
            "type": normalized_content_type,
            "size": file_size,
            "url": file_url,
            "public_id": public_id,
            "user_id": user_id,
            "description": summary,
            "page_wise_summary": formatted_file_content,
            "sandbox_path": sandbox_path,
            "created_at": current_time,
            "updated_at": current_time,
        }
        if conversation_id:
            file_metadata["conversation_id"] = conversation_id

        # Store in DB (Mongo + Chroma)
        await asyncio.gather(
            _store_in_mongodb(file_metadata),
            _store_in_chromadb(
                file_id=file_id,
                user_id=user_id,
                filename=filename,
                content_type=normalized_content_type,
                conversation_id=conversation_id,
                file_description=summary_result,
            ),
        )

        return {
            "file_id": file_id,
            "url": file_url,
            "filename": filename,
            "description": summary,
            "type": normalized_content_type,
            "sandbox_path": sandbox_path,
        }

    except HTTPException:
        raise
    except Exception as e:
        log.error(f"Failed to upload file: {e!s}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to upload file: {e!s}")


async def _persist_upload_to_sandbox(
    user_id: str,
    conversation_id: str,
    safe_filename: str,
    content: bytes,
    content_type: str,
) -> str | None:
    """Mirror an upload into the session's read-only `user-uploaded/` dir.

    Returns the `/workspace/...` path the agent can operate on, or None if
    JuiceFS is unavailable (dev). Cloudinary remains the durable copy; a
    failure here must never fail the upload.
    """
    try:
        async with fs_timer(FsOps.UPLOAD_PERSIST_SANDBOX):
            # Clear a prior read-only copy so re-uploads (last-writer-wins) work.
            prior = session_root(user_id, conversation_id) / USER_UPLOADED_DIRNAME / safe_filename
            with contextlib.suppress(Exception):
                if prior.exists():
                    await chmod_path(prior, 0o644)

            host_path, sbx_path = await write_session_file(
                user_id=user_id,
                conversation_id=conversation_id,
                relative_path=f"{USER_UPLOADED_DIRNAME}/{safe_filename}",
                content=content,
            )
            await chmod_path(host_path, 0o444)
    except JuiceFSUnavailable as e:
        log.warning("[upload] juicefs unavailable; sandbox_path not set", error=str(e))
        return None
    except Exception as e:
        log.error("[upload] juicefs write failed", error=str(e), exc_info=True)
        return None

    # Cross-mount host writes may not reach the sandbox watcher; publish the
    # artifact event directly so the chat UI sees the upload immediately.
    await publish_artifact_event(
        user_id,
        upload_event(
            conversation_id,
            safe_filename,
            size_bytes=len(content),
            content_type=content_type,
        ),
    )
    return sbx_path


def _process_file_summary(
    file_summary: str | list[DocumentSummaryModel] | DocumentSummaryModel,
) -> tuple:
    """Helper function to process file description into the correct format."""
    if isinstance(file_summary, str):
        return file_summary, None
    if isinstance(file_summary, list):
        content_str = ""
        content_model: list[dict[str, Any]] = []
        for x in file_summary:
            content_model.append(x.model_dump(mode="json"))
            content_str += x.summary
        return content_str, content_model
    if isinstance(file_summary, DocumentSummaryModel):
        content_str = file_summary.summary
        content_model_dict = file_summary.model_dump(mode="json")
        return content_str, content_model_dict
    log.error("Invalid file description format")
    raise HTTPException(status_code=400, detail="Invalid file description format")


async def _store_in_mongodb(file_metadata: dict) -> None:
    """Helper function to store file metadata in MongoDB."""
    result = await files_collection.insert_one(document=file_metadata)
    if not result.inserted_id:
        raise HTTPException(status_code=500, detail="Failed to store file metadata")


async def _store_in_chromadb(
    file_id: str,
    user_id: str,
    filename: str,
    content_type: str,
    file_description,
    conversation_id: str | None = None,
) -> None:
    """Helper function to store file data in ChromaDB."""
    try:
        chroma_documents_collection = await ChromaClient.get_langchain_client(
            collection_name="documents"
        )

        documents = []
        ids = []

        if isinstance(file_description, list):
            for page in file_description:
                metadata = {
                    "file_id": file_id,
                    "user_id": user_id,
                    "filename": filename,
                    "type": content_type,
                    "page_number": page.data.page_number,
                }

                if conversation_id:
                    metadata["conversation_id"] = conversation_id

                documents.append(
                    Document(
                        page_content=page.summary,
                        metadata=metadata,
                    )
                )
                ids.append(str(uuid.uuid4()))  # Generate a new ID for each page
        else:
            metadata = {
                "file_id": file_id,
                "user_id": user_id,
                "filename": filename,
                "type": content_type,
            }

            if conversation_id:
                metadata["conversation_id"] = conversation_id

            documents.append(
                Document(
                    page_content=(
                        file_description
                        if isinstance(file_description, str)
                        else file_description.summary
                    ),
                    metadata=metadata,
                )
            )
            ids.append(file_id)

        # Store document metadata in ChromaDB
        await chroma_documents_collection.aadd_documents(
            ids=ids,
            documents=documents,
        )
        log.info(f"File with id {file_id} indexed in ChromaDB")
    except Exception as chroma_err:
        # Log but don't fail if ChromaDB indexing fails
        log.error(
            f"Failed to index file in ChromaDB: {chroma_err!s}",
            exc_info=True,
        )


async def update_file_in_chromadb(
    file_id: str,
    user_id: str,
    filename: str,
    content_type: str,
    file_description,
    conversation_id: str | None = None,
) -> None:
    """Helper function to update file data in ChromaDB."""
    try:
        # First try to delete the existing records
        try:
            chroma_documents_collection = await ChromaClient.get_langchain_client(
                collection_name="documents"
            )
            await chroma_documents_collection.adelete(ids=[file_id])
            log.info(f"Removed old file data for {file_id} from ChromaDB")
        except Exception as delete_err:
            # Just log and continue with the new insertion
            log.warning(f"Could not delete old file data from ChromaDB: {delete_err!s}")

        # Now store the updated file data
        await _store_in_chromadb(
            file_id=file_id,
            user_id=user_id,
            filename=filename,
            content_type=content_type,
            file_description=file_description,
            conversation_id=conversation_id,
        )

    except Exception as chroma_err:
        # Log but don't fail if ChromaDB update fails
        log.error(
            f"Failed to update file in ChromaDB: {chroma_err!s}",
            exc_info=True,
        )


@CacheInvalidator(
    key_patterns=[
        "files:{user_id}:*",
    ]
)
async def delete_file_service(file_id: str, user_id: str | None) -> dict:
    """Delete a file by ID for the user, removing it from MongoDB, Cloudinary, and ChromaDB."""
    log.info(f"Deleting file with id: {file_id} for user: {user_id}")
    log.set(service="file_service", operation="delete", file_id=file_id, user_id=user_id)

    if user_id is None:
        log.error("User ID is required to delete a file")
        raise HTTPException(status_code=400, detail="User ID is required")

    # Retrieve file metadata before deletion
    file_data = await files_collection.find_one({"file_id": file_id, "user_id": user_id})
    if not file_data:
        log.error(f"File with id {file_id} not found for user {user_id}")
        raise HTTPException(
            status_code=404, detail="File not found"
        )  # Get the conversation_id for cache invalidation

    public_id = file_data.get("public_id")
    if not public_id:
        log.warning(f"File {file_id} has no public_id for Cloudinary deletion")

    # Delete from MongoDB
    result = await files_collection.delete_one({"file_id": file_id, "user_id": user_id})
    if result.deleted_count == 0:
        log.error("File not found for deletion in MongoDB")
        raise HTTPException(status_code=404, detail="File not found")

    # Delete from Cloudinary if public_id exists
    if public_id:
        try:
            cloudinary_result = cloudinary.uploader.destroy(public_id)
            if cloudinary_result.get("result") != "ok":
                log.warning(f"Failed to delete file from Cloudinary: {cloudinary_result}")
        except Exception as e:
            # Log but don't fail if Cloudinary deletion fails
            log.error(f"Error deleting file from Cloudinary: {e!s}", exc_info=True)

    try:
        chroma_documents_collection = await ChromaClient.get_langchain_client(
            collection_name="documents"
        )
        await chroma_documents_collection.adelete(ids=[file_id])
        log.info(f"File with id {file_id} deleted from ChromaDB")
    except Exception as e:
        # Log the error but don't fail the request if ChromaDB deletion fails
        log.error(f"Failed to delete file from ChromaDB: {e!s}")

    # Cache invalidation is handled by the CacheInvalidator decorator
    log.info(f"File {file_id} successfully deleted")

    return {
        "message": "File deleted successfully",
        "file_id": file_id,
        "filename": file_data.get("filename", "Unknown"),
    }


@CacheInvalidator(
    key_patterns=[
        "files:{user_id}:*",
    ]
)
async def update_file_service(
    file_id: str,
    user_id: str,
    update_data: dict,
    file_content: bytes | None = None,
    conversation_id: str | None = None,
) -> dict:
    """Update file metadata, regenerating the description from new content if provided.

    Refreshes the ChromaDB embedding and invalidates related caches.
    """
    log.info(f"Updating file with id: {file_id} for user: {user_id}")
    log.set(service="file_service", operation="update", file_id=file_id, user_id=user_id)

    file_data = await files_collection.find_one({"file_id": file_id, "user_id": user_id})
    if not file_data:
        log.error(f"File with id {file_id} not found for user {user_id}")
        raise HTTPException(status_code=404, detail="File not found")

    # Store original conversation ID if not provided in update
    if not conversation_id:
        conversation_id = file_data.get("conversation_id")

    # Prepare update data
    current_time = datetime.now(UTC)
    update_data["updated_at"] = current_time

    # Generate new description if file content is provided
    if file_content:
        try:
            # Use the same file description generator as upload_file_service
            content_type = update_data.get("type") or file_data.get("type")
            filename = update_data.get("filename") or file_data.get("filename")

            file_description = await generate_file_summary(
                file_content=file_content,
                content_type=content_type,
                filename=filename,
            )

            # Process file description
            summary, page_wise_summary = _process_file_summary(file_description)

            update_data["description"] = summary
            update_data["page_wise_summary"] = page_wise_summary
        except Exception as e:
            log.error(f"Failed to generate file description: {e!s}", exc_info=True)
            raise HTTPException(status_code=500, detail=f"Failed to process file: {e!s}")

    # Check if description is being updated
    description_updated = "description" in update_data

    # Update in MongoDB
    result = await files_collection.update_one(
        {"file_id": file_id, "user_id": user_id}, {"$set": update_data}
    )

    if result.modified_count == 0:
        log.warning(f"No changes made to file {file_id}")

    updated_file = await files_collection.find_one({"file_id": file_id, "user_id": user_id})
    if not updated_file:
        log.error(f"Updated file {file_id} not found")
        raise HTTPException(status_code=404, detail="File not found after update")

    # If description was updated, update ChromaDB
    if description_updated:
        try:
            # Generate new embedding for the updated description
            new_description = update_data["description"]

            # Update in ChromaDB
            await update_file_in_chromadb(
                file_id=file_id,
                user_id=user_id,
                filename=updated_file.get("filename", ""),
                content_type=updated_file.get("type", ""),
                file_description=new_description,
                conversation_id=conversation_id,
            )

        except Exception as err:
            # Log but don't fail if ChromaDB update fails
            log.error(f"Failed to update file in ChromaDB: {err!s}", exc_info=True)

    # Convert ObjectId to string for serialization
    if "_id" in updated_file:
        updated_file["_id"] = str(updated_file["_id"])

    # Convert date fields to ISO format
    for date_field in ["created_at", "updated_at"]:
        if date_field in updated_file and hasattr(updated_file[date_field], "isoformat"):
            updated_file[date_field] = updated_file[date_field].isoformat()

    return serialize_document(updated_file)
