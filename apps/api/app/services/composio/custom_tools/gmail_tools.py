"""Gmail custom tools using Composio custom tool infrastructure.

All Gmail API calls go through Composio's proxy via `proxy_request_sync`.
The proxy attaches the user's OAuth token server-side; tools only need
`user_id` from `auth_credentials`.
"""

import datetime
import json
import re
from typing import Any
import uuid

from composio import Composio
from pydantic import BaseModel, Field

from app.agents.templates.mail_templates import build_message_view
from app.models.common_models import GatherContextInput
from app.models.composio_schemas.gmail import FetchInboxSummaryInput
from app.services.composio.custom_tools.gmail_constants import (
    _DAYS_PER_UNIT,
    GMAIL_API_BASE,
    GMAIL_TOOLKIT,
    INLINE_LIMIT_CHARS,
    MAX_ABSOLUTE_MESSAGES,
    OFFLOAD_DIR,
    OFFLOAD_FILE_PREFIX,
    OFFLOAD_PREVIEW_SIZE,
    TIMEFRAME_DEFAULT_MAX,
)
from app.services.composio.proxy_client import proxy_request_sync
from app.services.contact_service import build_contact_index
from app.utils.timezone import Timezone
from shared.py.wide_events import log

# =============================================================================
# Shared helpers
# =============================================================================


def _user_id(auth_credentials: dict[str, Any]) -> str:
    user_id = auth_credentials.get("user_id")
    if not user_id:
        raise ValueError("Missing user_id in auth_credentials")
    return user_id


def _gmail_proxy(
    user_id: str,
    *,
    endpoint: str,
    method: str,
    body: dict[str, Any] | None = None,
    query: dict[str, Any] | None = None,
) -> Any:
    return proxy_request_sync(
        user_id=user_id,
        toolkit=GMAIL_TOOLKIT,
        endpoint=endpoint,
        method=method,  # type: ignore[arg-type]
        body=body,
        query=query,
    )


def _conversation_id(auth_credentials: dict[str, Any]) -> str | None:
    """Pull a vfs_session_id / thread_id out of auth_credentials for offload.

    Composio's custom tool infrastructure surfaces runnable metadata through
    the auth_credentials dict. We mirror the same convention used by
    ``extract_user_id_from_params`` in ``composio_hooks/user_id_hooks.py``.
    """
    return (
        auth_credentials.get("vfs_session_id")
        or auth_credentials.get("thread_id")
        or auth_credentials.get("conversation_id")
    )


def _write_session_file_sync(
    user_id: str, conversation_id: str, relative_path: str, content: str
) -> tuple[Any, str]:
    """Synchronous session file write for the offload path.

    Custom tool handlers run synchronously (composio's sync ``custom_tool``
    framework), so we can't await ``write_session_file`` directly. We
    replicate its safety logic (path containment + parent mkdir) here
    without the async instrumentation. The body is just a file write;
    the JuiceFS mount is already on the host filesystem.
    """
    from app.services.storage.juicefs import (
        _contained,
        _require_mount,
        ensure_safe_path_id,
    )

    ensure_safe_path_id(conversation_id, label="conversation_id")
    base = _require_mount() / "users" / user_id / "sessions" / conversation_id
    target = _contained(base, relative_path, root_label="session root")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")
    sandbox_view = f"/workspace/sessions/{conversation_id}/{relative_path}"
    return target, sandbox_view


# =============================================================================
# FETCH_INBOX_SUMMARY — timeframe resolution
# =============================================================================


def _resolve_user_timezone(auth_credentials: dict[str, Any]) -> Timezone:
    """Resolve the user's home timezone from auth_credentials metadata.

    Falls back to UTC with a warning. The custom tool infrastructure doesn't
    pass the full LangGraph config, so we extract the timezone the
    integrations system already attached to the credentials.
    """
    raw = auth_credentials.get("user_timezone") or auth_credentials.get("timezone")
    tz = Timezone.parse(raw) if raw else Timezone.utc()
    if tz.is_utc and raw is None:
        log.warning(
            "GMAIL_FETCH_INBOX_SUMMARY: no user_timezone in auth_credentials; "
            "using UTC for timeframe resolution"
        )
    return tz


