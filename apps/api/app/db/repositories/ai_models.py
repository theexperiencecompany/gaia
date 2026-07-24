"""Repository for the ``ai_models`` collection — the global AI model catalog.

Global (not user-scoped), keyed by the business ``model_id``. Read-only in the
app today (seeding is done by scripts); the ``@Cacheable`` decorators on the
model service stay the caching layer for these hot reads, so this repository sets
no cache policy of its own.
"""

from app.db.repositories.base import MongoRepository
from app.models.models_models import AiModelUpdate, ModelConfig


class AiModelsRepository(MongoRepository[ModelConfig, AiModelUpdate]):
    collection_name = "ai_models"
    document_model = ModelConfig
    update_model = AiModelUpdate
    uses_object_id = True
    identity_field = "model_id"
    cache_policy = None

    async def get_by_model_id(self, model_id: str) -> ModelConfig | None:
        return await self._find_one({"model_id": model_id})

    async def get_default(self) -> ModelConfig | None:
        """The default active model, falling back to any active model."""
        default = await self._find_one({"is_default": True, "is_active": True})
        if default is not None:
            return default
        return await self._find_one({"is_active": True})


ai_model_repository = AiModelsRepository()
