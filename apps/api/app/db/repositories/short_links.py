"""Repository for the short_links collection.

Short links are capability URLs (heygaia.link/<slug>): the slug alone grants
read-only access to one artifact with no session, so resolution
(``get_by_slug``) is a deliberately global, unscoped read — the one operation
in this user-scoped repository with no ``user_id`` in its filter, exactly like
a cross-user maintenance scan on any other ``UserScopedRepository``. Minting,
refreshing and revoking a link are all owner-scoped.

No ``CachePolicy``: resolution is a public, low-volume read keyed by slug, not
by the entity id an id-keyed cache would serve.
"""

from datetime import datetime

from app.db.repositories.base import UserScopedRepository
from app.models.short_link_models import ShortLink, ShortLinkTarget, ShortLinkUpdate


class ShortLinksRepository(UserScopedRepository[ShortLink, ShortLinkUpdate]):
    collection_name = "short_links"
    document_model = ShortLink
    update_model = ShortLinkUpdate
    uses_object_id = True
    identity_field = "slug"
    cache_policy = None

    async def get_by_slug(self, slug: str) -> ShortLink | None:
        """Global lookup by slug — the public capability-URL resolver has no
        user in context."""
        return await self._find_one({"slug": slug})

    async def refresh_for_target(
        self, user_id: str, target_type: ShortLinkTarget, target_id: str, *, expires_at: datetime
    ) -> ShortLink | None:
        """Push a live (non-revoked) link's expiry forward on reuse — the
        idempotency path so a re-minted artifact reuses its slug. ``None`` when
        no link exists yet for this target (the caller mints a fresh one) or the
        existing one was revoked."""
        return await self._apply_raw_update(
            {
                "user_id": user_id,
                "target_type": target_type,
                "target_id": target_id,
                "revoked": {"$ne": True},
            },
            {"$set": {"expires_at": expires_at}},
            scope=user_id,
        )

    async def revoke(self, user_id: str, slug: str) -> bool:
        """Owner revocation: the URL goes dead immediately. False when the slug
        doesn't belong to this user."""
        updated = await self.update(slug, user_id=user_id, update=ShortLinkUpdate(revoked=True))
        return updated is not None


short_link_repository = ShortLinksRepository()
