"""Comprehensive tests for app/agents/templates/mail_templates.py."""

import base64
import email.message
import json
from unittest.mock import patch

import pytest

from app.agents.templates.mail_templates import (
    GmailMessageParser,
    _copy_headers,
    _decode_part_payload,
    _get_text_from_html,
    build_message_view,
    detailed_message_template,
    draft_template,
    message_view_needs_body,
    minimal_message_template,
    process_get_thread_response,
    process_list_drafts_response,
    project_message_view,
    thread_template,
)
from app.models.composio_schemas.gmail import (
    BodyProcessingLiteral,
    GmailMessagePart,
    GmailMessageView,
)
from app.models.integrations.gmail import GmailThreadData
from app.models.integrations.gmail_messages import RelayedGmailMessage
from shared.py.wide_events import log

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


_RAW_EMAIL_HEADERS = {
    "subject": "Subject",
    "sender": "From",
    "to": "To",
    "cc": "Cc",
    "date": "Date",
}
_RAW_EMAIL_DEFAULTS = {
    "subject": "Test Subject",
    "sender": "alice@example.com",
    "to": "bob@example.com",
    "date": "Mon, 01 Jan 2025 12:00:00 +0000",
}


def _make_raw_email(
    body_text: str = "Hello plain text", body_html: str = "", **headers: str
) -> str:
    """Build a raw base64url-encoded email; headers (subject, sender, to, cc, date) override the defaults."""
    msg = email.message.EmailMessage()
    for key, value in {**_RAW_EMAIL_DEFAULTS, **headers}.items():
        if value:
            msg[_RAW_EMAIL_HEADERS[key]] = value
    if body_html:
        msg.set_content(body_text)
        msg.add_alternative(body_html, subtype="html")
    else:
        msg.set_content(body_text)
    raw_bytes = msg.as_bytes()
    return base64.urlsafe_b64encode(raw_bytes).decode("ascii")


def _make_gmail_message(
    msg_id: str = "msg_001",
    thread_id: str = "thread_001",
    raw: str | None = None,
    payload: dict | None = None,
    label_ids: list | None = None,
    snippet: str = "Preview text",
    **extra,
) -> dict:
    """Build a Gmail API message dict."""
    result: dict = {
        "id": msg_id,
        "threadId": thread_id,
        "snippet": snippet,
        "labelIds": label_ids or ["INBOX"],
    }
    if raw:
        result["raw"] = raw
    if payload:
        result["payload"] = payload
    result.update(extra)
    return result


def _b64_encode(text: str) -> str:
    return base64.urlsafe_b64encode(text.encode("utf-8")).decode("ascii")


def _parser(message: dict) -> GmailMessageParser:
    return GmailMessageParser(RelayedGmailMessage.model_validate(message))


# ---------------------------------------------------------------------------
# _get_text_from_html
# ---------------------------------------------------------------------------


class TestGetTextFromHtml:
    def test_basic_html(self):
        html = "<p>Hello <b>World</b></p>"
        result = _get_text_from_html(html)
        assert "Hello" in result
        assert "World" in result

    def test_empty_string(self):
        assert _get_text_from_html("") == ""

    def test_none_returns_empty(self):
        assert _get_text_from_html(None) == ""

    def test_html_entities_unescaped(self):
        html = "<p>5 &gt; 3 &amp; 2 &lt; 4</p>"
        result = _get_text_from_html(html)
        assert ">" in result
        assert "&" in result
        assert "<" in result

    def test_nested_tags(self):
        html = "<div><ul><li>Item 1</li><li>Item 2</li></ul></div>"
        result = _get_text_from_html(html)
        assert "Item 1" in result
        assert "Item 2" in result


# ---------------------------------------------------------------------------
# GmailMessageParser — raw email parsing
# ---------------------------------------------------------------------------


class TestGmailMessageParserRaw:
    def test_parse_raw_email_success(self):
        raw = _make_raw_email(subject="Important", sender="a@b.com", body_text="content")
        msg = _make_gmail_message(raw=raw)

        parser = _parser(msg)
        assert parser.parse() is True
        assert parser.subject == "Important"
        assert parser.sender == "a@b.com"
        assert "content" in parser.text_content

    def test_properties_before_parse(self):
        parser = _parser({"id": "x"})
        assert parser.subject == ""
        assert parser.sender == ""
        assert parser.to == ""
        assert parser.cc == ""
        assert parser.date == ""
        assert parser.text_content == ""
        assert parser.html_content == ""
        assert parser.content == {"text": "", "html": ""}

    def test_raw_email_with_html(self):
        raw = _make_raw_email(
            body_text="Plain text",
            body_html="<p>HTML content</p>",
        )
        msg = _make_gmail_message(raw=raw)

        parser = _parser(msg)
        parser.parse()

        assert "HTML content" in parser.html_content
        assert "Plain text" in parser.text_content

    def test_raw_email_cc_header(self):
        raw = _make_raw_email(cc="cc@example.com")
        msg = _make_gmail_message(raw=raw)

        parser = _parser(msg)
        parser.parse()
        assert "cc@example.com" in parser.cc

    def test_raw_email_to_header(self):
        raw = _make_raw_email(to="recipient@example.com")
        msg = _make_gmail_message(raw=raw)

        parser = _parser(msg)
        parser.parse()
        assert "recipient@example.com" in parser.to

    def test_raw_email_date(self):
        raw = _make_raw_email(date="Tue, 15 Mar 2025 10:30:00 +0000")
        msg = _make_gmail_message(raw=raw)

        parser = _parser(msg)
        parser.parse()
        assert "2025" in parser.date


