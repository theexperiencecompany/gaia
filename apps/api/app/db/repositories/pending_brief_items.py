"""Repository for the pending_brief_items collection.

One document per finished brief-delivery workflow run, waiting for the user's
next brief. Written once; the brief reads the items
oldest first and clears the ones it carried once it has gone out.
"""

from app.db.repositories.base import UserScopedRepository
from app.models.brief_models import PendingBriefItemDocument, PendingBriefItemUpdate


class PendingBriefItemsRepository(
    UserScopedRepository[PendingBriefItemDocument, PendingBriefItemUpdate]
):
    collection_name = "pending_brief_items"
    document_model = PendingBriefItemDocument
    update_model = PendingBriefItemUpdate
    uses_object_id = True
    cache_policy = None

    async def consume(self, user_id: str, item_ids: list[str]) -> int:
        """Clear the items a delivered brief carried; return how many were cleared."""
        return await self._bulk_delete(item_ids, scope=user_id)


pending_brief_items_repository = PendingBriefItemsRepository()
