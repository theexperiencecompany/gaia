"""Unit tests for app.utils.linkedin_utils — LinkedIn API helpers."""

from unittest.mock import MagicMock, patch

import httpx
import pytest

from app.utils.linkedin_utils import (
    LINKEDIN_API_BASE,
    LINKEDIN_REST_BASE,
    LINKEDIN_VERSION,
    get_access_token,
    get_author_urn,
    linkedin_headers,
    upload_document_from_url,
    upload_image_from_url,
)


# ---------------------------------------------------------------------------
# get_access_token
# ---------------------------------------------------------------------------


class TestGetAccessToken:
    """Tests for get_access_token helper."""

    def test_returns_token_when_present(self) -> None:
        """Valid credentials dict yields the access token."""
        creds = {"access_token": "tok_abc123"}
        assert get_access_token(creds) == "tok_abc123"

    def test_raises_when_token_missing(self) -> None:
        """Missing access_token key raises ValueError."""
        with pytest.raises(ValueError, match="Missing access_token"):
            get_access_token({})

    def test_raises_when_token_empty_string(self) -> None:
        """Empty-string token is falsy and should raise ValueError."""
        with pytest.raises(ValueError, match="Missing access_token"):
            get_access_token({"access_token": ""})

    def test_raises_when_token_none(self) -> None:
        """Explicit None value should raise ValueError."""
        with pytest.raises(ValueError, match="Missing access_token"):
            get_access_token({"access_token": None})


# ---------------------------------------------------------------------------
# linkedin_headers
# ---------------------------------------------------------------------------


class TestLinkedinHeaders:
    """Tests for linkedin_headers helper."""

    def test_returns_correct_headers(self) -> None:
        """Headers include Bearer token, content type, protocol version, and API version."""
        headers = linkedin_headers("tok_test")
        assert headers == {
            "Authorization": "Bearer tok_test",
            "Content-Type": "application/json",
            "X-Restli-Protocol-Version": "2.0.0",
            "LinkedIn-Version": LINKEDIN_VERSION,
        }

    def test_authorization_uses_bearer_scheme(self) -> None:
        """Authorization header starts with 'Bearer '."""
        headers = linkedin_headers("my_token")
        assert headers["Authorization"].startswith("Bearer ")


# ---------------------------------------------------------------------------
# get_author_urn
# ---------------------------------------------------------------------------


class TestGetAuthorUrn:
    """Tests for get_author_urn — resolves person or organization URN."""

    @patch("app.utils.linkedin_utils.log")
    def test_organization_id_with_urn_prefix(self, _mock_log: MagicMock) -> None:
        """If org_id already has the URN prefix, return it as-is."""
        urn = get_author_urn("tok", organization_id="urn:li:organization:12345")
        assert urn == "urn:li:organization:12345"

    @patch("app.utils.linkedin_utils.log")
    def test_organization_id_without_urn_prefix(self, _mock_log: MagicMock) -> None:
        """Plain numeric org_id gets wrapped in the URN prefix."""
        urn = get_author_urn("tok", organization_id="67890")
        assert urn == "urn:li:organization:67890"

    @patch("app.utils.linkedin_utils.log")
    @patch("app.utils.linkedin_utils._http_client")
    def test_fetches_person_urn_when_no_org_id(
        self, mock_client: MagicMock, _mock_log: MagicMock
    ) -> None:
        """Without org_id, fetches /userinfo and builds a person URN from 'sub'."""
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"sub": "abc_person"}
        mock_resp.raise_for_status = MagicMock()
        mock_client.get.return_value = mock_resp

        urn = get_author_urn("tok_user")
        assert urn == "urn:li:person:abc_person"
        mock_client.get.assert_called_once_with(
            f"{LINKEDIN_API_BASE}/userinfo",
            headers={"Authorization": "Bearer tok_user"},
        )

    @patch("app.utils.linkedin_utils.log")
    @patch("app.utils.linkedin_utils._http_client")
    def test_raises_when_sub_missing(
        self, mock_client: MagicMock, _mock_log: MagicMock
    ) -> None:
        """If userinfo response has no 'sub', raises ValueError."""
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"name": "John"}  # no sub
        mock_resp.raise_for_status = MagicMock()
        mock_client.get.return_value = mock_resp

        with pytest.raises(ValueError, match="Could not determine author URN"):
            get_author_urn("tok_user")

    @patch("app.utils.linkedin_utils.log")
    @patch("app.utils.linkedin_utils._http_client")
    def test_raises_when_http_request_fails(
        self, mock_client: MagicMock, _mock_log: MagicMock
    ) -> None:
        """HTTP errors during /userinfo call fall through to ValueError."""
        mock_client.get.side_effect = httpx.HTTPStatusError(
            "500", request=MagicMock(), response=MagicMock()
        )

        with pytest.raises(ValueError, match="Could not determine author URN"):
            get_author_urn("tok_bad")


