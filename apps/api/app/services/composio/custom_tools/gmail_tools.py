"""Gmail custom tools using Composio custom tool infrastructure.

All Gmail API calls go through Composio's proxy via proxy_request_sync.
The proxy attaches the user's OAuth token server-side; tools only need
user_id from auth_credentials.
"""

from collections.abc import Sequence
import datetime
import re
import time

from composio import Composio
from composio.types import ExecuteRequestFn
from pydantic import BaseModel, Field

from app.agents.templates.mail_templates import (
    build_message_view,
    message_view_needs_body,
    project_message_view,
)
from app.constants.agents import TOOL_RESULT_FETCHED_AT_KEY
from app.constants.email import MessageFieldLiteral
from app.constants.log_tags import LogTag
from app.constants.offload import OFFLOAD_MIN_MESSAGES
from app.models.agent_models import agent_configurable, current_run_config, current_stream_writer
from app.models.common_models import GatherContextInput
from app.models.composio_schemas.gmail import (
    BodyProcessingLiteral,
    FetchMessagesInput,
    FetchThreadInput,
    GmailBatchModifyResult,
    GmailContactList,
    GmailContextSnapshot,
    GmailFetchInlineResult,
    GmailFetchPartialResult,
    GmailFetchThreadResult,
    GmailLabelCounts,
    GmailLabelDetail,
    GmailMessagesListResponse,
    GmailMessageView,
    GmailProfile,
    GmailStarResult,
    GmailThreadResult,
    GmailUnreadLabelCounts,
    GmailUnreadQueryCounts,
    Timeframe,
)
from app.models.integrations.composio import CustomToolAuthCredentials
from app.models.integrations.gmail import GmailThreadData
from app.models.integrations.gmail_messages import GmailApiMessage, RelayedGmailMessage
from app.services.composio.custom_tools.fetched_mail_gate import installed_fetched_mail_gate
from app.services.composio.custom_tools.gmail_constants import (
    _DAYS_PER_UNIT,
    FETCH_CONCURRENCY,
    GMAIL_API_BASE,
    GMAIL_BATCH_MODIFY_CAP,
    GMAIL_FORMAT_FULL,
    GMAIL_FORMAT_METADATA,
    GMAIL_TOOLKIT,
    MAX_ABSOLUTE_MESSAGES,
    NAMED_TIMEFRAME_DEFAULT_MAX,
    NO_TIMEFRAME_DEFAULT_MAX,
    RELATIVE_TIMEFRAME_DEFAULT_MAX,
    RELATIVE_TIMEFRAME_LONG_MAX,
)
from app.services.composio.proxy_client import ProxyMethod, ProxyRequest, proxy_request_sync
from app.services.contact_service import build_contact_index
from app.utils.concurrency import ContextThreadPoolExecutor, run_on_captured_loop
from app.utils.errors import AppError
from app.utils.timezone import Timezone, home_timezone_from_config
from shared.py.wide_events import log

# =============================================================================
# Shared helpers
# =============================================================================


#: Gmail REST query parameters: scalars, or a list for a repeated parameter (labelIds, metadataHeaders).
_GmailQuery = dict[str, str | int | list[str]]


def _gmail_proxy(
    user_id: str,
    *,
    endpoint: str,
    method: ProxyMethod,
    body: dict[str, list[str]] | None = None,
    query: _GmailQuery | None = None,
) -> object:
    """Send one Gmail REST request through the Composio proxy.

    Returns object, not Any: each Gmail endpoint answers with a
    different JSON shape, so the honest type is "something was parsed" — and
    object forces every caller to validate it into a real model (or narrow
    it) before reading a single field off it.
    """
    return proxy_request_sync(
        ProxyRequest(
            user_id=user_id,
            toolkit=GMAIL_TOOLKIT,
            endpoint=endpoint,
            method=method,
            body=body,
            query=query,
        )
    )


# =============================================================================
# FETCH_MESSAGES — timeframe resolution
# =============================================================================


def _relative_days(timeframe: str) -> int:
    """Count the calendar days a relative timeframe (14d, 2w, 3m) spans."""
    match = re.fullmatch(r"(\d+)([dwmy])", timeframe)
    if match is None:
        raise ValueError(f"not a relative timeframe: {timeframe!r}")
    return int(match.group(1)) * _DAYS_PER_UNIT[match.group(2)]


