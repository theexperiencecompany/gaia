"""Pydantic models for LinkedIn custom tools."""

from typing import List, Literal, Optional

from pydantic import BaseModel, Field


class CreatePostInput(BaseModel):
    """Unified input for creating LinkedIn posts with optional media (image, document, or article).

    This model supports:
    - Text-only posts: Just provide commentary
    - Single image post: Provide commentary + image_url
    - Multi-image carousel: Provide commentary + image_urls (list of URLs, max 20)
    - Document posts: Provide commentary + document_url + document_title
    - Article posts: Provide commentary + article_url

    Only one media type should be provided per post.
    """

    commentary: str = Field(
        ...,
        description="The main text content of the post. Supports @-mentions and hashtags. Maximum 3000 characters.",
        min_length=1,
        max_length=3000,
    )
    visibility: Literal["PUBLIC", "CONNECTIONS"] = Field(
        "PUBLIC",
        description="Post visibility: 'PUBLIC' for everyone, 'CONNECTIONS' for 1st degree connections only",
    )
    organization_id: Optional[str] = Field(
        None,
        description="Organization URN to post on behalf of (e.g., 'urn:li:organization:12345'). If omitted, posts as the authenticated user.",
    )

    # ===== Image Media Fields =====
    image_url: Optional[str] = Field(
        None,
        description="URL of a single image to include. Use image_urls for multi-image carousel posts.",
    )
    image_urls: Optional[List[str]] = Field(
        None,
        description="List of image URLs for a multi-image carousel post (max 20 images). Takes priority over image_url if both provided.",
    )
    image_title: Optional[str] = Field(
        None,
        description="Optional title for single-image posts (not used for carousels)",
    )

    # ===== Document Media Fields =====
    document_url: Optional[str] = Field(
        None,
        description="URL of a document to share (PDF, PPT, etc. - must be publicly accessible). Use for document posts.",
    )
    document_title: Optional[str] = Field(
        None,
        description="Title for the document (required if document_url is provided)",
    )

    # ===== Article/Link Media Fields =====
    article_url: Optional[str] = Field(
        None,
        description="URL of an article or external link to share. Use for sharing web content with link preview.",
    )
    article_title: Optional[str] = Field(
        None,
        description="Custom title for the article preview (overrides auto-fetched title)",
    )
    article_description: Optional[str] = Field(
        None,
        description="Custom description for the article preview (overrides auto-fetched description)",
    )
    thumbnail_url: Optional[str] = Field(
        None,
        description="Custom thumbnail image URL for the article preview",
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
