"""Unit tests for image service operations.

The seams are the AI/upload/logging boundaries: do_prompt_no_stream,
generate_image, cloudinary.uploader.upload, convert_image_to_text, log,
log_context, get_trace_id, and uuid are mocked — the service's own logic
(slug building, refined-text composition, error mapping, stream framing)
runs for real. Tests pin exact values: upload kwargs, refined prompts,
public ids, HTTPException status/detail, and every log line.
"""

import io
from unittest.mock import AsyncMock, MagicMock, call, patch

from fastapi import HTTPException, UploadFile
import pytest

from app.agents.prompts.image_prompts import IMAGE_PROMPT_REFINER
from app.models.chat_models import ImageData
from app.services.image_service import (
    api_generate_image,
    generate_image_stream,
    generate_public_id,
    image_to_text_endpoint,
)

FIXED_UUID_HEX = "1234567890abcdef1234567890abcdef"


def patch_uuid() -> MagicMock:
    """Pin ``uuid.uuid4().hex[:8]`` so public ids are fully deterministic."""
    uuid4 = MagicMock()
    uuid4.hex = FIXED_UUID_HEX
    return patch("app.services.image_service.uuid.uuid4", return_value=uuid4)


def make_log_context() -> MagicMock:
    """A log_context mock that supports ``async with``."""
    log_context = MagicMock()
    log_context.return_value.__aenter__ = AsyncMock()
    log_context.return_value.__aexit__ = AsyncMock()
    return log_context


# ---------------------------------------------------------------------------
# generate_public_id
# ---------------------------------------------------------------------------


class TestGeneratePublicId:
    def test_basic_slug_generation(self):
        with patch_uuid():
            result = generate_public_id("A beautiful sunset")

        assert result == "generated_image_a-beautiful-sunset_12345678"

    def test_removes_special_characters(self):
        with patch_uuid():
            result = generate_public_id("Hello! @World #2024")

        assert result == "generated_image_hello-world-2024_12345678"

    def test_truncates_long_slugs(self):
        with patch_uuid():
            result = generate_public_id("a" * 100, max_length=50)

        assert result == "generated_image_" + ("a" * 50) + "_12345678"

    def test_default_max_length_truncates(self):
        # The default max_length is 50 — a caller relying on it gets a
        # 50-char slug, not the full input.
        with patch_uuid():
            result = generate_public_id("b" * 100)

        assert result == "generated_image_" + ("b" * 50) + "_12345678"

    def test_handles_empty_string(self):
        with patch_uuid():
            result = generate_public_id("")

        assert result == "generated_image__12345678"

    def test_handles_whitespace_only(self):
        # Whitespace collapses to a single dash before the character filter runs,
        # so the dash survives into the slug.
        with patch_uuid():
            result = generate_public_id("   ")

        assert result == "generated_image_-_12345678"

    def test_unique_ids_each_call(self):
        id1 = generate_public_id("same text")
        id2 = generate_public_id("same text")
        assert id1 != id2

    def test_lowercases_text(self):
        with patch_uuid():
            result = generate_public_id("UPPERCASE")

        assert result == "generated_image_uppercase_12345678"


# ---------------------------------------------------------------------------
# api_generate_image
# ---------------------------------------------------------------------------