def _timeframe_clause(timeframe: str, tz: Timezone) -> str:
    """Translate a timeframe enum to a Gmail after:/before: clause.

    Returns "" for unrecognized values (caller falls back to default cap).
    """
    today = tz.now().date()

    if timeframe in ("today", "yesterday", "tomorrow"):
        delta = {"today": 0, "yesterday": -1, "tomorrow": 1}[timeframe]
        return _date_window_clause(today + datetime.timedelta(days=delta), days=1)

    if timeframe in ("this_week", "last_week", "next_week"):
        delta_weeks = {"this_week": 0, "last_week": -1, "next_week": 1}[timeframe]
        # ISO week: Monday is day 1. today.weekday() is 0 (Mon) .. 6 (Sun).
        monday = (
            today - datetime.timedelta(days=today.weekday()) + datetime.timedelta(weeks=delta_weeks)
        )
        return _date_window_clause(monday, days=7)

    match = re.fullmatch(r"(\d+)([dwmy])", timeframe)
    if match:
        n = int(match.group(1))
        days = n * _DAYS_PER_UNIT[match.group(2)]
        start = today - datetime.timedelta(days=days)
        # "last N days" → window ends at the end of today.
        return _date_window_clause(start, end_date=today)

    return ""


def _date_window_clause(
    start: datetime.date,
    *,
    days: int | None = None,
    end_date: datetime.date | None = None,
) -> str:
    """Format ``after:<start> before:<exclusive_end>`` for a single window."""
    if end_date is None:
        if days is None:
            raise ValueError("Provide either days= or end_date=")
        end = start + datetime.timedelta(days=days)
    else:
        end = end_date + datetime.timedelta(days=1)
    return f"after:{_gmail_date(start)} before:{_gmail_date(end)}"


def _gmail_date(d: datetime.date) -> str:
    """Gmail wants YYYY/MM/DD, not ISO dashes."""
    return d.isoformat().replace("-", "/")


def _resolve_timeframe(
    timeframe: str | None,
    query: str | None,
    tz: Timezone,
) -> tuple[str, int]:
    """Resolve a timeframe enum + raw query to (combined_query, default_max).

    Honors an explicit after:/before: in `query` over `timeframe`.
    """
    default_max = TIMEFRAME_DEFAULT_MAX.get(timeframe or "", 100)

    explicit_after_or_before = query and ("after:" in query or "before:" in query)
    if explicit_after_or_before:
        if timeframe is not None:
            log.warning(
                f"GMAIL_FETCH_INBOX_SUMMARY: query already has after:/before:, "
                f"ignoring timeframe={timeframe!r}"
            )
        return query or "", default_max

    clause = _timeframe_clause(timeframe, tz) if timeframe else ""
    combined = " ".join(filter(None, [clause, query or ""])).strip()
    return combined, default_max


def _effective_max(request: FetchInboxSummaryInput, default_max: int) -> int:
    """Apply the per-call override and the absolute ceiling, in that order."""
    override = request.max_messages if request.max_messages is not None else default_max
    return min(override, MAX_ABSOLUTE_MESSAGES)


# =============================================================================
# FETCH_INBOX_SUMMARY — pagination + field shaping + offload
# =============================================================================


class _PartialResult(Exception):
    """Raised internally to short-circuit the pagination loop on error.

    Caught at the top of ``FETCH_INBOX_SUMMARY`` and rendered as a
    partial / error response. ``partial_messages`` is the list of
    messages we managed to fetch before the error — the caller decides
    whether to surface them.
    """

    def __init__(self, *, reason: str, partial_messages: list[dict[str, Any]]):
        super().__init__(reason)
        self.reason = reason
        self.partial_messages = partial_messages


