from bson import ObjectId
from pydantic import BaseModel, ConfigDict, Field

from app.db.repositories.base import MongoDocument


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


class BlogDocument(MongoDocument):
    """A blog post as stored in the ``blog`` collection (global, keyed by ``_id``).

    ``author_details`` is not stored — it is populated by a ``$lookup`` join to the
    ``team`` collection when a post is read (see :class:`BlogAggregateRow`)."""

    slug: str
    title: str
    date: str
    authors: list[str] = Field(default_factory=list)
    category: str
    content: str
    image: str | None = None


class BlogUpdate(BaseModel):
    """Editable fields of a blog post (authoring is out of band for now)."""

    model_config = ConfigDict(extra="forbid")

    title: str | None = None
    date: str | None = None
    authors: list[str] | None = None
    category: str | None = None
    content: str | None = None
    image: str | None = None


class BlogCountResponse(BaseModel):
    """Response for the total count of blog posts."""

    count: int


class BlogAggregateRow(BaseModel):
    """One row of the blog read pipeline, before author/content normalisation.

    ``content`` is absent from list projections and ``author_details`` is absent
    when the ``team`` ``$lookup`` finds no members, so both are optional here and
    filled in when mapping to :class:`BlogPost`."""

    id: str = ""
    slug: str
    title: str
    date: str
    authors: list[str] = Field(default_factory=list)
    category: str
    image: str | None = None
    content: str | None = None
    author_details: list[AuthorDetails] | None = None
