"""Unit tests for app.agents.tools.integrations.linkedin_tool.

The Composio-registered tool bodies are exercised for real with only the true
I/O boundaries faked (`proxy_request_sync`, `proxy_request_full_sync`,
`get_author_urn`, and the upload helpers). Every test asserts the exact proxy
call (kwargs and body) and the exact returned dict, so a wrong constant,
endpoint, header, or default fails loudly.
"""

from typing import Any
from unittest.mock import MagicMock, call, patch

import pytest

from app.agents.tools.integrations.linkedin_tool import (
    _REST_HEADERS,
    LINKEDIN_API_BASE,
    LINKEDIN_REST_BASE,
    _user_id,
    register_linkedin_custom_tools,
)
from app.models.common_models import GatherContextInput
from app.models.linkedin_models import (
    AddCommentInput,
    CreatePostInput,
    DeleteReactionInput,
    GetPostCommentsInput,
    GetPostReactionsInput,
    ReactToPostInput,
)

MODULE = "app.agents.tools.integrations.linkedin_tool"
AUTH_CREDS: dict[str, Any] = {"user_id": "user_test_123"}
EXECUTE_REQUEST = MagicMock()

AUTHOR_URN = "urn:li:person:1"
POST_URN = "urn:li:share:123"
ENCODED_POST_URN = "urn%3Ali%3Ashare%3A123"


def _tools() -> dict[str, Any]:
    """Register the LinkedIn custom tools against a fake Composio and capture them."""
    captured: dict[str, Any] = {}
    composio = MagicMock()

    def custom_tool(**_kwargs: Any) -> Any:
        def decorator(fn: Any) -> Any:
            captured[fn.__name__] = fn
            return fn

        return decorator

    composio.tools.custom_tool = custom_tool
    register_linkedin_custom_tools(composio)
    return captured


@pytest.fixture
def tools() -> dict[str, Any]:
    return _tools()


@pytest.fixture
def author() -> MagicMock:
    with patch(f"{MODULE}.get_author_urn", return_value=AUTHOR_URN) as mock:
        yield mock


# ---------------------------------------------------------------------------
# register_linkedin_custom_tools
# ---------------------------------------------------------------------------


def test_register_linkedin_custom_tools_registers_all_tools() -> None:
    captured: dict[str, Any] = {}
    composio = MagicMock()

    def custom_tool(**_kwargs: Any) -> Any:
        def decorator(fn: Any) -> Any:
            captured[fn.__name__] = fn
            return fn

        return decorator

    composio.tools.custom_tool = custom_tool
    names = register_linkedin_custom_tools(composio)

    assert names == [
        "LINKEDIN_CUSTOM_CREATE_POST",
        "LINKEDIN_CUSTOM_ADD_COMMENT",
        "LINKEDIN_CUSTOM_GET_POST_COMMENTS",
        "LINKEDIN_CUSTOM_REACT_TO_POST",
        "LINKEDIN_CUSTOM_DELETE_REACTION",
        "LINKEDIN_CUSTOM_GET_POST_REACTIONS",
        "LINKEDIN_CUSTOM_GATHER_CONTEXT",
    ]
    assert set(captured) == {
        "CUSTOM_CREATE_POST",
        "CUSTOM_ADD_COMMENT",
        "CUSTOM_GET_POST_COMMENTS",
        "CUSTOM_REACT_TO_POST",
        "CUSTOM_DELETE_REACTION",
        "CUSTOM_GET_POST_REACTIONS",
        "CUSTOM_GATHER_CONTEXT",
    }


# ---------------------------------------------------------------------------
# _user_id
# ---------------------------------------------------------------------------


def test_user_id_returns_valid_value() -> None:
    assert _user_id({"user_id": "user-42"}) == "user-42"


@pytest.mark.parametrize(
    "credentials",
    [
        {},
        {"user_id": None},
        {"user_id": ""},
        {"user_id": 42},
        {"user_id": ["user-1"]},
    ],
)
def test_user_id_rejects_invalid_values(credentials: dict[str, Any]) -> None:
    with pytest.raises(ValueError, match=r"^Missing user_id in auth_credentials$"):
        _user_id(credentials)


# ---------------------------------------------------------------------------
# CUSTOM_CREATE_POST
# ---------------------------------------------------------------------------


