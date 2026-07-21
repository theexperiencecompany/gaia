"""Repository for the ``integrations`` collection.

Global (non-user-scoped) catalog of custom + community MCP integrations. Identity
is the business key ``integration_id`` (unique index); the Mongo ``_id`` (ObjectId)
is incidental and dropped on read. Timestamps are not auto-stamped — the collection
leaves ``updated_at`` unset on insert and only ``update_custom`` writes it, so the
repository mirrors that on-disk reality rather than stamping every write.
"""

import re

from app.db.repositories.base import MongoRepository
from app.models.integration_models import Integration, IntegrationUpdate


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


integration_repository = IntegrationsRepository()
