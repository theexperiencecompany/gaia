"""Templates for mail-related tool responses."""

import base64
from collections.abc import Sequence
import email
import email.message
import email.parser
import email.policy
from html import unescape
from typing import Any, cast

from bs4 import BeautifulSoup

from app.constants.email import MessageFieldLiteral
from app.models.composio_schemas.gmail import (
    BodyProcessingLiteral,
    GmailAttachmentMetadata,
    GmailMessageContent,
    GmailMessagePart,
    GmailParsedAttachment,
)
from app.utils.email_body_normalizer import normalize_email_body
from shared.py.wide_events import log

# ============================================================================
# GmailMessageParser - Class-based email parsing using email.parser
# ============================================================================

# Gmail omits ``mimeType`` on some parts; RFC 2045 makes text/plain the default.
_DEFAULT_MIME_TYPE = "text/plain"
_HTML_MIME_TYPE = "text/html"


# The synthesized EmailMessage stores already-DECODED content (set_content
# manages its own transfer encoding), so the original part's wire encoding
# must not be copied: an empty part stamped "Content-Transfer-Encoding:
# base64" sends the stdlib's get_payload(decode=True) down its base64 branch
# with no payload, crashing on the unbound `bpayload` local (bpo-level quirk).
_WIRE_ENCODING_HEADER = "content-transfer-encoding"


def _copy_headers(part: GmailMessagePart, target: email.message.EmailMessage) -> None:
    """Copy a Gmail MIME part's headers onto an ``EmailMessage``, minus the
    transfer encoding set_content owns."""
    for header in part.headers:
        if header.name and header.value and header.name.lower() != _WIRE_ENCODING_HEADER:
            target[header.name] = header.value


def _set_decoded_content(
    target: email.message.EmailMessage, part: GmailMessagePart, mime_type: str
) -> None:
    """Decode a leaf part's base64url body onto ``target``, if it carries one."""
    body_data = part.body.data if part.body else None
    if not body_data:
        return
    try:
        decoded_content = base64.urlsafe_b64decode(body_data).decode("utf-8", errors="ignore")
        if mime_type == _HTML_MIME_TYPE:
            target.set_content(decoded_content, subtype="html")
        else:
            target.set_content(decoded_content)
    except Exception:
        target.set_content(body_data)


def _decode_part_payload(part: email.message.Message) -> bytes | str | None:
    """Decode a MIME part's raw payload, or None if the part is malformed.

    ``get_payload(decode=True)`` can raise on a malformed part (the stdlib's
    unbound-bpayload path) — callers should skip the part, not the whole message.
    """
    try:
        # decode=True only ever yields the leaf's decoded bytes (or the raw str
        # payload when no Content-Transfer-Encoding header is set) — the stdlib's
        # broader Message[str, str] return type is for the decode=False overload.
        return cast("bytes | str | None", part.get_payload(decode=True))
    except Exception as e:
        log.warning(
            "Skipping malformed MIME part during content extraction",
            error_type=type(e).__name__,
        )
        return None