def _fetch_list_page(
    user_id: str,
    *,
    query: str,
    per_page: int,
    page_token: str | None,
) -> dict[str, Any]:
    """Return the next ``users.me.messages`` page.

    Lets proxy exceptions propagate; the aggregator attaches the
    partial-state context (already-fetched messages) before re-raising.
    """
    params: dict[str, Any] = {"q": query, "maxResults": per_page}
    if page_token:
        params["pageToken"] = page_token
    return _gmail_proxy(  # type: ignore[no-any-return]
        user_id,
        endpoint=f"{GMAIL_API_BASE}/users/me/messages",
        method="GET",
        query=params,
    )


def _fetch_message_view(
    user_id: str,
    message_id: str,
    *,
    fields: Any,
    body_processing: str,
) -> dict[str, Any] | None:
    """Fetch one message and project it to the caller-requested fields.

    Returns None if the proxy returned something that isn't a dict (we
    don't fail the whole tool call on a single weird response). Lets
    proxy exceptions propagate; the aggregator attaches the partial-
    state context before re-raising.
    """
    full = _gmail_proxy(
        user_id,
        endpoint=f"{GMAIL_API_BASE}/users/me/messages/{message_id}",
        method="GET",
        query={"format": "full"},
    )
    if not isinstance(full, dict):
        return None
    return build_message_view(full, fields=fields, body_processing=body_processing)


def _aggregate_pages(
    user_id: str,
    request: FetchInboxSummaryInput,
    *,
    combined_query: str,
    effective_max: int,
) -> tuple[list[dict[str, Any]], bool]:
    """Drive the list→fetch loop until exhausted, capped, or errored.

    Returns (messages, truncated). Raises ``_PartialResult`` for caller
    mid-loop errors, carrying the messages already aggregated.
    """
    all_messages: list[dict[str, Any]] = []
    page_token: str | None = None
    truncated = False

    try:
        while True:
            data = _fetch_list_page(
                user_id,
                query=combined_query,
                per_page=request.per_page,
                page_token=page_token,
            )
            page_ids = [m["id"] for m in (data or {}).get("messages", []) if m.get("id")]
            if not page_ids:
                break

            for mid in page_ids:
                if len(all_messages) >= effective_max:
                    truncated = True
                    break
                view = _fetch_message_view(
                    user_id,
                    mid,
                    fields=request.fields,
                    body_processing=request.body_processing,
                )
                if view is not None:
                    all_messages.append(view)

            if len(all_messages) >= effective_max:
                truncated = True
                break

            page_token = (data or {}).get("nextPageToken")
            if not page_token:
                break
    except Exception as exc:
        log.warning(f"GMAIL_FETCH_INBOX_SUMMARY: pagination aborted mid-loop: {exc}")
        raise _PartialResult(reason=str(exc), partial_messages=all_messages) from exc

    return all_messages, truncated


def _offload_path() -> str:
    """Build a timestamped, unique offload path (relative to the session root)."""
    ts = datetime.datetime.now(datetime.UTC).strftime("%Y%m%d_%H%M%S")
    return f"{OFFLOAD_DIR}/{OFFLOAD_FILE_PREFIX}{ts}_{uuid.uuid4().hex[:8]}.jsonl"


def _format_offload_result(
    messages: list[dict[str, Any]],
    *,
    truncated: bool,
    user_id: str,
    conversation_id: str,
    field_count: int,
) -> dict[str, Any]:
    """Write the messages to a session JSONL file and return the digest."""
    rel_path = _offload_path()
    body = "\n".join(json.dumps(m, default=str) for m in messages)
    _, sandbox_path = _write_session_file_sync(
        user_id=user_id,
        conversation_id=conversation_id,
        relative_path=rel_path,
        content=body,
    )
    return {
        "fetched_count": len(messages),
        "truncated": truncated,
        "offloaded_to": sandbox_path,
        "inline_preview": messages[:OFFLOAD_PREVIEW_SIZE],
        "field_count": field_count,
        "hint": (
            f"Wrote {len(messages)} messages to {sandbox_path} (JSONL). Examples:\n"
            f"  jq -r 'select(.from | contains(\"github\")) | .subject' {sandbox_path}\n"
            f"  grep -i 'invoice' {sandbox_path}"
        ),
    }


