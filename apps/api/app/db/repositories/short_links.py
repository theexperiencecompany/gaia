"""Repository for the short_links collection.

Short links are capability URLs (heygaia.link/<slug>): the slug alone grants
read-only access to one artifact with no session, so resolution
(get_by_slug) is a deliberately global, unscoped read — the one operation
in this user-scoped repository with no user_id in its filter, exactly like
a cross-user maintenance scan on any other UserScopedRepository. Finding a
target's live link and revoking are owner-scoped: a target is only unique per
owner (a workspace file is a conversation id and a path), so a link one user
mints can never be handed to — or block — another.

No CachePolicy: resolution is a public, low-volume read keyed by slug, not
by the entity id an id-keyed cache would serve.
"""

from collections.abc import Sequence
from datetime import UTC, datetime

from pydantic import BaseModel

from app.db.repositories.base import UserScopedRepository
from app.models.short_link_models import (
    LinkTarget,
    RevokeReason,
    ShortLink,
    ShortLinkTargetType,
    ShortLinkUpdate,
    WorkspaceFileTarget,
)

# Index names, shared with the index builder and the mint loop, which tells the
# two unique-key violations apart by the index Mongo names in the error.
SLUG_UNIQUE_INDEX = "slug_unique"
LIVE_TARGET_UNIQUE_INDEX = "target_live_unique"
TARGET_HISTORY_INDEX = "target_history"
CONTENT_ID_INDEX = "snapshot_content_id"
WORKSPACE_FILE_CONVERSATION_INDEX = "workspace_file_conversation"
# Every field of every target reference; a reference leaves the others out, and they index as null.
TARGET_INDEX_KEY = [
    ("target.type", 1),
    ("target.id", 1),
    ("target.conversation_id", 1),
    ("target.path", 1),
]
WORKSPACE_FILE_LIVE_FILTER = {
    "revoked": False,
    "target.type": ShortLinkTargetType.WORKSPACE_FILE.value,
}


def _target_filter(target: LinkTarget) -> dict[str, object]:
    """Match the links to one target: an equality on each of its reference's fields."""
    return {f"target.{field}": value for field, value in target.model_dump().items()}


class _StoredBytes(BaseModel):
    total: int


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

    async def get_live_for_target(self, user_id: str, target: LinkTarget) -> ShortLink | None:
        """Return the owner's one live (non-revoked) link to a target.

        Served by the partial LIVE_TARGET_UNIQUE_INDEX, whose predicate the filter matches.
        """
        return await self._find_one(
            {"user_id": user_id, **_target_filter(target), "revoked": False}
        )

    async def live_for_targets(
        self, user_id: str, targets: Sequence[LinkTarget]
    ) -> list[ShortLink]:
        """Return the owner's live links to any of targets."""
        if not targets:
            return []
        return await self._find(
            {
                "user_id": user_id,
                "$or": [_target_filter(target) for target in targets],
                "revoked": False,
            }
        )

    async def live_workspace_files_in(
        self, user_id: str, conversation_id: str
    ) -> list[WorkspaceFileTarget]:
        """Return the owner's live-linked files in one conversation's workspace.

        Served by WORKSPACE_FILE_CONVERSATION_INDEX, whose predicate the filter matches.
        """
        return await self._aggregate(
            [
                {
                    "$match": {
                        "user_id": user_id,
                        "target.conversation_id": conversation_id,
                        **WORKSPACE_FILE_LIVE_FILTER,
                    }
                },
                {"$replaceRoot": {"newRoot": "$target"}},
            ],
            WorkspaceFileTarget,
        )

    async def live_for_owner(self, user_id: str) -> list[ShortLink]:
        """Return every live link the owner holds."""
        return await self._find({"user_id": user_id, "revoked": False})

    async def get_latest_for_target(self, user_id: str, target: LinkTarget) -> ShortLink | None:
        """Return the owner's newest link to a target, live or revoked.

        A live link is always the newest — a link is only minted while none is
        live — so the newest one alone tells whether sharing is on (live), turned
        off by the owner (revoked) or never started (None). Served by
        TARGET_HISTORY_INDEX.
        """
        return await self._find_one(
            {"user_id": user_id, **_target_filter(target)}, sort=[("created_at", -1)]
        )

    async def revoke(self, user_id: str, slug: str, reason: RevokeReason) -> ShortLink | None:
        """Revoke a live link its owner holds; the URL goes dead immediately.

        None when the slug does not belong to this user or is already dead.
        """
        return await self._apply_update(
            slug,
            user_id,
            {"user_id": user_id, "revoked": False},
            ShortLinkUpdate(revoked=True, revoked_at=datetime.now(UTC), revoked_reason=reason),
        )

    async def update_live(
        self, user_id: str, slug: str, update: ShortLinkUpdate
    ) -> ShortLink | None:
        """Set fields on a live link its owner holds; None when it is not theirs or already dead.

        A revoked link's fields are its record: a rotation already carried them to the new link.
        """
        return await self._apply_update(
            slug, user_id, {"user_id": user_id, "revoked": False}, update
        )

    async def get_live_by_content_id(self, content_id: str) -> ShortLink | None:
        """Return the live link serving a snapshot; global like get_by_slug, for the content origin."""
        return await self._find_one({"snapshot.content_id": content_id, "revoked": False})

    async def live_pins_content(self, content_id: str) -> bool:
        """Whether any live link still pins content_id (a rotation hands it to the new link)."""
        return await self._count({"snapshot.content_id": content_id, "revoked": False}) > 0

    async def count_takedowns(self, user_id: str) -> int:
        return await self._count({"user_id": user_id, "revoked_reason": RevokeReason.TAKEDOWN})

    async def stored_snapshot_bytes(self, user_id: str) -> int:
        """Bytes of the snapshots the owner's live links pin."""
        rows = await self._aggregate(
            [
                {
                    "$match": {
                        "user_id": user_id,
                        "revoked": False,
                        "snapshot.content_id": {"$type": "string"},
                    }
                },
                {"$group": {"_id": None, "total": {"$sum": "$snapshot.size_bytes"}}},
            ],
            _StoredBytes,
        )
        return rows[0].total if rows else 0


short_link_repository = ShortLinksRepository()
