from typing import Annotated

from fastapi import APIRouter, Depends, Response

from app.api.v1.dependencies.oauth_dependencies import get_current_user
from app.models.openui_artifact_models import OpenUIArtifactResponse
from app.models.user_models import AuthenticatedUser
from app.services.openui_artifacts.export import owner_artifact_pdf, pdf_download_headers
from app.services.openui_artifacts.read import read_artifact
from shared.py.wide_events import log

router = APIRouter(prefix="/artifacts", tags=["Artifacts"])


@router.get("/{artifact_id}")
async def get_artifact(
    artifact_id: str,
    user: Annotated[AuthenticatedUser, Depends(get_current_user)],
) -> OpenUIArtifactResponse:
    """One of the user's artifacts, program included."""
    log.set(user={"id": user.user_id}, artifact={"operation": "read", "id": artifact_id})
    artifact = await read_artifact(user.user_id, artifact_id)
    log.set_ns("artifact", kind=artifact.kind.value, version=artifact.version)
    return artifact


@router.get(
    "/{artifact_id}/pdf",
    response_class=Response,
    responses={200: {"content": {"application/pdf": {}}}},
)
async def get_artifact_pdf(
    artifact_id: str,
    user: Annotated[AuthenticatedUser, Depends(get_current_user)],
) -> Response:
    """One of the user's artifacts as an A4 PDF."""
    log.set(user={"id": user.user_id}, artifact={"operation": "pdf", "id": artifact_id})
    artifact, pdf = await owner_artifact_pdf(user.user_id, artifact_id)
    log.set_ns("artifact", kind=artifact.kind.value, pdf_bytes=len(pdf))
    return Response(pdf, media_type="application/pdf", headers=pdf_download_headers(artifact))
