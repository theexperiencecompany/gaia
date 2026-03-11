"""LinkedIn custom tool tests.

Tests the six custom LinkedIn tools registered via register_linkedin_custom_tools:
  - CUSTOM_CREATE_POST
  - CUSTOM_ADD_COMMENT
  - CUSTOM_GET_POST_COMMENTS
  - CUSTOM_REACT_TO_POST
  - CUSTOM_DELETE_REACTION
  - CUSTOM_GET_POST_REACTIONS

Strategy
--------
The decorator-capture pattern is used: a mock Composio client intercepts
every ``@composio.tools.custom_tool(toolkit=...)`` call at registration time
and stores the real production closure under its ``__name__``.  Tests then
call those closures directly, mocking only the module-level ``_http_client``
(httpx.Client) and the ``linkedin_utils`` helpers that perform outbound HTTP.

This means:
- If the production function body is rewritten, the tests will detect it.
- No production logic is reimplemented inside the test file.
- No real network calls or Composio credentials are required.
"""

from typing import Any, Dict
from unittest.mock import MagicMock, patch

import httpx
import pytest

from app.agents.tools.integrations.linkedin_tool import (
    register_linkedin_custom_tools,
)
from app.models.linkedin_models import (
    AddCommentInput,
    CreatePostInput,
    DeleteReactionInput,
    GetPostCommentsInput,
    GetPostReactionsInput,
    ReactToPostInput,
)
from app.utils.linkedin_utils import (
    get_access_token,
    linkedin_headers,
    get_author_urn,
)

# ---------------------------------------------------------------------------
# Shared test constants
# ---------------------------------------------------------------------------

FAKE_TOKEN = "fake-linkedin-access-token"
FAKE_AUTHOR_URN = "urn:li:person:abc123"
FAKE_POST_URN = "urn:li:share:9999"
FAKE_POST_ID = "urn:li:share:9999"
AUTH_CREDENTIALS: Dict[str, Any] = {"access_token": FAKE_TOKEN}
EXECUTE_REQUEST_STUB = None  # handlers never use this arg


def _make_response(
    status_code: int = 200,
    json_data: Any = None,
    headers: dict | None = None,
) -> MagicMock:
    """Build a minimal mock httpx.Response."""
    resp = MagicMock(spec=httpx.Response)
    resp.status_code = status_code
    resp.json.return_value = json_data or {}
    resp.headers = headers or {}
    resp.text = str(json_data)
    if status_code >= 400:
        err = httpx.HTTPStatusError(
            f"HTTP {status_code}", request=MagicMock(), response=resp
        )
        resp.raise_for_status.side_effect = err
    else:
        resp.raise_for_status.return_value = None
    return resp


# ---------------------------------------------------------------------------
# Decorator-capture helpers
# ---------------------------------------------------------------------------


def _make_composio_mock() -> tuple[MagicMock, Dict[str, Any]]:
    """Return a (composio_mock, captured_fns) pair.

    Calling ``register_linkedin_custom_tools(composio_mock)`` causes the
    decorator ``composio.tools.custom_tool(toolkit=...)`` to be invoked for
    each handler.  We capture every decorated function so the tests can call
    them directly, exercising the real production closures.
    """
    captured: Dict[str, Any] = {}

    def _fake_custom_tool(toolkit: str):
        """Mimic @composio.tools.custom_tool(toolkit=...) decorator."""

        def _decorator(fn):
            captured[fn.__name__] = fn
            return fn

        return _decorator

    composio = MagicMock()
    composio.tools.custom_tool.side_effect = _fake_custom_tool

    register_linkedin_custom_tools(composio)
    return composio, captured


# ---------------------------------------------------------------------------
# get_access_token (utility) — already calls real production code
# ---------------------------------------------------------------------------


@pytest.mark.composio
class TestLinkedInGetAccessToken:
    def test_returns_token(self):
        assert get_access_token({"access_token": "tok"}) == "tok"

    def test_raises_when_missing(self):
        with pytest.raises(ValueError, match="Missing access_token"):
            get_access_token({})

    def test_raises_when_none(self):
        with pytest.raises(ValueError, match="Missing access_token"):
            get_access_token({"access_token": None})


