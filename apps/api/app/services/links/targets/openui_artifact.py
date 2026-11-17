"""An artifact create_artifact made: its program, which the page renders as data."""

from app.db.repositories.openui_artifacts import openui_artifact_repository
from app.db.repositories.users import user_repository
from app.models.short_link_models import (
    LinkSnapshot,
    LinkViewerKind,
    PublicOpenUIArtifact,
    ShortLink,
    ShortLinkTargetType,
)
from app.services.links.spec import ExportedFile, LinkTargetSpec, PreviewFacts
from app.services.openui_artifacts.export import owner_artifact_pdf, pdf_download_headers
from shared.py.wide_events import log


async def _project(link: ShortLink, _viewer: LinkViewerKind) -> PublicOpenUIArtifact | None:
    artifact = await openui_artifact_repository.get(link.target_id, user_id=link.user_id)
    if artifact is None:
        return None
    owner = await user_repository.get(link.user_id)
    return PublicOpenUIArtifact(
        target_type=ShortLinkTargetType.OPENUI_ARTIFACT,
        kind=artifact.kind,
        title=artifact.title,
        program=artifact.program,
        created_at=artifact.created_at,
        shared_by=owner.name if owner is not None and owner.name else None,
    )


async def _preview(
    owner_id: str, target_id: str, _snapshot: LinkSnapshot | None
) -> PreviewFacts | None:
    artifact = await openui_artifact_repository.get(target_id, user_id=owner_id)
    return PreviewFacts(title=artifact.title, image_url=None) if artifact else None


async def _export(owner_id: str, target_id: str) -> ExportedFile:
    artifact, pdf = await owner_artifact_pdf(owner_id, target_id)
    log.set(artifact={"kind": artifact.kind.value, "pdf_bytes": len(pdf)})
    return ExportedFile(
        body=pdf, media_type="application/pdf", headers=pdf_download_headers(artifact)
    )


SPEC = LinkTargetSpec(
    type=ShortLinkTargetType.OPENUI_ARTIFACT,
    kind_line="A report or dashboard GAIA made, shared with you.",
    project=_project,
    preview=_preview,
    in_conversation=openui_artifact_repository.ids_in_conversation,
    export=_export,
)
