from collections.abc import AsyncGenerator
import io
import json
import re
import uuid

import cloudinary
import cloudinary.uploader
from fastapi import HTTPException, UploadFile

from app.agents.prompts.image_prompts import IMAGE_PROMPT_REFINER
from app.models.chat_models import ImageData
from app.models.image_models import ImageToTextResponse
from app.utils.chat_utils import do_prompt_no_stream
from app.utils.image_utils import convert_image_to_text, generate_image
from shared.py.wide_events import get_trace_id, log, log_context


def generate_public_id(refined_text: str, max_length: int = 50) -> str:
    slug = re.sub(r"\s+", "-", refined_text.lower())
    slug = re.sub(r"[^a-z0-9\-]", "", slug)
    slug = slug[:max_length]
    unique_suffix = uuid.uuid4().hex[:8]
    return f"generated_image_{slug}_{unique_suffix}"


async def api_generate_image(message: str, improve_prompt: bool = True) -> ImageData:
    """
    Generate an image based on the provided message prompt and upload it to Cloudinary.

    Args:
        message (str): The user's input prompt for image generation.
        improve_prompt (bool): Whether to improve the prompt using AI.

    Raises:
        HTTPException: If an error occurs during image generation or upload.
    """
    log.set(
        component="image_service",
        operation="generate_image",
        improve_prompt=improve_prompt,
    )
    try:
        original_message = message

        if improve_prompt:
            improved_prompt = await do_prompt_no_stream(
                prompt=IMAGE_PROMPT_REFINER.format(message=message),
            )
            refined_text = ", ".join(
                part.strip()
                for part in [
                    message or "",
                    improved_prompt.get("response", "") or "",
                ]
                if part.strip()
            )

            if not refined_text:
                log.error("Failed to generate an improved prompt.")
                raise ValueError(
                    "Failed to generate an improved prompt or fallback to the original prompt."
                )

            message = refined_text

        # Handle the case when generate_image returns a dict or bytes
        image_data = await generate_image(message)

        # Ensure we're working with bytes for the upload. generate_image only
        # ever returns a dict on the httpx failure path ({"error": str(e)});
        # bytes is the sole success shape.
        if isinstance(image_data, dict):
            raise ValueError(
                f"Failed to generate image: {image_data.get('error', 'unknown error')}"
            )
        if isinstance(image_data, bytes):
            # Already bytes, use as is
            image_bytes = image_data
        else:
            raise ValueError(f"Unexpected type from generate_image: {type(image_data)}")

        upload_result = cloudinary.uploader.upload(
            io.BytesIO(image_bytes),
            resource_type="image",
            public_id=generate_public_id(message),
            overwrite=True,
        )

        image_url = upload_result.get("secure_url")
        log.info("Image uploaded successfully. URL", image_url=image_url)

        return ImageData(
            url=image_url,
            prompt=original_message,
            improved_prompt=(message if improve_prompt and original_message != message else None),
        )

    except Exception as e:
        log.error(
            "Error occurred while processing image generation",
            error=str(e),
            error_type=type(e).__name__,
        )
        # No explicit detail: Starlette fills it from the status phrase, which
        # for 500 is the exact same "Internal Server Error" string.
        raise HTTPException(status_code=500) from e


async def image_to_text_endpoint(message: str, file: UploadFile) -> ImageToTextResponse:
    """Describe an uploaded image, answering ``message`` about it."""
    log.set(component="image_service", operation="image_to_text")
    try:
        response = await convert_image_to_text(file, message)
        log.set(outcome="success")
        return ImageToTextResponse(response=response)

    except HTTPException:
        # An unreadable upload is the caller's problem, not a 500 — let the
        # status the conversion chose reach them.
        raise
    except Exception as e:
        log.error(
            "Error occurred while processing image-to-text",
            error=str(e),
            error_type=type(e).__name__,
        )
        # No explicit detail: Starlette fills it from the status phrase, which
        # for 500 is the exact same "Internal Server Error" string.
        raise HTTPException(status_code=500) from e


async def generate_image_stream(query_text: str) -> AsyncGenerator[str, None]:
    """
    Create a streaming generator for image generation responses.
    This generator yields data in the format expected by the frontend
    for image generation results.

    Args:
        query_text (str): The user's text prompt for image generation

    Yields:
        str: Formatted response lines for streaming

    The body runs while the response streams — after the request's
    ``http_request`` event has emitted — so it needs its own boundary or the
    generation outcome is silently discarded. The generator body inherits the
    request's context, so ``get_trace_id()`` still returns the request's
    trace_id.
    """
    async with log_context(
        "image_generation_stream",
        trace_id=get_trace_id() or None,
        prompt_length=len(query_text),
    ):
        try:
            yield f"data: {json.dumps({'status': 'generating_image'})}\n\n"

            # Get image result with the new structure
            image_result = await api_generate_image(query_text)

            # Format the response to match the expected frontend format
            yield f"data: {json.dumps({'image_data': image_result.model_dump()})}\n\n"
            yield "data: [DONE]\n\n"
        except Exception as e:
            log.error("Error generating image", error=str(e), error_type=type(e).__name__)
            yield f"data: {json.dumps({'error': f'Failed to generate image: {e!s}'})}\n\n"
            yield "data: [DONE]\n\n"
