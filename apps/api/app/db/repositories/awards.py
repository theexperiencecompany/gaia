"""Repository for the awards collection.

User-scoped; each badge is earnable once per user (``(user_id, key)`` unique
index). No ``CachePolicy`` — badge checks run once a day inside the briefing,
not a hot per-request path.
"""

from pymongo.errors import DuplicateKeyError

from app.db.repositories.base import UserScopedRepository
from app.models.briefing_models import AwardDocument, AwardUpdate


class AwardsRepository(UserScopedRepository[AwardDocument, AwardUpdate]):
    collection_name = "awards"
    document_model = AwardDocument
    update_model = AwardUpdate
    uses_object_id = True
    cache_policy = None

    async def get_awarded_keys(self, user_id: str) -> set[str]:
        """Badge keys the user already holds — the daily check's already-earned set."""
        return set(await self._distinct("key", {"user_id": user_id}))

    async def award_badge(self, user_id: str, key: str) -> bool:
        """Insert a badge once. Returns True if newly earned, False if already held
        (the unique index lost the race, or a concurrent run got there first)."""
        try:
            await self.create(AwardDocument(user_id=user_id, key=key))
        except DuplicateKeyError:
            return False
        return True


award_repository = AwardsRepository()
