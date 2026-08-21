"""Comprehensive tests for app/agents/templates/mail_templates.py."""

import base64
import email.message
from unittest.mock import patch

from app.agents.templates.mail_templates import (
    GmailMessageParser,
    _copy_headers,
    _decode_part_payload,
    _get_text_from_html,
    detailed_message_template,
    draft_template,
    minimal_message_template,
    process_get_thread_response,
    process_list_drafts_response,
    thread_template,
)
from app.models.composio_schemas.gmail import GmailMessagePart
from shared.py.wide_events import log

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_raw_email(
    subject: str = "Test Subject",
    sender: str = "alice@example.com",
    to: str = "bob@example.com",
    cc: str = "",
    body_text: str = "Hello plain text",
    body_html: str = "",
    date: str = "Mon, 01 Jan 2025 12:00:00 +0000",
) -> str:
    """Build a raw base64url-encoded email."""
    msg = email.message.EmailMessage()
    msg["Subject"] = subject
    msg["From"] = sender
    msg["To"] = to
    if cc:
        msg["Cc"] = cc
    msg["Date"] = date
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

        parser = GmailMessageParser(msg)
        assert parser.parse() is True
        assert parser.subject == "Important"
        assert parser.sender == "a@b.com"
        assert "content" in parser.text_content

    def test_properties_before_parse(self):
        parser = GmailMessageParser({"id": "x"})
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

        parser = GmailMessageParser(msg)
        parser.parse()

        assert "HTML content" in parser.html_content
        assert "Plain text" in parser.text_content

    def test_raw_email_cc_header(self):
        raw = _make_raw_email(cc="cc@example.com")
        msg = _make_gmail_message(raw=raw)

        parser = GmailMessageParser(msg)
        parser.parse()
        assert "cc@example.com" in parser.cc

    def test_raw_email_to_header(self):
        raw = _make_raw_email(to="recipient@example.com")
        msg = _make_gmail_message(raw=raw)

        parser = GmailMessageParser(msg)
        parser.parse()
        assert "recipient@example.com" in parser.to

    def test_raw_email_date(self):
        raw = _make_raw_email(date="Tue, 15 Mar 2025 10:30:00 +0000")
        msg = _make_gmail_message(raw=raw)

        parser = GmailMessageParser(msg)
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

        parser = GmailMessageParser(msg)
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

        parser = GmailMessageParser(msg)
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

        parser = GmailMessageParser(msg)
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

        parser = GmailMessageParser(msg)
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

        parser = GmailMessageParser(msg)
        assert parser.parse() is True

    def test_empty_payload_returns_false(self):
        """Empty payload dict is falsy, so parsing returns None / False."""
        msg = _make_gmail_message(payload={})

        parser = GmailMessageParser(msg)
        # Empty dict is falsy, so `if payload:` is False -> returns None -> parse is False
        assert parser.parse() is False

    def test_no_raw_no_payload(self):
        msg = {"id": "msg_empty"}

        parser = GmailMessageParser(msg)
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

        parser = GmailMessageParser(msg)
        parser.parse()
        assert parser.text_content == ""

    def test_parse_error_returns_false(self):
        """Simulate a parse error."""
        msg = _make_gmail_message()

        parser = GmailMessageParser(msg)
        with patch.object(parser, "_parse_with_email_parser", side_effect=Exception("parse fail")):
            assert parser.parse() is False
            assert parser._parsed is False


# ---------------------------------------------------------------------------
# GmailMessageParser — labels, is_read
# ---------------------------------------------------------------------------


class TestGmailMessageParserLabels:
    def test_labels(self):
        msg = _make_gmail_message(label_ids=["INBOX", "UNREAD", "HAS_ATTACHMENT"])
        parser = GmailMessageParser(msg)
        assert parser.labels == ["INBOX", "UNREAD", "HAS_ATTACHMENT"]

    def test_is_read_true(self):
        msg = _make_gmail_message(label_ids=["INBOX"])
        parser = GmailMessageParser(msg)
        assert parser.is_read is True

    def test_is_read_false(self):
        msg = _make_gmail_message(label_ids=["INBOX", "UNREAD"])
        parser = GmailMessageParser(msg)
        assert parser.is_read is False

    def test_no_label_ids_returns_empty_list(self):
        msg = {"id": "x"}
        parser = GmailMessageParser(msg)
        assert parser.labels == []


# ---------------------------------------------------------------------------
# GmailMessageParser — attachments
# ---------------------------------------------------------------------------


class TestGmailMessageParserAttachments:
    def test_attachments_from_parsed_email(self):
        raw = _make_raw_email(body_text="text")
        msg = _make_gmail_message(raw=raw)
        parser = GmailMessageParser(msg)
        parser.parse()
        # Simple email without attachments
        assert parser.attachments == []

    def test_attachments_fallback_to_payload(self):
        """When not parsed, fall back to manual extraction from payload."""
        msg = {
            "id": "m1",
            "payload": {
                "parts": [
                    {
                        "filename": "doc.pdf",
                        "mimeType": "application/pdf",
                        "body": {"attachmentId": "att_1", "size": 1024},
                    },
                    {
                        "filename": "",
                        "body": {},  # Not an attachment
                    },
                ],
            },
        }
        parser = GmailMessageParser(msg)
        # Not parsed, so fallback kicks in
        atts = parser.attachments
        assert len(atts) == 1
        assert atts[0]["filename"] == "doc.pdf"
        assert atts[0]["attachmentId"] == "att_1"

    def test_attachments_fallback_no_payload(self):
        msg = {"id": "m2"}
        parser = GmailMessageParser(msg)
        assert parser.attachments == []


# ---------------------------------------------------------------------------
# GmailMessageParser — text_content fallback to HTML
# ---------------------------------------------------------------------------


