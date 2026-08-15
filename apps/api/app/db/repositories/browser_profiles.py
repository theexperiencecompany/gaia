"""Repository for the ``browser_profiles`` collection — one Steel profile per (user, domain).

Uncached: a profile id is read once per browser task, right before the Steel
session is created, and written once when a task ends with a fresh profile.
"""

from datetime import UTC, datetime

from app.db.repositories.base import UserScopedRepository
from app.models.browser_models import BrowserProfileDocument, BrowserProfileUpdate


class BrowserProfilesRepository(UserScopedRepository[BrowserProfileDocument, BrowserProfileUpdate]):
    collection_name = "browser_profiles"
    document_model = BrowserProfileDocument
    update_model = BrowserProfileUpdate
    uses_object_id = True
    cache_policy = None

    async def get_for_domain(self, user_id: str, domain: str) -> BrowserProfileDocument | None:
        return await self._find_one({"user_id": user_id, "domain": domain})

    async def upsert_steel_profile_id(
        self, user_id: str, domain: str, steel_profile_id: str
    ) -> None:
        """Set the user's Steel profile for ``domain``, creating the record on first use."""
        now = datetime.now(UTC)
        await self._apply_raw_update_unfetched(
            {"user_id": user_id, "domain": domain},
            {
                "$set": {"steel_profile_id": steel_profile_id},
                "$setOnInsert": {"user_id": user_id, "domain": domain, "created_at": now},
            },
            scope=user_id,
            upsert=True,
        )


browser_profile_repository = BrowserProfilesRepository()
