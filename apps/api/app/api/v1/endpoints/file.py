"""File upload, update, and delete endpoints."""

from fastapi import (
    APIRouter,
    Body,
    Depends,
    File,
    Form,
    Header,
    HTTPException,
    UploadFile,
    status,
)

from app.api.v1.dependencies.oauth_dependencies import get_current_user
from app.db.mongodb.collections import conversations_collection
from app.decorators import tiered_rate_limit
from app.models.message_models import FileData
from app.services.file_service import (
    delete_file_service,
    update_file_service,
    upload_file_service,
)
from app.services.storage import SAFE_PATH_ID_PATTERN
from shared.py.wide_events import log

router = APIRouter()


@router.post("/upload", response_model=FileData, status_code=status.HTTP_201_CREATED)
@tiered_rate_limit("file_upload")
async def upload_file_endpoint(
    file: UploadFile = File(...),
    conversation_id: str | None = Form(default=None, pattern=SAFE_PATH_ID_PATTERN),
    content_length: int | None = Header(default=None, alias="content-length"),
    user: dict = Depends(get_current_user),
):
    """Upload a file, persist metadata, and generate embeddings for images."""
    user_id = user.get("user_id")
    if not user_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Authentication required."
        )

    if conversation_id is not None:
        # Reject uploads targeting a conversation the authenticated user does
        # not own — otherwise alice could pollute her own session tree with
        # artifacts keyed under bob's conversation id.
        owner = await conversations_collection.find_one(
            {"user_id": user_id, "conversation_id": conversation_id},
            projection={"_id": 1},
        )
        if owner is None:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Conversation not found or not owned by this user",
            )

    try:
        result = await upload_file_service(
            file=file,
            user_id=user_id,
            conversation_id=conversation_id,
            content_length=content_length,
        )

        log.set(
            user={"id": user_id},
            operation="upload",
            file_id=result["file_id"],
            file_name=result["filename"],
            mime_type=result.get("type", "file"),
            outcome="success",
        )
        return FileData(
            fileId=result["file_id"],
            url=result["url"],
            filename=result["filename"],
            message="File uploaded successfully",
            type=result.get("type", "file"),
        )
    except HTTPException:
        # Preserve 4xx from the upload service (413 oversize, 415 bad type, …).
        raise
    except Exception as e:
        log.error(f"Error uploading file: {e!s}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to upload file",
        )


@router.put("/{file_id}", status_code=status.HTTP_200_OK)
async def update_file_endpoint(
    file_id: str,
    update_data: dict = Body(...),
    user: dict = Depends(get_current_user),
):
    """Update file metadata; regenerates the embedding when the description changes."""
    user_id = user.get("user_id")
    if not user_id:
        return {"error": "User ID is required"}

    try:
        result = await update_file_service(
            file_id=file_id,
            user_id=user_id,
            update_data=update_data,
        )

        log.set(user={"id": user_id}, operation="update", file_id=file_id, outcome="success")
        return result
    except Exception as e:
        log.error(f"Error updating file {file_id}: {e!s}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to update file",
        )


@router.delete("/{file_id}", status_code=status.HTTP_200_OK)
async def delete_file_endpoint(
    file_id: str,
    user: dict = Depends(get_current_user),
):
    """Delete a file from Cloudinary, MongoDB, and ChromaDB."""
    try:
        result = await delete_file_service(
            file_id=file_id,
            user_id=user.get("user_id"),
        )

        log.set(
            user={"id": user.get("user_id")},
            operation="delete",
            file_id=file_id,
            outcome="success",
        )
        return result
    except Exception as e:
        log.error(f"Error deleting file {file_id}: {e!s}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to delete file",
        )
