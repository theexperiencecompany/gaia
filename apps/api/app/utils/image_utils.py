import base64

from fastapi import HTTPException, UploadFile
import httpx
from openai import AsyncOpenAI

from app.agents.llm.vision import describe_image
from app.agents.prompts.image_prompts import IMAGE_TO_TEXT_PROMPT
from app.config.settings import settings
from app.constants.llm import (
    HOSTED_IMAGE_GENERATION_URL,
    IMAGE_GENERATION_TIMEOUT_SECONDS,
    OPENAI_IMAGE_MODEL_NAME,
    OPENAI_IMAGE_SIZE,
)
from app.constants.media import MAX_IMAGE_FILE_BYTES
from app.services.providers.provider_credentials_service import ProviderConfig, resolve
from app.utils.image_codec import ImageCodec, InvalidImageError

http_async_client = httpx.AsyncClient(timeout=IMAGE_GENERATION_TIMEOUT_SECONDS)

IMAGE_GENERATION_NOT_CONFIGURED_MESSAGE = (
    "Image generation is not configured. Add an OpenAI API key in Settings → AI Providers."
)


class ImageGenerationNotConfiguredError(RuntimeError):
    """No image generator can serve this instance: outside production, no OpenAI key."""


async def generate_image(imageprompt: str) -> bytes:
    """Generate an image: GAIA's hosted generator in production, the operator's OpenAI key elsewhere.

    Raises ImageGenerationNotConfiguredError without an OpenAI key outside
    production; provider failures propagate.
    """
    if settings.deployment.hosted_models:
        response = await http_async_client.post(
            HOSTED_IMAGE_GENERATION_URL, json={"imageprompt": imageprompt}
        )
        response.raise_for_status()
        return response.content
    config: ProviderConfig | None = await resolve("openai")
    if config is None or not config.api_key:
        raise ImageGenerationNotConfiguredError(IMAGE_GENERATION_NOT_CONFIGURED_MESSAGE)
    result = await AsyncOpenAI(api_key=config.api_key).images.generate(
        model=OPENAI_IMAGE_MODEL_NAME, prompt=imageprompt, size=OPENAI_IMAGE_SIZE
    )
    encoded = result.data[0].b64_json if result.data else None
    if not encoded:
        raise ValueError("OpenAI image generation returned no image data")
    return base64.b64decode(encoded)


async def convert_image_to_text(image: UploadFile, message: str, user_id: str) -> str:
    """Answer message about an uploaded image.

    Runs on the same codec and vision model as the agent's read tool, so there
    is one way to turn an image into words rather than two that drift apart. The
    upload's declared content_type is ignored — the codec sniffs the real
    format from the bytes and transcodes anything a provider won't take.
    """
    data = await image.read(MAX_IMAGE_FILE_BYTES + 1)
    if len(data) > MAX_IMAGE_FILE_BYTES:
        raise HTTPException(status_code=413, detail="Image exceeds the upload limit.")
    try:
        inline = await ImageCodec.from_bytes(data)
    except InvalidImageError as exc:
        raise HTTPException(status_code=400, detail=f"Unreadable image: {exc}") from exc

    description = await describe_image(
        inline.base64,
        inline.mime_type,
        prompt=IMAGE_TO_TEXT_PROMPT.format(message=message),
        label="image_to_text",
        user_id=user_id,
    )
    if description is None:
        raise HTTPException(status_code=502, detail="The vision model is unavailable.")
    return description
