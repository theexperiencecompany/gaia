"""Behavior tests for the LinkedIn custom tools.

The proxy smoke test (test_integration_tools_proxy.py) proves two of the tools
route through the proxy; these tests pin the exact ProxyRequest each tool
sends (user, toolkit, endpoint, method, body/query, headers) and what it
returns from the proxy's response. The true I/O boundaries are the seams:
`proxy_request_sync` / `proxy_request_full_sync` and the linkedin_utils
helpers that themselves hit the proxy (`get_author_urn`, the uploaders).
"""

from collections.abc import Callable, Iterator
from typing import Any
from unittest.mock import MagicMock, call, patch

import pytest

from app.agents.tools.integrations.linkedin_tool import register_linkedin_custom_tools
from app.models.common_models import GatherContextInput
from app.models.linkedin_models import (
    AddCommentInput,
    CreatePostInput,
    DeleteReactionInput,
    GetPostCommentsInput,
    GetPostReactionsInput,
    ReactToPostInput,
)
from app.services.composio.proxy_client import ProxyRequest

MODULE = "app.agents.tools.integrations.linkedin_tool"

USER_ID = "user_test_123"
AUTH_CREDS: dict[str, Any] = {"user_id": USER_ID}
EXECUTE_REQUEST = MagicMock()
AUTHOR_URN = "urn:li:person:abc"
POST_URN = "urn:li:share:12345"
ENCODED_POST_URN = "urn%3Ali%3Ashare%3A12345"
REST_HEADERS = {
    "Content-Type": "application/json",
    "X-Restli-Protocol-Version": "2.0.0",
    "LinkedIn-Version": "202401",
}

EXPECTED_TOOL_NAMES = [
    "LINKEDIN_CUSTOM_CREATE_POST",
    "LINKEDIN_CUSTOM_ADD_COMMENT",
    "LINKEDIN_CUSTOM_GET_POST_COMMENTS",
    "LINKEDIN_CUSTOM_REACT_TO_POST",
    "LINKEDIN_CUSTOM_DELETE_REACTION",
    "LINKEDIN_CUSTOM_GET_POST_REACTIONS",
    "LINKEDIN_CUSTOM_GATHER_CONTEXT",
]


def _capture_tools() -> tuple[list[str], dict[str, Callable[..., Any]], list[dict[str, Any]]]:
    tools: dict[str, Callable[..., Any]] = {}
    toolkits: list[dict[str, Any]] = []
    composio = MagicMock()

    def custom_tool(**kwargs: Any) -> Callable[[Any], Any]:
        toolkits.append(kwargs)

        def decorator(fn: Any) -> Any:
            tools[fn.__name__] = fn
            return fn

        return decorator

    composio.tools.custom_tool = custom_tool
    registered = register_linkedin_custom_tools(composio)
    return registered, tools, toolkits


@pytest.fixture
def tools() -> dict[str, Callable[..., Any]]:
    return _capture_tools()[1]


@pytest.fixture
def proxy() -> Iterator[MagicMock]:
    with patch(f"{MODULE}.proxy_request_sync") as mock:
        mock.return_value = {}
        yield mock


@pytest.fixture
def proxy_full() -> Iterator[MagicMock]:
    with patch(f"{MODULE}.proxy_request_full_sync") as mock:
        mock.return_value = {"status": 201, "data": None, "headers": {}}
        yield mock


@pytest.fixture
def author_urn() -> Iterator[MagicMock]:
    with patch(f"{MODULE}.get_author_urn", return_value=AUTHOR_URN) as mock:
        yield mock


@pytest.fixture
def upload_image() -> Iterator[MagicMock]:
    with patch(f"{MODULE}.upload_image_from_url") as mock:
        yield mock


@pytest.fixture
def upload_document() -> Iterator[MagicMock]:
    with patch(f"{MODULE}.upload_document_from_url") as mock:
        yield mock


def _text_post_body(author: str = AUTHOR_URN, commentary: str = "Hello") -> dict[str, Any]:
    return {
        "author": author,
        "commentary": commentary,
        "visibility": "PUBLIC",
        "distribution": {
            "feedDistribution": "MAIN_FEED",
            "targetEntities": [],
            "thirdPartyDistributionChannels": [],
        },
        "lifecycleState": "PUBLISHED",
        "isReshareDisabledByAuthor": False,
    }


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------


