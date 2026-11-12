"""Owner reads of a stored artifact."""

from app.db.repositories.openui_artifacts import openui_artifact_repository
from app.models.openui_artifact_models import OpenUIArtifact, OpenUIArtifactResponse
from app.services.analytics_service import capture
from app.utils.errors import AppError
from shared.py.analytics import UserId
from shared.py.analytics.catalog.artifacts import ArtifactOpened


class ArtifactNotFoundError(AppError):
    """No artifact with that id belongs to the user."""


async def get_owned_artifact(user_id: str, artifact_id: str) -> OpenUIArtifact:
    artifact = await openui_artifact_repository.get(artifact_id, user_id=user_id)
    if artifact is None:
        raise ArtifactNotFoundError(message="artifact not found", status_code=404)
    return artifact


def artifact_response(artifact: OpenUIArtifact) -> OpenUIArtifactResponse:
    return OpenUIArtifactResponse(
        id=artifact.id,
        kind=artifact.kind,
        title=artifact.title,
        program=artifact.program,
        version=artifact.version,
        conversation_id=artifact.conversation_id,
        created_at=artifact.created_at,
    )


async def read_artifact(user_id: str, artifact_id: str, *, opened: bool) -> OpenUIArtifactResponse:
    """Read the owner's artifact; opened marks a viewer load, what artifact:opened counts."""
    artifact = await get_owned_artifact(user_id, artifact_id)
    if opened:
        capture(UserId(user_id), ArtifactOpened(kind=artifact.kind.value, via="chat"))
    return artifact_response(artifact)