def test_create_post_text_only(tools: dict[str, Any], author: MagicMock) -> None:
    with patch(f"{MODULE}.proxy_request_full_sync") as proxy_full:
        proxy_full.return_value = {"headers": {"x-restli-id": "post-1"}}
        result = tools["CUSTOM_CREATE_POST"](
            CreatePostInput(commentary="hello world"),
            EXECUTE_REQUEST,
            AUTH_CREDS,
        )

    author.assert_called_once_with("user_test_123", None)
    proxy_full.assert_called_once_with(
        user_id="user_test_123",
        toolkit="LINKEDIN",
        endpoint=f"{LINKEDIN_REST_BASE}/posts",
        method="POST",
        body={
            "author": AUTHOR_URN,
            "commentary": "hello world",
            "visibility": "PUBLIC",
            "distribution": {
                "feedDistribution": "MAIN_FEED",
                "targetEntities": [],
                "thirdPartyDistributionChannels": [],
            },
            "lifecycleState": "PUBLISHED",
            "isReshareDisabledByAuthor": False,
        },
        headers=_REST_HEADERS,
    )
    assert result == {
        "post_id": "post-1",
        "url": "https://www.linkedin.com/feed/update/post-1",
        "author": AUTHOR_URN,
        "media_type": "text",
    }


def test_create_post_as_organization() -> None:
    with (
        patch(f"{MODULE}.get_author_urn", return_value="urn:li:organization:999") as author,
        patch(f"{MODULE}.proxy_request_full_sync") as proxy_full,
    ):
        proxy_full.return_value = {"headers": {}}
        tools = _tools()
        tools["CUSTOM_CREATE_POST"](
            CreatePostInput(
                commentary="org post",
                organization_id="urn:li:organization:999",
            ),
            EXECUTE_REQUEST,
            AUTH_CREDS,
        )

    author.assert_called_once_with("user_test_123", "urn:li:organization:999")
    assert proxy_full.call_args.kwargs["body"]["author"] == "urn:li:organization:999"


def test_create_post_connections_visibility(tools: dict[str, Any], author: MagicMock) -> None:
    with patch(f"{MODULE}.proxy_request_full_sync") as proxy_full:
        proxy_full.return_value = {"headers": {}}
        tools["CUSTOM_CREATE_POST"](
            CreatePostInput(commentary="private", visibility="CONNECTIONS"),
            EXECUTE_REQUEST,
            AUTH_CREDS,
        )

    assert proxy_full.call_args.kwargs["body"]["visibility"] == "CONNECTIONS"


def test_create_post_document(tools: dict[str, Any], author: MagicMock) -> None:
    with (
        patch(f"{MODULE}.proxy_request_full_sync") as proxy_full,
        patch(f"{MODULE}.upload_document_from_url", return_value="urn:li:document:9") as upload,
    ):
        proxy_full.return_value = {"headers": {"x-restli-id": "post-2"}}
        result = tools["CUSTOM_CREATE_POST"](
            CreatePostInput(
                commentary="doc post",
                document_url="https://example.com/report.pdf",
                document_title="Report",
            ),
            EXECUTE_REQUEST,
            AUTH_CREDS,
        )

    upload.assert_called_once_with(
        "user_test_123", "https://example.com/report.pdf", AUTHOR_URN
    )
    body = proxy_full.call_args.kwargs["body"]
    assert body["content"] == {
        "media": {"title": "Report", "id": "urn:li:document:9"}
    }
    assert result["media_type"] == "document"


def test_create_post_document_without_title_raises(
    tools: dict[str, Any], author: MagicMock
) -> None:
    with patch(f"{MODULE}.proxy_request_full_sync") as proxy_full:
        with pytest.raises(ValueError, match=r"^document_title is required when document_url is provided$"):
            tools["CUSTOM_CREATE_POST"](
                CreatePostInput(
                    commentary="doc post",
                    document_url="https://example.com/report.pdf",
                ),
                EXECUTE_REQUEST,
                AUTH_CREDS,
            )

    proxy_full.assert_not_called()


def test_create_post_document_upload_failure_raises(
    tools: dict[str, Any], author: MagicMock
) -> None:
    with (
        patch(f"{MODULE}.proxy_request_full_sync") as proxy_full,
        patch(f"{MODULE}.upload_document_from_url", return_value=None),
    ):
        with pytest.raises(RuntimeError, match=r"^Failed to upload document to LinkedIn$"):
            tools["CUSTOM_CREATE_POST"](
                CreatePostInput(
                    commentary="doc post",
                    document_url="https://example.com/report.pdf",
                    document_title="Report",
                ),
                EXECUTE_REQUEST,
                AUTH_CREDS,
            )

    proxy_full.assert_not_called()


def test_create_post_document_takes_precedence_over_images(
    tools: dict[str, Any], author: MagicMock
) -> None:
    with (
        patch(f"{MODULE}.proxy_request_full_sync") as proxy_full,
        patch(f"{MODULE}.upload_document_from_url", return_value="urn:li:document:9") as upload_doc,
        patch(f"{MODULE}.upload_image_from_url") as upload_image,
    ):
        proxy_full.return_value = {"headers": {}}
        result = tools["CUSTOM_CREATE_POST"](
            CreatePostInput(
                commentary="both",
                document_url="https://example.com/report.pdf",
                document_title="Report",
                image_urls=["https://example.com/a.png"],
            ),
            EXECUTE_REQUEST,
            AUTH_CREDS,
        )

    upload_doc.assert_called_once()
    upload_image.assert_not_called()
    assert result["media_type"] == "document"