class GmailMessageParser:
    """Parse Gmail messages via Python's email library, exposing clean
    content-extraction methods over raw Gmail API data."""

    def __init__(self, gmail_message: dict[str, Any]):
        """Initialize the parser with a Gmail API message object.

        ``gmail_message`` stays a raw mapping: this is the provider boundary and
        the same parser is handed both a Gmail REST message (``id`` / ``raw`` /
        ``payload``) and a Composio-shaped one (``messageId`` / ``message_text``),
        so the key set genuinely differs by source. The one nested structure that
        *is* a fixed schema — the MIME tree — is validated into
        ``GmailMessagePart`` before it is walked.
        """
        self.gmail_message = gmail_message
        self.email_message: email.message.EmailMessage | None = None
        self._parsed = False

    def parse(self) -> bool:
        """Parse the Gmail message. Returns True on success, False otherwise."""
        message_id = self.gmail_message.get("id") or self.gmail_message.get("messageId", "")
        log.set(gmail_message_id=message_id, mail_op="parse_gmail_message")
        try:
            self.email_message = self._parse_with_email_parser()
            self._parsed = True
            return self.email_message is not None

        except Exception as e:
            log.error("Error parsing email message", error_type=type(e).__name__)
            self._parsed = False
            return False

    def _parse_with_email_parser(self) -> email.message.EmailMessage | None:
        """Parse Gmail message using manual parsing of payload structure."""
        # Try raw email data first (most reliable)
        raw_data = self.gmail_message.get("raw")
        if raw_data:
            raw_email_bytes = base64.urlsafe_b64decode(raw_data)
            parser = email.parser.BytesParser(policy=email.policy.default)
            # BytesParser is typed as producing a plain Message; under
            # ``email.policy.default`` it always builds an EmailMessage.
            return cast("email.message.EmailMessage", parser.parsebytes(raw_email_bytes))

        # Manual parsing from payload structure
        payload = self.gmail_message.get("payload")
        if payload:
            return self._parse_payload_manually(GmailMessagePart.model_validate(payload))

        return None

    def _parse_payload_manually(
        self, payload: GmailMessagePart
    ) -> email.message.EmailMessage | None:
        """Parse Gmail payload structure manually into EmailMessage."""
        msg = email.message.EmailMessage()

        _copy_headers(payload, msg)

        # Handle body content based on mime type
        mime_type = payload.mime_type or _DEFAULT_MIME_TYPE

        if mime_type.startswith("multipart/"):
            # Handle multipart messages
            self._parse_multipart_payload(msg, payload)
        else:
            # Handle single part messages
            self._parse_single_part_payload(msg, payload)

        return msg

    def _parse_multipart_payload(
        self, msg: email.message.EmailMessage, payload: GmailMessagePart
    ) -> None:
        """Parse multipart payload and attach parts to message."""
        for part_data in payload.parts:
            part_mime_type = part_data.mime_type or _DEFAULT_MIME_TYPE

            # Create a part message
            part = email.message.EmailMessage()

            _copy_headers(part_data, part)

            # Set part content
            if part_mime_type.startswith("multipart/"):
                # Recursive multipart
                self._parse_multipart_payload(part, part_data)
            else:
                # Single part content
                _set_decoded_content(part, part_data, part_mime_type)

                # Handle attachments
                filename = part_data.filename
                if filename:
                    # Remove existing Content-Disposition header if present
                    if "Content-Disposition" in part:
                        del part["Content-Disposition"]
                    part.add_header("Content-Disposition", "attachment", filename=filename)

            # Attach part to main message
            msg.attach(part)

    def _parse_single_part_payload(
        self, msg: email.message.EmailMessage, payload: GmailMessagePart
    ) -> None:
        """Parse single part payload content."""
        _set_decoded_content(msg, payload, payload.mime_type or _DEFAULT_MIME_TYPE)

    # ========================================================================
    # Public getter methods
    # ========================================================================

    @property
    def subject(self) -> str:
        """Get email subject."""
        if not self._parsed or not self.email_message:
            return ""
        return self.email_message.get("Subject", "")

    @property
    def sender(self) -> str:
        """Get sender (From header)."""
        if not self._parsed or not self.email_message:
            return ""
        return self.email_message.get("From", "")

    @property
    def to(self) -> str:
        """Get recipients (To header)."""
        if not self._parsed or not self.email_message:
            return ""
        return self.email_message.get("To", "")

    @property
    def cc(self) -> str:
        """Get CC recipients."""
        if not self._parsed or not self.email_message:
            return ""
        return self.email_message.get("Cc", "")

    @property
    def date(self) -> str:
        """Get email date."""
        if not self._parsed or not self.email_message:
            return ""
        return self.email_message.get("Date", "")

    @property
    def text_content(self) -> str:
        """Get plain text content."""
        if not self._parsed or not self.email_message:
            return ""

        # Handle Composio messages
        if "message_text" in self.gmail_message:
            content: str = self.gmail_message.get("message_text", "")
            if "<" in content and ">" in content:
                return _get_text_from_html(content)
            return content

        # Use email.parser walk method
        for part in self.email_message.walk():
            if part.get_content_type() == "text/plain":
                try:
                    # A text/* part's content manager always yields str.
                    return cast(str, part.get_content())
                except Exception:
                    # get_payload itself can raise on a malformed part — skip
                    # the part, never the whole message.
                    payload = _decode_part_payload(part)
                    if payload is None:
                        continue
                    if isinstance(payload, bytes):
                        return payload.decode("utf-8", errors="ignore")
                    if isinstance(payload, str):
                        return payload

        # If no text/plain, extract from HTML
        html = self.html_content
        if html:
            return _get_text_from_html(html)

        return ""

    @property
    def html_content(self) -> str:
        """Get HTML content."""
        if not self._parsed or not self.email_message:
            return ""

        # Handle Composio messages
        if "message_text" in self.gmail_message:
            content: str = self.gmail_message.get("message_text", "")
            if "<" in content and ">" in content:
                return content
            return ""

        # Use email.parser walk method
        for part in self.email_message.walk():
            if part.get_content_type() == "text/html":
                try:
                    return cast(str, part.get_content())
                except Exception:
                    payload = _decode_part_payload(part)
                    if payload is None:
                        continue
                    if isinstance(payload, bytes):
                        return payload.decode("utf-8", errors="ignore")
                    if isinstance(payload, str):
                        return payload

        return ""

    @property
    def content(self) -> GmailMessageContent:
        """Get both text and HTML content."""
        return {"text": self.text_content, "html": self.html_content}

    @property
    def attachments(self) -> list[GmailParsedAttachment]:
        """Get email attachments."""
        attachments: list[GmailParsedAttachment] = []

        if not self._parsed or not self.email_message:
            # Fallback to manual extraction for Gmail API
            payload = GmailMessagePart.model_validate(self.gmail_message.get("payload") or {})
            for mime_part in payload.parts:
                body = mime_part.body
                if mime_part.filename and body and body.attachment_id:
                    attachments.append(
                        {
                            "filename": mime_part.filename,
                            "attachmentId": body.attachment_id,
                            "mimeType": mime_part.mime_type,
                            "size": body.size,
                            "messageId": self.gmail_message.get("id", ""),
                        }
                    )
            return attachments

        # Use email.parser for attachments
        for part in self.email_message.walk():
            if part.get_content_disposition() == "attachment":
                filename = part.get_filename()
                if filename:
                    # ``decode=True`` on a non-multipart part yields the decoded
                    # bytes (or None); typeshed's union also covers the multipart
                    # case, which an "attachment" disposition rules out.
                    try:
                        payload_bytes = cast("bytes | None", part.get_payload(decode=True))
                    except Exception:
                        # Malformed part — list the attachment without content.
                        payload_bytes = None
                    attachments.append(
                        {
                            "filename": filename,
                            "mimeType": part.get_content_type(),
                            "size": len(payload_bytes or b""),
                            "messageId": self.gmail_message.get("id", ""),
                            "content": payload_bytes,
                        }
                    )

        return attachments

    @property
    def labels(self) -> list[str]:
        """Get Gmail labels."""
        labels: list[str] = self.gmail_message.get("labelIds", [])
        return labels

    @property
    def is_read(self) -> bool:
        """Check if email is read."""
        return "UNREAD" not in self.labels


