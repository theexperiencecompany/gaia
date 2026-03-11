"""Tests for Gmail custom tools (gmail_tools.py).

These tests call the actual tool functions directly and mock only the
outbound HTTP / Google API calls.  If gmail_tools.py is deleted or its
behaviour changes, these tests will fail.

Run with:
    uv run pytest tests/composio/ -m composio
"""

from typing import Any, Dict
from unittest.mock import MagicMock, patch

import httpx
import pytest

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

GMAIL_BATCH_MODIFY_URL = (
    "https://gmail.googleapis.com/gmail/v1/users/me/messages/batchModify"
)
GMAIL_LABELS_BASE = "https://gmail.googleapis.com/gmail/v1/users/me/labels"


def _make_response(status_code: int = 200, json_body: dict | None = None) -> MagicMock:
    """Build a mock httpx.Response."""
    resp = MagicMock(spec=httpx.Response)
    resp.status_code = status_code
    resp.json.return_value = json_body or {}
    if status_code >= 400:
        resp.raise_for_status.side_effect = httpx.HTTPStatusError(
            message=f"HTTP {status_code}",
            request=MagicMock(),
            response=resp,
        )
    else:
        resp.raise_for_status.return_value = None
    return resp


# ---------------------------------------------------------------------------
# Fixture: register tools once per test via the mock Composio client
# ---------------------------------------------------------------------------


@pytest.fixture
def gmail_tools(mock_composio_client):
    """
    Call register_gmail_custom_tools() with the mock client and return the
    dict of captured tool functions keyed by their uppercase name.
    """
    from app.services.composio.custom_tools.gmail_tools import (
        register_gmail_custom_tools,
    )

    register_gmail_custom_tools(mock_composio_client)
    return mock_composio_client._registered_tools


# ---------------------------------------------------------------------------
# _auth_headers unit tests
# ---------------------------------------------------------------------------


@pytest.mark.composio
class TestAuthHeaders:
    """Unit tests for the _auth_headers helper."""

    def test_returns_bearer_header_when_token_present(self):
        from app.services.composio.custom_tools.gmail_tools import _auth_headers

        headers = _auth_headers({"access_token": "my_token"})
        assert headers == {"Authorization": "Bearer my_token"}

    def test_raises_when_token_missing(self):
        from app.services.composio.custom_tools.gmail_tools import _auth_headers

        with pytest.raises(ValueError, match="Missing access_token"):
            _auth_headers({})

    def test_raises_when_token_is_none(self):
        from app.services.composio.custom_tools.gmail_tools import _auth_headers

        with pytest.raises(ValueError, match="Missing access_token"):
            _auth_headers({"access_token": None})


# ---------------------------------------------------------------------------
# MARK_AS_READ tests
# ---------------------------------------------------------------------------


@pytest.mark.composio
class TestMarkAsRead:
    """Tests for the MARK_AS_READ tool."""

    def test_mark_as_read_success(
        self, gmail_tools, mock_gmail_credentials, mock_http_client
    ):
        tool = gmail_tools["MARK_AS_READ"]
        mock_http_client.post.return_value = _make_response(200)

        from app.services.composio.custom_tools.gmail_tools import MarkAsReadInput

        request = MarkAsReadInput(message_ids=["msg_001", "msg_002"])

        with patch(
            "app.services.composio.custom_tools.gmail_tools._http_client",
            mock_http_client,
        ):
            result = tool(
                request=request,
                execute_request=None,
                auth_credentials=mock_gmail_credentials,
            )

        # Tool returns an empty dict on success
        assert result == {}

        # Verify the correct URL and payload were used
        mock_http_client.post.assert_called_once_with(
            GMAIL_BATCH_MODIFY_URL,
            json={"ids": ["msg_001", "msg_002"], "removeLabelIds": ["UNREAD"]},
            headers={"Authorization": "Bearer test_access_token_abc123"},
        )

    def test_mark_as_read_http_error_raises(
        self, gmail_tools, mock_gmail_credentials, mock_http_client
    ):
        tool = gmail_tools["MARK_AS_READ"]
        mock_http_client.post.return_value = _make_response(401)

        from app.services.composio.custom_tools.gmail_tools import MarkAsReadInput

        request = MarkAsReadInput(message_ids=["msg_001"])

        with patch(
            "app.services.composio.custom_tools.gmail_tools._http_client",
            mock_http_client,
        ):
            with pytest.raises(httpx.HTTPStatusError):
                tool(
                    request=request,
                    execute_request=None,
                    auth_credentials=mock_gmail_credentials,
                )

    def test_mark_as_read_missing_token_raises(
        self, gmail_tools, mock_gmail_credentials_no_token
    ):
        tool = gmail_tools["MARK_AS_READ"]
        from app.services.composio.custom_tools.gmail_tools import MarkAsReadInput

        request = MarkAsReadInput(message_ids=["msg_001"])

        with pytest.raises(ValueError, match="Missing access_token"):
            tool(
                request=request,
                execute_request=None,
                auth_credentials=mock_gmail_credentials_no_token,
            )

    def test_mark_as_read_single_message(
        self, gmail_tools, mock_gmail_credentials, mock_http_client
    ):
        tool = gmail_tools["MARK_AS_READ"]
        mock_http_client.post.return_value = _make_response(200)

        from app.services.composio.custom_tools.gmail_tools import MarkAsReadInput

        request = MarkAsReadInput(message_ids=["single_msg"])

        with patch(
            "app.services.composio.custom_tools.gmail_tools._http_client",
            mock_http_client,
        ):
            result = tool(
                request=request,
                execute_request=None,
                auth_credentials=mock_gmail_credentials,
            )

        assert result == {}
        call_kwargs = mock_http_client.post.call_args
        assert call_kwargs.kwargs["json"]["ids"] == ["single_msg"]
        assert "UNREAD" in call_kwargs.kwargs["json"]["removeLabelIds"]

    def test_mark_as_read_403_raises(
        self, gmail_tools, mock_gmail_credentials, mock_http_client
    ):
        """403 Forbidden from Gmail API must propagate as HTTPStatusError."""
        tool = gmail_tools["MARK_AS_READ"]
        mock_http_client.post.return_value = _make_response(403)

        from app.services.composio.custom_tools.gmail_tools import MarkAsReadInput

        with patch(
            "app.services.composio.custom_tools.gmail_tools._http_client",
            mock_http_client,
        ):
            with pytest.raises(httpx.HTTPStatusError):
                tool(
                    request=MarkAsReadInput(message_ids=["msg_001"]),
                    execute_request=None,
                    auth_credentials=mock_gmail_credentials,
                )

    def test_mark_as_read_429_rate_limit_raises(
        self, gmail_tools, mock_gmail_credentials, mock_http_client
    ):
        """429 Too Many Requests from Gmail API must propagate as HTTPStatusError."""
        tool = gmail_tools["MARK_AS_READ"]
        mock_http_client.post.return_value = _make_response(429)

        from app.services.composio.custom_tools.gmail_tools import MarkAsReadInput

        with patch(
            "app.services.composio.custom_tools.gmail_tools._http_client",
            mock_http_client,
        ):
            with pytest.raises(httpx.HTTPStatusError):
                tool(
                    request=MarkAsReadInput(message_ids=["msg_001"]),
                    execute_request=None,
                    auth_credentials=mock_gmail_credentials,
                )


