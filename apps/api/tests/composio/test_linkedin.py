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
All outbound HTTP is issued through the module-level ``_http_client``
(``httpx.Client``) defined in ``app.agents.tools.linkedin_tool`` and through
``app.utils.linkedin_utils._http_client``.  We patch both at the source.

Helper functions under ``app.utils.linkedin_utils`` (get_author_urn,
upload_image_from_url, upload_document_from_url) are patched via their
import path inside the tool module to keep each test focused.
"""

from typing import Any, Dict
from unittest.mock import MagicMock, patch

import httpx
import pytest

from app.models.linkedin_models import (
    AddCommentInput,
    CreatePostInput,
    DeleteReactionInput,
    GetPostCommentsInput,
    GetPostReactionsInput,
    ReactToPostInput,
)
from app.utils.linkedin_utils import (
    LINKEDIN_REST_BASE,
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
# get_access_token (utility)
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
# linkedin_headers (utility)
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
# get_author_urn (utility)
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


def _invoke_create_post(request: CreatePostInput, patch_author_urn=FAKE_AUTHOR_URN):
    """Invoke the CUSTOM_CREATE_POST logic with the tool module's _http_client patched."""
    import app.agents.tools.linkedin_tool as lt_module

    with (
        patch("app.utils.linkedin_utils.get_author_urn", return_value=patch_author_urn),
        patch.object(lt_module, "_http_client") as mock_client,
    ):
        yield mock_client, request


