"""Repository for the pending_brief_items collection.

One document per finished brief-delivery workflow run, waiting for the user's
next brief. Insert-only here; the brief reads and clears the items it carries.
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


pending_brief_items_repository = PendingBriefItemsRepository()