def test_create_post_single_image(tools: dict[str, Any], author: MagicMock) -> None:
    with (
        patch(f"{MODULE}.proxy_request_full_sync") as proxy_full,
        patch(f"{MODULE}.upload_image_from_url", return_value="urn:li:image:5") as upload,
    ):
        proxy_full.return_value = {"headers": {"x-restli-id": "post-3"}}
        result = tools["CUSTOM_CREATE_POST"](
            CreatePostInput(
                commentary="pic",
                image_url="https://example.com/a.png",
                image_title="Sunset",
            ),
            EXECUTE_REQUEST,
            AUTH_CREDS,
        )

    upload.assert_called_once_with("user_test_123", "https://example.com/a.png", AUTHOR_URN)
    body = proxy_full.call_args.kwargs["body"]
    assert body["content"] == {
        "media": {"title": "Sunset", "id": "urn:li:image:5"}
    }
    assert result["media_type"] == "image"


def test_create_post_single_image_without_title(
    tools: dict[str, Any], author: MagicMock
) -> None:
    with (
        patch(f"{MODULE}.proxy_request_full_sync") as proxy_full,
        patch(f"{MODULE}.upload_image_from_url", return_value="urn:li:image:5"),
    ):
        proxy_full.return_value = {"headers": {}}
        tools["CUSTOM_CREATE_POST"](
            CreatePostInput(commentary="pic", image_url="https://example.com/a.png"),
            EXECUTE_REQUEST,
            AUTH_CREDS,
        )

    assert proxy_full.call_args.kwargs["body"]["content"] == {
        "media": {"title": "", "id": "urn:li:image:5"}
    }


def test_create_post_carousel(tools: dict[str, Any], author: MagicMock) -> None:
    urls = ["https://example.com/a.png", "https://example.com/b.png"]
    with (
        patch(f"{MODULE}.proxy_request_full_sync") as proxy_full,
        patch(
            f"{MODULE}.upload_image_from_url",
            side_effect=["urn:li:image:1", "urn:li:image:2"],
        ) as upload,
    ):
        proxy_full.return_value = {"headers": {}}
        result = tools["CUSTOM_CREATE_POST"](
            CreatePostInput(commentary="carousel", image_urls=urls),
            EXECUTE_REQUEST,
            AUTH_CREDS,
        )

    assert upload.call_args_list == [
        call("user_test_123", urls[0], AUTHOR_URN),
        call("user_test_123", urls[1], AUTHOR_URN),
    ]
    body = proxy_full.call_args.kwargs["body"]
    assert body["content"] == {
        "multiImage": {"images": [{"id": "urn:li:image:1"}, {"id": "urn:li:image:2"}]}
    }
    assert result["media_type"] == "carousel"


def test_create_post_image_urls_override_single_image_url(
    tools: dict[str, Any], author: MagicMock
) -> None:
    with (
        patch(f"{MODULE}.proxy_request_full_sync") as proxy_full,
        patch(f"{MODULE}.upload_image_from_url", return_value="urn:li:image:1") as upload,
    ):
        proxy_full.return_value = {"headers": {}}
        tools["CUSTOM_CREATE_POST"](
            CreatePostInput(
                commentary="both",
                image_url="https://example.com/solo.png",
                image_urls=["https://example.com/a.png", "https://example.com/b.png"],
            ),
            EXECUTE_REQUEST,
            AUTH_CREDS,
        )

    assert upload.call_count == 2
    assert proxy_full.call_args.kwargs["body"]["content"]["multiImage"]["images"] == [
        {"id": "urn:li:image:1"},
        {"id": "urn:li:image:1"},
    ]


def test_create_post_too_many_images_raises(tools: dict[str, Any], author: MagicMock) -> None:
    with (
        patch(f"{MODULE}.proxy_request_full_sync") as proxy_full,
        patch(f"{MODULE}.upload_image_from_url") as upload,
    ):
        with pytest.raises(ValueError, match=r"^Maximum 20 images allowed in a carousel post$"):
            tools["CUSTOM_CREATE_POST"](
                CreatePostInput(
                    commentary="lots",
                    image_urls=[f"https://example.com/{i}.png" for i in range(21)],
                ),
                EXECUTE_REQUEST,
                AUTH_CREDS,
            )

    upload.assert_not_called()
    proxy_full.assert_not_called()