def _get_text_from_html(html_content: str | None) -> str:
    """Extract text from HTML content."""
    if not html_content:
        return ""

    soup = BeautifulSoup(unescape(html_content), "html.parser")
    return soup.get_text()


def _attachment_metadata(raw: dict[str, Any]) -> list[GmailAttachmentMetadata]:
    """Extract attachment metadata (no bytes) from a full-format Gmail payload.

    Walks the (possibly nested) MIME ``parts`` tree, returning one entry per
    part that has a filename and an ``attachmentId`` — the id the caller later
    passes to fetch the attachment content. Returns ``[]`` for a metadata-format
    message (no ``parts``), so the fetch requests ``format=full`` when the
    ``attachments`` field is selected.
    """
    out: list[GmailAttachmentMetadata] = []

    def walk(part: GmailMessagePart) -> None:
        body = part.body
        if part.filename and body and body.attachment_id:
            out.append(
                {
                    "filename": part.filename,
                    "mimeType": part.mime_type,
                    "size": body.size,
                    "attachmentId": body.attachment_id,
                }
            )
        for sub in part.parts:
            walk(sub)

    walk(GmailMessagePart.model_validate(raw.get("payload") or {}))
    return out


# Template for minimal message representation
def minimal_message_template(
    email_data: dict[str, Any],
    short_body: bool = True,
    include_both_formats: bool = False,
) -> dict[str, Any]:
    """Convert a Gmail message to a minimal representation with only essential
    fields. short_body truncates the body to 100 chars; include_both_formats
    adds text and HTML content."""
    # Use GmailMessageParser directly for efficiency
    parser = GmailMessageParser(email_data)
    parser.parse()

    content = parser.content if include_both_formats else None

    body_content = (content["text"] if content else parser.text_content) or email_data.get(
        "messageText", ""
    )
    labels = parser.labels

    result: dict[str, Any] = {
        "id": email_data.get("messageId") or email_data.get("id", ""),
        "threadId": email_data.get("threadId", ""),
        "from": parser.sender or email_data.get("sender", ""),
        "to": parser.to or email_data.get("to", ""),
        "subject": parser.subject or email_data.get("subject", ""),
        "snippet": email_data.get("snippet", ""),
        "time": parser.date or email_data.get("messageTimestamp", ""),
        "isRead": "UNREAD" not in labels,
        "hasAttachment": "HAS_ATTACHMENT" in labels,
        "body": body_content[:100] if short_body else body_content,
        "labels": labels,
    }

    # Add content formats if requested
    if include_both_formats and content:
        result["content"] = {
            "text": content["text"],
            "html": content["html"],
        }

    return result