# ---------------------------------------------------------------------------
# MARK_AS_UNREAD tests
# ---------------------------------------------------------------------------


@pytest.mark.composio
class TestMarkAsUnread:
    """Tests for the MARK_AS_UNREAD tool."""

    def test_mark_as_unread_success(
        self, gmail_tools, mock_gmail_credentials, mock_http_client
    ):
        tool = gmail_tools["MARK_AS_UNREAD"]
        mock_http_client.post.return_value = _make_response(200)

        from app.services.composio.custom_tools.gmail_tools import MarkAsUnreadInput

        request = MarkAsUnreadInput(message_ids=["msg_001"])

        with patch(
            "app.services.composio.custom_tools.gmail_tools._http_client",
            mock_http_client,
        ):
            result = tool(
                request=request,
                execute_request=None,
                auth_credentials=mock_gmail_credentials,
            )

        assert result == {}

        mock_http_client.post.assert_called_once_with(
            GMAIL_BATCH_MODIFY_URL,
            json={"ids": ["msg_001"], "addLabelIds": ["UNREAD"]},
            headers={"Authorization": "Bearer test_access_token_abc123"},
        )

    def test_mark_as_unread_uses_add_label_not_remove(
        self, gmail_tools, mock_gmail_credentials, mock_http_client
    ):
        """UNREAD is added (not removed) to make messages appear unread."""
        tool = gmail_tools["MARK_AS_UNREAD"]
        mock_http_client.post.return_value = _make_response(200)

        from app.services.composio.custom_tools.gmail_tools import MarkAsUnreadInput

        with patch(
            "app.services.composio.custom_tools.gmail_tools._http_client",
            mock_http_client,
        ):
            tool(
                request=MarkAsUnreadInput(message_ids=["msg_x"]),
                execute_request=None,
                auth_credentials=mock_gmail_credentials,
            )

        payload = mock_http_client.post.call_args.kwargs["json"]
        assert "addLabelIds" in payload
        assert "removeLabelIds" not in payload
        assert "UNREAD" in payload["addLabelIds"]

    def test_mark_as_unread_server_error_raises(
        self, gmail_tools, mock_gmail_credentials, mock_http_client
    ):
        tool = gmail_tools["MARK_AS_UNREAD"]
        mock_http_client.post.return_value = _make_response(500)

        from app.services.composio.custom_tools.gmail_tools import MarkAsUnreadInput

        with patch(
            "app.services.composio.custom_tools.gmail_tools._http_client",
            mock_http_client,
        ):
            with pytest.raises(httpx.HTTPStatusError):
                tool(
                    request=MarkAsUnreadInput(message_ids=["msg_001"]),
                    execute_request=None,
                    auth_credentials=mock_gmail_credentials,
                )


# ---------------------------------------------------------------------------
# ARCHIVE_EMAIL tests
# ---------------------------------------------------------------------------


