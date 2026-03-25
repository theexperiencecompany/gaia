from typing import Optional

from shared.py.wide_events import log
from app.db.mongodb.collections import ai_models_collection
from app.decorators.caching import Cacheable
from app.models.models_models import ModelConfig
from fastapi import HTTPException


@Cacheable(
    key_pattern="chat_models:model_by_id:{model_id}",
    ttl=3600,
    model=ModelConfig,
    ignore_none=True,
)
async def get_model_by_id(model_id: str) -> Optional[ModelConfig]:
    """
    Get a specific model by its ID.

    Args:
        model_id: Model identifier

    Returns:
        Model configuration or None if not found
    """
    try:
        model_doc = await ai_models_collection.find_one({"model_id": model_id})
        if not model_doc:
            return None

        # Remove MongoDB ObjectId for serialization
        model_doc.pop("_id", None)

        return ModelConfig(**model_doc)

    except Exception as e:
        log.error(f"Error fetching model {model_id}: {e}")
        raise HTTPException(status_code=500, detail="Failed to fetch model")


@Cacheable(
    key_pattern="chat_models:default_model",
    ttl=3600,
    model=ModelConfig,
    ignore_none=True,
)
async def get_default_model() -> Optional[ModelConfig]:
    """
    Get the default model.

    Returns:
        Default model configuration
    """
    try:
        model_doc = await ai_models_collection.find_one(
            {"is_default": True, "is_active": True}
        )

        if not model_doc:
            # Fallback to any active model if no default is set
            model_doc = await ai_models_collection.find_one({"is_active": True})

        if not model_doc:
            return None

        model_doc.pop("_id", None)
        return ModelConfig(**model_doc)

    except Exception as e:
        log.error(f"Error fetching default model: {e}")
        return None
