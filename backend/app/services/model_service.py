from datetime import datetime, timezone
from typing import List, Optional

from app.config.loggers import app_logger as logger
from app.db.mongodb.collections import ai_models_collection, users_collection
from app.decorators.caching import Cacheable, CacheInvalidator
from app.models.models_models import ModelConfig, ModelResponse, PlanType
from bson import ObjectId
from fastapi import HTTPException


@Cacheable(
    key_pattern="chat_models:available_models:{user_plan}",
    ttl=3600,  # Cache for 1 hour
    model=List[ModelResponse],
)
async def get_available_models(user_plan: str = "all") -> List[ModelResponse]:
    """
    Get all available models for a user based on their plan.

    Args:
        user_plan: User's subscription plan (free, pro, enterprise). If None, returns all active models.

    Returns:
        List of available models
    """
    try:
        if user_plan == "all":
            # If no plan specified, return all active models
            models_cursor = ai_models_collection.find({"is_active": True})
        else:
            plan_enum = PlanType(user_plan.lower())
            # Find models available for the user's plan
            models_cursor = ai_models_collection.find(
                {"is_active": True, "available_in_plans": {"$in": [plan_enum.value]}}
            )

        models = []
        async for model_doc in models_cursor:
            model_response = ModelResponse(
                model_id=model_doc["model_id"],
                name=model_doc["name"],
                model_provider=model_doc.get("model_provider"),
                inference_provider=model_doc.get("inference_provider"),
                description=model_doc.get("description"),
                logo_url=model_doc.get("logo_url"),
                max_tokens=model_doc["max_tokens"],
                supports_streaming=model_doc.get("supports_streaming", True),
                supports_function_calling=model_doc.get(
                    "supports_function_calling", True
                ),
                available_in_plans=model_doc["available_in_plans"],
                lowest_tier=model_doc["lowest_tier"],
                is_default=model_doc.get("is_default", False),
            )
            models.append(model_response)

        return models

    except ValueError:
        logger.error(f"Invalid plan type: {user_plan}")
        raise HTTPException(status_code=400, detail="Invalid plan type")
    except Exception as e:
        logger.error(f"Error fetching available models: {e}")
        raise HTTPException(status_code=500, detail="Failed to fetch models")


@Cacheable(
    key_pattern="chat_models:model_by_id:{model_id}",
    ttl=3600,  # Cache for 1 hour
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
        logger.error(f"Error fetching model {model_id}: {e}")
        raise HTTPException(status_code=500, detail="Failed to fetch model")


@CacheInvalidator(key_patterns=["chat_models:selected_model:{user_id}"])
async def update_user_selected_model(
    user_id: str, model_id: str, user_plan: str
) -> ModelResponse:
    """
    Update user's selected model.

    Args:
        user_id: User ID
        model_id: Model ID to select
        user_plan: User's subscription plan

    Returns:
        Selected model data
    """
    try:
        # Verify model exists and is available for user's plan
        model = await get_model_by_id(model_id)
        if not model:
            raise HTTPException(status_code=404, detail="Model not found")

        if not model.is_active:
            raise HTTPException(status_code=400, detail="Model is not active")

        plan_enum = PlanType(user_plan.lower())
        if plan_enum.value not in model.available_in_plans:
            raise HTTPException(
                status_code=403, detail=f"Model not available for {user_plan} plan"
            )

        # Update user's selected model
        result = await users_collection.update_one(
            {"_id": ObjectId(user_id)},
            {
                "$set": {
                    "selected_model": model_id,
                    "updated_at": datetime.now(timezone.utc),
                }
            },
        )

        if result.matched_count == 0:
            raise HTTPException(status_code=404, detail="User not found")

        # Return model response
        return ModelResponse(
            model_id=model.model_id,
            name=model.name,
            model_provider=model.model_provider,
            inference_provider=model.inference_provider,
            description=model.description,
            logo_url=model.logo_url,
            max_tokens=model.max_tokens,
            supports_streaming=model.supports_streaming,
            supports_function_calling=model.supports_function_calling,
            available_in_plans=model.available_in_plans,
            lowest_tier=model.lowest_tier,
            is_default=model.is_default,
        )

    except ValueError:
        logger.error(f"Invalid plan type: {user_plan}")
        raise HTTPException(status_code=400, detail="Invalid plan type")
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error updating user model selection: {e}")
        raise HTTPException(status_code=500, detail="Failed to update model selection")


@Cacheable(
    key_pattern="chat_models:selected_model:{user_id}",
    ttl=3600,  # Cache for 1 hour
    model=ModelConfig,
    ignore_none=True,
)
async def get_user_selected_model(user_id: str) -> Optional[ModelConfig]:
    """
    Get user's currently selected model.

    Args:
        user_id: User ID

    Returns:
        Selected model configuration or None if not set
    """
    try:
        user = await users_collection.find_one({"_id": ObjectId(user_id)})
        if not user:
            raise HTTPException(status_code=404, detail="User not found")

        selected_model_id = user.get("selected_model")
        if not selected_model_id:
            # Return default model if no selection
            return await get_default_model()

        return await get_model_by_id(selected_model_id)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error fetching user selected model: {e}")
        raise HTTPException(status_code=500, detail="Failed to fetch user model")


@Cacheable(
    key_pattern="chat_models:default_model",
    ttl=3600,  # Cache for 1 hour
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
        logger.error(f"Error fetching default model: {e}")
        return None