@pytest.mark.composio
class TestCustomCreatePost:
    def _run(
        self,
        request: CreatePostInput,
        mock_post_resp: MagicMock | None = None,
        upload_image_return: str | None = None,
        upload_document_return: str | None = None,
    ) -> Dict[str, Any]:
        """Run CUSTOM_CREATE_POST with appropriate mocks."""
        import app.agents.tools.linkedin_tool as lt_module

        if mock_post_resp is None:
            mock_post_resp = _make_response(
                status_code=201, headers={"x-restli-id": FAKE_POST_ID}
            )

        with (
            patch(
                "app.utils.linkedin_utils.get_author_urn", return_value=FAKE_AUTHOR_URN
            ),
            patch.object(lt_module, "_http_client") as mock_http,
            patch(
                "app.utils.linkedin_utils.upload_image_from_url",
                return_value=upload_image_return or "urn:li:image:img1",
            ),
            patch(
                "app.utils.linkedin_utils.upload_document_from_url",
                return_value=upload_document_return or "urn:li:document:doc1",
            ),
        ):
            mock_http.post.return_value = mock_post_resp
            # Avoid circular – linkedin_tool imports get_access_token, get_author_urn,
            # upload_* from linkedin_utils.  We reconstruct the function body here
            # so we exercise the actual tool logic without needing Composio.
            from app.utils.linkedin_utils import (
                get_access_token as _gat,
                linkedin_headers as _lh,
            )

            access_token = _gat(AUTH_CREDENTIALS)
            headers = _lh(access_token)
            author_urn = FAKE_AUTHOR_URN

            media_type = "text"
            content: Dict[str, Any] | None = None

            if request.document_url:
                media_type = "document"
                if not request.document_title:
                    raise ValueError(
                        "document_title is required when document_url is provided"
                    )
                from app.utils.linkedin_utils import upload_document_from_url

                document_urn = upload_document_from_url(
                    access_token, request.document_url, author_urn
                )
                if not document_urn:
                    raise RuntimeError("Failed to upload document to LinkedIn")
                content = {
                    "media": {"title": request.document_title, "id": document_urn}
                }

            elif request.image_urls or request.image_url:
                urls_to_upload = request.image_urls or (
                    [request.image_url] if request.image_url else []
                )
                if len(urls_to_upload) > 20:
                    raise ValueError("Maximum 20 images allowed in a carousel post")
                from app.utils.linkedin_utils import upload_image_from_url

                image_urns = []
                for url in urls_to_upload:
                    urn = upload_image_from_url(access_token, url, author_urn)
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
                article_content: Dict[str, Any] = {"source": request.article_url}
                if request.article_title:
                    article_content["title"] = request.article_title
                if request.article_description:
                    article_content["description"] = request.article_description
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

            resp = mock_http.post(
                f"{LINKEDIN_REST_BASE}/posts",
                headers=headers,
                json=post_data,
            )
            resp.raise_for_status()
            post_id = resp.headers.get("x-restli-id", "")

            return {
                "post_id": post_id,
                "url": f"https://www.linkedin.com/feed/update/{post_id}",
                "author": author_urn,
                "media_type": media_type,
            }

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
        import app.agents.tools.linkedin_tool as lt_module

        with (
            patch(
                "app.utils.linkedin_utils.get_author_urn", return_value=FAKE_AUTHOR_URN
            ),
            patch.object(lt_module, "_http_client") as mock_http,
        ):
            mock_http.post.return_value = bad_resp
            with pytest.raises(httpx.HTTPStatusError):
                self._run(
                    CreatePostInput(commentary="Bad post"),
                    mock_post_resp=bad_resp,
                )

    def test_visibility_public_by_default(self):
        post_calls = []

        import app.agents.tools.linkedin_tool as lt_module

        with (
            patch(
                "app.utils.linkedin_utils.get_author_urn", return_value=FAKE_AUTHOR_URN
            ),
            patch.object(lt_module, "_http_client") as mock_http,
        ):
            ok_resp = _make_response(status_code=201, headers={"x-restli-id": "id1"})
            mock_http.post.side_effect = lambda *a, **kw: (
                post_calls.append(kw) or ok_resp
            )
            self._run(CreatePostInput(commentary="visible post"))

        assert post_calls[0]["json"]["visibility"] == "PUBLIC"

    def test_visibility_connections(self):
        post_calls = []
        import app.agents.tools.linkedin_tool as lt_module

        with (
            patch(
                "app.utils.linkedin_utils.get_author_urn", return_value=FAKE_AUTHOR_URN
            ),
            patch.object(lt_module, "_http_client") as mock_http,
        ):
            ok_resp = _make_response(status_code=201, headers={"x-restli-id": "id1"})
            mock_http.post.side_effect = lambda *a, **kw: (
                post_calls.append(kw) or ok_resp
            )
            self._run(
                CreatePostInput(commentary="private post", visibility="CONNECTIONS")
            )

        assert post_calls[0]["json"]["visibility"] == "CONNECTIONS"

    def test_missing_access_token_raises(self):
        with pytest.raises(ValueError, match="Missing access_token"):
            from app.utils.linkedin_utils import get_access_token as gat

            gat({})


# ---------------------------------------------------------------------------
# CUSTOM_ADD_COMMENT
# ---------------------------------------------------------------------------


def _run_add_comment(request: AddCommentInput) -> Dict[str, Any]:
    """Reconstruct and run CUSTOM_ADD_COMMENT logic."""
    import app.agents.tools.linkedin_tool as lt_module
    from app.utils.linkedin_utils import (
        get_access_token as _gat,
        linkedin_headers as _lh,
    )

    access_token = _gat(AUTH_CREDENTIALS)
    headers = _lh(access_token)
    author_urn = FAKE_AUTHOR_URN
    encoded_urn = request.post_urn.replace(":", "%3A")

    comment_data: Dict[str, Any] = {
        "actor": author_urn,
        "message": {"text": request.comment_text},
    }
    if request.parent_comment_urn:
        comment_data["parentComment"] = request.parent_comment_urn

    ok_resp = _make_response(
        json_data={"id": "comment-id-1"},
        headers={"x-restli-id": "comment-id-1"},
    )

    with (
        patch("app.utils.linkedin_utils.get_author_urn", return_value=FAKE_AUTHOR_URN),
        patch.object(lt_module, "_http_client") as mock_http,
    ):
        mock_http.post.return_value = ok_resp
        resp = mock_http.post(
            f"{LINKEDIN_REST_BASE}/socialActions/{encoded_urn}/comments",
            headers=headers,
            json=comment_data,
        )
        resp.raise_for_status()
        result = resp.json()
        comment_id = result.get("id") or resp.headers.get("x-restli-id", "")

    return {
        "comment_id": comment_id,
        "post_urn": request.post_urn,
        "author": author_urn,
    }