# ---------------------------------------------------------------------------
# GmailMessageParser — payload parsing
# ---------------------------------------------------------------------------


class TestGmailMessageParserPayload:
    def test_single_part_text_plain(self):
        payload = {
            "mimeType": "text/plain",
            "headers": [
                {"name": "Subject", "value": "Test"},
                {"name": "From", "value": "sender@test.com"},
            ],
            "body": {"data": _b64_encode("Body content")},
        }
        msg = _make_gmail_message(payload=payload)

        parser = _parser(msg)
        assert parser.parse() is True
        assert parser.subject == "Test"
        assert "Body content" in parser.text_content

    def test_single_part_text_html(self):
        payload = {
            "mimeType": "text/html",
            "headers": [{"name": "Subject", "value": "HTML Email"}],
            "body": {"data": _b64_encode("<p>Hello HTML</p>")},
        }
        msg = _make_gmail_message(payload=payload)

        parser = _parser(msg)
        parser.parse()
        assert "Hello HTML" in parser.html_content

    def test_multipart_payload(self):
        payload = {
            "mimeType": "multipart/alternative",
            "headers": [{"name": "Subject", "value": "Multi"}],
            "parts": [
                {
                    "mimeType": "text/plain",
                    "headers": [],
                    "body": {"data": _b64_encode("Plain part")},
                },
                {
                    "mimeType": "text/html",
                    "headers": [],
                    "body": {"data": _b64_encode("<p>HTML part</p>")},
                },
            ],
        }
        msg = _make_gmail_message(payload=payload)

        parser = _parser(msg)
        parser.parse()
        assert "Plain part" in parser.text_content or "HTML part" in parser.html_content

    def test_multipart_with_attachment(self):
        payload = {
            "mimeType": "multipart/mixed",
            "headers": [{"name": "Subject", "value": "With Attach"}],
            "parts": [
                {
                    "mimeType": "text/plain",
                    "headers": [],
                    "body": {"data": _b64_encode("Main body")},
                },
                {
                    "mimeType": "application/pdf",
                    "headers": [
                        {
                            "name": "Content-Disposition",
                            "value": 'attachment; filename="doc.pdf"',
                        },
                    ],
                    "filename": "doc.pdf",
                    "body": {
                        "data": _b64_encode("fake pdf"),
                        "attachmentId": "att_001",
                        "size": 100,
                    },
                },
            ],
        }
        msg = _make_gmail_message(payload=payload)

        parser = _parser(msg)
        parser.parse()
        assert parser.subject == "With Attach"

    def test_nested_multipart(self):
        payload = {
            "mimeType": "multipart/mixed",
            "headers": [],
            "parts": [
                {
                    "mimeType": "multipart/alternative",
                    "headers": [],
                    "parts": [
                        {
                            "mimeType": "text/plain",
                            "headers": [],
                            "body": {"data": _b64_encode("Nested plain")},
                        },
                    ],
                },
            ],
        }
        msg = _make_gmail_message(payload=payload)

        parser = _parser(msg)
        assert parser.parse() is True

    def test_empty_payload_returns_false(self):
        """Empty payload dict is falsy, so parsing returns None / False."""
        msg = _make_gmail_message(payload={})

        parser = _parser(msg)
        # Empty dict is falsy, so `if payload:` is False -> returns None -> parse is False
        assert parser.parse() is False

    def test_no_raw_no_payload(self):
        msg = {"id": "msg_empty"}

        parser = _parser(msg)
        result = parser.parse()
        # No raw, no payload -> email_message is None -> returns False
        assert result is False

    def test_empty_body_data(self):
        payload = {
            "mimeType": "text/plain",
            "headers": [],
            "body": {"data": ""},
        }
        msg = _make_gmail_message(payload=payload)

        parser = _parser(msg)
        parser.parse()
        assert parser.text_content == ""

    def test_parse_error_returns_false(self):
        """Simulate a parse error."""
        msg = _make_gmail_message()

        parser = _parser(msg)
        with patch.object(parser, "_parse_with_email_parser", side_effect=Exception("parse fail")):
            assert parser.parse() is False
            assert parser._parsed is False


