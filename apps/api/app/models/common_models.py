"""Shared Pydantic input models used across multiple tool files."""

from typing import Optional

from pydantic import BaseModel, Field


class GatherContextInput(BaseModel):
    """Input model for CUSTOM_GATHER_CONTEXT tools.

    No required parameters — these tools gather context automatically using the
    auth_credentials provided by Composio at call time.
    """

    since: Optional[str] = Field(
        default=None,
        description=(
            "Optional ISO 8601 timestamp to filter results to only items updated "
            "after this time (e.g., '2024-01-15T10:00:00Z'). If omitted, "
            "tools return their default recent snapshot."
        ),
    )
