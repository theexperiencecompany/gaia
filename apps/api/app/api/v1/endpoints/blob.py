"""Serve self-hosted blobs (uploads, generated images, avatars) to whoever their kind allows."""

from fastapi import APIRouter, Depends
from fastapi.responses import FileResponse, Response

from app.api.v1.dependencies.oauth_dependencies import get_current_user
from app.constants.files import BLOB_ROUTE_INLINE_TYPE_PREFIXES, BLOB_ROUTE_RESPONSE_HEADERS
from app.models.user_models import AuthenticatedUser
from app.services.blob_store import LocalBlob, open_readable_blob
from shared.py.wide_events import log

router = APIRouter()


@router.get("/blobs/{owner_id}/{key}", response_class=FileResponse)
async def get_blob(
    owner_id: str, key: str, user: AuthenticatedUser = Depends(get_current_user)
) -> Response:
    """Return a blob the caller may read (BLOB_AUDIENCE); local blobs honour Range requests."""
    log.set(user={"id": user.user_id}, blob={"operation": "read", "owner_id": owner_id})
    blob = await open_readable_blob(user.user_id, owner_id, key)
    log.set_ns("blob", content_type=blob.content_type)
    disposition = (
        "inline" if blob.content_type.startswith(BLOB_ROUTE_INLINE_TYPE_PREFIXES) else "attachment"
    )
    if isinstance(blob, LocalBlob):
        return FileResponse(
            blob.path,
            media_type=blob.content_type,
            filename=key,
            headers=BLOB_ROUTE_RESPONSE_HEADERS,
            content_disposition_type=disposition,
        )
    # Keys are [A-Za-z0-9._-] only, so the filename needs no quoting.
    return Response(
        blob.content,
        media_type=blob.content_type,
        headers={
            **BLOB_ROUTE_RESPONSE_HEADERS,
            "Content-Disposition": f'{disposition}; filename="{key}"',
        },
    )