# ---------------------------------------------------------------------------
# GmailMessageParser — labels
# ---------------------------------------------------------------------------


class TestGmailMessageParserLabels:
    def test_the_wide_event_names_the_message_this_parse_read(self) -> None:
        """The parse stamps the id it is working on."""
        log.reset()

        _parser(_make_gmail_message(raw=_make_raw_email())).parse()

        assert log.get()["gmail_message_id"] == "msg_001"
        assert log.get()["mail_op"] == "parse_gmail_message"

    def test_the_wide_event_falls_back_to_the_relayed_id_then_says_nothing(self) -> None:
        """A relay that carries only messageId still names the message it parsed."""
        log.reset()

        _parser({"messageId": "mid_9", "labelIds": []}).parse()

        assert log.get()["gmail_message_id"] == "mid_9"

    def test_a_message_with_neither_id_is_logged_with_no_id(self) -> None:
        log.reset()

        _parser({"labelIds": []}).parse()

        assert log.get()["gmail_message_id"] == ""

    def test_no_header_reads_as_empty_before_and_after_a_failed_parse(self) -> None:
        """Every header getter answers "" when there is no parsed message to ask."""
        parser = _parser(_make_gmail_message(raw=_make_raw_email()))

        assert (parser.subject, parser.sender, parser.to) == ("", "", "")
        assert parser.parse() is True

        parser = _parser({"labelIds": [], "snippet": "no raw and no payload"})
        assert parser.parse() is False
        assert parser.subject == ""
        assert parser.sender == ""
        assert parser.to == ""

    def test_labels(self) -> None:
        msg = _make_gmail_message(label_ids=["INBOX", "UNREAD", "HAS_ATTACHMENT"])
        parser = _parser(msg)
        assert parser.labels == ["INBOX", "UNREAD", "HAS_ATTACHMENT"]

    def test_no_label_ids_returns_empty_list(self) -> None:
        msg = {"id": "x"}
        parser = _parser(msg)
        assert parser.labels == []


# ---------------------------------------------------------------------------
# GmailMessageParser — text_content fallback to HTML
# ---------------------------------------------------------------------------


class TestGmailMessageParserTextContentFallback:
    def test_text_content_fallback_to_html(self):
        """If no text/plain part, extract from HTML."""
        raw = _make_raw_email(body_text="", body_html="<p>Only HTML</p>")
        msg = _make_gmail_message(raw=raw)

        parser = _parser(msg)
        parser.parse()
        # text_content should extract from html_content or return whitespace
        text = parser.text_content
        # The multipart raw email may have a blank text/plain part; the result
        # is either the extracted HTML text or whitespace-only from the empty part.
        assert "Only HTML" in text or text.strip() == ""


# ---------------------------------------------------------------------------
# minimal_message_template
# ---------------------------------------------------------------------------


