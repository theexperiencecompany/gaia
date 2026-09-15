"""How the active model lane takes delivery of a tool result's inline images."""

from enum import Enum

from langchain_core.runnables import RunnableConfig

from app.agents.llm.lane import ModelLane
from app.agents.llm.model_catalog import get_openrouter_catalog
from app.constants.llm import (
    DEFAULT_LLM_PROVIDER,
    DEFAULT_MODEL_NAME,
    GEMINI_PROVIDER,
    LANE_FIELD_ID,
    OPENROUTER_PROVIDER,
)
from app.models.agent_models import agent_configurable


class MediaDelivery(Enum):
    """The transform MediaAdapter applies to a *tool result's* images for the active lane.

    One strategy per lane, picked from what that lane's model can see. Images
    the user themselves attached are never touched.
    """

    # Leave them in the tool result — the model reads them there.
    KEEP_IN_TOOL_RESULTS = "keep_in_tool_results"
    # Replace each with a text description — the model can't see images at all.
    REPLACE_WITH_TEXT = "replace_with_text"


def active_lane(config: RunnableConfig) -> tuple[str, str]:
    """Return the (provider, model) this run will actually call."""
    lane = ModelLane.from_configurable(agent_configurable(config).get(LANE_FIELD_ID))
    if lane is None:
        return DEFAULT_LLM_PROVIDER, DEFAULT_MODEL_NAME
    return lane.provider, lane.model or DEFAULT_MODEL_NAME


async def resolve_media_delivery(config: RunnableConfig) -> MediaDelivery:
    """Return the delivery strategy for the active lane's tool-result images.

    Direct Gemini is multimodal into tool results; OpenRouter models are
    looked up in the live catalog. Unknown/miss falls back to text, never a
    request that will be rejected — media support is per-model and unlisted
    by the models API, so it's established via tests/model_onboarding.
    """
    provider, model = active_lane(config)
    if provider == GEMINI_PROVIDER:
        return MediaDelivery.KEEP_IN_TOOL_RESULTS
    if provider == OPENROUTER_PROVIDER:
        catalog = await get_openrouter_catalog()
        if await catalog.accepts_images(model):
            return MediaDelivery.KEEP_IN_TOOL_RESULTS
    return MediaDelivery.REPLACE_WITH_TEXT


async def model_can_view_images(config: RunnableConfig) -> bool:
    """Whether the active model can see pixels at all, however they're delivered."""
    return await resolve_media_delivery(config) is not MediaDelivery.REPLACE_WITH_TEXT
