"""
Base Composio response model.
"""

from pydantic import BaseModel, ConfigDict


class ComposioResponse(BaseModel):  # type: ignore[explicit-any]
    """Base model for all Composio tool responses."""

    model_config = ConfigDict(from_attributes=True)

    successful: bool
    error: str | None = None
    data: dict[str, object]
