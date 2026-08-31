"""File upload, update, and delete endpoints."""

from typing import cast

from fastapi import (
    APIRouter,
    Depends,
    File,
    Form,
    Header,
    HTTPException,
    UploadFile,
    status,
)

from app.api.v1.dependencies.oauth_dependencies import get_current_user, get_user_id
from app.db.repositories.conversations import conversation_repository
from app.decorators import tiered_rate_limit
from app.models.files_models import FileDocument
from app.models.message_models import FileData
from app.models.user_models import AuthenticatedUser
from app.schemas.file import FileDeletedResponse, UpdateFileRequest
from app.services.files import FileService
from app.services.storage import SAFE_PATH_ID_PATTERN
from shared.py.wide_events import log

router = APIRouter()


@router.post("/upload", response_model=FileData, status_code=status.HTTP_201_CREATED)
@tiered_rate_limit("file_upload")
async def upload_file_endpoint(
    file: UploadFile = File(...),
    conversation_id: str | None = Form(default=None, pattern=SAFE_PATH_ID_PATTERN),
    content_length: int | None = Header(default=None, alias="content-length"),
    user: AuthenticatedUser = Depends(get_current_user),
) -> FileData:
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
        if not await conversation_repository.exists(conversation_id, user_id=user_id):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Conversation not found or not owned by this user",
            )

    try:
        # CacheInvalidator erases the wrapped function's return type; FileService.upload
        # is declared -> FileDocument, so this is correct by construction.
        uploaded = cast(
            FileDocument,
            await FileService.upload(
                file=file,
                user_id=user_id,
                conversation_id=conversation_id,
                content_length=content_length,
            ),
        )

        log.set(
            user={"id": user_id},
            operation="upload",
            file_id=uploaded.file_id,
            file_name=uploaded.filename,
            mime_type=uploaded.type,
            outcome="success",
        )
        return FileData(
            fileId=uploaded.file_id,
            url=uploaded.url,
            filename=uploaded.filename,
            message="File uploaded successfully",
            type=uploaded.type,
            description=uploaded.description,
        )
    except HTTPException:
        # Preserve 4xx from the upload service (413 oversize, 415 bad type, …).
        raise
    except Exception as e:
        log.error(
            "Error uploading file",
            user_id=user_id,
            error_type=type(e).__name__,
            error=str(e),
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to upload file",
        ) from e


@router.put("/{file_id}", status_code=status.HTTP_200_OK)
async def update_file_endpoint(
    file_id: str,
    payload: UpdateFileRequest,
    user_id: str = Depends(get_user_id),
) -> FileDocument:
    """Update file metadata; regenerates the embedding when the description changes."""
    try:
        result = await FileService.update(
            file_id=file_id,
            user_id=user_id,
            update_data=payload.model_dump(exclude_none=True),
        )

        log.set(user={"id": user_id}, operation="update", file_id=file_id, outcome="success")
        # CacheInvalidator erases the wrapped function's return type; FileService.update
        # is declared -> FileDocument, so this is correct by construction.
        return cast(FileDocument, result)
    except Exception as e:
        log.error(
            "Error updating file",
            file_id=file_id,
            user_id=user_id,
            error_type=type(e).__name__,
            error=str(e),
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to update file",
        ) from e


@router.delete("/{file_id}", status_code=status.HTTP_200_OK)
async def delete_file_endpoint(
    file_id: str,
    user_id: str = Depends(get_user_id),
) -> FileDeletedResponse:
    """Delete a file from Cloudinary, MongoDB, and ChromaDB."""
    try:
        result = await FileService.delete(
            file_id=file_id,
            user_id=user_id,
        )

        log.set(
            user={"id": user_id},
            operation="delete",
            file_id=file_id,
            outcome="success",
        )
        # CacheInvalidator erases the wrapped function's return type; FileService.delete
        # is declared -> FileDeletedResponse, so this is correct by construction.
        return cast(FileDeletedResponse, result)
    except Exception as e:
        log.error(
            "Error deleting file",
            file_id=file_id,
            user_id=user_id,
            error_type=type(e).__name__,
            error=str(e),
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to delete file",
        ) from e
