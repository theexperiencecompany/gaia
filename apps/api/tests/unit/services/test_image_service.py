"""Unit tests for image service operations."""

import json
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi import HTTPException, UploadFile
import pytest

from app.models.chat_models import ImageData
from app.services.image_service import (
    api_generate_image,
    generate_image_stream,
    generate_public_id,
    image_to_text_endpoint,
)

# ---------------------------------------------------------------------------
# generate_public_id
# ---------------------------------------------------------------------------


class TestGeneratePublicId:
    def test_basic_slug_generation(self):
        result = generate_public_id("A beautiful sunset")
        assert result.startswith("generated_image_a-beautiful-sunset_")
        assert len(result.split("_")[-1]) == 8  # uuid hex suffix

    def test_removes_special_characters(self):
        result = generate_public_id("Hello! @World #2024")
        # After slugification: "hello-world-2024" (special chars removed)
        assert "!" not in result
        assert "@" not in result
        assert "#" not in result

    def test_truncates_long_slugs(self):
        long_text = "a" * 100
        result = generate_public_id(long_text, max_length=50)
        # slug portion should be limited
        prefix = "generated_image_"
        slug_and_suffix = result[len(prefix) :]
        slug = slug_and_suffix.rsplit("_", 1)[0]
        assert len(slug) <= 50

    def test_handles_empty_string(self):
        result = generate_public_id("")
        assert result.startswith("generated_image_")

    def test_handles_whitespace_only(self):
        result = generate_public_id("   ")
        assert result.startswith("generated_image_")

    def test_unique_ids_each_call(self):
        id1 = generate_public_id("same text")
        id2 = generate_public_id("same text")
        assert id1 != id2

    def test_lowercases_text(self):
        result = generate_public_id("UPPERCASE")
        assert "uppercase" in result
        assert "UPPERCASE" not in result


# ---------------------------------------------------------------------------
# api_generate_image
# ---------------------------------------------------------------------------


class TestApiGenerateImage:
    async def test_generates_image_with_improved_prompt(self):
        with (
            patch(
                "app.services.image_service.do_prompt_no_stream",
                new_callable=AsyncMock,
                return_value={"response": "enhanced artistic sunset"},
            ),
            patch(
                "app.services.image_service.generate_image",
                new_callable=AsyncMock,
                return_value=b"fake_image_bytes",
            ),
            patch(
                "app.services.image_service.cloudinary.uploader.upload",
                return_value={"secure_url": "https://cdn.example.com/image.png"},
            ),
        ):
            result = await api_generate_image("sunset", improve_prompt=True)

        assert result.url == "https://cdn.example.com/image.png"
        assert result.prompt == "sunset"
        assert result.improved_prompt is not None

    async def test_generates_image_without_prompt_improvement(self):
        with (
            patch(
                "app.services.image_service.generate_image",
                new_callable=AsyncMock,
                return_value=b"fake_bytes",
            ),
            patch(
                "app.services.image_service.cloudinary.uploader.upload",
                return_value={"secure_url": "https://cdn.example.com/img.png"},
            ),
        ):
            result = await api_generate_image("a cat", improve_prompt=False)

        assert result.url == "https://cdn.example.com/img.png"
        assert result.prompt == "a cat"
        assert result.improved_prompt is None

    async def test_raises_500_on_invalid_dict_return(self):
        with (
            patch(
                "app.services.image_service.generate_image",
                new_callable=AsyncMock,
                return_value={"no_image_key": "data"},
            ),
        ):
            with pytest.raises(HTTPException) as exc_info:
                await api_generate_image("test", improve_prompt=False)

            assert exc_info.value.status_code == 500

    async def test_raises_500_on_unexpected_type(self):
        with (
            patch(
                "app.services.image_service.generate_image",
                new_callable=AsyncMock,
                return_value=12345,
            ),
        ):
            with pytest.raises(HTTPException) as exc_info:
                await api_generate_image("test", improve_prompt=False)

            assert exc_info.value.status_code == 500

    async def test_raises_500_on_generation_error(self):
        with (
            patch(
                "app.services.image_service.generate_image",
                new_callable=AsyncMock,
                side_effect=Exception("GPU error"),
            ),
        ):
            with pytest.raises(HTTPException) as exc_info:
                await api_generate_image("test", improve_prompt=False)

            assert exc_info.value.status_code == 500
            # The body reaches the client; pin it, not just the status.
            assert exc_info.value.detail == "Internal Server Error"
            assert isinstance(exc_info.value.__cause__, Exception)

    async def test_raises_when_improved_prompt_is_empty(self):
        """When both message and improved prompt resolve to empty, should raise."""
        with (
            patch(
                "app.services.image_service.do_prompt_no_stream",
                new_callable=AsyncMock,
                return_value={"response": ""},
            ),
        ):
            with pytest.raises(HTTPException) as exc_info:
                await api_generate_image("", improve_prompt=True)

            assert exc_info.value.status_code == 500

    async def test_improved_prompt_is_none_when_unchanged(self):
        """When the refined text equals the original, improved_prompt should be None."""
        with (
            patch(
                "app.services.image_service.do_prompt_no_stream",
                new_callable=AsyncMock,
                return_value={"response": ""},
            ),
            patch(
                "app.services.image_service.generate_image",
                new_callable=AsyncMock,
                return_value=b"bytes",
            ),
            patch(
                "app.services.image_service.cloudinary.uploader.upload",
                return_value={"secure_url": "https://cdn.example.com/same.png"},
            ),
        ):
            # message is "hello" and response is empty, so refined = "hello"
            # which equals original, so improved_prompt should be None
            result = await api_generate_image("hello", improve_prompt=True)

        assert result.improved_prompt is None


