"""Mint, open, change and revoke heygaia.link links, for every target type alike.

Two ways a link comes to exist, with one rule between them: sharing is the
owner's call. share is the owner asking for a link (the share menu) and always
yields one. optional_short_link is GAIA attaching a link to something it hands
over (a file it wrote, a finished todo, a workflow result, a brief); it never
re-shares a target the owner turned off, let expire, or GAIA took down, and a
failure costs only the link, never the message carrying it.

Per-type facts live in the registry; nothing here branches on a target type.
"""

from datetime import UTC, datetime
import secrets

from pymongo.errors import DuplicateKeyError, PyMongoError

from app.config.settings import settings
from app.db.repositories.short_links import (
    LIVE_TARGET_UNIQUE_INDEX,
    SLUG_UNIQUE_INDEX,
    short_link_repository,
)
from app.models.short_link_models import (
    LinkDenial,
    LinkEnvelope,
    LinkSettings,
    LinkSettingsUpdate,
    LinkSnapshot,
    LinkViewer,
    LinkViewerKind,
    PublicShortLinkView,
    RevokeReason,
    ShortLink,
    ShortLinkResponse,
    ShortLinkTargetType,
    ShortLinkUpdate,
)
from app.services.analytics_service import analytics_day_start, capture
from app.services.links.access import Denied, dead_state, evaluate
from app.services.links.content import (
    delete_snapshot,
    framed_content,
    publish,
    servable,
    unchanged,
)
from app.services.links.errors import LinkDeniedError, LinkTargetNotFoundError
from app.services.links.registry import REGISTRY
from app.utils.errors import AppError
from app.utils.log_identifiers import hash_link_viewer, hash_short_link_slug
from shared.py.analytics import Dedupe, UserId
from shared.py.analytics.catalog.short_links import (
    ShortLinkAccessChanged,
    ShortLinkCreated,
    ShortLinkDenied,
    ShortLinkOpened,
    ShortLinkRevoked,
    ShortLinkRotated,
)
from shared.py.wide_events import log

# The slug is the capability for unlisted links, so it must survive guessing:
# 11 base62 chars ≈ 65 bits; rate limits close enumeration, not length.
# Lengthening later is safe: resolution is an exact match.
SLUG_ALPHABET = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"
SLUG_LENGTH = 11

# Cap on random-slug attempts. Exhausting it means the unique index is missing,
# which must fail loudly rather than silently reuse a slug.
MAX_SLUG_ATTEMPTS = 10

# The newest link to a target revoked for one of these means sharing is off until the owner shares again.
_SHARING_OFF = frozenset({RevokeReason.OWNER, RevokeReason.EXPIRED, RevokeReason.TAKEDOWN})


class ShortLinkExhaustedError(RuntimeError):
    """A unique slug could not be minted within MAX_SLUG_ATTEMPTS."""


def _random_slug() -> str:
    return "".join(secrets.choice(SLUG_ALPHABET) for _ in range(SLUG_LENGTH))


def build_url(slug: str) -> str:
    return f"{settings.SHORTLINK_BASE_URL}/{slug}"


def link_response(link: ShortLink) -> ShortLinkResponse:
    snapshot = link.snapshot
    restricted = snapshot is not None and snapshot.restricted_by is not None
    return ShortLinkResponse(
        url=build_url(link.slug),
        slug=link.slug,
        access=link.access,
        grantees=link.grantees,
        expires_at=link.expires_at,
        content_max_access=snapshot.max_access if snapshot and restricted else None,
    )


def _now() -> datetime:
    return datetime.now(UTC)


async def _snapshot_for(
    user_id: str, target_type: ShortLinkTargetType, target_id: str
) -> LinkSnapshot | None:
    """Publish the target's bytes when its type serves any; raise when the owner has no such target."""
    spec = REGISTRY[target_type]
    if spec.source is None:
        if await spec.project(user_id, target_id, None) is None:
            raise LinkTargetNotFoundError()
        return None
    source = await spec.source(user_id, target_id)
    if source is None:
        raise LinkTargetNotFoundError()
    return await publish(user_id, target_type, source)


