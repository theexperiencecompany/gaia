"""Gmail custom tools using Composio custom tool infrastructure.

All HTTP calls are synchronous using httpx.Client to avoid event loop issues.
"""

import datetime
from typing import Any, Dict, List, Optional

import httpx
from app.models.common_models import GatherContextInput
from app.services.contact_service import get_gmail_contacts
from composio import Composio
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build  # type: ignore
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

    label_ids: Optional[List[str]] = Field(
        default=None,
        description="Optional list of Gmail label IDs to count. "
        "Examples: INBOX, CATEGORY_PROMOTIONS, CATEGORY_UPDATES.",
    )
    query: Optional[str] = Field(
        default=None,
        description="Optional Gmail search query to count matching messages "
        "without fetching full message payloads.",
    )
    include_spam_trash: bool = Field(
        default=False,
        description="Whether query counts should include Spam and Trash.",
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


class SnoozeEmailInput(BaseModel):
    """Input for snoozing emails until a specified time."""

    message_ids: List[str] = Field(
        ...,
        description="List of Gmail message IDs to snooze",
    )
    snooze_until: str = Field(
        ...,
        description="ISO 8601 timestamp for when to unsnooze (e.g., '2024-01-15T09:00:00Z'). "
        "Common values: 'tomorrow morning' (9am next day), 'next week' (Monday 9am), "
        "'this afternoon' (today 3pm), 'this evening' (today 6pm)",
    )


class GetContactListInput(BaseModel):
    """Input for getting contact list from email history."""

    query: str = Field(
        ...,
        description="Search query to filter contacts (e.g., email address, name, or any Gmail search query)",
    )
    max_results: int = Field(
        default=30,
        description="Maximum number of messages to analyze for contact extraction (default: 30)",
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
        return {}

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
        return {}

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
        return {}

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
        return {"action": action}

    @composio.tools.custom_tool(toolkit="gmail")
    def GET_UNREAD_COUNT(
        request: GetUnreadCountInput,
        execute_request: Any,
        auth_credentials: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Get message counts using lightweight Gmail APIs.

        Supports two modes:
        1) Label mode (default): returns per-label unread + total counts
        2) Query mode: returns count estimates for a Gmail search query,
           with an unread-filtered estimate as well

        Notes:
        - Query counts use ``resultSizeEstimate`` from Gmail API.
        - For backward compatibility, single-label requests still return
          top-level ``unreadCount`` and ``label_id``.
        """

        headers = _auth_headers(auth_credentials)
        resolved_label_ids: List[str] = []

        if request.label_ids:
            resolved_label_ids = [label for label in request.label_ids if label]
        elif not request.query:
            resolved_label_ids = ["INBOX"]

        def _count_messages(query: str) -> int:
            params: Dict[str, Any] = {
                "maxResults": 1,
                "includeSpamTrash": request.include_spam_trash,
                "q": query,
            }
            if resolved_label_ids:
                params["labelIds"] = resolved_label_ids

            resp = _http_client.get(
                "https://gmail.googleapis.com/gmail/v1/users/me/messages",
                headers=headers,
                params=params,
            )
            resp.raise_for_status()
            data = resp.json()

            estimate = data.get("resultSizeEstimate", 0)
            if isinstance(estimate, int):
                return max(0, estimate)

            messages = data.get("messages", [])
            if isinstance(messages, list):
                return len(messages)
            return 0

        query = request.query.strip() if request.query else ""
        if query:
            total_count = _count_messages(query)
            unread_query = (
                query if "is:unread" in query.lower() else f"{query} is:unread"
            )
            unread_count = _count_messages(unread_query)

            result: Dict[str, Any] = {
                "query": query,
                "label_ids": resolved_label_ids,
                "totalCount": total_count,
                "unreadCount": unread_count,
                "is_estimate": True,
            }

            if len(resolved_label_ids) == 1:
                result["label_id"] = resolved_label_ids[0]

            return result

        counts: Dict[str, Dict[str, Any]] = {}
        for label_id in resolved_label_ids:
            url = f"https://gmail.googleapis.com/gmail/v1/users/me/labels/{label_id}"
            resp = _http_client.get(url, headers=headers)
            resp.raise_for_status()
            data = resp.json()

            counts[label_id] = {
                "label_id": label_id,
                "label_name": data.get("name", label_id),
                "unreadCount": data.get("messagesUnread", 0),
                "totalCount": data.get("messagesTotal", 0),
            }

        if not counts:
            return {
                "counts": {},
                "label_ids": [],
                "unreadCount": 0,
                "totalCount": 0,
            }

        if len(resolved_label_ids) == 1:
            label_id = resolved_label_ids[0]
            label_stats = counts[label_id]
            return {
                "counts": counts,
                "label_ids": resolved_label_ids,
                "label_id": label_id,
                "label_name": label_stats["label_name"],
                "unreadCount": label_stats["unreadCount"],
                "totalCount": label_stats["totalCount"],
            }

        return {
            "counts": counts,
            "label_ids": resolved_label_ids,
        }

    @composio.tools.custom_tool(toolkit="gmail")
    def GET_CONTACT_LIST(
        request: GetContactListInput,
        execute_request: Any,
        auth_credentials: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Get contacts from email history.

        Extracts unique contacts from the user's email history using a search query.
        This is the most optimized tool for finding contacts.

        Args:
            request.query: Search query to filter contacts (e.g., name, email, domain)
            request.max_results: Maximum number of messages to analyze (default: 30)

        Returns: Array of contacts with name and email.

        Use this when:
        - User asks to find a contact by name or email
        - User asks "Show me contacts matching 'john'"
        - User asks "Find contacts from company.com"
        """
        token = auth_credentials.get("access_token")
        if not token:
            raise ValueError("Missing access_token in auth_credentials")

        try:
            credentials = Credentials(token=token)
            service = build(
                "gmail", "v1", credentials=credentials, cache_discovery=False
            )

            return get_gmail_contacts(
                service=service,
                query=request.query,
                max_results=request.max_results,
            )
        except Exception as e:
            raise RuntimeError(f"Failed to get contacts: {e}")

    @composio.tools.custom_tool(toolkit="gmail")
    def CUSTOM_GATHER_CONTEXT(
        request: GatherContextInput,
        execute_request: Any,
        auth_credentials: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Get Gmail context snapshot: profile info, inbox unread count, and recent message IDs.

        Zero required parameters. Returns current user's Gmail state for situational awareness.
        """
        headers = _auth_headers(auth_credentials)

        # Get user profile
        profile_resp = _http_client.get(
            "https://gmail.googleapis.com/gmail/v1/users/me/profile",
            headers=headers,
        )
        profile_resp.raise_for_status()
        profile = profile_resp.json()

        # Get inbox label info (includes unread count)
        inbox_resp = _http_client.get(
            "https://gmail.googleapis.com/gmail/v1/users/me/labels/INBOX",
            headers=headers,
        )
        inbox_resp.raise_for_status()
        inbox = inbox_resp.json()

        # Get recent inbox messages (IDs only)
        messages_params: Dict[str, Any] = {"labelIds": "INBOX", "maxResults": 5}
        if request.since:
            since_ts = int(
                datetime.datetime.fromisoformat(
                    request.since.replace("Z", "+00:00")
                ).timestamp()
            )
            messages_params["q"] = f"after:{since_ts}"
        messages_resp = _http_client.get(
            "https://gmail.googleapis.com/gmail/v1/users/me/messages",
            headers=headers,
            params=messages_params,
        )
        messages_resp.raise_for_status()
        messages_data = messages_resp.json()

        recent_ids = [m.get("id") for m in messages_data.get("messages", [])]

        return {
            "user": {
                "email": profile.get("emailAddress"),
                "messages_total": profile.get("messagesTotal"),
                "threads_total": profile.get("threadsTotal"),
            },
            "inbox": {
                "unread_count": inbox.get("messagesUnread", 0),
                "message_count": inbox.get("messagesTotal", 0),
            },
            "recent_message_ids": recent_ids,
        }

    return [
        "GMAIL_MARK_AS_READ",
        "GMAIL_MARK_AS_UNREAD",
        "GMAIL_ARCHIVE_EMAIL",
        "GMAIL_STAR_EMAIL",
        "GMAIL_GET_UNREAD_COUNT",
        "GMAIL_GET_CONTACT_LIST",
        "GMAIL_CUSTOM_GATHER_CONTEXT",
    ]
