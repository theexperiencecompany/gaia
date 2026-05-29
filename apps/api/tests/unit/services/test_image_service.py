"""Unit tests for image service operations.

Behavior spec (drives every test below; each MUST-CATCH maps to >=1 killed mutant):

UNIT: app/services/image_service.py :: generate_public_id
EXPECTED: slugify lowercased text (spaces -> '-', strip non [a-z0-9-]), truncate the
          slug to max_length chars, append a fresh 8-char uuid hex suffix, wrapped as
          "generated_image_<slug>_<suffix>".
MECHANISM: re.sub spaces->'-'; re.sub strip; slug[:max_length]; uuid.uuid4().hex[:8].
MUST-CATCH:
  - slug is truncated at exactly max_length (default 50) chars  [L17 default, L20 slice]
  - suffix is exactly 8 hex chars                                [L21 hex[:8]]
  - special chars stripped, text lowercased
  - each call gets a distinct suffix (uuid, not constant)

UNIT: app/services/image_service.py :: api_generate_image
EXPECTED: optionally refine the prompt via the LLM, generate image bytes, upload to
          Cloudinary as an image, return {url, prompt(original), improved_prompt}.
MECHANISM: do_prompt_no_stream(formatted); ", ".join non-empty parts; raise on empty;
           generate_image -> bytes|{"image": bytes}; cloudinary.uploader.upload(...,
           resource_type="image", public_id=generate_public_id(message), overwrite=True);
           return secure_url + original prompt + improved_prompt(None when unchanged).
MUST-CATCH:
  - improve_prompt defaults to True (refinement runs without passing the flag)  [L25 default]
  - refined message is original + improved joined by ", "                       [L51 join]
  - improved_prompt is the joined refined text when it changed                  [L99]
  - improved_prompt is None when refinement leaves the text unchanged           [L99 ==]
  - upload is called with resource_type="image" and overwrite=True              [L86/L88]
  - public_id is derived from the (refined) message, not a constant             [L87]
  - dict return with bytes "image" key is uploaded; missing/invalid -> 500      [L74/L77]
  - non-bytes / non-dict return -> 500                                          [L82]
  - any failure (LLM/generate/upload) -> HTTPException(500, "Internal Server Error")
EQUIVALENT MUTANTS (justified survivors): the two ValueError *message* strings
  (L63, L77) are caught by the outer except and re-raised as HTTPException(500);
  the message text never reaches the caller, so blanking it preserves behavior.

UNIT: app/services/image_service.py :: image_to_text_endpoint
EXPECTED: convert the uploaded image to text, return {"response": text}; on any error
          raise HTTPException(500, "Internal Server Error").
MECHANISM: convert_image_to_text(file, message); return {"response": response}.
MUST-CATCH:
  - the converter receives (file, message) in that order
  - the returned dict carries the converter's text under "response"
  - converter failure -> HTTPException(500, "Internal Server Error")

UNIT: app/services/image_service.py :: generate_image_stream
EXPECTED: SSE generator yielding exactly: a generating-status frame, an image_data
          frame (or an error frame), then [DONE]. Each frame is "data: <json>\n\n".
MECHANISM: yield status; api_generate_image(query); yield image_data; yield [DONE];
           on exception yield error frame then [DONE].
MUST-CATCH:
  - first frame is exactly 'data: {"status": "generating_image"}\n\n'
  - success second frame is 'data: {"image_data": <result>}\n\n' carrying the result
  - terminator frame is exactly 'data: [DONE]\n\n'
  - on failure the second frame carries {"error": "Failed to generate image: <err>"}
  - api_generate_image is called with the query text, not a constant
EQUIVALENT MUTANTS: none.
"""

