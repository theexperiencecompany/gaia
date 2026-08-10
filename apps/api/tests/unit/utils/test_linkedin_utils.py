"""Unit tests for app.utils.linkedin_utils (proxy migration).

The utils wrap LinkedIn REST/v2 calls behind Composio's proxy
(``proxy_request_sync``). These tests mock that single seam and pin the
service's own responsibilities: exact proxy call arguments (endpoint,
method, body, headers, binary_body, toolkit), author-URN resolution rules,
the image/document upload initialize→PUT flow, the best-effort error paths
(never raise out of the uploads; exact wide-event log calls), and the
restli header/literal contracts.
"""

from unittest.mock import call, patch

import pytest

from app.constants.log_tags import LogTag
from app.utils.linkedin_utils import (
    LINKEDIN_API_BASE,
    LINKEDIN_REST_BASE,
    LINKEDIN_TOOLKIT,
    LINKEDIN_VERSION,
    _proxy,
    _restli_headers,
    get_author_urn,
    upload_document_from_url,
    upload_image_from_url,
)

USER_ID = "user_test_123"
PROXY_PATH = "app.utils.linkedin_utils.proxy_request_sync"
LOG_PATH = "app.utils.linkedin_utils.log"

PERSON_URN = "urn:li:person:1"
IMAGE_UPLOAD_URL = "https://upload.example/image-1"
IMAGE_URN = "urn:li:image:abc"
DOC_UPLOAD_URL = "https://upload.example/doc-1"
DOC_URN = "urn:li:document:abc"


@pytest.fixture
def mock_proxy():
    with patch(PROXY_PATH) as proxy:
        proxy.return_value = {}
        yield proxy


# --- _restli_headers: the exact header contract every write call carries ---


def test_restli_headers_exact() -> None:
    assert _restli_headers() == {
        "Content-Type": "application/json",
        "X-Restli-Protocol-Version": "2.0.0",
        "LinkedIn-Version": LINKEDIN_VERSION,
    }


# --- _proxy: every argument passes through to proxy_request_sync verbatim ---


def test_proxy_passes_all_kwargs_through() -> None:
    with patch(PROXY_PATH) as proxy:
        proxy.return_value = {"ok": True}
        result = _proxy(
            USER_ID,
            endpoint="/e",
            method="POST",
            body={"a": 1},
            query={"q": "x"},
            headers={"h": "1"},
            binary_body={"url": "u"},
        )
    assert result == {"ok": True}
    proxy.assert_called_once_with(
        user_id=USER_ID,
        toolkit=LINKEDIN_TOOLKIT,
        endpoint="/e",
        method="POST",
        body={"a": 1},
        query={"q": "x"},
        headers={"h": "1"},
        binary_body={"url": "u"},
    )


def test_proxy_defaults_optional_kwargs_to_none() -> None:
    with patch(PROXY_PATH) as proxy:
        _proxy(USER_ID, endpoint="/e", method="GET")
    proxy.assert_called_once_with(
        user_id=USER_ID,
        toolkit=LINKEDIN_TOOLKIT,
        endpoint="/e",
        method="GET",
        body=None,
        query=None,
        headers=None,
        binary_body=None,
    )