# ---------------------------------------------------------------------------
# linkedin_headers (utility) — already calls real production code
# ---------------------------------------------------------------------------


@pytest.mark.composio
class TestLinkedInHeaders:
    def test_contains_bearer_token(self):
        h = linkedin_headers("mytoken")
        assert h["Authorization"] == "Bearer mytoken"

    def test_contains_required_linkedin_headers(self):
        h = linkedin_headers("t")
        assert h["X-Restli-Protocol-Version"] == "2.0.0"
        assert "LinkedIn-Version" in h
        assert h["Content-Type"] == "application/json"


# ---------------------------------------------------------------------------
# get_author_urn (utility) — already calls real production code
# ---------------------------------------------------------------------------


@pytest.mark.composio
class TestGetAuthorUrn:
    def test_uses_full_org_urn_as_is(self):
        result = get_author_urn("tok", "urn:li:organization:12345")
        assert result == "urn:li:organization:12345"

    def test_builds_org_urn_from_bare_id(self):
        result = get_author_urn("tok", "12345")
        assert result == "urn:li:organization:12345"

    def test_resolves_person_urn_from_userinfo(self):
        resp = _make_response(json_data={"sub": "person-sub-99"})
        with patch("app.utils.linkedin_utils._http_client") as mock_client:
            mock_client.get.return_value = resp
            result = get_author_urn("tok")
        assert result == "urn:li:person:person-sub-99"

    def test_raises_when_userinfo_has_no_sub(self):
        resp = _make_response(json_data={})
        with patch("app.utils.linkedin_utils._http_client") as mock_client:
            mock_client.get.return_value = resp
            with pytest.raises(ValueError, match="Could not determine author URN"):
                get_author_urn("tok")

    def test_raises_when_userinfo_call_fails(self):
        with patch("app.utils.linkedin_utils._http_client") as mock_client:
            mock_client.get.side_effect = httpx.ConnectError("network down")
            with pytest.raises(ValueError, match="Could not determine author URN"):
                get_author_urn("tok")


# ---------------------------------------------------------------------------
# CUSTOM_CREATE_POST
# ---------------------------------------------------------------------------