async def _release_snapshot(user_id: str, snapshot: LinkSnapshot | None) -> None:
    """Delete a snapshot's bytes once no live link pins them."""
    if snapshot is None or snapshot.content_id is None:
        return
    if await short_link_repository.live_pins_content(snapshot.content_id):
        return
    await delete_snapshot(user_id, snapshot)


async def _insert(link_fields: ShortLink) -> ShortLink | None:
    """Insert under a fresh slug; None when a concurrent mint already made the target's live link."""
    for _ in range(MAX_SLUG_ATTEMPTS):
        try:
            return await short_link_repository.create(
                link_fields.model_copy(update={"slug": _random_slug()})
            )
        except DuplicateKeyError as e:
            violated = str(e)
            if f"index: {SLUG_UNIQUE_INDEX}" in violated:
                continue
            if f"index: {LIVE_TARGET_UNIQUE_INDEX}" in violated:
                return None
            raise
    log.error("short_link.slug_exhausted", user_id=link_fields.user_id)
    raise ShortLinkExhaustedError(
        f"Could not mint a unique slug for user {link_fields.user_id} after {MAX_SLUG_ATTEMPTS} attempts"
    )


async def _live_link(
    user_id: str, target_type: ShortLinkTargetType, target_id: str
) -> ShortLink | None:
    """Return the target's live link; an expired one is revoked here so the next share mints afresh."""
    live = await short_link_repository.get_live_for_target(user_id, target_type, target_id)
    if live is None or dead_state(live, _now()) is not LinkDenial.EXPIRED:
        return live
    await short_link_repository.revoke(user_id, live.slug, RevokeReason.EXPIRED)
    await _release_snapshot(user_id, live.snapshot)
    return None


async def share(
    user_id: str,
    target_type: ShortLinkTargetType,
    target_id: str,
    link_settings: LinkSettings,
    *,
    gaia_attached: bool = False,
) -> ShortLink:
    """Return the target's live link, minting one with link_settings when none is live.

    The owner sharing (callers prove nothing; the spec's read under user_id is
    the ownership check) is the only path that re-enables a target they stopped
    sharing. Idempotent: racing callers all get the one live link.
    """
    existing = await _live_link(user_id, target_type, target_id)
    if existing is not None:
        return existing
    snapshot = await _snapshot_for(user_id, target_type, target_id)
    candidate = ShortLink(
        slug="",
        user_id=user_id,
        target_type=target_type,
        target_id=target_id,
        access=link_settings.access,
        grantees=[str(email) for email in link_settings.grantees],
        expires_at=link_settings.expires_at,
        snapshot=snapshot,
    )
    minted = await _insert(candidate)
    if minted is None:
        # Lost a concurrent mint: the winner's link is the one live link, and the snapshot just
        # published belongs to nobody.
        await _release_snapshot(user_id, snapshot)
        winner = await short_link_repository.get_live_for_target(user_id, target_type, target_id)
        if winner is None:
            return await share(user_id, target_type, target_id, link_settings)
        return winner
    capture(
        UserId(user_id),
        ShortLinkCreated(
            target_type=target_type.value,
            access=minted.access.value,
            origin="gaia_attached" if gaia_attached else "owner_share",
            has_expiry=minted.expires_at is not None,
        ),
    )
    return minted


async def live_share_link(
    user_id: str, target_type: ShortLinkTargetType, target_id: str
) -> ShortLink | None:
    """Return the owner's live link to a target, or None when it is not shared. Never mints."""
    return await _live_link(user_id, target_type, target_id)


async def _refresh_snapshot(link: ShortLink) -> None:
    """Point a live file link at the file as it is now, when its bytes changed."""
    spec = REGISTRY[link.target_type]
    if spec.source is None:
        return
    source = await spec.source(link.user_id, link.target_id)
    if source is None or unchanged(link.snapshot, source):
        return
    fresh = await publish(link.user_id, link.target_type, source)
    await short_link_repository.update(
        link.slug, user_id=link.user_id, update=ShortLinkUpdate(snapshot=fresh)
    )
    await _release_snapshot(link.user_id, link.snapshot)


