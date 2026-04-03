"""Unit tests for image service operations."""

import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi import HTTPException, UploadFile

from app.services.image_service import (
    api_generate_image,
    generate_image_stream,
    generate_public_id,
    image_to_text_endpoint,
)


# ---------------------------------------------------------------------------
# generate_public_id
# ---------------------------------------------------------------------------


@pytest.mark.unit
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


@pytest.mark.unit
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

        assert result["url"] == "https://cdn.example.com/image.png"
        assert result["prompt"] == "sunset"
        assert result["improved_prompt"] is not None

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

        assert result["url"] == "https://cdn.example.com/img.png"
        assert result["prompt"] == "a cat"
        assert result["improved_prompt"] is None

    async def test_handles_dict_return_with_image_key(self):
        image_dict = {"image": b"raw_bytes_data"}
        with (
            patch(
                "app.services.image_service.generate_image",
                new_callable=AsyncMock,
                return_value=image_dict,
            ),
            patch(
                "app.services.image_service.cloudinary.uploader.upload",
                return_value={"secure_url": "https://cdn.example.com/dict.png"},
            ),
        ):
            result = await api_generate_image("test", improve_prompt=False)

        assert result["url"] == "https://cdn.example.com/dict.png"

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

        assert result["improved_prompt"] is None


# ---------------------------------------------------------------------------
# image_to_text_endpoint
# ---------------------------------------------------------------------------


@pytest.mark.unit
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

        assert result["response"] == "A photo of a cat"

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


@pytest.mark.unit
class TestGenerateImageStream:
    async def test_yields_generating_status_and_image_data(self):
        image_result = {
            "url": "https://cdn.example.com/img.png",
            "prompt": "sunset",
            "improved_prompt": "golden sunset",
        }
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
        assert second_data["image_data"] == image_result
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