def _timeframe_clause(timeframe: Timeframe, tz: Timezone) -> str:
    """Translate a timeframe to a Gmail after:/before: clause."""
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

    # "last N days" is inclusive of today, so the window spans N calendar days:
    # [today - (N-1), today]. _date_window_clause makes the end exclusive (today + 1).
    start = today - datetime.timedelta(days=_relative_days(timeframe) - 1)
    return _date_window_clause(start, end_date=today)


def _date_window_clause(
    start: datetime.date,
    *,
    days: int | None = None,
    end_date: datetime.date | None = None,
) -> str:
    """Format after:<start> before:<exclusive_end> for a single window."""
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


def _default_max(timeframe: Timeframe | None) -> int:
    """Return the message cap a timeframe implies when the call sets no max_messages."""
    if timeframe is None:
        return NO_TIMEFRAME_DEFAULT_MAX
    if timeframe in NAMED_TIMEFRAME_DEFAULT_MAX:
        return NAMED_TIMEFRAME_DEFAULT_MAX[timeframe]
    days = _relative_days(timeframe)
    return next(
        (cap for max_days, cap in RELATIVE_TIMEFRAME_DEFAULT_MAX if days <= max_days),
        RELATIVE_TIMEFRAME_LONG_MAX,
    )


def _resolve_timeframe(
    timeframe: Timeframe | None,
    query: str | None,
    tz: Timezone,
) -> tuple[str, int]:
    """Resolve a timeframe + raw query to (combined_query, default_max).

    Honors an explicit after:/before: in query over timeframe.
    """
    default_max = _default_max(timeframe)

    explicit_after_or_before = query and ("after:" in query or "before:" in query)
    if explicit_after_or_before:
        if timeframe is not None:
            log.warning(
                "GMAIL_FETCH_MESSAGES: query already has after:/before:, ignoring timeframe",
                timeframe=timeframe,
            )
        return query or "", default_max

    clause = _timeframe_clause(timeframe, tz) if timeframe else ""
    combined = " ".join(filter(None, [clause, query or ""])).strip()
    return combined, default_max


def _effective_max(request: FetchMessagesInput, default_max: int) -> int:
    """Apply the per-call override and the absolute ceiling, in that order."""
    override = request.max_messages if request.max_messages is not None else default_max
    return min(override, MAX_ABSOLUTE_MESSAGES)


# =============================================================================
# FETCH_MESSAGES — pagination + field shaping + offload
# =============================================================================


class _PartialResultError(Exception):
    """Raised internally to short-circuit the pagination loop on error.

    Caught at the top of FETCH_MESSAGES and rendered as a
    partial / error response. partial_messages is the list of
    messages we managed to fetch before the error — the caller decides
    whether to surface them.
    """

    def __init__(self, *, reason: str, partial_messages: list[GmailMessageView]) -> None:
        super().__init__(reason)
        self.reason = reason
        self.partial_messages = partial_messages


def _fetch_list_page(
    user_id: str,
    *,
    query: str,
    per_page: int,
    page_token: str | None,
) -> GmailMessagesListResponse:
    """Return the next users.me.messages page, validated at the proxy boundary.

    Lets proxy exceptions propagate; the aggregator attaches the
    partial-state context (already-fetched messages) before re-raising.
    """
    params: _GmailQuery = {"q": query, "maxResults": per_page}
    if page_token:
        params["pageToken"] = page_token
    data = _gmail_proxy(
        user_id,
        endpoint=f"{GMAIL_API_BASE}/users/me/messages",
        method="GET",
        query=params,
    )
    return GmailMessagesListResponse.model_validate(data or {})


def _fetch_message_view(
    user_id: str,
    message_id: str,
    *,
    fields: Sequence[MessageFieldLiteral] | None,
    body_processing: BodyProcessingLiteral,
    force_body: bool,
) -> GmailMessageView | None:
    """Fetch one message and build its full (unprojected) view.

    Requests format=metadata unless fields will carry a body; force_body
    overrides this for the offload path (an explicit body_processing="none"
    still wins). Returns None on a non-dict proxy response; other exceptions
    propagate for the aggregator to attach partial-state context.
    """
    needs_body = force_body or message_view_needs_body(fields, body_processing)
    # The attachment list lives in the MIME ``parts`` tree, which only
    # ``format=full`` returns — request it when ``attachments`` is selected,
    # even if no body is wanted.
    wants_attachments = bool(fields) and "attachments" in fields
    needs_full = needs_body or wants_attachments
    full = _gmail_proxy(
        user_id,
        endpoint=f"{GMAIL_API_BASE}/users/me/messages/{message_id}",
        method="GET",
        query={"format": GMAIL_FORMAT_FULL if needs_full else GMAIL_FORMAT_METADATA},
    )
    if not isinstance(full, dict):
        return None
    return build_message_view(
        RelayedGmailMessage.model_validate(full),
        body_processing=body_processing if needs_body else "none",
    )


