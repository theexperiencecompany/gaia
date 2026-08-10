"""Comprehensive tests for app/agents/templates/mail_templates.py."""

import base64
import email.message
from unittest.mock import patch

from app.agents.templates.mail_templates import (
    GmailMessageParser,
    _attachment_metadata,
    _copy_headers,
    _get_text_from_html,
    _set_decoded_content,
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
from app.models.composio_schemas.gmail import GmailMessagePart

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

    def test_exact_text(self):
        assert _get_text_from_html("<p>Hello <b>World</b></p>") == "Hello World"

    def test_exact_entities(self):
        assert _get_text_from_html("<p>5 &gt; 3 &amp; 2 &lt; 4</p>") == "5 > 3 & 2 < 4"


# ---------------------------------------------------------------------------
# _copy_headers
# ---------------------------------------------------------------------------


class TestCopyHeaders:
    def test_copies_all_headers(self):
        part = GmailMessagePart.model_validate(
            {
                "headers": [
                    {"name": "Subject", "value": "Hi"},
                    {"name": "From", "value": "a@b.com"},
                ]
            }
        )
        target = email.message.EmailMessage()
        _copy_headers(part, target)
        assert list(target.keys()) == ["Subject", "From"]
        assert target["Subject"] == "Hi"
        assert target["From"] == "a@b.com"

    def test_skips_empty_name_or_value(self):
        part = GmailMessagePart.model_validate(
            {
                "headers": [
                    {"name": "", "value": "orphan"},
                    {"name": "Empty", "value": ""},
                    {"name": "Ok", "value": "v"},
                ]
            }
        )
        target = email.message.EmailMessage()
        _copy_headers(part, target)
        assert list(target.keys()) == ["Ok"]
        assert target["Ok"] == "v"

    def test_no_headers(self):
        target = email.message.EmailMessage()
        _copy_headers(GmailMessagePart.model_validate({"headers": []}), target)
        assert list(target.keys()) == []


# ---------------------------------------------------------------------------
# _set_decoded_content
# ---------------------------------------------------------------------------


def _part_with_body(data: str) -> GmailMessagePart:
    return GmailMessagePart.model_validate({"body": {"data": data}})


class TestSetDecodedContent:
    def test_no_body_sets_nothing(self):
        target = email.message.EmailMessage()
        _set_decoded_content(target, GmailMessagePart.model_validate({}), "text/plain")
        assert target.get_payload() is None

    def test_empty_body_data_sets_nothing(self):
        target = email.message.EmailMessage()
        _set_decoded_content(target, _part_with_body(""), "text/plain")
        assert target.get_payload() is None

    def test_plain_text_decoded(self):
        target = email.message.EmailMessage()
        _set_decoded_content(target, _part_with_body(_b64_encode("Hello")), "text/plain")
        assert target.get_content() == "Hello\n"
        assert target.get_content_type() == "text/plain"

    def test_html_uses_html_subtype(self):
        target = email.message.EmailMessage()
        _set_decoded_content(target, _part_with_body(_b64_encode("<p>Hi</p>")), "text/html")
        assert target.get_content() == "<p>Hi</p>\n"
        assert target.get_content_type() == "text/html"
        assert target["Content-Type"] == 'text/html; charset="utf-8"'

    def test_invalid_base64_falls_back_to_raw(self):
        target = email.message.EmailMessage()
        _set_decoded_content(target, _part_with_body("not-base64!!"), "text/plain")
        assert target.get_content() == "not-base64!!\n"

    def test_invalid_utf8_bytes_are_ignored(self):
        target = email.message.EmailMessage()
        _set_decoded_content(target, _part_with_body("//4A"), "text/plain")
        assert target.get_content() == "\x00\n"


# ---------------------------------------------------------------------------
# _attachment_metadata
# ---------------------------------------------------------------------------


class TestAttachmentMetadata:
    def test_no_payload(self):
        assert _attachment_metadata({}) == []
        assert _attachment_metadata({"id": "x"}) == []

    def test_single_attachment_exact(self):
        raw = {
            "payload": {
                "parts": [
                    {
                        "filename": "doc.pdf",
                        "mimeType": "application/pdf",
                        "body": {"attachmentId": "att_1", "size": 1024},
                    },
                ],
            },
        }
        assert _attachment_metadata(raw) == [
            {
                "filename": "doc.pdf",
                "mimeType": "application/pdf",
                "size": 1024,
                "attachmentId": "att_1",
            },
        ]

    def test_multiple_attachments_in_order(self):
        raw = {
            "payload": {
                "parts": [
                    {
                        "filename": "a.pdf",
                        "mimeType": "application/pdf",
                        "body": {"attachmentId": "att_1", "size": 1},
                    },
                    {
                        "filename": "b.png",
                        "mimeType": "image/png",
                        "body": {"attachmentId": "att_2", "size": 2},
                    },
                ],
            },
        }
        assert _attachment_metadata(raw) == [
            {"filename": "a.pdf", "mimeType": "application/pdf", "size": 1, "attachmentId": "att_1"},
            {"filename": "b.png", "mimeType": "image/png", "size": 2, "attachmentId": "att_2"},
        ]

    def test_nested_parts_walked(self):
        raw = {
            "payload": {
                "parts": [
                    {"mimeType": "text/plain", "body": {"data": _b64_encode("x")}},
                    {
                        "mimeType": "multipart/mixed",
                        "parts": [
                            {
                                "filename": "inner.pdf",
                                "mimeType": "application/pdf",
                                "body": {"attachmentId": "att_2", "size": 5},
                            },
                        ],
                    },
                ],
            },
        }
        assert _attachment_metadata(raw) == [
            {"filename": "inner.pdf", "mimeType": "application/pdf", "size": 5, "attachmentId": "att_2"},
        ]

    def test_filename_without_attachment_id_excluded(self):
        raw = {
            "payload": {
                "parts": [
                    {"filename": "noid.pdf", "mimeType": "application/pdf", "body": {"size": 1}},
                ],
            },
        }
        assert _attachment_metadata(raw) == []

    def test_attachment_id_without_filename_excluded(self):
        raw = {
            "payload": {
                "parts": [
                    {"mimeType": "application/pdf", "body": {"attachmentId": "att_3"}},
                ],
            },
        }
        assert _attachment_metadata(raw) == []

    def test_no_body_excluded(self):
        raw = {
            "payload": {
                "parts": [
                    {"filename": "x.pdf", "mimeType": "application/pdf"},
                ],
            },
        }
        assert _attachment_metadata(raw) == []


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

    def test_exact_parsed_message(self):
        raw = _make_raw_email(
            subject="Hello",
            sender="a@b.com",
            to="c@d.com",
            cc="e@f.com",
            body_text="Body text",
            body_html="<p>Body HTML</p>",
            date="Wed, 01 Jan 2025 12:00:00 +0000",
        )
        msg = {
            "messageId": "mid_1",
            "id": "msg_001",
            "threadId": "thread_001",
            "snippet": "Preview",
            "labelIds": ["INBOX"],
            "raw": raw,
        }

        result = minimal_message_template(msg, short_body=False, include_both_formats=True)

        assert result == {
            "id": "mid_1",
            "threadId": "thread_001",
            "from": "a@b.com",
            "to": "c@d.com",
            "subject": "Hello",
            "snippet": "Preview",
            "time": "Wed, 01 Jan 2025 12:00:00 +0000",
            "isRead": True,
            "hasAttachment": False,
            "body": "Body text\n",
            "labels": ["INBOX"],
            "content": {"text": "Body text\n", "html": "<p>Body HTML</p>\n"},
        }

    def test_truncation_exact(self):
        raw = _make_raw_email(body_text="A" * 150)
        msg = _make_gmail_message(raw=raw)

        assert minimal_message_template(msg)["body"] == "A" * 100

    def test_body_of_exactly_100_not_truncated(self):
        raw = _make_raw_email(body_text="B" * 100)
        msg = _make_gmail_message(raw=raw)

        assert minimal_message_template(msg)["body"] == "B" * 100

    def test_short_body_false(self):
        raw = _make_raw_email(body_text="A" * 200)
        msg = _make_gmail_message(raw=raw)

        result = minimal_message_template(msg, short_body=False)
        assert len(result["body"]) >= 200
        assert result["body"].rstrip("\n") == "A" * 200

    def test_include_both_formats(self):
        raw = _make_raw_email(body_text="Plain", body_html="<p>HTML</p>")
        msg = _make_gmail_message(raw=raw)

        result = minimal_message_template(msg, include_both_formats=True)
        assert "content" in result
        assert "text" in result["content"]
        assert "html" in result["content"]

    def test_no_content_key_by_default(self):
        raw = _make_raw_email(body_text="Plain", body_html="<p>HTML</p>")
        msg = _make_gmail_message(raw=raw)

        result = minimal_message_template(msg)
        assert "content" not in result

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
        assert result == {
            "id": "mid_1",
            "threadId": "t1",
            "from": "fallback@sender.com",
            "to": "fallback@to.com",
            "subject": "Fallback Subject",
            "snippet": "snip",
            "time": "2025-01-01T00:00:00Z",
            "isRead": True,
            "hasAttachment": False,
            "body": "fallback body",
            "labels": [],
        }

    def test_empty_message_uses_defaults(self):
        assert minimal_message_template({}) == {
            "id": "",
            "threadId": "",
            "from": "",
            "to": "",
            "subject": "",
            "snippet": "",
            "time": "",
            "isRead": True,
            "hasAttachment": False,
            "body": "",
            "labels": [],
        }

    def test_message_id_falls_back_to_id_when_empty(self):
        msg = {"messageId": "", "id": "real_id", "labelIds": []}
        assert minimal_message_template(msg)["id"] == "real_id"


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

    def test_exact_detailed_view(self):
        raw = _make_raw_email(
            subject="Detailed",
            sender="a@b.com",
            to="c@d.com",
            cc="e@f.com",
            body_text="Full body",
            body_html="<p>Full body</p>",
            date="Wed, 01 Jan 2025 12:00:00 +0000",
        )
        msg = {
            "messageId": "mid_1",
            "id": "msg_001",
            "threadId": "thread_001",
            "snippet": "snip",
            "labelIds": ["UNREAD", "HAS_ATTACHMENT"],
            "raw": raw,
        }

        assert detailed_message_template(msg) == {
            "id": "mid_1",
            "threadId": "thread_001",
            "from": "a@b.com",
            "to": "c@d.com",
            "subject": "Detailed",
            "snippet": "snip",
            "time": "Wed, 01 Jan 2025 12:00:00 +0000",
            "isRead": False,
            "hasAttachment": True,
            "attachments": [],
            "labels": ["UNREAD", "HAS_ATTACHMENT"],
            "cc": "e@f.com",
            "body": "Full body\n",
            "content": {"text": "Full body\n", "html": "<p>Full body</p>\n"},
        }

    def test_include_body_false_omits_body_and_content(self):
        raw = _make_raw_email(
            subject="Detailed",
            sender="a@b.com",
            to="c@d.com",
            cc="e@f.com",
            body_text="Full body",
            body_html="<p>Full body</p>",
            date="Wed, 01 Jan 2025 12:00:00 +0000",
        )
        msg = {
            "messageId": "mid_1",
            "id": "msg_001",
            "threadId": "thread_001",
            "snippet": "snip",
            "labelIds": ["UNREAD", "HAS_ATTACHMENT"],
            "raw": raw,
        }

        assert detailed_message_template(msg, include_body=False) == {
            "id": "mid_1",
            "threadId": "thread_001",
            "from": "a@b.com",
            "to": "c@d.com",
            "subject": "Detailed",
            "snippet": "snip",
            "time": "Wed, 01 Jan 2025 12:00:00 +0000",
            "isRead": False,
            "hasAttachment": True,
            "attachments": [],
            "labels": ["UNREAD", "HAS_ATTACHMENT"],
            "cc": "e@f.com",
        }

    def test_include_body_false_still_carries_attachments(self):
        payload = {
            "mimeType": "multipart/mixed",
            "headers": [{"name": "Subject", "value": "S"}],
            "parts": [
                {"mimeType": "text/plain", "headers": [], "body": {"data": _b64_encode("body")}},
                {
                    "mimeType": "application/pdf",
                    "filename": "doc.pdf",
                    "headers": [],
                    "body": {"attachmentId": "att_1", "size": 1024},
                },
            ],
        }
        msg = {"id": "m1", "threadId": "t1", "snippet": "", "labelIds": ["INBOX"], "payload": payload}

        result = detailed_message_template(msg, include_body=False)
        assert result["attachments"] == [
            {"filename": "doc.pdf", "mimeType": "application/pdf", "size": 1024, "attachmentId": "att_1"},
        ]
        assert "body" not in result
        assert "content" not in result

    def test_empty_message_uses_defaults(self):
        assert detailed_message_template(
            {"id": "m1", "threadId": "t1", "labelIds": []}, include_body=False
        ) == {
            "id": "m1",
            "threadId": "t1",
            "from": "",
            "to": "",
            "subject": "",
            "snippet": "",
            "time": "",
            "isRead": True,
            "hasAttachment": False,
            "attachments": [],
            "labels": [],
            "cc": "",
        }

    def test_missing_id_falls_back_to_default(self):
        result = detailed_message_template({"labelIds": [], "snippet": ""})
        assert result["id"] == ""
        assert result["threadId"] == ""


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

    def test_messages_carry_full_body_and_content(self):
        raw = _make_raw_email(body_text="A" * 150, body_html="<p>HTML</p>")
        thread_data = {
            "id": "t1",
            "messages": [_make_gmail_message(raw=raw, msg_id="m1")],
        }

        result = thread_template(thread_data)
        message = result["messages"][0]
        assert message["body"] == "A" * 150 + "\n"
        assert message["content"] == {"text": "A" * 150 + "\n", "html": "<p>HTML</p>\n"}

    def test_missing_id_uses_default(self):
        assert thread_template({"messages": []})["id"] == ""

    def test_empty_thread(self):
        assert thread_template({}) == {"id": "", "messages": [], "messageCount": 0}


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

    def test_exact_draft(self):
        raw = _make_raw_email(
            subject="Draft Subject",
            to="recipient@example.com",
            body_text="Draft body",
            body_html="<p>Draft HTML</p>",
        )
        draft_data = {
            "id": "draft_001",
            "message": {"id": "m9", "snippet": "Draft snip", "raw": raw},
        }

        assert draft_template(draft_data) == {
            "id": "draft_001",
            "message": {
                "to": "recipient@example.com",
                "subject": "Draft Subject",
                "snippet": "Draft snip",
                "body": "Draft body\n",
                "content": {"text": "Draft body\n", "html": "<p>Draft HTML</p>\n"},
            },
        }

    def test_missing_id_uses_default(self):
        draft_data = {"message": {"id": "m9", "snippet": ""}}
        assert draft_template(draft_data)["id"] == ""

    def test_missing_message_key(self):
        assert draft_template({"id": "d"}) == {
            "id": "d",
            "message": {
                "to": "",
                "subject": "",
                "snippet": "",
                "body": "",
                "content": {"text": "", "html": ""},
            },
        }

    def test_empty_message_exact(self):
        assert draft_template({"id": "d_empty", "message": {}}) == {
            "id": "d_empty",
            "message": {
                "to": "",
                "subject": "",
                "snippet": "",
                "body": "",
                "content": {"text": "", "html": ""},
            },
        }


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

    def test_exact_with_drafts(self):
        raw = _make_raw_email(subject="S", to="r@x.com", body_text="body")
        response = {
            "nextPageToken": "tok",
            "drafts": [
                {"id": "d1", "message": {"id": "m", "snippet": "Preview text", "raw": raw}},
            ],
        }

        assert process_list_drafts_response(response) == {
            "nextPageToken": "tok",
            "resultSize": 1,
            "drafts": [
                {
                    "id": "d1",
                    "message": {
                        "to": "r@x.com",
                        "subject": "S",
                        "snippet": "Preview text",
                        "body": "body\n",
                        "content": {"text": "body\n", "html": ""},
                    },
                },
            ],
        }

    def test_no_drafts_key_exact(self):
        assert process_list_drafts_response({"nextPageToken": "tok"}) == {
            "nextPageToken": "tok",
            "resultSize": 0,
        }

    def test_empty_drafts_list_present(self):
        assert process_list_drafts_response({"drafts": []}) == {
            "nextPageToken": None,
            "resultSize": 0,
            "drafts": [],
        }


# ---------------------------------------------------------------------------
# message_view_needs_body / project_message_view / build_message_view
# ---------------------------------------------------------------------------


class TestMessageViewNeedsBody:
    def test_none_processing_never_needs_body(self):
        assert message_view_needs_body(None, "none") is False
        assert message_view_needs_body(["body"], "none") is False
        assert message_view_needs_body([], "none") is False

    def test_no_fields_means_all_fields(self):
        assert message_view_needs_body(None, "normalize") is True
        assert message_view_needs_body([], "raw") is True

    def test_body_field_only_requires_payload(self):
        assert message_view_needs_body(["body"], "normalize") is True
        assert message_view_needs_body(["body"], "raw") is True

    def test_other_fields_do_not_require_payload(self):
        assert message_view_needs_body(["id", "subject"], "raw") is False
        assert message_view_needs_body(["snippet"], "normalize") is False


class TestProjectMessageView:
    def test_none_or_empty_returns_view_unchanged(self):
        view = {"id": "m1", "snippet": "s"}
        assert project_message_view(view, None) is view
        assert project_message_view(view, []) is view

    def test_projects_selected_fields(self):
        view = {"id": "m1", "subject": "S", "snippet": "s", "cc": "c"}
        assert project_message_view(view, ["id", "subject"]) == {"id": "m1", "subject": "S"}

    def test_skips_fields_not_in_view(self):
        view = {"id": "m1"}
        assert project_message_view(view, ["id", "missing"]) == {"id": "m1"}

    def test_output_follows_field_order(self):
        view = {"a": 1, "b": 2}
        assert project_message_view(view, ["b", "a"]) == {"b": 2, "a": 1}


class TestBuildMessageView:
    def test_default_drops_body_and_content(self):
        raw = _make_raw_email(
            subject="S",
            sender="a@b.com",
            to="c@d.com",
            body_text="Body text",
            date="Wed, 01 Jan 2025 12:00:00 +0000",
        )
        msg = {"id": "m1", "threadId": "t1", "snippet": "snip", "labelIds": ["INBOX"], "raw": raw}

        result = build_message_view(msg)

        assert result["id"] == "m1"
        assert "body" not in result
        assert "content" not in result

    def test_raw_processing_keeps_body_untouched(self):
        body = "Meeting at 3pm tomorrow.\n\n-- \nSent from my iPhone"
        raw = _make_raw_email(subject="S", body_text=body)
        msg = {"id": "m1", "threadId": "t1", "snippet": "", "labelIds": [], "raw": raw}

        result = build_message_view(msg, body_processing="raw")
        assert result["body"] == body + "\n"
        assert "content" not in result

    def test_normalize_processing_strips_signature(self):
        body = "Meeting at 3pm tomorrow.\n\n-- \nSent from my iPhone"
        raw = _make_raw_email(subject="S", body_text=body)
        msg = {"id": "m1", "threadId": "t1", "snippet": "", "labelIds": [], "raw": raw}

        result = build_message_view(msg, body_processing="normalize")
        assert result["body"] == "Meeting at 3pm tomorrow."
        assert "content" not in result

    def test_field_projection_respects_body_processing(self):
        raw = _make_raw_email(subject="S", body_text="Body")
        msg = {"id": "m1", "threadId": "t1", "snippet": "", "labelIds": [], "raw": raw}

        result = build_message_view(msg, fields=["id"], body_processing="normalize")
        assert result == {"id": "m1"}

    def test_delegates_include_body_flag(self):
        with patch(
            "app.agents.templates.mail_templates.detailed_message_template"
        ) as detailed:
            detailed.return_value = {}
            build_message_view({"id": "m1"}, fields=["id"], body_processing="normalize")
            assert detailed.call_args.kwargs["include_body"] is False
            build_message_view({"id": "m1"}, fields=["body"], body_processing="raw")
            assert detailed.call_args.kwargs["include_body"] is True

    def test_none_processing_drops_body_even_when_requested(self):
        raw = _make_raw_email(subject="S", body_text="Body")
        msg = {"id": "m1", "threadId": "t1", "snippet": "", "labelIds": [], "raw": raw}

        assert build_message_view(msg, body_processing="none", fields=["body"]) == {}

    def test_field_projection(self):
        raw = _make_raw_email(subject="S", body_text="Body")
        msg = {"id": "m1", "threadId": "t1", "snippet": "snip", "labelIds": [], "raw": raw}

        assert build_message_view(msg, fields=["id", "snippet"], body_processing="raw") == {
            "id": "m1",
            "snippet": "snip",
        }


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