def _format_inline_result(messages: list[dict[str, Any]], *, truncated: bool) -> dict[str, Any]:
    """Small-result shape: full payload, no offload."""
    return {
        "fetched_count": len(messages),
        "truncated": truncated,
        "messages": messages,
    }


def _format_partial_result(messages: list[dict[str, Any]], *, reason: str) -> dict[str, Any]:
    """Error-mid-loop shape: stop at the page that succeeded, surface the error."""
    return {
        "fetched_count": len(messages),
        "truncated": True,
        "partial": True,
        "error": reason,
        "messages": messages,
    }


def _summarize(
    user_id: str,
    request: FetchInboxSummaryInput,
    auth_credentials: dict[str, Any],
) -> dict[str, Any]:
    """Top-level orchestrator: resolve → paginate → offload-or-inline."""
    tz = _resolve_user_timezone(auth_credentials)
    combined_query, default_max = _resolve_timeframe(request.timeframe, request.query, tz)
    cap = _effective_max(request, default_max)

    try:
        all_messages, truncated = _aggregate_pages(
            user_id, request, combined_query=combined_query, effective_max=cap
        )
    except _PartialResult as exc:
        return _format_partial_result(exc.partial_messages, reason=exc.reason)

    serialized = json.dumps({"messages": all_messages}, default=str)
    if len(serialized) <= INLINE_LIMIT_CHARS:
        return _format_inline_result(all_messages, truncated=truncated)

    conversation_id = _conversation_id(auth_credentials)
    if conversation_id is None:
        log.warning(
            "GMAIL_FETCH_INBOX_SUMMARY: no conversation_id for offload; "
            "returning inline (compaction middleware will catch it if needed)"
        )
        return _format_inline_result(all_messages, truncated=truncated)

    return _format_offload_result(
        all_messages,
        truncated=truncated,
        user_id=user_id,
        conversation_id=conversation_id,
        field_count=len(request.fields),
    )


# =============================================================================
# Input models
# =============================================================================


class MarkAsReadInput(BaseModel):
    """Input for marking emails as read."""

    message_ids: list[str] = Field(
        ...,
        description="List of Gmail message IDs to mark as read",
    )


class MarkAsUnreadInput(BaseModel):
    """Input for marking emails as unread."""

    message_ids: list[str] = Field(
        ...,
        description="List of Gmail message IDs to mark as unread",
    )


class ArchiveEmailInput(BaseModel):
    """Input for archiving emails."""

    message_ids: list[str] = Field(
        ...,
        description="List of Gmail message IDs to archive (remove from inbox)",
    )


class StarEmailInput(BaseModel):
    """Input for starring/unstarring emails."""

    message_ids: list[str] = Field(
        ...,
        description="List of Gmail message IDs to star or unstar",
    )
    unstar: bool = Field(
        default=False,
        description="If True, remove star instead of adding it",
    )


