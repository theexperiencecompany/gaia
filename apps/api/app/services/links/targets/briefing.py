"""A persisted daily or weekly brief: its owner is sent to the full brief, anyone else sees its front page."""

from app.db.repositories.briefings import briefing_repository
from app.models.short_link_models import (
    LinkSnapshot,
    LinkViewerKind,
    PublicBriefing,
    RecordTarget,
    ShortLink,
    ShortLinkTargetType,
)
from app.services.briefing.message import full_brief_url
from app.services.briefing.view import public_view
from app.services.links.spec import LinkTargetSpec, PreviewFacts


async def _project(
    link: ShortLink, target: RecordTarget, viewer: LinkViewerKind
) -> PublicBriefing | None:
    briefing = await briefing_repository.get(target.id, user_id=link.user_id)
    if briefing is None:
        return None
    view = public_view(briefing)
    if viewer is LinkViewerKind.OWNER:
        return view.model_copy(update={"full_url": full_brief_url(briefing.id)})
    return view


async def _preview(
    owner_id: str, target: RecordTarget, _snapshot: LinkSnapshot | None
) -> PreviewFacts | None:
    briefing = await briefing_repository.get(target.id, user_id=owner_id)
    if briefing is None:
        return None
    return PreviewFacts(title=briefing.payload.headline, image_url=None)


SPEC = LinkTargetSpec(
    type=ShortLinkTargetType.BRIEFING,
    target=RecordTarget,
    kind_line="A brief from GAIA, the proactive personal assistant.",
    project=_project,
    preview=_preview,
)