@pytest.mark.composio
class TestArchiveEmail:
    """Tests for the ARCHIVE_EMAIL tool."""

    def test_archive_success(
        self, gmail_tools, mock_gmail_credentials, mock_http_client
    ):
        tool = gmail_tools["ARCHIVE_EMAIL"]
        mock_http_client.post.return_value = _make_response(200)

        from app.services.composio.custom_tools.gmail_tools import ArchiveEmailInput

        request = ArchiveEmailInput(message_ids=["msg_inbox_1", "msg_inbox_2"])

        with patch(
            "app.services.composio.custom_tools.gmail_tools._http_client",
            mock_http_client,
        ):
            result = tool(
                request=request,
                execute_request=None,
                auth_credentials=mock_gmail_credentials,
            )

        assert result == {}

        mock_http_client.post.assert_called_once_with(
            GMAIL_BATCH_MODIFY_URL,
            json={
                "ids": ["msg_inbox_1", "msg_inbox_2"],
                "removeLabelIds": ["INBOX"],
            },
            headers={"Authorization": "Bearer test_access_token_abc123"},
        )

    def test_archive_removes_inbox_not_unread(
        self, gmail_tools, mock_gmail_credentials, mock_http_client
    ):
        """Archiving should remove INBOX label, not UNREAD."""
        tool = gmail_tools["ARCHIVE_EMAIL"]
        mock_http_client.post.return_value = _make_response(200)

        from app.services.composio.custom_tools.gmail_tools import ArchiveEmailInput

        with patch(
            "app.services.composio.custom_tools.gmail_tools._http_client",
            mock_http_client,
        ):
            tool(
                request=ArchiveEmailInput(message_ids=["m1"]),
                execute_request=None,
                auth_credentials=mock_gmail_credentials,
            )

        payload = mock_http_client.post.call_args.kwargs["json"]
        assert payload["removeLabelIds"] == ["INBOX"]

    def test_archive_404_raises(
        self, gmail_tools, mock_gmail_credentials, mock_http_client
    ):
        tool = gmail_tools["ARCHIVE_EMAIL"]
        mock_http_client.post.return_value = _make_response(404)

        from app.services.composio.custom_tools.gmail_tools import ArchiveEmailInput

        with patch(
            "app.services.composio.custom_tools.gmail_tools._http_client",
            mock_http_client,
        ):
            with pytest.raises(httpx.HTTPStatusError):
                tool(
                    request=ArchiveEmailInput(message_ids=["missing_msg"]),
                    execute_request=None,
                    auth_credentials=mock_gmail_credentials,
                )

    def test_archive_401_raises(
        self, gmail_tools, mock_gmail_credentials, mock_http_client
    ):
        """401 Unauthorized must propagate as HTTPStatusError."""
        tool = gmail_tools["ARCHIVE_EMAIL"]
        mock_http_client.post.return_value = _make_response(401)

        from app.services.composio.custom_tools.gmail_tools import ArchiveEmailInput

        with patch(
            "app.services.composio.custom_tools.gmail_tools._http_client",
            mock_http_client,
        ):
            with pytest.raises(httpx.HTTPStatusError):
                tool(
                    request=ArchiveEmailInput(message_ids=["msg_001"]),
                    execute_request=None,
                    auth_credentials=mock_gmail_credentials,
                )

    def test_archive_403_raises(
        self, gmail_tools, mock_gmail_credentials, mock_http_client
    ):
        """403 Forbidden must propagate as HTTPStatusError."""
        tool = gmail_tools["ARCHIVE_EMAIL"]
        mock_http_client.post.return_value = _make_response(403)

        from app.services.composio.custom_tools.gmail_tools import ArchiveEmailInput

        with patch(
            "app.services.composio.custom_tools.gmail_tools._http_client",
            mock_http_client,
        ):
            with pytest.raises(httpx.HTTPStatusError):
                tool(
                    request=ArchiveEmailInput(message_ids=["msg_001"]),
                    execute_request=None,
                    auth_credentials=mock_gmail_credentials,
                )

    def test_archive_429_rate_limit_raises(
        self, gmail_tools, mock_gmail_credentials, mock_http_client
    ):
        """429 Too Many Requests must propagate as HTTPStatusError."""
        tool = gmail_tools["ARCHIVE_EMAIL"]
        mock_http_client.post.return_value = _make_response(429)

        from app.services.composio.custom_tools.gmail_tools import ArchiveEmailInput

        with patch(
            "app.services.composio.custom_tools.gmail_tools._http_client",
            mock_http_client,
        ):
            with pytest.raises(httpx.HTTPStatusError):
                tool(
                    request=ArchiveEmailInput(message_ids=["msg_001"]),
                    execute_request=None,
                    auth_credentials=mock_gmail_credentials,
                )

    def test_archive_missing_token_raises(
        self, gmail_tools, mock_gmail_credentials_no_token
    ):
        tool = gmail_tools["ARCHIVE_EMAIL"]
        from app.services.composio.custom_tools.gmail_tools import ArchiveEmailInput

        with pytest.raises(ValueError, match="Missing access_token"):
            tool(
                request=ArchiveEmailInput(message_ids=["msg_001"]),
                execute_request=None,
                auth_credentials=mock_gmail_credentials_no_token,
            )


# ---------------------------------------------------------------------------
# STAR_EMAIL tests
# ---------------------------------------------------------------------------


