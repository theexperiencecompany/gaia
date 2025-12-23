"""Pydantic models for LinkedIn custom tools."""

from typing import Literal, Optional

from pydantic import BaseModel, Field


class CreateImagePostInput(BaseModel):
    """Input for creating a LinkedIn post with an image."""

    commentary: str = Field(
        ...,
        description="The text content of the post. Supports mentions and hashtags.",
        min_length=1,
        max_length=3000,
    )
    image_url: str = Field(
        ...,
        description="URL of the image to include in the post (must be publicly accessible)",
    )
    image_title: Optional[str] = Field(None, description="Optional title for the image")
    image_description: Optional[str] = Field(
        None, description="Optional description for the image"
    )
    visibility: Literal["PUBLIC", "CONNECTIONS"] = Field(
        "PUBLIC",
        description="Post visibility: 'PUBLIC' for everyone, 'CONNECTIONS' for 1st degree only",
    )
    organization_id: Optional[str] = Field(
        None,
        description="Organization URN to post on behalf of (e.g., 'urn:li:organization:12345'). If omitted, posts as the authenticated user.",
    )


class CreateArticlePostInput(BaseModel):
    """Input for creating a LinkedIn post sharing an article/link."""

    commentary: str = Field(
        ...,
        description="The text content accompanying the shared article",
        min_length=1,
        max_length=3000,
    )
    article_url: str = Field(..., description="URL of the article to share")
    article_title: Optional[str] = Field(
        None, description="Custom title for the article preview"
    )
    article_description: Optional[str] = Field(
        None, description="Custom description for the article preview"
    )
    thumbnail_url: Optional[str] = Field(
        None, description="Custom thumbnail image URL for the article preview"
    )
    visibility: Literal["PUBLIC", "CONNECTIONS"] = Field(
        "PUBLIC",
        description="Post visibility: 'PUBLIC' for everyone, 'CONNECTIONS' for 1st degree only",
    )
    organization_id: Optional[str] = Field(
        None,
        description="Organization URN to post on behalf of. If omitted, posts as the authenticated user.",
    )


class CreateDocumentPostInput(BaseModel):
    """Input for creating a LinkedIn post with a document (PDF, etc.)."""

    commentary: str = Field(
        ...,
        description="The text content of the post",
        min_length=1,
        max_length=3000,
    )
    document_url: str = Field(
        ...,
        description="URL of the document to share (PDF, PPT, etc. - must be publicly accessible)",
    )
    document_title: str = Field(..., description="Title for the document")
    visibility: Literal["PUBLIC", "CONNECTIONS"] = Field(
        "PUBLIC",
        description="Post visibility: 'PUBLIC' for everyone, 'CONNECTIONS' for 1st degree only",
    )
    organization_id: Optional[str] = Field(
        None,
        description="Organization URN to post on behalf of. If omitted, posts as the authenticated user.",
    )


class AddCommentInput(BaseModel):
    """Input for adding a comment to a LinkedIn post."""

    post_urn: str = Field(
        ...,
        description="URN of the post to comment on (e.g., 'urn:li:share:12345' or 'urn:li:ugcPost:12345')",
    )
    comment_text: str = Field(
        ...,
        description="The text content of the comment",
        min_length=1,
        max_length=1250,
    )
    parent_comment_urn: Optional[str] = Field(
        None,
        description="URN of parent comment for nested replies (e.g., 'urn:li:comment:12345')",
    )


class GetPostCommentsInput(BaseModel):
    """Input for retrieving comments on a LinkedIn post."""

    post_urn: str = Field(
        ...,
        description="URN of the post to get comments from (e.g., 'urn:li:share:12345')",
    )
    count: int = Field(
        10,
        description="Number of comments to retrieve",
        ge=1,
        le=100,
    )
    start: int = Field(
        0,
        description="Starting index for pagination",
        ge=0,
    )


class ReactToPostInput(BaseModel):
    """Input for adding a reaction to a LinkedIn post."""

    post_urn: str = Field(
        ...,
        description="URN of the post to react to (e.g., 'urn:li:share:12345')",
    )
    reaction_type: Literal[
        "LIKE", "CELEBRATE", "SUPPORT", "LOVE", "INSIGHTFUL", "FUNNY"
    ] = Field(
        "LIKE",
        description="Type of reaction to add",
    )


class DeleteReactionInput(BaseModel):
    """Input for removing a reaction from a LinkedIn post."""

    post_urn: str = Field(
        ...,
        description="URN of the post to remove reaction from",
    )


class GetPostReactionsInput(BaseModel):
    """Input for retrieving reactions on a LinkedIn post."""

    post_urn: str = Field(
        ...,
        description="URN of the post to get reactions from",
    )
    count: int = Field(
        10,
        description="Number of reactions to retrieve",
        ge=1,
        le=100,
    )
