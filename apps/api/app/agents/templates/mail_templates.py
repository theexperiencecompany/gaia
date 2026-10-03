"""Templates for mail-related tool responses."""

import base64
from collections.abc import Mapping, Sequence
import email.message
import email.parser
import email.policy
from email.utils import parseaddr
from html import unescape
from typing import cast

from bs4 import BeautifulSoup

from app.constants.email import MessageFieldLiteral
from app.models.composio_schemas.gmail import (
    BodyProcessingLiteral,
    GmailAttachmentMetadata,
    GmailMessageContent,
    GmailMessagePart,
    GmailMessageView,
)
from app.models.integrations.gmail import (
    GmailDraftDetailData,
    GmailDraftListData,
    GmailDraftListView,
    GmailDraftView,
    GmailThreadData,
    GmailThreadMessageView,
    GmailThreadView,
)
from app.models.integrations.gmail_messages import RelayedGmailMessage
from app.utils.email_body_normalizer import normalize_email_body
from shared.py.wide_events import log

# ============================================================================
# GmailMessageParser - Class-based email parsing using email.parser
# ============================================================================

# Gmail omits ``mimeType`` on some parts; RFC 2045 makes text/plain the default.
_DEFAULT_MIME_TYPE = "text/plain"
_HTML_MIME_TYPE = "text/html"


# The synthesized EmailMessage stores already-DECODED content, so the
# original wire encoding must not be copied: an empty part stamped
# "Content-Transfer-Encoding: base64" crashes get_payload(decode=True).
_WIRE_ENCODING_HEADER = "content-transfer-encoding"


def _copy_headers(part: GmailMessagePart, target: email.message.EmailMessage) -> None:
    """Copy a Gmail MIME part's headers onto an EmailMessage, minus the transfer encoding set_content owns."""
    for header in part.headers:
        if header.name and header.value and header.name.lower() != _WIRE_ENCODING_HEADER:
            target[header.name] = header.value


