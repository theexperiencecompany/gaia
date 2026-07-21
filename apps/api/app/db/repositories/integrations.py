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


integration_repository = IntegrationsRepository()
