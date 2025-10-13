"""Templates for mail-related tool responses."""

import base64
import email
import email.message
import email.parser
import email.policy
from html import unescape
from typing import Any, Dict, List, Optional

from app.config.loggers import app_logger as logger
from bs4 import BeautifulSoup

# ============================================================================
# GmailMessageParser - Class-based email parsing using email.parser
# ============================================================================


class GmailMessageParser:
    """
    A class to parse Gmail messages using Python's email library.
    Handles raw Gmail data and exposes clean methods for content extraction.
    """

    def __init__(self, gmail_message: dict):
        """
        Initialize parser with Gmail message data.

        Args:
            gmail_message (dict): Gmail API message object
        """
        self.gmail_message = gmail_message
        self.email_message: Optional[email.message.EmailMessage] = None
        self._parsed = False

    def parse(self) -> bool:
        """
        Parse the Gmail message using email.parser.

        Returns:
            bool: True if parsing succeeded, False otherwise
        """
        try:
            self.email_message = self._parse_with_email_parser()
            self._parsed = True
            return self.email_message is not None

        except Exception as e:
            logger.error(f"Error parsing email message: {e}")
            self._parsed = False
            return False

    def _parse_with_email_parser(self) -> Optional[email.message.EmailMessage]:
        """Parse Gmail message using manual parsing of payload structure."""
        # Try raw email data first (most reliable)
        raw_data = self.gmail_message.get("raw")
        if raw_data:
            raw_email_bytes = base64.urlsafe_b64decode(raw_data)
            parser = email.parser.BytesParser(policy=email.policy.default)
            return parser.parsebytes(raw_email_bytes)  # type: ignore

        # Manual parsing from payload structure
        payload = self.gmail_message.get("payload", {})
        if payload:
            return self._parse_payload_manually(payload)

        return None

    def _parse_payload_manually(
        self, payload: dict
    ) -> Optional[email.message.EmailMessage]:
        """Parse Gmail payload structure manually into EmailMessage."""
        msg = email.message.EmailMessage()

        # Set headers
        headers = payload.get("headers", [])
        for header in headers:
            name = header.get("name", "")
            value = header.get("value", "")
            if name and value:
                msg[name] = value

        # Handle body content based on mime type
        mime_type = payload.get("mimeType", "text/plain")

        if mime_type.startswith("multipart/"):
            # Handle multipart messages
            self._parse_multipart_payload(msg, payload)
        else:
            # Handle single part messages
            self._parse_single_part_payload(msg, payload)

        return msg

    def _parse_multipart_payload(self, msg: email.message.EmailMessage, payload: dict):
        """Parse multipart payload and attach parts to message."""
        parts = payload.get("parts", [])
        for part_data in parts:
            part_mime_type = part_data.get("mimeType", "text/plain")

            # Create a part message
            part = email.message.EmailMessage()
            # part.set_type(part_mime_type, requote=False)

            # Set part headers
            part_headers = part_data.get("headers", [])
            for header in part_headers:
                name = header.get("name", "")
                value = header.get("value", "")
                if name and value:
                    part[name] = value

            # Set part content
            if part_mime_type.startswith("multipart/"):
                # Recursive multipart
                self._parse_multipart_payload(part, part_data)
            else:
                # Single part content
                body_data = part_data.get("body", {}).get("data", "")
                if body_data:
                    try:
                        decoded_content = base64.urlsafe_b64decode(body_data).decode(
                            "utf-8", errors="ignore"
                        )
                        if part_mime_type == "text/html":
                            part.set_content(decoded_content, subtype="html")
                        else:
                            part.set_content(decoded_content)
                    except Exception:
                        part.set_content(body_data)

                # Handle attachments
                filename = part_data.get("filename")
                if filename:
                    # Remove existing Content-Disposition header if present
                    if "Content-Disposition" in part:
                        del part["Content-Disposition"]
                    part.add_header(
                        "Content-Disposition", "attachment", filename=filename
                    )

            # Attach part to main message
            msg.attach(part)

    def _parse_single_part_payload(
        self, msg: email.message.EmailMessage, payload: dict
    ):
        """Parse single part payload content."""
        body_data = payload.get("body", {}).get("data", "")
        mime_type = payload.get("mimeType", "text/plain")

        if body_data:
            try:
                decoded_content = base64.urlsafe_b64decode(body_data).decode(
                    "utf-8", errors="ignore"
                )
                if mime_type == "text/html":
                    msg.set_content(decoded_content, subtype="html")
                else:
                    msg.set_content(decoded_content)
            except Exception:
                msg.set_content(body_data)

    def _handle_composio_message(self):
        """Handle Composio message format."""
        content = self.gmail_message.get("message_text", "")
        # Create a simple email message for Composio data
        self.email_message = email.message.EmailMessage()
        if "<" in content and ">" in content:
            self.email_message.set_content("", subtype="html")
            self.email_message.set_payload(content)
        else:
            self.email_message.set_content(content)
        self._parsed = True

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
            content = self.gmail_message.get("message_text", "")
            if "<" in content and ">" in content:
                return _get_text_from_html(content)
            return content

        # Use email.parser walk method
        for part in self.email_message.walk():
            if part.get_content_type() == "text/plain":
                try:
                    return part.get_content()
                except Exception:
                    payload = part.get_payload(decode=True)
                    if isinstance(payload, bytes):
                        return payload.decode("utf-8", errors="ignore")
                    elif isinstance(payload, str):
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
            content = self.gmail_message.get("message_text", "")
            if "<" in content and ">" in content:
                return content
            return ""

        # Use email.parser walk method
        for part in self.email_message.walk():
            if part.get_content_type() == "text/html":
                try:
                    return part.get_content()
                except Exception:
                    payload = part.get_payload(decode=True)
                    if isinstance(payload, bytes):
                        return payload.decode("utf-8", errors="ignore")
                    elif isinstance(payload, str):
                        return payload

        return ""

    @property
    def content(self) -> dict:
        """Get both text and HTML content."""
        return {"text": self.text_content, "html": self.html_content}

    @property
    def attachments(self) -> List[dict]:
        """Get email attachments."""
        attachments = []

        if not self._parsed or not self.email_message:
            # Fallback to manual extraction for Gmail API
            parts = self.gmail_message.get("payload", {}).get("parts", [])
            for part in parts:
                if part.get("filename") and part.get("body", {}).get("attachmentId"):
                    attachments.append(
                        {
                            "filename": part.get("filename"),
                            "attachmentId": part.get("body", {}).get("attachmentId"),
                            "mimeType": part.get("mimeType"),
                            "size": part.get("body", {}).get("size"),
                            "messageId": self.gmail_message.get("id", ""),
                        }
                    )
            return attachments

        # Use email.parser for attachments
        for part in self.email_message.walk():
            if part.get_content_disposition() == "attachment":
                filename = part.get_filename()
                if filename:
                    attachments.append(
                        {
                            "filename": filename,
                            "mimeType": part.get_content_type(),
                            "size": len(part.get_payload(decode=True) or b""),
                            "messageId": self.gmail_message.get("id", ""),
                            "content": part.get_payload(decode=True),
                        }
                    )

        return attachments

    @property
    def labels(self) -> List[str]:
        """Get Gmail labels."""
        return self.gmail_message.get("labelIds", [])

    @property
    def is_read(self) -> bool:
        """Check if email is read."""
        return "UNREAD" not in self.labels

    @property
    def has_attachments(self) -> bool:
        """Check if email has attachments."""
        return len(self.attachments) > 0 or "HAS_ATTACHMENT" in self.labels