def test_register_returns_exact_tool_names_under_linkedin_toolkit() -> None:
    registered, tools, toolkits = _capture_tools()

    assert registered == EXPECTED_TOOL_NAMES
    assert [f"LINKEDIN_{name}" for name in tools] == EXPECTED_TOOL_NAMES
    assert toolkits == [{"toolkit": "LINKEDIN"}] * len(EXPECTED_TOOL_NAMES)


@pytest.mark.parametrize(
    "tool_name,request_input",
    [
        ("CUSTOM_CREATE_POST", CreatePostInput(commentary="Hello")),
        ("CUSTOM_ADD_COMMENT", AddCommentInput(post_urn=POST_URN, comment_text="hi")),
        ("CUSTOM_GET_POST_COMMENTS", GetPostCommentsInput(post_urn=POST_URN)),
        ("CUSTOM_REACT_TO_POST", ReactToPostInput(post_urn=POST_URN)),
        ("CUSTOM_DELETE_REACTION", DeleteReactionInput(post_urn=POST_URN)),
        ("CUSTOM_GET_POST_REACTIONS", GetPostReactionsInput(post_urn=POST_URN)),
        ("CUSTOM_GATHER_CONTEXT", GatherContextInput()),
    ],
)
def test_missing_user_id_raises_before_any_proxy_call(
    tools: dict[str, Callable[..., Any]],
    proxy: MagicMock,
    proxy_full: MagicMock,
    author_urn: MagicMock,
    tool_name: str,
    request_input: Any,
) -> None:
    with pytest.raises(ValueError, match="Missing user_id"):
        tools[tool_name](request_input, EXECUTE_REQUEST, {"user_id": ""})

    proxy.assert_not_called()
    proxy_full.assert_not_called()
    author_urn.assert_not_called()


# ---------------------------------------------------------------------------
# CUSTOM_CREATE_POST
# ---------------------------------------------------------------------------