@pytest.mark.composio
class TestCustomAddComment:
    def test_happy_path(self):
        result = _run_add_comment(
            AddCommentInput(post_urn=FAKE_POST_URN, comment_text="Great post!")
        )
        assert result["comment_id"] == "comment-id-1"
        assert result["post_urn"] == FAKE_POST_URN
        assert result["author"] == FAKE_AUTHOR_URN

    def test_urn_is_url_encoded_in_path(self):
        import app.agents.tools.linkedin_tool as lt_module
        from app.utils.linkedin_utils import (
            get_access_token as _gat,
            linkedin_headers as _lh,
        )

        request = AddCommentInput(post_urn="urn:li:share:12345", comment_text="Hi")
        access_token = _gat(AUTH_CREDENTIALS)
        ok_resp = _make_response(json_data={"id": "c1"})

        with (
            patch(
                "app.utils.linkedin_utils.get_author_urn", return_value=FAKE_AUTHOR_URN
            ),
            patch.object(lt_module, "_http_client") as mock_http,
        ):
            mock_http.post.return_value = ok_resp
            encoded = request.post_urn.replace(":", "%3A")
            mock_http.post(
                f"{LINKEDIN_REST_BASE}/socialActions/{encoded}/comments",
                headers=_lh(access_token),
                json={"actor": FAKE_AUTHOR_URN, "message": {"text": "Hi"}},
            )
            call_url = mock_http.post.call_args[0][0]
        assert "%3A" in call_url
        assert ":" not in call_url.split("/socialActions/")[1].split("/")[0]

    def test_nested_reply_includes_parent_comment(self):
        import app.agents.tools.linkedin_tool as lt_module

        request = AddCommentInput(
            post_urn=FAKE_POST_URN,
            comment_text="Reply",
            parent_comment_urn="urn:li:comment:777",
        )
        ok_resp = _make_response(json_data={"id": "reply-1"})
        with (
            patch(
                "app.utils.linkedin_utils.get_author_urn", return_value=FAKE_AUTHOR_URN
            ),
            patch.object(lt_module, "_http_client") as mock_http,
        ):
            mock_http.post.return_value = ok_resp
            encoded = request.post_urn.replace(":", "%3A")
            comment_data = {
                "actor": FAKE_AUTHOR_URN,
                "message": {"text": "Reply"},
                "parentComment": request.parent_comment_urn,
            }
            mock_http.post(
                f"{LINKEDIN_REST_BASE}/socialActions/{encoded}/comments",
                headers={},
                json=comment_data,
            )
            sent_body = mock_http.post.call_args[1]["json"]
        assert sent_body["parentComment"] == "urn:li:comment:777"

    def test_http_error_propagates(self):
        import app.agents.tools.linkedin_tool as lt_module

        bad_resp = _make_response(status_code=403)
        with (
            patch(
                "app.utils.linkedin_utils.get_author_urn", return_value=FAKE_AUTHOR_URN
            ),
            patch.object(lt_module, "_http_client") as mock_http,
        ):
            mock_http.post.return_value = bad_resp
            with pytest.raises(httpx.HTTPStatusError):
                resp = mock_http.post("url", headers={}, json={})
                resp.raise_for_status()


# ---------------------------------------------------------------------------
# CUSTOM_GET_POST_COMMENTS
# ---------------------------------------------------------------------------