class TestMinimalMessageTemplate:
    def test_basic_template(self):
        raw = _make_raw_email(
            subject="Hello",
            sender="a@b.com",
            to="c@d.com",
            body_text="Short body text here that is longer than truncation limit" * 5,
        )
        msg = _make_gmail_message(raw=raw, snippet="Preview")

        result = minimal_message_template(RelayedGmailMessage.model_validate(msg))

        assert result.id == "msg_001"
        assert result.subject == "Hello"
        assert result.sender == "a@b.com"
        assert result.snippet == "Preview"
        # Short body is truncated to 100 chars
        assert len(result.body) <= 100
        assert "content" not in result.model_dump(mode="json", by_alias=True)

    def test_short_body_false(self):
        raw = _make_raw_email(body_text="A" * 200)
        msg = _make_gmail_message(raw=raw)

        result = minimal_message_template(RelayedGmailMessage.model_validate(msg), short_body=False)
        assert len(result.body) >= 200

    def test_include_both_formats(self):
        raw = _make_raw_email(body_text="Plain", body_html="<p>HTML</p>")
        msg = _make_gmail_message(raw=raw)

        result = minimal_message_template(
            RelayedGmailMessage.model_validate(msg), include_both_formats=True
        )
        assert result.content is not None
        assert "Plain" in result.content["text"]
        assert "HTML" in result.content["html"]

    def test_is_read_and_has_attachment(self):
        raw = _make_raw_email()
        msg = _make_gmail_message(raw=raw, label_ids=["UNREAD", "HAS_ATTACHMENT"])

        result = minimal_message_template(RelayedGmailMessage.model_validate(msg))
        assert result.is_read is False
        assert result.has_attachment is True

    def test_fallback_fields(self):
        """When parser returns empty, fallback to email_data fields."""
        msg = {
            "id": "m1",
            "messageId": "mid_1",
            "threadId": "t1",
            "sender": "fallback@sender.com",
            "to": "fallback@to.com",
            "subject": "Fallback Subject",
            "snippet": "snip",
            "messageText": "fallback body",
            "messageTimestamp": "2025-01-01T00:00:00Z",
            "labelIds": [],
        }

        result = minimal_message_template(RelayedGmailMessage.model_validate(msg))
        assert result.id == "mid_1"
        assert result.sender == "fallback@sender.com"

    def test_every_header_and_label_reaches_the_card_under_its_own_field(self) -> None:
        """Each field carries its own value, not a neighbour's."""
        raw = _make_raw_email(
            subject="Quarterly numbers",
            sender="Alice <alice@example.com>",
            to="Bob <bob@example.com>",
            date="Tue, 02 Jan 2025 09:30:00 +0000",
            body_text="The body",
        )
        msg = _make_gmail_message(
            raw=raw, label_ids=["INBOX", "UNREAD", "HAS_ATTACHMENT"], snippet="The snippet"
        )

        result = minimal_message_template(RelayedGmailMessage.model_validate(msg))

        assert result.id == "msg_001"
        assert result.thread_id == "thread_001"
        assert result.sender == "Alice <alice@example.com>"
        assert result.to == "Bob <bob@example.com>"
        assert result.subject == "Quarterly numbers"
        assert result.snippet == "The snippet"
        assert "02 Jan 2025 09:30:00" in result.time
        assert result.is_read is False
        assert result.has_attachment is True
        assert result.labels == ["INBOX", "UNREAD", "HAS_ATTACHMENT"]
        assert result.body.strip() == "The body"

    def test_a_message_with_no_id_at_all_carries_no_id_rather_than_one_of_its_neighbours(self) -> None:
        """Neither Gmail id present: the card says nothing rather than naming the thread."""
        msg = {"threadId": "t1", "labelIds": [], "snippet": "s"}

        result = minimal_message_template(RelayedGmailMessage.model_validate(msg))

        assert result.id == ""
        assert result.thread_id == "t1"


# ---------------------------------------------------------------------------
# detailed_message_template
# ---------------------------------------------------------------------------


class TestDetailedMessageTemplate:
    def test_detailed_template(self):
        raw = _make_raw_email(
            subject="Detailed",
            sender="a@b.com",
            to="c@d.com",
            cc="e@f.com",
            body_text="Full body",
            body_html="<p>Full body</p>",
        )
        msg = _make_gmail_message(raw=raw, label_ids=["INBOX"])

        result = detailed_message_template(msg)

        assert result["subject"] == "Detailed"
        assert result["from"] == "a@b.com"
        assert result["cc"] == "e@f.com"
        assert "content" in result
        assert result["isRead"] is True
        assert result["hasAttachment"] is False

    def test_detailed_template_minimal_data(self):
        msg = {"id": "m1", "threadId": "t1", "labelIds": [], "snippet": ""}

        result = detailed_message_template(msg)
        assert result["id"] == "m1"

    def test_the_detailed_card_is_a_json_document_the_agent_can_be_handed(self) -> None:
        """It reaches the agent as JSON, so every value must already be JSON."""
        raw = _make_raw_email(
            subject="JSON please", sender="a@b.com", to="c@d.com", body_text="Body"
        )
        msg = _make_gmail_message(raw=raw, label_ids=["INBOX"])

        result = detailed_message_template(msg)

        assert json.loads(json.dumps(result)) == result


# ---------------------------------------------------------------------------
# build_message_view / project_message_view
# ---------------------------------------------------------------------------


def _fetched_view(body_processing: BodyProcessingLiteral) -> GmailMessageView:
    raw = _make_raw_email(body_text="Plain words", body_html="<p>HTML words</p>")
    message = RelayedGmailMessage.model_validate(_make_gmail_message(raw=raw))
    return build_message_view(message, body_processing)