@pytest.mark.composio
class TestCustomCreatePost:
    """Tests for the CUSTOM_CREATE_POST production closure."""

    def _run(
        self,
        request: CreatePostInput,
        mock_post_resp: MagicMock | None = None,
        upload_image_return: str = "urn:li:image:img1",
        upload_document_return: str = "urn:li:document:doc1",
    ) -> Dict[str, Any]:
        """Call the real CUSTOM_CREATE_POST closure with mocked I/O boundaries."""
        _, fns = _make_composio_mock()
        fn = fns["CUSTOM_CREATE_POST"]

        if mock_post_resp is None:
            mock_post_resp = _make_response(
                status_code=201, headers={"x-restli-id": FAKE_POST_ID}
            )

        with (
            patch(
                "app.agents.tools.integrations.linkedin_tool.get_author_urn",
                return_value=FAKE_AUTHOR_URN,
            ),
            patch(
                "app.agents.tools.integrations.linkedin_tool._http_client"
            ) as mock_http,
            patch(
                "app.agents.tools.integrations.linkedin_tool.upload_image_from_url",
                return_value=upload_image_return,
            ),
            patch(
                "app.agents.tools.integrations.linkedin_tool.upload_document_from_url",
                return_value=upload_document_return,
            ),
        ):
            mock_http.post.return_value = mock_post_resp
            return fn(request, EXECUTE_REQUEST_STUB, AUTH_CREDENTIALS)

    def test_text_only_post(self):
        result = self._run(CreatePostInput(commentary="Hello LinkedIn!"))
        assert result["post_id"] == FAKE_POST_ID
        assert result["media_type"] == "text"
        assert "linkedin.com" in result["url"]
        assert result["author"] == FAKE_AUTHOR_URN

    def test_single_image_post(self):
        result = self._run(
            CreatePostInput(
                commentary="Check this out",
                image_url="https://example.com/photo.jpg",
            )
        )
        assert result["media_type"] == "image"

    def test_multi_image_carousel_post(self):
        result = self._run(
            CreatePostInput(
                commentary="Carousel post",
                image_urls=["https://example.com/1.jpg", "https://example.com/2.jpg"],
            )
        )
        assert result["media_type"] == "carousel"

    def test_document_post(self):
        result = self._run(
            CreatePostInput(
                commentary="Read my doc",
                document_url="https://example.com/doc.pdf",
                document_title="My Report",
            )
        )
        assert result["media_type"] == "document"

    def test_document_post_without_title_raises(self):
        with pytest.raises(ValueError, match="document_title is required"):
            self._run(
                CreatePostInput(
                    commentary="Doc without title",
                    document_url="https://example.com/doc.pdf",
                )
            )

    def test_article_post(self):
        result = self._run(
            CreatePostInput(
                commentary="Interesting article",
                article_url="https://example.com/article",
                article_title="Great Article",
                article_description="A wonderful read",
            )
        )
        assert result["media_type"] == "article"

    def test_carousel_exceeds_20_images_raises(self):
        with pytest.raises(ValueError, match="Maximum 20 images"):
            self._run(
                CreatePostInput(
                    commentary="Too many images",
                    image_urls=[f"https://example.com/{i}.jpg" for i in range(21)],
                )
            )

    def test_http_error_propagates(self):
        bad_resp = _make_response(status_code=422)
        with pytest.raises(httpx.HTTPStatusError):
            self._run(
                CreatePostInput(commentary="Bad post"),
                mock_post_resp=bad_resp,
            )

    def test_visibility_public_by_default(self):
        _, fns = _make_composio_mock()
        fn = fns["CUSTOM_CREATE_POST"]
        post_calls = []

        ok_resp = _make_response(status_code=201, headers={"x-restli-id": "id1"})

        with (
            patch(
                "app.agents.tools.integrations.linkedin_tool.get_author_urn",
                return_value=FAKE_AUTHOR_URN,
            ),
            patch(
                "app.agents.tools.integrations.linkedin_tool._http_client"
            ) as mock_http,
        ):
            mock_http.post.side_effect = lambda *a, **kw: (
                post_calls.append(kw) or ok_resp
            )
            fn(
                CreatePostInput(commentary="visible post"),
                EXECUTE_REQUEST_STUB,
                AUTH_CREDENTIALS,
            )

        assert post_calls[0]["json"]["visibility"] == "PUBLIC"

    def test_visibility_connections(self):
        _, fns = _make_composio_mock()
        fn = fns["CUSTOM_CREATE_POST"]
        post_calls = []

        ok_resp = _make_response(status_code=201, headers={"x-restli-id": "id1"})

        with (
            patch(
                "app.agents.tools.integrations.linkedin_tool.get_author_urn",
                return_value=FAKE_AUTHOR_URN,
            ),
            patch(
                "app.agents.tools.integrations.linkedin_tool._http_client"
            ) as mock_http,
        ):
            mock_http.post.side_effect = lambda *a, **kw: (
                post_calls.append(kw) or ok_resp
            )
            fn(
                CreatePostInput(commentary="private post", visibility="CONNECTIONS"),
                EXECUTE_REQUEST_STUB,
                AUTH_CREDENTIALS,
            )

        assert post_calls[0]["json"]["visibility"] == "CONNECTIONS"

    def test_missing_access_token_raises(self):
        _, fns = _make_composio_mock()
        fn = fns["CUSTOM_CREATE_POST"]
        with pytest.raises(ValueError, match="Missing access_token"):
            fn(CreatePostInput(commentary="no token"), EXECUTE_REQUEST_STUB, {})


# ---------------------------------------------------------------------------
# CUSTOM_ADD_COMMENT
# ---------------------------------------------------------------------------