# ---------------------------------------------------------------------------
# upload_image_from_url
# ---------------------------------------------------------------------------


class TestUploadImageFromUrl:
    """Tests for upload_image_from_url — downloads then uploads to LinkedIn."""

    @patch("app.utils.linkedin_utils.log")
    @patch("app.utils.linkedin_utils._http_client")
    def test_success_returns_image_urn(
        self, mock_client: MagicMock, _mock_log: MagicMock
    ) -> None:
        """Happy path: init → download → upload → returns image URN."""
        init_resp = MagicMock()
        init_resp.json.return_value = {
            "value": {
                "uploadUrl": "https://linkedin.upload/img",
                "image": "urn:li:digitalmediaAsset:img123",
            }
        }
        init_resp.raise_for_status = MagicMock()

        img_resp = MagicMock()
        img_resp.content = b"\x89PNG"
        img_resp.headers = {"content-type": "image/png"}
        img_resp.raise_for_status = MagicMock()

        upload_resp = MagicMock()
        upload_resp.raise_for_status = MagicMock()

        mock_client.post.return_value = init_resp
        mock_client.get.return_value = img_resp
        mock_client.put.return_value = upload_resp

        result = upload_image_from_url(
            "tok_ok", "https://example.com/photo.png", "urn:li:person:1"
        )
        assert result == "urn:li:digitalmediaAsset:img123"

        mock_client.post.assert_called_once()
        mock_client.get.assert_called_once_with(
            "https://example.com/photo.png", follow_redirects=True
        )
        mock_client.put.assert_called_once()

    @patch("app.utils.linkedin_utils.log")
    @patch("app.utils.linkedin_utils._http_client")
    def test_uses_default_content_type_when_missing(
        self, mock_client: MagicMock, _mock_log: MagicMock
    ) -> None:
        """When image response lacks content-type, defaults to image/jpeg."""
        init_resp = MagicMock()
        init_resp.json.return_value = {
            "value": {
                "uploadUrl": "https://linkedin.upload/img",
                "image": "urn:li:digitalmediaAsset:img456",
            }
        }
        init_resp.raise_for_status = MagicMock()

        img_resp = MagicMock()
        img_resp.content = b"\xff\xd8"
        img_resp.headers = {}  # no content-type
        img_resp.raise_for_status = MagicMock()

        upload_resp = MagicMock()
        upload_resp.raise_for_status = MagicMock()

        mock_client.post.return_value = init_resp
        mock_client.get.return_value = img_resp
        mock_client.put.return_value = upload_resp

        result = upload_image_from_url(
            "tok", "https://example.com/photo.jpg", "urn:li:person:1"
        )
        assert result == "urn:li:digitalmediaAsset:img456"

        # Verify default content type used in upload
        put_call_kwargs = mock_client.put.call_args
        assert put_call_kwargs.kwargs["headers"]["Content-Type"] == "image/jpeg"

    @patch("app.utils.linkedin_utils.log")
    @patch("app.utils.linkedin_utils._http_client")
    def test_init_upload_fails_returns_none(
        self, mock_client: MagicMock, _mock_log: MagicMock
    ) -> None:
        """If LinkedIn init-upload returns no uploadUrl, returns None."""
        init_resp = MagicMock()
        init_resp.json.return_value = {"value": {}}
        init_resp.raise_for_status = MagicMock()
        mock_client.post.return_value = init_resp

        result = upload_image_from_url(
            "tok", "https://example.com/photo.png", "urn:li:person:1"
        )
        assert result is None

    @patch("app.utils.linkedin_utils.log")
    @patch("app.utils.linkedin_utils._http_client")
    def test_init_http_error_returns_none(
        self, mock_client: MagicMock, _mock_log: MagicMock
    ) -> None:
        """HTTP error during init-upload is caught, returns None."""
        mock_client.post.side_effect = httpx.HTTPStatusError(
            "403", request=MagicMock(), response=MagicMock()
        )

        result = upload_image_from_url(
            "tok", "https://example.com/photo.png", "urn:li:person:1"
        )
        assert result is None

    @patch("app.utils.linkedin_utils.log")
    @patch("app.utils.linkedin_utils._http_client")
    def test_image_download_fails_returns_none(
        self, mock_client: MagicMock, _mock_log: MagicMock
    ) -> None:
        """If the image URL cannot be downloaded, returns None."""
        init_resp = MagicMock()
        init_resp.json.return_value = {
            "value": {
                "uploadUrl": "https://linkedin.upload/img",
                "image": "urn:li:digitalmediaAsset:img789",
            }
        }
        init_resp.raise_for_status = MagicMock()
        mock_client.post.return_value = init_resp

        mock_client.get.side_effect = httpx.ConnectError("Connection refused")

        result = upload_image_from_url(
            "tok", "https://broken.example.com/photo.png", "urn:li:person:1"
        )
        assert result is None

    @patch("app.utils.linkedin_utils.log")
    @patch("app.utils.linkedin_utils._http_client")
    def test_upload_step_fails_returns_none(
        self, mock_client: MagicMock, _mock_log: MagicMock
    ) -> None:
        """If the PUT upload to LinkedIn fails, returns None."""
        init_resp = MagicMock()
        init_resp.json.return_value = {
            "value": {
                "uploadUrl": "https://linkedin.upload/img",
                "image": "urn:li:digitalmediaAsset:imgX",
            }
        }
        init_resp.raise_for_status = MagicMock()

        img_resp = MagicMock()
        img_resp.content = b"\x89PNG"
        img_resp.headers = {"content-type": "image/png"}
        img_resp.raise_for_status = MagicMock()

        mock_client.post.return_value = init_resp
        mock_client.get.return_value = img_resp
        mock_client.put.side_effect = httpx.HTTPStatusError(
            "500", request=MagicMock(), response=MagicMock()
        )

        result = upload_image_from_url(
            "tok", "https://example.com/photo.png", "urn:li:person:1"
        )
        assert result is None

    @patch("app.utils.linkedin_utils.log")
    @patch("app.utils.linkedin_utils._http_client")
    def test_missing_image_urn_returns_none(
        self, mock_client: MagicMock, _mock_log: MagicMock
    ) -> None:
        """If init response has uploadUrl but no image URN, returns None."""
        init_resp = MagicMock()
        init_resp.json.return_value = {
            "value": {
                "uploadUrl": "https://linkedin.upload/img",
                # "image" key missing
            }
        }
        init_resp.raise_for_status = MagicMock()
        mock_client.post.return_value = init_resp

        result = upload_image_from_url(
            "tok", "https://example.com/photo.png", "urn:li:person:1"
        )
        assert result is None