def _set_decoded_content(
    target: email.message.EmailMessage, part: GmailMessagePart, mime_type: str
) -> None:
    """Decode a leaf part's base64url body onto target, if it carries one."""
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

    get_payload(decode=True) can raise on a malformed part (the stdlib's
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
    """Parse Gmail messages via Python's email library.

    Exposes clean content-extraction methods over raw Gmail API data.
    """

    def __init__(self, gmail_message: RelayedGmailMessage) -> None:
        self.gmail_message = gmail_message
        self.email_message: email.message.EmailMessage | None = None
        self._parsed = False

    def parse(self) -> bool:
        """Parse the Gmail message. Returns True on success, False otherwise."""
        message_id = self.gmail_message.id or self.gmail_message.message_id or ""
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
        raw_data = self.gmail_message.raw
        if raw_data:
            raw_email_bytes = base64.urlsafe_b64decode(raw_data)
            parser = email.parser.BytesParser(policy=email.policy.default)
            # BytesParser is typed as producing a plain Message; under
            # ``email.policy.default`` it always builds an EmailMessage.
            return cast("email.message.EmailMessage", parser.parsebytes(raw_email_bytes))

        # Manual parsing from payload structure
        payload = self.gmail_message.payload
        # An empty payload ({}) carries no MIME tree, so there is nothing to parse.
        if payload is not None and payload.model_fields_set:
            return self._parse_payload_manually(payload)

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

    def _header(self, name: str) -> str:
        """Return the named RFC 5322 header, or "" when it is absent or the parse failed."""
        if not self._parsed or not self.email_message:
            return ""
        return self.email_message.get(name, "")

    @property
    def subject(self) -> str:
        """Get email subject."""
        return self._header("Subject")

    @property
    def sender(self) -> str:
        """Get sender (From header)."""
        return self._header("From")

    @property
    def to(self) -> str:
        """Get recipients (To header)."""
        return self._header("To")

    @property
    def cc(self) -> str:
        """Get CC recipients."""
        return self._header("Cc")

    @property
    def date(self) -> str:
        """Get email date."""
        return self._header("Date")

    @property
    def text_content(self) -> str:
        """Get plain text content."""
        if not self._parsed or not self.email_message:
            return ""

        # Handle Composio messages
        content = self.gmail_message.snake_case_message_text
        if content is not None:
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
        if not self._parsed or not self.email_message:
            return ""

        # Handle Composio messages
        content = self.gmail_message.snake_case_message_text
        if content is not None:
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
    def labels(self) -> list[str]:
        """Get Gmail labels."""
        return self.gmail_message.label_ids or []


def _get_text_from_html(html_content: str | None) -> str:
    """Extract text from HTML content."""
    if not html_content:
        return ""

    soup = BeautifulSoup(unescape(html_content), "html.parser")
    return soup.get_text()


def _attachment_metadata(payload: GmailMessagePart | None) -> list[GmailAttachmentMetadata]:
    """Extract attachment metadata (no bytes) from a full-format Gmail payload.

    Walks the MIME parts tree, returning one entry per part with a filename
    and attachmentId. Returns [] for a metadata-format message (no parts).
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

    walk(payload or GmailMessagePart())
    return out


# Template for minimal message representation
def minimal_message_template(
    message: RelayedGmailMessage,
    short_body: bool = True,
    include_both_formats: bool = False,
) -> GmailThreadMessageView:
    """Convert a Gmail message to a minimal representation with only essential fields.

    short_body truncates the body to 100 chars; include_both_formats adds
    text and HTML content.
    """
    parser = GmailMessageParser(message)
    parser.parse()

    content: GmailMessageContent | None = parser.content if include_both_formats else None

    body_content = (
        (content["text"] if content else parser.text_content) or message.message_text or ""
    )
    labels = parser.labels

    return GmailThreadMessageView(
        id=message.message_id or message.id or "",
        thread_id=message.thread_id or "",
        sender=parser.sender or message.sender or "",
        to=parser.to or message.to or "",
        subject=parser.subject or message.subject or "",
        snippet=message.snippet or "",
        time=parser.date or message.message_timestamp or "",
        is_read="UNREAD" not in labels,
        has_attachment="HAS_ATTACHMENT" in labels,
        body=body_content[:100] if short_body else body_content,
        labels=labels,
        content=content,
    )


def _message_view(message: RelayedGmailMessage, *, include_body: bool) -> GmailMessageView:
    """Build the detailed view: essential fields, plus the body in text and HTML when include_body.

    include_body=False skips MIME body extraction entirely (headers, labels,
    snippet only) — use it when the body would be dropped anyway.
    """
    parser = GmailMessageParser(message)
    parser.parse()

    labels = parser.labels

    view = GmailMessageView(
        id=message.message_id or message.id or "",
        thread_id=message.thread_id or "",
        sender=parser.sender,
        from_address=parseaddr(parser.sender)[1].lower(),
        to=parser.to,
        subject=parser.subject,
        snippet=message.snippet or "",
        time=parser.date,
        is_read="UNREAD" not in labels,
        has_attachment="HAS_ATTACHMENT" in labels,
        attachments=_attachment_metadata(message.payload),
        labels=labels,
        cc=parser.cc,
    )
    if include_body:
        content: GmailMessageContent = parser.content
        view.body = content["text"]  # Plain text for backward compatibility
        view.content = content
    return view


def detailed_message_template(raw: Mapping[str, object]) -> dict[str, object]:
    """Convert a raw Gmail message to its detailed view, keyed as the agent reads it."""
    view = _message_view(RelayedGmailMessage.model_validate(raw), include_body=True)
    return view.model_dump(mode="json", by_alias=True)


def thread_template(thread: GmailThreadData) -> GmailThreadView:
    """Convert a Gmail thread to a minimal representation (thread ID + minimized messages)."""
    return GmailThreadView(
        id=thread.id or "",
        messages=[
            minimal_message_template(msg, short_body=False, include_both_formats=True)
            for msg in thread.messages
        ],
        message_count=len(thread.messages),
    )


def _draft_view(draft: GmailDraftDetailData) -> GmailDraftView:
    """Convert a Gmail draft to a minimal representation: essential fields plus text and HTML content."""
    message = draft.message or RelayedGmailMessage()

    # Use GmailMessageParser directly for efficiency
    parser = GmailMessageParser(message)
    parser.parse()

    content: GmailMessageContent = parser.content

    return {
        "id": draft.id or "",
        "message": {
            "to": parser.to,
            "subject": parser.subject,
            "snippet": message.snippet or "",
            "body": content["text"],  # Plain text for backward compatibility
            "content": content,
        },
    }


def draft_template(raw: Mapping[str, object]) -> GmailDraftView:
    """Convert a raw GMAIL_GET_DRAFT payload to its minimal draft view."""
    return _draft_view(GmailDraftDetailData.model_validate(raw))


def message_view_needs_body(
    fields: Sequence[MessageFieldLiteral] | None, body_processing: BodyProcessingLiteral
) -> bool:
    """Whether a projected message view will carry a body.

    body is the only projectable field that requires the full MIME
    payload — everything else in build_message_view comes from headers,
    labels, and top-level metadata (so format=metadata suffices).
    """
    if body_processing == "none":
        return False
    # `None` or an empty list both mean "all documented fields", body included.
    return not fields or "body" in fields


def project_message_view(
    view: GmailMessageView, fields: Sequence[MessageFieldLiteral] | None
) -> dict[str, object]:
    """Project a message view to the requested fields, keyed as the agent reads them.

    None or an empty fields list means "all fields".
    """
    wire = view.model_dump(mode="json", by_alias=True)
    if not fields:
        return wire
    return {key: wire[key] for key in fields if key in wire}


def build_message_view(
    message: RelayedGmailMessage, body_processing: BodyProcessingLiteral
) -> GmailMessageView:
    """Build the full view of a Gmail API message, for GMAIL_FETCH_MESSAGES and GMAIL_FETCH_THREAD.

    body_processing "normalize" strips signatures/disclaimers/unsubscribe
    footers/utm chains (quoted replies kept); "raw" keeps it untouched;
    "none" drops the body.
    """
    view = _message_view(message, include_body=body_processing != "none")

    # `content` is the detailed view's internal dual text/html blob; it is not
    # part of the field contract and would otherwise leak the full body
    # through the "all fields" path. Drop it.
    view.content = None

    if body_processing == "normalize" and view.body:
        view.body = normalize_email_body(view.body)

    return view


def process_list_drafts_response(raw: Mapping[str, object]) -> GmailDraftListView:
    """Process the response from list_email_drafts tool to minimize data."""
    response = GmailDraftListData.model_validate(raw)
    processed: GmailDraftListView = {
        "nextPageToken": response.next_page_token,
        "resultSize": len(response.drafts or []),
    }
    if response.drafts is not None:
        processed["drafts"] = [_draft_view(draft) for draft in response.drafts]
    return processed


def process_get_thread_response(raw: Mapping[str, object]) -> dict[str, object]:
    """Process the response from get_email_thread tool to minimize data."""
    thread = thread_template(GmailThreadData.model_validate(raw))
    return thread.model_dump(mode="json", by_alias=True)