@pytest.mark.composio
class TestCustomAddComment:
    """Tests for the CUSTOM_ADD_COMMENT production closure."""

    def _run(
        self,
        request: AddCommentInput,
        mock_resp: MagicMock | None = None,
    ) -> Dict[str, Any]:
        _, fns = _make_composio_mock()
        fn = fns["CUSTOM_ADD_COMMENT"]

        if mock_resp is None:
            mock_resp = _make_response(
                json_data={"id": "comment-id-1"},
                headers={"x-restli-id": "comment-id-1"},
            )

        with (
            patch(
                "app.agents.tools.integrations.linkedin_tool.get_author_urn",
                return_value=FAKE_AUTHOR_URN,
            ),
            patch(
                "app.agents.tools.integrations.linkedin_tool._http_client"
            ) as mock_http,
        ):
            mock_http.post.return_value = mock_resp
            return fn(request, EXECUTE_REQUEST_STUB, AUTH_CREDENTIALS)

    def test_happy_path(self):
        result = self._run(
            AddCommentInput(post_urn=FAKE_POST_URN, comment_text="Great post!")
        )
        assert result["comment_id"] == "comment-id-1"
        assert result["post_urn"] == FAKE_POST_URN
        assert result["author"] == FAKE_AUTHOR_URN

    def test_urn_is_url_encoded_in_path(self):
        _, fns = _make_composio_mock()
        fn = fns["CUSTOM_ADD_COMMENT"]

        request = AddCommentInput(post_urn="urn:li:share:12345", comment_text="Hi")
        ok_resp = _make_response(json_data={"id": "c1"})

        with (
            patch(
                "app.agents.tools.integrations.linkedin_tool.get_author_urn",
                return_value=FAKE_AUTHOR_URN,
            ),
            patch(
                "app.agents.tools.integrations.linkedin_tool._http_client"
            ) as mock_http,
        ):
            mock_http.post.return_value = ok_resp
            fn(request, EXECUTE_REQUEST_STUB, AUTH_CREDENTIALS)
            call_url = mock_http.post.call_args[0][0]

        assert "%3A" in call_url
        assert ":" not in call_url.split("/socialActions/")[1].split("/")[0]

    def test_nested_reply_includes_parent_comment(self):
        _, fns = _make_composio_mock()
        fn = fns["CUSTOM_ADD_COMMENT"]

        request = AddCommentInput(
            post_urn=FAKE_POST_URN,
            comment_text="Reply",
            parent_comment_urn="urn:li:comment:777",
        )
        ok_resp = _make_response(json_data={"id": "reply-1"})

        with (
            patch(
                "app.agents.tools.integrations.linkedin_tool.get_author_urn",
                return_value=FAKE_AUTHOR_URN,
            ),
            patch(
                "app.agents.tools.integrations.linkedin_tool._http_client"
            ) as mock_http,
        ):
            mock_http.post.return_value = ok_resp
            fn(request, EXECUTE_REQUEST_STUB, AUTH_CREDENTIALS)
            sent_body = mock_http.post.call_args[1]["json"]

        assert sent_body["parentComment"] == "urn:li:comment:777"

    def test_http_error_propagates(self):
        bad_resp = _make_response(status_code=403)
        with pytest.raises(httpx.HTTPStatusError):
            self._run(
                AddCommentInput(post_urn=FAKE_POST_URN, comment_text="fail"),
                mock_resp=bad_resp,
            )


# ---------------------------------------------------------------------------
# CUSTOM_GET_POST_COMMENTS
# ---------------------------------------------------------------------------