@pytest.mark.composio
class TestStarEmail:
    """Tests for the STAR_EMAIL tool."""

    def test_star_adds_starred_label(
        self, gmail_tools, mock_gmail_credentials, mock_http_client
    ):
        tool = gmail_tools["STAR_EMAIL"]
        mock_http_client.post.return_value = _make_response(200)

        from app.services.composio.custom_tools.gmail_tools import StarEmailInput

        request = StarEmailInput(message_ids=["msg_a"], unstar=False)

        with patch(
            "app.services.composio.custom_tools.gmail_tools._http_client",
            mock_http_client,
        ):
            result = tool(
                request=request,
                execute_request=None,
                auth_credentials=mock_gmail_credentials,
            )

        assert result == {"action": "starred"}
        payload = mock_http_client.post.call_args.kwargs["json"]
        assert payload["addLabelIds"] == ["STARRED"]
        assert "removeLabelIds" not in payload

    def test_unstar_removes_starred_label(
        self, gmail_tools, mock_gmail_credentials, mock_http_client
    ):
        tool = gmail_tools["STAR_EMAIL"]
        mock_http_client.post.return_value = _make_response(200)

        from app.services.composio.custom_tools.gmail_tools import StarEmailInput

        request = StarEmailInput(message_ids=["msg_a"], unstar=True)

        with patch(
            "app.services.composio.custom_tools.gmail_tools._http_client",
            mock_http_client,
        ):
            result = tool(
                request=request,
                execute_request=None,
                auth_credentials=mock_gmail_credentials,
            )

        assert result == {"action": "unstarred"}
        payload = mock_http_client.post.call_args.kwargs["json"]
        assert payload["removeLabelIds"] == ["STARRED"]
        assert "addLabelIds" not in payload

    def test_star_default_is_star_not_unstar(
        self, gmail_tools, mock_gmail_credentials, mock_http_client
    ):
        """Omitting unstar should default to starring (unstar=False)."""
        tool = gmail_tools["STAR_EMAIL"]
        mock_http_client.post.return_value = _make_response(200)

        from app.services.composio.custom_tools.gmail_tools import StarEmailInput

        request = StarEmailInput(message_ids=["msg_b"])

        with patch(
            "app.services.composio.custom_tools.gmail_tools._http_client",
            mock_http_client,
        ):
            result = tool(
                request=request,
                execute_request=None,
                auth_credentials=mock_gmail_credentials,
            )

        assert result["action"] == "starred"

    def test_star_http_error_raises(
        self, gmail_tools, mock_gmail_credentials, mock_http_client
    ):
        tool = gmail_tools["STAR_EMAIL"]
        mock_http_client.post.return_value = _make_response(403)

        from app.services.composio.custom_tools.gmail_tools import StarEmailInput

        with patch(
            "app.services.composio.custom_tools.gmail_tools._http_client",
            mock_http_client,
        ):
            with pytest.raises(httpx.HTTPStatusError):
                tool(
                    request=StarEmailInput(message_ids=["msg_x"]),
                    execute_request=None,
                    auth_credentials=mock_gmail_credentials,
                )

    def test_star_multiple_messages(
        self, gmail_tools, mock_gmail_credentials, mock_http_client
    ):
        tool = gmail_tools["STAR_EMAIL"]
        mock_http_client.post.return_value = _make_response(200)

        from app.services.composio.custom_tools.gmail_tools import StarEmailInput

        ids = ["msg_1", "msg_2", "msg_3"]
        with patch(
            "app.services.composio.custom_tools.gmail_tools._http_client",
            mock_http_client,
        ):
            result = tool(
                request=StarEmailInput(message_ids=ids),
                execute_request=None,
                auth_credentials=mock_gmail_credentials,
            )

        assert result["action"] == "starred"
        payload = mock_http_client.post.call_args.kwargs["json"]
        assert payload["ids"] == ids

    def test_star_401_raises(
        self, gmail_tools, mock_gmail_credentials, mock_http_client
    ):
        """401 Unauthorized must propagate as HTTPStatusError."""
        tool = gmail_tools["STAR_EMAIL"]
        mock_http_client.post.return_value = _make_response(401)

        from app.services.composio.custom_tools.gmail_tools import StarEmailInput

        with patch(
            "app.services.composio.custom_tools.gmail_tools._http_client",
            mock_http_client,
        ):
            with pytest.raises(httpx.HTTPStatusError):
                tool(
                    request=StarEmailInput(message_ids=["msg_001"]),
                    execute_request=None,
                    auth_credentials=mock_gmail_credentials,
                )

    def test_star_429_rate_limit_raises(
        self, gmail_tools, mock_gmail_credentials, mock_http_client
    ):
        """429 Too Many Requests must propagate as HTTPStatusError."""
        tool = gmail_tools["STAR_EMAIL"]
        mock_http_client.post.return_value = _make_response(429)

        from app.services.composio.custom_tools.gmail_tools import StarEmailInput

        with patch(
            "app.services.composio.custom_tools.gmail_tools._http_client",
            mock_http_client,
        ):
            with pytest.raises(httpx.HTTPStatusError):
                tool(
                    request=StarEmailInput(message_ids=["msg_001"]),
                    execute_request=None,
                    auth_credentials=mock_gmail_credentials,
                )


# ---------------------------------------------------------------------------
# GET_UNREAD_COUNT tests
# ---------------------------------------------------------------------------
# The GET_UNREAD_COUNT tool accepts GetUnreadCountInput with:
#   - label_ids: Optional[List[str]]  (defaults to ["INBOX"] when no query)
#   - query: Optional[str]
#   - include_spam_trash: bool (default False)
#
# Label mode (no query): GETs /users/me/labels/{label_id} for each label.
#   unreadCount comes from data.get("messagesUnread", 0) — returns 0, not None,
#   when the field is absent.
# Query mode: GETs /users/me/messages with q= params, uses resultSizeEstimate.