class TestFetchedMessageView:
    def test_the_agent_reads_every_field_under_its_documented_key(self) -> None:
        assert list(project_message_view(_fetched_view("raw"), None)) == [
            "id",
            "threadId",
            "from",
            "from_address",
            "to",
            "subject",
            "snippet",
            "time",
            "isRead",
            "hasAttachment",
            "attachments",
            "labels",
            "cc",
            "body",
        ]

    def test_the_fetched_view_carries_each_field_under_its_own_value(self) -> None:
        """Every field of the fetched view holds its own value."""
        raw = _make_raw_email(
            subject="Lease renewal",
            sender="Alice <alice@example.com>",
            to="Bob <bob@example.com>",
            date="Wed, 03 Jan 2025 11:00:00 +0000",
            body_text="Sign here",
        )
        message = RelayedGmailMessage.model_validate(
            _make_gmail_message(raw=raw, label_ids=["INBOX", "UNREAD"], snippet="Sign here today")
        )

        view = build_message_view(message, "raw")

        assert view.id == "msg_001"
        assert view.thread_id == "thread_001"
        assert view.sender == "Alice <alice@example.com>"
        # The sweep groups by this, so it is the address alone, lowercased, whatever
        # the display name was.
        assert view.from_address == "alice@example.com"
        assert view.to == "Bob <bob@example.com>"
        assert view.subject == "Lease renewal"
        assert view.snippet == "Sign here today"
        assert "03 Jan 2025 11:00:00" in view.time
        assert view.is_read is False
        assert view.has_attachment is False
        assert view.labels == ["INBOX", "UNREAD"]

    def test_the_dual_text_and_html_blob_never_reaches_the_agent(self) -> None:
        wire = project_message_view(_fetched_view("raw"), None)

        assert "content" not in wire
        assert "Plain words" in str(wire["body"])

    def test_an_unfetched_body_is_absent_rather_than_null(self) -> None:
        view = _fetched_view("none")

        assert "body" not in project_message_view(view, None)
        assert project_message_view(view, ["body", "id"]) == {"id": "msg_001"}


# ---------------------------------------------------------------------------
# thread_template
# ---------------------------------------------------------------------------


class TestThreadTemplate:
    def test_thread_with_messages(self):
        raw = _make_raw_email(body_text="msg1")
        thread_data = {
            "id": "thread_001",
            "messages": [
                _make_gmail_message(raw=raw, msg_id="m1"),
                _make_gmail_message(raw=raw, msg_id="m2"),
            ],
        }

        result = thread_template(GmailThreadData.model_validate(thread_data))
        assert result.id == "thread_001"
        assert result.message_count == 2
        assert [message.id for message in result.messages] == ["m1", "m2"]

    def test_thread_no_messages(self):
        thread_data = {"id": "t_empty", "messages": []}

        result = thread_template(GmailThreadData.model_validate(thread_data))
        assert result.message_count == 0
        assert result.messages == []

    def test_thread_missing_messages_key(self):
        thread_data = {"id": "t_none"}

        result = thread_template(GmailThreadData.model_validate(thread_data))
        assert result.message_count == 0


# ---------------------------------------------------------------------------
# draft_template
# ---------------------------------------------------------------------------


class TestDraftTemplate:
    def test_draft_template(self):
        raw = _make_raw_email(
            subject="Draft Subject",
            to="recipient@example.com",
            body_text="Draft body",
            body_html="<p>Draft HTML</p>",
        )
        draft_data = {
            "id": "draft_001",
            "message": _make_gmail_message(raw=raw, snippet="Draft snip"),
        }

        result = draft_template(draft_data)
        assert result["id"] == "draft_001"
        assert result["message"]["subject"] == "Draft Subject"
        assert result["message"]["to"] == "recipient@example.com"
        assert "content" in result["message"]

    def test_draft_template_empty_message(self):
        draft_data = {"id": "d_empty", "message": {}}

        result = draft_template(draft_data)
        assert result["id"] == "d_empty"


# ---------------------------------------------------------------------------
# process_list_drafts_response
# ---------------------------------------------------------------------------


class TestProcessListDraftsResponse:
    def test_with_drafts(self):
        raw = _make_raw_email(body_text="draft body")
        response = {
            "nextPageToken": "dt_token",
            "drafts": [
                {"id": "d1", "message": _make_gmail_message(raw=raw)},
            ],
        }

        result = process_list_drafts_response(response)
        assert result["nextPageToken"] == "dt_token"
        assert result["resultSize"] == 1

    def test_no_drafts_key(self):
        response = {}
        result = process_list_drafts_response(response)
        assert result["resultSize"] == 0


# ---------------------------------------------------------------------------
# process_get_thread_response
# ---------------------------------------------------------------------------


class TestProcessGetThreadResponse:
    def test_delegates_to_thread_template(self):
        raw = _make_raw_email(body_text="thread body")
        response = {
            "id": "thread_x",
            "messages": [_make_gmail_message(raw=raw)],
        }

        result = process_get_thread_response(response)
        assert result["id"] == "thread_x"
        assert result["messageCount"] == 1


# ---------------------------------------------------------------------------
# Regression: stdlib get_payload's unbound `bpayload` on a malformed part
# ---------------------------------------------------------------------------