@pytest.mark.composio
class TestCustomGetPostComments:
    """Tests for the CUSTOM_GET_POST_COMMENTS production closure."""

    _RAW_COMMENTS = [
        {
            "id": "c1",
            "actor": "urn:li:person:p1",
            "message": {"text": "Nice post"},
            "created": {"time": 1700000000},
            "parentComment": None,
        }
    ]

    def _run(
        self,
        request: GetPostCommentsInput,
        mock_resp: MagicMock | None = None,
    ) -> Dict[str, Any]:
        _, fns = _make_composio_mock()
        fn = fns["CUSTOM_GET_POST_COMMENTS"]

        if mock_resp is None:
            mock_resp = _make_response(
                json_data={"elements": self._RAW_COMMENTS, "paging": {"total": 1}}
            )

        with patch(
            "app.agents.tools.integrations.linkedin_tool._http_client"
        ) as mock_http:
            mock_http.get.return_value = mock_resp
            return fn(request, EXECUTE_REQUEST_STUB, AUTH_CREDENTIALS)

    def test_returns_formatted_comments(self):
        result = self._run(GetPostCommentsInput(post_urn=FAKE_POST_URN))
        assert len(result["comments"]) == 1
        assert result["comments"][0]["id"] == "c1"
        assert result["comments"][0]["text"] == "Nice post"
        assert result["total_count"] == 1
        assert result["post_urn"] == FAKE_POST_URN

    def test_comment_fields_mapped_correctly(self):
        result = self._run(GetPostCommentsInput(post_urn=FAKE_POST_URN))
        c = result["comments"][0]
        assert c["author"] == "urn:li:person:p1"
        assert c["created_at"] == 1700000000
        assert c["parent_comment"] is None

    def test_pagination_params_sent(self):
        _, fns = _make_composio_mock()
        fn = fns["CUSTOM_GET_POST_COMMENTS"]

        request = GetPostCommentsInput(post_urn=FAKE_POST_URN, count=25, start=50)
        ok_resp = _make_response(json_data={"elements": [], "paging": {"total": 0}})

        with patch(
            "app.agents.tools.integrations.linkedin_tool._http_client"
        ) as mock_http:
            mock_http.get.return_value = ok_resp
            fn(request, EXECUTE_REQUEST_STUB, AUTH_CREDENTIALS)
            params = mock_http.get.call_args[1]["params"]

        assert params["count"] == 25
        assert params["start"] == 50

    def test_http_error_propagates(self):
        bad_resp = _make_response(status_code=404)
        with pytest.raises(httpx.HTTPStatusError):
            self._run(GetPostCommentsInput(post_urn=FAKE_POST_URN), mock_resp=bad_resp)


# ---------------------------------------------------------------------------
# CUSTOM_REACT_TO_POST
# ---------------------------------------------------------------------------


@pytest.mark.composio
class TestCustomReactToPost:
    """Tests for the CUSTOM_REACT_TO_POST production closure."""

    def _run(
        self,
        request: ReactToPostInput,
        mock_resp: MagicMock | None = None,
    ) -> Dict[str, Any]:
        _, fns = _make_composio_mock()
        fn = fns["CUSTOM_REACT_TO_POST"]

        if mock_resp is None:
            mock_resp = _make_response(status_code=201)

        with (
            patch(
                "app.agents.tools.integrations.linkedin_tool.get_author_urn",
                return_value=FAKE_AUTHOR_URN,
            ),
            patch(
                "app.agents.tools.integrations.linkedin_tool._http_client"
            ) as mock_http,
        ):
            mock_http.post.return_value = mock_resp
            return fn(request, EXECUTE_REQUEST_STUB, AUTH_CREDENTIALS)

    def test_like_reaction(self):
        result = self._run(ReactToPostInput(post_urn=FAKE_POST_URN))
        assert result["post_urn"] == FAKE_POST_URN
        assert result["reaction_type"] == "LIKE"
        assert result["author"] == FAKE_AUTHOR_URN

    def test_celebrate_reaction(self):
        result = self._run(
            ReactToPostInput(post_urn=FAKE_POST_URN, reaction_type="CELEBRATE")
        )
        assert result["reaction_type"] == "CELEBRATE"

    def test_support_reaction(self):
        result = self._run(
            ReactToPostInput(post_urn=FAKE_POST_URN, reaction_type="SUPPORT")
        )
        assert result["reaction_type"] == "SUPPORT"

    def test_insightful_reaction(self):
        result = self._run(
            ReactToPostInput(post_urn=FAKE_POST_URN, reaction_type="INSIGHTFUL")
        )
        assert result["reaction_type"] == "INSIGHTFUL"

    def test_invalid_reaction_type_rejected_by_model(self):
        with pytest.raises(Exception):
            ReactToPostInput(post_urn=FAKE_POST_URN, reaction_type="THUMBSUP")

    def test_http_error_propagates(self):
        bad_resp = _make_response(status_code=429)
        with pytest.raises(httpx.HTTPStatusError):
            self._run(ReactToPostInput(post_urn=FAKE_POST_URN), mock_resp=bad_resp)

    def test_reaction_endpoint_uses_likes_path(self):
        _, fns = _make_composio_mock()
        fn = fns["CUSTOM_REACT_TO_POST"]

        ok_resp = _make_response(status_code=201)
        request = ReactToPostInput(post_urn=FAKE_POST_URN)

        with (
            patch(
                "app.agents.tools.integrations.linkedin_tool.get_author_urn",
                return_value=FAKE_AUTHOR_URN,
            ),
            patch(
                "app.agents.tools.integrations.linkedin_tool._http_client"
            ) as mock_http,
        ):
            mock_http.post.return_value = ok_resp
            fn(request, EXECUTE_REQUEST_STUB, AUTH_CREDENTIALS)
            called_url = mock_http.post.call_args[0][0]

        assert "/likes" in called_url