class TestApiGenerateImage:
    async def test_generates_image_with_improved_prompt(self):
        refined_text = "sunset, enhanced artistic sunset"
        with (
            patch("app.services.image_service.log") as mock_log,
            patch_uuid(),
            patch(
                "app.services.image_service.do_prompt_no_stream",
                new_callable=AsyncMock,
                return_value={"response": "enhanced artistic sunset"},
            ) as do_prompt,
            patch(
                "app.services.image_service.generate_image",
                new_callable=AsyncMock,
                return_value=b"fake_image_bytes",
            ) as generate,
            patch(
                "app.services.image_service.cloudinary.uploader.upload",
                return_value={"secure_url": "https://cdn.example.com/image.png"},
            ) as upload,
        ):
            result = await api_generate_image("sunset", improve_prompt=True)

        assert result.url == "https://cdn.example.com/image.png"
        assert result.prompt == "sunset"
        assert result.improved_prompt == refined_text
        mock_log.set.assert_called_once_with(
            component="image_service", operation="generate_image", improve_prompt=True
        )
        do_prompt.assert_awaited_once_with(prompt=IMAGE_PROMPT_REFINER.format(message="sunset"))
        generate.assert_awaited_once_with(refined_text)
        upload.assert_called_once()
        args, kwargs = upload.call_args
        assert isinstance(args[0], io.BytesIO)
        assert args[0].getvalue() == b"fake_image_bytes"
        assert kwargs == {
            "resource_type": "image",
            "public_id": "generated_image_sunset-enhanced-artistic-sunset_12345678",
            "overwrite": True,
        }
        mock_log.info.assert_called_once_with(
            "Image uploaded successfully. URL", image_url="https://cdn.example.com/image.png"
        )

    async def test_generates_image_without_prompt_improvement(self):
        with (
            patch("app.services.image_service.log") as mock_log,
            patch_uuid(),
            patch(
                "app.services.image_service.do_prompt_no_stream",
                new_callable=AsyncMock,
            ) as do_prompt,
            patch(
                "app.services.image_service.generate_image",
                new_callable=AsyncMock,
                return_value=b"fake_bytes",
            ) as generate,
            patch(
                "app.services.image_service.cloudinary.uploader.upload",
                return_value={"secure_url": "https://cdn.example.com/img.png"},
            ) as upload,
        ):
            result = await api_generate_image("a cat", improve_prompt=False)

        assert result.url == "https://cdn.example.com/img.png"
        assert result.prompt == "a cat"
        assert result.improved_prompt is None
        mock_log.set.assert_called_once_with(
            component="image_service", operation="generate_image", improve_prompt=False
        )
        do_prompt.assert_not_awaited()
        generate.assert_awaited_once_with("a cat")
        upload.assert_called_once()
        args, kwargs = upload.call_args
        assert args[0].getvalue() == b"fake_bytes"
        assert kwargs == {
            "resource_type": "image",
            "public_id": "generated_image_a-cat_12345678",
            "overwrite": True,
        }
        mock_log.info.assert_called_once_with(
            "Image uploaded successfully. URL", image_url="https://cdn.example.com/img.png"
        )

    async def test_improve_prompt_defaults_to_true(self):
        with (
            patch("app.services.image_service.log"),
            patch(
                "app.services.image_service.do_prompt_no_stream",
                new_callable=AsyncMock,
                return_value={"response": "refined"},
            ) as do_prompt,
            patch(
                "app.services.image_service.generate_image",
                new_callable=AsyncMock,
                return_value=b"bytes",
            ),
            patch(
                "app.services.image_service.cloudinary.uploader.upload",
                return_value={"secure_url": "https://cdn.example.com/x.png"},
            ),
        ):
            await api_generate_image("sunset")

        do_prompt.assert_awaited_once()

    async def test_improved_prompt_is_none_when_unchanged(self):
        """When the refined text equals the original, improved_prompt should be None."""
        with (
            patch("app.services.image_service.log"),
            patch(
                "app.services.image_service.do_prompt_no_stream",
                new_callable=AsyncMock,
                return_value={"response": ""},
            ),
            patch(
                "app.services.image_service.generate_image",
                new_callable=AsyncMock,
                return_value=b"bytes",
            ) as generate,
            patch(
                "app.services.image_service.cloudinary.uploader.upload",
                return_value={"secure_url": "https://cdn.example.com/same.png"},
            ),
        ):
            # message is "hello" and response is empty, so refined = "hello"
            # which equals original, so improved_prompt should be None
            result = await api_generate_image("hello", improve_prompt=True)

        assert result.improved_prompt is None
        assert result.prompt == "hello"
        generate.assert_awaited_once_with("hello")

    async def test_response_key_missing_falls_back_to_message(self):
        # The refiner response is read with a default — a missing "response"
        # key must not leak anything into the refined text.
        with (
            patch("app.services.image_service.log"),
            patch(
                "app.services.image_service.do_prompt_no_stream",
                new_callable=AsyncMock,
                return_value={"other": "ignored"},
            ),
            patch(
                "app.services.image_service.generate_image",
                new_callable=AsyncMock,
                return_value=b"bytes",
            ) as generate,
            patch(
                "app.services.image_service.cloudinary.uploader.upload",
                return_value={"secure_url": "https://cdn.example.com/x.png"},
            ),
        ):
            result = await api_generate_image("hello", improve_prompt=True)

        assert result.prompt == "hello"
        assert result.improved_prompt is None
        generate.assert_awaited_once_with("hello")

    async def test_raises_500_on_error_dict_with_message(self):
        with (
            patch("app.services.image_service.log") as mock_log,
            patch(
                "app.services.image_service.generate_image",
                new_callable=AsyncMock,
                return_value={"error": "boom"},
            ),
        ):
            with pytest.raises(HTTPException) as exc_info:
                await api_generate_image("test", improve_prompt=False)

            assert exc_info.value.status_code == 500
            assert exc_info.value.detail == "Internal Server Error"
        mock_log.error.assert_called_once_with(
            "Error occurred while processing image generation",
            error="Failed to generate image: boom",
            error_type="ValueError",
        )

    async def test_raises_500_on_error_dict_without_message(self):
        with (
            patch("app.services.image_service.log") as mock_log,
            patch(
                "app.services.image_service.generate_image",
                new_callable=AsyncMock,
                return_value={"no_image_key": "data"},
            ),
        ):
            with pytest.raises(HTTPException) as exc_info:
                await api_generate_image("test", improve_prompt=False)

            assert exc_info.value.status_code == 500
            assert exc_info.value.detail == "Internal Server Error"
        mock_log.error.assert_called_once_with(
            "Error occurred while processing image generation",
            error="Failed to generate image: unknown error",
            error_type="ValueError",
        )

    async def test_raises_500_on_unexpected_type(self):
        with (
            patch("app.services.image_service.log") as mock_log,
            patch(
                "app.services.image_service.generate_image",
                new_callable=AsyncMock,
                return_value=12345,
            ),
        ):
            with pytest.raises(HTTPException) as exc_info:
                await api_generate_image("test", improve_prompt=False)

            assert exc_info.value.status_code == 500
            assert exc_info.value.detail == "Internal Server Error"
        mock_log.error.assert_called_once_with(
            "Error occurred while processing image generation",
            error="Unexpected type from generate_image: <class 'int'>",
            error_type="ValueError",
        )

    async def test_raises_500_on_generation_error(self):
        with (
            patch("app.services.image_service.log") as mock_log,
            patch(
                "app.services.image_service.generate_image",
                new_callable=AsyncMock,
                side_effect=Exception("GPU error"),
            ),
        ):
            with pytest.raises(HTTPException) as exc_info:
                await api_generate_image("test", improve_prompt=False)

            assert exc_info.value.status_code == 500
            assert exc_info.value.detail == "Internal Server Error"
        mock_log.error.assert_called_once_with(
            "Error occurred while processing image generation",
            error="GPU error",
            error_type="Exception",
        )

    async def test_raises_when_improved_prompt_is_empty(self):
        """When both message and improved prompt resolve to empty, should raise."""
        with (
            patch("app.services.image_service.log") as mock_log,
            patch(
                "app.services.image_service.do_prompt_no_stream",
                new_callable=AsyncMock,
                return_value={"response": ""},
            ),
        ):
            with pytest.raises(HTTPException) as exc_info:
                await api_generate_image("", improve_prompt=True)

            assert exc_info.value.status_code == 500
            assert exc_info.value.detail == "Internal Server Error"
        mock_log.error.assert_has_calls(
            [
                call("Failed to generate an improved prompt."),
                call(
                    "Error occurred while processing image generation",
                    error="Failed to generate an improved prompt or fallback to the original prompt.",
                    error_type="ValueError",
                ),
            ]
        )
        assert mock_log.error.call_count == 2


