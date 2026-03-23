"""Unit tests for general utility functions."""

import base64
from typing import Any, Dict, List
from unittest.mock import mock_open, patch

import pytest

from app.utils.general_utils import (
    decode_message_body,
    describe_structure,
    get_context_window,
    get_project_info,
    transform_gmail_message,
)


# ---------------------------------------------------------------------------
# get_context_window
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestGetContextWindow:
    """Tests for get_context_window — returns a substring of *text* centred
    around *query* with configurable padding and ellipsis markers."""

    def test_query_found_in_middle_of_text(self) -> None:
        text = "The quick brown fox jumps over the lazy dog"
        result = get_context_window(text, "fox", chars_before=10, chars_after=10)
        assert "fox" in result
        assert result.startswith("...")
        assert result.endswith("...")

    def test_query_found_at_start_of_text(self) -> None:
        text = "Hello world, this is a test"
        result = get_context_window(text, "Hello", chars_before=10, chars_after=10)
        # window_start == max(0, 0 - 10) == 0 → no leading ellipsis
        assert not result.startswith("...")
        assert "Hello" in result

    def test_query_found_at_end_of_text(self) -> None:
        text = "This is a test string"
        result = get_context_window(text, "string", chars_before=5, chars_after=50)
        # window_end == min(len, pos + 6 + 50) → clamps to len → no trailing ellipsis
        assert not result.endswith("...")
        assert "string" in result

    def test_query_not_found_returns_empty(self) -> None:
        result = get_context_window("some text", "missing")
        assert result == ""

    def test_empty_text_returns_empty(self) -> None:
        result = get_context_window("", "query")
        assert result == ""

    def test_empty_query_matches_at_position_zero(self) -> None:
        # str.find("") returns 0 for any non-empty string
        text = "Hello world"
        result = get_context_window(text, "", chars_before=5, chars_after=5)
        assert result != ""

    def test_case_insensitive_match(self) -> None:
        text = "The Quick Brown Fox"
        result = get_context_window(text, "quick brown", chars_before=5, chars_after=5)
        assert "Quick Brown" in result

    def test_case_insensitive_all_uppercase_query(self) -> None:
        text = "hello world"
        result = get_context_window(text, "HELLO", chars_before=0, chars_after=5)
        assert "hello" in result

    def test_no_ellipsis_when_window_covers_full_text(self) -> None:
        text = "short"
        result = get_context_window(text, "short", chars_before=100, chars_after=100)
        assert result == "short"
        assert "..." not in result

    def test_both_ellipses_when_window_is_narrow(self) -> None:
        text = "aaaa NEEDLE bbbb"
        result = get_context_window(text, "NEEDLE", chars_before=2, chars_after=2)
        assert result.startswith("...")
        assert result.endswith("...")

    @pytest.mark.parametrize(
        "chars_before,chars_after",
        [(0, 0), (0, 10), (10, 0)],
    )
    def test_zero_padding_still_returns_query(
        self, chars_before: int, chars_after: int
    ) -> None:
        text = "before NEEDLE after"
        result = get_context_window(
            text, "NEEDLE", chars_before=chars_before, chars_after=chars_after
        )
        assert "NEEDLE" in result

    def test_default_padding_values(self) -> None:
        # Default: chars_before=15, chars_after=30
        text = "x" * 20 + "NEEDLE" + "y" * 40
        result = get_context_window(text, "NEEDLE")
        # Should have leading ellipsis (20 > 15) and trailing ellipsis (40 > 30)
        assert result.startswith("...")
        assert result.endswith("...")
        assert "NEEDLE" in result

    def test_preserves_original_casing_in_output(self) -> None:
        text = "The Quick Brown Fox"
        result = get_context_window(text, "quick", chars_before=50, chars_after=50)
        assert "Quick" in result


