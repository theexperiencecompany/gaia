"""LinkedIn tools using Composio custom tool infrastructure.

These tools provide LinkedIn functionality using the access_token from Composio's
auth_credentials. Uses LinkedIn API v2 for posts, comments, and reactions.
"""

from typing import Any, Dict, List

import httpx
from app.config.loggers import chat_logger as logger
from app.decorators.documentation import with_doc
from app.models.linkedin_models import (
    AddCommentInput,
    CreatePostInput,
    DeleteReactionInput,
    GetPostCommentsInput,
    GetPostReactionsInput,
    ReactToPostInput,
)
from app.templates.docstrings.linkedin_tool_docs import (
    CUSTOM_ADD_COMMENT_DOC,
    CUSTOM_CREATE_POST_DOC,
    CUSTOM_DELETE_REACTION_DOC,
    CUSTOM_GET_POST_COMMENTS_DOC,
    CUSTOM_GET_POST_REACTIONS_DOC,
    CUSTOM_REACT_TO_POST_DOC,
)
from composio import Composio

LINKEDIN_API_BASE = "https://api.linkedin.com/v2"
LINKEDIN_REST_BASE = "https://api.linkedin.com/rest"

# LinkedIn API version - use a recent stable version
LINKEDIN_VERSION = "202401"

# Reusable sync HTTP client
_http_client = httpx.Client(timeout=60)


def _get_access_token(auth_credentials: Dict[str, Any]) -> str:
    """Extract access token from auth_credentials."""
    token = auth_credentials.get("access_token")
    if not token:
        raise ValueError("Missing access_token in auth_credentials")
    return token


def _linkedin_headers(access_token: str) -> Dict[str, str]:
    """Return headers for LinkedIn API v2 requests."""
    return {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json",
        "X-Restli-Protocol-Version": "2.0.0",
        "LinkedIn-Version": LINKEDIN_VERSION,
    }


def _get_author_urn(access_token: str, organization_id: str | None = None) -> str:
    """Get the author URN (person or organization)."""
    if organization_id:
        # If org ID provided, use it directly
        if organization_id.startswith("urn:li:organization:"):
            return organization_id
        return f"urn:li:organization:{organization_id}"

    # Get the authenticated user's URN
    try:
        resp = _http_client.get(
            f"{LINKEDIN_API_BASE}/userinfo",
            headers={"Authorization": f"Bearer {access_token}"},
        )
        resp.raise_for_status()
        data = resp.json()
        sub = data.get("sub")
        if sub:
            return f"urn:li:person:{sub}"
    except Exception as e:
        logger.error(f"Error getting user info: {e}")

    raise ValueError("Could not determine author URN")


def _upload_image_from_url(
    access_token: str,
    image_url: str,
    author_urn: str,
) -> str | None:
    """Download image from URL and upload to LinkedIn, returning the asset URN."""
    headers = _linkedin_headers(access_token)

    try:
        # Step 1: Initialize upload
        init_data = {
            "initializeUploadRequest": {
                "owner": author_urn,
            }
        }

        init_resp = _http_client.post(
            f"{LINKEDIN_REST_BASE}/images?action=initializeUpload",
            headers=headers,
            json=init_data,
        )
        init_resp.raise_for_status()
        init_result = init_resp.json()

        upload_url = init_result.get("value", {}).get("uploadUrl")
        image_urn = init_result.get("value", {}).get("image")

        if not upload_url or not image_urn:
            logger.error("Failed to get upload URL from LinkedIn")
            return None

        # Step 2: Download image from URL
        img_resp = _http_client.get(image_url, follow_redirects=True)
        img_resp.raise_for_status()
        image_data = img_resp.content
        content_type = img_resp.headers.get("content-type", "image/jpeg")

        # Step 3: Upload to LinkedIn
        upload_headers = {
            "Authorization": f"Bearer {access_token}",
            "Content-Type": content_type,
        }
        upload_resp = _http_client.put(
            upload_url,
            headers=upload_headers,
            content=image_data,
        )
        upload_resp.raise_for_status()

        return image_urn

    except Exception as e:
        logger.error(f"Error uploading image: {e}")
        return None