# ---------------------------------------------------------------------------
# image_to_text_endpoint
# ---------------------------------------------------------------------------


class TestImageToTextEndpoint:
    async def test_converts_image_to_text(self):
        mock_file = MagicMock(spec=UploadFile)
        mock_file.filename = "test.png"

        with patch(
            "app.services.image_service.convert_image_to_text",
            new_callable=AsyncMock,
            return_value="A photo of a cat",
        ):
            result = await image_to_text_endpoint("Describe this image", mock_file)

        assert result.response == "A photo of a cat"

    async def test_raises_500_on_conversion_error(self):
        mock_file = MagicMock(spec=UploadFile)

        with patch(
            "app.services.image_service.convert_image_to_text",
            new_callable=AsyncMock,
            side_effect=Exception("OCR failed"),
        ):
            with pytest.raises(HTTPException) as exc_info:
                await image_to_text_endpoint("Describe", mock_file)

            assert exc_info.value.status_code == 500


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
        with patch(
            "app.services.image_service.api_generate_image",
            new_callable=AsyncMock,
            return_value=image_result,
        ):
            chunks = []
            async for chunk in generate_image_stream("sunset"):
                chunks.append(chunk)

        assert len(chunks) == 3
        # First chunk: generating status
        first_data = json.loads(chunks[0].replace("data: ", "").strip())
        assert first_data["status"] == "generating_image"
        # Second chunk: image data
        second_data = json.loads(chunks[1].replace("data: ", "").strip())
        assert second_data["image_data"] == {
            "url": "https://cdn.example.com/img.png",
            "prompt": "sunset",
            "improved_prompt": "golden sunset",
        }
        # Third chunk: DONE
        assert "[DONE]" in chunks[2]

    async def test_yields_error_on_failure(self):
        with patch(
            "app.services.image_service.api_generate_image",
            new_callable=AsyncMock,
            side_effect=Exception("generation failed"),
        ):
            chunks = []
            async for chunk in generate_image_stream("fail"):
                chunks.append(chunk)

        assert len(chunks) == 3
        # First chunk: generating status
        first_data = json.loads(chunks[0].replace("data: ", "").strip())
        assert first_data["status"] == "generating_image"
        # Second chunk: error
        error_data = json.loads(chunks[1].replace("data: ", "").strip())
        assert "error" in error_data
        assert "generation failed" in error_data["error"]
        # Third chunk: DONE
        assert "[DONE]" in chunks[2]


