"""Repository for the ``integrations`` collection.

Global (non-user-scoped) catalog of custom + community MCP integrations. Identity
is the business key ``integration_id`` (unique index); the Mongo ``_id`` (ObjectId)
is incidental and dropped on read. Timestamps are not auto-stamped — the collection
leaves ``updated_at`` unset on insert and only ``update_custom`` writes it, so the
repository mirrors that on-disk reality rather than stamping every write.
"""

from datetime import UTC, datetime
import re

from app.constants.cache import REPO_GLOBAL_SCOPE
from app.db.repositories.base import MongoRepository
from app.helpers.integration_helpers import generate_integration_slug
from app.models.integration_models import (
    Integration,
    IntegrationTool,
    IntegrationToolsRecord,
    IntegrationToolsSlice,
    IntegrationUpdate,
    IntegrationWithCreator,
)
from app.models.oauth_models import IntegrationContent

# Community browse sort options → Mongo sort spec. "popular" is the default.
_COMMUNITY_SORT: dict[str, list[tuple[str, int]]] = {
    "popular": [("clone_count", -1), ("published_at", -1)],
    "recent": [("published_at", -1)],
    "name": [("name", 1)],
}


class IntegrationsRepository(MongoRepository[Integration, IntegrationUpdate]):
    collection_name = "integrations"
    document_model = Integration
    update_model = IntegrationUpdate
    uses_object_id = False
    identity_field = "integration_id"
    auto_stamp_timestamps = False
    cache_policy = None

    async def find_by_id_prefix_or_name(self, search: str) -> Integration | None:
        """Resolve a partial id or exact name to an integration.

        Matches ``integration_id`` by case-insensitive prefix, or ``name`` by
        case-insensitive exact match — the disambiguation used by handoff/agent
        metadata lookups where the caller may hold either a short id or a name.
        """
        escaped = re.escape(search)
        return await self._find_one(
            {
                "$or": [
                    {"integration_id": {"$regex": f"^{escaped}", "$options": "i"}},
                    {"name": {"$regex": f"^{escaped}$", "$options": "i"}},
                ]
            }
        )

    async def find_by_id_prefix(self, prefix: str) -> Integration | None:
        """Resolve a partial ``integration_id`` (case-insensitive prefix) to an integration."""
        escaped = re.escape(prefix)
        return await self._find_one({"integration_id": {"$regex": f"^{escaped}", "$options": "i"}})

    async def find_custom_by_ids(self, integration_ids: list[str]) -> list[Integration]:
        """Custom-source integrations among the given ids (a user's added customs)."""
        return await self._find({"integration_id": {"$in": integration_ids}, "source": "custom"})

    async def get_custom(self, integration_id: str) -> Integration | None:
        """A custom-source integration by id (the delete-ownership check reads this)."""
        return await self._find_one({"integration_id": integration_id, "source": "custom"})

    async def get_custom_for_user(self, integration_id: str, user_id: str) -> Integration | None:
        """A custom integration owned by ``user_id`` — the creator-only edit guard."""
        return await self._find_one(
            {"integration_id": integration_id, "source": "custom", "created_by": user_id}
        )

    async def delete_custom(self, integration_id: str, created_by: str) -> bool:
        """Delete a custom integration only if ``created_by`` owns it (creator-only)."""
        return await self._remove(
            integration_id, REPO_GLOBAL_SCOPE, {"source": "custom", "created_by": created_by}
        )

    async def list_public_custom(self, category: str | None = None) -> list[Integration]:
        """Public custom integrations for the marketplace, newest first, optionally
        filtered by category. Lenient: a single corrupt legacy doc is skipped, not
        fatal to the whole listing (mirrors the old per-doc try/except)."""
        filter_: dict[str, object] = {"source": "custom", "is_public": True}
        if category and category != "all":
            filter_["category"] = category
        return await self._find_lenient(filter_, sort=[("created_at", -1)])

    async def search_public(
        self, *, words: list[str], query: str, exclude_ids: list[str], limit: int
    ) -> list[Integration]:
        """Marketplace text search over public integrations.

        Matches each word against name/description/category and the full query
        against name/description (case-insensitive regex), excluding ids the user
        already has. The regex construction stays inside the repository so Mongo
        filter shapes never leak across the boundary.
        """
        conditions: list[dict[str, object]] = []
        for word in words:
            escaped_word = re.escape(word)
            conditions.extend(
                [
                    {"name": {"$regex": escaped_word, "$options": "i"}},
                    {"description": {"$regex": escaped_word, "$options": "i"}},
                    {"category": {"$regex": escaped_word, "$options": "i"}},
                ]
            )
        escaped_query = re.escape(query)
        conditions.extend(
            [
                {"name": {"$regex": escaped_query, "$options": "i"}},
                {"description": {"$regex": escaped_query, "$options": "i"}},
            ]
        )
        return await self._find(
            {
                "is_public": True,
                "integration_id": {"$nin": exclude_ids},
                "$or": conditions,
            },
            limit=limit,
        )

    async def find_public_by_ids(self, integration_ids: list[str]) -> list[Integration]:
        """Public integrations among the given ids (semantic-search hydration)."""
        return await self._find({"integration_id": {"$in": integration_ids}, "is_public": True})

    async def find_by_ids(self, integration_ids: list[str]) -> list[Integration]:
        """Integrations for the given ids, any source/visibility (workspace hydration).

        Lenient: a single corrupt legacy document is skipped and logged rather than
        blanking a user's whole integration list."""
        return await self._find_lenient({"integration_id": {"$in": integration_ids}})

    async def heal_top_level_auth(
        self, integration_id: str, requires_auth: bool, auth_type: str
    ) -> None:
        """Sync the legacy top-level auth mirror to match the authoritative mcp_config.

        Writes the ad-hoc ``requires_auth`` / ``auth_type`` document-root fields that
        predate mcp_config; kept as a raw ``$set`` because they are not part of the
        typed update surface."""
        await self._apply_raw_update_unfetched(
            {"integration_id": integration_id},
            {"$set": {"requires_auth": requires_auth, "auth_type": auth_type}},
            scope=REPO_GLOBAL_SCOPE,
            doc_id=integration_id,
        )

    # ---- creator-lookup aggregations (marketplace detail + community) ----

    @staticmethod
    def _creator_lookup_stages() -> list[dict[str, object]]:
        """Join each integration's creator (name/picture) from the users collection.

        The single canonical creator-lookup, folded in from the two divergent copies
        that used to live in integration_helpers and integration_service. ``created_by``
        holds a user's ObjectId-as-string; ``$convert`` tolerates a missing/invalid
        value (``creator`` becomes ``None``) rather than failing the pipeline.
        """
        return [
            {
                "$lookup": {
                    "from": "users",
                    "let": {
                        "creator_id": {
                            "$convert": {
                                "input": "$created_by",
                                "to": "objectId",
                                "onError": None,
                                "onNull": None,
                            }
                        }
                    },
                    "pipeline": [
                        {"$match": {"$expr": {"$eq": ["$_id", "$$creator_id"]}}},
                        {"$project": {"name": 1, "picture": 1}},
                    ],
                    "as": "creator_info",
                }
            },
            {
                "$addFields": {
                    "creator": {
                        "$cond": {
                            "if": {"$gt": [{"$size": "$creator_info"}, 0]},
                            "then": {"$arrayElemAt": ["$creator_info", 0]},
                            "else": None,
                        }
                    }
                }
            },
            {"$project": {"creator_info": 0}},
        ]

    async def get_public_by_slug(self, slug: str) -> IntegrationWithCreator | None:
        """A published integration by exact slug, with creator info joined."""
        results = await self._aggregate(
            [{"$match": {"slug": slug, "is_public": True}}, *self._creator_lookup_stages()],
            IntegrationWithCreator,
        )
        return results[0] if results else None

    async def get_public_by_id_prefix(self, short_id: str) -> IntegrationWithCreator | None:
        """A published integration by ``integration_id`` prefix (legacy hash slugs),
        with creator info joined."""
        escaped = re.escape(short_id)
        results = await self._aggregate(
            [
                {
                    "$match": {
                        "integration_id": {"$regex": f"^{escaped}", "$options": "i"},
                        "is_public": True,
                    }
                },
                *self._creator_lookup_stages(),
            ],
            IntegrationWithCreator,
        )
        return results[0] if results else None

    async def community_by_ids(self, integration_ids: list[str]) -> list[IntegrationWithCreator]:
        """Published integrations among the given ids, creator joined (semantic-search hits).
        Caller reorders to match the search ranking."""
        return await self._aggregate(
            [
                {"$match": {"integration_id": {"$in": integration_ids}, "is_public": True}},
                *self._creator_lookup_stages(),
            ],
            IntegrationWithCreator,
        )

    @staticmethod
    def _community_search_filter(query: str, category: str) -> dict[str, object]:
        search_regex = {"$regex": re.escape(query), "$options": "i"}
        filter_: dict[str, object] = {
            "is_public": True,
            "$or": [
                {"name": search_regex},
                {"description": search_regex},
                {"tools.name": search_regex},
                {"tools.description": search_regex},
            ],
        }
        if category and category != "all":
            filter_["category"] = category
        return filter_

    async def count_community_search(self, query: str, category: str) -> int:
        return await self._count(self._community_search_filter(query, category))

    async def community_search(
        self, query: str, category: str, *, offset: int, limit: int
    ) -> list[IntegrationWithCreator]:
        """Regex fallback search over published integrations, popular first."""
        return await self._aggregate(
            [
                {"$match": self._community_search_filter(query, category)},
                {"$sort": {"clone_count": -1, "published_at": -1}},
                {"$skip": offset},
                {"$limit": limit},
                *self._creator_lookup_stages(),
            ],
            IntegrationWithCreator,
        )

    @staticmethod
    def _community_browse_filter(category: str) -> dict[str, object]:
        filter_: dict[str, object] = {"is_public": True, "published_at": {"$ne": None}}
        if category and category != "all":
            filter_["category"] = category
        return filter_

    async def count_community_browse(self, category: str) -> int:
        return await self._count(self._community_browse_filter(category))

    async def community_browse(
        self, sort: str, category: str, *, offset: int, limit: int
    ) -> list[IntegrationWithCreator]:
        """Browse published integrations by the given sort (popular/recent/name)."""
        sort_spec = _COMMUNITY_SORT.get(sort, _COMMUNITY_SORT["popular"])
        return await self._aggregate(
            [
                {"$match": self._community_browse_filter(category)},
                {"$sort": dict(sort_spec)},
                {"$skip": offset},
                {"$limit": limit},
                *self._creator_lookup_stages(),
            ],
            IntegrationWithCreator,
        )

    # ---- publish / connection-status writes ----

    async def get_public(self, integration_id: str) -> Integration | None:
        """A published integration by id (the public add-to-workspace read)."""
        return await self._find_one({"integration_id": integration_id, "is_public": True})

    async def get_by_creator(self, integration_id: str, created_by: str) -> Integration | None:
        """An integration by id constrained to its creator (publish conflict check)."""
        return await self._find_one({"integration_id": integration_id, "created_by": created_by})

    async def increment_clone_count(self, integration_id: str) -> None:
        """Bump the clone counter when a user adds a public integration."""
        await self._increment(integration_id, "clone_count", 1, scope=REPO_GLOBAL_SCOPE)

    async def set_mcp_auth(self, integration_id: str, requires_auth: bool, auth_type: str) -> bool:
        """Sync the stored mcp_config auth flags after server probe discovery.

        Returns whether a matching integration was updated.
        """
        matched = await self._apply_raw_update_unfetched(
            {"integration_id": integration_id},
            {
                "$set": {
                    "mcp_config.requires_auth": requires_auth,
                    "mcp_config.auth_type": auth_type,
                }
            },
            scope=REPO_GLOBAL_SCOPE,
            doc_id=integration_id,
        )
        return matched > 0

    async def clear_tools(self, integration_id: str) -> None:
        """Drop the stored tool metadata (on disconnect) so ghost tools don't linger."""
        await self._apply_raw_update_unfetched(
            {"integration_id": integration_id},
            {"$unset": {"tools": ""}},
            scope=REPO_GLOBAL_SCOPE,
            doc_id=integration_id,
        )

    async def ensure_unique_slug(self, name: str, category: str, integration_id: str) -> str:
        """A marketplace slug unique across published integrations.

        Appends -2, -3, … to the canonical slug until a free one is found (the
        slug-uniqueness probe, folded in from generate_unique_integration_slug).
        """
        base_slug = generate_integration_slug(name, category, integration_id)
        if await self._slug_free(base_slug, integration_id):
            return base_slug
        suffix = 2
        while suffix <= 100:
            candidate = f"{base_slug}-{suffix}"
            if await self._slug_free(candidate, integration_id):
                return candidate
            suffix += 1
        return f"{base_slug}-{integration_id[:6]}"

    async def _slug_free(self, slug: str, integration_id: str) -> bool:
        taken = await self._find_one({"slug": slug, "integration_id": {"$ne": integration_id}})
        return taken is None

    async def publish(
        self,
        integration_id: str,
        *,
        created_by: str,
        category: str,
        slug: str,
        content: IntegrationContent | None,
        clone_count: int,
    ) -> bool:
        """Publish a creator's unpublished custom integration. Returns False when the
        guarded filter matches nothing (already public, or not the creator's custom)."""
        matched = await self._apply_raw_update_unfetched(
            {
                "integration_id": integration_id,
                "created_by": created_by,
                "source": "custom",
                "is_public": {"$ne": True},
            },
            {
                "$set": {
                    "is_public": True,
                    "published_at": datetime.now(UTC),
                    "category": category,
                    "clone_count": clone_count,
                    "slug": slug,
                    # Explicitly null on regeneration failure so a republish never
                    # serves stale copy from a previous publish.
                    "content": content.model_dump() if content is not None else None,
                }
            },
            scope=REPO_GLOBAL_SCOPE,
            doc_id=integration_id,
        )
        return matched > 0

    async def unpublish(self, integration_id: str) -> bool:
        """Take a published integration private. Returns whether it was updated."""
        matched = await self._apply_raw_update_unfetched(
            {"integration_id": integration_id},
            {"$set": {"is_public": False}, "$unset": {"published_at": ""}},
            scope=REPO_GLOBAL_SCOPE,
            doc_id=integration_id,
        )
        return matched > 0

    # ---- global MCP tool metadata (frontend display) ----

    async def store_tools(self, integration_id: str, tools: list[IntegrationTool]) -> None:
        """Upsert the stored tool metadata for an integration (creating a tools-only
        stub document if the integration doc does not exist yet).

        Uses the unfetched upsert: a tools-only stub is not a full ``Integration``,
        so it must never be read back through model validation.
        """
        await self._apply_raw_update_unfetched(
            {"integration_id": integration_id},
            {
                "$set": {
                    "tools": [t.model_dump() for t in tools],
                    "integration_id": integration_id,
                }
            },
            scope=REPO_GLOBAL_SCOPE,
            doc_id=integration_id,
            upsert=True,
        )

    async def store_tools_batch(self, items: list[tuple[str, list[IntegrationTool]]]) -> None:
        """Upsert tool metadata for several integrations (catalog metadata population)."""
        for integration_id, tools in items:
            await self.store_tools(integration_id, tools)

    async def get_tools(self, integration_id: str) -> list[IntegrationTool]:
        """The stored tool metadata for an integration (empty when none stored)."""
        slice_ = await self._find_one_projected(
            {"integration_id": integration_id}, {"tools": 1}, IntegrationToolsSlice
        )
        return slice_.tools if slice_ is not None else []

    async def all_with_tools(self) -> list[IntegrationToolsRecord]:
        """Every integration that has stored tools, projected for the global roll-up."""
        return await self._aggregate(
            [
                {"$match": {"tools": {"$exists": True, "$ne": []}}},
                {"$project": {"integration_id": 1, "tools": 1, "name": 1, "icon_url": 1}},
            ],
            IntegrationToolsRecord,
        )


integration_repository = IntegrationsRepository()
