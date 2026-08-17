"""Repository for the ``pending_platform_registrations`` collection.

Global, one record per (user, platform): the handle a user registered upstream
but has not yet linked. A unique index on ``(platform, platform_user_id)`` keeps
two accounts from claiming the same handle; ``created_at`` anchors the sweep
that releases abandoned registrations.
"""

from datetime import datetime

from pymongo.errors import DuplicateKeyError

from app.constants.cache import REPO_GLOBAL_SCOPE
from app.db.repositories.base import MongoRepository
from app.models.platform_models import (
    PendingPlatformRegistrationDocument,
    PendingPlatformRegistrationUpdate,
)


class PendingPlatformRegistrationsRepository(
    MongoRepository[PendingPlatformRegistrationDocument, PendingPlatformRegistrationUpdate]
):
    collection_name = "pending_platform_registrations"
    document_model = PendingPlatformRegistrationDocument
    update_model = PendingPlatformRegistrationUpdate
    uses_object_id = True
    cache_policy = None

    async def record(
        self, *, user_id: str, platform: str, platform_user_id: str, created_at: datetime
    ) -> PendingPlatformRegistrationDocument | None:
        """Upsert the user's pending registration, restarting its expiry clock.

        Returns None when the handle is already pending on a different account —
        the unique index refusing the claim, not an error to swallow.
        """
        try:
            return await self._apply_raw_update(
                {"user_id": user_id, "platform": platform},
                {
                    "$set": {"platform_user_id": platform_user_id, "created_at": created_at},
                    "$setOnInsert": {"user_id": user_id, "platform": platform},
                },
                scope=REPO_GLOBAL_SCOPE,
                upsert=True,
            )
        except DuplicateKeyError:
            return None

    async def get_for_user(
        self, user_id: str, platform: str
    ) -> PendingPlatformRegistrationDocument | None:
        return await self._find_one({"user_id": user_id, "platform": platform})

    async def find_older_than(
        self, platform: str, cutoff: datetime
    ) -> list[PendingPlatformRegistrationDocument]:
        return await self._find(
            {"platform": platform, "created_at": {"$lt": cutoff}}, sort=[("created_at", 1)]
        )

    async def delete_for_user(self, user_id: str, platform: str) -> int:
        return await self._delete_many(
            {"user_id": user_id, "platform": platform}, scope=REPO_GLOBAL_SCOPE
        )

    async def delete_by_platform_user_id(self, platform: str, platform_user_id: str) -> int:
        return await self._delete_many(
            {"platform": platform, "platform_user_id": platform_user_id},
            scope=REPO_GLOBAL_SCOPE,
        )


pending_platform_registration_repository = PendingPlatformRegistrationsRepository()