async def optional_short_link(
    user_id: str, target_type: ShortLinkTargetType, target_id: str
) -> str | None:
    """Return the link GAIA attaches to something it hands the owner, or None.

    A file's live link moves to the file as it is now. None when sharing is off
    for the target (its newest link was revoked by the owner, expired or taken
    down; that sticks until they share it themselves), or when minting fails: an
    error event that costs only the link.
    """
    try:
        latest = await short_link_repository.get_latest_for_target(user_id, target_type, target_id)
        if latest is not None:
            off = latest.revoked_reason or RevokeReason.OWNER
            if (latest.revoked and off in _SHARING_OFF) or dead_state(latest, _now()) in (
                LinkDenial.EXPIRED,
                LinkDenial.REMOVED,
            ):
                log.info(
                    "short_link.sharing_disabled", user_id=user_id, target_type=target_type.value
                )
                return None
            if not latest.revoked:
                await _refresh_snapshot(latest)
                return build_url(latest.slug)
        link = await share(user_id, target_type, target_id, LinkSettings(), gaia_attached=True)
        return build_url(link.slug)
    except (PyMongoError, ShortLinkExhaustedError, AppError) as exc:
        log.error(
            "short_link.mint_failed",
            user_id=user_id,
            target_type=target_type.value,
            error_type=type(exc).__name__,
            error=str(exc),
        )
        return None


async def _owned_live(user_id: str, slug: str) -> ShortLink:
    link = await short_link_repository.get_by_slug(slug)
    if link is None or link.user_id != user_id or dead_state(link, _now()) is not None:
        raise LinkTargetNotFoundError(message="Link not found")
    return link


async def update_settings(user_id: str, slug: str, change: LinkSettingsUpdate) -> ShortLink:
    """Change who a live link opens for, or its expiry; an omitted field keeps its value."""
    link = await _owned_live(user_id, slug)
    if change.expires_at is not None and change.expires_at <= _now():
        raise AppError(
            message="That expiry is already in the past",
            fix="Pick a time from now on, or no expiry",
            status_code=422,
            code="link_expiry_in_past",
        )
    fields = change.model_dump(exclude_unset=True)
    if not fields:
        raise AppError(message="Nothing to change", status_code=422, code="link_settings_empty")
    if "grantees" in fields:
        fields["grantees"] = [str(email) for email in change.grantees or []]
    updated = await short_link_repository.update(
        slug, user_id=user_id, update=ShortLinkUpdate(**fields)
    )
    if updated is None:
        raise LinkTargetNotFoundError(message="Link not found")
    if updated.access != link.access or updated.grantees != link.grantees:
        capture(
            UserId(user_id),
            ShortLinkAccessChanged(
                target_type=link.target_type.value,
                from_access=link.access.value,
                to_access=updated.access.value,
                grantee_count=len(updated.grantees),
            ),
        )
    return updated


async def rotate(user_id: str, slug: str) -> ShortLink:
    """Replace a live link with a new URL carrying the same settings and file; the old URL dies."""
    link = await _owned_live(user_id, slug)
    revoked = await short_link_repository.revoke(user_id, slug, RevokeReason.ROTATED)
    if revoked is None:
        raise LinkTargetNotFoundError(message="Link not found")
    minted = await _insert(
        link.model_copy(update={"id": "", "created_at": _now(), "updated_at": None})
    )
    if minted is None:
        raise AppError(
            message="This was shared again while the link was being replaced",
            fix="Reload to see its current link",
            status_code=409,
            code="link_rotate_conflict",
        )
    capture(
        UserId(user_id),
        ShortLinkRotated(target_type=link.target_type.value, access=link.access.value),
    )
    return minted


async def stop_sharing(user_id: str, target_type: ShortLinkTargetType, target_id: str) -> bool:
    """Turn sharing off for a target on its owner's behalf: its live link dies at once.

    The revoked link stays on record as the target's newest, which is what
    stops optional_short_link from handing out a fresh one. Idempotent; False
    when the target had no live link to revoke.
    """
    live = await short_link_repository.get_live_for_target(user_id, target_type, target_id)
    if live is None:
        return False
    revoked = await short_link_repository.revoke(user_id, live.slug, RevokeReason.OWNER)
    if revoked is None:
        return False
    await _release_snapshot(user_id, live.snapshot)
    log.set(short_link={"slug_hash": hash_short_link_slug(live.slug)})
    capture(
        UserId(user_id),
        ShortLinkRevoked(target_type=target_type.value, reason=RevokeReason.OWNER.value),
    )
    return True