def _aggregate_pages(
    user_id: str,
    request: FetchMessagesInput,
    *,
    combined_query: str,
    effective_max: int,
) -> tuple[list[GmailMessageView], bool]:
    """Drive the list→fetch loop until exhausted, capped, or errored.

    Per-message fetches fan out over a bounded thread pool (FETCH_CONCURRENCY),
    keeping page order. Returns (messages, truncated); raises
    _PartialResultError for mid-loop errors, carrying messages already aggregated.
    """
    all_messages: list[GmailMessageView] = []
    page_token: str | None = None
    truncated = False
    # Resolved from the first list page's resultSizeEstimate: when the scan is
    # headed for offload, we fetch the body up front (one pass, no extra calls)
    # so the offloaded JSONL is minable. Off for an explicit no-body request.
    force_body = False

    def fetch_view(message_id: str) -> GmailMessageView | None:
        return _fetch_message_view(
            user_id,
            message_id,
            fields=request.fields,
            body_processing=request.body_processing,
            force_body=force_body,
        )

    try:
        with ContextThreadPoolExecutor(max_workers=FETCH_CONCURRENCY) as executor:
            first_page = True
            while True:
                data = _fetch_list_page(
                    user_id,
                    query=combined_query,
                    per_page=request.per_page,
                    page_token=page_token,
                )
                if first_page:
                    first_page = False
                    estimate = data.result_size_estimate
                    # An absent estimate says nothing about the size, so it cannot be
                    # read as "small": only a number over the threshold offloads.
                    headed_for_file = (
                        estimate is not None and min(estimate, effective_max) > OFFLOAD_MIN_MESSAGES
                    )
                    force_body = headed_for_file and request.body_processing != "none"
                page_ids = [ref.id for ref in data.messages if ref.id]
                if not page_ids:
                    break

                remaining = effective_max - len(all_messages)
                if len(page_ids) > remaining:
                    truncated = True
                    page_ids = page_ids[:remaining]

                # executor.map preserves input order; a per-message exception
                # surfaces mid-iteration, keeping the views appended before it
                # (same partial semantics as a sequential loop).
                for view in executor.map(fetch_view, page_ids):
                    if view is not None:
                        all_messages.append(view)

                if len(all_messages) >= effective_max:
                    truncated = True
                    break

                page_token = data.next_page_token
                if not page_token:
                    break
    except Exception as exc:
        if not all_messages:
            # Nothing fetched before the error (e.g. an expired Gmail connection)
            # is a total failure, not partial — propagate so the tool reports
            # successful: false instead of masking it as an empty inbox.
            raise
        log.warning(
            "GMAIL_FETCH_MESSAGES: pagination aborted mid-loop",
            error=str(exc),
            error_type=type(exc).__name__,
            user_id=user_id,
        )
        raise _PartialResultError(reason=str(exc), partial_messages=all_messages) from exc

    return all_messages, truncated


def _emit_email_card(views: list[GmailMessageView]) -> None:
    """Stream the interactive email-list card to the chat for an inline result.

    Mirrors what the old GMAIL_FETCH_EMAILS after-hook rendered. Takes the
    full (unprojected) views so the card keeps id/threadId/time even when the
    caller narrowed fields. No active run (background/silent execution,
    tests) just means no card; the data is still returned to the agent.
    """
    if not views:
        return
    email_fetch_data = [
        {
            "from": view.sender,
            "subject": view.subject,
            "time": view.time,
            "thread_id": view.thread_id,
            "id": view.id,
        }
        for view in views
    ]
    current_stream_writer()(
        {"email_fetch_data": email_fetch_data, "resultSize": len(email_fetch_data)}
    )


def _format_inline_result(
    messages: list[dict[str, object]], *, truncated: bool
) -> GmailFetchInlineResult:
    """Small-result shape: full payload, no offload."""
    return {
        "fetched_count": len(messages),
        "truncated": truncated,
        "messages": messages,
    }