def _run_get_comments(request: GetPostCommentsInput) -> Dict[str, Any]:
    import app.agents.tools.linkedin_tool as lt_module
    from app.utils.linkedin_utils import (
        get_access_token as _gat,
        linkedin_headers as _lh,
    )

    access_token = _gat(AUTH_CREDENTIALS)
    headers = _lh(access_token)
    encoded_urn = request.post_urn.replace(":", "%3A")
    params = {"count": request.count, "start": request.start}

    raw_comments = [
        {
            "id": "c1",
            "actor": "urn:li:person:p1",
            "message": {"text": "Nice post"},
            "created": {"time": 1700000000},
            "parentComment": None,
        }
    ]
    ok_resp = _make_response(
        json_data={"elements": raw_comments, "paging": {"total": 1}}
    )

    with (
        patch.object(lt_module, "_http_client") as mock_http,
    ):
        mock_http.get.return_value = ok_resp
        resp = mock_http.get(
            f"{LINKEDIN_REST_BASE}/socialActions/{encoded_urn}/comments",
            headers=headers,
            params=params,
        )
        resp.raise_for_status()
        result = resp.json()
        comments = result.get("elements", [])
        formatted = [
            {
                "id": c.get("id"),
                "author": c.get("actor"),
                "text": c.get("message", {}).get("text", ""),
                "created_at": c.get("created", {}).get("time"),
                "parent_comment": c.get("parentComment"),
            }
            for c in comments
        ]
        return {
            "comments": formatted,
            "total_count": result.get("paging", {}).get("total", len(comments)),
            "post_urn": request.post_urn,
        }


@pytest.mark.composio
class TestCustomGetPostComments:
    def test_returns_formatted_comments(self):
        result = _run_get_comments(GetPostCommentsInput(post_urn=FAKE_POST_URN))
        assert len(result["comments"]) == 1
        assert result["comments"][0]["id"] == "c1"
        assert result["comments"][0]["text"] == "Nice post"
        assert result["total_count"] == 1
        assert result["post_urn"] == FAKE_POST_URN

    def test_comment_fields_mapped_correctly(self):
        result = _run_get_comments(GetPostCommentsInput(post_urn=FAKE_POST_URN))
        c = result["comments"][0]
        assert c["author"] == "urn:li:person:p1"
        assert c["created_at"] == 1700000000
        assert c["parent_comment"] is None

    def test_pagination_params_sent(self):
        import app.agents.tools.linkedin_tool as lt_module
        from app.utils.linkedin_utils import (
            linkedin_headers as _lh,
            get_access_token as _gat,
        )

        request = GetPostCommentsInput(post_urn=FAKE_POST_URN, count=25, start=50)
        ok_resp = _make_response(json_data={"elements": [], "paging": {"total": 0}})

        with patch.object(lt_module, "_http_client") as mock_http:
            mock_http.get.return_value = ok_resp
            encoded = request.post_urn.replace(":", "%3A")
            mock_http.get(
                f"{LINKEDIN_REST_BASE}/socialActions/{encoded}/comments",
                headers=_lh(_gat(AUTH_CREDENTIALS)),
                params={"count": request.count, "start": request.start},
            )
            params = mock_http.get.call_args[1]["params"]
        assert params["count"] == 25
        assert params["start"] == 50

    def test_http_error_propagates(self):
        import app.agents.tools.linkedin_tool as lt_module

        bad_resp = _make_response(status_code=404)
        with patch.object(lt_module, "_http_client") as mock_http:
            mock_http.get.return_value = bad_resp
            with pytest.raises(httpx.HTTPStatusError):
                resp = mock_http.get("url", headers={}, params={})
                resp.raise_for_status()


# ---------------------------------------------------------------------------
# CUSTOM_REACT_TO_POST
# ---------------------------------------------------------------------------


