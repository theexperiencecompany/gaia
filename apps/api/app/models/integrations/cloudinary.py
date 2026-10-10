"""Cloudinary upload API payloads."""

from pydantic import BaseModel, ConfigDict


class CloudinaryUploadResult(BaseModel):
    """A Cloudinary upload response, read only for the hosted URL."""

    model_config = ConfigDict(extra="ignore")

    secure_url: str | None = None
