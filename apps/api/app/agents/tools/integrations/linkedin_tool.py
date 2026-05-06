"""LinkedIn tools using Composio custom tool infrastructure.

LinkedIn API calls go through Composio's proxy via `proxy_request_sync`/
`proxy_request_full_sync`. The proxy attaches OAuth server-side; tools
only need `user_id` from `auth_credentials`.

Note: Errors are raised as exceptions - Composio wraps responses automatically.
"""

from typing import Any, Dict, List

from app.decorators.documentation import with_doc
from app.models.common_models import GatherContextInput
from app.models.linkedin_models import (
    AddCommentInput,
    CreatePostInput,
    DeleteReactionInput,
    GetPostCommentsInput,
    GetPostReactionsInput,
    ReactToPostInput,
)
from app.services.composio.proxy_client import (
    proxy_request_full_sync,
    proxy_request_sync,
)
from app.templates.docstrings.linkedin_tool_docs import (
    CUSTOM_ADD_COMMENT_DOC,
    CUSTOM_CREATE_POST_DOC,
    CUSTOM_DELETE_REACTION_DOC,
    CUSTOM_GET_POST_COMMENTS_DOC,
    CUSTOM_GET_POST_REACTIONS_DOC,
    CUSTOM_REACT_TO_POST_DOC,
)
from app.utils.linkedin_utils import (
    LINKEDIN_REST_BASE,
    LINKEDIN_TOOLKIT,
    get_author_urn,
    upload_document_from_url,
    upload_image_from_url,
)
from composio import Composio

LINKEDIN_API_BASE = "https://api.linkedin.com/v2"
LINKEDIN_VERSION = "202401"
_REST_HEADERS = {
    "Content-Type": "application/json",
    "X-Restli-Protocol-Version": "2.0.0",
    "LinkedIn-Version": LINKEDIN_VERSION,
}