# ---------------------------------------------------------------------------
# CUSTOM_DELETE_REACTION
# ---------------------------------------------------------------------------


@pytest.mark.composio
class TestCustomDeleteReaction:
    """Tests for the CUSTOM_DELETE_REACTION production closure."""

    def _run(
        self,
        request: DeleteReactionInput,
        mock_resp: MagicMock | None = None,
    ) -> Dict[str, Any]:
        _, fns = _make_composio_mock()
        fn = fns["CUSTOM_DELETE_REACTION"]

        if mock_resp is None:
            mock_resp = _make_response(status_code=204)

        with (
            patch(
                "app.agents.tools.integrations.linkedin_tool.get_author_urn",
                return_value=FAKE_AUTHOR_URN,
            ),
            patch(
                "app.agents.tools.integrations.linkedin_tool._http_client"
            ) as mock_http,
        ):
            mock_http.delete.return_value = mock_resp
            return fn(request, EXECUTE_REQUEST_STUB, AUTH_CREDENTIALS)

    def test_happy_path(self):
        result = self._run(DeleteReactionInput(post_urn=FAKE_POST_URN))
        assert result["post_urn"] == FAKE_POST_URN
        assert result["message"] == "Reaction removed successfully"

    def test_delete_url_contains_encoded_post_urn_and_author_urn(self):
        _, fns = _make_composio_mock()
        fn = fns["CUSTOM_DELETE_REACTION"]

        ok_resp = _make_response(status_code=204)
        encoded_post = FAKE_POST_URN.replace(":", "%3A")
        encoded_author = FAKE_AUTHOR_URN.replace(":", "%3A")

        with (
            patch(
                "app.agents.tools.integrations.linkedin_tool.get_author_urn",
                return_value=FAKE_AUTHOR_URN,
            ),
            patch(
                "app.agents.tools.integrations.linkedin_tool._http_client"
            ) as mock_http,
        ):
            mock_http.delete.return_value = ok_resp
            fn(
                DeleteReactionInput(post_urn=FAKE_POST_URN),
                EXECUTE_REQUEST_STUB,
                AUTH_CREDENTIALS,
            )
            called_url = mock_http.delete.call_args[0][0]

        assert encoded_post in called_url
        assert encoded_author in called_url
        assert ":" not in called_url.split("/socialActions/")[1]

    def test_http_error_propagates(self):
        bad_resp = _make_response(status_code=404)
        with pytest.raises(httpx.HTTPStatusError):
            self._run(DeleteReactionInput(post_urn=FAKE_POST_URN), mock_resp=bad_resp)

    def test_missing_access_token_raises(self):
        _, fns = _make_composio_mock()
        fn = fns["CUSTOM_DELETE_REACTION"]
        with pytest.raises(ValueError, match="Missing access_token"):
            fn(DeleteReactionInput(post_urn=FAKE_POST_URN), EXECUTE_REQUEST_STUB, {})


# ---------------------------------------------------------------------------
# CUSTOM_GET_POST_REACTIONS
# ---------------------------------------------------------------------------