class TestCreatePost:
    def test_text_post_sends_exact_rest_request_and_returns_post_url(
        self,
        tools: dict[str, Callable[..., Any]],
        proxy_full: MagicMock,
        author_urn: MagicMock,
    ) -> None:
        proxy_full.return_value = {
            "status": 201,
            "data": None,
            "headers": {"x-restli-id": "urn:li:share:999"},
        }

        result = tools["CUSTOM_CREATE_POST"](
            CreatePostInput(commentary="Hello"), EXECUTE_REQUEST, AUTH_CREDS
        )

        author_urn.assert_called_once_with(USER_ID, None)
        assert proxy_full.call_args_list == [
            call(
                ProxyRequest(
                    user_id=USER_ID,
                    toolkit="LINKEDIN",
                    endpoint="https://api.linkedin.com/rest/posts",
                    method="POST",
                    body=_text_post_body(),
                    headers=REST_HEADERS,
                )
            )
        ]
        assert result == {
            "post_id": "urn:li:share:999",
            "url": "https://www.linkedin.com/feed/update/urn:li:share:999",
            "author": AUTHOR_URN,
            "media_type": "text",
        }

    def test_organization_post_uses_org_author_and_visibility(
        self,
        tools: dict[str, Callable[..., Any]],
        proxy_full: MagicMock,
        author_urn: MagicMock,
    ) -> None:
        author_urn.return_value = "urn:li:organization:42"

        result = tools["CUSTOM_CREATE_POST"](
            CreatePostInput(commentary="Org", organization_id="42", visibility="CONNECTIONS"),
            EXECUTE_REQUEST,
            AUTH_CREDS,
        )

        author_urn.assert_called_once_with(USER_ID, "42")
        body = proxy_full.call_args.args[0].body
        assert body["author"] == "urn:li:organization:42"
        assert body["visibility"] == "CONNECTIONS"
        assert "content" not in body
        assert result["author"] == "urn:li:organization:42"
        assert result["post_id"] == ""
        assert result["url"] == "https://www.linkedin.com/feed/update/"

    def test_document_post_uploads_then_attaches_media(
        self,
        tools: dict[str, Callable[..., Any]],
        proxy_full: MagicMock,
        author_urn: MagicMock,
        upload_document: MagicMock,
    ) -> None:
        upload_document.return_value = "urn:li:document:d1"

        result = tools["CUSTOM_CREATE_POST"](
            CreatePostInput(
                commentary="Doc",
                document_url="https://src/doc.pdf",
                document_title="Q3 deck",
            ),
            EXECUTE_REQUEST,
            AUTH_CREDS,
        )

        upload_document.assert_called_once_with(USER_ID, "https://src/doc.pdf", AUTHOR_URN)
        assert proxy_full.call_args.args[0].body["content"] == {
            "media": {"title": "Q3 deck", "id": "urn:li:document:d1"}
        }
        assert result["media_type"] == "document"

    def test_document_without_title_raises_before_upload(
        self,
        tools: dict[str, Callable[..., Any]],
        proxy_full: MagicMock,
        author_urn: MagicMock,
        upload_document: MagicMock,
    ) -> None:
        with pytest.raises(ValueError, match="document_title is required"):
            tools["CUSTOM_CREATE_POST"](
                CreatePostInput(commentary="Doc", document_url="https://src/doc.pdf"),
                EXECUTE_REQUEST,
                AUTH_CREDS,
            )

        upload_document.assert_not_called()
        proxy_full.assert_not_called()

    def test_document_upload_failure_raises_and_does_not_post(
        self,
        tools: dict[str, Callable[..., Any]],
        proxy_full: MagicMock,
        author_urn: MagicMock,
        upload_document: MagicMock,
    ) -> None:
        upload_document.return_value = None

        with pytest.raises(RuntimeError, match="Failed to upload document"):
            tools["CUSTOM_CREATE_POST"](
                CreatePostInput(
                    commentary="Doc", document_url="https://src/doc.pdf", document_title="t"
                ),
                EXECUTE_REQUEST,
                AUTH_CREDS,
            )

        proxy_full.assert_not_called()

    def test_single_image_post_attaches_image_media(
        self,
        tools: dict[str, Callable[..., Any]],
        proxy_full: MagicMock,
        author_urn: MagicMock,
        upload_image: MagicMock,
    ) -> None:
        upload_image.return_value = "urn:li:image:i1"

        result = tools["CUSTOM_CREATE_POST"](
            CreatePostInput(commentary="Pic", image_url="https://src/a.jpg", image_title="A"),
            EXECUTE_REQUEST,
            AUTH_CREDS,
        )

        upload_image.assert_called_once_with(USER_ID, "https://src/a.jpg", AUTHOR_URN)
        assert proxy_full.call_args.args[0].body["content"] == {
            "media": {"title": "A", "id": "urn:li:image:i1"}
        }
        assert result["media_type"] == "image"

    def test_single_image_without_title_sends_empty_title(
        self,
        tools: dict[str, Callable[..., Any]],
        proxy_full: MagicMock,
        author_urn: MagicMock,
        upload_image: MagicMock,
    ) -> None:
        upload_image.return_value = "urn:li:image:i1"

        tools["CUSTOM_CREATE_POST"](
            CreatePostInput(commentary="Pic", image_url="https://src/a.jpg"),
            EXECUTE_REQUEST,
            AUTH_CREDS,
        )

        assert proxy_full.call_args.args[0].body["content"]["media"]["title"] == ""

    def test_multiple_images_build_carousel_in_order(
        self,
        tools: dict[str, Callable[..., Any]],
        proxy_full: MagicMock,
        author_urn: MagicMock,
        upload_image: MagicMock,
    ) -> None:
        upload_image.side_effect = ["urn:li:image:1", "urn:li:image:2"]

        result = tools["CUSTOM_CREATE_POST"](
            CreatePostInput(commentary="Pics", image_urls=["https://src/1", "https://src/2"]),
            EXECUTE_REQUEST,
            AUTH_CREDS,
        )

        assert [c.args for c in upload_image.call_args_list] == [
            (USER_ID, "https://src/1", AUTHOR_URN),
            (USER_ID, "https://src/2", AUTHOR_URN),
        ]
        assert proxy_full.call_args.args[0].body["content"] == {
            "multiImage": {"images": [{"id": "urn:li:image:1"}, {"id": "urn:li:image:2"}]}
        }
        assert result["media_type"] == "carousel"

    def test_more_than_twenty_images_raises_before_upload(
        self,
        tools: dict[str, Callable[..., Any]],
        proxy_full: MagicMock,
        author_urn: MagicMock,
        upload_image: MagicMock,
    ) -> None:
        with pytest.raises(ValueError, match="Maximum 20 images"):
            tools["CUSTOM_CREATE_POST"](
                CreatePostInput(
                    commentary="Pics", image_urls=[f"https://src/{i}" for i in range(21)]
                ),
                EXECUTE_REQUEST,
                AUTH_CREDS,
            )

        upload_image.assert_not_called()
        proxy_full.assert_not_called()

    def test_image_upload_failure_names_the_url(
        self,
        tools: dict[str, Callable[..., Any]],
        proxy_full: MagicMock,
        author_urn: MagicMock,
        upload_image: MagicMock,
    ) -> None:
        upload_image.side_effect = ["urn:li:image:1", None]

        with pytest.raises(RuntimeError, match="Failed to upload image: https://src/2"):
            tools["CUSTOM_CREATE_POST"](
                CreatePostInput(commentary="Pics", image_urls=["https://src/1", "https://src/2"]),
                EXECUTE_REQUEST,
                AUTH_CREDS,
            )

        proxy_full.assert_not_called()

    def test_article_post_includes_only_provided_fields_and_thumbnail(
        self,
        tools: dict[str, Callable[..., Any]],
        proxy_full: MagicMock,
        author_urn: MagicMock,
        upload_image: MagicMock,
    ) -> None:
        upload_image.return_value = "urn:li:image:thumb"

        result = tools["CUSTOM_CREATE_POST"](
            CreatePostInput(
                commentary="Read",
                article_url="https://blog/post",
                article_title="Title",
                thumbnail_url="https://src/t.png",
            ),
            EXECUTE_REQUEST,
            AUTH_CREDS,
        )

        upload_image.assert_called_once_with(USER_ID, "https://src/t.png", AUTHOR_URN)
        assert proxy_full.call_args.args[0].body["content"] == {
            "article": {
                "source": "https://blog/post",
                "title": "Title",
                "thumbnail": "urn:li:image:thumb",
            }
        }
        assert result["media_type"] == "article"

    def test_article_thumbnail_upload_failure_is_tolerated(
        self,
        tools: dict[str, Callable[..., Any]],
        proxy_full: MagicMock,
        author_urn: MagicMock,
        upload_image: MagicMock,
    ) -> None:
        upload_image.return_value = None

        tools["CUSTOM_CREATE_POST"](
            CreatePostInput(
                commentary="Read",
                article_url="https://blog/post",
                article_description="Desc",
                thumbnail_url="https://src/t.png",
            ),
            EXECUTE_REQUEST,
            AUTH_CREDS,
        )

        assert proxy_full.call_args.args[0].body["content"] == {
            "article": {"source": "https://blog/post", "description": "Desc"}
        }


