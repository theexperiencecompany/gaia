"""Serve self-hosted blobs (uploads, generated images, avatars) to whoever their kind allows."""

from fastapi import APIRouter, Depends
from fastapi.responses import FileResponse

from app.api.v1.dependencies.oauth_dependencies import get_current_user
from app.constants.files import LOCAL_BLOB_INLINE_TYPE_PREFIXES, LOCAL_BLOB_RESPONSE_HEADERS
from app.models.user_models import AuthenticatedUser
from app.services.blob_store import open_readable_blob
from shared.py.wide_events import log

router = APIRouter()


@router.get("/blobs/{owner_id}/{key}", response_class=FileResponse)
async def get_blob(
    owner_id: str, key: str, user: AuthenticatedUser = Depends(get_current_user)
) -> FileResponse:
    """Stream a blob the caller may read (BLOB_AUDIENCE); Range requests are honoured."""
    log.set(user={"id": user.user_id}, blob={"operation": "read", "owner_id": owner_id})
    blob = await open_readable_blob(user.user_id, owner_id, key)
    log.set_ns("blob", content_type=blob.content_type)
    return FileResponse(
        blob.path,
        media_type=blob.content_type,
        filename=key,
        headers=LOCAL_BLOB_RESPONSE_HEADERS,
        content_disposition_type=(
            "inline"
            if blob.content_type.startswith(LOCAL_BLOB_INLINE_TYPE_PREFIXES)
            else "attachment"
        ),
    )
