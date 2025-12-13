from typing import List, Optional
from pydantic import BaseModel, Field, ConfigDict
from bson import ObjectId


class AuthorDetails(BaseModel):
    """Author details model for populated team member information."""

    id: Optional[str] = None
    name: str
    role: str
    avatar: Optional[str] = None
    linkedin: Optional[str] = None
    twitter: Optional[str] = None


class BlogPostBase(BaseModel):
    title: str
    date: str
    authors: List[str]  # Team member IDs
    category: str
    content: str
    image: Optional[str] = None


class BlogPostCreate(BlogPostBase):
    slug: str


class BlogPostUpdate(BaseModel):
    title: Optional[str] = None
    date: Optional[str] = None
    authors: Optional[List[str]] = None
    category: Optional[str] = None
    content: Optional[str] = None
    image: Optional[str] = None


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
    author_details: Optional[List[AuthorDetails]] = None

    @classmethod
    def from_mongo(cls, data: dict) -> "BlogPost":
        """Create BlogPost instance from MongoDB document."""
        if "_id" in data:
            data["id"] = str(data["_id"])
        return cls(**data)
