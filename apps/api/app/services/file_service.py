"""
Service module for file upload functionality with vector search capabilities.
"""

import asyncio
import io
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import cloudinary
import cloudinary.uploader
from app.config.loggers import app_logger as logger
from app.db.chroma.chromadb import ChromaClient
from app.db.mongodb.collections import files_collection
from app.db.utils import serialize_document
from app.decorators.caching import Cacheable, CacheInvalidator
from app.models.files_models import DocumentSummaryModel
from app.models.message_models import FileData
from app.utils.embedding_utils import search_documents_by_similarity
from app.utils.file_utils import generate_file_summary
from fastapi import HTTPException, UploadFile
from langchain_core.documents import Document


@CacheInvalidator(
    key_patterns=[
        "files:{user_id}:*",
    ]
)
async def upload_file_service(
    file: UploadFile,
    user_id: str,
    conversation_id: Optional[str] = None,
) -> dict:
    """
    Upload a file to Cloudinary, generate embeddings, and store metadata in MongoDB and ChromaDB.
    Args:
        file (UploadFile): The file to upload
        user_id (str): The ID of the user uploading the file
        conversation_id (str, optional): The conversation ID to associate with the file
    Returns:
        dict: File metadata including file_id and url
    Raises:
        HTTPException: If file upload fails
    """
    if not file.filename:
        logger.error("Missing filename in file upload")
        raise HTTPException(
            status_code=400, detail="Invalid file name. Filename is required."
        )
    if not file.content_type:
        logger.error("Missing content_type in file upload")
        raise HTTPException(
            status_code=400, detail="Invalid file type. Content type is required."
        )

    file_id = str(uuid.uuid4())
    public_id = f"file_{file_id}_{file.filename.replace(' ', '_')}"

    try:
        content = await file.read()

        file_size = len(content)
        if file_size > 10 * 1024 * 1024:
            logger.error("File size exceeds the 10 MB limit")
            raise HTTPException(
                status_code=400, detail="File size exceeds the 10 MB limit"
            )

        cloudinary_task = asyncio.to_thread(
            cloudinary.uploader.upload,
            io.BytesIO(content),
            resource_type="auto",
            public_id=public_id,
            overwrite=True,
        )

        summary_task = generate_file_summary(
            file_content=content,
            content_type=file.content_type,
            filename=file.filename,
        )

        upload_result, summary_result = await asyncio.gather(
            cloudinary_task,
            summary_task,
        )

        file_url = upload_result.get("secure_url")
        if not file_url:
            logger.error("Missing secure_url in Cloudinary upload response")
            raise HTTPException(
                status_code=500, detail="Invalid response from file upload service"
            )

        summary, formatted_file_content = _process_file_summary(summary_result)

        current_time = datetime.now(timezone.utc)
        file_metadata = {
            "file_id": file_id,
            "filename": file.filename,
            "type": file.content_type,
            "size": file_size,
            "url": file_url,
            "public_id": public_id,
            "user_id": user_id,
            "description": summary,
            "page_wise_summary": formatted_file_content,
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
                filename=file.filename,
                content_type=file.content_type,
                conversation_id=conversation_id,
                file_description=summary_result,
            ),
        )

        return {
            "file_id": file_id,
            "url": file_url,
            "filename": file.filename,
            "description": summary,
            "type": file.content_type,
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to upload file: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to upload file: {str(e)}")


def _process_file_summary(
    file_summary: str | list[DocumentSummaryModel] | DocumentSummaryModel,
) -> tuple:
    """Helper function to process file description into the correct format."""
    if isinstance(file_summary, str):
        return file_summary, None
    elif isinstance(file_summary, list):
        content_str = ""
        content_model: list[dict[str, Any]] = []
        for x in file_summary:
            content_model.append(x.model_dump(mode="json"))
            content_str += x.summary
        return content_str, content_model
    elif isinstance(file_summary, DocumentSummaryModel):
        content_str = file_summary.summary
        content_model_dict = file_summary.model_dump(mode="json")
        return content_str, content_model_dict
    else:
        logger.error("Invalid file description format")
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
    conversation_id: Optional[str] = None,
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
        logger.info(f"File with id {file_id} indexed in ChromaDB")
    except Exception as chroma_err:
        # Log but don't fail if ChromaDB indexing fails
        logger.error(
            f"Failed to index file in ChromaDB: {str(chroma_err)}",
            exc_info=True,
        )


async def update_file_in_chromadb(
    file_id: str,
    user_id: str,
    filename: str,
    content_type: str,
    file_description,
    conversation_id: Optional[str] = None,
) -> None:
    """Helper function to update file data in ChromaDB."""
    try:
        # First try to delete the existing records
        try:
            chroma_documents_collection = await ChromaClient.get_langchain_client(
                collection_name="documents"
            )
            await chroma_documents_collection.adelete(ids=[file_id])
            logger.info(f"Removed old file data for {file_id} from ChromaDB")
        except Exception as delete_err:
            # Just log and continue with the new insertion
            logger.warning(
                f"Could not delete old file data from ChromaDB: {str(delete_err)}"
            )

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
        logger.error(
            f"Failed to update file in ChromaDB: {str(chroma_err)}",
            exc_info=True,
        )


async def fetch_files(context: Dict[str, Any]) -> Dict[str, Any]:
    """
    Fetch file data based on fileIds in the request, perform RAG with vector search,
    and add relevant file information to the message context.

    This pipeline step:
    1. Processes explicit file IDs provided in the request
    2. Uses fileData if available to avoid redundant database lookups
    3. Performs vector similarity search to find relevant files based on the query
    4. Formats and adds the file information to the message context

    Args:
        context (Dict[str, Any]): The pipeline context containing request data

    Returns:
        Dict[str, Any]: Updated context with file data added
    """

    user_id = context.get("user_id")
    if not user_id:
        return context

    conversation_id = context.get("conversation_id")
    query_text = context.get("query_text", "")
    last_message = context.get("last_message")

    # Check if the last message is empty or not
    if not last_message:
        context["files_added"] = False
        return context

    try:
        # Track files to include in the response
        included_files = []

        # Get explicit file IDs and file data from context
        explicit_file_ids = context.get("fileIds", [])
        file_data_list: List[FileData] = context.get("fileData", [])

        # Create a mapping of file IDs to their complete metadata from fileData
        file_data_map = {
            file_data.fileId: file_data.model_dump() for file_data in file_data_list
        }

        if explicit_file_ids:
            logger.info(f"Fetching {len(explicit_file_ids)} files by ID")

            # Find which IDs aren't in the file_data_map
            missing_ids = [
                file_id for file_id in explicit_file_ids if file_id not in file_data_map
            ]

            # Process files from file_data_map
            for file_id in explicit_file_ids:
                if file_id in file_data_map:
                    file_data = file_data_map[file_id]
                    included_files.append(
                        {
                            "file_id": file_data["file_id"],
                            "url": file_data["url"],
                            "filename": file_data["filename"],
                            "description": file_data.get("deskcription", ""),
                            "content_type": file_data.get("content_type", ""),
                            "_id": file_data[
                                "file_id"
                            ],  # Use file_id as _id for consistency
                        }
                    )

            # Batch lookup missing files from database
            if missing_ids:
                db_files = await files_collection.find(
                    {"file_id": {"$in": missing_ids}}
                ).to_list(length=None)

                for file_data in db_files:
                    # Convert ObjectId to string for serialization
                    if "_id" in file_data:
                        file_data["_id"] = str(file_data["_id"])

                    # Convert date fields to ISO format
                    for date_field in ["created_at", "updated_at"]:
                        if date_field in file_data and hasattr(
                            file_data[date_field], "isoformat"
                        ):
                            file_data[date_field] = file_data[date_field].isoformat()

                    included_files.append(
                        {
                            "file_id": file_data["file_id"],
                            "url": file_data["url"],
                            "filename": file_data["filename"],
                            "description": file_data.get("description", ""),
                            "content_type": file_data.get("content_type", ""),
                            "_id": file_data[
                                "file_id"
                            ],  # Use file_id as _id for consistency
                        }
                    )

        # 2. Perform vector search for relevant files based on the query
        # Only perform the search if there's a meaningful query
        if len(query_text) > 3:
            relevant_files = []

            # Use ChromaDB for vector search
            try:
                # Search documents using ChromaDB
                relevant_files = await search_documents_by_similarity(
                    input_text=query_text,
                    user_id=user_id,
                    conversation_id=conversation_id,
                    top_k=5,
                )

                # Format the results to match the expected structure
                for file in relevant_files:
                    file["score"] = file.get("similarity_score", 0)
            except Exception as e:
                logger.error(
                    f"Error searching documents with ChromaDB: {str(e)}", exc_info=True
                )
                relevant_files = []

            if relevant_files:
                logger.info(f"Found {len(relevant_files)} semantically relevant files")

                # Add relevant files that weren't already included via explicit IDs
                for file in relevant_files:
                    file_id = file.get("file_id")
                    if file_id not in [f.get("file_id") for f in included_files]:
                        included_files.append(
                            {
                                "file_id": file_id,
                                "url": file.get("url"),
                                "filename": file.get("filename"),
                                "description": file.get("description", ""),
                                "content_type": file.get("content_type", ""),
                                "_id": file_id,  # Use file_id as _id for consistency
                            }
                        )
                logger.info(f"Added {len(relevant_files)} semantically relevant files")

        # 3. Format and add file information to the message context
        if included_files:
            # Separate explicit files from semantic search results
            explicit_files = [
                f for f in included_files if f.get("file_id") in explicit_file_ids
            ]
            semantic_files = [
                f for f in included_files if f.get("file_id") not in explicit_file_ids
            ]

            # Format file information for the message context
            formatted_files = "\n\n## File Information\n\n"

            # Include explicitly requested files first
            if explicit_files:
                formatted_files += "### Uploaded Files\n\n"
                for file in explicit_files:
                    filename = file.get("filename", "Unnamed file")
                    file_type = file.get("content_type", "Unknown type")
                    description = file.get("description", "No description available")

                    formatted_files += f"**{filename}** ({file_type})\n"
                    formatted_files += f"{description}\n\n"

            if semantic_files:
                formatted_files += "### Relevant Files\n\n"
                for file in semantic_files:
                    filename = file.get("filename", "Unnamed file")
                    file_type = file.get("content_type", "Unknown type")
                    description = file.get("description", "No description available")
                    relevance = file.get("relevance_score", 0)

                    formatted_files += (
                        f"**{filename}** ({file_type}) - Relevance: {relevance:.2f}\n"
                    )
                    formatted_files += f"{description}\n\n"

            # Add the file information to the message context
            context["last_message"]["content"] += formatted_files
            context["files_data"] = included_files
            context["files_added"] = True
            logger.info(f"Added {len(included_files)} files to message context")
        else:
            context["files_added"] = False
            logger.info("No relevant files found")

    except Exception as e:
        logger.error(f"Error processing files: {str(e)}", exc_info=True)
        context["files_added"] = False
        context["file_error"] = str(e)

    return context


@CacheInvalidator(
    key_patterns=[
        "files:{user_id}:*",
    ]
)
async def delete_file_service(file_id: str, user_id: Optional[str]) -> dict:
    """
    Delete a file by its ID for the specified user.
    Removes the file from MongoDB, Cloudinary, and ChromaDB.

    Args:
        file_id (str): The ID of the file to delete
        user_id (Optional[str]): The ID of the authenticated user

    Returns:
        dict: Success message with deleted file information

    Raises:
        HTTPException: If the file is not found or deletion fails
    """
    logger.info(f"Deleting file with id: {file_id} for user: {user_id}")

    if user_id is None:
        logger.error("User ID is required to delete a file")
        raise HTTPException(status_code=400, detail="User ID is required")

    # Retrieve file metadata before deletion
    file_data = await files_collection.find_one(
        {"file_id": file_id, "user_id": user_id}
    )
    if not file_data:
        logger.error(f"File with id {file_id} not found for user {user_id}")
        raise HTTPException(
            status_code=404, detail="File not found"
        )  # Get the conversation_id for cache invalidation

    # Get the public_id for cloudinary deletion
    public_id = file_data.get("public_id")
    if not public_id:
        logger.warning(f"File {file_id} has no public_id for Cloudinary deletion")

    # Delete from MongoDB
    result = await files_collection.delete_one({"file_id": file_id, "user_id": user_id})
    if result.deleted_count == 0:
        logger.error("File not found for deletion in MongoDB")
        raise HTTPException(status_code=404, detail="File not found")

    # Delete from Cloudinary if public_id exists
    if public_id:
        try:
            cloudinary_result = cloudinary.uploader.destroy(public_id)
            if cloudinary_result.get("result") != "ok":
                logger.warning(
                    f"Failed to delete file from Cloudinary: {cloudinary_result}"
                )
        except Exception as e:
            # Log but don't fail if Cloudinary deletion fails
            logger.error(
                f"Error deleting file from Cloudinary: {str(e)}", exc_info=True
            )

    try:
        chroma_documents_collection = await ChromaClient.get_langchain_client(
            collection_name="documents"
        )
        await chroma_documents_collection.adelete(ids=[file_id])
        logger.info(f"File with id {file_id} deleted from ChromaDB")
    except Exception as e:
        # Log the error but don't fail the request if ChromaDB deletion fails
        logger.error(f"Failed to delete file from ChromaDB: {str(e)}")

    # Cache invalidation is handled by the CacheInvalidator decorator
    logger.info(f"File {file_id} successfully deleted")

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
    file_content: Optional[bytes] = None,
    conversation_id: Optional[str] = None,
) -> dict:
    """
    Update file metadata and optionally regenerate description if file content is provided.
    The function refreshes ChromaDB embedding and invalidates related caches.

    Args:
        file_id (str): The ID of the file to update
        user_id (str): The ID of the authenticated user
        update_data (dict): The file data to update
        file_content (bytes, optional): The new file content to process for description
        conversation_id (str, optional): The conversation ID to associate with the file

    Returns:
        dict: Updated file metadata

    Raises:
        HTTPException: If the file is not found or update fails
    """
    logger.info(f"Updating file with id: {file_id} for user: {user_id}")

    # Get the current file data
    file_data = await files_collection.find_one(
        {"file_id": file_id, "user_id": user_id}
    )
    if not file_data:
        logger.error(f"File with id {file_id} not found for user {user_id}")
        raise HTTPException(status_code=404, detail="File not found")

    # Store original conversation ID if not provided in update
    if not conversation_id:
        conversation_id = file_data.get("conversation_id")

    # Prepare update data
    current_time = datetime.now(timezone.utc)
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
            logger.error(
                f"Failed to generate file description: {str(e)}", exc_info=True
            )
            raise HTTPException(
                status_code=500, detail=f"Failed to process file: {str(e)}"
            )

    # Check if description is being updated
    description_updated = "description" in update_data

    # Update in MongoDB
    result = await files_collection.update_one(
        {"file_id": file_id, "user_id": user_id}, {"$set": update_data}
    )

    if result.modified_count == 0:
        logger.warning(f"No changes made to file {file_id}")

    # Get the updated file data
    updated_file = await files_collection.find_one(
        {"file_id": file_id, "user_id": user_id}
    )
    if not updated_file:
        logger.error(f"Updated file {file_id} not found")
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
            logger.error(
                f"Failed to update file in ChromaDB: {str(err)}", exc_info=True
            )

    # Convert ObjectId to string for serialization
    if "_id" in updated_file:
        updated_file["_id"] = str(updated_file["_id"])

    # Convert date fields to ISO format
    for date_field in ["created_at", "updated_at"]:
        if date_field in updated_file and hasattr(
            updated_file[date_field], "isoformat"
        ):
            updated_file[date_field] = updated_file[date_field].isoformat()

    return serialize_document(updated_file)


