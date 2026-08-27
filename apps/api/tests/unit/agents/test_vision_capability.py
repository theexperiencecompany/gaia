"""Which images the run's model is allowed to see, and how they reach it.

The answer comes from the run's resolved lane. Get it wrong in the permissive
direction and every tool result carrying an image 400s at the provider; get it
wrong the other way and a multimodal model is fed text descriptions of pictures
it could have read.
"""

from unittest.mock import AsyncMock, MagicMock, patch

from langchain_core.runnables import RunnableConfig
import pytest

from app.agents.llm.types import LLMProviderName
from app.agents.llm.vision.capability import (
    MediaDelivery,
    active_lane,
    model_can_view_images,
    resolve_media_delivery,
)
from app.constants.llm import (
    DEFAULT_LLM_PROVIDER,
    DEFAULT_MODEL_NAME,
    GEMINI_PROVIDER,
    LANE_FIELD_ID,
    OPENROUTER_PROVIDER,
)

_MOD = "app.agents.llm.vision.capability"


def _config(lane: dict | None) -> RunnableConfig:
    return {"configurable": {LANE_FIELD_ID: lane} if lane is not None else {}}


def _catalog(accepts: bool) -> MagicMock:
    catalog = MagicMock()
    catalog.accepts_images = AsyncMock(return_value=accepts)
    return catalog


@pytest.mark.unit
class TestActiveLane:
    def test_the_runs_lane_answers_the_question(self) -> None:
        assert active_lane(_config({"provider": GEMINI_PROVIDER, "model": "gemini-x"})) == (
            GEMINI_PROVIDER,
            "gemini-x",
        )

    def test_a_bag_with_no_lane_falls_back_to_the_default_model(self) -> None:
        """Queue items and stored HIL resume_items predate the lane key, so "no
        lane" is a real state — and answering it wrong strips images from a run
        that could have read them."""
        assert active_lane(_config(None)) == (DEFAULT_LLM_PROVIDER, DEFAULT_MODEL_NAME)

    def test_a_lane_that_pins_no_model_answers_with_the_clients_default(self) -> None:
        """The custom dev endpoint pins no model — the client serves DEV_LLM_MODEL."""
        assert active_lane(_config({"provider": OPENROUTER_PROVIDER, "model": None})) == (
            OPENROUTER_PROVIDER,
            DEFAULT_MODEL_NAME,
        )


@pytest.mark.unit
class TestMediaDeliveryPerLane:
    async def test_direct_gemini_keeps_images_in_the_tool_result(self) -> None:
        """Multimodal all the way down, and not in the OpenRouter catalog."""
        delivery = await resolve_media_delivery(
            _config({"provider": GEMINI_PROVIDER, "model": "gemini-x"})
        )

        assert delivery is MediaDelivery.KEEP_IN_TOOL_RESULTS

    async def test_an_openrouter_model_the_catalog_says_takes_images_keeps_them(self) -> None:
        with patch(f"{_MOD}.get_openrouter_catalog", AsyncMock(return_value=_catalog(True))):
            delivery = await resolve_media_delivery(
                _config({"provider": OPENROUTER_PROVIDER, "model": "vendor/sees"})
            )

        assert delivery is MediaDelivery.KEEP_IN_TOOL_RESULTS

    async def test_a_text_only_openrouter_model_gets_the_description_instead(self) -> None:
        with patch(f"{_MOD}.get_openrouter_catalog", AsyncMock(return_value=_catalog(False))):
            delivery = await resolve_media_delivery(
                _config({"provider": OPENROUTER_PROVIDER, "model": "vendor/blind"})
            )

        assert delivery is MediaDelivery.REPLACE_WITH_TEXT

    async def test_the_catalog_is_asked_about_the_lanes_own_model(self) -> None:
        catalog = _catalog(True)
        with patch(f"{_MOD}.get_openrouter_catalog", AsyncMock(return_value=catalog)):
            await resolve_media_delivery(
                _config({"provider": OPENROUTER_PROVIDER, "model": "vendor/sees"})
            )

        catalog.accepts_images.assert_awaited_once_with("vendor/sees")

    async def test_a_provider_with_no_catalog_never_gets_a_request_it_would_reject(self) -> None:
        """The dev endpoint is neither Gemini nor in the OpenRouter catalog, so
        nothing can establish that it takes pixels — send the description."""
        delivery = await resolve_media_delivery(
            _config({"provider": LLMProviderName.CUSTOM, "model": "local/dev-model"})
        )

        assert delivery is MediaDelivery.REPLACE_WITH_TEXT

    async def test_a_bogus_provider_fails_loudly_rather_than_silently_dropping_images(
        self,
    ) -> None:
        """A lane names its provider as an ``LLMProviderName``. An unknown one is a
        bug in whatever wrote the bag, and it must surface there rather than
        degrade every image on the run to text."""
        with pytest.raises(ValueError, match="not a valid LLMProviderName"):
            await resolve_media_delivery(_config({"provider": "some-new-provider"}))


@pytest.mark.unit
class TestModelCanViewImages:
    async def test_a_text_only_lane_cannot_view_images_however_they_are_delivered(self) -> None:
        with patch(f"{_MOD}.get_openrouter_catalog", AsyncMock(return_value=_catalog(False))):
            assert (
                await model_can_view_images(
                    _config({"provider": OPENROUTER_PROVIDER, "model": "vendor/blind"})
                )
                is False
            )

    async def test_a_multimodal_lane_can(self) -> None:
        assert (
            await model_can_view_images(_config({"provider": GEMINI_PROVIDER, "model": "gemini-x"}))
            is True
        )