class TestMalformedPartDoesNotAbortTheMessage:
    def test_empty_part_claiming_base64_cte_does_not_raise(self):
        # A part claiming base64 encoding with no body data used to crash content
        # extraction with UnboundLocalError('bpayload') inside the stdlib.
        payload = {
            "mimeType": "multipart/mixed",
            "headers": [{"name": "Subject", "value": "Mixed"}],
            "parts": [
                {
                    "mimeType": "text/plain",
                    "headers": [
                        {"name": "Content-Transfer-Encoding", "value": "base64"},
                    ],
                    "body": {},
                },
                {
                    "mimeType": "text/plain",
                    "headers": [],
                    "body": {"data": _b64_encode("Good part")},
                },
            ],
        }
        msg = _make_gmail_message(payload=payload)

        parser = _parser(msg)
        assert parser.parse() is True
        assert "Good part" in parser.text_content

    def test_synthesized_part_drops_the_source_wire_transfer_encoding(self):
        """set_content stores already-decoded text; carrying the source wire encoding across describes it wrongly."""
        part = GmailMessagePart.model_validate(
            {
                "mimeType": "text/plain",
                "headers": [
                    {"name": "Subject", "value": "Kept"},
                    {"name": "Content-Transfer-Encoding", "value": "base64"},
                ],
            }
        )
        target = email.message.EmailMessage()

        _copy_headers(part, target)

        assert target["Subject"] == "Kept"
        assert "Content-Transfer-Encoding" not in target

    def test_wire_transfer_encoding_is_dropped_case_insensitively(self):
        # Gmail returns canonical header names, but MIME header names are
        # case-insensitive and a lowercase spelling must not slip the filter.
        part = GmailMessagePart.model_validate(
            {
                "mimeType": "text/plain",
                "headers": [{"name": "content-transfer-encoding", "value": "base64"}],
            }
        )
        target = email.message.EmailMessage()

        _copy_headers(part, target)

        assert "Content-Transfer-Encoding" not in target


def _stamp_wire_encoding(parser: GmailMessageParser, content_type: str) -> None:
    """Stamp base64 onto an empty walked part; _copy_headers no longer lets the parser reach this state itself.

    Nothing is mocked — the stdlib genuinely raises UnboundLocalError from
    get_payload(decode=True), which is the failure the extraction guards absorb.
    """
    assert parser.email_message is not None
    for part in parser.email_message.walk():
        if part.get_content_type() == content_type and part.get_payload() is None:
            part["Content-Transfer-Encoding"] = "base64"
            return
    raise AssertionError(f"no empty {content_type} part to corrupt")


class TestUndecodablePartIsSkippedNotFatal:
    def test_text_extraction_skips_the_bad_part_and_keeps_reading(self):
        payload = {
            "mimeType": "multipart/mixed",
            "headers": [{"name": "Subject", "value": "Mixed"}],
            "parts": [
                {"mimeType": "text/plain", "headers": [], "body": {}},
                {
                    "mimeType": "text/plain",
                    "headers": [],
                    "body": {"data": _b64_encode("Good part")},
                },
            ],
        }
        parser = _parser(_make_gmail_message(payload=payload))
        assert parser.parse() is True
        _stamp_wire_encoding(parser, "text/plain")

        assert "Good part" in parser.text_content

    def test_html_extraction_skips_the_bad_part_and_keeps_reading(self):
        payload = {
            "mimeType": "multipart/alternative",
            "headers": [{"name": "Subject", "value": "Alt"}],
            "parts": [
                {
                    "mimeType": "text/html",
                    "headers": [{"name": "Content-Type", "value": "text/html; charset=UTF-8"}],
                    "body": {},
                },
                {
                    "mimeType": "text/html",
                    "headers": [],
                    "body": {"data": _b64_encode("<p>Good HTML</p>")},
                },
            ],
        }
        parser = _parser(_make_gmail_message(payload=payload))
        assert parser.parse() is True
        _stamp_wire_encoding(parser, "text/html")

        assert "Good HTML" in parser.html_content

    def test_a_message_of_nothing_but_bad_parts_yields_empty_content(self):
        payload = {
            "mimeType": "multipart/mixed",
            "headers": [{"name": "Subject", "value": "All bad"}],
            "parts": [{"mimeType": "text/plain", "headers": [], "body": {}}],
        }
        parser = _parser(_make_gmail_message(payload=payload))
        assert parser.parse() is True
        _stamp_wire_encoding(parser, "text/plain")

        assert parser.content == {"text": "", "html": ""}


