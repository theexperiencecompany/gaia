"""Unit tests for app.utils.linkedin_utils (proxy migration)."""

from unittest.mock import call, patch

import pytest

from app.services.composio.proxy_client import ProxyRequest
from app.utils.linkedin_utils import (
    LINKEDIN_API_BASE,
    LINKEDIN_REST_BASE,
    get_author_urn,
    upload_document_from_url,
    upload_image_from_url,
)

USER_ID = "user_test_123"
PROXY_PATH = "app.utils.linkedin_utils.proxy_request_sync"
AUTHOR_URN = "urn:li:person:1"
RESTLI_HEADERS = {
    "Content-Type": "application/json",
    "X-Restli-Protocol-Version": "2.0.0",
    "LinkedIn-Version": "202401",
}


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
        assert mock_proxy.call_args_list == [
            call(
                ProxyRequest(
                    user_id=USER_ID,
                    toolkit="LINKEDIN",
                    endpoint="https://api.linkedin.com/v2/userinfo",
                    method="GET",
                )
            )
        ]

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
        urn = upload_image_from_url(USER_ID, "https://src/img.jpg", AUTHOR_URN)
        assert urn == "urn:li:image:abc"

        assert mock_proxy.call_args_list == [
            call(
                ProxyRequest(
                    user_id=USER_ID,
                    toolkit="LINKEDIN",
                    endpoint="https://api.linkedin.com/rest/images?action=initializeUpload",
                    method="POST",
                    body={"initializeUploadRequest": {"owner": AUTHOR_URN}},
                    headers=RESTLI_HEADERS,
                )
            ),
            call(
                ProxyRequest(
                    user_id=USER_ID,
                    toolkit="LINKEDIN",
                    endpoint="https://upload.example/x",
                    method="PUT",
                    binary_body={"url": "https://src/img.jpg"},
                )
            ),
        ]

    def test_returns_none_on_init_failure(self, mock_proxy):
        mock_proxy.return_value = {"value": {}}
        assert upload_image_from_url(USER_ID, "https://src", AUTHOR_URN) is None
        assert mock_proxy.call_count == 1

    def test_returns_none_when_proxy_raises(self, mock_proxy):
        mock_proxy.side_effect = RuntimeError("boom")
        assert upload_image_from_url(USER_ID, "https://src", AUTHOR_URN) is None


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
        urn = upload_document_from_url(USER_ID, "https://src/doc.pdf", AUTHOR_URN)
        assert urn == "urn:li:document:abc"
        assert mock_proxy.call_args_list == [
            call(
                ProxyRequest(
                    user_id=USER_ID,
                    toolkit="LINKEDIN",
                    endpoint="https://api.linkedin.com/rest/documents?action=initializeUpload",
                    method="POST",
                    body={"initializeUploadRequest": {"owner": AUTHOR_URN}},
                    headers=RESTLI_HEADERS,
                )
            ),
            call(
                ProxyRequest(
                    user_id=USER_ID,
                    toolkit="LINKEDIN",
                    endpoint="https://upload.example/d",
                    method="PUT",
                    binary_body={"url": "https://src/doc.pdf"},
                )
            ),
        ]

    def test_returns_none_on_init_failure(self, mock_proxy):
        mock_proxy.return_value = {"value": {"uploadUrl": "https://upload.example/d"}}
        assert upload_document_from_url(USER_ID, "https://src", AUTHOR_URN) is None
        assert mock_proxy.call_count == 1

    def test_returns_none_when_proxy_raises(self, mock_proxy):
        mock_proxy.side_effect = RuntimeError("boom")
        assert upload_document_from_url(USER_ID, "https://src", AUTHOR_URN) is None


def test_constants_unchanged():
    assert LINKEDIN_API_BASE == "https://api.linkedin.com/v2"
    assert LINKEDIN_REST_BASE == "https://api.linkedin.com/rest"
