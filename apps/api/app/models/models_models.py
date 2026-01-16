from datetime import datetime, timezone
from enum import Enum
from typing import List, Optional

from pydantic import BaseModel, Field


class ModelProvider(str, Enum):
    """Supported model providers."""

    OPENAI = "openai"
    GEMINI = "gemini"
    GROK = "grok"
    OPENROUTER = "openrouter"


class PlanType(str, Enum):
    """Subscription plan types."""

    FREE = "free"
    PRO = "pro"


class ModelConfig(BaseModel):
    """Configuration for an AI model."""

    model_config = {"arbitrary_types_allowed": True}

    model_id: str = Field(..., description="Unique identifier for the model")
    name: str = Field(..., description="Display name of the model")
    model_provider: ModelProvider = Field(description="Model provider (new field)")
    inference_provider: ModelProvider = Field(
        description="Inference provider (new field)"
    )
    provider_model_name: str = Field(
        ..., description="Model name as used by the provider"
    )
    description: Optional[str] = Field(None, description="Model description")
    logo_url: Optional[str] = Field(
        None, description="URL to the model's logo (not provider logo)"
    )
    max_tokens: int = Field(..., description="Maximum token limit")
    supports_streaming: bool = Field(
        default=True, description="Whether model supports streaming"
    )
    supports_function_calling: bool = Field(
        default=True, description="Whether model supports function calling"
    )
    available_in_plans: List[PlanType] = Field(
        ..., description="Plans where this model is available"
    )
    lowest_tier: PlanType = Field(
        ..., description="Lowest pricing tier where this model is available"
    )
    is_active: bool = Field(
        default=True, description="Whether model is currently active"
    )
    is_default: bool = Field(
        default=False, description="Whether this is a default model"
    )
    pricing_per_1k_input_tokens: Optional[float] = Field(
        None, description="Cost per 1K input tokens in USD"
    )
    pricing_per_1k_output_tokens: Optional[float] = Field(
        None, description="Cost per 1K output tokens in USD"
    )
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class ModelResponse(BaseModel):
    """Response model for model data."""

    model_id: str = Field(..., description="Unique identifier for the model")
    name: str = Field(..., description="Display name of the model")
    model_provider: Optional[ModelProvider] = Field(
        None, description="Model provider (new field)"
    )
    inference_provider: Optional[ModelProvider] = Field(
        None, description="Inference provider (new field)"
    )
    description: Optional[str] = Field(None, description="Model description")
    logo_url: Optional[str] = Field(
        None, description="URL to the model's logo (not provider logo)"
    )
    max_tokens: int = Field(..., description="Maximum token limit")
    supports_streaming: bool = Field(
        ..., description="Whether model supports streaming"
    )
    supports_function_calling: bool = Field(
        ..., description="Whether model supports function calling"
    )
    available_in_plans: List[PlanType] = Field(
        ..., description="Plans where this model is available"
    )
    lowest_tier: PlanType = Field(
        ..., description="Lowest pricing tier where this model is available"
    )
    is_default: bool = Field(..., description="Whether this is a default model")


class ModelSelectionRequest(BaseModel):
    """Request to select a model for a user."""

    model_id: str = Field(..., description="Model ID to select")


class ModelSelectionResponse(BaseModel):
    """Response after selecting a model."""

    success: bool = Field(..., description="Whether selection was successful")
    message: str = Field(..., description="Response message")
    selected_model: ModelResponse = Field(..., description="Selected model data")


class ModelCreateRequest(BaseModel):
    """Request to create a new model (admin only)."""

    model_id: str = Field(..., description="Unique identifier for the model")
    name: str = Field(..., description="Display name of the model")
    provider: ModelProvider = Field(..., description="Model provider")
    model_provider: Optional[ModelProvider] = Field(
        None, description="Model provider (new field)"
    )
    inference_provider: Optional[ModelProvider] = Field(
        None, description="Inference provider (new field)"
    )
    provider_model_name: str = Field(
        ..., description="Model name as used by the provider"
    )
    description: Optional[str] = Field(None, description="Model description")
    logo_url: Optional[str] = Field(
        None, description="URL to the model's logo (not provider logo)"
    )
    max_tokens: int = Field(..., description="Maximum token limit")
    supports_streaming: bool = Field(
        default=True, description="Whether model supports streaming"
    )
    supports_function_calling: bool = Field(
        default=True, description="Whether model supports function calling"
    )
    available_in_plans: List[PlanType] = Field(
        ..., description="Plans where this model is available"
    )
    lowest_tier: PlanType = Field(
        ..., description="Lowest pricing tier where this model is available"
    )
    is_active: bool = Field(
        default=True, description="Whether model is currently active"
    )
    is_default: bool = Field(
        default=False, description="Whether this is a default model"
    )
    pricing_per_1k_input_tokens: Optional[float] = Field(
        None, description="Cost per 1K input tokens in USD"
    )
    pricing_per_1k_output_tokens: Optional[float] = Field(
        None, description="Cost per 1K output tokens in USD"
    )


class ModelUpdateRequest(BaseModel):
    """Request to update an existing model (admin only)."""

    name: Optional[str] = Field(None, description="Display name of the model")
    description: Optional[str] = Field(None, description="Model description")
    logo_url: Optional[str] = Field(
        None, description="URL to the model's logo (not provider logo)"
    )
    max_tokens: Optional[int] = Field(None, description="Maximum token limit")
    supports_streaming: Optional[bool] = Field(
        None, description="Whether model supports streaming"
    )
    supports_function_calling: Optional[bool] = Field(
        None, description="Whether model supports function calling"
    )
    available_in_plans: Optional[List[PlanType]] = Field(
        None, description="Plans where this model is available"
    )
    lowest_tier: Optional[PlanType] = Field(
        None, description="Lowest pricing tier where this model is available"
    )
    is_active: Optional[bool] = Field(
        None, description="Whether model is currently active"
    )
    is_default: Optional[bool] = Field(
        None, description="Whether this is a default model"
    )
    pricing_per_1k_input_tokens: Optional[float] = Field(
        None, description="Cost per 1K input tokens in USD"
    )
    pricing_per_1k_output_tokens: Optional[float] = Field(
        None, description="Cost per 1K output tokens in USD"
    )