class GetUnreadCountInput(BaseModel):
    """Input for getting unread email count."""

    label_ids: list[str] | None = Field(
        default=None,
        description="Optional list of Gmail label IDs to count. "
        "Examples: INBOX, CATEGORY_PROMOTIONS, CATEGORY_UPDATES.",
    )
    query: str | None = Field(
        default=None,
        description="Optional Gmail search query to count matching messages "
        "without fetching full message payloads.",
    )
    include_spam_trash: bool = Field(
        default=False,
        description="Whether query counts should include Spam and Trash.",
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


# =============================================================================
# Tool registration
# =============================================================================


def _count_messages(
    user_id: str,
    *,
    query: str,
    label_ids: list[str],
    include_spam_trash: bool,
) -> int:
    """Lightweight count via ``maxResults=1`` — uses ``resultSizeEstimate``."""
    params: dict[str, Any] = {
        "maxResults": 1,
        "includeSpamTrash": str(include_spam_trash).lower(),
        "q": query,
    }
    if label_ids:
        params["labelIds"] = label_ids

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


def _label_stats(user_id: str, label_id: str) -> dict[str, Any]:
    data = _gmail_proxy(
        user_id,
        endpoint=f"{GMAIL_API_BASE}/users/me/labels/{label_id}",
        method="GET",
    )
    return {
        "label_id": label_id,
        "label_name": (data or {}).get("name", label_id),
        "unreadCount": (data or {}).get("messagesUnread", 0),
        "totalCount": (data or {}).get("messagesTotal", 0),
    }


def _gmail_user_profile(user_id: str) -> dict[str, Any]:
    return (
        _gmail_proxy(
            user_id,
            endpoint=f"{GMAIL_API_BASE}/users/me/profile",
            method="GET",
        )
        or {}
    )


def _gmail_inbox_label(user_id: str) -> dict[str, Any]:
    return (
        _gmail_proxy(
            user_id,
            endpoint=f"{GMAIL_API_BASE}/users/me/labels/INBOX",
            method="GET",
        )
        or {}
    )


def _recent_inbox_ids(user_id: str, *, since: str | None, max_results: int) -> list[str]:
    messages_query: dict[str, Any] = {"labelIds": "INBOX", "maxResults": max_results}
    if since:
        since_ts = int(datetime.datetime.fromisoformat(since.replace("Z", "+00:00")).timestamp())
        messages_query["q"] = f"after:{since_ts}"
    messages_data = (
        _gmail_proxy(
            user_id,
            endpoint=f"{GMAIL_API_BASE}/users/me/messages",
            method="GET",
            query=messages_query,
        )
        or {}
    )
    return [m.get("id") for m in messages_data.get("messages", [])]


def register_gmail_custom_tools(composio: Composio):
    """Register custom Gmail tools with the Composio client. Returns the registered tool names."""

    @composio.tools.custom_tool(toolkit="gmail")
    def MARK_AS_READ(
        request: MarkAsReadInput,
        execute_request: Any,
        auth_credentials: dict[str, Any],
    ) -> dict[str, Any]:
        """Mark Gmail messages as read (removes the UNREAD label)."""
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
        auth_credentials: dict[str, Any],
    ) -> dict[str, Any]:
        """Mark Gmail messages as unread (adds the UNREAD label)."""
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
        auth_credentials: dict[str, Any],
    ) -> dict[str, Any]:
        """Archive Gmail messages (removes the INBOX label, moving to All Mail)."""
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
        auth_credentials: dict[str, Any],
    ) -> dict[str, Any]:
        """Star or unstar Gmail messages (adds/removes the STARRED label)."""
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
        auth_credentials: dict[str, Any],
    ) -> dict[str, Any]:
        """Get message counts using lightweight Gmail APIs.

        Supports two modes:
        1) Label mode (default): returns per-label unread + total counts
        2) Query mode: returns count estimates for a Gmail search query,
           with an unread-filtered estimate as well
        """
        user_id = _user_id(auth_credentials)
        resolved_label_ids: list[str] = []
        if request.label_ids:
            resolved_label_ids = [label for label in request.label_ids if label]
        elif not request.query:
            resolved_label_ids = ["INBOX"]

        query = request.query.strip() if request.query else ""
        if query:
            return _unread_count_query_mode(
                user_id, query, resolved_label_ids, request.include_spam_trash
            )
        return _unread_count_label_mode(user_id, resolved_label_ids)

    @composio.tools.custom_tool(toolkit="gmail")
    def GET_CONTACT_LIST(
        request: GetContactListInput,
        execute_request: Any,
        auth_credentials: dict[str, Any],
    ) -> dict[str, Any]:
        """Extract unique contacts from email history matching a Gmail search query."""
        user_id = _user_id(auth_credentials)

        list_response = _gmail_proxy(
            user_id,
            endpoint=f"{GMAIL_API_BASE}/users/me/messages",
            method="GET",
            query={"q": request.query, "maxResults": request.max_results},
        )
        message_ids = [
            m.get("id") for m in (list_response or {}).get("messages", []) if m.get("id")
        ]

        messages, fetch_failures = _fetch_messages_for_contacts(user_id, message_ids)
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
        auth_credentials: dict[str, Any],
    ) -> dict[str, Any]:
        """Get Gmail context snapshot: profile info, inbox unread count, and recent message IDs.

        Zero required parameters. Returns current user's Gmail state for situational awareness.
        """
        user_id = _user_id(auth_credentials)
        profile = _gmail_user_profile(user_id)
        inbox = _gmail_inbox_label(user_id)
        recent_ids = _recent_inbox_ids(user_id, since=request.since, max_results=5)

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

    @composio.tools.custom_tool(toolkit="gmail")
    def FETCH_INBOX_SUMMARY(
        request: FetchInboxSummaryInput,
        execute_request: Any,
        auth_credentials: dict[str, Any],
    ) -> dict[str, Any]:
        """Fetch and aggregate Gmail messages matching a timeframe/query.

        Server-side paginates the Gmail API and returns the full set of
        matching messages in one tool call. This avoids the broken
        pagination handoff (subagent receiving a nextPageToken it never
        returns to the gmail_agent).

        Supports a ``timeframe`` convenience enum (``today``, ``7d``,
        ``this_week``, etc.) which is resolved to Gmail's after:/before:
        operators in the user's home timezone.

        When the aggregate response is too large to inline, the tool
        writes a JSONL file to the user's session workspace and returns
        a digest + path. The agent then uses ``bash``/``jq``/``grep`` to
        mine it (the standard GAIA offload pattern).
        """
        return _summarize(_user_id(auth_credentials), request, auth_credentials)

    return [
        "GMAIL_MARK_AS_READ",
        "GMAIL_MARK_AS_UNREAD",
        "GMAIL_ARCHIVE_EMAIL",
        "GMAIL_STAR_EMAIL",
        "GMAIL_GET_UNREAD_COUNT",
        "GMAIL_GET_CONTACT_LIST",
        "GMAIL_CUSTOM_GATHER_CONTEXT",
        "GMAIL_FETCH_INBOX_SUMMARY",
    ]


