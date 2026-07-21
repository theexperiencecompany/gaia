"""Repository for the ``integrations`` collection.

Global (non-user-scoped) catalog of custom + community MCP integrations. Identity
is the business key ``integration_id`` (unique index); the Mongo ``_id`` (ObjectId)
is incidental and dropped on read. Timestamps are not auto-stamped — the collection
leaves ``updated_at`` unset on insert and only ``update_custom`` writes it, so the
repository mirrors that on-disk reality rather than stamping every write.
"""

import re

from app.db.repositories.base import MongoRepository
from app.models.integration_models import (
    Integration,
    IntegrationUpdate,
    IntegrationWithCreator,
)

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


integration_repository = IntegrationsRepository()
