import io
import json
import re
import uuid
from typing import AsyncGenerator

import cloudinary
import cloudinary.uploader
from fastapi import HTTPException, UploadFile

from app.config.loggers import image_logger as logger
from app.agents.prompts.image_prompts import IMAGE_PROMPT_REFINER
from app.utils.chat_utils import do_prompt_no_stream
from app.utils.image_utils import convert_image_to_text, generate_image


def generate_public_id(refined_text: str, max_length: int = 50) -> str:
    slug = re.sub(r"\s+", "-", refined_text.lower())
    slug = re.sub(r"[^a-z0-9\-]", "", slug)
    slug = slug[:max_length]
    unique_suffix = uuid.uuid4().hex[:8]
    return f"generated_image_{slug}_{unique_suffix}"


async def api_generate_image(message: str, improve_prompt=True) -> dict:
    """
    Generate an image based on the provided message prompt and upload it to Cloudinary.

    Args:
        message (str): The user's input prompt for image generation.
        improve_prompt (bool): Whether to improve the prompt using AI.

    Returns:
        dict: A dictionary containing the URL of the uploaded image and prompt information.

    Raises:
        HTTPException: If an error occurs during image generation or upload.
    """
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
                logger.error("Failed to generate an improved prompt.")
                raise ValueError(
                    "Failed to generate an improved prompt or fallback to the original prompt."
                )

            message = refined_text

        # Handle the case when generate_image returns a dict or bytes
        image_data = await generate_image(message)

        # Ensure we're working with bytes for the upload
        if isinstance(image_data, dict):
            # Handle the case when it returns a dict
            if "image" in image_data and isinstance(image_data["image"], bytes):
                image_bytes = image_data["image"]
            else:
                raise ValueError("Invalid image data returned from generate_image")
        elif isinstance(image_data, bytes):
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
        logger.info(f"Image uploaded successfully. URL: {image_url}")

        # Format the response in the new structure
        return {
            "url": image_url,
            "prompt": original_message,
            "improved_prompt": (
                message if improve_prompt and original_message != message else None
            ),
        }

    except Exception as e:
        logger.error(f"Error occurred while processing image generation: {str(e)}")
        raise HTTPException(status_code=500, detail="Internal Server Error")


async def image_to_text_endpoint(message: str, file: UploadFile) -> dict:
    """
    Convert an uploaded image to text.

    Args:
        message (str): A message accompanying the image.
        file (UploadFile): The uploaded image file.

    Returns:
        dict: A dictionary containing the extracted text from the image.

    Raises:
        HTTPException: If an error occurs during the image-to-text conversion process.
    """
    try:
        logger.info(f"Received image-to-text request with message: {message}")

        response = await convert_image_to_text(file, message)

        logger.info("Image-to-text conversion successful.")
        return {"response": response}

    except Exception as e:
        logger.error(f"Error occurred while processing image-to-text: {str(e)}")
        raise HTTPException(status_code=500, detail="Internal Server Error")


async def generate_image_stream(query_text: str) -> AsyncGenerator[str, None]:
    """
    Create a streaming generator for image generation responses.
    This generator yields data in the format expected by the frontend
    for image generation results.

    Args:
        query_text (str): The user's text prompt for image generation

    Yields:
        str: Formatted response lines for streaming
    """
    try:
        yield f"data: {json.dumps({'status': 'generating_image'})}\n\n"

        # Get image result with the new structure
        image_result = await api_generate_image(query_text)

        # Format the response to match the expected frontend format
        yield f"data: {json.dumps({'image_data': image_result})}\n\n"
        yield "data: [DONE]\n\n"
    except Exception as e:
        logger.error(f"Error generating image: {str(e)}")
        yield f"data: {json.dumps({'error': f'Failed to generate image: {str(e)}'})}\n\n"
        yield "data: [DONE]\n\n"