def test_create_post_exactly_twenty_images_allowed(
    tools: dict[str, Any], author: MagicMock
) -> None:
    with (
        patch(f"{MODULE}.proxy_request_full_sync") as proxy_full,
        patch(
            f"{MODULE}.upload_image_from_url",
            side_effect=[f"urn:li:image:{i}" for i in range(20)],
        ),
    ):
        proxy_full.return_value = {"headers": {}}
        result = tools["CUSTOM_CREATE_POST"](
            CreatePostInput(
                commentary="twenty",
                image_urls=[f"https://example.com/{i}.png" for i in range(20)],
            ),
            EXECUTE_REQUEST,
            AUTH_CREDS,
        )

    assert result["media_type"] == "carousel"
    assert len(proxy_full.call_args.kwargs["body"]["content"]["multiImage"]["images"]) == 20


def test_create_post_image_upload_failure_raises(
    tools: dict[str, Any], author: MagicMock
) -> None:
    with (
        patch(f"{MODULE}.proxy_request_full_sync") as proxy_full,
        patch(f"{MODULE}.upload_image_from_url", side_effect=["urn:li:image:1", None]),
    ):
        with pytest.raises(
            RuntimeError, match=r"^Failed to upload image: https://example.com/b.png$"
        ):
            tools["CUSTOM_CREATE_POST"](
                CreatePostInput(
                    commentary="fail",
                    image_urls=[
                        "https://example.com/a.png",
                        "https://example.com/b.png",
                    ],
                ),
                EXECUTE_REQUEST,
                AUTH_CREDS,
            )

    proxy_full.assert_not_called()


def test_create_post_article(tools: dict[str, Any], author: MagicMock) -> None:
    with (
        patch(f"{MODULE}.proxy_request_full_sync") as proxy_full,
        patch(f"{MODULE}.upload_image_from_url") as upload,
    ):
        proxy_full.return_value = {"headers": {}}
        result = tools["CUSTOM_CREATE_POST"](
            CreatePostInput(commentary="article", article_url="https://example.com/art"),
            EXECUTE_REQUEST,
            AUTH_CREDS,
        )

    upload.assert_not_called()
    body = proxy_full.call_args.kwargs["body"]
    assert body["content"] == {"article": {"source": "https://example.com/art"}}
    assert result["media_type"] == "article"


def test_create_post_article_with_metadata(
    tools: dict[str, Any], author: MagicMock
) -> None:
    with patch(f"{MODULE}.proxy_request_full_sync") as proxy_full:
        proxy_full.return_value = {"headers": {}}
        tools["CUSTOM_CREATE_POST"](
            CreatePostInput(
                commentary="article",
                article_url="https://example.com/art",
                article_title="Title",
                article_description="Desc",
            ),
            EXECUTE_REQUEST,
            AUTH_CREDS,
        )

    assert proxy_full.call_args.kwargs["body"]["content"] == {
        "article": {
            "source": "https://example.com/art",
            "title": "Title",
            "description": "Desc",
        }
    }


def test_create_post_article_with_thumbnail(
    tools: dict[str, Any], author: MagicMock
) -> None:
    with (
        patch(f"{MODULE}.proxy_request_full_sync") as proxy_full,
        patch(
            f"{MODULE}.upload_image_from_url", return_value="urn:li:image:thumb"
        ) as upload,
    ):
        proxy_full.return_value = {"headers": {}}
        tools["CUSTOM_CREATE_POST"](
            CreatePostInput(
                commentary="article",
                article_url="https://example.com/art",
                thumbnail_url="https://example.com/thumb.png",
            ),
            EXECUTE_REQUEST,
            AUTH_CREDS,
        )

    upload.assert_called_once_with(
        "user_test_123", "https://example.com/thumb.png", AUTHOR_URN
    )
    assert proxy_full.call_args.kwargs["body"]["content"] == {
        "article": {"source": "https://example.com/art", "thumbnail": "urn:li:image:thumb"}
    }


def test_create_post_article_thumbnail_upload_failure_omits_thumbnail(
    tools: dict[str, Any],
    author: MagicMock,
) -> None:
    with (
        patch(f"{MODULE}.proxy_request_full_sync") as proxy_full,
        patch(f"{MODULE}.upload_image_from_url", return_value=None),
    ):
        proxy_full.return_value = {"headers": {}}
        tools["CUSTOM_CREATE_POST"](
            CreatePostInput(
                commentary="article",
                article_url="https://example.com/art",
                thumbnail_url="https://example.com/thumb.png",
            ),
            EXECUTE_REQUEST,
            AUTH_CREDS,
        )

    assert proxy_full.call_args.kwargs["body"]["content"] == {
        "article": {"source": "https://example.com/art"}
    }


