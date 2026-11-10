"""Unit tests for app.agents.tools.image_tool."""

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

from app.models.chat_models import ImageData

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

FAKE_USER_ID = "507f1f77bcf86cd799439011"

MODULE = "app.agents.tools.image_tool"


def _make_config(user_id: str = FAKE_USER_ID) -> dict[str, Any]:
    """Return a minimal RunnableConfig-like dict."""
    return {"metadata": {"user_id": user_id}}


def _writer_mock() -> MagicMock:
    return MagicMock()


# ---------------------------------------------------------------------------
# Tests: generate_image
# ---------------------------------------------------------------------------


class TestGenerateImage:
    """Tests for the generate_image tool."""

    @patch(f"{MODULE}.current_stream_writer")
    @patch(f"{MODULE}.api_generate_image", new_callable=AsyncMock)
    async def test_happy_path(
        self,
        mock_generate: AsyncMock,
        mock_writer_factory: MagicMock,
    ) -> None:
        """Successful image generation returns success status."""
        writer = _writer_mock()
        mock_writer_factory.return_value = writer
        mock_generate.return_value = ImageData(
            url="https://images.example.com/img.png",
            prompt="A sunset",
        )

        from app.agents.tools.image_tool import generate_image

        result = await generate_image.coroutine(
            prompt="A beautiful sunset over the ocean",
            config=_make_config(),
        )

        assert result["status"] == "success"
        assert "instructions" in result
        assert "DO NOT" in result["instructions"]
        mock_generate.assert_awaited_once_with(
            message="A beautiful sunset over the ocean",
            user_id=FAKE_USER_ID,
            improve_prompt=False,
        )

    @patch(f"{MODULE}.current_stream_writer")
    @patch(f"{MODULE}.api_generate_image", new_callable=AsyncMock)
    async def test_a_run_without_a_user_stores_nothing(
        self,
        mock_generate: AsyncMock,
        mock_writer_factory: MagicMock,
    ) -> None:
        mock_writer_factory.return_value = _writer_mock()

        from app.agents.tools.image_tool import generate_image

        result = await generate_image.coroutine(prompt="A cat", config={"metadata": {}})

        assert result["status"] == "error"
        mock_generate.assert_not_awaited()

    @patch(f"{MODULE}.current_stream_writer")
    @patch(f"{MODULE}.api_generate_image", new_callable=AsyncMock)
    async def test_streams_image_data(
        self,
        mock_generate: AsyncMock,
        mock_writer_factory: MagicMock,
    ) -> None:
        """Verifies image_data is streamed to frontend writer."""
        writer = _writer_mock()
        mock_writer_factory.return_value = writer
        mock_generate.return_value = ImageData(
            url="https://images.example.com/img.png",
            prompt="A cat",
        )

        from app.agents.tools.image_tool import generate_image

        await generate_image.coroutine(
            prompt="A cat",
            config=_make_config(),
        )

        # Expect: first call is status, second call is image_data
        calls = writer.call_args_list
        status_calls = [c for c in calls if "status" in c[0][0]]
        assert len(status_calls) >= 1
        assert status_calls[0][0][0] == {"status": "generating_image"}

        image_calls = [c for c in calls if "image_data" in c[0][0]]
        assert len(image_calls) == 1
        assert image_calls[0][0][0]["image_data"] == {
            "url": "https://images.example.com/img.png",
            "prompt": "A cat",
            "improved_prompt": None,
        }

    @patch(f"{MODULE}.current_stream_writer")
    @patch(f"{MODULE}.api_generate_image", new_callable=AsyncMock)
    async def test_api_failure_returns_error(
        self,
        mock_generate: AsyncMock,
        mock_writer_factory: MagicMock,
    ) -> None:
        """API failure returns error status with message."""
        writer = _writer_mock()
        mock_writer_factory.return_value = writer
        mock_generate.side_effect = Exception("API rate limit exceeded")

        from app.agents.tools.image_tool import generate_image

        result = await generate_image.coroutine(
            prompt="A cat",
            config=_make_config(),
        )

        assert result["status"] == "error"
        assert "API rate limit exceeded" in result["message"]

    @patch(f"{MODULE}.current_stream_writer")
    @patch(f"{MODULE}.api_generate_image", new_callable=AsyncMock)
    async def test_error_streams_error_to_writer(
        self,
        mock_generate: AsyncMock,
        mock_writer_factory: MagicMock,
    ) -> None:
        """On error, the error is also streamed to the frontend."""
        writer = _writer_mock()
        mock_writer_factory.return_value = writer
        mock_generate.side_effect = Exception("timeout")

        from app.agents.tools.image_tool import generate_image

        await generate_image.coroutine(
            prompt="A cat",
            config=_make_config(),
        )

        error_calls = [c for c in writer.call_args_list if "error" in c[0][0]]
        assert len(error_calls) == 1
        assert "timeout" in error_calls[0][0][0]["error"]

    @patch(f"{MODULE}.current_stream_writer")
    @patch(f"{MODULE}.api_generate_image", new_callable=AsyncMock)
    async def test_a_run_without_a_user_is_refused_before_generating(
        self,
        mock_generate: AsyncMock,
        mock_writer_factory: MagicMock,
    ) -> None:
        mock_writer_factory.return_value = _writer_mock()

        from app.agents.tools.image_tool import generate_image

        result = await generate_image.coroutine(prompt="A cat", config={"metadata": {}})

        assert result == {
            "status": "error",
            "message": "Error generating image: "
            "generate_image needs the run's user id to store the image",
        }
        mock_generate.assert_not_awaited()
