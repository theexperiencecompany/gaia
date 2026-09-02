"""Repository for the ``browser_profiles`` collection — one saved login per (user, domain).

Uncached: a profile is read once per browser task, right before the session is
created, and written once when a task ends with a fresh storage_state.
"""

from datetime import UTC, datetime

from app.db.repositories.base import UserScopedRepository
from app.models.browser_models import (
    BrowserLoginProvenance,
    BrowserProfileDocument,
    BrowserProfileUpdate,
)


class BrowserProfilesRepository(UserScopedRepository[BrowserProfileDocument, BrowserProfileUpdate]):
    """Persistence for per-domain browser login profiles."""

    collection_name = "browser_profiles"
    document_model = BrowserProfileDocument
    update_model = BrowserProfileUpdate
    uses_object_id = True
    cache_policy = None

    async def get_for_domain(self, user_id: str, domain: str) -> BrowserProfileDocument | None:
        """Return the saved profile for a domain, or None."""
        return await self._find_one({"user_id": user_id, "domain": domain})

    async def upsert_storage_state_blob(
        self,
        user_id: str,
        domain: str,
        storage_state_blob: str,
        provenance: BrowserLoginProvenance | None = None,
    ) -> None:
        """Set the user's encrypted storage_state for ``domain``, creating the record on first use.

        ``provenance`` is written only on the CLI import path; the generic
        task-end save passes ``None`` and leaves any existing provenance intact.
        """
        now = datetime.now(UTC)
        set_fields: dict[str, object] = {"storage_state_blob": storage_state_blob}
        if provenance is not None:
            set_fields.update(provenance.model_dump())
        await self._apply_raw_update_unfetched(
            {"user_id": user_id, "domain": domain},
            {
                "$set": set_fields,
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