def _get_text_from_html(html_content):
    """Extract text from HTML content."""
    if not html_content:
        return ""

    soup = BeautifulSoup(unescape(html_content), "html.parser")
    return soup.get_text()


# Template for minimal message representation
def minimal_message_template(
    email_data: Dict[str, Any], short_body=True, include_both_formats=False
) -> Dict[str, Any]:
    """
    Convert a Gmail message to a minimal representation with only essential fields.

    Args:
        email_data: The full Gmail message data
        short_body: Whether to truncate body content to 100 characters
        include_both_formats: Whether to include both text and HTML content

    Returns:
        A dictionary with only the most essential email fields
    """
    # Use GmailMessageParser directly for efficiency
    parser = GmailMessageParser(email_data)
    parser.parse()

    content = parser.content if include_both_formats else None

    body_content = content["text"] if content else parser.text_content
    labels = parser.labels

    result = {
        "id": email_data.get("messageId") or email_data.get("id", ""),
        "threadId": email_data.get("threadId", ""),
        "from": parser.sender,
        "to": parser.to,
        "subject": parser.subject,
        "snippet": email_data.get("snippet", ""),
        "time": parser.date,
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
def detailed_message_template(email_data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Convert a Gmail message to a detailed but optimized representation including both text and HTML content.

    Args:
        email_data: The full Gmail message data

    Returns:
        A dictionary with the essential email fields plus body content in both formats
    """
    # Use GmailMessageParser directly for efficiency
    parser = GmailMessageParser(email_data)
    parser.parse()

    content = parser.content
    labels = parser.labels

    return {
        "id": email_data.get("messageId") or email_data.get("id", ""),
        "threadId": email_data.get("threadId", ""),
        "from": parser.sender,
        "to": parser.to,
        "subject": parser.subject,
        "snippet": email_data.get("snippet", ""),
        "time": parser.date,
        "isRead": "UNREAD" not in labels,
        "hasAttachment": "HAS_ATTACHMENT" in labels,
        "body": content["text"],  # Plain text for backward compatibility
        "labels": labels,
        "content": {"text": content["text"], "html": content["html"]},
        "cc": parser.cc,
    }


# Template for thread information
def thread_template(thread_data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Convert a Gmail thread to a minimal representation.

    Args:
        thread_data: The full Gmail thread data

    Returns:
        A dictionary with thread ID and minimized messages
    """
    return {
        "id": thread_data.get("id", ""),
        "messages": [
            minimal_message_template(msg, short_body=False, include_both_formats=True)
            for msg in thread_data.get("messages", [])
        ],
        "messageCount": len(thread_data.get("messages", [])),
    }


# Template for draft information
def draft_template(draft_data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Convert a Gmail draft to a minimal representation including both text and HTML content.

    Args:
        draft_data: The full Gmail draft data

    Returns:
        A dictionary with the essential draft fields including text and HTML content
    """
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


# Process tool responses
def process_list_messages_response(response: Dict[str, Any]) -> Dict[str, Any]:
    """Process the response from list_gmail_messages tool to minimize data."""
    processed_response = {
        "nextPageToken": response.get("nextPageToken"),
        "resultSize": len(response.get("messages", [])),
    }

    if "messages" in response:
        processed_response["messages"] = [
            minimal_message_template(msg) for msg in response.get("messages", [])
        ]

    if "error" in response:
        processed_response["error"] = response["error"]

    return processed_response


def process_list_drafts_response(response: Dict[str, Any]) -> Dict[str, Any]:
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


def process_get_thread_response(response: Dict[str, Any]) -> Dict[str, Any]:
    """Process the response from get_email_thread tool to minimize data."""
    return thread_template(response)