@Cacheable(
    key_pattern="files:{user_id}:{conversation_id}",
    ttl=86400,  # 24 hours
    model=List[FileData],
)
async def get_files(
    user_id: str,
    conversation_id: Optional[str] = None,
) -> List[FileData]:
    """
    Retrieve files for a specific user and optionally filter by conversation ID.

    Args:
        user_id (str): The ID of the user
        conversation_id (Optional[str]): The conversation ID to filter by
        use_cache (bool): Whether to use cache or force a database query

    Returns:
        List[FileData]: A list of file data objects
    """
    # If conversation_id is None, fetch all files for the user
    if conversation_id:
        query = {"user_id": user_id, "conversation_id": conversation_id}
    else:
        query = {"user_id": user_id}

    # Cache miss or cache disabled, fetch from database
    logger.info(
        f"Fetching files from database for user: {user_id}"
        + (f", conversation: {conversation_id}" if conversation_id else "")
    )

    files = await files_collection.find(query).to_list(length=None)

    logger.info(f"Found {len(files)} files for user: {user_id}")

    # Convert ObjectId to string for serialization
    return [deserialize_file(file) for file in files]


def deserialize_file(file: dict) -> FileData:
    """
    Serialize a file document to a FileData object.

    Args:
        file (dict): The file document to serialize

    Returns:
        FileData: The serialized file data object
    """
    file_id = file.get("file_id", "") or file.get("fileId", "")
    if not file_id:
        logger.error("Missing file_id in file document")
        raise HTTPException(status_code=400, detail="Invalid file document")

    return FileData(
        fileId=file_id,
        filename=file["filename"],
        url=file["url"],
        type=file["type"],
        message=file.get("message", ""),
    )