# ---------------------------------------------------------------------------
# transform_gmail_message
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestTransformGmailMessage:
    """Tests for transform_gmail_message — normalises both Composio and
    Gmail API message formats into a unified frontend-friendly dict."""

    def test_composio_format_basic(self) -> None:
        msg: Dict[str, Any] = {
            "messageId": "msg-123",
            "messageText": "Hello there",
            "threadId": "thread-1",
            "from": "alice@example.com",
            "to": "bob@example.com",
            "subject": "Test Subject",
            "date": "2024-01-15 10:00",
            "labelIds": ["INBOX"],
        }
        result = transform_gmail_message(msg)
        assert result["id"] == "msg-123"
        assert result["threadId"] == "thread-1"
        assert result["from"] == "alice@example.com"
        assert result["to"] == "bob@example.com"
        assert result["subject"] == "Test Subject"
        assert result["time"] == "2024-01-15 10:00"
        assert result["snippet"] == "Hello there"
        assert result["body"] == "Hello there"
        assert result["isThread"] is True

    def test_composio_format_snippet_fallback_to_messageText(self) -> None:
        msg: Dict[str, Any] = {
            "messageId": "id1",
            "messageText": "fallback text",
        }
        result = transform_gmail_message(msg)
        assert result["snippet"] == "fallback text"
        assert result["body"] == "fallback text"

    def test_composio_format_sender_fallback_to_sender_field(self) -> None:
        msg: Dict[str, Any] = {
            "messageId": "id1",
            "messageText": "text",
            "sender": "sender@example.com",
        }
        result = transform_gmail_message(msg)
        assert result["from"] == "sender@example.com"

    def test_composio_format_sender_empty_when_missing(self) -> None:
        msg: Dict[str, Any] = {
            "messageId": "id1",
            "messageText": "text",
        }
        result = transform_gmail_message(msg)
        assert result["from"] == ""

    def test_composio_format_messageTimestamp_used_when_no_date(self) -> None:
        msg: Dict[str, Any] = {
            "messageId": "id1",
            "messageText": "text",
            "messageTimestamp": "2024-06-15T14:30:00Z",
        }
        result = transform_gmail_message(msg)
        assert "2024-06-15" in result["time"]
        assert "14:30" in result["time"]

    def test_composio_format_messageTimestamp_unparseable_returned_raw(self) -> None:
        msg: Dict[str, Any] = {
            "messageId": "id1",
            "messageText": "text",
            "messageTimestamp": "not-a-date",
        }
        result = transform_gmail_message(msg)
        assert result["time"] == "not-a-date"

    def test_composio_format_isThread_false_when_no_labelIds(self) -> None:
        msg: Dict[str, Any] = {
            "messageId": "id1",
            "messageText": "text",
            "threadId": "thread-1",
        }
        result = transform_gmail_message(msg)
        # labelIds is missing → len([]) == 0 → False
        assert result["isThread"] is False

    def test_composio_format_isThread_false_when_no_threadId(self) -> None:
        msg: Dict[str, Any] = {
            "messageId": "id1",
            "messageText": "text",
            "labelIds": ["INBOX"],
        }
        result = transform_gmail_message(msg)
        assert result["isThread"] is False

    def test_gmail_api_format_basic(self) -> None:
        body_text = "Hello from Gmail"
        encoded_body = base64.urlsafe_b64encode(body_text.encode()).decode()
        msg: Dict[str, Any] = {
            "id": "gmail-1",
            "threadId": "thread-2",
            "snippet": "Hello from...",
            "internalDate": "1705305600000",  # 2024-01-15 in epoch ms
            "labelIds": ["INBOX"],
            "payload": {
                "headers": [
                    {"name": "From", "value": "sender@gmail.com"},
                    {"name": "To", "value": "receiver@gmail.com"},
                    {"name": "Cc", "value": "cc@gmail.com"},
                    {"name": "Reply-To", "value": "reply@gmail.com"},
                    {"name": "Subject", "value": "Gmail Subject"},
                ],
                "body": {"data": encoded_body},
            },
        }
        result = transform_gmail_message(msg)
        assert result["id"] == "gmail-1"
        assert result["threadId"] == "thread-2"
        assert result["from"] == "sender@gmail.com"
        assert result["to"] == "receiver@gmail.com"
        assert result["cc"] == "cc@gmail.com"
        assert result["replyTo"] == "reply@gmail.com"
        assert result["subject"] == "Gmail Subject"
        assert result["snippet"] == "Hello from..."
        assert result["body"] == body_text

    def test_gmail_api_format_uses_internalDate_for_time(self) -> None:
        msg: Dict[str, Any] = {
            "internalDate": "1705305600000",
            "payload": {"headers": []},
        }
        result = transform_gmail_message(msg)
        # Should produce a formatted datetime string
        assert "2024" in result["time"]

    def test_gmail_api_format_invalid_internalDate_returns_string(self) -> None:
        msg: Dict[str, Any] = {
            "internalDate": "not_a_number",
            "payload": {"headers": []},
        }
        result = transform_gmail_message(msg)
        assert result["time"] == "not_a_number"

    def test_gmail_api_format_missing_headers(self) -> None:
        msg: Dict[str, Any] = {
            "payload": {"headers": []},
        }
        result = transform_gmail_message(msg)
        assert result["from"] == ""
        assert result["to"] == ""
        assert result["subject"] == ""

    def test_gmail_api_format_missing_payload(self) -> None:
        msg: Dict[str, Any] = {}
        result = transform_gmail_message(msg)
        assert result["from"] == ""
        assert result["to"] == ""
        assert result["body"] is None  # decode_message_body returns None

    def test_gmail_api_format_no_time_fields_returns_empty(self) -> None:
        msg: Dict[str, Any] = {
            "payload": {"headers": []},
        }
        result = transform_gmail_message(msg)
        assert result["time"] == ""

    def test_gmail_api_format_isThread_true(self) -> None:
        msg: Dict[str, Any] = {
            "threadId": "t-1",
            "labelIds": ["INBOX", "IMPORTANT"],
            "payload": {"headers": []},
        }
        result = transform_gmail_message(msg)
        assert result["isThread"] is True

    def test_gmail_api_format_isThread_false_empty_labels(self) -> None:
        msg: Dict[str, Any] = {
            "threadId": "t-1",
            "labelIds": [],
            "payload": {"headers": []},
        }
        result = transform_gmail_message(msg)
        assert result["isThread"] is False

    def test_composio_preserves_extra_keys(self) -> None:
        """The **m spread should keep original keys in the result."""
        msg: Dict[str, Any] = {
            "messageId": "id1",
            "messageText": "text",
            "customField": "custom_value",
        }
        result = transform_gmail_message(msg)
        assert result["customField"] == "custom_value"

    def test_gmail_api_preserves_extra_keys(self) -> None:
        msg: Dict[str, Any] = {
            "payload": {"headers": []},
            "historyId": "12345",
        }
        result = transform_gmail_message(msg)
        assert result["historyId"] == "12345"

    def test_composio_date_field_takes_priority(self) -> None:
        msg: Dict[str, Any] = {
            "messageId": "id1",
            "messageText": "text",
            "date": "2024-01-01 09:00",
            "messageTimestamp": "2025-12-31T23:59:59Z",
            "internalDate": "9999999999999",
        }
        result = transform_gmail_message(msg)
        assert result["time"] == "2024-01-01 09:00"