@pytest.mark.composio
class TestGetUnreadCount:
    """Tests for the GET_UNREAD_COUNT tool."""

    def test_get_unread_count_inbox(
        self, gmail_tools, mock_gmail_credentials, mock_http_client
    ):
        """Single-label mode returns label_id, unreadCount, totalCount at top level."""
        tool = gmail_tools["GET_UNREAD_COUNT"]
        api_response = {
            "id": "INBOX",
            "name": "INBOX",
            "messagesUnread": 42,
            "messagesTotal": 100,
        }
        mock_http_client.get.return_value = _make_response(200, api_response)

        from app.services.composio.custom_tools.gmail_tools import GetUnreadCountInput

        # label_ids is a list; no label_ids + no query defaults to ["INBOX"]
        request = GetUnreadCountInput()

        with patch(
            "app.services.composio.custom_tools.gmail_tools._http_client",
            mock_http_client,
        ):
            result = tool(
                request=request,
                execute_request=None,
                auth_credentials=mock_gmail_credentials,
            )

        assert result["unreadCount"] == 42
        assert result["label_id"] == "INBOX"

    def test_get_unread_count_custom_label(
        self, gmail_tools, mock_gmail_credentials, mock_http_client
    ):
        """A custom label ID is passed through correctly."""
        tool = gmail_tools["GET_UNREAD_COUNT"]
        api_response = {
            "id": "Label_123",
            "name": "Work",
            "messagesUnread": 7,
        }
        mock_http_client.get.return_value = _make_response(200, api_response)

        from app.services.composio.custom_tools.gmail_tools import GetUnreadCountInput

        request = GetUnreadCountInput(label_ids=["Label_123"])

        with patch(
            "app.services.composio.custom_tools.gmail_tools._http_client",
            mock_http_client,
        ):
            result = tool(
                request=request,
                execute_request=None,
                auth_credentials=mock_gmail_credentials,
            )

        assert result["unreadCount"] == 7
        assert result["label_id"] == "Label_123"

        # The URL should contain the label ID
        call_url = mock_http_client.get.call_args.args[0]
        assert "Label_123" in call_url

    def test_get_unread_count_zero(
        self, gmail_tools, mock_gmail_credentials, mock_http_client
    ):
        """When messagesUnread is explicitly 0, unreadCount must be 0."""
        tool = gmail_tools["GET_UNREAD_COUNT"]
        api_response = {"id": "INBOX", "name": "INBOX", "messagesUnread": 0}
        mock_http_client.get.return_value = _make_response(200, api_response)

        from app.services.composio.custom_tools.gmail_tools import GetUnreadCountInput

        with patch(
            "app.services.composio.custom_tools.gmail_tools._http_client",
            mock_http_client,
        ):
            result = tool(
                request=GetUnreadCountInput(),
                execute_request=None,
                auth_credentials=mock_gmail_credentials,
            )

        assert result["unreadCount"] == 0

    def test_get_unread_count_missing_field_returns_zero(
        self, gmail_tools, mock_gmail_credentials, mock_http_client
    ):
        """If messagesUnread is absent the default is 0 (not None).

        The production code uses data.get("messagesUnread", 0).
        Changing that default to None would break this test — ensuring
        the sentinel value stays correct.
        """
        tool = gmail_tools["GET_UNREAD_COUNT"]
        # API response contains no messagesUnread field
        mock_http_client.get.return_value = _make_response(200, {"id": "INBOX", "name": "INBOX"})

        from app.services.composio.custom_tools.gmail_tools import GetUnreadCountInput

        with patch(
            "app.services.composio.custom_tools.gmail_tools._http_client",
            mock_http_client,
        ):
            result = tool(
                request=GetUnreadCountInput(),
                execute_request=None,
                auth_credentials=mock_gmail_credentials,
            )

        # data.get("messagesUnread", 0) returns 0, not None
        assert result["unreadCount"] == 0
        assert result["unreadCount"] is not None

    def test_get_unread_count_401_raises(
        self, gmail_tools, mock_gmail_credentials, mock_http_client
    ):
        """401 Unauthorized from Gmail API must propagate as HTTPStatusError."""
        tool = gmail_tools["GET_UNREAD_COUNT"]
        mock_http_client.get.return_value = _make_response(401)

        from app.services.composio.custom_tools.gmail_tools import GetUnreadCountInput

        with patch(
            "app.services.composio.custom_tools.gmail_tools._http_client",
            mock_http_client,
        ):
            with pytest.raises(httpx.HTTPStatusError):
                tool(
                    request=GetUnreadCountInput(),
                    execute_request=None,
                    auth_credentials=mock_gmail_credentials,
                )

    def test_get_unread_count_403_raises(
        self, gmail_tools, mock_gmail_credentials, mock_http_client
    ):
        """403 Forbidden from Gmail API must propagate as HTTPStatusError."""
        tool = gmail_tools["GET_UNREAD_COUNT"]
        mock_http_client.get.return_value = _make_response(403)

        from app.services.composio.custom_tools.gmail_tools import GetUnreadCountInput

        with patch(
            "app.services.composio.custom_tools.gmail_tools._http_client",
            mock_http_client,
        ):
            with pytest.raises(httpx.HTTPStatusError):
                tool(
                    request=GetUnreadCountInput(),
                    execute_request=None,
                    auth_credentials=mock_gmail_credentials,
                )

    def test_get_unread_count_429_rate_limit_raises(
        self, gmail_tools, mock_gmail_credentials, mock_http_client
    ):
        """429 Too Many Requests must propagate as HTTPStatusError."""
        tool = gmail_tools["GET_UNREAD_COUNT"]
        mock_http_client.get.return_value = _make_response(429)

        from app.services.composio.custom_tools.gmail_tools import GetUnreadCountInput

        with patch(
            "app.services.composio.custom_tools.gmail_tools._http_client",
            mock_http_client,
        ):
            with pytest.raises(httpx.HTTPStatusError):
                tool(
                    request=GetUnreadCountInput(),
                    execute_request=None,
                    auth_credentials=mock_gmail_credentials,
                )

    def test_get_unread_count_default_label_is_inbox(
        self, gmail_tools, mock_gmail_credentials, mock_http_client
    ):
        """Omitting label_ids (and query) should default to INBOX."""
        tool = gmail_tools["GET_UNREAD_COUNT"]
        mock_http_client.get.return_value = _make_response(
            200, {"id": "INBOX", "name": "INBOX", "messagesUnread": 5}
        )

        from app.services.composio.custom_tools.gmail_tools import GetUnreadCountInput

        # No label_ids, no query → defaults to INBOX
        request = GetUnreadCountInput()

        with patch(
            "app.services.composio.custom_tools.gmail_tools._http_client",
            mock_http_client,
        ):
            result = tool(
                request=request,
                execute_request=None,
                auth_credentials=mock_gmail_credentials,
            )

        assert result["label_id"] == "INBOX"
        url_called = mock_http_client.get.call_args.args[0]
        assert url_called.endswith("/INBOX")

    def test_get_unread_count_query_mode(
        self, gmail_tools, mock_gmail_credentials, mock_http_client
    ):
        """Query mode calls the messages list endpoint with q= param."""
        tool = gmail_tools["GET_UNREAD_COUNT"]
        # query mode calls _http_client.get twice (total + unread query)
        messages_response = {"resultSizeEstimate": 10, "messages": []}
        mock_http_client.get.return_value = _make_response(200, messages_response)

        from app.services.composio.custom_tools.gmail_tools import GetUnreadCountInput

        request = GetUnreadCountInput(query="from:boss@example.com")

        with patch(
            "app.services.composio.custom_tools.gmail_tools._http_client",
            mock_http_client,
        ):
            result = tool(
                request=request,
                execute_request=None,
                auth_credentials=mock_gmail_credentials,
            )

        assert result["query"] == "from:boss@example.com"
        assert "unreadCount" in result
        assert "totalCount" in result
        assert result["is_estimate"] is True
        # Two GET calls: one for total, one for unread
        assert mock_http_client.get.call_count == 2

    def test_get_unread_count_multiple_labels(
        self, gmail_tools, mock_gmail_credentials, mock_http_client
    ):
        """Multiple label_ids return counts dict without top-level label_id."""
        tool = gmail_tools["GET_UNREAD_COUNT"]

        def _side_effect(url, **kwargs):
            if url.endswith("/INBOX"):
                return _make_response(
                    200, {"id": "INBOX", "name": "INBOX", "messagesUnread": 3, "messagesTotal": 50}
                )
            if url.endswith("/STARRED"):
                return _make_response(
                    200, {"id": "STARRED", "name": "Starred", "messagesUnread": 1, "messagesTotal": 5}
                )
            return _make_response(200, {})

        mock_http_client.get.side_effect = _side_effect

        from app.services.composio.custom_tools.gmail_tools import GetUnreadCountInput

        request = GetUnreadCountInput(label_ids=["INBOX", "STARRED"])

        with patch(
            "app.services.composio.custom_tools.gmail_tools._http_client",
            mock_http_client,
        ):
            result = tool(
                request=request,
                execute_request=None,
                auth_credentials=mock_gmail_credentials,
            )

        assert "counts" in result
        assert "INBOX" in result["counts"]
        assert "STARRED" in result["counts"]
        assert result["counts"]["INBOX"]["unreadCount"] == 3
        assert result["counts"]["STARRED"]["unreadCount"] == 1
        # Multi-label result does not have top-level label_id
        assert "label_id" not in result


