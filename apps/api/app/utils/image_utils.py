from fastapi import HTTPException, UploadFile
import httpx

from app.agents.llm.vision import describe_image
from app.agents.prompts.image_prompts import IMAGE_TO_TEXT_PROMPT
from app.constants.media import MAX_IMAGE_FILE_BYTES
from app.utils.image_codec import ImageCodec, InvalidImageError

http_async_client = httpx.AsyncClient(timeout=1000)


async def generate_image(imageprompt: str) -> dict[str, str] | bytes:
    url = "https://generateimage.aryanranderiya1478.workers.dev/"
    try:
        response = await http_async_client.post(url, json={"imageprompt": imageprompt})
        response.raise_for_status()
        return response.content
    except httpx.HTTPError as e:
        return {"error": str(e)}


async def convert_image_to_text(image: UploadFile, message: str) -> str:
    """Answer ``message`` about an uploaded image.

    Runs on the same codec and vision model as the agent's `read` tool, so there
    is one way to turn an image into words rather than two that drift apart. The
    upload's declared ``content_type`` is ignored — the codec sniffs the real
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
    )
    if description is None:
        raise HTTPException(status_code=502, detail="The vision model is unavailable.")
    return description