def _format_partial_result(
    messages: list[dict[str, object]], *, reason: str
) -> GmailFetchPartialResult:
    """Error-mid-loop shape: stop at the page that succeeded, surface the error."""
    return {
        "fetched_count": len(messages),
        "truncated": True,
        "partial": True,
        "error": reason,
        # Weak models read a partial result, promise the user "still digging",
        # and end the turn — no work can happen after a turn ends. Spell out the
        # only honest moves.
        "note": (
            "This fetch FAILED partway; the messages above are all that could be "
            "retrieved. Retrying the same call will hit the same error. Do NOT "
            "tell the user you are still fetching or that more results are "
            "coming. Either narrow the query (shorter date range, a filter) and "
            "call again NOW, or answer with what you have and state plainly that "
            "the rest failed and why."
        ),
        "messages": messages,
    }


def _summarize(
    user_id: str,
    request: FetchMessagesInput,
) -> dict[str, object]:
    """Run the query and stamp its result with fetched_at, the Unix second before Gmail was asked."""
    fetched_at = int(time.time())
    return {TOOL_RESULT_FETCHED_AT_KEY: fetched_at, **_fetch_and_shape(user_id, request)}


def _fetch_and_shape(
    user_id: str, request: FetchMessagesInput
) -> GmailFetchInlineResult | GmailFetchPartialResult:
    """Resolve and paginate, then return every message, whole when compaction will file them."""
    tz = home_timezone_from_config(current_run_config())
    combined_query, default_max = _resolve_timeframe(request.timeframe, request.query, tz)
    cap = _effective_max(request, default_max)

    try:
        full_views, truncated = _aggregate_pages(
            user_id, request, combined_query=combined_query, effective_max=cap
        )
    except _PartialResultError as exc:
        return _format_partial_result(
            [project_message_view(view, request.fields) for view in exc.partial_messages],
            reason=exc.reason,
        )

    full_views = _through_todo_gate(user_id, request, full_views)
    if len(full_views) > OFFLOAD_MIN_MESSAGES:
        return _format_inline_result(_file_bound_views(full_views), truncated=truncated)
    _emit_email_card(full_views)
    return _format_inline_result(
        [project_message_view(view, request.fields) for view in full_views], truncated=truncated
    )


def _through_todo_gate(
    user_id: str, request: FetchMessagesInput, views: list[GmailMessageView]
) -> list[GmailMessageView]:
    """Return the views a tracked todo run's gate lets through; all of them outside one.

    body_processing "none" is the desk's count sweep, so only mail it triages meets the gate.
    """
    todo_id = agent_configurable(current_run_config()).get("active_todo_id")
    if not todo_id or not views or request.body_processing == "none":
        return views
    gate = installed_fetched_mail_gate()
    if gate is None:
        log.error(f"{LogTag.TOOL} GMAIL_FETCH_MESSAGES: no mail gate installed", todo_id=todo_id)
        return views
    kept = run_on_captured_loop(gate(user_id, todo_id, views))
    log.info(
        f"{LogTag.TOOL} GMAIL_FETCH_MESSAGES: mail passed its todo's gate",
        todo_id=todo_id,
        fetched=len(views),
        gate_skipped=len(views) - len(kept),
    )
    return kept


def _file_bound_views(views: list[GmailMessageView]) -> list[dict[str, object]]:
    """Every field of each message, for a result compaction spills to a file.

    Unprojected because a body query against a body-less file silently finds
    nothing; the in-context digest is compaction's, so no card renders either.
    """
    return [project_message_view(view, None) for view in views]


# =============================================================================
# FETCH_THREAD — full-conversation reconstruction by id
# =============================================================================


def _thread_needs_full(request: FetchThreadInput) -> bool:
    """Whether the thread fetch must request format=full.

    The thread endpoint returns every message inline, so unlike the per-message
    read there is no N+1 cost to full — one call per thread regardless. Full is
    needed for the body (any non-none processing) or the attachment list.
    """
    wants_attachments = bool(request.fields) and "attachments" in request.fields
    return request.body_processing != "none" or wants_attachments


def _fetch_one_thread(
    user_id: str, thread_id: str, *, needs_full: bool, body_processing: BodyProcessingLiteral
) -> list[GmailMessageView]:
    """Fetch one thread and return its messages as full views, in thread order.

    Reuses build_message_view so a thread message is shaped identically to a
    GMAIL_FETCH_MESSAGES result (normalized body, attachment metadata, same
    field contract) — one read path, not a divergent raw thread view. Lets proxy
    exceptions propagate so the aggregator attaches partial state.
    """
    data = _gmail_proxy(
        user_id,
        endpoint=f"{GMAIL_API_BASE}/users/me/threads/{thread_id}",
        method="GET",
        query={"format": GMAIL_FORMAT_FULL if needs_full else GMAIL_FORMAT_METADATA},
    )
    if not isinstance(data, dict):
        return []
    return [
        build_message_view(message, body_processing=body_processing)
        for message in GmailThreadData.model_validate(data).messages
    ]