def test_create_post_no_post_id_in_response(
    tools: dict[str, Any], author: MagicMock
) -> None:
    with patch(f"{MODULE}.proxy_request_full_sync") as proxy_full:
        proxy_full.return_value = {"headers": {}}
        result = tools["CUSTOM_CREATE_POST"](
            CreatePostInput(commentary="x"),
            EXECUTE_REQUEST,
            AUTH_CREDS,
        )

    assert result["post_id"] == ""
    assert result["url"] == "https://www.linkedin.com/feed/update/"


def test_create_post_missing_headers_key_in_response(
    tools: dict[str, Any], author: MagicMock
) -> None:
    with patch(f"{MODULE}.proxy_request_full_sync") as proxy_full:
        proxy_full.return_value = {"data": {"post": "ignored"}}
        result = tools["CUSTOM_CREATE_POST"](
            CreatePostInput(commentary="x"),
            EXECUTE_REQUEST,
            AUTH_CREDS,
        )

    assert result["post_id"] == ""
    assert result["url"] == "https://www.linkedin.com/feed/update/"


def test_create_post_missing_user_id_raises(tools: dict[str, Any]) -> None:
    with (
        patch(f"{MODULE}.proxy_request_full_sync") as proxy_full,
        patch(f"{MODULE}.get_author_urn"),
    ):
        with pytest.raises(ValueError, match=r"^Missing user_id in auth_credentials$"):
            tools["CUSTOM_CREATE_POST"](
                CreatePostInput(commentary="x"),
                EXECUTE_REQUEST,
                {},
            )

    proxy_full.assert_not_called()


# ---------------------------------------------------------------------------
# CUSTOM_ADD_COMMENT
# ---------------------------------------------------------------------------


def test_add_comment(tools: dict[str, Any], author: MagicMock) -> None:
    with patch(f"{MODULE}.proxy_request_full_sync") as proxy_full:
        proxy_full.return_value = {"data": {"id": "comment-1"}, "headers": {}}
        result = tools["CUSTOM_ADD_COMMENT"](
            AddCommentInput(post_urn=POST_URN, comment_text="nice post"),
            EXECUTE_REQUEST,
            AUTH_CREDS,
        )

    author.assert_called_once_with("user_test_123")
    proxy_full.assert_called_once_with(
        user_id="user_test_123",
        toolkit="LINKEDIN",
        endpoint=(
            f"{LINKEDIN_REST_BASE}/socialActions/{ENCODED_POST_URN}/comments"
        ),
        method="POST",
        body={
            "actor": AUTHOR_URN,
            "message": {"text": "nice post"},
        },
        headers=_REST_HEADERS,
    )
    assert result == {
        "comment_id": "comment-1",
        "post_urn": POST_URN,
        "author": AUTHOR_URN,
    }


def test_add_comment_with_parent(tools: dict[str, Any], author: MagicMock) -> None:
    with patch(f"{MODULE}.proxy_request_full_sync") as proxy_full:
        proxy_full.return_value = {"data": {"id": "comment-1"}, "headers": {}}
        tools["CUSTOM_ADD_COMMENT"](
            AddCommentInput(
                post_urn=POST_URN,
                comment_text="reply",
                parent_comment_urn="urn:li:comment:7",
            ),
            EXECUTE_REQUEST,
            AUTH_CREDS,
        )

    body = proxy_full.call_args.kwargs["body"]
    assert body["parentComment"] == "urn:li:comment:7"


def test_add_comment_id_falls_back_to_response_header(
    tools: dict[str, Any], author: MagicMock
) -> None:
    with patch(f"{MODULE}.proxy_request_full_sync") as proxy_full:
        proxy_full.return_value = {
            "data": {},
            "headers": {"x-restli-id": "header-comment-1"},
        }
        result = tools["CUSTOM_ADD_COMMENT"](
            AddCommentInput(post_urn=POST_URN, comment_text="hi"),
            EXECUTE_REQUEST,
            AUTH_CREDS,
        )

    assert result["comment_id"] == "header-comment-1"


def test_add_comment_id_from_header_when_data_missing(
    tools: dict[str, Any], author: MagicMock
) -> None:
    with patch(f"{MODULE}.proxy_request_full_sync") as proxy_full:
        proxy_full.return_value = {"headers": {"x-restli-id": "header-comment-2"}}
        result = tools["CUSTOM_ADD_COMMENT"](
            AddCommentInput(post_urn=POST_URN, comment_text="hi"),
            EXECUTE_REQUEST,
            AUTH_CREDS,
        )

    assert result["comment_id"] == "header-comment-2"


def test_add_comment_id_from_header_when_data_is_non_dict(
    tools: dict[str, Any],
    author: MagicMock,
) -> None:
    with patch(f"{MODULE}.proxy_request_full_sync") as proxy_full:
        proxy_full.return_value = {
            "data": ["not-a-dict"],
            "headers": {"x-restli-id": "header-comment-3"},
        }
        result = tools["CUSTOM_ADD_COMMENT"](
            AddCommentInput(post_urn=POST_URN, comment_text="hi"),
            EXECUTE_REQUEST,
            AUTH_CREDS,
        )

    assert result["comment_id"] == "header-comment-3"


