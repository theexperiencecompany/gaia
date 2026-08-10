"""Pydantic models for the image endpoints.

Image *generation* reuses ``chat_models.ImageData`` — that model already
describes the ``{url, prompt, improved_prompt}`` payload both this router and
the chat stream emit, and there must be one of it.
"""

from pydantic import BaseModel, Field


class ImageToTextResponse(BaseModel):
    """``POST /image/text`` — the vision model's answer about the upload."""

    response: str = Field(..., description="The model's answer about the uploaded image")
