"""An artifact create_artifact made: its program, which the page renders as data."""

from app.db.repositories.openui_artifacts import openui_artifact_repository
from app.db.repositories.users import user_repository
from app.models.short_link_models import LinkSnapshot, PublicOpenUIArtifact, ShortLinkTargetType
from app.services.links.spec import LinkTargetSpec, PreviewFacts


async def _project(
    owner_id: str, target_id: str, _snapshot: LinkSnapshot | None
) -> PublicOpenUIArtifact | None:
    artifact = await openui_artifact_repository.get(target_id, user_id=owner_id)
    if artifact is None:
        return None
    owner = await user_repository.get(owner_id)
    return PublicOpenUIArtifact(
        target_type=ShortLinkTargetType.OPENUI_ARTIFACT,
        kind=artifact.kind,
        title=artifact.title,
        program=artifact.program,
        version=artifact.version,
        created_at=artifact.created_at,
        shared_by=owner.name if owner is not None and owner.name else None,
    )


async def _preview(
    owner_id: str, target_id: str, _snapshot: LinkSnapshot | None
) -> PreviewFacts | None:
    artifact = await openui_artifact_repository.get(target_id, user_id=owner_id)
    return PreviewFacts(title=artifact.title, image_url=None) if artifact else None


SPEC = LinkTargetSpec(
    type=ShortLinkTargetType.OPENUI_ARTIFACT,
    kind_line="A report or dashboard GAIA made, shared with you.",
    project=_project,
    preview=_preview,
)