def _aggregate_threads(
    user_id: str, request: FetchThreadInput
) -> tuple[list[tuple[str, list[GmailMessageView]]], list[GmailMessageView], bool]:
    """Fetch every requested thread over the bounded pool, honoring the total message cap.

    Returns (threads, flat_views, truncated) where threads keeps the
    per-thread grouping as (thread_id, views) and flat_views is every message
    view. Raises _PartialResultError on a mid-fetch error once anything succeeded.
    """
    needs_full = _thread_needs_full(request)
    cap = min(request.max_messages or MAX_ABSOLUTE_MESSAGES, MAX_ABSOLUTE_MESSAGES)
    threads: list[tuple[str, list[GmailMessageView]]] = []
    flat_views: list[GmailMessageView] = []
    truncated = False

    def fetch(thread_id: str) -> tuple[str, list[GmailMessageView]]:
        return thread_id, _fetch_one_thread(
            user_id, thread_id, needs_full=needs_full, body_processing=request.body_processing
        )

    try:
        with ContextThreadPoolExecutor(max_workers=FETCH_CONCURRENCY) as executor:
            for thread_id, views in executor.map(fetch, request.thread_ids):
                remaining = cap - len(flat_views)
                if remaining <= 0:
                    truncated = True
                    break
                if len(views) > remaining:
                    views = views[:remaining]
                    truncated = True
                threads.append((thread_id, views))
                flat_views.extend(views)
    except Exception as exc:
        if not flat_views:
            raise
        log.warning(
            "GMAIL_FETCH_THREAD: aborted mid-fetch",
            error=str(exc),
            error_type=type(exc).__name__,
            user_id=user_id,
        )
        raise _PartialResultError(reason=str(exc), partial_messages=flat_views) from exc

    return threads, flat_views, truncated


def _summarize_threads(
    user_id: str, request: FetchThreadInput
) -> GmailFetchThreadResult | GmailFetchPartialResult | GmailFetchInlineResult:
    """Top-level FETCH_THREAD orchestrator: fetch, then group by thread or return flat.

    Mirrors _fetch_and_shape: past OFFLOAD_MIN_MESSAGES the messages come back
    flat and whole (each carries its threadId), for compaction to file as records.
    """
    try:
        threads, flat_views, truncated = _aggregate_threads(user_id, request)
    except _PartialResultError as exc:
        return _format_partial_result(
            [project_message_view(view, request.fields) for view in exc.partial_messages],
            reason=exc.reason,
        )

    if len(flat_views) > OFFLOAD_MIN_MESSAGES:
        return _format_inline_result(_file_bound_views(flat_views), truncated=truncated)

    grouped: list[GmailThreadResult] = [
        {
            "id": thread_id,
            "message_count": len(views),
            "messages": [project_message_view(view, request.fields) for view in views],
        }
        for thread_id, views in threads
    ]
    _emit_email_card(flat_views)
    return {
        "fetched_threads": len(threads),
        "total_messages": len(flat_views),
        "truncated": truncated,
        "threads": grouped,
    }


# =============================================================================
# Batch label mutation — chunked + fail-loud
# =============================================================================


