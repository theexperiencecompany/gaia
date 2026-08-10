"""LinkedIn tools using Composio custom tool infrastructure.

LinkedIn API calls go through Composio's proxy via `proxy_request_sync`/
`proxy_request_full_sync`. The proxy attaches OAuth server-side; tools
only need `user_id` from `auth_credentials`.

Note: Errors are raised as exceptions - Composio wraps responses automatically.
"""

from typing import Any

from composio import Composio
from composio.types import ExecuteRequestFn

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
from app.utils.json_helpers import dict_bag, int_bag, list_bag, text_bag, text_opt_bag
from app.utils.linkedin_utils import (
    LINKEDIN_REST_BASE,
    LINKEDIN_TOOLKIT,
    get_author_urn,
    upload_document_from_url,
    upload_image_from_url,
)

LINKEDIN_API_BASE = "https://api.linkedin.com/v2"
LINKEDIN_VERSION = "202401"
_REST_HEADERS = {
    "Content-Type": "application/json",
    "X-Restli-Protocol-Version": "2.0.0",
    "LinkedIn-Version": LINKEDIN_VERSION,
}


def _user_id(auth_credentials: dict[str, object]) -> str:
    user_id = auth_credentials.get("user_id")
    if not isinstance(user_id, str) or not user_id:
        raise ValueError("Missing user_id in auth_credentials")
    return user_id