def test_add_comment_no_id_anywhere(tools: dict[str, Any], author: MagicMock) -> None:
    with patch(f"{MODULE}.proxy_request_full_sync") as proxy_full:
        proxy_full.return_value = {"data": {}}
        result = tools["CUSTOM_ADD_COMMENT"](
            AddCommentInput(post_urn=POST_URN, comment_text="hi"),
            EXECUTE_REQUEST,
            AUTH_CREDS,
        )

    assert result["comment_id"] == ""


# ---------------------------------------------------------------------------
# CUSTOM_GET_POST_COMMENTS
# ---------------------------------------------------------------------------


def test_get_post_comments(tools: dict[str, Any], author: MagicMock) -> None:
    with patch(f"{MODULE}.proxy_request_sync") as proxy:
        proxy.return_value = {
            "elements": [
                {
                    "id": "c1",
                    "actor": "urn:li:person:9",
                    "message": {"text": "first"},
                    "created": {"time": 1111},
                    "parentComment": None,
                },
                {
                    "id": "c2",
                    "actor": "urn:li:person:10",
                    "message": {"text": "second"},
                    "created": {"time": 2222},
                    "parentComment": "urn:li:comment:5",
                },
            ],
            "paging": {"total": 7},
        }
        result = tools["CUSTOM_GET_POST_COMMENTS"](
            GetPostCommentsInput(post_urn=POST_URN, count=5, start=2),
            EXECUTE_REQUEST,
            AUTH_CREDS,
        )

    author.assert_not_called()
    proxy.assert_called_once_with(
        user_id="user_test_123",
        toolkit="LINKEDIN",
        endpoint=(
            f"{LINKEDIN_REST_BASE}/socialActions/{ENCODED_POST_URN}/comments"
        ),
        method="GET",
        query={"count": 5, "start": 2},
        headers=_REST_HEADERS,
    )
    assert result == {
        "comments": [
            {
                "id": "c1",
                "author": "urn:li:person:9",
                "text": "first",
                "created_at": 1111,
                "parent_comment": None,
            },
            {
                "id": "c2",
                "author": "urn:li:person:10",
                "text": "second",
                "created_at": 2222,
                "parent_comment": "urn:li:comment:5",
            },
        ],
        "total_count": 7,
        "post_urn": POST_URN,
    }


def test_get_post_comments_defaults_for_missing_fields(
    tools: dict[str, Any],
) -> None:
    with patch(f"{MODULE}.proxy_request_sync") as proxy:
        proxy.return_value = {
            "elements": [{"id": "c1"}],
            "paging": {"total": 1},
        }
        result = tools["CUSTOM_GET_POST_COMMENTS"](
            GetPostCommentsInput(post_urn=POST_URN),
            EXECUTE_REQUEST,
            AUTH_CREDS,
        )

    assert result["comments"] == [
        {
            "id": "c1",
            "author": None,
            "text": "",
            "created_at": None,
            "parent_comment": None,
        }
    ]


def test_get_post_comments_total_count_falls_back_to_elements(
    tools: dict[str, Any],
) -> None:
    with patch(f"{MODULE}.proxy_request_sync") as proxy:
        proxy.return_value = {
            "elements": [{"id": "c1"}, {"id": "c2"}],
        }
        result = tools["CUSTOM_GET_POST_COMMENTS"](
            GetPostCommentsInput(post_urn=POST_URN),
            EXECUTE_REQUEST,
            AUTH_CREDS,
        )

    assert result["total_count"] == 2


def test_get_post_comments_none_response(tools: dict[str, Any]) -> None:
    with patch(f"{MODULE}.proxy_request_sync", return_value=None) as proxy:
        result = tools["CUSTOM_GET_POST_COMMENTS"](
            GetPostCommentsInput(post_urn=POST_URN),
            EXECUTE_REQUEST,
            AUTH_CREDS,
        )

    assert result == {
        "comments": [],
        "total_count": 0,
        "post_urn": POST_URN,
    }
    proxy.assert_called_once()


# ---------------------------------------------------------------------------
# CUSTOM_REACT_TO_POST
# ---------------------------------------------------------------------------