def _upload_document_from_url(
    access_token: str,
    document_url: str,
    author_urn: str,
) -> str | None:
    """Download document from URL and upload to LinkedIn, returning the asset URN."""
    headers = _linkedin_headers(access_token)

    try:
        # Step 1: Initialize upload
        init_data = {
            "initializeUploadRequest": {
                "owner": author_urn,
            }
        }

        init_resp = _http_client.post(
            f"{LINKEDIN_REST_BASE}/documents?action=initializeUpload",
            headers=headers,
            json=init_data,
        )
        init_resp.raise_for_status()
        init_result = init_resp.json()

        upload_url = init_result.get("value", {}).get("uploadUrl")
        document_urn = init_result.get("value", {}).get("document")

        if not upload_url or not document_urn:
            logger.error("Failed to get upload URL from LinkedIn")
            return None

        # Step 2: Download document from URL
        doc_resp = _http_client.get(document_url, follow_redirects=True)
        doc_resp.raise_for_status()
        document_data = doc_resp.content
        content_type = doc_resp.headers.get("content-type", "application/pdf")

        # Step 3: Upload to LinkedIn
        upload_headers = {
            "Authorization": f"Bearer {access_token}",
            "Content-Type": content_type,
        }
        upload_resp = _http_client.put(
            upload_url,
            headers=upload_headers,
            content=document_data,
        )
        upload_resp.raise_for_status()

        return document_urn

    except Exception as e:
        logger.error(f"Error uploading document: {e}")
        return None


