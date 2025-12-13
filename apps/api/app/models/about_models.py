"""
Pydantic models for the about page functionality.
"""

from typing import List, Optional
from pydantic import BaseModel


class Author(BaseModel):
    """Author information model."""

    name: str
    avatar: str
    role: str
    linkedin: Optional[str] = None
    twitter: Optional[str] = None


class AboutResponse(BaseModel):
    """Response model for about page content."""

    content: str
    authors: List[Author]
