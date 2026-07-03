"""Short-link service — mint and resolve heygaia.link/<slug> handles.

Slugs live in a per-user namespace (unique only within one user's links) and
resolution is viewer-scoped, so the same URL points at a different artifact for
each signed-in viewer and a forwarded private link leaks nothing.
"""

import secrets

from pymongo.errors import DuplicateKeyError

from app.config.settings import settings
from app.db.mongodb.collections import short_links_collection
from app.models.short_link_models import ShortLink, ShortLinkTarget
from shared.py.wide_events import log

# Slug namespace: lowercase a–z, 3 chars → 26³ = 17,576 handles per user, far
# more than any user accrues, so collisions are rare and retries near-free.
SLUG_ALPHABET = "abcdefghijklmnopqrstuvwxyz"
SLUG_LENGTH = 3

# Cap on random-slug attempts before failing. With a near-empty per-user
# namespace this is never reached; exhausting it means the namespace is
# saturated (or the unique index is missing), which must fail loudly rather
# than silently reuse or truncate a slug.
MAX_SLUG_ATTEMPTS = 10


class ShortLinkExhaustedError(RuntimeError):
    """A unique slug could not be minted within MAX_SLUG_ATTEMPTS."""


def _random_slug() -> str:
    return "".join(secrets.choice(SLUG_ALPHABET) for _ in range(SLUG_LENGTH))


# In production the heygaia.link domain is aliased to the app and its middleware
# rewrites /<slug> → the /l resolver. That alias does not exist in local dev, so a
# minted heygaia.link URL is a dead link on localhost — point dev links straight
# at the local web app's own /l route so they are clickable. An explicit
# SHORTLINK_BASE_URL override (env) wins in either environment.
_PROD_SHORTLINK_DEFAULT = "https://heygaia.link"
_DEV_SHORTLINK_BASE = "http://localhost:3000/l"


def _shortlink_base() -> str:
    if settings.ENV == "development" and settings.SHORTLINK_BASE_URL == _PROD_SHORTLINK_DEFAULT:
        return _DEV_SHORTLINK_BASE
    return settings.SHORTLINK_BASE_URL


def _build_url(slug: str) -> str:
    return f"{_shortlink_base()}/{slug}"


async def get_or_create_short_link(
    user_id: str, target_type: ShortLinkTarget, target_id: str
) -> str:
    """Return the heygaia.link URL for ``(user, target)``, minting it once.

    Idempotent per target: repeated calls for the same artifact return the same
    slug, so re-running a briefing reuses one link instead of spawning a new one
    each run.
    """
    existing = await short_links_collection.find_one(
        {"user_id": user_id, "target_type": target_type, "target_id": target_id},
        {"slug": 1},
    )
    if existing:
        return _build_url(existing["slug"])

    for _ in range(MAX_SLUG_ATTEMPTS):
        link = ShortLink(
            slug=_random_slug(),
            user_id=user_id,
            target_type=target_type,
            target_id=target_id,
        )
        try:
            await short_links_collection.insert_one(link.model_dump())
        except DuplicateKeyError:
            # Slug already taken in this user's namespace — draw another.
            continue
        return _build_url(link.slug)

    log.error("short_link.slug_exhausted", user_id=user_id, target_id=target_id)
    raise ShortLinkExhaustedError(
        f"Could not mint a unique slug for user {user_id} after {MAX_SLUG_ATTEMPTS} attempts"
    )


async def resolve_short_link(user_id: str, slug: str) -> ShortLink | None:
    """Resolve ``slug`` within the viewer's namespace, or ``None`` if unknown."""
    doc = await short_links_collection.find_one({"user_id": user_id, "slug": slug})
    if doc is None:
        return None
    return ShortLink.model_validate(doc)
