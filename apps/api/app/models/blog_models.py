from bson import ObjectId
from pydantic import BaseModel, ConfigDict, Field


class AuthorDetails(BaseModel):
    """Author details model for populated team member information."""

    id: str | None = None
    name: str
    role: str
    avatar: str | None = None
    linkedin: str | None = None
    twitter: str | None = None


class BlogPostBase(BaseModel):
    title: str
    date: str
    authors: list[str]  # Team member IDs
    category: str
    content: str
    image: str | None = None


class BlogPost(BlogPostBase):
    """Blog post response model with proper ID handling."""

    model_config = ConfigDict(
        json_encoders={ObjectId: str},
        populate_by_name=True,
        arbitrary_types_allowed=True,
        from_attributes=True,
    )

    slug: str
    id: str = Field(description="Unique identifier for the blog post")
    author_details: list[AuthorDetails] | None = None