# ---------------------------------------------------------------------------
# image_to_text_endpoint
# ---------------------------------------------------------------------------


class TestImageToTextEndpoint:
    async def test_converts_image_to_text(self):
        mock_file = MagicMock(spec=UploadFile)
        mock_file.filename = "test.png"

        with (
            patch("app.services.image_service.log") as mock_log,
            patch(
                "app.services.image_service.convert_image_to_text",
                new_callable=AsyncMock,
                return_value="A photo of a cat",
            ) as convert,
        ):
            result = await image_to_text_endpoint("Describe this image", mock_file)

        assert result.response == "A photo of a cat"
        convert.assert_awaited_once_with(mock_file, "Describe this image")
        mock_log.set.assert_has_calls(
            [
                call(component="image_service", operation="image_to_text"),
                call(outcome="success"),
            ]
        )

    async def test_passes_through_http_exception(self):
        mock_file = MagicMock(spec=UploadFile)

        with (
            patch("app.services.image_service.log") as mock_log,
            patch(
                "app.services.image_service.convert_image_to_text",
                new_callable=AsyncMock,
                side_effect=HTTPException(status_code=422, detail="unreadable upload"),
            ),
        ):
            with pytest.raises(HTTPException) as exc_info:
                await image_to_text_endpoint("Describe", mock_file)

        assert exc_info.value.status_code == 422
        assert exc_info.value.detail == "unreadable upload"
        mock_log.error.assert_not_called()

    async def test_raises_500_on_conversion_error(self):
        mock_file = MagicMock(spec=UploadFile)

        with (
            patch("app.services.image_service.log") as mock_log,
            patch(
                "app.services.image_service.convert_image_to_text",
                new_callable=AsyncMock,
                side_effect=Exception("OCR failed"),
            ),
        ):
            with pytest.raises(HTTPException) as exc_info:
                await image_to_text_endpoint("Describe", mock_file)

            assert exc_info.value.status_code == 500
            assert exc_info.value.detail == "Internal Server Error"
        mock_log.error.assert_called_once_with(
            "Error occurred while processing image-to-text",
            error="OCR failed",
            error_type="Exception",
        )


