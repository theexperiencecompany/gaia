"""Who may open a link: one pure decision over the link doc, the viewer and the clock."""

from dataclasses import dataclass
from datetime import datetime

from app.constants.short_links import UNFURL_BOT_USER_AGENT_MARKERS
from app.models.short_link_models import (
    LinkAccess,
    LinkDenial,
    LinkSnapshot,
    LinkState,
    LinkViewer,
    LinkViewerKind,
    RevokeReason,
    ShortLink,
)

#: Every level by who it opens for, widest first; a snapshot capped at one level serves at it and narrower.
ACCESS_WIDEST_FIRST = (LinkAccess.PUBLIC, LinkAccess.UNLISTED, LinkAccess.PEOPLE, LinkAccess.OWNER)

_REVOKED_STATE: dict[RevokeReason, LinkState] = {
    RevokeReason.OWNER: LinkState.STOPPED,
    RevokeReason.ROTATED: LinkState.ROTATED,
    RevokeReason.EXPIRED: LinkState.EXPIRED,
    RevokeReason.TAKEDOWN: LinkState.TAKEN_DOWN,
    RevokeReason.TARGET_DELETED: LinkState.TARGET_DELETED,
    RevokeReason.ACCOUNT_REMOVED: LinkState.ACCOUNT_REMOVED,
}

_DENIAL: dict[LinkState, LinkDenial] = {
    LinkState.SUSPENDED: LinkDenial.REMOVED,
    LinkState.EXPIRED: LinkDenial.EXPIRED,
    LinkState.STOPPED: LinkDenial.REVOKED,
    LinkState.ROTATED: LinkDenial.REVOKED,
    LinkState.TAKEN_DOWN: LinkDenial.REMOVED,
    LinkState.TARGET_DELETED: LinkDenial.TARGET_DELETED,
    LinkState.ACCOUNT_REMOVED: LinkDenial.REVOKED,
}

#: States after which GAIA attaches no new link to the target until its owner shares it again.
SHARING_OFF = frozenset(
    {
        LinkState.SUSPENDED,
        LinkState.EXPIRED,
        LinkState.STOPPED,
        LinkState.TAKEN_DOWN,
        LinkState.ACCOUNT_REMOVED,
    }
)

_OPEN = frozenset({LinkAccess.PUBLIC, LinkAccess.UNLISTED})

#: Dead by the owner's own hand (stopped, rotated or expired): still theirs to open.
OWNER_STILL_OPENS = frozenset({LinkDenial.REVOKED, LinkDenial.EXPIRED})


@dataclass(frozen=True, slots=True)
class Granted:
    viewer_kind: LinkViewerKind


@dataclass(frozen=True, slots=True)
class Denied:
    denial: LinkDenial


def at_most(access: LinkAccess, cap: LinkAccess) -> bool:
    """Whether access opens for no one beyond cap."""
    return ACCESS_WIDEST_FIRST.index(access) >= ACCESS_WIDEST_FIRST.index(cap)


def is_open(access: LinkAccess) -> bool:
    """Whether a link at access opens for anyone holding its URL, signed in or not."""
    return access in _OPEN


def servable_content(link: ShortLink, now: datetime) -> LinkSnapshot | None:
    """Return the snapshot whose bytes link may serve now; None when dead, unpublished or wider than they allow."""
    snapshot = link.snapshot
    if (
        snapshot is None
        or snapshot.content_id is None
        or dead_state(link, now) is not None
        or not at_most(link.access, snapshot.max_access)
    ):
        return None
    return snapshot


def is_unfurl_bot(user_agent: str) -> bool:
    lowered = user_agent.lower()
    return any(marker in lowered for marker in UNFURL_BOT_USER_AGENT_MARKERS)


def link_state(link: ShortLink, now: datetime) -> LinkState:
    """Where link stands now; the one reading of revoked, revoked_reason, suspended and expiry."""
    if link.revoked_reason is not None:
        return _REVOKED_STATE[link.revoked_reason]
    if link.suspended:
        return LinkState.SUSPENDED
    if link.expires_at is not None and link.expires_at <= now:
        return LinkState.EXPIRED
    return LinkState.LIVE


def dead_state(link: ShortLink, now: datetime) -> LinkDenial | None:
    """Why a link no longer opens for anyone, or None while it is live."""
    return _DENIAL.get(link_state(link, now))


def _is_grantee(link: ShortLink, viewer: LinkViewer) -> bool:
    by_email = viewer.email is not None and viewer.email.lower() in {
        grantee.lower() for grantee in link.grantees
    }
    return by_email or viewer.user_id in link.grantee_ids


def _may_open(link: ShortLink, viewer: LinkViewer) -> LinkDenial | None:
    """Why viewer may not open a live link they do not own, or None when they may."""
    if is_open(link.access):
        return None
    if viewer.user_id is None:
        return LinkDenial.SIGN_IN_REQUIRED
    if link.access is LinkAccess.PEOPLE and _is_grantee(link, viewer):
        return None
    return LinkDenial.FORBIDDEN


def evaluate(link: ShortLink | None, viewer: LinkViewer, now: datetime) -> Granted | Denied:
    """Decide whether viewer may open link now.

    The owner opens every link at every level, a turned-off one too: the emails and
    QR codes GAIA sent them carry it. A takedown or a deleted target closes it for them too.
    """
    if link is None:
        return Denied(LinkDenial.NOT_FOUND)
    dead = dead_state(link, now)
    is_owner = viewer.user_id is not None and viewer.user_id == link.user_id
    if is_owner and (dead is None or dead in OWNER_STILL_OPENS):
        return Granted(LinkViewerKind.OWNER)
    if dead is not None:
        return Denied(dead)
    denial = _may_open(link, viewer)
    if denial is not None:
        return Denied(denial)
    if is_unfurl_bot(viewer.user_agent):
        return Granted(LinkViewerKind.UNFURL_BOT)
    return Granted(LinkViewerKind.RECIPIENT)