def register_linkedin_custom_tools(composio: Composio[Any, Any]) -> list[str]:  # type: ignore[explicit-any]
    """Register LinkedIn tools as Composio custom tools."""

    @composio.tools.custom_tool(toolkit="LINKEDIN")
    @with_doc(CUSTOM_CREATE_POST_DOC)
    def CUSTOM_CREATE_POST(
        request: CreatePostInput,
        execute_request: ExecuteRequestFn,
        auth_credentials: dict[str, object],
    ) -> dict[str, object]:
        """Create a LinkedIn post with optional media (image, document, or article)."""
        del execute_request  # unused: framework-mandated custom-tool signature
        user_id = _user_id(auth_credentials)

        author_urn = get_author_urn(user_id, request.organization_id)

        media_type = "text"
        content: dict[str, object] | None = None

        if request.document_url:
            media_type = "document"
            if not request.document_title:
                raise ValueError("document_title is required when document_url is provided")
            document_urn = upload_document_from_url(user_id, request.document_url, author_urn)
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
                content = {"multiImage": {"images": [{"id": urn} for urn in image_urns]}}

        elif request.article_url:
            media_type = "article"
            article_content: dict[str, object] = {
                "source": request.article_url,
            }
            if request.article_title:
                article_content["title"] = request.article_title
            if request.article_description:
                article_content["description"] = request.article_description
            if request.thumbnail_url:
                thumbnail_urn = upload_image_from_url(user_id, request.thumbnail_url, author_urn)
                if thumbnail_urn:
                    article_content["thumbnail"] = thumbnail_urn
            content = {"article": article_content}

        post_data: dict[str, object] = {
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
        execute_request: ExecuteRequestFn,
        auth_credentials: dict[str, object],
    ) -> dict[str, object]:
        """Add a comment to a LinkedIn post."""
        del execute_request  # unused: framework-mandated custom-tool signature
        user_id = _user_id(auth_credentials)

        author_urn = get_author_urn(user_id)
        encoded_urn = request.post_urn.replace(":", "%3A")

        comment_data: dict[str, object] = {
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
        comment_id = (body.get("id") if isinstance(body, dict) else None) or response.get(
            "headers", {}
        ).get("x-restli-id", "")

        return {
            "comment_id": comment_id,
            "post_urn": request.post_urn,
            "author": author_urn,
        }

    @composio.tools.custom_tool(toolkit="LINKEDIN")
    @with_doc(CUSTOM_GET_POST_COMMENTS_DOC)
    def CUSTOM_GET_POST_COMMENTS(
        request: GetPostCommentsInput,
        execute_request: ExecuteRequestFn,
        auth_credentials: dict[str, object],
    ) -> dict[str, object]:
        """Retrieve comments on a LinkedIn post."""
        del execute_request  # unused: framework-mandated custom-tool signature
        user_id = _user_id(auth_credentials)
        encoded_urn = request.post_urn.replace(":", "%3A")

        result = proxy_request_sync(
            user_id=user_id,
            toolkit=LINKEDIN_TOOLKIT,
            endpoint=f"{LINKEDIN_REST_BASE}/socialActions/{encoded_urn}/comments",
            method="GET",
            query={"count": request.count, "start": request.start},
            headers=_REST_HEADERS,
        )

        comments = list_bag(result if isinstance(result, dict) else {}, "elements")

        formatted_comments = []
        for comment in comments:
            if not isinstance(comment, dict):
                continue
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
            "total_count": int_bag(
                dict_bag(result if isinstance(result, dict) else {}, "paging"),
                "total",
                len(comments),
            ),
            "post_urn": request.post_urn,
        }

    @composio.tools.custom_tool(toolkit="LINKEDIN")
    @with_doc(CUSTOM_REACT_TO_POST_DOC)
    def CUSTOM_REACT_TO_POST(
        request: ReactToPostInput,
        execute_request: ExecuteRequestFn,
        auth_credentials: dict[str, object],
    ) -> dict[str, object]:
        """Add a reaction to a LinkedIn post."""
        del execute_request  # unused: framework-mandated custom-tool signature
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
        execute_request: ExecuteRequestFn,
        auth_credentials: dict[str, object],
    ) -> dict[str, object]:
        """Remove your reaction from a LinkedIn post."""
        del execute_request  # unused: framework-mandated custom-tool signature
        user_id = _user_id(auth_credentials)

        author_urn = get_author_urn(user_id)
        encoded_post_urn = request.post_urn.replace(":", "%3A")
        encoded_author_urn = author_urn.replace(":", "%3A")

        proxy_request_sync(
            user_id=user_id,
            toolkit=LINKEDIN_TOOLKIT,
            endpoint=(
                f"{LINKEDIN_REST_BASE}/socialActions/{encoded_post_urn}/likes/{encoded_author_urn}"
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
        execute_request: ExecuteRequestFn,
        auth_credentials: dict[str, object],
    ) -> dict[str, object]:
        """Retrieve reactions on a LinkedIn post."""
        del execute_request  # unused: framework-mandated custom-tool signature
        user_id = _user_id(auth_credentials)
        encoded_urn = request.post_urn.replace(":", "%3A")

        result = proxy_request_sync(
            user_id=user_id,
            toolkit=LINKEDIN_TOOLKIT,
            endpoint=f"{LINKEDIN_REST_BASE}/socialActions/{encoded_urn}/likes",
            method="GET",
            query={"count": request.count},
            headers=_REST_HEADERS,
        )

        reactions = list_bag(result if isinstance(result, dict) else {}, "elements")

        formatted_reactions = []
        for reaction in reactions:
            if not isinstance(reaction, dict):
                continue
            formatted_reactions.append(
                {
                    "actor": reaction.get("actor"),
                    "reaction_type": reaction.get("reactionType", "LIKE"),
                    "created_at": reaction.get("created", {}).get("time"),
                }
            )

        return {
            "reactions": formatted_reactions,
            "total_count": int_bag(
                dict_bag(result if isinstance(result, dict) else {}, "paging"),
                "total",
                len(reactions),
            ),
            "post_urn": request.post_urn,
        }

    @composio.tools.custom_tool(toolkit="LINKEDIN")
    def CUSTOM_GATHER_CONTEXT(
        request: GatherContextInput,
        execute_request: ExecuteRequestFn,
        auth_credentials: dict[str, object],
    ) -> dict[str, object]:
        """Get LinkedIn context snapshot: authenticated user profile info and recent posts.

        Zero required parameters. Returns user identity information and up to 5
        recent posts authored by the authenticated user.
        """
        del request, execute_request  # unused: framework-mandated custom-tool signature
        user_id = _user_id(auth_credentials)

        data = proxy_request_sync(
            user_id=user_id,
            toolkit=LINKEDIN_TOOLKIT,
            endpoint=f"{LINKEDIN_API_BASE}/userinfo",
            method="GET",
        )

        person_id = text_bag(data if isinstance(data, dict) else {}, "sub")
        person_urn = f"urn:li:person:{person_id}"

        posts: list[dict[str, object]] = []
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
                )
                posts = [
                    p
                    for p in list_bag(
                        posts_data if isinstance(posts_data, dict) else {}, "elements"
                    )
                    if isinstance(p, dict)
                ]
            except Exception:
                posts = []

        return {
            "user": {
                "id": person_id,
                "name": text_opt_bag(data, "name") if isinstance(data, dict) else None,
                "given_name": text_opt_bag(data, "given_name") if isinstance(data, dict) else None,
                "family_name": text_opt_bag(data, "family_name")
                if isinstance(data, dict)
                else None,
                "email": text_opt_bag(data, "email") if isinstance(data, dict) else None,
                "profile_picture": text_opt_bag(data, "picture")
                if isinstance(data, dict)
                else None,
            },
            "recent_posts": [
                {
                    "id": post.get("id"),
                    "text": text_bag(
                        dict_bag(
                            dict_bag(
                                dict_bag(post, "specificContent"), "com.linkedin.ugc.ShareContent"
                            ),
                            "shareCommentary",
                        ),
                        "text",
                    )[:200],
                    "created": int_bag(dict_bag(post, "created"), "time"),
                    "visibility": text_opt_bag(
                        dict_bag(post, "visibility"), "com.linkedin.ugc.MemberNetworkVisibility"
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