# ---------------------------------------------------------------------------
# GET_CONTACT_LIST tests
# ---------------------------------------------------------------------------


@pytest.mark.composio
class TestGetContactList:
    """Tests for the GET_CONTACT_LIST tool."""

    def test_get_contacts_returns_contact_list(
        self, gmail_tools, mock_gmail_credentials
    ):
        tool = gmail_tools["GET_CONTACT_LIST"]

        fake_contacts_result = {
            "success": True,
            "contacts": [
                {"name": "Alice Smith", "email": "alice@example.com"},
                {"name": "Bob Jones", "email": "bob@example.com"},
            ],
            "count": 2,
        }

        from app.services.composio.custom_tools.gmail_tools import GetContactListInput

        request = GetContactListInput(query="alice", max_results=30)

        with (
            patch(
                "app.services.composio.custom_tools.gmail_tools.Credentials"
            ) as MockCreds,
            patch(
                "app.services.composio.custom_tools.gmail_tools.build"
            ) as mock_build,
            patch(
                "app.services.composio.custom_tools.gmail_tools.get_gmail_contacts",
                return_value=fake_contacts_result,
            ) as mock_get_contacts,
        ):
            mock_service = MagicMock()
            mock_build.return_value = mock_service

            result = tool(
                request=request,
                execute_request=None,
                auth_credentials=mock_gmail_credentials,
            )

        assert result["success"] is True
        assert len(result["contacts"]) == 2
        assert result["count"] == 2
        assert result["contacts"][0]["email"] == "alice@example.com"

        # Verify the service was built with the correct token
        MockCreds.assert_called_once_with(token="test_access_token_abc123")
        mock_build.assert_called_once_with(
            "gmail", "v1", credentials=MockCreds.return_value, cache_discovery=False
        )
        mock_get_contacts.assert_called_once_with(
            service=mock_service,
            query="alice",
            max_results=30,
        )

    def test_get_contacts_missing_token_raises(
        self, gmail_tools, mock_gmail_credentials_no_token
    ):
        tool = gmail_tools["GET_CONTACT_LIST"]

        from app.services.composio.custom_tools.gmail_tools import GetContactListInput

        with pytest.raises(ValueError, match="Missing access_token"):
            tool(
                request=GetContactListInput(query="test"),
                execute_request=None,
                auth_credentials=mock_gmail_credentials_no_token,
            )

    def test_get_contacts_service_error_raises_runtime(
        self, gmail_tools, mock_gmail_credentials
    ):
        tool = gmail_tools["GET_CONTACT_LIST"]

        from app.services.composio.custom_tools.gmail_tools import GetContactListInput

        with (
            patch("app.services.composio.custom_tools.gmail_tools.Credentials"),
            patch(
                "app.services.composio.custom_tools.gmail_tools.build",
                side_effect=Exception("Google API unreachable"),
            ),
        ):
            with pytest.raises(RuntimeError, match="Failed to get contacts"):
                tool(
                    request=GetContactListInput(query="test"),
                    execute_request=None,
                    auth_credentials=mock_gmail_credentials,
                )

    def test_get_contacts_passes_max_results(
        self, gmail_tools, mock_gmail_credentials
    ):
        tool = gmail_tools["GET_CONTACT_LIST"]

        from app.services.composio.custom_tools.gmail_tools import GetContactListInput

        with (
            patch("app.services.composio.custom_tools.gmail_tools.Credentials"),
            patch("app.services.composio.custom_tools.gmail_tools.build"),
            patch(
                "app.services.composio.custom_tools.gmail_tools.get_gmail_contacts",
                return_value={"success": True, "contacts": [], "count": 0},
            ) as mock_contacts,
        ):
            tool(
                request=GetContactListInput(query="test", max_results=50),
                execute_request=None,
                auth_credentials=mock_gmail_credentials,
            )

        mock_contacts.assert_called_once()
        call_kwargs = mock_contacts.call_args.kwargs
        assert call_kwargs["max_results"] == 50
        assert call_kwargs["query"] == "test"

    def test_get_contacts_empty_result(self, gmail_tools, mock_gmail_credentials):
        tool = gmail_tools["GET_CONTACT_LIST"]

        from app.services.composio.custom_tools.gmail_tools import GetContactListInput

        empty_result = {"success": True, "contacts": [], "count": 0}

        with (
            patch("app.services.composio.custom_tools.gmail_tools.Credentials"),
            patch("app.services.composio.custom_tools.gmail_tools.build"),
            patch(
                "app.services.composio.custom_tools.gmail_tools.get_gmail_contacts",
                return_value=empty_result,
            ),
        ):
            result = tool(
                request=GetContactListInput(query="nobody"),
                execute_request=None,
                auth_credentials=mock_gmail_credentials,
            )

        assert result["success"] is True
        assert result["contacts"] == []
        assert result["count"] == 0