def register_linkedin_custom_tools(composio: Composio) -> List[str]:
    """Register LinkedIn tools as Composio custom tools."""

    @composio.tools.custom_tool(toolkit="LINKEDIN")
    @with_doc(CUSTOM_CREATE_POST_DOC)
    def CUSTOM_CREATE_POST(
        request: CreatePostInput,
        execute_request: Any,
        auth_credentials: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Create a LinkedIn post with optional media (image, document, or article)."""
        access_token = _get_access_token(auth_credentials)
        headers = _linkedin_headers(access_token)

        try:
            # Get author URN
            author_urn = _get_author_urn(access_token, request.organization_id)

            # Determine media type and build content accordingly
            media_type = "text"
            content: Dict[str, Any] | None = None

            # Priority: document > image > article (if multiple provided, use this order)
            if request.document_url:
                # Document post
                media_type = "document"
                if not request.document_title:
                    return {
                        "success": False,
                        "error": "document_title is required when document_url is provided",
                    }

                document_urn = _upload_document_from_url(
                    access_token, request.document_url, author_urn
                )
                if not document_urn:
                    return {
                        "success": False,
                        "error": "Failed to upload document to LinkedIn",
                    }
                content = {
                    "media": {
                        "title": request.document_title,
                        "id": document_urn,
                    }
                }

            elif request.image_urls or request.image_url:
                # Image post - single or carousel
                urls_to_upload = request.image_urls or (
                    [request.image_url] if request.image_url else []
                )

                # Limit to max 20 images (LinkedIn carousel limit)
                if len(urls_to_upload) > 20:
                    return {
                        "success": False,
                        "error": "Maximum 20 images allowed in a carousel post",
                    }

                # Upload all images
                image_urns = []
                for url in urls_to_upload:
                    urn = _upload_image_from_url(access_token, url, author_urn)
                    if not urn:
                        return {
                            "success": False,
                            "error": f"Failed to upload image: {url}",
                        }
                    image_urns.append(urn)

                if len(image_urns) == 1:
                    # Single image post
                    media_type = "image"
                    content = {
                        "media": {
                            "title": request.image_title or "",
                            "id": image_urns[0],
                        }
                    }
                else:
                    # Multi-image carousel
                    media_type = "carousel"
                    content = {
                        "multiImage": {"images": [{"id": urn} for urn in image_urns]}
                    }

            elif request.article_url:
                # Article/link post
                media_type = "article"
                article_content: Dict[str, Any] = {
                    "source": request.article_url,
                }
                if request.article_title:
                    article_content["title"] = request.article_title
                if request.article_description:
                    article_content["description"] = request.article_description
                if request.thumbnail_url:
                    thumbnail_urn = _upload_image_from_url(
                        access_token, request.thumbnail_url, author_urn
                    )
                    if thumbnail_urn:
                        article_content["thumbnail"] = thumbnail_urn
                content = {"article": article_content}

            # Build the post data
            post_data: Dict[str, Any] = {
                "author": author_urn,
                "commentary": request.commentary,
                "visibility": request.visibility,
                "distribution": {
                    "feedDistribution": "MAIN_FEED",
                    "targetEntities": [],
                    "thirdPartyDistributionChannels": [],
                },
                "lifecycleState": "PUBLISHED",
                "isReshareDisabledByAuthor": False,
            }

            # Add content if media is present
            if content:
                post_data["content"] = content

            resp = _http_client.post(
                f"{LINKEDIN_REST_BASE}/posts",
                headers=headers,
                json=post_data,
            )
            resp.raise_for_status()

            # Get post ID from response header
            post_id = resp.headers.get("x-restli-id", "")

            return {
                "success": True,
                "post_id": post_id,
                "url": f"https://www.linkedin.com/feed/update/{post_id}",
                "author": author_urn,
                "media_type": media_type,
            }

        except httpx.HTTPStatusError as e:
            logger.error(f"Error creating post: {e}")
            return {
                "success": False,
                "error": f"API error: {e.response.status_code} - {e.response.text}",
            }
        except Exception as e:
            logger.error(f"Error creating post: {e}")
            return {"success": False, "error": str(e)}

    @composio.tools.custom_tool(toolkit="LINKEDIN")
    @with_doc(CUSTOM_ADD_COMMENT_DOC)
    def CUSTOM_ADD_COMMENT(
        request: AddCommentInput,
        execute_request: Any,
        auth_credentials: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Add a comment to a LinkedIn post."""
        access_token = _get_access_token(auth_credentials)
        headers = _linkedin_headers(access_token)

        try:
            author_urn = _get_author_urn(access_token)

            # URL encode the post URN for the path
            encoded_urn = request.post_urn.replace(":", "%3A")

            comment_data: Dict[str, Any] = {
                "actor": author_urn,
                "message": {
                    "text": request.comment_text,
                },
            }

            if request.parent_comment_urn:
                comment_data["parentComment"] = request.parent_comment_urn

            resp = _http_client.post(
                f"{LINKEDIN_REST_BASE}/socialActions/{encoded_urn}/comments",
                headers=headers,
                json=comment_data,
            )
            resp.raise_for_status()

            result = resp.json()
            comment_id = result.get("id") or resp.headers.get("x-restli-id", "")

            return {
                "success": True,
                "comment_id": comment_id,
                "post_urn": request.post_urn,
                "author": author_urn,
            }

        except httpx.HTTPStatusError as e:
            logger.error(f"Error adding comment: {e}")
            return {
                "success": False,
                "error": f"API error: {e.response.status_code} - {e.response.text}",
            }
        except Exception as e:
            logger.error(f"Error adding comment: {e}")
            return {"success": False, "error": str(e)}

    @composio.tools.custom_tool(toolkit="LINKEDIN")
    @with_doc(CUSTOM_GET_POST_COMMENTS_DOC)
    def CUSTOM_GET_POST_COMMENTS(
        request: GetPostCommentsInput,
        execute_request: Any,
        auth_credentials: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Retrieve comments on a LinkedIn post."""
        access_token = _get_access_token(auth_credentials)
        headers = _linkedin_headers(access_token)

        try:
            encoded_urn = request.post_urn.replace(":", "%3A")

            params = {
                "count": request.count,
                "start": request.start,
            }

            resp = _http_client.get(
                f"{LINKEDIN_REST_BASE}/socialActions/{encoded_urn}/comments",
                headers=headers,
                params=params,
            )
            resp.raise_for_status()

            result = resp.json()
            comments = result.get("elements", [])

            # Format comments for easier consumption
            formatted_comments = []
            for comment in comments:
                formatted_comments.append(
                    {
                        "id": comment.get("id"),
                        "author": comment.get("actor"),
                        "text": comment.get("message", {}).get("text", ""),
                        "created_at": comment.get("created", {}).get("time"),
                        "parent_comment": comment.get("parentComment"),
                    }
                )

            return {
                "success": True,
                "comments": formatted_comments,
                "total_count": result.get("paging", {}).get("total", len(comments)),
                "post_urn": request.post_urn,
            }

        except httpx.HTTPStatusError as e:
            logger.error(f"Error getting comments: {e}")
            return {
                "success": False,
                "error": f"API error: {e.response.status_code} - {e.response.text}",
            }
        except Exception as e:
            logger.error(f"Error getting comments: {e}")
            return {"success": False, "error": str(e)}

    @composio.tools.custom_tool(toolkit="LINKEDIN")
    @with_doc(CUSTOM_REACT_TO_POST_DOC)
    def CUSTOM_REACT_TO_POST(
        request: ReactToPostInput,
        execute_request: Any,
        auth_credentials: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Add a reaction to a LinkedIn post."""
        access_token = _get_access_token(auth_credentials)
        headers = _linkedin_headers(access_token)

        try:
            author_urn = _get_author_urn(access_token)
            encoded_urn = request.post_urn.replace(":", "%3A")

            reaction_data = {
                "actor": author_urn,
                "reactionType": request.reaction_type,
            }

            resp = _http_client.post(
                f"{LINKEDIN_REST_BASE}/socialActions/{encoded_urn}/likes",
                headers=headers,
                json=reaction_data,
            )
            resp.raise_for_status()

            return {
                "success": True,
                "post_urn": request.post_urn,
                "reaction_type": request.reaction_type,
                "author": author_urn,
            }

        except httpx.HTTPStatusError as e:
            logger.error(f"Error adding reaction: {e}")
            return {
                "success": False,
                "error": f"API error: {e.response.status_code} - {e.response.text}",
            }
        except Exception as e:
            logger.error(f"Error adding reaction: {e}")
            return {"success": False, "error": str(e)}

    @composio.tools.custom_tool(toolkit="LINKEDIN")
    @with_doc(CUSTOM_DELETE_REACTION_DOC)
    def CUSTOM_DELETE_REACTION(
        request: DeleteReactionInput,
        execute_request: Any,
        auth_credentials: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Remove your reaction from a LinkedIn post."""
        access_token = _get_access_token(auth_credentials)
        headers = _linkedin_headers(access_token)

        try:
            author_urn = _get_author_urn(access_token)
            encoded_post_urn = request.post_urn.replace(":", "%3A")
            encoded_author_urn = author_urn.replace(":", "%3A")

            resp = _http_client.delete(
                f"{LINKEDIN_REST_BASE}/socialActions/{encoded_post_urn}/likes/{encoded_author_urn}",
                headers=headers,
            )
            resp.raise_for_status()

            return {
                "success": True,
                "post_urn": request.post_urn,
                "message": "Reaction removed successfully",
            }

        except httpx.HTTPStatusError as e:
            logger.error(f"Error removing reaction: {e}")
            return {
                "success": False,
                "error": f"API error: {e.response.status_code} - {e.response.text}",
            }
        except Exception as e:
            logger.error(f"Error removing reaction: {e}")
            return {"success": False, "error": str(e)}

    @composio.tools.custom_tool(toolkit="LINKEDIN")
    @with_doc(CUSTOM_GET_POST_REACTIONS_DOC)
    def CUSTOM_GET_POST_REACTIONS(
        request: GetPostReactionsInput,
        execute_request: Any,
        auth_credentials: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Retrieve reactions on a LinkedIn post."""
        access_token = _get_access_token(auth_credentials)
        headers = _linkedin_headers(access_token)

        try:
            encoded_urn = request.post_urn.replace(":", "%3A")

            params = {
                "count": request.count,
            }

            resp = _http_client.get(
                f"{LINKEDIN_REST_BASE}/socialActions/{encoded_urn}/likes",
                headers=headers,
                params=params,
            )
            resp.raise_for_status()

            result = resp.json()
            reactions = result.get("elements", [])

            # Format reactions
            formatted_reactions = []
            for reaction in reactions:
                formatted_reactions.append(
                    {
                        "actor": reaction.get("actor"),
                        "reaction_type": reaction.get("reactionType", "LIKE"),
                        "created_at": reaction.get("created", {}).get("time"),
                    }
                )

            return {
                "success": True,
                "reactions": formatted_reactions,
                "total_count": result.get("paging", {}).get("total", len(reactions)),
                "post_urn": request.post_urn,
            }

        except httpx.HTTPStatusError as e:
            logger.error(f"Error getting reactions: {e}")
            return {
                "success": False,
                "error": f"API error: {e.response.status_code} - {e.response.text}",
            }
        except Exception as e:
            logger.error(f"Error getting reactions: {e}")
            return {"success": False, "error": str(e)}

    # Return list of registered tool names
    return [
        "LINKEDIN_CUSTOM_CREATE_POST",
        "LINKEDIN_CUSTOM_ADD_COMMENT",
        "LINKEDIN_CUSTOM_GET_POST_COMMENTS",
        "LINKEDIN_CUSTOM_REACT_TO_POST",
        "LINKEDIN_CUSTOM_DELETE_REACTION",
        "LINKEDIN_CUSTOM_GET_POST_REACTIONS",
    ]