def _served_snapshot(link: ShortLink) -> LinkSnapshot | None:
    """Return the snapshot as the link may serve it: no bytes when its access is wider than they allow."""
    snapshot = link.snapshot
    if snapshot is None or servable(snapshot, link.access):
        return snapshot
    return snapshot.model_copy(update={"content_id": None})


def _viewer_key(viewer: LinkViewer) -> str:
    return viewer.user_id or hash_link_viewer(viewer.ip, viewer.user_agent)


def _day_dedupe(slug: str, viewer: LinkViewer, what: str) -> Dedupe:
    day = analytics_day_start(_now())
    return Dedupe(
        key=f"{hash_short_link_slug(slug)}:{_viewer_key(viewer)}:{what}:{day.date().isoformat()}",
        occurred_at=day,
    )


def _deny(link: ShortLink | None, viewer: LinkViewer, denial: LinkDenial) -> LinkDeniedError:
    """Build the error a denial raises, counted for the owner whenever the link exists."""
    if link is not None and denial is not LinkDenial.NOT_FOUND:
        reason = denial.value.removeprefix("link_")
        capture(
            UserId(link.user_id),
            ShortLinkDenied(target_type=link.target_type.value, reason=reason),
            _day_dedupe(link.slug, viewer, reason),
        )
    signed_in_as = viewer.email if denial is LinkDenial.FORBIDDEN else None
    return LinkDeniedError.for_denial(denial, signed_in_as=signed_in_as)


async def get_link(slug: str) -> ShortLink | None:
    return await short_link_repository.get_by_slug(slug)


async def _granted_view(
    link: ShortLink | None, viewer: LinkViewer
) -> tuple[ShortLink, LinkViewerKind, PublicShortLinkView]:
    if link is None:
        raise _deny(None, viewer, LinkDenial.NOT_FOUND)
    decision = evaluate(link, viewer, _now())
    if isinstance(decision, Denied):
        raise _deny(link, viewer, decision.denial)
    view = await REGISTRY[link.target_type].project(
        link.user_id, link.target_id, _served_snapshot(link)
    )
    if view is None:
        raise _deny(link, viewer, LinkDenial.TARGET_DELETED)
    return link, decision.viewer_kind, view


async def resolve(link: ShortLink | None, viewer: LinkViewer) -> LinkEnvelope:
    """Open a link for viewer, or raise the denial they see. A read: never counts an open.

    The target is read under the owner on the link doc, only through its type's
    projection. A target the owner has since deleted is TARGET_DELETED.
    """
    granted, kind, view = await _granted_view(link, viewer)
    return LinkEnvelope(
        access=granted.access,
        target_type=granted.target_type,
        view=view,
        content=framed_content(granted.snapshot, granted.access),
        downloadable=servable(granted.snapshot, granted.access),
        is_owner=kind is LinkViewerKind.OWNER,
    )


async def record_open(link: ShortLink | None, viewer: LinkViewer) -> LinkViewerKind:
    """Count a viewer opening a link for its owner, at most once a day per viewer.

    The owner and unfurl bots are classified but never counted; a viewer the
    link does not open for raises its denial.
    """
    decision = evaluate(link, viewer, _now())
    if isinstance(decision, Denied):
        raise _deny(link, viewer, decision.denial)
    if decision.viewer_kind is LinkViewerKind.RECIPIENT and link is not None:
        capture(
            UserId(link.user_id),
            ShortLinkOpened(
                target_type=link.target_type.value,
                access=link.access.value,
                viewer_signed_in=viewer.user_id is not None,
            ),
            _day_dedupe(link.slug, viewer, "opened"),
        )
    return decision.viewer_kind


async def openable_link(
    link: ShortLink | None, viewer: LinkViewer, target_type: ShortLinkTargetType | None = None
) -> ShortLink:
    """Return the link when viewer may open it (and it points at target_type, when given); raise the denial otherwise."""
    granted, _, _ = await _granted_view(link, viewer)
    if target_type is not None and granted.target_type is not target_type:
        raise LinkDeniedError.for_denial(LinkDenial.NOT_FOUND)
    return granted