def _batch_modify(
    user_id: str,
    message_ids: list[str],
    *,
    add_label_ids: list[str] | None = None,
    remove_label_ids: list[str] | None = None,
) -> GmailBatchModifyResult:
    """Apply label add/removes across message_ids via batchModify, chunked at the Gmail 1000-id cap.

    Fail-loud + partial, mirroring _aggregate_pages: a first-chunk failure
    with nothing modified propagates as a total failure; once some chunks
    succeeded, the error surfaces as a partial result carrying the
    modified/failed counts.
    """
    if not message_ids:
        return {"modified_count": 0, "failed_count": 0}

    labels: dict[str, list[str]] = {}
    if add_label_ids:
        labels["addLabelIds"] = add_label_ids
    if remove_label_ids:
        labels["removeLabelIds"] = remove_label_ids

    modified = 0
    for start in range(0, len(message_ids), GMAIL_BATCH_MODIFY_CAP):
        chunk = message_ids[start : start + GMAIL_BATCH_MODIFY_CAP]
        try:
            _gmail_proxy(
                user_id,
                endpoint=f"{GMAIL_API_BASE}/users/me/messages/batchModify",
                method="POST",
                body={"ids": chunk, **labels},
            )
        except Exception as exc:
            if modified == 0:
                raise
            failed = len(message_ids) - modified
            log.set(
                gmail_batch_modify={
                    "requested": len(message_ids),
                    "modified": modified,
                    "failed": failed,
                }
            )
            log.warning(
                "GMAIL batchModify aborted after / modified",
                modified=modified,
                message_ids_count=len(message_ids),
                error=str(exc),
                error_type=type(exc).__name__,
                user_id=user_id,
            )
            return {
                "modified_count": modified,
                "failed_count": failed,
                "partial": True,
                "error": str(exc),
            }
        modified += len(chunk)

    log.set(gmail_batch_modify={"requested": len(message_ids), "modified": modified, "failed": 0})
    return {"modified_count": modified, "failed_count": 0}


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
    """Lightweight count via maxResults=1 — uses resultSizeEstimate."""
    params: _GmailQuery = {
        "maxResults": 1,
        "includeSpamTrash": str(include_spam_trash).lower(),
        "q": query,
    }
    if label_ids:
        params["labelIds"] = label_ids

    data = GmailMessagesListResponse.model_validate(
        _gmail_proxy(
            user_id,
            endpoint=f"{GMAIL_API_BASE}/users/me/messages",
            method="GET",
            query=params,
        )
        or {}
    )
    # Gmail omits resultSizeEstimate on some empty responses; the page's own
    # message count is the fallback, exactly as before.
    if data.result_size_estimate is not None:
        return max(0, data.result_size_estimate)
    return len(data.messages)


def _label_stats(user_id: str, label_id: str) -> GmailLabelCounts:
    label = _gmail_label(user_id, label_id)
    return {
        "label_id": label_id,
        "label_name": label.name if label.name is not None else label_id,
        "unreadCount": label.messages_unread,
        "totalCount": label.messages_total,
    }


def _gmail_label(user_id: str, label_id: str) -> GmailLabelDetail:
    return GmailLabelDetail.model_validate(
        _gmail_proxy(
            user_id,
            endpoint=f"{GMAIL_API_BASE}/users/me/labels/{label_id}",
            method="GET",
        )
        or {}
    )


def _gmail_user_profile(user_id: str) -> GmailProfile:
    return GmailProfile.model_validate(
        _gmail_proxy(
            user_id,
            endpoint=f"{GMAIL_API_BASE}/users/me/profile",
            method="GET",
        )
        or {}
    )


def _recent_inbox_ids(user_id: str, *, since: str | None, max_results: int) -> list[str]:
    messages_query: _GmailQuery = {"labelIds": "INBOX", "maxResults": max_results}
    if since:
        try:
            since_ts = int(datetime.datetime.fromisoformat(since).timestamp())
        except ValueError as exc:
            raise AppError(
                message=f"Invalid 'since' value: {since!r}",
                why="GMAIL_CUSTOM_GATHER_CONTEXT received a 'since' that is not an ISO-8601 datetime.",
                fix="Pass an ISO-8601 datetime such as 2026-06-19T00:00:00Z.",
                status_code=400,
            ) from exc
        messages_query["q"] = f"after:{since_ts}"
    messages_data = GmailMessagesListResponse.model_validate(
        _gmail_proxy(
            user_id,
            endpoint=f"{GMAIL_API_BASE}/users/me/messages",
            method="GET",
            query=messages_query,
        )
        or {}
    )
    return [ref.id for ref in messages_data.messages if ref.id]


