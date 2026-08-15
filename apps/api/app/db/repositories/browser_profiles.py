"""Repository for the ``browser_profiles`` collection — one saved login per (user, domain).

Uncached: a profile is read once per browser task, right before the session is
created, and written once when a task ends with a fresh storage_state.
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

    async def upsert_storage_state_blob(
        self, user_id: str, domain: str, storage_state_blob: str
    ) -> None:
        """Set the user's encrypted storage_state for ``domain``, creating the record on first use."""
        now = datetime.now(UTC)
        await self._apply_raw_update_unfetched(
            {"user_id": user_id, "domain": domain},
            {
                "$set": {"storage_state_blob": storage_state_blob},
                "$setOnInsert": {"user_id": user_id, "domain": domain, "created_at": now},
            },
            scope=user_id,
            upsert=True,
        )

    async def delete_for_user(self, user_id: str, domain: str | None = None) -> int:
        """Delete saved logins for ``user_id``, optionally scoped to one ``domain``.

        Returns the number of records deleted.
        """
        filter_: dict[str, object] = {"user_id": user_id}
        if domain is not None:
            filter_["domain"] = domain
        return await self._delete_many(filter_, scope=user_id)


browser_profile_repository = BrowserProfilesRepository()