def _user_id(auth_credentials: Dict[str, Any]) -> str:
    user_id = auth_credentials.get("user_id")
    if not user_id:
        raise ValueError("Missing user_id in auth_credentials")
    return user_id


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
        user_id = _user_id(auth_credentials)

        author_urn = get_author_urn(user_id, request.organization_id)

        media_type = "text"
        content: Dict[str, Any] | None = None

        if request.document_url:
            media_type = "document"
            if not request.document_title:
                raise ValueError(
                    "document_title is required when document_url is provided"
                )
            document_urn = upload_document_from_url(
                user_id, request.document_url, author_urn
            )
            if not document_urn:
                raise RuntimeError("Failed to upload document to LinkedIn")
            content = {
                "media": {
                    "title": request.document_title,
                    "id": document_urn,
                }
            }

        elif request.image_urls or request.image_url:
            urls_to_upload = request.image_urls or (
                [request.image_url] if request.image_url else []
            )

            if len(urls_to_upload) > 20:
                raise ValueError("Maximum 20 images allowed in a carousel post")

            image_urns = []
            for url in urls_to_upload:
                urn = upload_image_from_url(user_id, url, author_urn)
                if not urn:
                    raise RuntimeError(f"Failed to upload image: {url}")
                image_urns.append(urn)

            if len(image_urns) == 1:
                media_type = "image"
                content = {
                    "media": {
                        "title": request.image_title or "",
                        "id": image_urns[0],
                    }
                }
            else:
                media_type = "carousel"
                content = {
                    "multiImage": {"images": [{"id": urn} for urn in image_urns]}
                }

        elif request.article_url:
            media_type = "article"
            article_content: Dict[str, Any] = {
                "source": request.article_url,
            }
            if request.article_title:
                article_content["title"] = request.article_title
            if request.article_description:
                article_content["description"] = request.article_description
            if request.thumbnail_url:
                thumbnail_urn = upload_image_from_url(
                    user_id, request.thumbnail_url, author_urn
                )
                if thumbnail_urn:
                    article_content["thumbnail"] = thumbnail_urn
            content = {"article": article_content}

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

        if content:
            post_data["content"] = content

        response = proxy_request_full_sync(
            user_id=user_id,
            toolkit=LINKEDIN_TOOLKIT,
            endpoint=f"{LINKEDIN_REST_BASE}/posts",
            method="POST",
            body=post_data,
            headers=_REST_HEADERS,
        )

        post_id = response.get("headers", {}).get("x-restli-id", "")

        return {
            "post_id": post_id,
            "url": f"https://www.linkedin.com/feed/update/{post_id}",
            "author": author_urn,
            "media_type": media_type,
        }

    @composio.tools.custom_tool(toolkit="LINKEDIN")
    @with_doc(CUSTOM_ADD_COMMENT_DOC)
    def CUSTOM_ADD_COMMENT(
        request: AddCommentInput,
        execute_request: Any,
        auth_credentials: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Add a comment to a LinkedIn post."""
        user_id = _user_id(auth_credentials)

        author_urn = get_author_urn(user_id)
        encoded_urn = request.post_urn.replace(":", "%3A")

        comment_data: Dict[str, Any] = {
            "actor": author_urn,
            "message": {
                "text": request.comment_text,
            },
        }

        if request.parent_comment_urn:
            comment_data["parentComment"] = request.parent_comment_urn

        response = proxy_request_full_sync(
            user_id=user_id,
            toolkit=LINKEDIN_TOOLKIT,
            endpoint=f"{LINKEDIN_REST_BASE}/socialActions/{encoded_urn}/comments",
            method="POST",
            body=comment_data,
            headers=_REST_HEADERS,
        )

        body = response.get("data") or {}
        comment_id = (
            (body.get("id") if isinstance(body, dict) else None)
            or response.get("headers", {}).get("x-restli-id", "")
        )

        return {
            "comment_id": comment_id,
            "post_urn": request.post_urn,
            "author": author_urn,
        }

    @composio.tools.custom_tool(toolkit="LINKEDIN")
    @with_doc(CUSTOM_GET_POST_COMMENTS_DOC)
    def CUSTOM_GET_POST_COMMENTS(
        request: GetPostCommentsInput,
        execute_request: Any,
        auth_credentials: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Retrieve comments on a LinkedIn post."""
        user_id = _user_id(auth_credentials)
        encoded_urn = request.post_urn.replace(":", "%3A")

        result = proxy_request_sync(
            user_id=user_id,
            toolkit=LINKEDIN_TOOLKIT,
            endpoint=f"{LINKEDIN_REST_BASE}/socialActions/{encoded_urn}/comments",
            method="GET",
            query={"count": request.count, "start": request.start},
            headers=_REST_HEADERS,
        ) or {}

        comments = result.get("elements", [])

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
            "comments": formatted_comments,
            "total_count": result.get("paging", {}).get("total", len(comments)),
            "post_urn": request.post_urn,
        }

    @composio.tools.custom_tool(toolkit="LINKEDIN")
    @with_doc(CUSTOM_REACT_TO_POST_DOC)
    def CUSTOM_REACT_TO_POST(
        request: ReactToPostInput,
        execute_request: Any,
        auth_credentials: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Add a reaction to a LinkedIn post."""
        user_id = _user_id(auth_credentials)

        author_urn = get_author_urn(user_id)
        encoded_urn = request.post_urn.replace(":", "%3A")

        proxy_request_sync(
            user_id=user_id,
            toolkit=LINKEDIN_TOOLKIT,
            endpoint=f"{LINKEDIN_REST_BASE}/socialActions/{encoded_urn}/likes",
            method="POST",
            body={"actor": author_urn, "reactionType": request.reaction_type},
            headers=_REST_HEADERS,
        )

        return {
            "post_urn": request.post_urn,
            "reaction_type": request.reaction_type,
            "author": author_urn,
        }

    @composio.tools.custom_tool(toolkit="LINKEDIN")
    @with_doc(CUSTOM_DELETE_REACTION_DOC)
    def CUSTOM_DELETE_REACTION(
        request: DeleteReactionInput,
        execute_request: Any,
        auth_credentials: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Remove your reaction from a LinkedIn post."""
        user_id = _user_id(auth_credentials)

        author_urn = get_author_urn(user_id)
        encoded_post_urn = request.post_urn.replace(":", "%3A")
        encoded_author_urn = author_urn.replace(":", "%3A")

        proxy_request_sync(
            user_id=user_id,
            toolkit=LINKEDIN_TOOLKIT,
            endpoint=(
                f"{LINKEDIN_REST_BASE}/socialActions/"
                f"{encoded_post_urn}/likes/{encoded_author_urn}"
            ),
            method="DELETE",
            headers=_REST_HEADERS,
        )

        return {
            "post_urn": request.post_urn,
            "message": "Reaction removed successfully",
        }

    @composio.tools.custom_tool(toolkit="LINKEDIN")
    @with_doc(CUSTOM_GET_POST_REACTIONS_DOC)
    def CUSTOM_GET_POST_REACTIONS(
        request: GetPostReactionsInput,
        execute_request: Any,
        auth_credentials: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Retrieve reactions on a LinkedIn post."""
        user_id = _user_id(auth_credentials)
        encoded_urn = request.post_urn.replace(":", "%3A")

        result = proxy_request_sync(
            user_id=user_id,
            toolkit=LINKEDIN_TOOLKIT,
            endpoint=f"{LINKEDIN_REST_BASE}/socialActions/{encoded_urn}/likes",
            method="GET",
            query={"count": request.count},
            headers=_REST_HEADERS,
        ) or {}

        reactions = result.get("elements", [])

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
            "reactions": formatted_reactions,
            "total_count": result.get("paging", {}).get("total", len(reactions)),
            "post_urn": request.post_urn,
        }

    @composio.tools.custom_tool(toolkit="LINKEDIN")
    def CUSTOM_GATHER_CONTEXT(
        request: GatherContextInput,
        execute_request: Any,
        auth_credentials: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Get LinkedIn context snapshot: authenticated user profile info and recent posts.

        Zero required parameters. Returns user identity information and up to 5
        recent posts authored by the authenticated user.
        """
        user_id = _user_id(auth_credentials)

        data = proxy_request_sync(
            user_id=user_id,
            toolkit=LINKEDIN_TOOLKIT,
            endpoint=f"{LINKEDIN_API_BASE}/userinfo",
            method="GET",
        ) or {}

        person_id = data.get("sub", "")
        person_urn = f"urn:li:person:{person_id}"

        posts: List[Dict[str, Any]] = []
        if person_id:
            try:
                encoded_urn = person_urn.replace(":", "%3A")
                posts_data = proxy_request_sync(
                    user_id=user_id,
                    toolkit=LINKEDIN_TOOLKIT,
                    endpoint=f"{LINKEDIN_API_BASE}/ugcPosts",
                    method="GET",
                    query={
                        "q": "authors",
                        "authors": f"List({encoded_urn})",
                        "count": 5,
                    },
                ) or {}
                posts = posts_data.get("elements", [])
            except Exception:
                posts = []

        return {
            "user": {
                "id": person_id,
                "name": data.get("name"),
                "given_name": data.get("given_name"),
                "family_name": data.get("family_name"),
                "email": data.get("email"),
                "profile_picture": data.get("picture"),
            },
            "recent_posts": [
                {
                    "id": post.get("id"),
                    "text": post.get("specificContent", {})
                    .get("com.linkedin.ugc.ShareContent", {})
                    .get("shareCommentary", {})
                    .get("text", "")[:200],
                    "created": post.get("created", {}).get("time"),
                    "visibility": post.get("visibility", {}).get(
                        "com.linkedin.ugc.MemberNetworkVisibility"
                    ),
                }
                for post in posts
            ],
        }

    return [
        "LINKEDIN_CUSTOM_CREATE_POST",
        "LINKEDIN_CUSTOM_ADD_COMMENT",
        "LINKEDIN_CUSTOM_GET_POST_COMMENTS",
        "LINKEDIN_CUSTOM_REACT_TO_POST",
        "LINKEDIN_CUSTOM_DELETE_REACTION",
        "LINKEDIN_CUSTOM_GET_POST_REACTIONS",
        "LINKEDIN_CUSTOM_GATHER_CONTEXT",
    ]