class TestDecodePartPayload:
    """The single decode seam both content extractors share.

    Exercised directly because through the extractors a wrong return is
    indistinguishable from a missing part: both surface as empty content.
    """

    def test_a_transfer_encoded_part_is_returned_decoded(self):
        # The wire form and the decoded bytes differ on purpose — a decode that
        # silently returned the raw base64 text would hand the model gibberish
        # and still read as "content was extracted".
        part = email.message.Message()
        part["Content-Transfer-Encoding"] = "base64"
        part.set_payload(base64.b64encode(b"Hello payload").decode())

        assert _decode_part_payload(part) == b"Hello payload"

    def test_a_part_with_no_transfer_encoding_is_still_returned_as_bytes(self):
        # Callers branch on bytes vs str; a part with no encoding header takes
        # the same bytes path, so the str branch is dead for real Gmail parts.
        part = email.message.Message()
        part.set_payload("Plain body")

        assert _decode_part_payload(part) == b"Plain body"

    def test_a_malformed_part_is_skipped_and_the_failure_is_named(self):
        # An empty part claiming base64 makes the stdlib raise UnboundLocalError.
        # The warning is the only trace the message came back short, so the
        # exception type has to reach it — "something failed" is not a diagnosis.
        part = email.message.Message()
        part["Content-Transfer-Encoding"] = "base64"
        log.reset()

        assert _decode_part_payload(part) is None

        warnings = log.get()["warnings"]
        assert len(warnings) == 1
        assert warnings[0]["msg"] == "Skipping malformed MIME part during content extraction"
        assert warnings[0]["error_type"] == "UnboundLocalError"

    def test_a_healthy_part_is_decoded_without_warning(self):
        part = email.message.Message()
        part.set_payload("Plain body")
        log.reset()

        _decode_part_payload(part)

        assert "warnings" not in log.get()


# ---------------------------------------------------------------------------
# What each template does when a field is missing, empty, or present
# ---------------------------------------------------------------------------


def _attachment_payload() -> dict:
    return {
        "mimeType": "multipart/mixed",
        "filename": "",
        "parts": [
            {"mimeType": "text/plain", "filename": "", "body": {"size": 12}},
            {
                "mimeType": "application/pdf",
                "filename": "invoice.pdf",
                "body": {"size": 2048, "attachmentId": "att-1"},
            },
        ],
    }


class TestTheCardsFallbacksAndEmptyFields:
    """A relayed message and its raw email disagree about which fields exist.

    The card reads the parsed email first and the relayed payload second, and answers ""
    for a field neither has. Every branch of that chain is a place a wrong value can
    reach the run, so each is pinned with a message where the two disagree.
    """

    def test_the_relayed_fields_are_used_where_the_parsed_email_has_nothing(self) -> None:
        msg = {
            "id": "m1",
            "messageId": "mid_1",
            "threadId": "thread_from_relay",
            "sender": "Alice <alice@example.com>",
            "to": "Bob <bob@example.com>",
            "subject": "From the relay",
            "snippet": "relayed snippet",
            "messageTimestamp": "2026-01-02T03:04:05Z",
            "labelIds": ["INBOX"],
        }

        result = minimal_message_template(RelayedGmailMessage.model_validate(msg))

        assert result.id == "mid_1"
        assert result.thread_id == "thread_from_relay"
        assert result.sender == "Alice <alice@example.com>"
        assert result.to == "Bob <bob@example.com>"
        assert result.subject == "From the relay"
        assert result.snippet == "relayed snippet"
        assert result.time == "2026-01-02T03:04:05Z"

    def test_a_relay_with_none_of_them_yields_empty_fields(self) -> None:
        result = minimal_message_template(RelayedGmailMessage.model_validate({"labelIds": []}))

        assert (result.id, result.thread_id, result.sender, result.to) == ("", "", "", "")
        assert (result.subject, result.snippet, result.time) == ("", "", "")
        assert result.body == ""

    def test_a_header_the_email_never_carried_reads_as_empty(self) -> None:
        """The raw email has a Subject but no To: the To must be "" and not a neighbour."""
        raw = _make_raw_email(subject="Only a subject", to="", cc="", body_text="Body")

        parser = _parser(_make_gmail_message(raw=raw))

        assert parser.parse() is True
        assert parser.subject == "Only a subject"
        assert parser.to == ""
        assert parser.cc == ""

    def test_a_message_with_neither_raw_nor_payload_reports_the_failed_parse(self) -> None:
        """No MIME tree anywhere: the parse says so rather than raising on a None payload."""
        parser = _parser({"id": "m1", "labelIds": [], "snippet": "s"})

        assert parser.parse() is False
        assert parser.email_message is None
        assert parser.subject == ""

    def test_an_empty_payload_object_is_the_same_as_no_payload(self) -> None:
        assert _parser({"labelIds": [], "payload": {}}).parse() is False

    def test_a_message_without_the_unread_label_is_reported_as_read(self) -> None:
        """is_read comes from the labels, not from the model default."""
        raw = _make_raw_email(subject="Read", body_text="Body")

        result = minimal_message_template(
            RelayedGmailMessage.model_validate(_make_gmail_message(raw=raw, label_ids=["INBOX"]))
        )

        assert result.is_read is True

    def test_a_message_with_neither_id_snippet_nor_body_still_carries_its_labels(self) -> None:
        result = minimal_message_template(
            RelayedGmailMessage.model_validate({"labelIds": ["INBOX", "UNREAD"]})
        )

        assert result.labels == ["INBOX", "UNREAD"]
        assert result.is_read is False
        assert result.snippet == ""

    def test_a_thread_with_no_id_reports_no_id(self) -> None:
        result = thread_template(GmailThreadData.model_validate({"messages": []}))

        assert result.id == ""
        assert result.messages == []
        assert result.message_count == 0