class TestGetAuthorUrn:
    def test_uses_organization_when_provided(self, mock_proxy) -> None:
        with patch(LOG_PATH) as mock_log:
            urn = get_author_urn(USER_ID, organization_id="42")
        assert urn == "urn:li:organization:42"
        mock_proxy.assert_not_called()
        mock_log.set.assert_called_once_with(
            operation="get_author_urn", organization_id="42"
        )

    def test_returns_existing_urn_unchanged(self, mock_proxy) -> None:
        urn = get_author_urn(USER_ID, organization_id="urn:li:organization:99")
        assert urn == "urn:li:organization:99"
        mock_proxy.assert_not_called()

    def test_empty_org_id_falls_through_to_userinfo(self, mock_proxy) -> None:
        mock_proxy.return_value = {"sub": "person123"}
        urn = get_author_urn(USER_ID, organization_id="")
        assert urn == "urn:li:person:person123"

    def test_resolves_personal_urn_via_userinfo_exact_call(self, mock_proxy) -> None:
        mock_proxy.return_value = {"sub": "person123"}
        urn = get_author_urn(USER_ID)
        assert urn == "urn:li:person:person123"
        mock_proxy.assert_called_once_with(
            user_id=USER_ID,
            toolkit=LINKEDIN_TOOLKIT,
            endpoint=f"{LINKEDIN_API_BASE}/userinfo",
            method="GET",
            body=None,
            query=None,
            headers=None,
            binary_body=None,
        )

    def test_raises_when_no_sub(self, mock_proxy) -> None:
        mock_proxy.return_value = {}
        with patch(LOG_PATH) as mock_log:
            with pytest.raises(ValueError, match="^Could not determine author URN$"):
                get_author_urn(USER_ID)
        # A missing sub is a data problem, not a transport failure — no error
        # log, just the raise. This also pins the `or {}` None-response guard.
        mock_log.error.assert_not_called()

    def test_none_proxy_response_raises_without_error_log(self, mock_proxy) -> None:
        # `_proxy(...) or {}` maps a None response to "no sub", not the
        # exception path — the ValueError must fire without a logged error.
        mock_proxy.return_value = None
        with patch(LOG_PATH) as mock_log:
            with pytest.raises(ValueError, match="^Could not determine author URN$"):
                get_author_urn(USER_ID)
        mock_log.error.assert_not_called()

    def test_userinfo_transport_error_logs_exact_and_raises(self, mock_proxy) -> None:
        mock_proxy.side_effect = RuntimeError("linkedin down")
        with patch(LOG_PATH) as mock_log:
            with pytest.raises(ValueError, match="^Could not determine author URN$"):
                get_author_urn(USER_ID)
        mock_log.error.assert_called_once_with(
            f"{LogTag.INTEGRATION} Error getting user info",
            error="linkedin down",
            error_type="RuntimeError",
            user_id=USER_ID,
        )

    def test_userinfo_unparseable_shape_logs_and_raises(self, mock_proxy) -> None:
        mock_proxy.return_value = {"sub": 123}  # int is not a str -> ValidationError
        with patch(LOG_PATH) as mock_log:
            with pytest.raises(ValueError, match="^Could not determine author URN$"):
                get_author_urn(USER_ID)
        message, kwargs = mock_log.error.call_args
        assert message[0] == f"{LogTag.INTEGRATION} Error getting user info"
        assert kwargs["error_type"] == "ValidationError"
        assert kwargs["user_id"] == USER_ID
        assert "sub" in kwargs["error"]


class TestUploadImageFromUrl:
    def test_exact_init_and_upload_call_args(self, mock_proxy) -> None:
        mock_proxy.side_effect = [
            {"value": {"uploadUrl": IMAGE_UPLOAD_URL, "image": IMAGE_URN}},
            None,
        ]
        urn = upload_image_from_url(USER_ID, "https://src/img.jpg", PERSON_URN)
        assert urn == IMAGE_URN
        assert mock_proxy.call_args_list == [
            call(
                user_id=USER_ID,
                toolkit=LINKEDIN_TOOLKIT,
                endpoint=f"{LINKEDIN_REST_BASE}/images?action=initializeUpload",
                method="POST",
                body={"initializeUploadRequest": {"owner": PERSON_URN}},
                query=None,
                headers=_restli_headers(),
                binary_body=None,
            ),
            call(
                user_id=USER_ID,
                toolkit=LINKEDIN_TOOLKIT,
                endpoint=IMAGE_UPLOAD_URL,
                method="PUT",
                body=None,
                query=None,
                headers=None,
                binary_body={"url": "https://src/img.jpg"},
            ),
        ]

    def test_logs_set_with_operation_and_args(self, mock_proxy) -> None:
        mock_proxy.return_value = {"value": {"uploadUrl": "u", "image": IMAGE_URN}}
        with patch(LOG_PATH) as mock_log:
            upload_image_from_url(USER_ID, "https://src/img.jpg", PERSON_URN)
        mock_log.set.assert_called_once_with(
            operation="upload_image", image_url="https://src/img.jpg", author_urn=PERSON_URN
        )

    @pytest.mark.parametrize(
        "init_response",
        [
            {},  # no value block at all
            {"value": None},  # explicit null value
            {"value": {"uploadUrl": IMAGE_UPLOAD_URL}},  # image urn missing
            {"value": {"image": IMAGE_URN}},  # upload url missing
        ],
    )
    def test_incomplete_init_returns_none_logs_and_skips_put(
        self, mock_proxy, init_response: dict
    ) -> None:
        mock_proxy.return_value = init_response
        with patch(LOG_PATH) as mock_log:
            urn = upload_image_from_url(USER_ID, "https://src/img.jpg", PERSON_URN)
        assert urn is None
        mock_log.error.assert_called_once_with(
            f"{LogTag.INTEGRATION} Failed to get upload URL from LinkedIn"
        )
        mock_proxy.assert_called_once()  # initialize only — never a half-target PUT

    def test_init_transport_error_returns_none_logs_exact(self, mock_proxy) -> None:
        mock_proxy.side_effect = RuntimeError("init failed")
        with patch(LOG_PATH) as mock_log:
            urn = upload_image_from_url(USER_ID, "https://src/img.jpg", PERSON_URN)
        assert urn is None
        mock_log.error.assert_called_once_with(
            f"{LogTag.INTEGRATION} Error uploading image",
            error="init failed",
            error_type="RuntimeError",
            user_id=USER_ID,
        )

    def test_put_transport_error_returns_none_logs_exact(self, mock_proxy) -> None:
        mock_proxy.side_effect = [
            {"value": {"uploadUrl": IMAGE_UPLOAD_URL, "image": IMAGE_URN}},
            RuntimeError("put failed"),
        ]
        with patch(LOG_PATH) as mock_log:
            urn = upload_image_from_url(USER_ID, "https://src/img.jpg", PERSON_URN)
        assert urn is None
        mock_log.error.assert_called_once_with(
            f"{LogTag.INTEGRATION} Error uploading image",
            error="put failed",
            error_type="RuntimeError",
            user_id=USER_ID,
        )