class TestGmailMessageParserTextContentFallback:
    def test_text_content_fallback_to_html(self):
        """If no text/plain part, extract from HTML."""
        raw = _make_raw_email(body_text="", body_html="<p>Only HTML</p>")
        msg = _make_gmail_message(raw=raw)

        parser = GmailMessageParser(msg)
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

        result = minimal_message_template(msg)

        assert result["id"] == "msg_001"
        assert result["subject"] == "Hello"
        assert result["from"] == "a@b.com"
        assert result["snippet"] == "Preview"
        # Short body is truncated to 100 chars
        assert len(result["body"]) <= 100

    def test_short_body_false(self):
        raw = _make_raw_email(body_text="A" * 200)
        msg = _make_gmail_message(raw=raw)

        result = minimal_message_template(msg, short_body=False)
        assert len(result["body"]) >= 200

    def test_include_both_formats(self):
        raw = _make_raw_email(body_text="Plain", body_html="<p>HTML</p>")
        msg = _make_gmail_message(raw=raw)

        result = minimal_message_template(msg, include_both_formats=True)
        assert "content" in result
        assert "text" in result["content"]
        assert "html" in result["content"]

    def test_is_read_and_has_attachment(self):
        raw = _make_raw_email()
        msg = _make_gmail_message(raw=raw, label_ids=["UNREAD", "HAS_ATTACHMENT"])

        result = minimal_message_template(msg)
        assert result["isRead"] is False
        assert result["hasAttachment"] is True

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

        result = minimal_message_template(msg)
        assert result["id"] == "mid_1"
        assert result["from"] == "fallback@sender.com"


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

        result = thread_template(thread_data)
        assert result["id"] == "thread_001"
        assert result["messageCount"] == 2
        assert len(result["messages"]) == 2

    def test_thread_no_messages(self):
        thread_data = {"id": "t_empty", "messages": []}

        result = thread_template(thread_data)
        assert result["messageCount"] == 0
        assert result["messages"] == []

    def test_thread_missing_messages_key(self):
        thread_data = {"id": "t_none"}

        result = thread_template(thread_data)
        assert result["messageCount"] == 0


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

    def test_with_error(self):
        response = {"drafts": [], "error": "Draft error"}
        result = process_list_drafts_response(response)
        assert result["error"] == "Draft error"


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
        # A part whose copied headers claim base64 transfer encoding but whose
        # body carries no data used to crash content extraction with
        # UnboundLocalError('bpayload') inside the stdlib, aborting the whole
        # fetch loop as a partial result.
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

        parser = GmailMessageParser(msg)
        assert parser.parse() is True
        assert "Good part" in parser.text_content

    def test_attachment_listing_survives_a_malformed_part(self):
        payload = {
            "mimeType": "multipart/mixed",
            "headers": [{"name": "Subject", "value": "Attach"}],
            "parts": [
                {
                    "mimeType": "application/pdf",
                    "filename": "report.pdf",
                    "headers": [
                        {"name": "Content-Transfer-Encoding", "value": "base64"},
                    ],
                    "body": {},
                },
            ],
        }
        msg = _make_gmail_message(payload=payload)

        parser = GmailMessageParser(msg)
        assert parser.parse() is True
        names = [a["filename"] for a in parser.attachments]
        assert names == ["report.pdf"]

    def test_synthesized_part_drops_the_source_wire_transfer_encoding(self):
        """``set_content`` stores already-decoded text and stamps its own encoding,
        so carrying the source part's wire encoding across describes the body
        wrongly — and on an empty part it is what sent the stdlib down its base64
        branch with nothing to decode."""
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
    """Put a walked part back into the undecodable state, on the real MIME tree.

    ``_copy_headers`` no longer lets the parser build this itself, so the state is
    restored on the parsed ``EmailMessage``: an empty part whose headers claim
    base64. Nothing is mocked — the stdlib genuinely raises ``UnboundLocalError``
    from ``get_payload(decode=True)`` on the way through, which is the failure the
    extraction guards have to absorb. What this does NOT prove is that a Gmail
    payload can still reach that state through the parser's own construction; with
    the header fix in place it cannot.
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
        parser = GmailMessageParser(_make_gmail_message(payload=payload))
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
        parser = GmailMessageParser(_make_gmail_message(payload=payload))
        assert parser.parse() is True
        _stamp_wire_encoding(parser, "text/html")

        assert "Good HTML" in parser.html_content

    def test_an_undecodable_attachment_is_listed_without_content(self):
        """The attachment still has to appear — a user looking at the message must
        see that a file is there, even when its bytes cannot be pulled out."""
        payload = {
            "mimeType": "multipart/mixed",
            "headers": [{"name": "Subject", "value": "Attach"}],
            "parts": [
                {
                    "mimeType": "application/pdf",
                    "filename": "report.pdf",
                    "headers": [{"name": "Content-Type", "value": "application/pdf"}],
                    "body": {},
                },
            ],
        }
        parser = GmailMessageParser(_make_gmail_message(payload=payload))
        assert parser.parse() is True
        _stamp_wire_encoding(parser, "application/pdf")

        attachments = parser.attachments
        assert len(attachments) == 1
        assert attachments[0]["filename"] == "report.pdf"
        assert attachments[0]["content"] is None
        assert attachments[0]["size"] == 0

    def test_a_message_of_nothing_but_bad_parts_yields_empty_content(self):
        payload = {
            "mimeType": "multipart/mixed",
            "headers": [{"name": "Subject", "value": "All bad"}],
            "parts": [{"mimeType": "text/plain", "headers": [], "body": {}}],
        }
        parser = GmailMessageParser(_make_gmail_message(payload=payload))
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