@pytest.mark.composio
class TestCustomGetPostReactions:
    """Tests for the CUSTOM_GET_POST_REACTIONS production closure."""

    _RAW_REACTIONS = [
        {
            "actor": "urn:li:person:p1",
            "reactionType": "LIKE",
            "created": {"time": 1700000000},
        },
        {
            "actor": "urn:li:person:p2",
            "reactionType": "CELEBRATE",
            "created": {"time": 1700001000},
        },
    ]

    def _run(
        self,
        request: GetPostReactionsInput,
        mock_resp: MagicMock | None = None,
    ) -> Dict[str, Any]:
        _, fns = _make_composio_mock()
        fn = fns["CUSTOM_GET_POST_REACTIONS"]

        if mock_resp is None:
            mock_resp = _make_response(
                json_data={"elements": self._RAW_REACTIONS, "paging": {"total": 2}}
            )

        with patch(
            "app.agents.tools.integrations.linkedin_tool._http_client"
        ) as mock_http:
            mock_http.get.return_value = mock_resp
            return fn(request, EXECUTE_REQUEST_STUB, AUTH_CREDENTIALS)

    def test_returns_formatted_reactions(self):
        result = self._run(GetPostReactionsInput(post_urn=FAKE_POST_URN))
        assert len(result["reactions"]) == 2
        assert result["total_count"] == 2
        assert result["post_urn"] == FAKE_POST_URN

    def test_reaction_fields_mapped_correctly(self):
        result = self._run(GetPostReactionsInput(post_urn=FAKE_POST_URN))
        r0 = result["reactions"][0]
        assert r0["actor"] == "urn:li:person:p1"
        assert r0["reaction_type"] == "LIKE"
        assert r0["created_at"] == 1700000000

    def test_celebrate_reaction_type_preserved(self):
        result = self._run(GetPostReactionsInput(post_urn=FAKE_POST_URN))
        assert result["reactions"][1]["reaction_type"] == "CELEBRATE"

    def test_count_param_forwarded(self):
        _, fns = _make_composio_mock()
        fn = fns["CUSTOM_GET_POST_REACTIONS"]

        request = GetPostReactionsInput(post_urn=FAKE_POST_URN, count=50)
        ok_resp = _make_response(json_data={"elements": [], "paging": {"total": 0}})

        with patch(
            "app.agents.tools.integrations.linkedin_tool._http_client"
        ) as mock_http:
            mock_http.get.return_value = ok_resp
            fn(request, EXECUTE_REQUEST_STUB, AUTH_CREDENTIALS)
            params = mock_http.get.call_args[1]["params"]

        assert params["count"] == 50

    def test_empty_reactions_list(self):
        ok_resp = _make_response(json_data={"elements": [], "paging": {"total": 0}})
        result = self._run(
            GetPostReactionsInput(post_urn=FAKE_POST_URN), mock_resp=ok_resp
        )
        assert result["reactions"] == []
        assert result["total_count"] == 0

    def test_http_error_propagates(self):
        bad_resp = _make_response(status_code=500)
        with pytest.raises(httpx.HTTPStatusError):
            self._run(GetPostReactionsInput(post_urn=FAKE_POST_URN), mock_resp=bad_resp)


# ---------------------------------------------------------------------------
# register_linkedin_custom_tools returns correct tool name list
# ---------------------------------------------------------------------------


@pytest.mark.composio
class TestRegisterLinkedInCustomTools:
    def test_returns_all_six_tool_names(self):
        from app.agents.tools.integrations.linkedin_tool import (
            register_linkedin_custom_tools,
        )

        mock_composio = MagicMock()
        mock_composio.tools.custom_tool.return_value = lambda fn: fn

        names = register_linkedin_custom_tools(mock_composio)

        assert set(names) == {
            "LINKEDIN_CUSTOM_CREATE_POST",
            "LINKEDIN_CUSTOM_ADD_COMMENT",
            "LINKEDIN_CUSTOM_GET_POST_COMMENTS",
            "LINKEDIN_CUSTOM_REACT_TO_POST",
            "LINKEDIN_CUSTOM_DELETE_REACTION",
            "LINKEDIN_CUSTOM_GET_POST_REACTIONS",
            "LINKEDIN_CUSTOM_GATHER_CONTEXT",
        }
        assert len(names) == 7
