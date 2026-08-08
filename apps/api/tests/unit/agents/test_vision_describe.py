"""Behavior tests for app.agents.llm.vision.describe (the text-description fallback).

Locks: a one-off default-model call with the image attached as an inline block,
flattened text returned, and graceful ``None`` degradation on provider failure
or an empty completion — the caller degrades instead of failing the whole tool.
"""

from unittest.mock import AsyncMock, patch

from langchain_core.messages import AIMessage

from app.agents.llm.vision.describe import describe_image
from app.utils.multimodal import image_content_block

MODULE = "app.agents.llm.vision.describe"

IMAGE_B64 = "aW1hZ2UtYnl0ZXM="
MIME = "image/png"
PROMPT = "Describe what is in this screenshot."
LABEL = "vision_fallback"


class TestDescribeImage:
    @patch(f"{MODULE}.get_default_llm")
    @patch(f"{MODULE}.ainvoke_llm", new_callable=AsyncMock)
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
        assert mock_ainvoke.await_args.kwargs["label"] == LABEL

    @patch(f"{MODULE}.get_default_llm")
    @patch(f"{MODULE}.ainvoke_llm", new_callable=AsyncMock)
    async def test_provider_failure_returns_none(
        self, mock_ainvoke: AsyncMock, _: AsyncMock
    ) -> None:
        mock_ainvoke.side_effect = RuntimeError("provider down")

        assert await describe_image(IMAGE_B64, MIME, PROMPT) is None

    @patch(f"{MODULE}.get_default_llm")
    @patch(f"{MODULE}.ainvoke_llm", new_callable=AsyncMock)
    async def test_blank_completion_returns_none(
        self, mock_ainvoke: AsyncMock, _: AsyncMock
    ) -> None:
        mock_ainvoke.return_value = AIMessage(content="   ")

        assert await describe_image(IMAGE_B64, MIME, PROMPT) is None

    @patch(f"{MODULE}.get_default_llm")
    @patch(f"{MODULE}.ainvoke_llm", new_callable=AsyncMock)
    async def test_custom_label_is_forwarded(self, mock_ainvoke: AsyncMock, _: AsyncMock) -> None:
        mock_ainvoke.return_value = AIMessage(content="ok")

        await describe_image(IMAGE_B64, MIME, PROMPT, label="screenshot_lane")

        assert mock_ainvoke.await_args.kwargs["label"] == "screenshot_lane"
