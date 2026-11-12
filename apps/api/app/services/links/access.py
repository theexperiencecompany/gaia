"""Who may open a link: one pure decision over the link doc, the viewer and the clock."""

from dataclasses import dataclass
from datetime import datetime

from app.constants.short_links import UNFURL_BOT_USER_AGENT_MARKERS
from app.models.short_link_models import (
    LinkAccess,
    LinkDenial,
    LinkViewer,
    LinkViewerKind,
    RevokeReason,
    ShortLink,
)

# Wider levels open for more people; a snapshot capped at one level serves at it and narrower.
_WIDTH: dict[LinkAccess, int] = {
    LinkAccess.OWNER: 0,
    LinkAccess.PEOPLE: 1,
    LinkAccess.UNLISTED: 2,
    LinkAccess.PUBLIC: 3,
}

_REVOKED_DENIAL: dict[RevokeReason, LinkDenial] = {
    RevokeReason.OWNER: LinkDenial.REVOKED,
    RevokeReason.ROTATED: LinkDenial.REVOKED,
    RevokeReason.EXPIRED: LinkDenial.EXPIRED,
    RevokeReason.TAKEDOWN: LinkDenial.REMOVED,
    RevokeReason.TARGET_DELETED: LinkDenial.TARGET_DELETED,
}


@dataclass(frozen=True, slots=True)
class Granted:
    viewer_kind: LinkViewerKind


@dataclass(frozen=True, slots=True)
class Denied:
    denial: LinkDenial


def at_most(access: LinkAccess, cap: LinkAccess) -> bool:
    """Whether access opens for no one beyond cap."""
    return _WIDTH[access] <= _WIDTH[cap]


def is_unfurl_bot(user_agent: str) -> bool:
    lowered = user_agent.lower()
    return any(marker in lowered for marker in UNFURL_BOT_USER_AGENT_MARKERS)


def dead_state(link: ShortLink, now: datetime) -> LinkDenial | None:
    """Why a link no longer opens for anyone, or None while it is live."""
    if link.suspended:
        return LinkDenial.REMOVED
    if link.revoked:
        return _REVOKED_DENIAL[link.revoked_reason or RevokeReason.OWNER]
    if link.expires_at is not None and link.expires_at <= now:
        return LinkDenial.EXPIRED
    return None


def _may_open(link: ShortLink, viewer: LinkViewer) -> LinkDenial | None:
    match link.access:
        case LinkAccess.PUBLIC | LinkAccess.UNLISTED:
            return None
        case LinkAccess.PEOPLE:
            if viewer.user_id is None:
                return LinkDenial.SIGN_IN_REQUIRED
            email = (viewer.email or "").lower()
            by_email = bool(email) and email in {grantee.lower() for grantee in link.grantees}
            return None if by_email or viewer.user_id in link.grantee_ids else LinkDenial.FORBIDDEN
        case LinkAccess.OWNER:
            return LinkDenial.SIGN_IN_REQUIRED if viewer.user_id is None else LinkDenial.FORBIDDEN


def evaluate(link: ShortLink | None, viewer: LinkViewer, now: datetime) -> Granted | Denied:
    """Decide whether viewer may open link now; the owner opens every live link at every level."""
    if link is None:
        return Denied(LinkDenial.NOT_FOUND)
    dead = dead_state(link, now)
    if dead is not None:
        return Denied(dead)
    if viewer.user_id is not None and viewer.user_id == link.user_id:
        return Granted(LinkViewerKind.OWNER)
    denial = _may_open(link, viewer)
    if denial is not None:
        return Denied(denial)
    if is_unfurl_bot(viewer.user_agent):
        return Granted(LinkViewerKind.UNFURL_BOT)
    return Granted(LinkViewerKind.RECIPIENT)
