"""Unit tests for app.agents.tools.image_tool."""

from typing import Any, Dict
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

FAKE_USER_ID = "507f1f77bcf86cd799439011"

MODULE = "app.agents.tools.image_tool"


def _make_config(user_id: str = FAKE_USER_ID) -> Dict[str, Any]:
    """Return a minimal RunnableConfig-like dict."""
    return {"metadata": {"user_id": user_id}}


def _writer_mock() -> MagicMock:
    return MagicMock()


# ---------------------------------------------------------------------------
# Tests: generate_image
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestGenerateImage:
    """Tests for the generate_image tool."""

    @patch(f"{MODULE}.get_stream_writer")
    @patch(f"{MODULE}.api_generate_image", new_callable=AsyncMock)
    async def test_happy_path(
        self,
        mock_generate: AsyncMock,
        mock_writer_factory: MagicMock,
    ) -> None:
        """Successful image generation returns success status."""
        writer = _writer_mock()
        mock_writer_factory.return_value = writer
        mock_generate.return_value = {
            "url": "https://images.example.com/img.png",
            "prompt": "A sunset",
        }

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
            improve_prompt=False,
        )

    @patch(f"{MODULE}.get_stream_writer")
    @patch(f"{MODULE}.api_generate_image", new_callable=AsyncMock)
    async def test_streams_image_data(
        self,
        mock_generate: AsyncMock,
        mock_writer_factory: MagicMock,
    ) -> None:
        """Verifies image_data is streamed to frontend writer."""
        writer = _writer_mock()
        mock_writer_factory.return_value = writer
        image_result = {"url": "https://images.example.com/img.png"}
        mock_generate.return_value = image_result

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
        assert image_calls[0][0][0]["image_data"] == image_result

    @patch(f"{MODULE}.get_stream_writer")
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

    @patch(f"{MODULE}.get_stream_writer")
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
