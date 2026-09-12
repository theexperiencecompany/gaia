"""Unit tests for app.utils.linkedin_utils (proxy migration)."""

from unittest.mock import patch

import pytest

from app.utils.linkedin_utils import (
    LINKEDIN_API_BASE,
    LINKEDIN_REST_BASE,
    get_author_urn,
    upload_document_from_url,
    upload_image_from_url,
)

USER_ID = "user_test_123"
PROXY_PATH = "app.utils.linkedin_utils.proxy_request_sync"


@pytest.fixture
def mock_proxy():
    with patch(PROXY_PATH) as proxy:
        proxy.return_value = {}
        yield proxy


class TestGetAuthorUrn:
    def test_uses_organization_when_provided(self, mock_proxy):
        urn = get_author_urn(USER_ID, organization_id="42")
        assert urn == "urn:li:organization:42"
        mock_proxy.assert_not_called()

    def test_returns_existing_urn_unchanged(self, mock_proxy):
        urn = get_author_urn(USER_ID, organization_id="urn:li:organization:99")
        assert urn == "urn:li:organization:99"

    def test_resolves_personal_urn_via_userinfo(self, mock_proxy):
        mock_proxy.return_value = {"sub": "person123"}
        urn = get_author_urn(USER_ID)
        assert urn == "urn:li:person:person123"
        request = mock_proxy.call_args.args[0]
        assert request.endpoint.endswith("/userinfo")

    def test_raises_when_no_sub(self, mock_proxy):
        mock_proxy.return_value = {}
        with pytest.raises(ValueError):
            get_author_urn(USER_ID)


class TestUploadImageFromUrl:
    def test_initializes_then_uploads_via_binary_body(self, mock_proxy):
        mock_proxy.side_effect = [
            {
                "value": {
                    "uploadUrl": "https://upload.example/x",
                    "image": "urn:li:image:abc",
                }
            },
            None,
        ]
        urn = upload_image_from_url(USER_ID, "https://src/img.jpg", "urn:li:person:1")
        assert urn == "urn:li:image:abc"

        init_request = mock_proxy.call_args_list[0].args[0]
        assert init_request.endpoint == (f"{LINKEDIN_REST_BASE}/images?action=initializeUpload")

        upload_request = mock_proxy.call_args_list[1].args[0]
        assert upload_request.endpoint == "https://upload.example/x"
        assert upload_request.method == "PUT"
        assert upload_request.binary_body == {"url": "https://src/img.jpg"}

    def test_returns_none_on_init_failure(self, mock_proxy):
        mock_proxy.return_value = {"value": {}}
        assert upload_image_from_url(USER_ID, "https://src", "urn:li:person:1") is None


class TestUploadDocumentFromUrl:
    def test_uses_documents_endpoint(self, mock_proxy):
        mock_proxy.side_effect = [
            {
                "value": {
                    "uploadUrl": "https://upload.example/d",
                    "document": "urn:li:document:abc",
                }
            },
            None,
        ]
        urn = upload_document_from_url(USER_ID, "https://src/doc.pdf", "urn:li:person:1")
        assert urn == "urn:li:document:abc"
        init_request = mock_proxy.call_args_list[0].args[0]
        assert "documents" in init_request.endpoint


def test_constants_unchanged():
    assert LINKEDIN_API_BASE == "https://api.linkedin.com/v2"
    assert LINKEDIN_REST_BASE == "https://api.linkedin.com/rest"