class TestApiGenerateImagePins:
    async def test_log_context_and_upload_kwargs_are_exact(self):
        with (
            patch("app.services.image_service.log") as log,
            patch(
                "app.services.image_service.generate_image",
                new_callable=AsyncMock,
                return_value=b"img",
            ),
            patch(
                "app.services.image_service.cloudinary.uploader.upload",
                return_value={"secure_url": "https://cdn.example.com/img.png"},
            ) as upload,
        ):
            await api_generate_image("a cat", improve_prompt=False)

        log.set.assert_called_once_with(
            component="image_service", operation="generate_image", improve_prompt=False
        )
        kwargs = upload.call_args.kwargs  # uploader.upload is synchronous
        assert kwargs["resource_type"] == "image"
        assert kwargs["overwrite"] is True
        # generate_public_id embeds a random suffix; pin only its stable part.
        assert kwargs["public_id"].startswith("generated_image_a-cat_")
        log.info.assert_called_once_with(
            "Image uploaded successfully. URL", image_url="https://cdn.example.com/img.png"
        )

    async def test_dict_error_result_names_the_missing_image_in_the_cause(self):
        with (
            patch(
                "app.services.image_service.generate_image",
                new_callable=AsyncMock,
                return_value={"no_image_key": "data"},
            ),
        ):
            with pytest.raises(HTTPException) as exc_info:
                await api_generate_image("test", improve_prompt=False)

        assert exc_info.value.status_code == 500
        assert isinstance(exc_info.value.__cause__, ValueError)
        assert "Failed to generate image" in str(exc_info.value.__cause__)

    async def test_improved_prompt_carries_the_refined_text(self):
        with (
            patch(
                "app.services.image_service.do_prompt_no_stream",
                new_callable=AsyncMock,
                return_value={"response": "a watercolor cat"},
            ),
            patch(
                "app.services.image_service.generate_image",
                new_callable=AsyncMock,
                return_value=b"img",
            ),
            patch(
                "app.services.image_service.cloudinary.uploader.upload",
                return_value={"secure_url": "https://cdn.example.com/img.png"},
            ),
        ):
            result = await api_generate_image("a cat", improve_prompt=True)

        # refined text is "<original>, <improvement>" — both parts stripped+joined
        assert result.improved_prompt == "a cat, a watercolor cat"
        assert result.prompt == "a cat"


class TestImageToTextEndpointPins:
    async def test_success_response_and_log_are_exact(self):
        upload = MagicMock(spec=UploadFile)
        with (
            patch("app.services.image_service.log") as log,
            patch(
                "app.services.image_service.convert_image_to_text",
                new_callable=AsyncMock,
                return_value="a red bicycle",
            ) as convert,
        ):
            response = await image_to_text_endpoint("what is this?", upload)

        assert response.response == "a red bicycle"
        convert.assert_awaited_once_with(upload, "what is this?")
        log.set.assert_any_call(component="image_service", operation="image_to_text")
        log.set.assert_any_call(outcome="success")

    async def test_http_exception_passes_through_unwrapped(self):
        upload = MagicMock(spec=UploadFile)
        original = HTTPException(status_code=415, detail="unsupported media")
        with patch(
            "app.services.image_service.convert_image_to_text",
            new_callable=AsyncMock,
            side_effect=original,
        ):
            with pytest.raises(HTTPException) as exc_info:
                await image_to_text_endpoint("q", upload)

        assert exc_info.value is original

    async def test_unexpected_error_raises_500_with_exact_log(self):
        upload = MagicMock(spec=UploadFile)
        with (
            patch("app.services.image_service.log") as log,
            patch(
                "app.services.image_service.convert_image_to_text",
                new_callable=AsyncMock,
                side_effect=RuntimeError("vision down"),
            ),
        ):
            with pytest.raises(HTTPException) as exc_info:
                await image_to_text_endpoint("q", upload)

        assert exc_info.value.status_code == 500
        assert exc_info.value.detail == "Internal Server Error"
        assert isinstance(exc_info.value.__cause__, RuntimeError)
        log.error.assert_called_once_with(
            "Error occurred while processing image-to-text",
            error="vision down",
            error_type="RuntimeError",
        )