# ---------------------------------------------------------------------------
# decode_message_body
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestDecodeMessageBody:
    """Tests for decode_message_body — extracts and base64-decodes the body
    from a Gmail API message payload."""

    def test_single_part_with_data(self) -> None:
        text = "Hello, World!"
        encoded = base64.urlsafe_b64encode(text.encode()).decode()
        msg: Dict[str, Any] = {
            "payload": {
                "body": {"data": encoded},
            }
        }
        result = decode_message_body(msg)
        assert result == text

    def test_single_part_no_data_returns_none(self) -> None:
        msg: Dict[str, Any] = {
            "payload": {
                "body": {"data": ""},
            }
        }
        result = decode_message_body(msg)
        assert result is None

    def test_single_part_no_body_key_returns_none(self) -> None:
        msg: Dict[str, Any] = {"payload": {}}
        result = decode_message_body(msg)
        assert result is None

    def test_no_payload_returns_none(self) -> None:
        msg: Dict[str, Any] = {}
        result = decode_message_body(msg)
        assert result is None

    def test_multipart_html_and_plain_prefers_html(self) -> None:
        html = "<h1>Hello</h1>"
        plain = "Hello"
        html_encoded = base64.urlsafe_b64encode(html.encode()).decode()
        plain_encoded = base64.urlsafe_b64encode(plain.encode()).decode()
        msg: Dict[str, Any] = {
            "payload": {
                "parts": [
                    {
                        "mimeType": "text/plain",
                        "body": {"data": plain_encoded},
                    },
                    {
                        "mimeType": "text/html",
                        "body": {"data": html_encoded},
                    },
                ]
            }
        }
        result = decode_message_body(msg)
        assert result == html

    def test_multipart_plain_only(self) -> None:
        plain = "Just plain text"
        plain_encoded = base64.urlsafe_b64encode(plain.encode()).decode()
        msg: Dict[str, Any] = {
            "payload": {
                "parts": [
                    {
                        "mimeType": "text/plain",
                        "body": {"data": plain_encoded},
                    },
                ]
            }
        }
        result = decode_message_body(msg)
        assert result == plain

    def test_multipart_html_only(self) -> None:
        html = "<p>Only HTML</p>"
        html_encoded = base64.urlsafe_b64encode(html.encode()).decode()
        msg: Dict[str, Any] = {
            "payload": {
                "parts": [
                    {
                        "mimeType": "text/html",
                        "body": {"data": html_encoded},
                    },
                ]
            }
        }
        result = decode_message_body(msg)
        assert result == html

    def test_multipart_no_data_in_parts_returns_none(self) -> None:
        msg: Dict[str, Any] = {
            "payload": {
                "parts": [
                    {
                        "mimeType": "text/plain",
                        "body": {"data": ""},
                    },
                    {
                        "mimeType": "text/html",
                        "body": {"data": ""},
                    },
                ]
            }
        }
        result = decode_message_body(msg)
        assert result is None

    def test_multipart_empty_parts_list_falls_to_single_part_path(self) -> None:
        # Empty parts list → treated as single-part → checks payload.body.data
        msg: Dict[str, Any] = {
            "payload": {
                "parts": [],
                "body": {"data": ""},
            }
        }
        result = decode_message_body(msg)
        assert result is None

    def test_multipart_unknown_mime_type_ignored(self) -> None:
        data = "attachment data"
        encoded = base64.urlsafe_b64encode(data.encode()).decode()
        msg: Dict[str, Any] = {
            "payload": {
                "parts": [
                    {
                        "mimeType": "application/pdf",
                        "body": {"data": encoded},
                    },
                ]
            }
        }
        result = decode_message_body(msg)
        # Neither html_body nor plain_body set → returns None
        assert result is None

    def test_decodes_standard_base64_with_plus_and_slash(self) -> None:
        # The function replaces - with + and _ with / before decoding.
        # urlsafe_b64encode uses - and _ already, so this tests the
        # replace logic is correct (double-replace shouldn't corrupt).
        text = "Test with special chars: +/="
        encoded = base64.urlsafe_b64encode(text.encode()).decode()
        msg: Dict[str, Any] = {
            "payload": {
                "body": {"data": encoded},
            }
        }
        result = decode_message_body(msg)
        assert result == text

    def test_handles_utf8_content(self) -> None:
        text = "Bonjour le monde! Schone Grusse! \u3053\u3093\u306b\u3061\u306f"
        encoded = base64.urlsafe_b64encode(text.encode("utf-8")).decode()
        msg: Dict[str, Any] = {
            "payload": {
                "body": {"data": encoded},
            }
        }
        result = decode_message_body(msg)
        assert result == text