def register_gmail_custom_tools(composio: Composio) -> list[str]:
    """Register custom Gmail tools with the Composio client. Returns the registered tool names."""

    @composio.tools.custom_tool(toolkit="gmail")
    def MARK_AS_READ(
        request: MarkAsReadInput,
        execute_request: ExecuteRequestFn,
        auth_credentials: dict[str, object],
    ) -> GmailBatchModifyResult:
        """Mark Gmail messages as read (removes the UNREAD label)."""
        return _batch_modify(
            CustomToolAuthCredentials.parse(auth_credentials).user_id,
            request.message_ids,
            remove_label_ids=["UNREAD"],
        )

    @composio.tools.custom_tool(toolkit="gmail")
    def MARK_AS_UNREAD(
        request: MarkAsUnreadInput,
        execute_request: ExecuteRequestFn,
        auth_credentials: dict[str, object],
    ) -> GmailBatchModifyResult:
        """Mark Gmail messages as unread (adds the UNREAD label)."""
        return _batch_modify(
            CustomToolAuthCredentials.parse(auth_credentials).user_id,
            request.message_ids,
            add_label_ids=["UNREAD"],
        )

    @composio.tools.custom_tool(toolkit="gmail")
    def ARCHIVE_EMAIL(
        request: ArchiveEmailInput,
        execute_request: ExecuteRequestFn,
        auth_credentials: dict[str, object],
    ) -> GmailBatchModifyResult:
        """Archive Gmail messages (removes the INBOX label, moving to All Mail)."""
        return _batch_modify(
            CustomToolAuthCredentials.parse(auth_credentials).user_id,
            request.message_ids,
            remove_label_ids=["INBOX"],
        )

    @composio.tools.custom_tool(toolkit="gmail")
    def STAR_EMAIL(
        request: StarEmailInput,
        execute_request: ExecuteRequestFn,
        auth_credentials: dict[str, object],
    ) -> GmailStarResult:
        """Star or unstar Gmail messages (adds/removes the STARRED label)."""
        user_id = CustomToolAuthCredentials.parse(auth_credentials).user_id
        if request.unstar:
            unstarred = _batch_modify(user_id, request.message_ids, remove_label_ids=["STARRED"])
            return {"action": "unstarred", **unstarred}
        starred = _batch_modify(user_id, request.message_ids, add_label_ids=["STARRED"])
        return {"action": "starred", **starred}

    @composio.tools.custom_tool(toolkit="gmail")
    def GET_UNREAD_COUNT(
        request: GetUnreadCountInput,
        execute_request: ExecuteRequestFn,
        auth_credentials: dict[str, object],
    ) -> GmailUnreadQueryCounts | GmailUnreadLabelCounts:
        """Get message counts using lightweight Gmail APIs.

        Supports two modes:
        1) Label mode (default): returns per-label unread + total counts
        2) Query mode: returns count estimates for a Gmail search query,
           with an unread-filtered estimate as well
        """
        user_id = CustomToolAuthCredentials.parse(auth_credentials).user_id
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
        execute_request: ExecuteRequestFn,
        auth_credentials: dict[str, object],
    ) -> GmailContactList:
        """Extract unique contacts from email history matching a Gmail search query."""
        user_id = CustomToolAuthCredentials.parse(auth_credentials).user_id

        list_response = GmailMessagesListResponse.model_validate(
            _gmail_proxy(
                user_id,
                endpoint=f"{GMAIL_API_BASE}/users/me/messages",
                method="GET",
                query={"q": request.query, "maxResults": request.max_results},
            )
            or {}
        )
        message_ids = [ref.id for ref in list_response.messages if ref.id]

        messages, fetch_failures = _fetch_messages_for_contacts(user_id, message_ids)

        if message_ids and not messages:
            log.error(
                f"{LogTag.COMPOSIO} Gmail contact list: all message fetches failed for user",
                message_ids_count=len(message_ids),
                user_id=user_id,
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
        execute_request: ExecuteRequestFn,
        auth_credentials: dict[str, object],
    ) -> GmailContextSnapshot:
        """Get Gmail context snapshot: profile info, inbox unread count, and recent message IDs.

        Zero required parameters. Returns current user's Gmail state for situational awareness.
        """
        user_id = CustomToolAuthCredentials.parse(auth_credentials).user_id
        profile = _gmail_user_profile(user_id)
        inbox = _gmail_label(user_id, "INBOX")
        recent_ids = _recent_inbox_ids(user_id, since=request.since, max_results=5)

        return {
            "user": {
                "email": profile.email_address,
                "messages_total": profile.messages_total,
                "threads_total": profile.threads_total,
            },
            "inbox": {
                "unread_count": inbox.messages_unread,
                "message_count": inbox.messages_total,
            },
            "recent_message_ids": recent_ids,
        }

    @composio.tools.custom_tool(toolkit="gmail")
    def FETCH_MESSAGES(
        request: FetchMessagesInput,
        execute_request: ExecuteRequestFn,
        auth_credentials: dict[str, object],
    ) -> dict[str, object]:
        """Fetch Gmail messages matching a query/timeframe, exhaustively.

        The canonical read tool. Server-side paginates the Gmail API and
        returns the full set of matching messages in one call, so a
        nextPageToken never escapes the process and results are never
        silently capped (unlike a single fixed-size list fetch).

        Supports a ``timeframe`` convenience enum (``today``, ``7d``,
        ``this_week``, etc.) resolved to Gmail's after:/before: operators
        in the user's home timezone (read from the run's LangGraph
        ``configurable``).

        Small results render the inbox email-list card in chat. Past
        OFFLOAD_MIN_MESSAGES every message comes back whole, and compaction
        files them as JSONL records the agent mines with ``query_json``/``grep``.

        Every result carries ``fetched_at``, the Unix second the query ran:
        query ``after:<fetched_at>`` next time to fetch only newer mail.
        """
        return _summarize(CustomToolAuthCredentials.parse(auth_credentials).user_id, request)

    @composio.tools.custom_tool(toolkit="gmail")
    def FETCH_THREAD(
        request: FetchThreadInput,
        execute_request: ExecuteRequestFn,
        auth_credentials: dict[str, object],
    ) -> GmailFetchThreadResult | GmailFetchPartialResult | GmailFetchInlineResult:
        """Reconstruct one or more Gmail conversation threads by id.

        The canonical thread-read tool. Fetches each ``thread_id`` (batched,
        concurrently) and returns its messages in conversation order, shaped
        exactly like ``GMAIL_FETCH_MESSAGES`` results: normalized body,
        attachment metadata, same ``fields``/``body_processing`` contract, so
        there is one read path, not a divergent raw thread view.

        Get thread ids from the ``threadId`` on ``GMAIL_FETCH_MESSAGES``
        results. Small results render the email-list card, grouped by thread;
        large ones come back flat (each message carrying ``threadId`` to
        regroup) for compaction to file as JSONL records.
        """
        return _summarize_threads(
            CustomToolAuthCredentials.parse(auth_credentials).user_id, request
        )

    return [
        "GMAIL_MARK_AS_READ",
        "GMAIL_MARK_AS_UNREAD",
        "GMAIL_ARCHIVE_EMAIL",
        "GMAIL_STAR_EMAIL",
        "GMAIL_GET_UNREAD_COUNT",
        "GMAIL_GET_CONTACT_LIST",
        "GMAIL_CUSTOM_GATHER_CONTEXT",
        "GMAIL_FETCH_MESSAGES",
        "GMAIL_FETCH_THREAD",
    ]


