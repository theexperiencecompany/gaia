from typing import List

from app.api.v1.dependencies.oauth_dependencies import get_current_user
from app.decorators.caching import Cacheable
from app.models.models_models import (
    ModelResponse,
    ModelSelectionRequest,
    ModelSelectionResponse,
)
from app.models.payment_models import PlanType
from app.services.model_service import (
    get_available_models,
    update_user_selected_model,
)
from app.services.payments.payment_service import payment_service
from fastapi import APIRouter, Depends, HTTPException

router = APIRouter(prefix="/chat-models", tags=["models"])


@router.get("", response_model=List[ModelResponse])
@Cacheable(smart_hash=True, ttl=1800, model=List[ModelResponse])  # 30 minutes
async def list_available_models(
    current_user: dict = Depends(get_current_user),
):
    """
    Get all available AI models for the current user.
    """
    return await get_available_models()


@router.put("/select", response_model=ModelSelectionResponse)
async def select_model(
    request: ModelSelectionRequest,
    current_user: dict = Depends(get_current_user),
):
    """
    Select an AI model for the current user.
    """

    user_id = current_user.get("user_id")
    if not user_id:
        raise HTTPException(status_code=400, detail="User ID not found")

    subscription_plan = await payment_service.get_user_subscription_status(
        user_id=user_id
    )
    selected_model = await update_user_selected_model(
        user_id=user_id,
        model_id=request.model_id,
        user_plan=subscription_plan.plan_type or PlanType.FREE,
    )

    return ModelSelectionResponse(
        success=True,
        message="Model selected successfully",
        selected_model=selected_model,
    )