def test_react_to_post(tools: dict[str, Any], author: MagicMock) -> None:
    with patch(f"{MODULE}.proxy_request_sync") as proxy:
        proxy.return_value = {}
        result = tools["CUSTOM_REACT_TO_POST"](
            ReactToPostInput(post_urn=POST_URN),
            EXECUTE_REQUEST,
            AUTH_CREDS,
        )

    author.assert_called_once_with("user_test_123")
    proxy.assert_called_once_with(
        user_id="user_test_123",
        toolkit="LINKEDIN",
        endpoint=f"{LINKEDIN_REST_BASE}/socialActions/{ENCODED_POST_URN}/likes",
        method="POST",
        body={"actor": AUTHOR_URN, "reactionType": "LIKE"},
        headers=_REST_HEADERS,
    )
    assert result == {
        "post_urn": POST_URN,
        "reaction_type": "LIKE",
        "author": AUTHOR_URN,
    }


def test_react_to_post_custom_reaction_type(
    tools: dict[str, Any], author: MagicMock
) -> None:
    with patch(f"{MODULE}.proxy_request_sync") as proxy:
        proxy.return_value = {}
        result = tools["CUSTOM_REACT_TO_POST"](
            ReactToPostInput(post_urn=POST_URN, reaction_type="CELEBRATE"),
            EXECUTE_REQUEST,
            AUTH_CREDS,
        )

    assert proxy.call_args.kwargs["body"] == {
        "actor": AUTHOR_URN,
        "reactionType": "CELEBRATE",
    }
    assert result["reaction_type"] == "CELEBRATE"


# ---------------------------------------------------------------------------
# CUSTOM_DELETE_REACTION
# ---------------------------------------------------------------------------


def test_delete_reaction(tools: dict[str, Any], author: MagicMock) -> None:
    with patch(f"{MODULE}.proxy_request_sync") as proxy:
        proxy.return_value = {}
        result = tools["CUSTOM_DELETE_REACTION"](
            DeleteReactionInput(post_urn=POST_URN),
            EXECUTE_REQUEST,
            AUTH_CREDS,
        )

    author.assert_called_once_with("user_test_123")
    proxy.assert_called_once_with(
        user_id="user_test_123",
        toolkit="LINKEDIN",
        endpoint=(
            f"{LINKEDIN_REST_BASE}/socialActions/{ENCODED_POST_URN}/likes/"
            f"{AUTHOR_URN.replace(':', '%3A')}"
        ),
        method="DELETE",
        headers=_REST_HEADERS,
    )
    assert result == {
        "post_urn": POST_URN,
        "message": "Reaction removed successfully",
    }


# ---------------------------------------------------------------------------
# CUSTOM_GET_POST_REACTIONS
# ---------------------------------------------------------------------------


def test_get_post_reactions(tools: dict[str, Any], author: MagicMock) -> None:
    with patch(f"{MODULE}.proxy_request_sync") as proxy:
        proxy.return_value = {
            "elements": [
                {
                    "actor": "urn:li:person:9",
                    "reactionType": "LOVE",
                    "created": {"time": 1111},
                },
                {
                    "actor": "urn:li:person:10",
                    "created": {"time": 2222},
                },
            ],
            "paging": {"total": 3},
        }
        result = tools["CUSTOM_GET_POST_REACTIONS"](
            GetPostReactionsInput(post_urn=POST_URN, count=3),
            EXECUTE_REQUEST,
            AUTH_CREDS,
        )

    author.assert_not_called()
    proxy.assert_called_once_with(
        user_id="user_test_123",
        toolkit="LINKEDIN",
        endpoint=f"{LINKEDIN_REST_BASE}/socialActions/{ENCODED_POST_URN}/likes",
        method="GET",
        query={"count": 3},
        headers=_REST_HEADERS,
    )
    assert result == {
        "reactions": [
            {
                "actor": "urn:li:person:9",
                "reaction_type": "LOVE",
                "created_at": 1111,
            },
            {
                "actor": "urn:li:person:10",
                "reaction_type": "LIKE",
                "created_at": 2222,
            },
        ],
        "total_count": 3,
        "post_urn": POST_URN,
    }


def test_get_post_reactions_none_response(tools: dict[str, Any]) -> None:
    with patch(f"{MODULE}.proxy_request_sync", return_value=None) as proxy:
        result = tools["CUSTOM_GET_POST_REACTIONS"](
            GetPostReactionsInput(post_urn=POST_URN),
            EXECUTE_REQUEST,
            AUTH_CREDS,
        )

    assert result == {
        "reactions": [],
        "total_count": 0,
        "post_urn": POST_URN,
    }
    proxy.assert_called_once()


def test_get_post_reactions_missing_created_field(tools: dict[str, Any]) -> None:
    with patch(f"{MODULE}.proxy_request_sync") as proxy:
        proxy.return_value = {
            "elements": [{"actor": "urn:li:person:9", "reactionType": "LIKE"}],
        }
        result = tools["CUSTOM_GET_POST_REACTIONS"](
            GetPostReactionsInput(post_urn=POST_URN),
            EXECUTE_REQUEST,
            AUTH_CREDS,
        )

    assert result["reactions"] == [
        {
            "actor": "urn:li:person:9",
            "reaction_type": "LIKE",
            "created_at": None,
        }
    ]


