"""Unit tests for the contact service (app/services/contact_service.py)."""

from typing import Any, Dict, List
from unittest.mock import MagicMock, patch


from app.services.contact_service import (
    _process_message_batch,
    _process_messages_individually,
    extract_contacts_from_messages_batch,
    get_gmail_contacts,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_message_response(
    headers: List[Dict[str, str]],
) -> Dict[str, Any]:
    """Build a minimal Gmail message response dict with given headers."""
    return {"payload": {"headers": [{"name": k, "value": v} for k, v in headers]}}


def _make_gmail_service(
    messages_response: Dict[str, Any] | None = None,
    get_side_effect: Any = None,
) -> MagicMock:
    """
    Build a mock Gmail service object.

    The mock supports the chained call pattern:
        service.users().messages().list(...)  .execute()
        service.users().messages().get(...)   .execute()
        service.new_batch_http_request()
    """
    service = MagicMock()

    # .users().messages().list(...).execute()
    list_chain = service.users.return_value.messages.return_value.list
    if messages_response is not None:
        list_chain.return_value.execute.return_value = messages_response

    # .users().messages().get(...).execute()
    get_chain = service.users.return_value.messages.return_value.get
    if get_side_effect is not None:
        get_chain.return_value.execute.side_effect = get_side_effect

    return service


# ---------------------------------------------------------------------------
# _process_message_batch
# ---------------------------------------------------------------------------


class TestProcessMessageBatch:
    """Tests for _process_message_batch."""

    def test_success_with_valid_email_headers(self):
        """Valid From/To/Cc headers produce a correct contacts dict."""
        service = _make_gmail_service()
        batch_mock = MagicMock()
        service.new_batch_http_request.return_value = batch_mock

        msg_response = _make_message_response(
            [
                ("From", "alice@example.com"),
                ("To", "bob@domain.org"),
            ]
        )

        # Capture the callbacks registered via batch.add so we can invoke them.
        callbacks = {}

        def _capture_add(request, callback, request_id):
            callbacks[request_id] = callback

        batch_mock.add.side_effect = _capture_add

        def _execute():
            for rid, cb in callbacks.items():
                cb(rid, msg_response, None)

        batch_mock.execute.side_effect = _execute

        result = _process_message_batch(service, ["msg1"])

        assert "alice@example.com" in result
        assert result["alice@example.com"] == {
            "name": "",
            "email": "alice@example.com",
        }
        assert "bob@domain.org" in result
        assert result["bob@domain.org"] == {
            "name": "",
            "email": "bob@domain.org",
        }

    def test_batch_failure_falls_back_to_individual(self):
        """When batch.execute() raises, falls back to _process_messages_individually."""
        service = _make_gmail_service()
        service.new_batch_http_request.side_effect = Exception("batch broken")

        with patch(
            "app.services.contact_service._process_messages_individually"
        ) as mock_individual:
            mock_individual.return_value = {
                "fallback@test.com": {"name": "", "email": "fallback@test.com"}
            }
            result = _process_message_batch(service, ["msg1"])

        mock_individual.assert_called_once_with(service, ["msg1"], None)
        assert "fallback@test.com" in result

    def test_batch_execute_exception_falls_back(self):
        """When batch.execute() itself raises, fallback is triggered."""
        service = _make_gmail_service()
        batch_mock = MagicMock()
        service.new_batch_http_request.return_value = batch_mock
        batch_mock.execute.side_effect = Exception("network error")

        with patch(
            "app.services.contact_service._process_messages_individually"
        ) as mock_individual:
            mock_individual.return_value = {}
            result = _process_message_batch(service, ["msg1"])

        mock_individual.assert_called_once_with(service, ["msg1"], None)
        assert result == {}

    def test_malformed_email_no_at_sign_filtered(self):
        """Emails without '@' are not included in results."""
        service = _make_gmail_service()
        batch_mock = MagicMock()
        service.new_batch_http_request.return_value = batch_mock

        msg_response = _make_message_response([("From", "not-an-email")])
        callbacks = {}

        def _capture_add(request, callback, request_id):
            callbacks[request_id] = callback

        batch_mock.add.side_effect = _capture_add

        def _execute():
            for rid, cb in callbacks.items():
                cb(rid, msg_response, None)

        batch_mock.execute.side_effect = _execute

        result = _process_message_batch(service, ["msg1"])
        assert result == {}

    def test_malformed_email_no_dot_filtered(self):
        """Emails without '.' are not included in results."""
        service = _make_gmail_service()
        batch_mock = MagicMock()
        service.new_batch_http_request.return_value = batch_mock

        msg_response = _make_message_response([("From", "user@localhost")])
        callbacks = {}

        def _capture_add(request, callback, request_id):
            callbacks[request_id] = callback

        batch_mock.add.side_effect = _capture_add

        def _execute():
            for rid, cb in callbacks.items():
                cb(rid, msg_response, None)

        batch_mock.execute.side_effect = _execute

        result = _process_message_batch(service, ["msg1"])
        assert result == {}

    def test_email_format_name_angle_bracket_parsed(self):
        """'Name <email>' format is parsed into separate name and email."""
        service = _make_gmail_service()
        batch_mock = MagicMock()
        service.new_batch_http_request.return_value = batch_mock

        msg_response = _make_message_response(
            [("From", "Alice Smith <alice@example.com>")]
        )
        callbacks = {}

        def _capture_add(request, callback, request_id):
            callbacks[request_id] = callback

        batch_mock.add.side_effect = _capture_add

        def _execute():
            for rid, cb in callbacks.items():
                cb(rid, msg_response, None)

        batch_mock.execute.side_effect = _execute

        result = _process_message_batch(service, ["msg1"])
        assert "alice@example.com" in result
        assert result["alice@example.com"]["name"] == "Alice Smith"
        assert result["alice@example.com"]["email"] == "alice@example.com"

    def test_filter_query_contains_match(self):
        """filter_query matches when contained in name or email."""
        service = _make_gmail_service()
        batch_mock = MagicMock()
        service.new_batch_http_request.return_value = batch_mock

        msg_response = _make_message_response(
            [
                ("From", "Alice Smith <alice@example.com>"),
                ("To", "Bob Jones <bob@other.com>"),
            ]
        )
        callbacks = {}

        def _capture_add(request, callback, request_id):
            callbacks[request_id] = callback

        batch_mock.add.side_effect = _capture_add

        def _execute():
            for rid, cb in callbacks.items():
                cb(rid, msg_response, None)

        batch_mock.execute.side_effect = _execute

        result = _process_message_batch(service, ["msg1"], filter_query="alice")
        assert "alice@example.com" in result
        assert "bob@other.com" not in result

    def test_filter_query_startswith_match(self):
        """filter_query matches when name or email starts with the query."""
        service = _make_gmail_service()
        batch_mock = MagicMock()
        service.new_batch_http_request.return_value = batch_mock

        msg_response = _make_message_response(
            [
                ("From", "Alice Smith <alice@example.com>"),
                ("To", "Zara <zara@test.com>"),
            ]
        )
        callbacks = {}

        def _capture_add(request, callback, request_id):
            callbacks[request_id] = callback

        batch_mock.add.side_effect = _capture_add

        def _execute():
            for rid, cb in callbacks.items():
                cb(rid, msg_response, None)

        batch_mock.execute.side_effect = _execute

        result = _process_message_batch(service, ["msg1"], filter_query="zar")
        assert "zara@test.com" in result
        assert "alice@example.com" not in result

    def test_filter_query_case_insensitive(self):
        """filter_query matching is case-insensitive."""
        service = _make_gmail_service()
        batch_mock = MagicMock()
        service.new_batch_http_request.return_value = batch_mock

        msg_response = _make_message_response(
            [("From", "Alice Smith <ALICE@EXAMPLE.COM>")]
        )
        callbacks = {}

        def _capture_add(request, callback, request_id):
            callbacks[request_id] = callback

        batch_mock.add.side_effect = _capture_add

        def _execute():
            for rid, cb in callbacks.items():
                cb(rid, msg_response, None)

        batch_mock.execute.side_effect = _execute

        result = _process_message_batch(service, ["msg1"], filter_query="alice")
        assert "ALICE@EXAMPLE.COM" in result

    def test_filter_query_no_match_returns_empty(self):
        """filter_query that matches nothing returns empty dict."""
        service = _make_gmail_service()
        batch_mock = MagicMock()
        service.new_batch_http_request.return_value = batch_mock

        msg_response = _make_message_response([("From", "Alice <alice@example.com>")])
        callbacks = {}

        def _capture_add(request, callback, request_id):
            callbacks[request_id] = callback

        batch_mock.add.side_effect = _capture_add

        def _execute():
            for rid, cb in callbacks.items():
                cb(rid, msg_response, None)

        batch_mock.execute.side_effect = _execute

        result = _process_message_batch(service, ["msg1"], filter_query="zzzznotfound")
        assert result == {}

    def test_missing_from_to_cc_headers_skipped(self):
        """Messages without From/To/Cc/Reply-To headers produce no contacts."""
        service = _make_gmail_service()
        batch_mock = MagicMock()
        service.new_batch_http_request.return_value = batch_mock

        msg_response = _make_message_response(
            [("Subject", "Hello"), ("Date", "2025-01-01")]
        )
        callbacks = {}

        def _capture_add(request, callback, request_id):
            callbacks[request_id] = callback

        batch_mock.add.side_effect = _capture_add

        def _execute():
            for rid, cb in callbacks.items():
                cb(rid, msg_response, None)

        batch_mock.execute.side_effect = _execute

        result = _process_message_batch(service, ["msg1"])
        assert result == {}

    def test_empty_payload_headers(self):
        """Message with no payload or empty headers produces no contacts."""
        service = _make_gmail_service()
        batch_mock = MagicMock()
        service.new_batch_http_request.return_value = batch_mock

        callbacks = {}

        def _capture_add(request, callback, request_id):
            callbacks[request_id] = callback

        batch_mock.add.side_effect = _capture_add

        def _execute():
            for rid, cb in callbacks.items():
                cb(rid, {}, None)

        batch_mock.execute.side_effect = _execute

        result = _process_message_batch(service, ["msg1"])
        assert result == {}

    def test_callback_exception_logged_and_skipped(self):
        """When a batch callback receives an exception, the message is skipped."""
        service = _make_gmail_service()
        batch_mock = MagicMock()
        service.new_batch_http_request.return_value = batch_mock

        callbacks = {}

        def _capture_add(request, callback, request_id):
            callbacks[request_id] = callback

        batch_mock.add.side_effect = _capture_add

        def _execute():
            for rid, cb in callbacks.items():
                cb(rid, None, Exception("404 not found"))

        batch_mock.execute.side_effect = _execute

        result = _process_message_batch(service, ["msg1"])
        assert result == {}

    def test_multiple_messages_deduplicates_by_email(self):
        """Same email across multiple messages appears only once."""
        service = _make_gmail_service()
        batch_mock = MagicMock()
        service.new_batch_http_request.return_value = batch_mock

        msg1_response = _make_message_response([("From", "alice@example.com")])
        msg2_response = _make_message_response(
            [("From", "alice@example.com"), ("To", "bob@test.org")]
        )

        callbacks = {}

        def _capture_add(request, callback, request_id):
            callbacks[request_id] = callback

        batch_mock.add.side_effect = _capture_add

        def _execute():
            responses = {"msg1": msg1_response, "msg2": msg2_response}
            for rid, cb in callbacks.items():
                cb(rid, responses.get(rid, {}), None)

        batch_mock.execute.side_effect = _execute

        result = _process_message_batch(service, ["msg1", "msg2"])
        assert len(result) == 2
        assert "alice@example.com" in result
        assert "bob@test.org" in result

    def test_comma_separated_addresses_in_to(self):
        """Multiple comma-separated addresses in To are all extracted."""
        service = _make_gmail_service()
        batch_mock = MagicMock()
        service.new_batch_http_request.return_value = batch_mock

        msg_response = _make_message_response(
            [("To", "a@test.com, b@test.com, c@test.com")]
        )
        callbacks = {}

        def _capture_add(request, callback, request_id):
            callbacks[request_id] = callback

        batch_mock.add.side_effect = _capture_add

        def _execute():
            for rid, cb in callbacks.items():
                cb(rid, msg_response, None)

        batch_mock.execute.side_effect = _execute

        result = _process_message_batch(service, ["msg1"])
        assert len(result) == 3
        assert "a@test.com" in result
        assert "b@test.com" in result
        assert "c@test.com" in result

    def test_reply_to_header_extracted(self):
        """Reply-To header is also used for contact extraction."""
        service = _make_gmail_service()
        batch_mock = MagicMock()
        service.new_batch_http_request.return_value = batch_mock

        msg_response = _make_message_response([("Reply-To", "replyto@example.com")])
        callbacks = {}

        def _capture_add(request, callback, request_id):
            callbacks[request_id] = callback

        batch_mock.add.side_effect = _capture_add

        def _execute():
            for rid, cb in callbacks.items():
                cb(rid, msg_response, None)

        batch_mock.execute.side_effect = _execute

        result = _process_message_batch(service, ["msg1"])
        assert "replyto@example.com" in result

    def test_empty_address_after_split_skipped(self):
        """Trailing comma producing empty string after split is skipped."""
        service = _make_gmail_service()
        batch_mock = MagicMock()
        service.new_batch_http_request.return_value = batch_mock

        msg_response = _make_message_response([("To", "a@test.com, , ")])
        callbacks = {}

        def _capture_add(request, callback, request_id):
            callbacks[request_id] = callback

        batch_mock.add.side_effect = _capture_add

        def _execute():
            for rid, cb in callbacks.items():
                cb(rid, msg_response, None)

        batch_mock.execute.side_effect = _execute

        result = _process_message_batch(service, ["msg1"])
        assert len(result) == 1
        assert "a@test.com" in result

    def test_callback_processing_exception_caught(self):
        """An exception inside the callback's try block is caught and logged."""
        service = _make_gmail_service()
        batch_mock = MagicMock()
        service.new_batch_http_request.return_value = batch_mock

        # response with a structure that will cause an error inside the callback
        # (headers not being iterable)
        bad_response = {"payload": {"headers": "not-a-list"}}
        callbacks = {}

        def _capture_add(request, callback, request_id):
            callbacks[request_id] = callback

        batch_mock.add.side_effect = _capture_add

        def _execute():
            for rid, cb in callbacks.items():
                cb(rid, bad_response, None)

        batch_mock.execute.side_effect = _execute

        # Should not raise, just log a warning and return empty
        result = _process_message_batch(service, ["msg1"])
        assert result == {}


# ---------------------------------------------------------------------------
# _process_messages_individually
# ---------------------------------------------------------------------------


class TestProcessMessagesIndividually:
    """Tests for _process_messages_individually."""

    def test_success_with_messages(self):
        """Successfully extracts contacts from individually fetched messages."""
        msg_response = _make_message_response(
            [
                ("From", "Alice <alice@example.com>"),
                ("To", "bob@domain.org"),
            ]
        )
        service = _make_gmail_service(get_side_effect=[msg_response])

        result = _process_messages_individually(service, ["msg1"])

        assert "alice@example.com" in result
        assert result["alice@example.com"]["name"] == "Alice"
        assert "bob@domain.org" in result

    def test_limited_to_20_messages(self):
        """Only the first 20 messages are processed."""
        msg_response = _make_message_response([("From", "a@test.com")])
        # Create 30 message IDs but only expect 20 calls
        service = _make_gmail_service(get_side_effect=[msg_response] * 20)

        message_ids = [f"msg{i}" for i in range(30)]
        _process_messages_individually(service, message_ids)

        get_chain = service.users.return_value.messages.return_value.get
        assert get_chain.return_value.execute.call_count == 20

    def test_individual_fetch_failure_continues(self):
        """Failure on one message does not prevent processing the rest."""
        msg_ok = _make_message_response([("From", "good@example.com")])

        service = _make_gmail_service(
            get_side_effect=[Exception("fetch failed"), msg_ok]
        )

        result = _process_messages_individually(service, ["msg_bad", "msg_good"])

        assert "good@example.com" in result
        assert len(result) == 1

    def test_with_filter_query_matching(self):
        """filter_query is applied during individual processing."""
        msg_response = _make_message_response(
            [
                ("From", "Alice <alice@example.com>"),
                ("To", "Bob <bob@other.com>"),
            ]
        )
        service = _make_gmail_service(get_side_effect=[msg_response])

        result = _process_messages_individually(service, ["msg1"], filter_query="bob")

        assert "bob@other.com" in result
        assert "alice@example.com" not in result

    def test_with_filter_query_no_match(self):
        """filter_query that matches nothing returns empty dict."""
        msg_response = _make_message_response([("From", "alice@example.com")])
        service = _make_gmail_service(get_side_effect=[msg_response])

        result = _process_messages_individually(service, ["msg1"], filter_query="zzz")

        assert result == {}

    def test_name_angle_bracket_format_parsed(self):
        """'Name <email>' is correctly parsed in individual processing."""
        msg_response = _make_message_response([("From", "John Doe <john@example.com>")])
        service = _make_gmail_service(get_side_effect=[msg_response])

        result = _process_messages_individually(service, ["msg1"])

        assert "john@example.com" in result
        assert result["john@example.com"]["name"] == "John Doe"

    def test_malformed_email_filtered_out(self):
        """Invalid emails are filtered during individual processing."""
        msg_response = _make_message_response(
            [("From", "notanemail"), ("To", "valid@test.com")]
        )
        service = _make_gmail_service(get_side_effect=[msg_response])

        result = _process_messages_individually(service, ["msg1"])

        assert "notanemail" not in result
        assert "valid@test.com" in result

    def test_missing_headers_skipped(self):
        """Messages without relevant headers produce no contacts."""
        msg_response = _make_message_response(
            [("Subject", "Hello"), ("Date", "2025-01-01")]
        )
        service = _make_gmail_service(get_side_effect=[msg_response])

        result = _process_messages_individually(service, ["msg1"])
        assert result == {}

    def test_empty_message_ids(self):
        """Empty message_ids list returns empty dict immediately."""
        service = _make_gmail_service()
        result = _process_messages_individually(service, [])
        assert result == {}

    def test_all_messages_fail(self):
        """When every individual fetch fails, returns empty dict."""
        service = _make_gmail_service(
            get_side_effect=[Exception("err1"), Exception("err2")]
        )

        result = _process_messages_individually(service, ["m1", "m2"])
        assert result == {}


# ---------------------------------------------------------------------------
# extract_contacts_from_messages_batch
# ---------------------------------------------------------------------------


class TestExtractContactsFromMessagesBatch:
    """Tests for extract_contacts_from_messages_batch."""

    @patch("app.services.contact_service._process_message_batch")
    def test_processes_in_batches_of_batch_size(self, mock_batch):
        """Messages are split into chunks of batch_size."""
        mock_batch.return_value = {}
        service = MagicMock()
        message_ids = [f"msg{i}" for i in range(75)]

        extract_contacts_from_messages_batch(service, message_ids, batch_size=25)

        assert mock_batch.call_count == 3
        # First batch: 25, second batch: 25, third batch: 25
        assert len(mock_batch.call_args_list[0][0][1]) == 25
        assert len(mock_batch.call_args_list[1][0][1]) == 25
        assert len(mock_batch.call_args_list[2][0][1]) == 25

    @patch("app.services.contact_service._process_message_batch")
    def test_limits_to_100_messages_max(self, mock_batch):
        """Only the first 100 messages are processed even if more are provided."""
        mock_batch.return_value = {}
        service = MagicMock()
        message_ids = [f"msg{i}" for i in range(150)]

        extract_contacts_from_messages_batch(service, message_ids, batch_size=50)

        # 100 messages / 50 batch_size = 2 batches
        assert mock_batch.call_count == 2
        total_processed = sum(len(c[0][1]) for c in mock_batch.call_args_list)
        assert total_processed == 100

    @patch("app.services.contact_service._process_message_batch")
    def test_empty_message_ids_returns_empty_list(self, mock_batch):
        """Empty message_ids produces an empty list without calling batch."""
        service = MagicMock()

        result = extract_contacts_from_messages_batch(service, [])

        assert result == []
        mock_batch.assert_not_called()

    @patch("app.services.contact_service._process_message_batch")
    def test_returns_sorted_contacts(self, mock_batch):
        """Contacts are sorted alphabetically by name, then email."""
        mock_batch.return_value = {
            "zara@test.com": {"name": "Zara", "email": "zara@test.com"},
            "alice@test.com": {"name": "Alice", "email": "alice@test.com"},
            "bob@test.com": {"name": "Bob", "email": "bob@test.com"},
        }
        service = MagicMock()

        result = extract_contacts_from_messages_batch(service, ["msg1"], batch_size=50)

        assert len(result) == 3
        assert result[0]["name"] == "Alice"
        assert result[1]["name"] == "Bob"
        assert result[2]["name"] == "Zara"

    @patch("app.services.contact_service._process_message_batch")
    def test_contacts_without_name_sorted_by_email(self, mock_batch):
        """Contacts with empty name are sorted by email."""
        mock_batch.return_value = {
            "zara@test.com": {"name": "", "email": "zara@test.com"},
            "alice@test.com": {"name": "", "email": "alice@test.com"},
        }
        service = MagicMock()

        result = extract_contacts_from_messages_batch(service, ["msg1"], batch_size=50)

        assert result[0]["email"] == "alice@test.com"
        assert result[1]["email"] == "zara@test.com"

    @patch("app.services.contact_service._process_message_batch")
    def test_merges_results_across_batches(self, mock_batch):
        """Results from multiple batches are merged and deduplicated."""
        call_count = [0]

        def _batch_response(service, batch_ids, filter_query=None):
            call_count[0] += 1
            if call_count[0] == 1:
                return {
                    "alice@test.com": {"name": "Alice", "email": "alice@test.com"},
                }
            return {
                "bob@test.com": {"name": "Bob", "email": "bob@test.com"},
                "alice@test.com": {"name": "Alice Updated", "email": "alice@test.com"},
            }

        mock_batch.side_effect = _batch_response
        service = MagicMock()
        message_ids = [f"msg{i}" for i in range(4)]

        result = extract_contacts_from_messages_batch(
            service, message_ids, batch_size=2
        )

        # alice appears in both batches; second batch overwrites first
        assert len(result) == 2
        emails = {c["email"] for c in result}
        assert "alice@test.com" in emails
        assert "bob@test.com" in emails

    @patch("app.services.contact_service._process_message_batch")
    def test_filter_query_passed_through(self, mock_batch):
        """filter_query is forwarded to _process_message_batch."""
        mock_batch.return_value = {}
        service = MagicMock()

        extract_contacts_from_messages_batch(
            service, ["msg1"], filter_query="test", batch_size=50
        )

        mock_batch.assert_called_once_with(service, ["msg1"], "test")

    @patch("app.services.contact_service._process_message_batch")
    def test_single_message_single_batch(self, mock_batch):
        """A single message ID results in one batch call."""
        mock_batch.return_value = {
            "a@test.com": {"name": "", "email": "a@test.com"},
        }
        service = MagicMock()

        result = extract_contacts_from_messages_batch(service, ["msg1"], batch_size=50)

        assert mock_batch.call_count == 1
        assert len(result) == 1

    @patch("app.services.contact_service._process_message_batch")
    def test_exact_100_messages_all_processed(self, mock_batch):
        """Exactly 100 messages are all processed (boundary condition)."""
        mock_batch.return_value = {}
        service = MagicMock()
        message_ids = [f"msg{i}" for i in range(100)]

        extract_contacts_from_messages_batch(service, message_ids, batch_size=50)

        assert mock_batch.call_count == 2
        total = sum(len(c[0][1]) for c in mock_batch.call_args_list)
        assert total == 100


# ---------------------------------------------------------------------------
# get_gmail_contacts
# ---------------------------------------------------------------------------


class TestGetGmailContacts:
    """Tests for get_gmail_contacts."""

    @patch("app.services.contact_service.extract_contacts_from_messages_batch")
    def test_success_with_messages_found(self, mock_extract):
        """When messages are found, returns contacts with success=True."""
        mock_extract.return_value = [
            {"name": "Alice", "email": "alice@example.com"},
            {"name": "Bob", "email": "bob@example.com"},
        ]
        service = _make_gmail_service(
            messages_response={"messages": [{"id": "msg1"}, {"id": "msg2"}]}
        )

        result = get_gmail_contacts(service, query="test")

        assert result["success"] is True
        assert result["count"] == 2
        assert len(result["contacts"]) == 2
        mock_extract.assert_called_once_with(
            service, ["msg1", "msg2"], filter_query="test"
        )

    @patch("app.services.contact_service.extract_contacts_from_messages_batch")
    def test_no_messages_returns_empty_contacts(self, mock_extract):
        """No messages found returns success=True with empty contacts list."""
        service = _make_gmail_service(messages_response={"messages": []})

        result = get_gmail_contacts(service, query="nobody")

        assert result["success"] is True
        assert result["contacts"] == []
        assert result["count"] == 0
        assert "message" in result
        mock_extract.assert_not_called()

    @patch("app.services.contact_service.extract_contacts_from_messages_batch")
    def test_no_messages_key_returns_empty(self, mock_extract):
        """Response without 'messages' key returns success=True with empty contacts."""
        service = _make_gmail_service(messages_response={})

        result = get_gmail_contacts(service, query="test")

        assert result["success"] is True
        assert result["contacts"] == []
        assert result["count"] == 0
        mock_extract.assert_not_called()

    def test_search_failure_returns_success_false(self):
        """When the list() call raises, returns success=False."""
        service = _make_gmail_service()
        service.users.return_value.messages.return_value.list.return_value.execute.side_effect = Exception(
            "API quota exceeded"
        )

        result = get_gmail_contacts(service, query="test")

        assert result["success"] is False
        assert "error" in result
        assert result["contacts"] == []

    @patch("app.services.contact_service.extract_contacts_from_messages_batch")
    def test_extract_failure_returns_success_false(self, mock_extract):
        """When extract_contacts raises, returns success=False."""
        mock_extract.side_effect = Exception("extraction error")
        service = _make_gmail_service(messages_response={"messages": [{"id": "msg1"}]})

        result = get_gmail_contacts(service, query="test")

        assert result["success"] is False
        assert "error" in result
        assert result["contacts"] == []

    @patch("app.services.contact_service.extract_contacts_from_messages_batch")
    def test_max_results_passed_to_list(self, mock_extract):
        """max_results is forwarded to the Gmail list API."""
        mock_extract.return_value = []
        service = _make_gmail_service(messages_response={"messages": [{"id": "msg1"}]})

        get_gmail_contacts(service, query="test", max_results=25)

        list_call = service.users.return_value.messages.return_value.list
        list_call.assert_called_once_with(userId="me", q="test", maxResults=25)

    @patch("app.services.contact_service.extract_contacts_from_messages_batch")
    def test_default_max_results_is_50(self, mock_extract):
        """Default max_results is 50."""
        mock_extract.return_value = []
        service = _make_gmail_service(messages_response={"messages": [{"id": "msg1"}]})

        get_gmail_contacts(service, query="test")

        list_call = service.users.return_value.messages.return_value.list
        list_call.assert_called_once_with(userId="me", q="test", maxResults=50)

    @patch("app.services.contact_service.extract_contacts_from_messages_batch")
    def test_message_ids_extracted_correctly(self, mock_extract):
        """Message IDs are correctly extracted from search results."""
        mock_extract.return_value = []
        service = _make_gmail_service(
            messages_response={
                "messages": [
                    {"id": "aaa", "threadId": "t1"},
                    {"id": "bbb", "threadId": "t2"},
                    {"id": "ccc", "threadId": "t3"},
                ]
            }
        )

        get_gmail_contacts(service, query="q")

        mock_extract.assert_called_once_with(
            service, ["aaa", "bbb", "ccc"], filter_query="q"
        )
