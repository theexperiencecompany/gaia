"""How the active model lane takes delivery of a tool result's inline images."""

from enum import Enum

from langchain_core.runnables import RunnableConfig

from app.agents.llm.model_catalog import openrouter_catalog
from app.constants.llm import (
    DEFAULT_LLM_PROVIDER,
    DEFAULT_MODEL_NAME,
    GEMINI_PROVIDER,
    OPENROUTER_PROVIDER,
)


class MediaDelivery(Enum):
    """The transform ``MediaAdapter`` applies to a *tool result's* images for the
    active lane — one strategy per lane, picked from what that lane's model can
    see. Images the user themselves attached are never touched; this only governs
    media a tool produced.
    """

    # Leave them in the tool result — the model reads them there (direct Gemini).
    KEEP_IN_TOOL_RESULTS = "keep_in_tool_results"
    # Move them into a user message after the tool run — the model can't see
    # images inside tool results, only in user messages (multimodal OpenRouter).
    MOVE_TO_USER_MESSAGE = "move_to_user_message"
    # Replace each with a text description — the model can't see images at all.
    REPLACE_WITH_TEXT = "replace_with_text"


def active_lane(config: RunnableConfig) -> tuple[str, str]:
    """The (provider, model) this run will actually call.

    Gemini binds its model from ``model_name`` and OpenRouter from ``model``, so
    ``plan_model._pin_model`` writes both and either key answers the question.
    """
    configurable = config.get("configurable") or {}
    provider = configurable.get("provider") or DEFAULT_LLM_PROVIDER
    model = configurable.get("model") or configurable.get("model_name") or DEFAULT_MODEL_NAME
    return provider, model


async def resolve_media_delivery(config: RunnableConfig) -> MediaDelivery:
    """The delivery strategy for the active lane's tool-result images.

    Direct Gemini is multimodal all the way down into tool results. OpenRouter
    models are looked up in the live catalog. Unknown providers and catalog
    misses fall back to the text description — never to a provider request that
    will be rejected.
    """
    provider, model = active_lane(config)
    if provider == GEMINI_PROVIDER:
        return MediaDelivery.KEEP_IN_TOOL_RESULTS
    if provider == OPENROUTER_PROVIDER and await openrouter_catalog.accepts_images(model):
        return MediaDelivery.MOVE_TO_USER_MESSAGE
    return MediaDelivery.REPLACE_WITH_TEXT


async def model_can_view_images(config: RunnableConfig) -> bool:
    """Whether the active model can see pixels at all, however they're delivered."""
    return await resolve_media_delivery(config) is not MediaDelivery.REPLACE_WITH_TEXT
