"""
Base Composio response model.
"""

from typing import Any, TypeVar

from pydantic import BaseModel, ConfigDict

T = TypeVar("T", bound=BaseModel)


class ComposioResponse(BaseModel):
    """Base model for all Composio tool responses."""

    model_config = ConfigDict(from_attributes=True)

    successful: bool
    error: str | None = None
    data: dict[str, Any]

    def parse_data(self, model: type[T]) -> T:
        """Parse the data field into a typed model."""
        return model.model_validate(self.data)