# ---------------------------------------------------------------------------
# upload_document_from_url
# ---------------------------------------------------------------------------


class TestUploadDocumentFromUrl:
    """Tests for upload_document_from_url — downloads then uploads to LinkedIn."""

    @patch("app.utils.linkedin_utils.log")
    @patch("app.utils.linkedin_utils._http_client")
    def test_success_returns_document_urn(
        self, mock_client: MagicMock, _mock_log: MagicMock
    ) -> None:
        """Happy path: init → download → upload → returns document URN."""
        init_resp = MagicMock()
        init_resp.json.return_value = {
            "value": {
                "uploadUrl": "https://linkedin.upload/doc",
                "document": "urn:li:digitalmediaAsset:doc123",
            }
        }
        init_resp.raise_for_status = MagicMock()

        doc_resp = MagicMock()
        doc_resp.content = b"%PDF-1.4 ..."
        doc_resp.headers = {"content-type": "application/pdf"}
        doc_resp.raise_for_status = MagicMock()

        upload_resp = MagicMock()
        upload_resp.raise_for_status = MagicMock()

        mock_client.post.return_value = init_resp
        mock_client.get.return_value = doc_resp
        mock_client.put.return_value = upload_resp

        result = upload_document_from_url(
            "tok_ok", "https://example.com/doc.pdf", "urn:li:person:1"
        )
        assert result == "urn:li:digitalmediaAsset:doc123"

        mock_client.post.assert_called_once()
        assert LINKEDIN_REST_BASE in mock_client.post.call_args.args[0]
        assert "documents" in mock_client.post.call_args.args[0]

    @patch("app.utils.linkedin_utils.log")
    @patch("app.utils.linkedin_utils._http_client")
    def test_uses_default_content_type_when_missing(
        self, mock_client: MagicMock, _mock_log: MagicMock
    ) -> None:
        """When document response lacks content-type, defaults to application/pdf."""
        init_resp = MagicMock()
        init_resp.json.return_value = {
            "value": {
                "uploadUrl": "https://linkedin.upload/doc",
                "document": "urn:li:digitalmediaAsset:doc456",
            }
        }
        init_resp.raise_for_status = MagicMock()

        doc_resp = MagicMock()
        doc_resp.content = b"%PDF"
        doc_resp.headers = {}  # no content-type
        doc_resp.raise_for_status = MagicMock()

        upload_resp = MagicMock()
        upload_resp.raise_for_status = MagicMock()

        mock_client.post.return_value = init_resp
        mock_client.get.return_value = doc_resp
        mock_client.put.return_value = upload_resp

        result = upload_document_from_url(
            "tok", "https://example.com/doc.pdf", "urn:li:person:1"
        )
        assert result == "urn:li:digitalmediaAsset:doc456"

        put_call_kwargs = mock_client.put.call_args
        assert put_call_kwargs.kwargs["headers"]["Content-Type"] == "application/pdf"

    @patch("app.utils.linkedin_utils.log")
    @patch("app.utils.linkedin_utils._http_client")
    def test_init_upload_fails_returns_none(
        self, mock_client: MagicMock, _mock_log: MagicMock
    ) -> None:
        """If init-upload returns no uploadUrl/document, returns None."""
        init_resp = MagicMock()
        init_resp.json.return_value = {"value": {}}
        init_resp.raise_for_status = MagicMock()
        mock_client.post.return_value = init_resp

        result = upload_document_from_url(
            "tok", "https://example.com/doc.pdf", "urn:li:person:1"
        )
        assert result is None

    @patch("app.utils.linkedin_utils.log")
    @patch("app.utils.linkedin_utils._http_client")
    def test_init_http_error_returns_none(
        self, mock_client: MagicMock, _mock_log: MagicMock
    ) -> None:
        """HTTP error during init is caught, returns None."""
        mock_client.post.side_effect = httpx.HTTPStatusError(
            "403", request=MagicMock(), response=MagicMock()
        )

        result = upload_document_from_url(
            "tok", "https://example.com/doc.pdf", "urn:li:person:1"
        )
        assert result is None

    @patch("app.utils.linkedin_utils.log")
    @patch("app.utils.linkedin_utils._http_client")
    def test_document_download_fails_returns_none(
        self, mock_client: MagicMock, _mock_log: MagicMock
    ) -> None:
        """If the document URL cannot be downloaded, returns None."""
        init_resp = MagicMock()
        init_resp.json.return_value = {
            "value": {
                "uploadUrl": "https://linkedin.upload/doc",
                "document": "urn:li:digitalmediaAsset:doc789",
            }
        }
        init_resp.raise_for_status = MagicMock()
        mock_client.post.return_value = init_resp
        mock_client.get.side_effect = httpx.ConnectError("Connection refused")

        result = upload_document_from_url(
            "tok", "https://broken.example.com/doc.pdf", "urn:li:person:1"
        )
        assert result is None

    @patch("app.utils.linkedin_utils.log")
    @patch("app.utils.linkedin_utils._http_client")
    def test_upload_step_fails_returns_none(
        self, mock_client: MagicMock, _mock_log: MagicMock
    ) -> None:
        """If the PUT upload to LinkedIn fails, returns None."""
        init_resp = MagicMock()
        init_resp.json.return_value = {
            "value": {
                "uploadUrl": "https://linkedin.upload/doc",
                "document": "urn:li:digitalmediaAsset:docX",
            }
        }
        init_resp.raise_for_status = MagicMock()

        doc_resp = MagicMock()
        doc_resp.content = b"%PDF"
        doc_resp.headers = {"content-type": "application/pdf"}
        doc_resp.raise_for_status = MagicMock()

        mock_client.post.return_value = init_resp
        mock_client.get.return_value = doc_resp
        mock_client.put.side_effect = httpx.HTTPStatusError(
            "500", request=MagicMock(), response=MagicMock()
        )

        result = upload_document_from_url(
            "tok", "https://example.com/doc.pdf", "urn:li:person:1"
        )
        assert result is None

    @patch("app.utils.linkedin_utils.log")
    @patch("app.utils.linkedin_utils._http_client")
    def test_missing_document_urn_returns_none(
        self, mock_client: MagicMock, _mock_log: MagicMock
    ) -> None:
        """If init response has uploadUrl but no document URN, returns None."""
        init_resp = MagicMock()
        init_resp.json.return_value = {
            "value": {
                "uploadUrl": "https://linkedin.upload/doc",
                # "document" key missing
            }
        }
        init_resp.raise_for_status = MagicMock()
        mock_client.post.return_value = init_resp

        result = upload_document_from_url(
            "tok", "https://example.com/doc.pdf", "urn:li:person:1"
        )
        assert result is None
