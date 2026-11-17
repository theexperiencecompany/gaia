"""Mint, open, change and revoke heygaia.link links, for every target type alike.

Two ways a link comes to exist, with one rule between them: sharing is the
owner's call. share is the owner asking for a link (the share menu) and always
yields one. attach_link is GAIA attaching a link to something it hands over (a
file it wrote, a finished todo, a workflow result, a brief): it opens for the
owner alone until they widen it, it never re-shares a target the owner turned
off, let expire, or GAIA took down, and a failed mint costs only the link, never
the message carrying it. What a model is told is a placeholder (placeholders.py),
never the URL.

Per-type facts live in the registry; nothing here branches on a target type.
"""

from dataclasses import dataclass
from datetime import UTC, datetime
import secrets

from pymongo.errors import DuplicateKeyError, PyMongoError

from app.config.settings import settings
from app.db.repositories.short_links import (
    LIVE_TARGET_UNIQUE_INDEX,
    SLUG_UNIQUE_INDEX,
    short_link_repository,
)
from app.db.repositories.users import user_repository
from app.models.short_link_models import (
    LinkAccess,
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
from app.services.links.urls import build_url
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
_SHARING_OFF = frozenset(
    {
        RevokeReason.OWNER,
        RevokeReason.EXPIRED,
        RevokeReason.TAKEDOWN,
        RevokeReason.ACCOUNT_REMOVED,
    }
)


class ShortLinkExhaustedError(RuntimeError):
    """A unique slug could not be minted within MAX_SLUG_ATTEMPTS."""


# What failing to mint looks like; reading the target (a storage outage) is not one, and propagates.
_MINT_ERRORS = (PyMongoError, ShortLinkExhaustedError)


def _random_slug() -> str:
    return "".join(secrets.choice(SLUG_ALPHABET) for _ in range(SLUG_LENGTH))


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


async def _grantee_ids(emails: list[str]) -> list[str]:
    """Resolve grantees to accounts where emails are unverified; raise naming any with no account.

    Granting an address nobody holds yet would hand the link to whoever registers it first.
    """
    if not settings.deployment.local_auth:
        return []
    ids: list[str] = []
    missing: list[str] = []
    for email in emails:
        # Exactly one account: two differing only in case cannot say which person was meant.
        matches = await user_repository.find_by_email_ignoring_case(email)
        if len(matches) == 1:
            ids.append(matches[0].id)
        else:
            missing.append(email)
    if missing:
        raise AppError(
            message="Some of these people have no account on this GAIA",
            fix="Add them after they have joined, or share with anyone who has the link",
            status_code=422,
            code="link_grantee_not_a_member",
            public={"missing": missing},
        )
    return ids


async def _snapshot_for(
    user_id: str, target_type: ShortLinkTargetType, target_id: str
) -> LinkSnapshot | None:
    """Publish the target's bytes when its type serves any; raise when the owner has no such target."""
    spec = REGISTRY[target_type]
    if spec.source is None:
        if await spec.preview(user_id, target_id, None) is None:
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
    grantees = [str(email) for email in link_settings.grantees]
    grantee_ids = await _grantee_ids(grantees)
    snapshot = await _snapshot_for(user_id, target_type, target_id)
    candidate = ShortLink(
        slug="",  # pragma: no mutate — _insert mints the slug before any write
        user_id=user_id,
        target_type=target_type,
        target_id=target_id,
        access=link_settings.access,
        grantees=grantees,
        grantee_ids=grantee_ids,
        expires_at=link_settings.expires_at,
        snapshot=snapshot,
        gaia_attached=gaia_attached,
    )
    try:
        minted = await _insert(candidate)
    except Exception:
        # The bytes were published for this link alone; nothing will ever point at them.
        await _release_snapshot(user_id, snapshot)
        raise
    if minted is None:
        # Lost a concurrent mint: the winner's link is the one live link, and the snapshot just
        # published belongs to nobody.
        await _release_snapshot(user_id, snapshot)
        return await share(user_id, target_type, target_id, link_settings)
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
    moved = await short_link_repository.update_live(
        link.user_id, link.slug, ShortLinkUpdate(snapshot=fresh)
    )
    # A link revoked meanwhile (a rotation carrying the old file forward) keeps it; the fresh one is nobody's.
    await _release_snapshot(link.user_id, link.snapshot if moved is not None else fresh)


async def attach_link(
    user_id: str,
    target_type: ShortLinkTargetType,
    target_id: str,
    access: LinkAccess = LinkAccess.OWNER,
) -> ShortLink | None:
    """Return the link GAIA attaches to something it hands the owner, or None.

    A new link opens at access (the owner alone, by default) until they widen it; a live
    one is reused, its file moved to the file as it is now. None when sharing is off for
    the target (revoked by the owner, expired or taken down) or the mint itself failed.
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
                return latest
        return await share(
            user_id, target_type, target_id, LinkSettings(access=access), gaia_attached=True
        )
    except _MINT_ERRORS as exc:
        log.error(
            "short_link.mint_failed",
            user_id=user_id,
            target_type=target_type.value,
            error_type=type(exc).__name__,
            error=str(exc),
        )
        return None


def _access_of(link: ShortLink) -> ShortLinkUpdate:
    return ShortLinkUpdate(access=link.access, grantees=link.grantees, grantee_ids=link.grantee_ids)


_OWNER_ONLY = ShortLinkUpdate(access=LinkAccess.OWNER, grantees=[], grantee_ids=[])


async def _carry_access(parent: ShortLink, follow: ShortLinkUpdate) -> None:
    """Give the GAIA-attached links of the targets parent carries (a brief's items) follow's access.

    A link the owner set themselves keeps its own settings.
    """
    carries = REGISTRY[parent.target_type].carries
    if carries is None:
        return
    for target_type, target_id in await carries(parent.user_id, parent.target_id):
        child = await short_link_repository.get_live_for_target(
            parent.user_id, target_type, target_id
        )
        if child is not None and child.gaia_attached:
            await short_link_repository.update_live(parent.user_id, child.slug, follow)


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
    if not change.model_fields_set:
        raise AppError(message="Nothing to change", status_code=422, code="link_settings_empty")
    update = ShortLinkUpdate.model_validate(change.model_dump(exclude_unset=True))
    if "grantees" in change.model_fields_set:
        update.grantees = [str(email) for email in change.grantees or []]
        update.grantee_ids = await _grantee_ids(update.grantees)
    # The owner set it themselves: a brief it rides on no longer moves it.
    update.gaia_attached = False
    updated = await short_link_repository.update_live(user_id, slug, update)
    if updated is None:
        raise LinkTargetNotFoundError(message="Link not found")
    await _carry_access(updated, _access_of(updated))
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
    # The revoked doc, not the read before it: a refresh in between may have moved the file on.
    minted = await _insert(
        revoked.model_copy(
            update={
                "id": "",
                "created_at": _now(),
                "updated_at": None,
                "revoked": False,
                "revoked_at": None,
                "revoked_reason": None,
            }
        )
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
    stops attach_link from handing out a fresh one. Idempotent; False
    when the target had no live link to revoke.
    """
    live = await short_link_repository.get_live_for_target(user_id, target_type, target_id)
    if live is None:
        return False
    revoked = await short_link_repository.revoke(user_id, live.slug, RevokeReason.OWNER)
    if revoked is None:
        return False
    await _carry_access(live, _OWNER_ONLY)
    await _release_snapshot(user_id, live.snapshot)
    log.set(short_link={"slug_hash": hash_short_link_slug(live.slug)})
    capture(
        UserId(user_id),
        ShortLinkRevoked(target_type=target_type.value, reason=RevokeReason.OWNER.value),
    )
    return True


async def revoke_deleted_targets(
    user_id: str, target_type: ShortLinkTargetType, target_ids: list[str]
) -> int:
    """Kill every live link to targets their owner deleted, and delete the snapshots they pinned.

    The one place a deleted source takes its links along: a snapshot outlives
    its file by design, so only this revocation stops it serving.
    """
    revoked = 0
    for link in await short_link_repository.live_for_targets(user_id, target_type, target_ids):
        if await short_link_repository.revoke(user_id, link.slug, RevokeReason.TARGET_DELETED):
            await _release_snapshot(user_id, link.snapshot)
            revoked += 1
    return revoked


async def revoke_all_links_for_user(user_id: str) -> int:
    """Kill every live link a user owns and delete the snapshots they pinned; the count killed.

    For removing the user's account: GAIA attaches no new link to their targets afterwards. Idempotent.
    """
    revoked = 0
    for link in await short_link_repository.live_for_owner(user_id):
        if await short_link_repository.revoke(user_id, link.slug, RevokeReason.ACCOUNT_REMOVED):
            await _release_snapshot(user_id, link.snapshot)
            capture(
                UserId(user_id),
                ShortLinkRevoked(
                    target_type=link.target_type.value, reason=RevokeReason.ACCOUNT_REMOVED.value
                ),
            )
            revoked += 1
    log.set(short_link={"revoked_for_account": revoked})
    return revoked


async def revoke_conversation_links(user_id: str, conversation_id: str) -> None:
    """Kill the links to everything a conversation held, before the conversation's things are deleted."""
    for spec in REGISTRY.values():
        if spec.in_conversation is not None:
            target_ids = await spec.in_conversation(user_id, conversation_id)
            await revoke_deleted_targets(user_id, spec.type, target_ids)


def _served(link: ShortLink) -> ShortLink:
    """Return the link as it may serve its snapshot: no bytes once it is dead or wider than they allow.

    A dead link opens only for its owner, and its bytes may already be deleted.
    """
    snapshot = link.snapshot
    if snapshot is None or (dead_state(link, _now()) is None and servable(snapshot, link.access)):
        return link
    return link.model_copy(update={"snapshot": snapshot.model_copy(update={"content_id": None})})


def _viewer_key(viewer: LinkViewer) -> str:
    return viewer.user_id or hash_link_viewer(viewer.ip, viewer.user_agent)


def _day_dedupe(slug: str, viewer: LinkViewer, what: str) -> Dedupe:
    day = analytics_day_start(_now())
    return Dedupe(
        key=f"{hash_short_link_slug(slug)}:{_viewer_key(viewer)}:{what}:{day.date().isoformat()}",
        occurred_at=day,
    )


def _denied(viewer: LinkViewer, denial: LinkDenial) -> LinkDeniedError:
    signed_in_as = viewer.signed_in_as if denial is LinkDenial.FORBIDDEN else None
    return LinkDeniedError.for_denial(denial, signed_in_as=signed_in_as)


async def get_link(slug: str) -> ShortLink | None:
    return await short_link_repository.get_by_slug(slug)


@dataclass(frozen=True, slots=True)
class _GrantedView:
    link: ShortLink
    viewer_kind: LinkViewerKind
    view: PublicShortLinkView


async def _decide(link: ShortLink | None, viewer: LinkViewer) -> _GrantedView | LinkDenial:
    """Return what viewer sees of link, or why they may not open it."""
    if link is None:
        return LinkDenial.NOT_FOUND
    decision = evaluate(link, viewer, _now())
    if isinstance(decision, Denied):
        return decision.denial
    served = _served(link)
    view = await REGISTRY[link.target_type].project(served, decision.viewer_kind)
    if view is None:
        return LinkDenial.TARGET_DELETED
    return _GrantedView(served, decision.viewer_kind, view)


async def _granted_view(link: ShortLink | None, viewer: LinkViewer) -> _GrantedView:
    decided = await _decide(link, viewer)
    if isinstance(decided, LinkDenial):
        raise _denied(viewer, decided)
    return decided


async def resolve(link: ShortLink | None, viewer: LinkViewer) -> LinkEnvelope:
    """Open a link for viewer, or raise the denial they see. A read: counts neither an open nor a denial.

    The target is read under the owner on the link doc, only through its type's
    projection. A target the owner has since deleted is TARGET_DELETED.
    """
    return _envelope(await _granted_view(link, viewer))


def _envelope(granted: _GrantedView) -> LinkEnvelope:
    link, kind = granted.link, granted.viewer_kind
    return LinkEnvelope(
        access=link.access,
        target_type=link.target_type,
        view=granted.view,
        content=framed_content(link.snapshot, link.access),
        downloadable=servable(link.snapshot, link.access),
        is_owner=kind is LinkViewerKind.OWNER,
        owner_target_id=link.target_id if kind is LinkViewerKind.OWNER else None,
    )


def _count_denial(link: ShortLink, viewer: LinkViewer, denial: LinkDenial) -> None:
    reason = denial.value.removeprefix("link_")
    capture(
        UserId(link.user_id),
        ShortLinkDenied(target_type=link.target_type.value, reason=reason),
        _day_dedupe(link.slug, viewer, reason),
    )


def _count_open(granted: _GrantedView, viewer: LinkViewer) -> None:
    link = granted.link
    capture(
        UserId(link.user_id),
        ShortLinkOpened(
            target_type=link.target_type.value,
            access=link.access.value,
            viewer_signed_in=viewer.user_id is not None,
        ),
        _day_dedupe(link.slug, viewer, "opened"),
    )


async def record_open(link: ShortLink | None, viewer: LinkViewer) -> LinkEnvelope:
    """Open a link from the viewer's browser: the one read that counts an open or a denial for its owner.

    Only the browser carries the viewer's session, so only it tells a viewer
    apart; every other read (the page's server render, unfurls, tokens,
    downloads) counts nothing. A recipient's open and a denial count at most
    once a day per viewer; the owner and unfurl bots never count.
    """
    decided = await _decide(link, viewer)
    if isinstance(decided, LinkDenial):
        if link is not None:
            _count_denial(link, viewer, decided)
        raise _denied(viewer, decided)
    log.set(short_link={"viewer_kind": decided.viewer_kind.value})
    if decided.viewer_kind is LinkViewerKind.RECIPIENT:
        _count_open(decided, viewer)
    return _envelope(decided)


async def openable_link(
    link: ShortLink | None, viewer: LinkViewer, target_type: ShortLinkTargetType | None = None
) -> ShortLink:
    """Return the link when viewer may open it (and it points at target_type, when given); raise the denial otherwise."""
    granted = (await _granted_view(link, viewer)).link
    if target_type is not None and granted.target_type is not target_type:
        raise LinkDeniedError.for_denial(LinkDenial.NOT_FOUND)
    return granted
