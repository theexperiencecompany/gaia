"""Gmail custom tools using Composio custom tool infrastructure.

All HTTP calls are synchronous using httpx.Client to avoid event loop issues.
"""

import base64
from email.mime.text import MIMEText
from typing import Any, Dict, List, Optional

import httpx
from composio import Composio
from pydantic import BaseModel, Field

# Reusable sync HTTP client
_http_client = httpx.Client(timeout=30)


def _auth_headers(auth_credentials: Dict[str, Any]) -> Dict[str, str]:
    """Return Bearer token header for Gmail API.

    ``auth_credentials`` is provided by Composio and contains ``access_token``.
    """
    token = auth_credentials.get("access_token")
    if not token:
        raise ValueError("Missing access_token in auth_credentials")
    return {"Authorization": f"Bearer {token}"}


class MarkAsReadInput(BaseModel):
    """Input for marking emails as read."""

    message_ids: List[str] = Field(
        ...,
        description="List of Gmail message IDs to mark as read",
    )


class MarkAsUnreadInput(BaseModel):
    """Input for marking emails as unread."""

    message_ids: List[str] = Field(
        ...,
        description="List of Gmail message IDs to mark as unread",
    )


class ArchiveEmailInput(BaseModel):
    """Input for archiving emails."""

    message_ids: List[str] = Field(
        ...,
        description="List of Gmail message IDs to archive (remove from inbox)",
    )


class StarEmailInput(BaseModel):
    """Input for starring/unstarring emails."""

    message_ids: List[str] = Field(
        ...,
        description="List of Gmail message IDs to star or unstar",
    )
    unstar: bool = Field(
        default=False,
        description="If True, remove star instead of adding it",
    )


class GetUnreadCountInput(BaseModel):
    """Input for getting unread email count."""

    label_id: str = Field(
        default="INBOX",
        description="Label ID to count unread emails in (default: INBOX)",
    )


class ScheduleSendInput(BaseModel):
    """Input for scheduling an email to send later."""

    recipient_email: str = Field(
        ...,
        description="Email address of the recipient",
    )
    subject: str = Field(
        ...,
        description="Subject line of the email",
    )
    body: str = Field(
        ...,
        description="Body content of the email",
    )
    send_at: str = Field(
        ...,
        description="ISO 8601 timestamp for when to send (e.g., '2024-01-15T10:00:00Z')",
    )
    cc: Optional[str] = Field(
        default=None,
        description="CC email addresses (comma-separated)",
    )
    bcc: Optional[str] = Field(
        default=None,
        description="BCC email addresses (comma-separated)",
    )


