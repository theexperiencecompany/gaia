"""What kind of inline media, if any, the active model lane can receive."""

from enum import Enum

from langchain_core.runnables import RunnableConfig

from app.agents.llm.model_catalog import openrouter_catalog
from app.constants.llm import (
    DEFAULT_LLM_PROVIDER,
    DEFAULT_MODEL_NAME,
    GEMINI_PROVIDER,
    OPENROUTER_PROVIDER,
)


class VisionCapability(Enum):
    """How a lane takes delivery of inline media, from most to least direct."""

    TOOL_MESSAGE_BLOCKS = "tool_message_blocks"
    USER_MESSAGE_BLOCKS = "user_message_blocks"
    TEXT_ONLY = "text_only"


def active_lane(config: RunnableConfig) -> tuple[str, str]:
    """The (provider, model) this run will actually call.

    Gemini binds its model from ``model_name`` and OpenRouter from ``model``, so
    ``plan_model._pin_model`` writes both and either key answers the question.
    """
    configurable = config.get("configurable") or {}
    provider = configurable.get("provider") or DEFAULT_LLM_PROVIDER
    model = configurable.get("model") or configurable.get("model_name") or DEFAULT_MODEL_NAME
    return provider, model


async def resolve_vision_capability(config: RunnableConfig) -> VisionCapability:
    """Resolve the active lane's media capability.

    Direct Gemini is multimodal all the way down into tool results. OpenRouter
    models are looked up in the live catalog. Unknown providers and catalog
    misses are treated as text-only — fail safe to the description fallback,
    never to a provider request that will be rejected.
    """
    provider, model = active_lane(config)
    if provider == GEMINI_PROVIDER:
        return VisionCapability.TOOL_MESSAGE_BLOCKS
    if provider == OPENROUTER_PROVIDER and await openrouter_catalog.accepts_images(model):
        return VisionCapability.USER_MESSAGE_BLOCKS
    return VisionCapability.TEXT_ONLY


async def model_can_view_images(config: RunnableConfig) -> bool:
    """Whether the active model can see pixels at all, however they're delivered."""
    return await resolve_vision_capability(config) is not VisionCapability.TEXT_ONLY