import json
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi import HTTPException, UploadFile
import pytest

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
    def test_slugifies_lowercases_and_appends_8_char_suffix(self):
        result = generate_public_id("A Beautiful Sunset")

        assert result.startswith("generated_image_a-beautiful-sunset_")
        # suffix is exactly the uuid hex[:8] slice
        suffix = result.rsplit("_", 1)[-1]
        assert len(suffix) == 8
        assert all(c in "0123456789abcdef" for c in suffix)

    def test_strips_non_alphanumeric_characters(self):
        result = generate_public_id("Hello! @World #2024")

        # spaces -> '-', then everything outside [a-z0-9-] dropped
        slug = result[len("generated_image_") :].rsplit("_", 1)[0]
        assert slug == "hello-world-2024"

    def test_truncates_slug_to_default_max_length_of_50(self):
        long_text = "a" * 80
        result = generate_public_id(long_text)

        slug = result[len("generated_image_") :].rsplit("_", 1)[0]
        # default max_length is 50: slug must be cut to exactly 50, not 51+
        assert len(slug) == 50

    def test_respects_custom_max_length(self):
        result = generate_public_id("b" * 80, max_length=10)

        slug = result[len("generated_image_") :].rsplit("_", 1)[0]
        assert len(slug) == 10

    def test_empty_text_produces_empty_slug(self):
        result = generate_public_id("")

        slug = result[len("generated_image_") :].rsplit("_", 1)[0]
        assert slug == ""

    def test_each_call_has_a_distinct_suffix(self):
        id1 = generate_public_id("same text")
        id2 = generate_public_id("same text")

        assert id1 != id2
        assert id1.rsplit("_", 1)[-1] != id2.rsplit("_", 1)[-1]