# ---------------------------------------------------------------------------
# SCHEDULE_SEND — model-level tests (no registered tool in production)
# ---------------------------------------------------------------------------


@pytest.mark.composio
class TestScheduleSend:
    """Tests for ScheduleSendInput model validation.

    GMAIL_SCHEDULE_SEND is not yet registered as a Composio tool — these
    tests cover the Pydantic input model so that when the tool is wired up
    the model contract is already verified.
    """

    def test_schedule_send_input_required_fields(self):
        """All four required fields must be supplied."""
        from app.services.composio.custom_tools.gmail_tools import ScheduleSendInput
        import pydantic

        with pytest.raises(pydantic.ValidationError):
            ScheduleSendInput()  # missing all required fields

    def test_schedule_send_input_model_fields(self):
        from app.services.composio.custom_tools.gmail_tools import ScheduleSendInput

        req = ScheduleSendInput(
            recipient_email="test@example.com",
            subject="Hello",
            body="Test body",
            send_at="2024-01-15T10:00:00Z",
        )
        assert req.recipient_email == "test@example.com"
        assert req.cc is None
        assert req.bcc is None

    def test_schedule_send_input_with_cc_and_bcc(self):
        from app.services.composio.custom_tools.gmail_tools import ScheduleSendInput

        req = ScheduleSendInput(
            recipient_email="to@example.com",
            subject="CC/BCC test",
            body="Body",
            send_at="2024-06-01T08:00:00Z",
            cc="cc1@example.com,cc2@example.com",
            bcc="bcc@example.com",
        )
        assert req.cc == "cc1@example.com,cc2@example.com"
        assert req.bcc == "bcc@example.com"

    def test_schedule_send_missing_recipient_raises(self):
        from app.services.composio.custom_tools.gmail_tools import ScheduleSendInput
        import pydantic

        with pytest.raises(pydantic.ValidationError):
            ScheduleSendInput(
                subject="No recipient",
                body="Body",
                send_at="2024-01-15T10:00:00Z",
            )

    def test_schedule_send_missing_send_at_raises(self):
        from app.services.composio.custom_tools.gmail_tools import ScheduleSendInput
        import pydantic

        with pytest.raises(pydantic.ValidationError):
            ScheduleSendInput(
                recipient_email="to@example.com",
                subject="No timestamp",
                body="Body",
            )