# ---------------------------------------------------------------------------
# CUSTOM_ADD_COMMENT
# ---------------------------------------------------------------------------


class TestAddComment:
    def test_sends_exact_comment_request_and_returns_body_id(
        self,
        tools: dict[str, Callable[..., Any]],
        proxy_full: MagicMock,
        author_urn: MagicMock,
    ) -> None:
        proxy_full.return_value = {
            "status": 201,
            "data": {"id": "urn:li:comment:1"},
            "headers": {"x-restli-id": "header-id"},
        }

        result = tools["CUSTOM_ADD_COMMENT"](
            AddCommentInput(post_urn=POST_URN, comment_text="Nice"),
            EXECUTE_REQUEST,
            AUTH_CREDS,
        )

        author_urn.assert_called_once_with(USER_ID)
        assert proxy_full.call_args_list == [
            call(
                ProxyRequest(
                    user_id=USER_ID,
                    toolkit="LINKEDIN",
                    endpoint=(
                        f"https://api.linkedin.com/rest/socialActions/{ENCODED_POST_URN}/comments"
                    ),
                    method="POST",
                    body={"actor": AUTHOR_URN, "message": {"text": "Nice"}},
                    headers=REST_HEADERS,
                )
            )
        ]
        assert result == {
            "comment_id": "urn:li:comment:1",
            "post_urn": POST_URN,
            "author": AUTHOR_URN,
        }

    def test_reply_includes_parent_comment(
        self,
        tools: dict[str, Callable[..., Any]],
        proxy_full: MagicMock,
        author_urn: MagicMock,
    ) -> None:
        tools["CUSTOM_ADD_COMMENT"](
            AddCommentInput(
                post_urn=POST_URN, comment_text="Reply", parent_comment_urn="urn:li:comment:9"
            ),
            EXECUTE_REQUEST,
            AUTH_CREDS,
        )

        assert proxy_full.call_args.args[0].body == {
            "actor": AUTHOR_URN,
            "message": {"text": "Reply"},
            "parentComment": "urn:li:comment:9",
        }

    def test_falls_back_to_restli_id_header_when_body_has_no_id(
        self,
        tools: dict[str, Callable[..., Any]],
        proxy_full: MagicMock,
        author_urn: MagicMock,
    ) -> None:
        proxy_full.return_value = {
            "status": 201,
            "data": "",
            "headers": {"x-restli-id": "urn:li:comment:hdr"},
        }

        result = tools["CUSTOM_ADD_COMMENT"](
            AddCommentInput(post_urn=POST_URN, comment_text="Nice"),
            EXECUTE_REQUEST,
            AUTH_CREDS,
        )

        assert result["comment_id"] == "urn:li:comment:hdr"