class TestUploadDocumentFromUrl:
    def test_exact_init_and_upload_call_args(self, mock_proxy) -> None:
        mock_proxy.side_effect = [
            {"value": {"uploadUrl": DOC_UPLOAD_URL, "document": DOC_URN}},
            None,
        ]
        urn = upload_document_from_url(USER_ID, "https://src/doc.pdf", PERSON_URN)
        assert urn == DOC_URN
        assert mock_proxy.call_args_list == [
            call(
                user_id=USER_ID,
                toolkit=LINKEDIN_TOOLKIT,
                endpoint=f"{LINKEDIN_REST_BASE}/documents?action=initializeUpload",
                method="POST",
                body={"initializeUploadRequest": {"owner": PERSON_URN}},
                query=None,
                headers=_restli_headers(),
                binary_body=None,
            ),
            call(
                user_id=USER_ID,
                toolkit=LINKEDIN_TOOLKIT,
                endpoint=DOC_UPLOAD_URL,
                method="PUT",
                body=None,
                query=None,
                headers=None,
                binary_body={"url": "https://src/doc.pdf"},
            ),
        ]

    def test_logs_set_with_operation_and_args(self, mock_proxy) -> None:
        mock_proxy.return_value = {"value": {"uploadUrl": "u", "document": DOC_URN}}
        with patch(LOG_PATH) as mock_log:
            upload_document_from_url(USER_ID, "https://src/doc.pdf", PERSON_URN)
        mock_log.set.assert_called_once_with(
            operation="upload_document",
            document_url="https://src/doc.pdf",
            author_urn=PERSON_URN,
        )

    @pytest.mark.parametrize(
        "init_response",
        [
            {},  # no value block at all
            {"value": None},  # explicit null value
            {"value": {"uploadUrl": DOC_UPLOAD_URL}},  # document urn missing
            {"value": {"document": DOC_URN}},  # upload url missing
        ],
    )
    def test_incomplete_init_returns_none_logs_and_skips_put(
        self, mock_proxy, init_response: dict
    ) -> None:
        mock_proxy.return_value = init_response
        with patch(LOG_PATH) as mock_log:
            urn = upload_document_from_url(USER_ID, "https://src/doc.pdf", PERSON_URN)
        assert urn is None
        mock_log.error.assert_called_once_with(
            f"{LogTag.INTEGRATION} Failed to get upload URL from LinkedIn"
        )
        mock_proxy.assert_called_once()  # initialize only — never a half-target PUT

    def test_init_transport_error_returns_none_logs_exact(self, mock_proxy) -> None:
        mock_proxy.side_effect = RuntimeError("init failed")
        with patch(LOG_PATH) as mock_log:
            urn = upload_document_from_url(USER_ID, "https://src/doc.pdf", PERSON_URN)
        assert urn is None
        mock_log.error.assert_called_once_with(
            f"{LogTag.INTEGRATION} Error uploading document",
            error="init failed",
            error_type="RuntimeError",
            user_id=USER_ID,
        )

    def test_put_transport_error_returns_none_logs_exact(self, mock_proxy) -> None:
        mock_proxy.side_effect = [
            {"value": {"uploadUrl": DOC_UPLOAD_URL, "document": DOC_URN}},
            RuntimeError("put failed"),
        ]
        with patch(LOG_PATH) as mock_log:
            urn = upload_document_from_url(USER_ID, "https://src/doc.pdf", PERSON_URN)
        assert urn is None
        mock_log.error.assert_called_once_with(
            f"{LogTag.INTEGRATION} Error uploading document",
            error="put failed",
            error_type="RuntimeError",
            user_id=USER_ID,
        )


def test_constants_unchanged() -> None:
    assert LINKEDIN_API_BASE == "https://api.linkedin.com/v2"
    assert LINKEDIN_REST_BASE == "https://api.linkedin.com/rest"
