"""
Router module for file upload functionality with RAG integration.
"""

from app.api.v1.dependencies.oauth_dependencies import get_current_user
from app.decorators import tiered_rate_limit
from app.models.message_models import FileData
from app.services.file_service import (
    delete_file_service,
    update_file_service,
    upload_file_service,
)
from fastapi import APIRouter, Body, Depends, File, Form, UploadFile, status

router = APIRouter()


@router.post("/upload", response_model=FileData, status_code=status.HTTP_201_CREATED)
@tiered_rate_limit("file_upload")
async def upload_file_endpoint(
    file: UploadFile = File(...),
    conversation_id: str = Form(None),
    user: dict = Depends(get_current_user),
):
    """
    Upload a file to the server and generate embeddings for image files.

    This endpoint uploads files to Cloudinary and stores metadata in MongoDB.
    For image files, it also generates vector embeddings to enable semantic search.

    Args:
        file: The file to upload
        conversation_id: Optional ID of conversation to associate with the file
        user: The authenticated user information

    Returns:
        File metadata including ID, URL, and auto-generated description
    """
    user_id = user.get("user_id", None)
    if not user_id:
        return {"error": "User ID is required"}

    result = await upload_file_service(
        file=file,
        user_id=user_id,
        conversation_id=conversation_id,
    )

    return FileData(
        fileId=result["file_id"],
        url=result["url"],
        filename=result["filename"],
        message="File uploaded successfully",
        type=result.get("type", "file"),
    )


@router.put("/{file_id}", status_code=status.HTTP_200_OK)
async def update_file_endpoint(
    file_id: str,
    update_data: dict = Body(...),
    user: dict = Depends(get_current_user),
):
    """
    Update file metadata and refresh embeddings if needed.

    This endpoint updates file metadata in MongoDB and ChromaDB.
    If the description is updated, it regenerates the embedding.

    Args:
        file_id: The ID of the file to update
        update_data: The file data to update
        user: The authenticated user information

    Returns:
        Updated file metadata
    """
    user_id = user.get("user_id", None)
    if not user_id:
        return {"error": "User ID is required"}

    result = await update_file_service(
        file_id=file_id,
        user_id=user_id,
        update_data=update_data,
    )

    return result


@router.delete("/{file_id}", status_code=status.HTTP_200_OK)
async def delete_file_endpoint(
    file_id: str,
    user: dict = Depends(get_current_user),
):
    """
    Delete a file by its ID.

    This endpoint removes a file from Cloudinary storage, MongoDB, and ChromaDB.

    Args:
        file_id: The ID of the file to delete
        user: The authenticated user information

    Returns:
        Success message with deleted file information
    """
    result = await delete_file_service(
        file_id=file_id,
        user_id=user.get("user_id", None),
    )

    return result
