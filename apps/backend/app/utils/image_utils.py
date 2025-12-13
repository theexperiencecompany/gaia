from io import BytesIO
from typing import Any

import httpx
import requests
from app.agents.prompts.image_prompts import IMAGE_CAPTION_FORMATTER
from app.utils.chat_utils import do_prompt_no_stream
from fastapi import File, Form, HTTPException, UploadFile
from PIL import Image

http_async_client = httpx.AsyncClient(timeout=1000)


async def generate_image(imageprompt: str) -> dict[str, str] | bytes:
    url = "https://generateimage.aryanranderiya1478.workers.dev/"
    try:
        response = await http_async_client.post(url, json={"imageprompt": imageprompt})
        response.raise_for_status()
        return response.content
    except requests.exceptions.RequestException as e:
        return {"error": str(e)}


def compress_image(image_bytes, sizing=0.4, quality=85):
    try:
        image = Image.open(BytesIO(image_bytes))
        output_io = BytesIO()

        new_width = int(image.width * sizing)
        new_height = int(image.height * sizing)
        resized_image = image.resize((new_width, new_height), Image.LANCZOS)

        resized_image.save(output_io, format="JPEG", optimize=True, quality=quality)
        compressed_image_bytes = output_io.getvalue()

        return compressed_image_bytes

    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"Failed to compress image: {str(e)}"
        )


async def convert_image_to_text(
    image: UploadFile = File(...),
    message: str = Form(...),
) -> dict[str, str] | str | Any:
    contents = await image.read()
    url = "https://imageunderstanding.aryanranderiya1478.workers.dev/"

    try:
        if 1 * 1024 * 1024 <= len(contents) <= 2 * 1024 * 1024:
            contents = compress_image(contents, sizing=0.9, quality=95)
        elif 2 * 1024 * 1024 <= len(contents) <= 6 * 1024 * 1024:
            contents = compress_image(contents)

        if len(contents) > 1 * 1024 * 1024:
            return "File too large"

        improved_prompt = await do_prompt_no_stream(
            prompt=IMAGE_CAPTION_FORMATTER.format(message=message)
        )

        async with httpx.AsyncClient() as client:
            response = await client.post(
                url,
                files={"image": ("image.jpg", contents, image.content_type)},
                data={"prompt": improved_prompt["response"]},
                timeout=1000.0,
            )
            response.raise_for_status()
            return response.json()

    except httpx.RequestError as e:
        return {"error": str(e)}