# ---------------------------------------------------------------------------
# CUSTOM_GET_POST_COMMENTS
# ---------------------------------------------------------------------------


class TestGetPostComments:
    def test_sends_exact_paged_query_and_formats_comments(
        self, tools: dict[str, Callable[..., Any]], proxy: MagicMock
    ) -> None:
        proxy.return_value = {
            "elements": [
                {
                    "id": "c1",
                    "actor": "urn:li:person:x",
                    "message": {"text": "Great"},
                    "created": {"time": 1700000000000},
                    "parentComment": None,
                },
                {"id": "c2", "actor": "urn:li:person:y", "parentComment": "urn:li:comment:c1"},
            ],
            "paging": {"total": 57},
        }

        result = tools["CUSTOM_GET_POST_COMMENTS"](
            GetPostCommentsInput(post_urn=POST_URN, count=25, start=50),
            EXECUTE_REQUEST,
            AUTH_CREDS,
        )

        assert proxy.call_args_list == [
            call(
                ProxyRequest(
                    user_id=USER_ID,
                    toolkit="LINKEDIN",
                    endpoint=(
                        f"https://api.linkedin.com/rest/socialActions/{ENCODED_POST_URN}/comments"
                    ),
                    method="GET",
                    query={"count": 25, "start": 50},
                    headers=REST_HEADERS,
                )
            )
        ]
        assert result == {
            "comments": [
                {
                    "id": "c1",
                    "author": "urn:li:person:x",
                    "text": "Great",
                    "created_at": 1700000000000,
                    "parent_comment": None,
                },
                {
                    "id": "c2",
                    "author": "urn:li:person:y",
                    "text": "",
                    "created_at": None,
                    "parent_comment": "urn:li:comment:c1",
                },
            ],
            "total_count": 57,
            "post_urn": POST_URN,
        }

    def test_empty_proxy_response_yields_no_comments(
        self, tools: dict[str, Callable[..., Any]], proxy: MagicMock
    ) -> None:
        proxy.return_value = None

        result = tools["CUSTOM_GET_POST_COMMENTS"](
            GetPostCommentsInput(post_urn=POST_URN), EXECUTE_REQUEST, AUTH_CREDS
        )

        assert result == {"comments": [], "total_count": 0, "post_urn": POST_URN}

    def test_total_count_falls_back_to_element_count_without_paging(
        self, tools: dict[str, Callable[..., Any]], proxy: MagicMock
    ) -> None:
        proxy.return_value = {"elements": [{"id": "c1"}, {"id": "c2"}]}

        result = tools["CUSTOM_GET_POST_COMMENTS"](
            GetPostCommentsInput(post_urn=POST_URN), EXECUTE_REQUEST, AUTH_CREDS
        )

        assert result["total_count"] == 2