# Template for message details (when a single message needs more detail)
def detailed_message_template(
    email_data: dict[str, Any], *, include_body: bool = True
) -> dict[str, Any]:
    """Convert a Gmail message to a detailed representation: essential fields
    plus body content in both text and HTML.

    ``include_body=False`` skips the MIME body extraction entirely (the view
    carries headers, labels, and snippet only) — use it when the body would be
    dropped anyway.
    """
    # Use GmailMessageParser directly for efficiency
    parser = GmailMessageParser(email_data)
    parser.parse()

    labels = parser.labels

    view: dict[str, Any] = {
        "id": email_data.get("messageId") or email_data.get("id", ""),
        "threadId": email_data.get("threadId", ""),
        "from": parser.sender,
        "to": parser.to,
        "subject": parser.subject,
        "snippet": email_data.get("snippet", ""),
        "time": parser.date,
        "isRead": "UNREAD" not in labels,
        "hasAttachment": "HAS_ATTACHMENT" in labels,
        "attachments": _attachment_metadata(email_data),
        "labels": labels,
        "cc": parser.cc,
    }
    if include_body:
        content = parser.content
        view["body"] = content["text"]  # Plain text for backward compatibility
        view["content"] = {"text": content["text"], "html": content["html"]}
    return view


# Template for thread information
def thread_template(thread_data: dict[str, Any]) -> dict[str, Any]:
    """Convert a Gmail thread to a minimal representation (thread ID + minimized
    messages)."""
    return {
        "id": thread_data.get("id", ""),
        "messages": [
            minimal_message_template(msg, short_body=False, include_both_formats=True)
            for msg in thread_data.get("messages", [])
        ],
        "messageCount": len(thread_data.get("messages", [])),
    }


