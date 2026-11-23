"""What a chat preview or the page's metadata may show for a link, by its access level and state.

Chat apps cache a preview and show it to everyone in the conversation, so only
a live public or unlisted link (which anyone in that chat can open by tapping)
previews its real title and image. Gated links preview their kind; dead links
say they are gone and disclose nothing else.
"""

from datetime import UTC, datetime

from app.models.short_link_models import LinkAccess, LinkPreviewMeta, ShortLink
from app.services.links.access import dead_state, is_open, servable_content
from app.services.links.registry import REGISTRY

DEAD_TITLE = "This link is no longer available"
DEAD_DESCRIPTION = "Ask the person who shared it for a new one."
GATED_TITLE = "Shared from GAIA"
GATED_DESCRIPTION = "Sign in to view."


def _dead() -> LinkPreviewMeta:
    return LinkPreviewMeta(
        live=False,
        target_type=None,
        access=None,
        indexable=False,
        title=DEAD_TITLE,
        description=DEAD_DESCRIPTION,
        image_url=None,
    )


async def preview_meta(link: ShortLink | None) -> LinkPreviewMeta:
    """Build the preview a link shows anyone, signed in or not."""
    now = datetime.now(UTC)
    if link is None or dead_state(link, now) is not None:
        return _dead()
    spec = REGISTRY[link.target.type]
    if not is_open(link.access):
        return LinkPreviewMeta(
            live=True,
            target_type=link.target.type,
            access=link.access,
            indexable=False,
            title=GATED_TITLE,
            description=GATED_DESCRIPTION,
            image_url=None,
        )
    facts = await spec.preview(link.user_id, link.target, servable_content(link, now))
    if facts is None:
        return _dead()
    return LinkPreviewMeta(
        live=True,
        target_type=link.target.type,
        access=link.access,
        indexable=link.access is LinkAccess.PUBLIC,
        title=facts.title,
        description=spec.kind_line,
        image_url=facts.image_url,
    )
