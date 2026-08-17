from fastapi import HTTPException

from app.db.repositories.ai_models import ai_model_repository
from app.decorators.caching import Cacheable
from app.models.models_models import ModelConfig
from shared.py.wide_events import log


@Cacheable(
    key_pattern="chat_models:model_by_id:{model_id}",
    ttl=3600,
    model=ModelConfig,
    ignore_none=True,
)
async def get_model_by_id(model_id: str) -> ModelConfig | None:
    """
    Get a specific model by its ID.

    Args:
        model_id: Model identifier

    Returns:
        Model configuration or None if not found
    """
    try:
        return await ai_model_repository.get_by_model_id(model_id)
    except Exception as e:
        log.error(
            "Error fetching model", model_id=model_id, error=str(e), error_type=type(e).__name__
        )
        raise HTTPException(status_code=500, detail="Failed to fetch model")
