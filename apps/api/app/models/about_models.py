"""
Pydantic models for the about page functionality.
"""

from pydantic import BaseModel


class Author(BaseModel):
    """Author information model."""

    name: str
    avatar: str
    role: str
    linkedin: str | None = None
    twitter: str | None = None


class AboutResponse(BaseModel):
    """Response model for about page content."""

    content: str
    authors: list[Author]