# ---------------------------------------------------------------------------
# get_project_info
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestGetProjectInfo:
    """Tests for get_project_info — reads pyproject.toml and returns
    project metadata, falling back to defaults on error."""

    def test_success_reads_pyproject_toml(self) -> None:
        toml_content = b"""
[project]
name = "gaia-api"
version = "1.2.3"
description = "The GAIA backend"
"""
        with patch("builtins.open", mock_open(read_data=toml_content)):
            result = get_project_info()
        assert result["name"] == "gaia-api"
        assert result["version"] == "1.2.3"
        assert result["description"] == "The GAIA backend"

    def test_file_not_found_returns_defaults(self) -> None:
        with patch("builtins.open", side_effect=FileNotFoundError):
            result = get_project_info()
        assert result == {
            "name": "GAIA API",
            "version": "dev",
            "description": "Backend for GAIA",
        }

    def test_missing_project_section_uses_defaults(self) -> None:
        toml_content = b"""
[tool.ruff]
line-length = 120
"""
        with patch("builtins.open", mock_open(read_data=toml_content)):
            result = get_project_info()
        assert result["name"] == "GAIA API"
        assert result["version"] == "dev"
        assert result["description"] == "Backend for GAIA"

    def test_partial_project_section_fills_defaults(self) -> None:
        toml_content = b"""
[project]
name = "custom-name"
"""
        with patch("builtins.open", mock_open(read_data=toml_content)):
            result = get_project_info()
        assert result["name"] == "custom-name"
        assert result["version"] == "dev"
        assert result["description"] == "Backend for GAIA"

    def test_permission_error_returns_defaults(self) -> None:
        with patch("builtins.open", side_effect=PermissionError):
            result = get_project_info()
        assert result == {
            "name": "GAIA API",
            "version": "dev",
            "description": "Backend for GAIA",
        }

    def test_invalid_toml_returns_defaults(self) -> None:
        with patch("builtins.open", side_effect=Exception("parse error")):
            result = get_project_info()
        assert result == {
            "name": "GAIA API",
            "version": "dev",
            "description": "Backend for GAIA",
        }


