"""Short-link service — mint and resolve heygaia.link/<slug> capability URLs.

The slug IS the capability: high-entropy and globally unique, it grants
read-only access to one artifact's public view with no session — links open
from Telegram, WhatsApp and email, where the viewer is never signed in. Anyone
holding a link can open it until the owner revokes it. What it serves is always
the target type's safe projection (app/services/short_link_projections.py),
never the stored document.

Two ways a link comes to exist, with one rule between them: sharing is the
owner's call. share_short_link is the owner asking for a link (the copy-link
control) and always yields one. optional_short_link is GAIA attaching a link
to something it hands over (a file it wrote, a finished todo, a workflow result,
a brief); it never re-shares a target the owner turned sharing off for, and a
failure to mint costs only the link, never the message carrying it.
"""

from pathlib import Path
import secrets

from pymongo.errors import DuplicateKeyError, PyMongoError

from app.config.settings import settings
from app.db.repositories.short_links import (
    LIVE_TARGET_UNIQUE_INDEX,
    SLUG_UNIQUE_INDEX,
    short_link_repository,
)
from app.models.short_link_models import PublicShortLinkView, ShortLink, ShortLinkTargetType
from app.services.analytics_service import capture
from app.services.short_link_projections import project_target, session_artifact_file
from app.utils.log_identifiers import hash_short_link_slug
from shared.py.analytics import UserId
from shared.py.analytics.catalog.short_links import (
    ShortLinkCreated,
    ShortLinkOpened,
    ShortLinkRevoked,
)
from shared.py.wide_events import log

# The slug is the capability and links do not expire, so it must survive guessing:
# 11 base62 chars ≈ 65 bits (8 base36 chars, 41 bits, falls to a distributed guesser).
# Lengthening later is safe: resolution is an exact match, minted slugs keep working.
SLUG_ALPHABET = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"
SLUG_LENGTH = 11

# Cap on random-slug attempts before failing. With a namespace this large the
# cap is never reached; exhausting it means the unique index is missing, which
# must fail loudly rather than silently reuse a slug.
MAX_SLUG_ATTEMPTS = 10


class ShortLinkExhaustedError(RuntimeError):
    """A unique slug could not be minted within MAX_SLUG_ATTEMPTS."""


def _random_slug() -> str:
    return "".join(secrets.choice(SLUG_ALPHABET) for _ in range(SLUG_LENGTH))


def _build_url(slug: str) -> str:
    return f"{settings.SHORTLINK_BASE_URL}/{slug}"


async def share_short_link(user_id: str, target_type: ShortLinkTargetType, target_id: str) -> str:
    """Return the target's live link, minting one when none is live.

    Called directly it is the owner sharing (callers prove ownership first), the
    only path that re-enables a target they stopped sharing. Idempotent: racing
    callers all get the one live link, so a revoke never leaves a second alive.
    """
    existing = await short_link_repository.get_live_for_target(user_id, target_type, target_id)
    if existing:
        return _build_url(existing.slug)

    for _ in range(MAX_SLUG_ATTEMPTS):
        try:
            link = await short_link_repository.create(
                ShortLink(
                    slug=_random_slug(),
                    user_id=user_id,
                    target_type=target_type,
                    target_id=target_id,
                )
            )
        except DuplicateKeyError as e:
            violated = str(e)
            if f"index: {SLUG_UNIQUE_INDEX}" in violated:
                # Slug already taken — draw another.
                continue
            if f"index: {LIVE_TARGET_UNIQUE_INDEX}" not in violated:
                raise
            # Lost a concurrent mint for this target. The winner's slug is the
            # one live link, and minting a third would leave a link alive after
            # the user revokes the one they were shown — hand back the winner.
            winner = await short_link_repository.get_live_for_target(
                user_id, target_type, target_id
            )
            if winner is None:
                # The winner was revoked between the collision and this read;
                # a fresh slug is now the correct outcome.
                continue
            return _build_url(winner.slug)
        capture(UserId(user_id), ShortLinkCreated(target_type=target_type.value))
        return _build_url(link.slug)

    log.error(
        "short_link.slug_exhausted",
        user_id=user_id,
        target_type=target_type.value,
        target_id=target_id,
    )
    raise ShortLinkExhaustedError(
        f"Could not mint a unique slug for user {user_id} after {MAX_SLUG_ATTEMPTS} attempts"
    )


async def optional_short_link(
    user_id: str, target_type: ShortLinkTargetType, target_id: str
) -> str | None:
    """Return the link GAIA attaches to something it hands the owner, or None.

    None when the owner stopped sharing the target (their newest link is revoked;
    that sticks until they share it themselves) or when minting fails — a Mongo
    error or exhausted namespace is an error event and costs only the link.
    """
    try:
        latest = await short_link_repository.get_latest_for_target(user_id, target_type, target_id)
        if latest is not None and latest.revoked:
            log.info(
                "short_link.sharing_disabled",
                user_id=user_id,
                target_type=target_type.value,
            )
            return None
        if latest is not None:
            return _build_url(latest.slug)
        return await share_short_link(user_id, target_type, target_id)
    except (PyMongoError, ShortLinkExhaustedError) as exc:
        log.error(
            "short_link.mint_failed",
            user_id=user_id,
            target_type=target_type.value,
            error_type=type(exc).__name__,
            error=str(exc),
        )
        return None


async def _resolve_live_link(slug: str) -> ShortLink | None:
    """Return the link behind slug; None when unknown or revoked."""
    link = await short_link_repository.get_by_slug(slug)
    if link is None or link.revoked:
        return None
    return link


async def get_public_view(slug: str) -> PublicShortLinkView | None:
    """Return the public view behind a capability slug, or None.

    The target is read under the OWNER stored on the link doc, never a viewer,
    and only through its type's projection. A target the owner has since
    deleted resolves to None exactly like an unknown slug.
    """
    link = await _resolve_live_link(slug)
    if link is None:
        return None
    view = await project_target(link.target_type, link.user_id, link.target_id)
    if view is not None:
        capture(UserId(link.user_id), ShortLinkOpened(target_type=link.target_type.value))
    return view


async def get_public_file(slug: str) -> Path | None:
    """Return the raw file behind a session-artifact slug.

    None for any other target type, an unknown or revoked slug, or a file
    that no longer exists.
    """
    link = await _resolve_live_link(slug)
    if link is None or link.target_type is not ShortLinkTargetType.SESSION_ARTIFACT:
        return None
    return await session_artifact_file(link.user_id, link.target_id)


async def stop_sharing(user_id: str, target_type: ShortLinkTargetType, target_id: str) -> bool:
    """Turn sharing off for a target on its owner's behalf: its live link dies at once.

    The revoked link stays on record as the target's newest, which is what
    stops optional_short_link from handing out a fresh one. Idempotent; False
    when the target had no live link to revoke.
    """
    live = await short_link_repository.get_live_for_target(user_id, target_type, target_id)
    if live is None:
        return False
    revoked = await short_link_repository.revoke(user_id, live.slug)
    if revoked:
        log.set(short_link={"slug_hash": hash_short_link_slug(live.slug)})
        capture(UserId(user_id), ShortLinkRevoked())
    return revoked
