"""Repository for attention settings: one document per user, absent until they change a setting."""

from app.constants.outbox_attention import ATTENTION_SETTINGS_COLLECTION
from app.db.repositories.base import UserScopedRepository
from app.models.attention_settings_models import (
    AttentionSettings,
    AttentionSettingsDocument,
    AttentionSettingsUpdate,
)


class AttentionSettingsRepository(
    UserScopedRepository[AttentionSettingsDocument, AttentionSettingsUpdate]
):
    """Persistence for attention settings, unique on user_id."""

    collection_name = ATTENTION_SETTINGS_COLLECTION
    document_model = AttentionSettingsDocument
    update_model = AttentionSettingsUpdate
    uses_object_id = True
    cache_policy = None

    async def read(self, user_id: str) -> AttentionSettings:
        """Return the user's settings; the defaults for a user who never changed one."""
        stored = await self._find_one({"user_id": user_id})
        if stored is None:
            return AttentionSettings()
        return AttentionSettings.model_validate(stored.model_dump(exclude={"id", "user_id"}))

    async def save(self, user_id: str, settings: AttentionSettings) -> None:
        """Store the settings as the user's, replacing what they had."""
        await self._apply_raw_update_unfetched(
            {"user_id": user_id},
            {
                "$set": settings.model_dump(mode="json"),
                "$setOnInsert": {"user_id": user_id},
            },
            scope=user_id,
            upsert=True,
        )


attention_settings_repository = AttentionSettingsRepository()
