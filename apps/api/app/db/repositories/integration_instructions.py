"""Repository for the ``integration_instructions`` collection.

User-scoped; one document per ``(user_id, integration_id)`` (unique index). The
incidental Mongo ``_id`` is preserved as ``id`` because the editor surfaces it.
"""

from app.db.repositories.base import UserScopedRepository
from app.models.integration_instructions_models import (
    InstructionsEditor,
    IntegrationInstructionsDocument,
    IntegrationInstructionsUpdate,
)


class IntegrationInstructionsRepository(
    UserScopedRepository[IntegrationInstructionsDocument, IntegrationInstructionsUpdate]
):
    collection_name = "integration_instructions"
    document_model = IntegrationInstructionsDocument
    update_model = IntegrationInstructionsUpdate
    uses_object_id = True
    cache_policy = None

    async def get_record(
        self, user_id: str, integration_id: str
    ) -> IntegrationInstructionsDocument | None:
        return await self._find_one({"user_id": user_id, "integration_id": integration_id})

    async def all_nonempty(self, user_id: str) -> list[IntegrationInstructionsDocument]:
        """Every instructions record for the user with non-empty content."""
        return await self._find({"user_id": user_id, "content": {"$ne": ""}})

    async def upsert(
        self,
        user_id: str,
        integration_id: str,
        *,
        content: str,
        updated_by: InstructionsEditor,
    ) -> IntegrationInstructionsDocument:
        """Create or replace one integration's instructions. ``updated_at`` is
        stamped by the base; on an insert the new document is returned."""
        doc = await self._apply_raw_update(
            {"user_id": user_id, "integration_id": integration_id},
            {"$set": {"content": content, "updated_by": updated_by.value}},
            scope=user_id,
            upsert=True,
        )
        if doc is None:
            # find_one_and_update(upsert=True, AFTER) always returns a document.
            raise RuntimeError("instructions upsert returned no document")
        return doc


integration_instructions_repository = IntegrationInstructionsRepository()
