"""
Common response models shared across API endpoints.
"""

from typing import Literal

from pydantic import BaseModel, ConfigDict


class SuccessResponse(BaseModel):
    """Base success response for CRUD operations."""

    model_config = ConfigDict(populate_by_name=True)

    status: Literal["success"] = "success"
    message: str
