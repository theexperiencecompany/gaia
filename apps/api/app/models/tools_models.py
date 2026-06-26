"""
Pydantic models for tool-related operations.
"""

from pydantic import BaseModel


class ToolInfo(BaseModel):
    """Model for individual tool information."""

    name: str
    category: str  # Integration ID (e.g., "gmail", UUID for custom)
    display_name: str  # REQUIRED - human-readable name, never null
    icon_url: str | None = None
    requires_integration: bool = False  # False for core platform tools
    # Server-computed: True when the tool's integration requires a connection the
    # user does not have. Core tools are never locked. The client renders lock
    # state from this — it must not re-derive it from a separate status call.
    locked: bool = False


class ToolsListResponse(BaseModel):
    """Response model for tools list endpoint."""

    tools: list[ToolInfo]
    total_count: int
    categories: list[str]


class ToolsCategoryResponse(BaseModel):
    """Response model for tools by category."""

    category: str
    tools: list[ToolInfo]
    count: int