# ---------------------------------------------------------------------------
# describe_structure
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestDescribeStructure:
    """Tests for describe_structure — recursively describes the shape of a
    nested dict/list structure as a flat list of dotted-path strings."""

    def test_flat_dict(self) -> None:
        obj: Dict[str, Any] = {"a": 1, "b": "two", "c": True}
        result = describe_structure(obj)
        assert result == ["a", "b", "c"]

    def test_nested_dict(self) -> None:
        obj: Dict[str, Any] = {"a": {"b": {"c": 1}}}
        result = describe_structure(obj)
        assert "a" in result
        assert "a.b" in result
        assert "a.b.c" in result

    def test_dict_with_list_value(self) -> None:
        obj: Dict[str, Any] = {"items": [1, 2, 3]}
        result = describe_structure(obj)
        assert "items: [3 items]" in result

    def test_dict_with_list_of_dicts(self) -> None:
        obj: Dict[str, Any] = {
            "users": [{"name": "Alice"}, {"name": "Bob"}],
        }
        result = describe_structure(obj)
        assert "users: [2 items]" in result
        assert "users.0.name" in result

    def test_dict_with_list_of_lists(self) -> None:
        obj: Dict[str, Any] = {
            "matrix": [[1, 2], [3, 4]],
        }
        result = describe_structure(obj)
        assert "matrix: [2 items]" in result
        # First element is a list → recurse into it
        assert "matrix.0: [2 items]" in result

    def test_empty_dict(self) -> None:
        result = describe_structure({})
        assert result == []

    def test_empty_list(self) -> None:
        result = describe_structure([])
        # list path, empty → just the parent line
        assert result == [": [0 items]"]

    def test_top_level_list(self) -> None:
        obj: List[Any] = [{"a": 1}, {"b": 2}]
        result = describe_structure(obj)
        assert ": [2 items]" in result
        assert ".0.a" in result

    def test_top_level_list_with_parent(self) -> None:
        obj: List[Any] = [{"x": 10}]
        result = describe_structure(obj, parent="root")
        assert "root: [1 items]" in result
        assert "root.0.x" in result

    def test_top_level_list_of_scalars(self) -> None:
        obj: List[Any] = [1, 2, 3]
        result = describe_structure(obj)
        # Non-empty list but first element is not dict/list → no recursion
        assert result == [": [3 items]"]

    def test_scalar_value_returns_parent(self) -> None:
        # When obj is neither dict nor list
        result = describe_structure("a string", parent="field")
        assert result == ["field"]

    def test_scalar_value_empty_parent(self) -> None:
        result = describe_structure(42)
        assert result == [""]

    def test_mixed_types_in_dict(self) -> None:
        obj: Dict[str, Any] = {
            "name": "test",
            "config": {"debug": True, "level": 5},
            "tags": ["a", "b"],
            "nested_list": [{"id": 1}],
        }
        result = describe_structure(obj)
        assert "name" in result
        assert "config" in result
        assert "config.debug" in result
        assert "config.level" in result
        assert "tags: [2 items]" in result
        assert "nested_list: [1 items]" in result
        assert "nested_list.0.id" in result

    def test_deeply_nested_structure(self) -> None:
        obj: Dict[str, Any] = {"a": {"b": {"c": {"d": "leaf"}}}}
        result = describe_structure(obj)
        assert "a" in result
        assert "a.b" in result
        assert "a.b.c" in result
        assert "a.b.c.d" in result

    def test_parent_parameter_propagates(self) -> None:
        obj: Dict[str, Any] = {"key": "value"}
        result = describe_structure(obj, parent="root")
        assert result == ["root.key"]

    def test_dict_with_empty_list_value(self) -> None:
        obj: Dict[str, Any] = {"empty": []}
        result = describe_structure(obj)
        assert "empty: [0 items]" in result

    def test_dict_with_none_value(self) -> None:
        obj: Dict[str, Any] = {"field": None}
        result = describe_structure(obj)
        assert "field" in result