# ---------------------------------------------------------------------------
# CUSTOM_REACT_TO_POST
# ---------------------------------------------------------------------------


class TestReactToPost:
    def test_sends_exact_like_request_and_echoes_reaction(
        self,
        tools: dict[str, Callable[..., Any]],
        proxy: MagicMock,
        author_urn: MagicMock,
    ) -> None:
        result = tools["CUSTOM_REACT_TO_POST"](
            ReactToPostInput(post_urn=POST_URN, reaction_type="CELEBRATE"),
            EXECUTE_REQUEST,
            AUTH_CREDS,
        )

        author_urn.assert_called_once_with(USER_ID)
        assert proxy.call_args_list == [
            call(
                ProxyRequest(
                    user_id=USER_ID,
                    toolkit="LINKEDIN",
                    endpoint=(
                        f"https://api.linkedin.com/rest/socialActions/{ENCODED_POST_URN}/likes"
                    ),
                    method="POST",
                    body={"actor": AUTHOR_URN, "reactionType": "CELEBRATE"},
                    headers=REST_HEADERS,
                )
            )
        ]
        assert result == {
            "post_urn": POST_URN,
            "reaction_type": "CELEBRATE",
            "author": AUTHOR_URN,
        }


# ---------------------------------------------------------------------------
# CUSTOM_DELETE_REACTION
# ---------------------------------------------------------------------------


class TestDeleteReaction:
    def test_sends_exact_delete_request_keyed_by_encoded_actor(
        self,
        tools: dict[str, Callable[..., Any]],
        proxy: MagicMock,
        author_urn: MagicMock,
    ) -> None:
        result = tools["CUSTOM_DELETE_REACTION"](
            DeleteReactionInput(post_urn=POST_URN), EXECUTE_REQUEST, AUTH_CREDS
        )

        author_urn.assert_called_once_with(USER_ID)
        assert proxy.call_args_list == [
            call(
                ProxyRequest(
                    user_id=USER_ID,
                    toolkit="LINKEDIN",
                    endpoint=(
                        "https://api.linkedin.com/rest/socialActions/"
                        f"{ENCODED_POST_URN}/likes/urn%3Ali%3Aperson%3Aabc"
                    ),
                    method="DELETE",
                    headers=REST_HEADERS,
                )
            )
        ]
        assert result == {"post_urn": POST_URN, "message": "Reaction removed successfully"}


# ---------------------------------------------------------------------------
# CUSTOM_GET_POST_REACTIONS
# ---------------------------------------------------------------------------


class TestGetPostReactions:
    def test_sends_exact_query_and_formats_reactions(
        self, tools: dict[str, Callable[..., Any]], proxy: MagicMock
    ) -> None:
        proxy.return_value = {
            "elements": [
                {
                    "actor": "urn:li:person:x",
                    "reactionType": "LOVE",
                    "created": {"time": 1700000000000},
                },
                {"actor": "urn:li:person:y"},
            ],
            "paging": {"total": 3},
        }

        result = tools["CUSTOM_GET_POST_REACTIONS"](
            GetPostReactionsInput(post_urn=POST_URN, count=7), EXECUTE_REQUEST, AUTH_CREDS
        )

        assert proxy.call_args_list == [
            call(
                ProxyRequest(
                    user_id=USER_ID,
                    toolkit="LINKEDIN",
                    endpoint=(
                        f"https://api.linkedin.com/rest/socialActions/{ENCODED_POST_URN}/likes"
                    ),
                    method="GET",
                    query={"count": 7},
                    headers=REST_HEADERS,
                )
            )
        ]
        assert result == {
            "reactions": [
                {
                    "actor": "urn:li:person:x",
                    "reaction_type": "LOVE",
                    "created_at": 1700000000000,
                },
                {"actor": "urn:li:person:y", "reaction_type": "LIKE", "created_at": None},
            ],
            "total_count": 3,
            "post_urn": POST_URN,
        }

    def test_empty_proxy_response_yields_no_reactions(
        self, tools: dict[str, Callable[..., Any]], proxy: MagicMock
    ) -> None:
        proxy.return_value = None

        result = tools["CUSTOM_GET_POST_REACTIONS"](
            GetPostReactionsInput(post_urn=POST_URN), EXECUTE_REQUEST, AUTH_CREDS
        )

        assert result == {"reactions": [], "total_count": 0, "post_urn": POST_URN}


