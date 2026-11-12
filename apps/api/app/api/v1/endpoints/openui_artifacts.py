from typing import Annotated

from fastapi import APIRouter, Depends, Query

from app.api.v1.dependencies.oauth_dependencies import get_current_user
from app.models.openui_artifact_models import OpenUIArtifactResponse
from app.models.user_models import AuthenticatedUser
from app.services.openui_artifacts.read import read_artifact
from shared.py.wide_events import log

router = APIRouter(prefix="/artifacts", tags=["Artifacts"])


@router.get("/{artifact_id}")
async def get_artifact(
    artifact_id: str,
    user: Annotated[AuthenticatedUser, Depends(get_current_user)],
    opened: Annotated[bool, Query(description="True when the viewer opens it")] = False,
) -> OpenUIArtifactResponse:
    """One of the user's artifacts, program included."""
    log.set(user={"id": user.user_id}, artifact={"operation": "read", "id": artifact_id})
    artifact = await read_artifact(user.user_id, artifact_id, opened=opened)
    log.set_ns("artifact", kind=artifact.kind.value, version=artifact.version)
    return artifact
