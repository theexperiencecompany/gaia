"""Gmail custom tools using Composio custom tool infrastructure.

All Gmail API calls go through Composio's proxy via `proxy_request_sync`.
The proxy attaches the user's OAuth token server-side; tools only need
`user_id` from `auth_credentials`.
"""

import datetime
from typing import Any, Dict, List, Optional

from shared.py.wide_events import log
from app.models.common_models import GatherContextInput
from app.services.composio.proxy_client import proxy_request_sync
from app.services.contact_service import build_contact_index
from composio import Composio
from pydantic import BaseModel, Field

GMAIL_API_BASE = "https://gmail.googleapis.com/gmail/v1"
GMAIL_TOOLKIT = "GMAIL"


def _user_id(auth_credentials: Dict[str, Any]) -> str:
    user_id = auth_credentials.get("user_id")
    if not user_id:
        raise ValueError("Missing user_id in auth_credentials")
    return user_id


def _gmail_proxy(
    user_id: str,
    *,
    endpoint: str,
    method: str,
    body: Optional[Dict[str, Any]] = None,
    query: Optional[Dict[str, Any]] = None,
) -> Any:
    return proxy_request_sync(
        user_id=user_id,
        toolkit=GMAIL_TOOLKIT,
        endpoint=endpoint,
        method=method,  # type: ignore[arg-type]
        body=body,
        query=query,
    )


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
    """Register custom Gmail tools with the Composio client.

    These tools provide user-friendly wrappers around Gmail's label-based
    operations for common email actions.

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
        _gmail_proxy(
            _user_id(auth_credentials),
            endpoint=f"{GMAIL_API_BASE}/users/me/messages/batchModify",
            method="POST",
            body={"ids": request.message_ids, "removeLabelIds": ["UNREAD"]},
        )
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
        _gmail_proxy(
            _user_id(auth_credentials),
            endpoint=f"{GMAIL_API_BASE}/users/me/messages/batchModify",
            method="POST",
            body={"ids": request.message_ids, "addLabelIds": ["UNREAD"]},
        )
        return {}

    @composio.tools.custom_tool(toolkit="gmail")
    def ARCHIVE_EMAIL(
        request: ArchiveEmailInput,
        execute_request: Any,
        auth_credentials: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Archive Gmail messages.

        Removes the INBOX label from specified messages, moving them
        to the archive (All Mail).

        Args:
            request.message_ids: List of Gmail message IDs to archive

        Returns:
            Dict with success status and API response data
        """
        _gmail_proxy(
            _user_id(auth_credentials),
            endpoint=f"{GMAIL_API_BASE}/users/me/messages/batchModify",
            method="POST",
            body={"ids": request.message_ids, "removeLabelIds": ["INBOX"]},
        )
        return {}

    @composio.tools.custom_tool(toolkit="gmail")
    def STAR_EMAIL(
        request: StarEmailInput,
        execute_request: Any,
        auth_credentials: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Star or unstar Gmail messages.

        Adds or removes the STARRED label from specified messages.

        Args:
            request.message_ids: List of Gmail message IDs to star/unstar
            request.unstar: If True, remove star; if False (default), add star

        Returns:
            Dict with action taken and API response data
        """
        if request.unstar:
            payload = {"ids": request.message_ids, "removeLabelIds": ["STARRED"]}
            action = "unstarred"
        else:
            payload = {"ids": request.message_ids, "addLabelIds": ["STARRED"]}
            action = "starred"
        _gmail_proxy(
            _user_id(auth_credentials),
            endpoint=f"{GMAIL_API_BASE}/users/me/messages/batchModify",
            method="POST",
            body=payload,
        )
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
        """

        user_id = _user_id(auth_credentials)
        resolved_label_ids: List[str] = []

        if request.label_ids:
            resolved_label_ids = [label for label in request.label_ids if label]
        elif not request.query:
            resolved_label_ids = ["INBOX"]

        def _count_messages(query: str) -> int:
            params: Dict[str, Any] = {
                "maxResults": 1,
                "includeSpamTrash": str(request.include_spam_trash).lower(),
                "q": query,
            }
            if resolved_label_ids:
                params["labelIds"] = resolved_label_ids

            data = _gmail_proxy(
                user_id,
                endpoint=f"{GMAIL_API_BASE}/users/me/messages",
                method="GET",
                query=params,
            )

            estimate = (data or {}).get("resultSizeEstimate", 0)
            if isinstance(estimate, int):
                return max(0, estimate)

            messages = (data or {}).get("messages", [])
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
            data = _gmail_proxy(
                user_id,
                endpoint=f"{GMAIL_API_BASE}/users/me/labels/{label_id}",
                method="GET",
            )

            counts[label_id] = {
                "label_id": label_id,
                "label_name": (data or {}).get("name", label_id),
                "unreadCount": (data or {}).get("messagesUnread", 0),
                "totalCount": (data or {}).get("messagesTotal", 0),
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

        Extracts unique contacts from the user's email history using a Gmail
        search query. Sends a list+get sequence through the Composio proxy.

        Args:
            request.query: Search query to filter contacts
            request.max_results: Maximum number of messages to analyze (default: 30)

        Returns: Array of contacts with name and email.
        """
        user_id = _user_id(auth_credentials)

        list_response = _gmail_proxy(
            user_id,
            endpoint=f"{GMAIL_API_BASE}/users/me/messages",
            method="GET",
            query={"q": request.query, "maxResults": request.max_results},
        )

        message_ids = [
            m.get("id")
            for m in (list_response or {}).get("messages", [])
            if m.get("id")
        ]

        messages: List[Dict[str, Any]] = []
        fetch_failures = 0
        for message_id in message_ids:
            try:
                full = _gmail_proxy(
                    user_id,
                    endpoint=f"{GMAIL_API_BASE}/users/me/messages/{message_id}",
                    method="GET",
                    query={
                        "format": "metadata",
                        "metadataHeaders": ["From", "To", "Cc", "Reply-To"],
                    },
                )
                if isinstance(full, dict):
                    messages.append(full)
            except Exception as exc:
                fetch_failures += 1
                log.warning(
                    f"Gmail message fetch failed for {message_id}: {exc}"
                )

        if message_ids and not messages:
            log.error(
                f"Gmail contact list: all {len(message_ids)} message fetches failed "
                f"for user {user_id}"
            )
            return {
                "success": False,
                "error": (
                    f"Failed to fetch any of the {len(message_ids)} matched "
                    "messages; cannot extract contacts"
                ),
                "contacts": [],
                "count": 0,
            }
        if fetch_failures:
            log.set(gmail_contact_fetch_failures=fetch_failures)

        return build_contact_index(messages, filter_query=request.query)

    @composio.tools.custom_tool(toolkit="gmail")
    def CUSTOM_GATHER_CONTEXT(
        request: GatherContextInput,
        execute_request: Any,
        auth_credentials: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Get Gmail context snapshot: profile info, inbox unread count, and recent message IDs.

        Zero required parameters. Returns current user's Gmail state for situational awareness.
        """
        user_id = _user_id(auth_credentials)

        profile = _gmail_proxy(
            user_id,
            endpoint=f"{GMAIL_API_BASE}/users/me/profile",
            method="GET",
        ) or {}

        inbox = _gmail_proxy(
            user_id,
            endpoint=f"{GMAIL_API_BASE}/users/me/labels/INBOX",
            method="GET",
        ) or {}

        messages_query: Dict[str, Any] = {"labelIds": "INBOX", "maxResults": 5}
        if request.since:
            since_ts = int(
                datetime.datetime.fromisoformat(
                    request.since.replace("Z", "+00:00")
                ).timestamp()
            )
            messages_query["q"] = f"after:{since_ts}"

        messages_data = _gmail_proxy(
            user_id,
            endpoint=f"{GMAIL_API_BASE}/users/me/messages",
            method="GET",
            query=messages_query,
        ) or {}

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