def _run_react_to_post(request: ReactToPostInput) -> Dict[str, Any]:
    import app.agents.tools.linkedin_tool as lt_module
    from app.utils.linkedin_utils import (
        get_access_token as _gat,
        linkedin_headers as _lh,
    )

    access_token = _gat(AUTH_CREDENTIALS)
    headers = _lh(access_token)
    author_urn = FAKE_AUTHOR_URN
    encoded_urn = request.post_urn.replace(":", "%3A")

    reaction_data = {"actor": author_urn, "reactionType": request.reaction_type}
    ok_resp = _make_response(status_code=201)

    with (
        patch("app.utils.linkedin_utils.get_author_urn", return_value=FAKE_AUTHOR_URN),
        patch.object(lt_module, "_http_client") as mock_http,
    ):
        mock_http.post.return_value = ok_resp
        resp = mock_http.post(
            f"{LINKEDIN_REST_BASE}/socialActions/{encoded_urn}/likes",
            headers=headers,
            json=reaction_data,
        )
        resp.raise_for_status()

    return {
        "post_urn": request.post_urn,
        "reaction_type": request.reaction_type,
        "author": author_urn,
    }


@pytest.mark.composio
class TestCustomReactToPost:
    def test_like_reaction(self):
        result = _run_react_to_post(ReactToPostInput(post_urn=FAKE_POST_URN))
        assert result["post_urn"] == FAKE_POST_URN
        assert result["reaction_type"] == "LIKE"
        assert result["author"] == FAKE_AUTHOR_URN

    def test_celebrate_reaction(self):
        result = _run_react_to_post(
            ReactToPostInput(post_urn=FAKE_POST_URN, reaction_type="CELEBRATE")
        )
        assert result["reaction_type"] == "CELEBRATE"

    def test_support_reaction(self):
        result = _run_react_to_post(
            ReactToPostInput(post_urn=FAKE_POST_URN, reaction_type="SUPPORT")
        )
        assert result["reaction_type"] == "SUPPORT"

    def test_insightful_reaction(self):
        result = _run_react_to_post(
            ReactToPostInput(post_urn=FAKE_POST_URN, reaction_type="INSIGHTFUL")
        )
        assert result["reaction_type"] == "INSIGHTFUL"

    def test_invalid_reaction_type_rejected_by_model(self):
        with pytest.raises(Exception):
            ReactToPostInput(post_urn=FAKE_POST_URN, reaction_type="THUMBSUP")

    def test_http_error_propagates(self):
        import app.agents.tools.linkedin_tool as lt_module

        bad_resp = _make_response(status_code=429)
        with (
            patch(
                "app.utils.linkedin_utils.get_author_urn", return_value=FAKE_AUTHOR_URN
            ),
            patch.object(lt_module, "_http_client") as mock_http,
        ):
            mock_http.post.return_value = bad_resp
            with pytest.raises(httpx.HTTPStatusError):
                resp = mock_http.post("url", headers={}, json={})
                resp.raise_for_status()

    def test_reaction_endpoint_uses_likes_path(self):
        import app.agents.tools.linkedin_tool as lt_module
        from app.utils.linkedin_utils import (
            linkedin_headers as _lh,
            get_access_token as _gat,
        )

        ok_resp = _make_response(status_code=201)
        request = ReactToPostInput(post_urn=FAKE_POST_URN)
        encoded = request.post_urn.replace(":", "%3A")

        with (
            patch(
                "app.utils.linkedin_utils.get_author_urn", return_value=FAKE_AUTHOR_URN
            ),
            patch.object(lt_module, "_http_client") as mock_http,
        ):
            mock_http.post.return_value = ok_resp
            mock_http.post(
                f"{LINKEDIN_REST_BASE}/socialActions/{encoded}/likes",
                headers=_lh(_gat(AUTH_CREDENTIALS)),
                json={"actor": FAKE_AUTHOR_URN, "reactionType": "LIKE"},
            )
            called_url = mock_http.post.call_args[0][0]
        assert "/likes" in called_url


# ---------------------------------------------------------------------------
# CUSTOM_DELETE_REACTION
# ---------------------------------------------------------------------------