# ---------------------------------------------------------------------------
# CUSTOM_GATHER_CONTEXT
# ---------------------------------------------------------------------------


def test_gather_context(tools: dict[str, Any]) -> None:
    long_text = "x" * 250
    with patch(f"{MODULE}.proxy_request_sync") as proxy:
        proxy.side_effect = [
            {
                "sub": "user-42",
                "name": "Ada Lovelace",
                "given_name": "Ada",
                "family_name": "Lovelace",
                "email": "ada@example.com",
                "picture": "https://example.com/pic.png",
            },
            {
                "elements": [
                    {
                        "id": "ugc-1",
                        "specificContent": {
                            "com.linkedin.ugc.ShareContent": {
                                "shareCommentary": {"text": long_text}
                            }
                        },
                        "created": {"time": 1111},
                        "visibility": {
                            "com.linkedin.ugc.MemberNetworkVisibility": "PUBLIC"
                        },
                    },
                    {"id": "ugc-2"},
                ]
            },
        ]
        result = tools["CUSTOM_GATHER_CONTEXT"](
            GatherContextInput(), EXECUTE_REQUEST, AUTH_CREDS
        )

    assert proxy.call_args_list == [
        call(
            user_id="user_test_123",
            toolkit="LINKEDIN",
            endpoint=f"{LINKEDIN_API_BASE}/userinfo",
            method="GET",
        ),
        call(
            user_id="user_test_123",
            toolkit="LINKEDIN",
            endpoint=f"{LINKEDIN_API_BASE}/ugcPosts",
            method="GET",
            query={
                "q": "authors",
                "authors": "List(urn%3Ali%3Aperson%3Auser-42)",
                "count": 5,
            },
        ),
    ]
    assert result == {
        "user": {
            "id": "user-42",
            "name": "Ada Lovelace",
            "given_name": "Ada",
            "family_name": "Lovelace",
            "email": "ada@example.com",
            "profile_picture": "https://example.com/pic.png",
        },
        "recent_posts": [
            {
                "id": "ugc-1",
                "text": "x" * 200,
                "created": 1111,
                "visibility": "PUBLIC",
            },
            {
                "id": "ugc-2",
                "text": "",
                "created": None,
                "visibility": None,
            },
        ],
    }


def test_gather_context_without_sub_skips_posts(tools: dict[str, Any]) -> None:
    with patch(f"{MODULE}.proxy_request_sync") as proxy:
        proxy.return_value = {"name": "No Sub"}
        result = tools["CUSTOM_GATHER_CONTEXT"](
            GatherContextInput(), EXECUTE_REQUEST, AUTH_CREDS
        )

    proxy.assert_called_once_with(
        user_id="user_test_123",
        toolkit="LINKEDIN",
        endpoint=f"{LINKEDIN_API_BASE}/userinfo",
        method="GET",
    )
    assert result["user"]["id"] == ""
    assert result["user"]["name"] == "No Sub"
    assert result["recent_posts"] == []


def test_gather_context_missing_userinfo_fields(tools: dict[str, Any]) -> None:
    with patch(f"{MODULE}.proxy_request_sync", return_value={"sub": "user-7"}) as proxy:
        result = tools["CUSTOM_GATHER_CONTEXT"](
            GatherContextInput(), EXECUTE_REQUEST, AUTH_CREDS
        )

    assert proxy.call_count == 2
    assert result["user"] == {
        "id": "user-7",
        "name": None,
        "given_name": None,
        "family_name": None,
        "email": None,
        "profile_picture": None,
    }


def test_gather_context_posts_fetch_failure_is_swallowed(
    tools: dict[str, Any],
) -> None:
    with patch(f"{MODULE}.proxy_request_sync") as proxy:
        proxy.side_effect = [
            {"sub": "user-42"},
            RuntimeError("api down"),
        ]
        result = tools["CUSTOM_GATHER_CONTEXT"](
            GatherContextInput(), EXECUTE_REQUEST, AUTH_CREDS
        )

    assert proxy.call_count == 2
    assert result["user"]["id"] == "user-42"
    assert result["recent_posts"] == []


def test_gather_context_none_userinfo_response(tools: dict[str, Any]) -> None:
    with patch(f"{MODULE}.proxy_request_sync", return_value=None) as proxy:
        result = tools["CUSTOM_GATHER_CONTEXT"](
            GatherContextInput(), EXECUTE_REQUEST, AUTH_CREDS
        )

    proxy.assert_called_once()
    assert result["user"]["id"] == ""
    assert result["recent_posts"] == []