# =============================================================================
# GET_UNREAD_COUNT sub-helpers
# =============================================================================


def _unread_count_query_mode(
    user_id: str,
    query: str,
    resolved_label_ids: list[str],
    include_spam_trash: bool,
) -> GmailUnreadQueryCounts:
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

    result: GmailUnreadQueryCounts = {
        "query": query,
        "label_ids": resolved_label_ids,
        "totalCount": total_count,
        "unreadCount": unread_count,
        "is_estimate": True,
    }
    if len(resolved_label_ids) == 1:
        result["label_id"] = resolved_label_ids[0]
    return result


def _unread_count_label_mode(user_id: str, resolved_label_ids: list[str]) -> GmailUnreadLabelCounts:
    if not resolved_label_ids:
        return {
            "counts": {},
            "label_ids": [],
            "unreadCount": 0,
            "totalCount": 0,
        }

    counts: dict[str, GmailLabelCounts] = {
        label_id: _label_stats(user_id, label_id) for label_id in resolved_label_ids
    }

    if len(resolved_label_ids) == 1:
        label_id = resolved_label_ids[0]
        label_stats: GmailLabelCounts = counts[label_id]
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
) -> tuple[list[GmailApiMessage], int]:
    """Fetch each message's metadata headers needed for contact extraction.

    Returns (messages, fetch_failures). fetch_failures is the count of
    ids that raised — the caller decides whether to surface that to the
    user.
    """
    messages: list[GmailApiMessage] = []
    fetch_failures = 0
    for message_id in message_ids:
        try:
            full = _gmail_proxy(
                user_id,
                endpoint=f"{GMAIL_API_BASE}/users/me/messages/{message_id}",
                method="GET",
                query={
                    "format": GMAIL_FORMAT_METADATA,
                    "metadataHeaders": ["From", "To", "Cc", "Reply-To"],
                },
            )
            if isinstance(full, dict):
                messages.append(GmailApiMessage.model_validate(full))
        except Exception as exc:
            fetch_failures += 1
            log.warning(
                f"{LogTag.COMPOSIO} Gmail message fetch failed for",
                message_id=message_id,
                error=str(exc),
                error_type=type(exc).__name__,
                user_id=user_id,
            )
    return messages, fetch_failures
