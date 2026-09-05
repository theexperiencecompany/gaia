"""Short-link service — mint and resolve heygaia.link/<slug> capability URLs.

The slug IS the capability: high-entropy and globally unique, it grants
read-only access to one artifact's deliverable with no session — briefing links
must open from Telegram/WhatsApp, where the viewer is never signed in. Links
expire (each briefing re-mint pushes the expiry forward) and can be revoked, so
a forwarded link shares exactly what a share link shares, for as long as the
owner lets it.
"""

from datetime import UTC, datetime, timedelta
import secrets

from pymongo.errors import DuplicateKeyError

from app.config.settings import settings
from app.constants.todos import FACET_DELIVERABLE, facet_from_doc
from app.db.repositories.short_links import short_link_repository
from app.db.repositories.todos import todo_repository
from app.models.short_link_models import ShortLink, ShortLinkTarget
from app.models.todo_models import ExecutionStatus
from shared.py.wide_events import log

# Slug namespace: a–z + A–Z + digits, 11 chars → 62¹¹ ≈ 5.2×10¹⁹, about 65 bits.
# The slug IS the capability — anyone holding one reads that deliverable with no
# session — so it has to survive guessing, not just casual sharing. Sizing it is
# a function of how many links are live at once, and the briefing mints one per
# item with a 30-day TTL, so that count grows with users × items. At 8 chars over
# a 36-char alphabet (41 bits) a distributed guesser clears the resolver's
# per-IP rate limit by spreading across hosts and starts landing hits once the
# live set reaches the millions. 11 chars is ~16 million times harder and still
# short enough to read in a chat message — the length YouTube uses for the same
# reason. Lengthening is safe at any time: resolution is an exact-match lookup,
# so slugs already minted keep working.
SLUG_ALPHABET = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"
SLUG_LENGTH = 11

# Pre-capability links were per-user and 3 chars, so they cannot be resolved
# under the global-unique model and are dropped at index creation. This is
# deliberately NOT expressed as "shorter than SLUG_LENGTH": that would turn any
# future lengthening of the mint into a silent mass delete of live links.
LEGACY_SLUG_MAX_LENGTH = 3

# Links die on their own when the briefing stops re-minting them; every reuse
# pushes the expiry forward so a live artifact's link keeps working.
LINK_TTL_DAYS = 30

# Cap on random-slug attempts before failing. With a namespace this large the
# cap is never reached; exhausting it means the unique index is missing, which
# must fail loudly rather than silently reuse a slug.
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
    return str(settings.SHORTLINK_BASE_URL)


def _build_url(slug: str) -> str:
    return f"{_shortlink_base()}/{slug}"


async def get_or_create_short_link(
    user_id: str, target_type: ShortLinkTarget, target_id: str
) -> str:
    """Return the heygaia.link URL for ``(user, target)``, minting it once.

    Idempotent per target: repeated calls for the same artifact return the same
    slug (with a refreshed expiry), so re-running a briefing reuses one link
    instead of spawning a new one each run. A revoked link stays dead — the next
    mint draws a fresh slug.
    """
    now = datetime.now(UTC)
    expires_at = now + timedelta(days=LINK_TTL_DAYS)
    existing = await short_link_repository.refresh_for_target(
        user_id, target_type, target_id, expires_at=expires_at
    )
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
                    expires_at=expires_at,
                )
            )
        except DuplicateKeyError:
            # Slug already taken — draw another.
            continue
        return _build_url(link.slug)

    log.error("short_link.slug_exhausted", user_id=user_id, target_id=target_id)
    raise ShortLinkExhaustedError(
        f"Could not mint a unique slug for user {user_id} after {MAX_SLUG_ATTEMPTS} attempts"
    )


async def resolve_public_short_link(slug: str) -> ShortLink | None:
    """Resolve ``slug`` globally; ``None`` when unknown, revoked, or expired."""
    link = await short_link_repository.get_by_slug(slug)
    if link is None or link.revoked:
        return None
    expires = link.expires_at
    if expires is not None:
        # Mongo returns naive UTC datetimes; normalize before comparing.
        if expires.tzinfo is None:
            expires = expires.replace(tzinfo=UTC)
        if expires < datetime.now(UTC):
            return None
    return link


async def get_public_artifact(slug: str) -> dict | None:
    """Read-only artifact content behind a capability slug, or ``None``.

    The read is scoped by the OWNER stored on the link doc, never a viewer.
    Only the deliverable facet is exposed (notes/log are GAIA's working
    memory); a still-proposed todo may fall back to its legacy canvas, exactly
    like the briefing's artifact summary does.
    """
    link = await resolve_public_short_link(slug)
    if link is None or link.target_type != "todo_canvas":
        return None
    todo = await todo_repository.get(link.target_id, user_id=link.user_id)
    if not todo:
        return None
    allow_fallback = todo.execution_status == ExecutionStatus.PROPOSED
    content = facet_from_doc(
        todo.model_dump(), FACET_DELIVERABLE, allow_canvas_fallback=allow_fallback
    )
    return {
        "title": todo.title or "Artifact",
        "content": content or "",
        "todo_id": link.target_id,
        "target_type": link.target_type,
    }


async def revoke_short_link(user_id: str, slug: str) -> bool:
    """Owner revocation: the URL goes dead immediately. False if not the owner's."""
    return await short_link_repository.revoke(user_id, slug)
