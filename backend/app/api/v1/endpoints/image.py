"""
Router module for image generation and image-to-text endpoints.
"""

from fastapi import APIRouter, File, Form, UploadFile, Depends
from fastapi.responses import JSONResponse, StreamingResponse

from app.models.message_models import MessageRequest
from app.services.image_service import (
    api_generate_image,
    generate_image_stream,
    image_to_text_endpoint,
)
from app.decorators import tiered_rate_limit
from app.api.v1.dependencies.oauth_dependencies import get_current_user

router = APIRouter()


@router.post("/image/generate")
@tiered_rate_limit("generate_image")
async def image(request: MessageRequest, _user: dict = Depends(get_current_user)):
    """Generate an image based on the text prompt."""
    response = await api_generate_image(request.message)
    return JSONResponse(content=response)


@router.post("/image/text")
@tiered_rate_limit("file_analysis", count_tokens=True)
async def image_to_text(
    message: str = Form(...),
    file: UploadFile = File(...),
    _user: dict = Depends(get_current_user),
):
    """Extract text from an image using OCR."""
    response = await image_to_text_endpoint(message, file)
    return JSONResponse(content=response)


@router.post("/image/generate/stream")
@tiered_rate_limit("generate_image")
async def image_stream(
    request: MessageRequest, _user: dict = Depends(get_current_user)
):
    """Generate an image with streaming response."""
    return StreamingResponse(
        generate_image_stream(request.message),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "Connection": "keep-alive"},
    )
