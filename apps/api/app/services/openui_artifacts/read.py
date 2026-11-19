"""Owner reads of a stored artifact."""

from app.db.repositories.openui_artifacts import openui_artifact_repository
from app.models.openui_artifact_models import OpenUIArtifact, OpenUIArtifactResponse
from app.utils.errors import AppError


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


async def read_artifact(user_id: str, artifact_id: str) -> OpenUIArtifactResponse:
    """Read the owner's artifact, program included."""
    return artifact_response(await get_owned_artifact(user_id, artifact_id))
