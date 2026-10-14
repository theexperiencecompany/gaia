"""
Common response models shared across API endpoints.
"""

from typing import Literal

from pydantic import BaseModel, ConfigDict


class ResponseModel(BaseModel):
    """Base for response-only models.

    A defaulted field is always serialized, so the OpenAPI output schema marks it
    required; without this every ``= None`` / ``default_factory=list`` field
    generates an optional key and each TypeScript consumer has to guard it.
    """

    model_config = ConfigDict(json_schema_serialization_defaults_required=True)


class SuccessResponse(BaseModel):
    """Base success response for CRUD operations."""

    model_config = ConfigDict(populate_by_name=True)

    status: Literal["success"] = "success"
    message: str