# ---------------------------------------------------------------------------
# generate_image_stream
# ---------------------------------------------------------------------------


class TestGenerateImageStream:
    async def test_yields_generating_status_and_image_data(self):
        image_result = ImageData(
            url="https://cdn.example.com/img.png",
            prompt="sunset",
            improved_prompt="golden sunset",
        )
        log_context = make_log_context()
        with (
            patch("app.services.image_service.log_context", log_context),
            patch("app.services.image_service.get_trace_id", return_value="trace-abc"),
            patch(
                "app.services.image_service.api_generate_image",
                new_callable=AsyncMock,
                return_value=image_result,
            ) as api_generate,
        ):
            chunks = []
            async for chunk in generate_image_stream("sunset"):
                chunks.append(chunk)

        assert chunks == [
            'data: {"status": "generating_image"}\n\n',
            'data: {"image_data": {"url": "https://cdn.example.com/img.png", '
            '"prompt": "sunset", "improved_prompt": "golden sunset"}}\n\n',
            "data: [DONE]\n\n",
        ]
        api_generate.assert_awaited_once_with("sunset")
        log_context.assert_called_once_with(
            "image_generation_stream", trace_id="trace-abc", prompt_length=6
        )

    async def test_trace_id_falls_back_to_none_when_empty(self):
        log_context = make_log_context()
        with (
            patch("app.services.image_service.log_context", log_context),
            patch("app.services.image_service.get_trace_id", return_value=""),
            patch(
                "app.services.image_service.api_generate_image",
                new_callable=AsyncMock,
                return_value=ImageData(url="u", prompt="p"),
            ),
        ):
            chunks = []
            async for chunk in generate_image_stream("sunset"):
                chunks.append(chunk)

        assert chunks[-1] == "data: [DONE]\n\n"
        log_context.assert_called_once_with(
            "image_generation_stream", trace_id=None, prompt_length=6
        )

    async def test_yields_error_on_failure(self):
        log_context = make_log_context()
        with (
            patch("app.services.image_service.log_context", log_context),
            patch("app.services.image_service.get_trace_id", return_value="trace-abc"),
            patch(
                "app.services.image_service.api_generate_image",
                new_callable=AsyncMock,
                side_effect=Exception("generation failed"),
            ),
            patch("app.services.image_service.log") as mock_log,
        ):
            chunks = []
            async for chunk in generate_image_stream("fail"):
                chunks.append(chunk)

        assert chunks == [
            'data: {"status": "generating_image"}\n\n',
            'data: {"error": "Failed to generate image: generation failed"}\n\n',
            "data: [DONE]\n\n",
        ]
        mock_log.error.assert_called_once_with(
            "Error generating image", error="generation failed", error_type="Exception"
        )