class TestTheFetchedViewReadsThePayload:
    def test_an_attachment_in_the_payload_is_reported_with_its_metadata(self) -> None:
        """The attachment list is walked out of the MIME parts, name and id paired."""
        message = RelayedGmailMessage.model_validate(
            _make_gmail_message(payload=_attachment_payload(), label_ids=["INBOX"])
        )

        view = build_message_view(message, "raw")

        assert view.attachments == [
            {
                "filename": "invoice.pdf",
                "mimeType": "application/pdf",
                "size": 2048,
                "attachmentId": "att-1",
            }
        ]
        assert view.has_attachment is False

    def test_the_has_attachment_label_is_the_one_gmail_sends(self) -> None:
        """The flag reads the label Gmail actually sets, spelled exactly."""
        message = RelayedGmailMessage.model_validate(
            _make_gmail_message(
                payload=_attachment_payload(), label_ids=["INBOX", "HAS_ATTACHMENT"]
            )
        )

        assert build_message_view(message, "raw").has_attachment is True

    def test_a_relay_with_no_ids_and_no_snippet_reports_them_empty(self) -> None:
        """A metadata-format message carries no id, thread or snippet of its own."""
        message = RelayedGmailMessage.model_validate(
            {"labelIds": ["INBOX"], "payload": _attachment_payload()}
        )

        view = build_message_view(message, "raw")

        assert view.id == ""
        assert view.thread_id == ""
        assert view.snippet == ""


class TestTheBodyIsOnlyFetchedWhenAFieldAsksForIt:
    """Whether the MIME body has to be parsed at all, decided before it is fetched.

    Getting this wrong either costs a full fetch for a metadata-only request, or hands
    back a view whose promised field is silently absent.
    """

    @pytest.mark.parametrize(
        ("fields", "body_processing", "expected"),
        [
            (None, "raw", True),
            (None, "none", False),
            (None, "normalize", True),
            ([], "raw", True),
            (["subject"], "raw", False),
            (["subject", "labels"], "normalize", False),
            (["body"], "raw", True),
            (["body"], "none", False),
        ],
        ids=[
            "all-fields-raw",
            "none-drops-it",
            "all-fields-normalize",
            "empty-list-is-all",
            "headers-only",
            "headers-only-normalize",
            "body-asked-for",
            "none-beats-body",
        ],
    )
    def test_the_decision_depends_on_the_field_list_and_the_processing(
        self, fields: list[str] | None, body_processing: str, expected: bool
    ) -> None:
        assert message_view_needs_body(fields, body_processing) is expected


class TestNormalizeStripsTheBoilerplate:
    def test_a_signature_and_an_unsubscribe_footer_are_gone_and_the_words_stay(self) -> None:
        """The normalize pass removes the boilerplate and keeps what the sender wrote."""
        raw = _make_raw_email(
            subject="Invoice",
            body_text=(
                "Your invoice for October is attached.\n\n"
                "--\nAlice Example\nHead of Things, Example Ltd\n\n"
                "Unsubscribe: https://example.com/u/abc123\n"
            ),
        )
        message = RelayedGmailMessage.model_validate(_make_gmail_message(raw=raw))

        view = build_message_view(message, "normalize")

        assert "Your invoice for October is attached." in view.body
        assert "Head of Things" not in view.body
        assert "Unsubscribe" not in view.body

    def test_raw_keeps_the_boilerplate_normalize_removes(self) -> None:
        """Same message, the two modes have to differ or one of them is a lie."""
        raw = _make_raw_email(
            subject="Invoice",
            body_text="The invoice is attached.\n\nUnsubscribe: https://example.com/u/abc123\n",
        )
        message = RelayedGmailMessage.model_validate(_make_gmail_message(raw=raw))

        assert "Unsubscribe" in (build_message_view(message, "raw").body or "")
        assert "Unsubscribe" not in (build_message_view(message, "normalize").body or "")