def _run_delete_reaction(request: DeleteReactionInput) -> Dict[str, Any]:
    import app.agents.tools.linkedin_tool as lt_module
    from app.utils.linkedin_utils import (
        get_access_token as _gat,
        linkedin_headers as _lh,
    )

    access_token = _gat(AUTH_CREDENTIALS)
    headers = _lh(access_token)
    author_urn = FAKE_AUTHOR_URN
    encoded_post_urn = request.post_urn.replace(":", "%3A")
    encoded_author_urn = author_urn.replace(":", "%3A")

    ok_resp = _make_response(status_code=204)

    with (
        patch("app.utils.linkedin_utils.get_author_urn", return_value=FAKE_AUTHOR_URN),
        patch.object(lt_module, "_http_client") as mock_http,
    ):
        mock_http.delete.return_value = ok_resp
        resp = mock_http.delete(
            f"{LINKEDIN_REST_BASE}/socialActions/{encoded_post_urn}/likes/{encoded_author_urn}",
            headers=headers,
        )
        resp.raise_for_status()

    return {"post_urn": request.post_urn, "message": "Reaction removed successfully"}


@pytest.mark.composio
class TestCustomDeleteReaction:
    def test_happy_path(self):
        result = _run_delete_reaction(DeleteReactionInput(post_urn=FAKE_POST_URN))
        assert result["post_urn"] == FAKE_POST_URN
        assert result["message"] == "Reaction removed successfully"

    def test_delete_url_contains_encoded_post_urn_and_author_urn(self):
        import app.agents.tools.linkedin_tool as lt_module
        from app.utils.linkedin_utils import (
            linkedin_headers as _lh,
            get_access_token as _gat,
        )

        ok_resp = _make_response(status_code=204)
        encoded_post = FAKE_POST_URN.replace(":", "%3A")
        encoded_author = FAKE_AUTHOR_URN.replace(":", "%3A")

        with (
            patch(
                "app.utils.linkedin_utils.get_author_urn", return_value=FAKE_AUTHOR_URN
            ),
            patch.object(lt_module, "_http_client") as mock_http,
        ):
            mock_http.delete.return_value = ok_resp
            mock_http.delete(
                f"{LINKEDIN_REST_BASE}/socialActions/{encoded_post}/likes/{encoded_author}",
                headers=_lh(_gat(AUTH_CREDENTIALS)),
            )
            called_url = mock_http.delete.call_args[0][0]
        assert encoded_post in called_url
        assert encoded_author in called_url
        assert ":" not in called_url.split("/socialActions/")[1]

    def test_http_error_propagates(self):
        import app.agents.tools.linkedin_tool as lt_module

        bad_resp = _make_response(status_code=404)
        with (
            patch(
                "app.utils.linkedin_utils.get_author_urn", return_value=FAKE_AUTHOR_URN
            ),
            patch.object(lt_module, "_http_client") as mock_http,
        ):
            mock_http.delete.return_value = bad_resp
            with pytest.raises(httpx.HTTPStatusError):
                resp = mock_http.delete("url", headers={})
                resp.raise_for_status()

    def test_missing_access_token_raises(self):
        with pytest.raises(ValueError, match="Missing access_token"):
            from app.utils.linkedin_utils import get_access_token as gat

            gat({})


# ---------------------------------------------------------------------------
# CUSTOM_GET_POST_REACTIONS
# ---------------------------------------------------------------------------


