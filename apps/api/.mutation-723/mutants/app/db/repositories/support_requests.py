"""Repository for the ``support_requests`` collection — user-scoped tickets.

Identity is a caller-minted UUID stored as the string ``_id`` (not an ObjectId).
Reads are always scoped to the owning user; the listing supports an optional
status filter with newest-first pagination.
"""

from app.db.repositories.base import UserScopedRepository
from app.models.support_models import (
    SupportRequestDocument,
    SupportRequestStatus,
    SupportRequestUpdate,
)


class SupportRequestsRepository(UserScopedRepository[SupportRequestDocument, SupportRequestUpdate]):
    collection_name = "support_requests"
    document_model = SupportRequestDocument
    update_model = SupportRequestUpdate
    uses_object_id = False
    cache_policy = None

    def _user_filter(self, user_id: str, status: SupportRequestStatus | None) -> dict[str, object]:
        filter_: dict[str, object] = {"user_id": user_id}
        if status is not None:
            filter_["status"] = status.value
        return filter_

    async def page_for_user(
        self,
        user_id: str,
        *,
        status: SupportRequestStatus | None = None,
        skip: int,
        limit: int,
    ) -> list[SupportRequestDocument]:
        """A user's requests, newest first, optionally filtered by status."""
        return await self._find(
            self._user_filter(user_id, status),
            sort=[("created_at", -1)],
            skip=skip,
            limit=limit,
        )

    async def count_for_user_status(
        self, user_id: str, *, status: SupportRequestStatus | None = None
    ) -> int:
        return await self._count(self._user_filter(user_id, status))


support_request_repository = SupportRequestsRepository()