def register_gmail_custom_tools(composio: Composio):
    """
    Register custom Gmail tools with the Composio client.

    These tools provide user-friendly wrappers around Gmail's label-based
    operations for common email actions.

    Args:
        composio: The Composio client instance

    Returns:
        List of registered tool names
    """

    @composio.tools.custom_tool(toolkit="gmail")
    def MARK_AS_READ(
        request: MarkAsReadInput,
        execute_request: Any,
        auth_credentials: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Mark Gmail messages as read.

        Removes the UNREAD label from specified messages, marking them as read
        in the user's inbox.

        Args:
            request.message_ids: List of Gmail message IDs to mark as read

        Returns:
            Dict with success status and API response data
        """
        url = "https://gmail.googleapis.com/gmail/v1/users/me/messages/batchModify"
        payload = {"ids": request.message_ids, "removeLabelIds": ["UNREAD"]}
        resp = _http_client.post(
            url, json=payload, headers=_auth_headers(auth_credentials)
        )
        resp.raise_for_status()
        return {"success": True, "data": resp.json()}

    @composio.tools.custom_tool(toolkit="gmail")
    def MARK_AS_UNREAD(
        request: MarkAsUnreadInput,
        execute_request: Any,
        auth_credentials: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Mark Gmail messages as unread.

        Adds the UNREAD label to specified messages, making them appear
        unread in the user's inbox.

        Args:
            request.message_ids: List of Gmail message IDs to mark as unread

        Returns:
            Dict with success status and API response data
        """
        url = "https://gmail.googleapis.com/gmail/v1/users/me/messages/batchModify"
        payload = {"ids": request.message_ids, "addLabelIds": ["UNREAD"]}
        resp = _http_client.post(
            url, json=payload, headers=_auth_headers(auth_credentials)
        )
        resp.raise_for_status()
        return {"success": True, "data": resp.json()}

    @composio.tools.custom_tool(toolkit="gmail")
    def ARCHIVE_EMAIL(
        request: ArchiveEmailInput,
        execute_request: Any,
        auth_credentials: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Archive Gmail messages.

        Removes the INBOX label from specified messages, moving them
        to the archive (All Mail) where they remain accessible but
        no longer appear in the inbox.

        Args:
            request.message_ids: List of Gmail message IDs to archive

        Returns:
            Dict with success status and API response data
        """
        url = "https://gmail.googleapis.com/gmail/v1/users/me/messages/batchModify"
        payload = {"ids": request.message_ids, "removeLabelIds": ["INBOX"]}
        resp = _http_client.post(
            url, json=payload, headers=_auth_headers(auth_credentials)
        )
        resp.raise_for_status()
        return {"success": True, "data": resp.json()}

    @composio.tools.custom_tool(toolkit="gmail")
    def STAR_EMAIL(
        request: StarEmailInput,
        execute_request: Any,
        auth_credentials: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Star or unstar Gmail messages.

        Adds or removes the STARRED label from specified messages.
        Starred messages appear in the Starred folder.

        Args:
            request.message_ids: List of Gmail message IDs to star/unstar
            request.unstar: If True, remove star; if False (default), add star

        Returns:
            Dict with success status, action taken, and API response data
        """
        url = "https://gmail.googleapis.com/gmail/v1/users/me/messages/batchModify"
        if request.unstar:
            payload = {"ids": request.message_ids, "removeLabelIds": ["STARRED"]}
            action = "unstarred"
        else:
            payload = {"ids": request.message_ids, "addLabelIds": ["STARRED"]}
            action = "starred"
        resp = _http_client.post(
            url, json=payload, headers=_auth_headers(auth_credentials)
        )
        resp.raise_for_status()
        return {"success": True, "action": action, "data": resp.json()}

    @composio.tools.custom_tool(toolkit="gmail")
    def GET_UNREAD_COUNT(
        request: GetUnreadCountInput,
        execute_request: Any,
        auth_credentials: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Get the unread email count for a Gmail label.

        Returns the number of unread messages in the specified label.
        Defaults to INBOX if no label is specified.

        Args:
            request.label_id: Label ID to count unread emails in (default: INBOX)

        Returns:
            Dict with success status, unread count, label_id, and label_name
        """
        url = (
            f"https://gmail.googleapis.com/gmail/v1/users/me/labels/{request.label_id}"
        )

        resp = _http_client.get(url, headers=_auth_headers(auth_credentials))
        resp.raise_for_status()
        data = resp.json()
        return {
            "success": True,
            "unreadCount": data.get("messagesUnread"),
            "label_id": request.label_id,
            "label_name": data.get("name", request.label_id),
        }

    @composio.tools.custom_tool(toolkit="gmail")
    def SCHEDULE_SEND(
        request: ScheduleSendInput,
        execute_request: Any,
        auth_credentials: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Schedule an email to be sent later.

        Creates a draft with scheduling metadata. The draft is stored
        in Gmail with an X-Scheduled-Send-At header containing the
        requested send time. An external scheduler should process
        and send the email at the specified time.

        Args:
            request.recipient_email: Email address of the recipient
            request.subject: Subject line of the email
            request.body: Body content of the email
            request.send_at: ISO 8601 timestamp for when to send
            request.cc: Optional CC email addresses (comma-separated)
            request.bcc: Optional BCC email addresses (comma-separated)

        Returns:
            Dict with success status, draft_id, and scheduled_for timestamp
        """

        msg = MIMEText(request.body)
        msg["to"] = request.recipient_email
        msg["subject"] = request.subject
        if request.cc:
            msg["cc"] = request.cc
        if request.bcc:
            msg["bcc"] = request.bcc
        msg["X-Scheduled-Send-At"] = request.send_at
        raw = base64.urlsafe_b64encode(msg.as_bytes()).decode("utf-8")

        url = "https://gmail.googleapis.com/gmail/v1/users/me/drafts"
        payload = {"message": {"raw": raw}}
        resp = _http_client.post(
            url, json=payload, headers=_auth_headers(auth_credentials)
        )
        resp.raise_for_status()
        data = resp.json()
        draft_id = data.get("id", "unknown")
        return {
            "success": True,
            "message": f"Email scheduled for {request.send_at}",
            "draft_id": draft_id,
            "scheduled_for": request.send_at,
        }

    return [
        "GMAIL_MARK_AS_READ",
        "GMAIL_MARK_AS_UNREAD",
        "GMAIL_ARCHIVE_EMAIL",
        "GMAIL_STAR_EMAIL",
        "GMAIL_GET_UNREAD_COUNT",
        "GMAIL_SCHEDULE_SEND",
    ]