# Template for draft information
def draft_template(draft_data: dict[str, Any]) -> dict[str, Any]:
    """Convert a Gmail draft to a minimal representation: essential fields plus
    text and HTML content."""
    message = draft_data.get("message", {})

    # Use GmailMessageParser directly for efficiency
    parser = GmailMessageParser(message)
    parser.parse()

    content = parser.content

    return {
        "id": draft_data.get("id", ""),
        "message": {
            "to": parser.to,
            "subject": parser.subject,
            "snippet": message.get("snippet", ""),
            "body": content["text"],  # Plain text for backward compatibility
            "content": {"text": content["text"], "html": content["html"]},
        },
    }


def message_view_needs_body(
    fields: Sequence[MessageFieldLiteral] | None, body_processing: BodyProcessingLiteral
) -> bool:
    """Whether a projected message view will carry a body.

    ``body`` is the only projectable field that requires the full MIME
    payload — everything else in ``build_message_view`` comes from headers,
    labels, and top-level metadata (so ``format=metadata`` suffices).
    """
    if body_processing == "none":
        return False
    # `None` or an empty list both mean "all documented fields", body included.
    return not fields or "body" in fields


def project_message_view(
    view: dict[str, Any], fields: Sequence[MessageFieldLiteral] | None
) -> dict[str, Any]:
    """Project a full message view to the requested fields.

    ``None`` or an empty ``fields`` list means "all fields" (view returned
    as-is).
    """
    if not fields:
        return view
    return {key: view[key] for key in fields if key in view}


# Process tool responses
def build_message_view(
    raw: dict[str, Any],
    fields: Sequence[MessageFieldLiteral] | None = None,
    body_processing: BodyProcessingLiteral = "none",
) -> dict[str, Any]:
    """Project a raw Gmail API message to only the requested fields.

    Single source of truth for per-message field selection. Used by
    ``GMAIL_FETCH_MESSAGES`` (caller-supplied fields + body processing
    mode). Body extraction/normalization is skipped entirely when the
    projected view won't carry a body (``message_view_needs_body``).

    Args:
        raw: Raw Gmail API message object (the same shape consumed by
            ``minimal_message_template`` and ``detailed_message_template``).
        fields: List of fields to include (from ``MessageFieldLiteral``).
            ``None`` or an empty list means "all documented fields". Pass a
            non-empty list to constrain the output.
        body_processing: One of ``"normalize"``, ``"raw"``, ``"none"``.
            ``"normalize"`` runs ``normalize_email_body`` over the body,
            which strips signatures / disclaimers / unsubscribe footers /
            utm tracking chains (quoted replies are kept). ``"raw"`` keeps
            the untouched body. ``"none"`` drops the body entirely,
            regardless of whether ``"body"`` is listed in ``fields``.
    """
    view = detailed_message_template(
        raw, include_body=message_view_needs_body(fields, body_processing)
    )

    # `content` is the detailed template's internal dual text/html blob; it is
    # not part of the field contract and would otherwise leak the full body
    # through the "all fields" path. Drop it.
    view.pop("content", None)

    if body_processing == "normalize" and view.get("body"):
        view["body"] = normalize_email_body(view["body"])

    return project_message_view(view, fields)


def process_list_drafts_response(response: dict[str, Any]) -> dict[str, Any]:
    """Process the response from list_email_drafts tool to minimize data."""
    processed_response = {
        "nextPageToken": response.get("nextPageToken"),
        "resultSize": len(response.get("drafts", [])),
    }

    if "drafts" in response:
        processed_response["drafts"] = [
            draft_template(draft) for draft in response.get("drafts", [])
        ]

    if "error" in response:
        processed_response["error"] = response["error"]

    return processed_response


def process_get_thread_response(response: dict[str, Any]) -> dict[str, Any]:
    """Process the response from get_email_thread tool to minimize data."""
    return thread_template(response)
