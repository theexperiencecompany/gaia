"""Cloudinary upload API payloads."""

from pydantic import BaseModel, ConfigDict


class CloudinaryUploadResult(BaseModel):
    """A Cloudinary upload response, read only for the hosted URL."""

    model_config = ConfigDict(extra="ignore")

    secure_url: str | None = None


class CloudinaryDestroyResult(BaseModel):
    """A Cloudinary destroy response; result is "ok" once the asset is gone."""

    model_config = ConfigDict(extra="ignore")

    result: str | None = None