# ---------------------------------------------------------------------------
# CUSTOM_GATHER_CONTEXT
# ---------------------------------------------------------------------------


_USERINFO = {
    "sub": "abc",
    "name": "Me User",
    "given_name": "Me",
    "family_name": "User",
    "email": "me@example.com",
    "picture": "https://example.com/pic.png",
}


class TestGatherContext:
    def test_fetches_userinfo_then_recent_posts_with_exact_requests(
        self, tools: dict[str, Callable[..., Any]], proxy: MagicMock
    ) -> None:
        proxy.side_effect = [
            _USERINFO,
            {
                "elements": [
                    {
                        "id": "urn:li:ugcPost:1",
                        "specificContent": {
                            "com.linkedin.ugc.ShareContent": {
                                "shareCommentary": {"text": "x" * 250}
                            }
                        },
                        "created": {"time": 1700000000000},
                        "visibility": {"com.linkedin.ugc.MemberNetworkVisibility": "PUBLIC"},
                    },
                    {"id": "urn:li:ugcPost:2"},
                ]
            },
        ]

        result = tools["CUSTOM_GATHER_CONTEXT"](GatherContextInput(), EXECUTE_REQUEST, AUTH_CREDS)

        assert proxy.call_args_list == [
            call(
                ProxyRequest(
                    user_id=USER_ID,
                    toolkit="LINKEDIN",
                    endpoint="https://api.linkedin.com/v2/userinfo",
                    method="GET",
                )
            ),
            call(
                ProxyRequest(
                    user_id=USER_ID,
                    toolkit="LINKEDIN",
                    endpoint="https://api.linkedin.com/v2/ugcPosts",
                    method="GET",
                    query={
                        "q": "authors",
                        "authors": "List(urn%3Ali%3Aperson%3Aabc)",
                        "count": 5,
                    },
                )
            ),
        ]
        assert result == {
            "user": {
                "id": "abc",
                "name": "Me User",
                "given_name": "Me",
                "family_name": "User",
                "email": "me@example.com",
                "profile_picture": "https://example.com/pic.png",
            },
            "recent_posts": [
                {
                    "id": "urn:li:ugcPost:1",
                    "text": "x" * 200,
                    "created": 1700000000000,
                    "visibility": "PUBLIC",
                },
                {"id": "urn:li:ugcPost:2", "text": "", "created": None, "visibility": None},
            ],
        }

    def test_missing_sub_skips_posts_lookup(
        self, tools: dict[str, Callable[..., Any]], proxy: MagicMock
    ) -> None:
        proxy.return_value = None

        result = tools["CUSTOM_GATHER_CONTEXT"](GatherContextInput(), EXECUTE_REQUEST, AUTH_CREDS)

        assert proxy.call_count == 1
        assert result == {
            "user": {
                "id": "",
                "name": None,
                "given_name": None,
                "family_name": None,
                "email": None,
                "profile_picture": None,
            },
            "recent_posts": [],
        }

    def test_posts_failure_keeps_profile(
        self, tools: dict[str, Callable[..., Any]], proxy: MagicMock
    ) -> None:
        proxy.side_effect = [_USERINFO, RuntimeError("scope missing")]

        result = tools["CUSTOM_GATHER_CONTEXT"](GatherContextInput(), EXECUTE_REQUEST, AUTH_CREDS)

        assert result["user"]["id"] == "abc"
        assert result["recent_posts"] == []
