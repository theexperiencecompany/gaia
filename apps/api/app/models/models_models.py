from datetime import UTC, datetime
from enum import Enum

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
    inference_provider: ModelProvider = Field(description="Inference provider (new field)")
    provider_model_name: str = Field(..., description="Model name as used by the provider")
    description: str | None = Field(None, description="Model description")
    logo_url: str | None = Field(None, description="URL to the model's logo (not provider logo)")
    max_tokens: int = Field(..., description="Maximum token limit")
    supports_streaming: bool = Field(default=True, description="Whether model supports streaming")
    supports_function_calling: bool = Field(
        default=True, description="Whether model supports function calling"
    )
    available_in_plans: list[PlanType] = Field(
        ..., description="Plans where this model is available"
    )
    lowest_tier: PlanType = Field(
        ..., description="Lowest pricing tier where this model is available"
    )
    is_active: bool = Field(default=True, description="Whether model is currently active")
    is_default: bool = Field(default=False, description="Whether this is a default model")
    pricing_per_1k_input_tokens: float | None = Field(
        None, description="Cost per 1K input tokens in USD"
    )
    pricing_per_1k_output_tokens: float | None = Field(
        None, description="Cost per 1K output tokens in USD"
    )
    pricing_per_1k_cached_input_tokens: float | None = Field(
        None,
        description="Cost per 1K cached input tokens in USD. Defaults to 25% of input.",
    )
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class ModelResponse(BaseModel):
    """Response model for model data."""

    model_id: str = Field(..., description="Unique identifier for the model")
    name: str = Field(..., description="Display name of the model")
    model_provider: ModelProvider | None = Field(None, description="Model provider (new field)")
    inference_provider: ModelProvider | None = Field(
        None, description="Inference provider (new field)"
    )
    description: str | None = Field(None, description="Model description")
    logo_url: str | None = Field(None, description="URL to the model's logo (not provider logo)")
    max_tokens: int = Field(..., description="Maximum token limit")
    supports_streaming: bool = Field(..., description="Whether model supports streaming")
    supports_function_calling: bool = Field(
        ..., description="Whether model supports function calling"
    )
    available_in_plans: list[PlanType] = Field(
        ..., description="Plans where this model is available"
    )
    lowest_tier: PlanType = Field(
        ..., description="Lowest pricing tier where this model is available"
    )
    is_default: bool = Field(..., description="Whether this is a default model")
