"""
Pydantic models for tool-related operations.
"""

from typing import List, Optional
from pydantic import BaseModel


class ToolInfo(BaseModel):
    """Model for individual tool information."""

    name: str
    category: str
    category_display_name: Optional[str] = None  # Human-readable name for display
    integration_name: Optional[str] = None  # Human-readable integration name
    required_integration: Optional[str] = None
    icon_url: Optional[str] = None  # For custom integrations with dynamic icons


class ToolsListResponse(BaseModel):
    """Response model for tools list endpoint."""

    tools: List[ToolInfo]
    total_count: int
    categories: List[str]


class ToolsCategoryResponse(BaseModel):
    """Response model for tools by category."""

    category: str
    tools: List[ToolInfo]
    count: int
