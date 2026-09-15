"""LinkedIn tools using Composio custom tool infrastructure.

LinkedIn API calls go through Composio's proxy via proxy_request_sync/
proxy_request_full_sync. The proxy attaches OAuth server-side; tools
only need user_id from auth_credentials.

Note: Errors are raised as exceptions - Composio wraps responses automatically.
"""

from composio import Composio
from composio.types import ExecuteRequestFn

from app.constants.log_tags import LogTag
from app.decorators.documentation import with_doc
from app.models.common_models import GatherContextInput
from app.models.integrations.composio import CustomToolAuthCredentials
from app.models.integrations.linkedin import (
    LinkedInArticleContent,
    LinkedInCommentList,
    LinkedInCommentMessage,
    LinkedInCommentRequest,
    LinkedInCreatedComment,
    LinkedInImageRef,
    LinkedInMediaContent,
    LinkedInMultiImageContent,
    LinkedInPostContent,
    LinkedInPostRequest,
    LinkedInProfile,
    LinkedInReactionList,
    LinkedInReactionRequest,
    LinkedInRestliResponse,
    LinkedInUgcPost,
    LinkedInUgcPostList,
)
from app.models.linkedin_models import (
    AddCommentInput,
    CreatePostInput,
    DeleteReactionInput,
    GetPostCommentsInput,
    GetPostReactionsInput,
    ReactToPostInput,
)
from app.services.composio.proxy_client import (
    ProxyRequest,
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
from shared.py.wide_events import log

LINKEDIN_API_BASE = "https://api.linkedin.com/v2"
LINKEDIN_VERSION = "202401"
_REST_HEADERS = {
    "Content-Type": "application/json",
    "X-Restli-Protocol-Version": "2.0.0",
    "LinkedIn-Version": LINKEDIN_VERSION,
}


def _user_id(auth_credentials: dict[str, object]) -> str:
    return CustomToolAuthCredentials.parse(auth_credentials).user_id


def register_linkedin_custom_tools(composio: Composio) -> list[str]:
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
        content: LinkedInPostContent | None = None

        if request.document_url:
            media_type = "document"
            if not request.document_title:
                raise ValueError("document_title is required when document_url is provided")
            document_urn = upload_document_from_url(user_id, request.document_url, author_urn)
            if not document_urn:
                raise RuntimeError("Failed to upload document to LinkedIn")
            content = LinkedInPostContent(
                media=LinkedInMediaContent(title=request.document_title, id=document_urn)
            )

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
                content = LinkedInPostContent(
                    media=LinkedInMediaContent(title=request.image_title or "", id=image_urns[0])
                )
            else:
                media_type = "carousel"
                content = LinkedInPostContent(
                    multi_image=LinkedInMultiImageContent(
                        images=[LinkedInImageRef(id=urn) for urn in image_urns]
                    )
                )

        elif request.article_url:
            media_type = "article"
            article_content = LinkedInArticleContent(
                source=request.article_url,
                title=request.article_title or None,
                description=request.article_description or None,
            )
            if request.thumbnail_url:
                article_content.thumbnail = (
                    upload_image_from_url(user_id, request.thumbnail_url, author_urn) or None
                )
            content = LinkedInPostContent(article=article_content)

        post_data = LinkedInPostRequest(
            author=author_urn,
            commentary=request.commentary,
            visibility=request.visibility,
            content=content,
        )

        response = LinkedInRestliResponse.model_validate(
            proxy_request_full_sync(
                ProxyRequest(
                    user_id=user_id,
                    toolkit=LINKEDIN_TOOLKIT,
                    endpoint=f"{LINKEDIN_REST_BASE}/posts",
                    method="POST",
                    body=post_data.body(),
                    headers=_REST_HEADERS,
                )
            )
        )

        post_id = response.headers.get("x-restli-id", "")

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

        comment_data = LinkedInCommentRequest(
            actor=author_urn,
            message=LinkedInCommentMessage(text=request.comment_text),
            parent_comment=request.parent_comment_urn or None,
        )

        response = LinkedInRestliResponse.model_validate(
            proxy_request_full_sync(
                ProxyRequest(
                    user_id=user_id,
                    toolkit=LINKEDIN_TOOLKIT,
                    endpoint=f"{LINKEDIN_REST_BASE}/socialActions/{encoded_urn}/comments",
                    method="POST",
                    body=comment_data.body(),
                    headers=_REST_HEADERS,
                )
            )
        )

        body = response.data
        created = LinkedInCreatedComment.model_validate(body) if isinstance(body, dict) else None
        comment_id = (created.id if created else None) or response.headers.get("x-restli-id", "")

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

        result = LinkedInCommentList.model_validate(
            proxy_request_sync(
                ProxyRequest(
                    user_id=user_id,
                    toolkit=LINKEDIN_TOOLKIT,
                    endpoint=f"{LINKEDIN_REST_BASE}/socialActions/{encoded_urn}/comments",
                    method="GET",
                    query={"count": request.count, "start": request.start},
                    headers=_REST_HEADERS,
                )
            )
        )

        comments = result.elements
        total = result.paging.total if result.paging and result.paging.total is not None else None

        return {
            "comments": [
                {
                    "id": comment.id,
                    "author": comment.actor,
                    "text": comment.message.text,
                    "created_at": comment.created.time,
                    "parent_comment": comment.parent_comment,
                }
                for comment in comments
            ],
            "total_count": len(comments) if total is None else total,
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
            ProxyRequest(
                user_id=user_id,
                toolkit=LINKEDIN_TOOLKIT,
                endpoint=f"{LINKEDIN_REST_BASE}/socialActions/{encoded_urn}/likes",
                method="POST",
                body=LinkedInReactionRequest(
                    actor=author_urn, reaction_type=request.reaction_type
                ).body(),
                headers=_REST_HEADERS,
            )
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
            ProxyRequest(
                user_id=user_id,
                toolkit=LINKEDIN_TOOLKIT,
                endpoint=(
                    f"{LINKEDIN_REST_BASE}/socialActions/{encoded_post_urn}/likes/{encoded_author_urn}"
                ),
                method="DELETE",
                headers=_REST_HEADERS,
            )
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

        result = LinkedInReactionList.model_validate(
            proxy_request_sync(
                ProxyRequest(
                    user_id=user_id,
                    toolkit=LINKEDIN_TOOLKIT,
                    endpoint=f"{LINKEDIN_REST_BASE}/socialActions/{encoded_urn}/likes",
                    method="GET",
                    query={"count": request.count},
                    headers=_REST_HEADERS,
                )
            )
        )

        reactions = result.elements
        total = result.paging.total if result.paging and result.paging.total is not None else None

        return {
            "reactions": [
                {
                    "actor": reaction.actor,
                    "reaction_type": reaction.reaction_type,
                    "created_at": reaction.created.time,
                }
                for reaction in reactions
            ],
            "total_count": len(reactions) if total is None else total,
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

        profile = LinkedInProfile.model_validate(
            proxy_request_sync(
                ProxyRequest(
                    user_id=user_id,
                    toolkit=LINKEDIN_TOOLKIT,
                    endpoint=f"{LINKEDIN_API_BASE}/userinfo",
                    method="GET",
                )
            )
        )
        person_urn = f"urn:li:person:{profile.sub}"

        posts: list[LinkedInUgcPost] = []
        try:
            encoded_urn = person_urn.replace(":", "%3A")
            posts = LinkedInUgcPostList.model_validate(
                proxy_request_sync(
                    ProxyRequest(
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
                )
            ).elements
        except Exception as e:
            # The profile is still useful without recent posts (the ugcPosts
            # scope is optional), so this returns a partial snapshot.
            log.warning(
                f"{LogTag.TOOL} LinkedIn recent posts fetch failed, returning profile without them",
                user_id=user_id,
                error=str(e),
                error_type=type(e).__name__,
            )

        return {
            "user": {
                "id": profile.sub,
                "name": profile.name,
                "given_name": profile.given_name,
                "family_name": profile.family_name,
                "email": profile.email,
                "profile_picture": profile.picture,
            },
            "recent_posts": [
                {
                    "id": post.id,
                    "text": post.text[:200],
                    "created": post.created.time,
                    "visibility": post.visibility.member_network_visibility,
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