# =============================================================================
# GET_UNREAD_COUNT sub-helpers
# =============================================================================


def _unread_count_query_mode(
    user_id: str,
    query: str,
    resolved_label_ids: list[str],
    include_spam_trash: bool,
) -> dict[str, Any]:
    total_count = _count_messages(
        user_id,
        query=query,
        label_ids=resolved_label_ids,
        include_spam_trash=include_spam_trash,
    )
    unread_query = query if "is:unread" in query.lower() else f"{query} is:unread"
    unread_count = _count_messages(
        user_id,
        query=unread_query,
        label_ids=resolved_label_ids,
        include_spam_trash=include_spam_trash,
    )

    result: dict[str, Any] = {
        "query": query,
        "label_ids": resolved_label_ids,
        "totalCount": total_count,
        "unreadCount": unread_count,
        "is_estimate": True,
    }
    if len(resolved_label_ids) == 1:
        result["label_id"] = resolved_label_ids[0]
    return result


def _unread_count_label_mode(user_id: str, resolved_label_ids: list[str]) -> dict[str, Any]:
    if not resolved_label_ids:
        return {
            "counts": {},
            "label_ids": [],
            "unreadCount": 0,
            "totalCount": 0,
        }

    counts = {label_id: _label_stats(user_id, label_id) for label_id in resolved_label_ids}

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


# =============================================================================
# GET_CONTACT_LIST sub-helpers
# =============================================================================


def _fetch_messages_for_contacts(
    user_id: str, message_ids: list[str]
) -> tuple[list[dict[str, Any]], int]:
    """Fetch each message's metadata headers needed for contact extraction.

    Returns (messages, fetch_failures). ``fetch_failures`` is the count of
    ids that raised — the caller decides whether to surface that to the
    user.
    """
    messages: list[dict[str, Any]] = []
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
            log.warning(f"Gmail message fetch failed for {message_id}: {exc}")
    return messages, fetch_failures