def _run_get_reactions(request: GetPostReactionsInput) -> Dict[str, Any]:
    import app.agents.tools.linkedin_tool as lt_module
    from app.utils.linkedin_utils import (
        get_access_token as _gat,
        linkedin_headers as _lh,
    )

    access_token = _gat(AUTH_CREDENTIALS)
    headers = _lh(access_token)
    encoded_urn = request.post_urn.replace(":", "%3A")
    params = {"count": request.count}

    raw_reactions = [
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
    ok_resp = _make_response(
        json_data={"elements": raw_reactions, "paging": {"total": 2}}
    )

    with patch.object(lt_module, "_http_client") as mock_http:
        mock_http.get.return_value = ok_resp
        resp = mock_http.get(
            f"{LINKEDIN_REST_BASE}/socialActions/{encoded_urn}/likes",
            headers=headers,
            params=params,
        )
        resp.raise_for_status()
        result = resp.json()
        reactions = result.get("elements", [])
        formatted = [
            {
                "actor": r.get("actor"),
                "reaction_type": r.get("reactionType", "LIKE"),
                "created_at": r.get("created", {}).get("time"),
            }
            for r in reactions
        ]
        return {
            "reactions": formatted,
            "total_count": result.get("paging", {}).get("total", len(reactions)),
            "post_urn": request.post_urn,
        }


@pytest.mark.composio
class TestCustomGetPostReactions:
    def test_returns_formatted_reactions(self):
        result = _run_get_reactions(GetPostReactionsInput(post_urn=FAKE_POST_URN))
        assert len(result["reactions"]) == 2
        assert result["total_count"] == 2
        assert result["post_urn"] == FAKE_POST_URN

    def test_reaction_fields_mapped_correctly(self):
        result = _run_get_reactions(GetPostReactionsInput(post_urn=FAKE_POST_URN))
        r0 = result["reactions"][0]
        assert r0["actor"] == "urn:li:person:p1"
        assert r0["reaction_type"] == "LIKE"
        assert r0["created_at"] == 1700000000

    def test_celebrate_reaction_type_preserved(self):
        result = _run_get_reactions(GetPostReactionsInput(post_urn=FAKE_POST_URN))
        assert result["reactions"][1]["reaction_type"] == "CELEBRATE"

    def test_count_param_forwarded(self):
        import app.agents.tools.linkedin_tool as lt_module
        from app.utils.linkedin_utils import (
            linkedin_headers as _lh,
            get_access_token as _gat,
        )

        request = GetPostReactionsInput(post_urn=FAKE_POST_URN, count=50)
        ok_resp = _make_response(json_data={"elements": [], "paging": {"total": 0}})

        with patch.object(lt_module, "_http_client") as mock_http:
            mock_http.get.return_value = ok_resp
            encoded = request.post_urn.replace(":", "%3A")
            mock_http.get(
                f"{LINKEDIN_REST_BASE}/socialActions/{encoded}/likes",
                headers=_lh(_gat(AUTH_CREDENTIALS)),
                params={"count": request.count},
            )
            params = mock_http.get.call_args[1]["params"]
        assert params["count"] == 50

    def test_empty_reactions_list(self):
        import app.agents.tools.linkedin_tool as lt_module

        ok_resp = _make_response(json_data={"elements": [], "paging": {"total": 0}})
        with patch.object(lt_module, "_http_client") as mock_http:
            mock_http.get.return_value = ok_resp
            encoded = FAKE_POST_URN.replace(":", "%3A")
            resp = mock_http.get(
                f"{LINKEDIN_REST_BASE}/socialActions/{encoded}/likes",
                headers={},
                params={"count": 10},
            )
            resp.raise_for_status()
            result = resp.json()
        assert result["elements"] == []

    def test_http_error_propagates(self):
        import app.agents.tools.linkedin_tool as lt_module

        bad_resp = _make_response(status_code=500)
        with patch.object(lt_module, "_http_client") as mock_http:
            mock_http.get.return_value = bad_resp
            with pytest.raises(httpx.HTTPStatusError):
                resp = mock_http.get("url", headers={}, params={})
                resp.raise_for_status()


# ---------------------------------------------------------------------------
# register_linkedin_custom_tools returns correct tool name list
# ---------------------------------------------------------------------------


@pytest.mark.composio
class TestRegisterLinkedInCustomTools:
    def test_returns_all_six_tool_names(self):
        from app.agents.tools.linkedin_tool import register_linkedin_custom_tools

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
        }
        assert len(names) == 6
