"""
Router module for image generation and image-to-text endpoints.
"""

from fastapi import APIRouter, Depends, File, Form, UploadFile
from fastapi.responses import StreamingResponse

from app.api.v1.dependencies.oauth_dependencies import get_current_user
from app.decorators import require_subscription, tiered_rate_limit
from app.models.chat_models import ImageData
from app.models.image_models import ImageToTextResponse
from app.models.message_models import MessageRequest
from app.models.user_models import AuthenticatedUser
from app.services.image_service import (
    api_generate_image,
    generate_image_stream,
    image_to_text_endpoint,
)
from shared.py.wide_events import log

router = APIRouter()


@router.post("/image/generate")
@require_subscription()
@tiered_rate_limit("generate_image")
async def image(
    request: MessageRequest, _user: AuthenticatedUser = Depends(get_current_user)
) -> ImageData:
    """Generate an image based on the text prompt."""
    log.set(operation="generate", prompt_length=len(request.message))
    response = await api_generate_image(request.message)
    log.set(outcome="success")
    return response


@router.post("/image/text")
@tiered_rate_limit("file_analysis")
async def image_to_text(
    message: str = Form(...),
    file: UploadFile = File(...),
    _user: AuthenticatedUser = Depends(get_current_user),
) -> ImageToTextResponse:
    """Extract text from an image using OCR."""
    log.set(
        operation="image_to_text",
        file_name=file.filename,
        mime_type=file.content_type,
        prompt_length=len(message),
    )
    response = await image_to_text_endpoint(message, file)
    log.set(outcome="success")
    return response


@router.post("/image/generate/stream")
@require_subscription()
@tiered_rate_limit("generate_image")
async def image_stream(
    request: MessageRequest, _user: AuthenticatedUser = Depends(get_current_user)
) -> StreamingResponse:
    """Generate an image with streaming response."""
    log.set(
        operation="generate_stream",
        prompt_length=len(request.message),
        outcome="success",
    )
    return StreamingResponse(
        generate_image_stream(request.message),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "Connection": "keep-alive"},
    )