# ---------------------------------------------------------------------------
# api_generate_image
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestApiGenerateImage:
    async def test_refines_prompt_by_default_and_joins_with_original(self):
        """improve_prompt defaults to True: the LLM refinement runs and the
        refined text is the original joined to the LLM response by ', '."""
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
            ) as mock_generate,
            patch(
                "app.services.image_service.cloudinary.uploader.upload",
                return_value={"secure_url": "https://cdn.example.com/image.png"},
            ),
        ):
            # called WITHOUT improve_prompt to pin the default to True
            result = await api_generate_image("sunset")

        assert result["url"] == "https://cdn.example.com/image.png"
        assert result["prompt"] == "sunset"
        assert result["improved_prompt"] == "sunset, enhanced artistic sunset"
        # the refined (joined) text is what gets handed to image generation
        mock_generate.assert_awaited_once_with("sunset, enhanced artistic sunset")

    async def test_uploads_bytes_to_cloudinary_as_image_with_refined_public_id(self):
        with (
            patch(
                "app.services.image_service.do_prompt_no_stream",
                new_callable=AsyncMock,
                return_value={"response": "vivid"},
            ),
            patch(
                "app.services.image_service.generate_image",
                new_callable=AsyncMock,
                return_value=b"fake_image_bytes",
            ),
            patch(
                "app.services.image_service.cloudinary.uploader.upload",
                return_value={"secure_url": "https://cdn.example.com/image.png"},
            ) as mock_upload,
        ):
            await api_generate_image("a cat")

        _, kwargs = mock_upload.call_args
        assert kwargs["resource_type"] == "image"
        assert kwargs["overwrite"] is True
        # public_id derives from the refined message ("a cat, vivid"), not a constant
        assert kwargs["public_id"].startswith("generated_image_a-cat-vivid_")

    async def test_skips_refinement_when_improve_prompt_false(self):
        with (
            patch(
                "app.services.image_service.do_prompt_no_stream",
                new_callable=AsyncMock,
            ) as mock_refine,
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

        mock_refine.assert_not_awaited()
        assert result["url"] == "https://cdn.example.com/img.png"
        assert result["prompt"] == "a cat"
        assert result["improved_prompt"] is None

    async def test_extracts_bytes_from_dict_return_with_image_key(self):
        with (
            patch(
                "app.services.image_service.generate_image",
                new_callable=AsyncMock,
                return_value={"image": b"raw_bytes_data"},
            ),
            patch(
                "app.services.image_service.cloudinary.uploader.upload",
                return_value={"secure_url": "https://cdn.example.com/dict.png"},
            ),
        ):
            result = await api_generate_image("test", improve_prompt=False)

        assert result["url"] == "https://cdn.example.com/dict.png"

    async def test_raises_500_when_dict_return_lacks_bytes_image(self):
        with patch(
            "app.services.image_service.generate_image",
            new_callable=AsyncMock,
            return_value={"image": "not-bytes"},
        ):
            with pytest.raises(HTTPException) as exc_info:
                await api_generate_image("test", improve_prompt=False)

        assert exc_info.value.status_code == 500
        assert exc_info.value.detail == "Internal Server Error"

    async def test_raises_500_on_unexpected_return_type(self):
        with patch(
            "app.services.image_service.generate_image",
            new_callable=AsyncMock,
            return_value=12345,
        ):
            with pytest.raises(HTTPException) as exc_info:
                await api_generate_image("test", improve_prompt=False)

        assert exc_info.value.status_code == 500
        assert exc_info.value.detail == "Internal Server Error"

    async def test_raises_500_when_image_generation_fails(self):
        with patch(
            "app.services.image_service.generate_image",
            new_callable=AsyncMock,
            side_effect=Exception("GPU error"),
        ):
            with pytest.raises(HTTPException) as exc_info:
                await api_generate_image("test", improve_prompt=False)

        assert exc_info.value.status_code == 500
        assert exc_info.value.detail == "Internal Server Error"

    async def test_raises_500_when_refined_prompt_is_empty(self):
        """Empty message + empty LLM response collapses the refined text to '';
        the empty-guard raises, which surfaces as a 500."""
        with patch(
            "app.services.image_service.do_prompt_no_stream",
            new_callable=AsyncMock,
            return_value={"response": ""},
        ):
            with pytest.raises(HTTPException) as exc_info:
                await api_generate_image("", improve_prompt=True)

        assert exc_info.value.status_code == 500
        assert exc_info.value.detail == "Internal Server Error"

    async def test_improved_prompt_is_none_when_refinement_unchanged(self):
        """Empty LLM response leaves refined text == original message, so
        improved_prompt resolves to None even though refinement ran."""
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
            result = await api_generate_image("hello", improve_prompt=True)

        assert result["prompt"] == "hello"
        assert result["improved_prompt"] is None


# ---------------------------------------------------------------------------
# image_to_text_endpoint
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestImageToTextEndpoint:
    async def test_returns_converter_text_under_response_key(self):
        mock_file = MagicMock(spec=UploadFile)

        with patch(
            "app.services.image_service.convert_image_to_text",
            new_callable=AsyncMock,
            return_value="A photo of a cat",
        ) as mock_convert:
            result = await image_to_text_endpoint("Describe this image", mock_file)

        assert result == {"response": "A photo of a cat"}
        # converter receives (file, message) in that order
        mock_convert.assert_awaited_once_with(mock_file, "Describe this image")

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
        assert exc_info.value.detail == "Internal Server Error"


# ---------------------------------------------------------------------------
# generate_image_stream
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestGenerateImageStream:
    async def test_streams_status_then_image_data_then_done(self):
        image_result = {
            "url": "https://cdn.example.com/img.png",
            "prompt": "sunset",
            "improved_prompt": "golden sunset",
        }
        with patch(
            "app.services.image_service.api_generate_image",
            new_callable=AsyncMock,
            return_value=image_result,
        ) as mock_generate:
            chunks = [chunk async for chunk in generate_image_stream("sunset")]

        # exact SSE framing is the frontend contract: "data: <json>\n\n"
        assert chunks == [
            f"data: {json.dumps({'status': 'generating_image'})}\n\n",
            f"data: {json.dumps({'image_data': image_result})}\n\n",
            "data: [DONE]\n\n",
        ]
        mock_generate.assert_awaited_once_with("sunset")

    async def test_streams_status_then_error_then_done_on_failure(self):
        with patch(
            "app.services.image_service.api_generate_image",
            new_callable=AsyncMock,
            side_effect=Exception("generation failed"),
        ):
            chunks = [chunk async for chunk in generate_image_stream("fail")]

        assert chunks == [
            f"data: {json.dumps({'status': 'generating_image'})}\n\n",
            f"data: {json.dumps({'error': 'Failed to generate image: generation failed'})}\n\n",
            "data: [DONE]\n\n",
        ]
