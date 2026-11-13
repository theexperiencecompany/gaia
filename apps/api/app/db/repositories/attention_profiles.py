"""Repository for attention profiles: one document per user, seeded the first time it is read."""

from app.constants.outbox_judge import ATTENTION_PROFILES_COLLECTION
from app.db.repositories.base import UserScopedRepository
from app.models.attention_profile_models import (
    AttentionProfileDocument,
    AttentionProfileUpdate,
    ProfileAnswer,
)


class AttentionProfilesRepository(
    UserScopedRepository[AttentionProfileDocument, AttentionProfileUpdate]
):
    """Persistence for attention profiles, unique on user_id."""

    collection_name = ATTENTION_PROFILES_COLLECTION
    document_model = AttentionProfileDocument
    update_model = AttentionProfileUpdate
    uses_object_id = True
    cache_policy = None

    async def get_or_seed(
        self, user_id: str, seed: list[ProfileAnswer]
    ) -> AttentionProfileDocument:
        """Return the user's profile, storing seed as it first if they have none; two first reads agree."""
        await self._apply_raw_update_unfetched(
            {"user_id": user_id},
            {
                "$setOnInsert": {
                    "user_id": user_id,
                    "version": 1,
                    "answers": [answer.model_dump() for answer in seed],
                }
            },
            scope=user_id,
            upsert=True,
        )
        stored = await self._find_one({"user_id": user_id})
        if stored is None:
            raise RuntimeError(f"attention profile of {user_id} vanished after its seed")
        return stored


attention_profiles_repository = AttentionProfilesRepository()
