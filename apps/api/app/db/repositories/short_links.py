"""Repository for the short_links collection.

Short links are capability URLs (heygaia.link/<slug>): the slug alone grants
read-only access to one artifact with no session, so resolution
(get_by_slug) is a deliberately global, unscoped read — the one operation
in this user-scoped repository with no user_id in its filter, exactly like
a cross-user maintenance scan on any other UserScopedRepository. Finding a
target's live link and revoking are owner-scoped: a target id is only unique
per owner (a session-artifact id is conversation_id/path), so a link one user
mints can never be handed to — or block — another.

No CachePolicy: resolution is a public, low-volume read keyed by slug, not
by the entity id an id-keyed cache would serve.
"""

from app.db.repositories.base import UserScopedRepository
from app.models.short_link_models import ShortLink, ShortLinkTargetType, ShortLinkUpdate

# Index names, shared with the index builder and the mint loop, which tells the
# two unique-key violations apart by the index Mongo names in the error.
SLUG_UNIQUE_INDEX = "slug_unique"
LIVE_TARGET_UNIQUE_INDEX = "target_live_unique"
TARGET_HISTORY_INDEX = "target_history"


class ShortLinksRepository(UserScopedRepository[ShortLink, ShortLinkUpdate]):
    collection_name = "short_links"
    document_model = ShortLink
    update_model = ShortLinkUpdate
    uses_object_id = True
    identity_field = "slug"
    cache_policy = None

    async def get_by_slug(self, slug: str) -> ShortLink | None:
        """Look a link up by slug alone.

        Global on purpose: the public capability-URL resolver has no user in context.
        """
        return await self._find_one({"slug": slug})

    async def get_live_for_target(
        self, user_id: str, target_type: ShortLinkTargetType, target_id: str
    ) -> ShortLink | None:
        """Return the owner's one live (non-revoked) link to a target.

        Served by the partial LIVE_TARGET_UNIQUE_INDEX, whose predicate the filter matches.
        """
        return await self._find_one(
            {
                "user_id": user_id,
                "target_type": target_type,
                "target_id": target_id,
                "revoked": False,
            }
        )

    async def get_latest_for_target(
        self, user_id: str, target_type: ShortLinkTargetType, target_id: str
    ) -> ShortLink | None:
        """Return the owner's newest link to a target, live or revoked.

        A live link is always the newest — a link is only minted while none is
        live — so the newest one alone tells whether sharing is on (live), turned
        off by the owner (revoked) or never started (None). Served by
        TARGET_HISTORY_INDEX.
        """
        return await self._find_one(
            {"user_id": user_id, "target_type": target_type, "target_id": target_id},
            sort=[("created_at", -1)],
        )

    async def revoke(self, user_id: str, slug: str) -> bool:
        """Revoke a link its owner holds; the URL goes dead immediately.

        False when the slug does not belong to this user.
        """
        updated = await self.update(slug, user_id=user_id, update=ShortLinkUpdate(revoked=True))
        return updated is not None


short_link_repository = ShortLinksRepository()
