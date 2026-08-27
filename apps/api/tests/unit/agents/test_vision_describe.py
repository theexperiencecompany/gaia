"""The vision fallback's own model must be able to see, and the fallback's
behavior must degrade gracefully.

``describe_image`` is what a blind lane falls back to, and it fails SILENTLY —
a failed call returns ``None`` and every caller degrades to "couldn't look". So
pointing it at a text-only model does not raise anywhere; images simply stop
being understood. These tests pin the invariant that makes the fallback work at
all, separately from ``test_vision_tool_media``, which pins the other half (a
lane that CAN see never pays for a description).

Plus the call contract: the image is attached as an inline block, the text is
flattened, and provider failure or an empty completion degrades to ``None``
instead of failing the whole tool.
"""

from unittest.mock import AsyncMock, MagicMock, patch

from langchain_core.messages import AIMessage
import pytest

from app.agents.llm.vision.capability import model_can_view_images
from app.agents.llm.vision.describe import describe_image
from app.constants.llm import (
    DEFAULT_MODEL_NAME,
    VISION_MODEL_NAME,
    VISION_MODEL_PROVIDER,
)
from app.utils.multimodal import image_content_block

_MOD = "app.agents.llm.vision.describe"

IMAGE_B64 = "aW1hZ2UtYnl0ZXM="
MIME = "image/png"
PROMPT = "Describe what is in this screenshot."


@pytest.mark.unit
class TestTheDescriberCanSee:
    async def test_the_vision_lane_is_one_that_takes_pixels(self) -> None:
        """The whole point of the fallback. If VISION_MODEL_* is ever pointed at a
        text-only model this fails here instead of silently blanking every image."""
        config = {
            "configurable": {
                "lane": {
                    "provider": VISION_MODEL_PROVIDER,
                    "model": VISION_MODEL_NAME,
                },
                "model": VISION_MODEL_NAME,
            }
        }

        assert await model_can_view_images(config) is True

    async def test_it_does_not_describe_with_the_default_chat_model(self) -> None:
        """The default is chosen for cheap text and may be text-only; the describer
        must not inherit it. Callers reach the fallback precisely BECAUSE the active
        lane cannot see, so describing with that lane would return nothing."""
        with (
            patch(f"{_MOD}.get_vision_llm") as vision_llm,
            patch(
                f"{_MOD}.ainvoke_llm", AsyncMock(return_value=MagicMock(text="a red login screen"))
            ),
        ):
            await describe_image("BASE64", "image/png", prompt="what is this?")

        vision_llm.assert_called_once()

    async def test_the_configured_vision_model_is_not_merely_the_default(self) -> None:
        # Not a style preference: if these collapse to one name, a future default
        # swap silently takes the describer with it — which is exactly how this
        # broke when the default moved to a text-only model.
        if VISION_MODEL_NAME == DEFAULT_MODEL_NAME:
            pytest.fail(
                "VISION_MODEL_NAME tracks DEFAULT_MODEL_NAME — the describer will "
                "follow the default model wherever it goes, including text-only."
            )


@pytest.mark.unit
class TestDescribeImage:
    @patch(f"{_MOD}.get_vision_llm")
    @patch(f"{_MOD}.ainvoke_llm", new_callable=AsyncMock)
    async def test_happy_path_returns_trimmed_text(
        self, mock_ainvoke: AsyncMock, mock_llm: AsyncMock
    ) -> None:
        mock_ainvoke.return_value = AIMessage(content="A sunny field with a red barn.\n\n")

        result = await describe_image(IMAGE_B64, MIME, PROMPT)

        assert result == "A sunny field with a red barn."
        mock_llm.assert_called_once()
        messages = mock_ainvoke.await_args.args[1]
        assert messages[0]["role"] == "user"
        assert messages[0]["content"][0] == {"type": "text", "text": PROMPT}
        assert messages[0]["content"][1] == image_content_block(IMAGE_B64, MIME)
        assert mock_ainvoke.await_args.kwargs["label"] == "vision_fallback"

    async def test_provider_failure_returns_none(self) -> None:
        with (
            patch(f"{_MOD}.get_vision_llm"),
            patch(f"{_MOD}.ainvoke_llm", AsyncMock(side_effect=RuntimeError("provider down"))),
        ):
            assert await describe_image(IMAGE_B64, MIME, PROMPT) is None

    async def test_empty_completion_returns_none(self) -> None:
        with (
            patch(f"{_MOD}.get_vision_llm"),
            patch(f"{_MOD}.ainvoke_llm", AsyncMock(return_value=AIMessage(content="   "))),
        ):
            assert await describe_image(IMAGE_B64, MIME, PROMPT) is None


@pytest.mark.unit
class TestDegradation:
    async def test_a_provider_failure_returns_none_rather_than_raising(self) -> None:
        with (
            patch(f"{_MOD}.get_vision_llm"),
            patch(f"{_MOD}.ainvoke_llm", AsyncMock(side_effect=RuntimeError("provider down"))),
        ):
            assert await describe_image("BASE64", "image/png", prompt="p") is None

    async def test_an_empty_description_is_reported_as_no_description(self) -> None:
        with (
            patch(f"{_MOD}.get_vision_llm"),
            patch(f"{_MOD}.ainvoke_llm", AsyncMock(return_value=MagicMock(text="   "))),
        ):
            assert await describe_image("BASE64", "image/png", prompt="p") is None
