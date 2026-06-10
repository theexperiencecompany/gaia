"""
Base Composio response model.
"""

from typing import Any

from pydantic import BaseModel, ConfigDict


class ComposioResponse(BaseModel):
    """Base model for all Composio tool responses."""

    model_config = ConfigDict(from_attributes=True)

    successful: bool
    error: str | None = None
    data: dict[str, Any]