# ---------------------------------------------------------------------------
# register_gmail_custom_tools return value tests
# ---------------------------------------------------------------------------


@pytest.mark.composio
class TestRegisterGmailCustomTools:
    """Tests for the registration function itself."""

    def test_returns_correct_tool_name_list(self, mock_composio_client):
        from app.services.composio.custom_tools.gmail_tools import (
            register_gmail_custom_tools,
        )

        result = register_gmail_custom_tools(mock_composio_client)

        assert isinstance(result, list)
        expected_names = [
            "GMAIL_MARK_AS_READ",
            "GMAIL_MARK_AS_UNREAD",
            "GMAIL_ARCHIVE_EMAIL",
            "GMAIL_STAR_EMAIL",
            "GMAIL_GET_UNREAD_COUNT",
            "GMAIL_GET_CONTACT_LIST",
            "GMAIL_CUSTOM_GATHER_CONTEXT",
        ]
        assert result == expected_names

    def test_all_tools_are_registered(self, mock_composio_client):
        from app.services.composio.custom_tools.gmail_tools import (
            register_gmail_custom_tools,
        )

        register_gmail_custom_tools(mock_composio_client)
        registered = mock_composio_client._registered_tools

        expected_fn_names = [
            "MARK_AS_READ",
            "MARK_AS_UNREAD",
            "ARCHIVE_EMAIL",
            "STAR_EMAIL",
            "GET_UNREAD_COUNT",
            "GET_CONTACT_LIST",
            "CUSTOM_GATHER_CONTEXT",
        ]
        for name in expected_fn_names:
            assert name in registered, f"Tool {name!r} was not registered"

    def test_all_registered_tools_are_callable(self, mock_composio_client):
        from app.services.composio.custom_tools.gmail_tools import (
            register_gmail_custom_tools,
        )

        register_gmail_custom_tools(mock_composio_client)
        for name, fn in mock_composio_client._registered_tools.items():
            assert callable(fn), f"{name} is not callable"

    def test_register_uses_gmail_toolkit(self, mock_composio_client):
        """All tools must be registered under the 'gmail' toolkit."""
        from app.services.composio.custom_tools.gmail_tools import (
            register_gmail_custom_tools,
        )

        register_gmail_custom_tools(mock_composio_client)

        # The custom_tool decorator was called with toolkit="gmail" for each tool
        for call in mock_composio_client.tools.custom_tool.call_args_list:
            assert call.kwargs.get("toolkit") == "gmail"


# ---------------------------------------------------------------------------
# Input model validation tests
# ---------------------------------------------------------------------------


@pytest.mark.composio
class TestInputModelValidation:
    """Tests that Pydantic input models enforce correct types."""

    def test_mark_as_read_input_requires_message_ids(self):
        from app.services.composio.custom_tools.gmail_tools import MarkAsReadInput
        import pydantic

        with pytest.raises(pydantic.ValidationError):
            MarkAsReadInput()  # missing required field

    def test_archive_email_input_requires_message_ids(self):
        from app.services.composio.custom_tools.gmail_tools import ArchiveEmailInput
        import pydantic

        with pytest.raises(pydantic.ValidationError):
            ArchiveEmailInput()

    def test_star_email_input_unstar_defaults_to_false(self):
        from app.services.composio.custom_tools.gmail_tools import StarEmailInput

        req = StarEmailInput(message_ids=["m1"])
        assert req.unstar is False

    def test_get_unread_count_input_defaults_to_no_label_ids(self):
        """GetUnreadCountInput has label_ids (list, optional), not label_id."""
        from app.services.composio.custom_tools.gmail_tools import GetUnreadCountInput

        req = GetUnreadCountInput()
        # label_ids defaults to None; the tool resolves to ["INBOX"] at runtime
        assert req.label_ids is None
        assert req.query is None
        assert req.include_spam_trash is False

    def test_get_unread_count_input_accepts_label_ids_list(self):
        from app.services.composio.custom_tools.gmail_tools import GetUnreadCountInput

        req = GetUnreadCountInput(label_ids=["INBOX", "STARRED"])
        assert req.label_ids == ["INBOX", "STARRED"]

    def test_schedule_send_input_model_fields(self):
        from app.services.composio.custom_tools.gmail_tools import ScheduleSendInput

        req = ScheduleSendInput(
            recipient_email="test@example.com",
            subject="Hello",
            body="Test body",
            send_at="2024-01-15T10:00:00Z",
        )
        assert req.recipient_email == "test@example.com"
        assert req.cc is None
        assert req.bcc is None

    def test_get_contact_list_input_default_max_results(self):
        from app.services.composio.custom_tools.gmail_tools import GetContactListInput

        req = GetContactListInput(query="test")
        assert req.max_results == 30

    def test_snooze_email_input_requires_snooze_until(self):
        from app.services.composio.custom_tools.gmail_tools import SnoozeEmailInput
        import pydantic

        with pytest.raises(pydantic.ValidationError):
            SnoozeEmailInput(message_ids=["m1"])  # missing snooze_until
