"""Gmail custom tools using Composio custom tool infrastructure.

All Gmail API calls go through Composio's proxy via `proxy_request_sync`.
The proxy attaches the user's OAuth token server-side; tools only need
`user_id` from `auth_credentials`.
"""

from collections.abc import Sequence
from concurrent.futures import ThreadPoolExecutor
import datetime
import json
import math
import re
from typing import Any, cast
import uuid

from composio import Composio
from composio.types import ExecuteRequestFn
from langchain_core.runnables import RunnableConfig
from langgraph.config import get_stream_writer
from pydantic import BaseModel, Field

from app.agents.templates.mail_templates import (
    build_message_view,
    message_view_needs_body,
    project_message_view,
)
from app.agents.workspace.offload import OffloadInfo
from app.constants.email import MessageFieldLiteral
from app.constants.log_tags import LogTag
from app.constants.offload import OFFLOAD_RESULT_KEY
from app.models.agent_models import agent_configurable, current_run_config
from app.models.common_models import GatherContextInput
from app.models.composio_schemas.gmail import (
    BodyProcessingLiteral,
    FetchMessagesInput,
    FetchThreadInput,
    GmailBatchModifyResult,
    GmailLabelCounts,
    GmailLabelDetail,
    GmailMessagesListResponse,
    GmailProfile,
    GmailReadChunk,
    GmailReadPlan,
    TimeframeLiteral,
)
from app.services.composio.custom_tools.gmail_constants import (
    _DAYS_PER_UNIT,
    CHUNK_TARGET_BYTES,
    CHUNK_TARGET_MESSAGES,
    FETCH_CONCURRENCY,
    GMAIL_API_BASE,
    GMAIL_BATCH_MODIFY_CAP,
    GMAIL_FORMAT_FULL,
    GMAIL_FORMAT_METADATA,
    GMAIL_TOOLKIT,
    INLINE_LIMIT_CHARS,
    MAX_ABSOLUTE_MESSAGES,
    MAX_READ_SUBAGENTS,
    OFFLOAD_DIR,
    OFFLOAD_FILE_PREFIX,
    OFFLOAD_MIN_MESSAGES,
    OFFLOAD_PREVIEW_SIZE,
    TIMEFRAME_DEFAULT_MAX,
)
from app.services.composio.proxy_client import ProxyMethod, proxy_request_sync
from app.services.contact_service import build_contact_index
from app.services.storage.juicefs import write_session_file_sync
from app.utils.errors import AppError
from app.utils.timezone import Timezone, home_timezone_from_config
from shared.py.wide_events import log

# =============================================================================
# Shared helpers
# =============================================================================


def _user_id(auth_credentials: dict[str, Any]) -> str:
    user_id = auth_credentials.get("user_id")
    if not user_id:
        raise ValueError("Missing user_id in auth_credentials")
    return cast(str, user_id)


def _gmail_proxy(
    user_id: str,
    *,
    endpoint: str,
    method: ProxyMethod,
    body: dict[str, Any] | None = None,
    query: dict[str, Any] | None = None,
) -> object:
    """Send one Gmail REST request through the Composio proxy.

    Returns ``object``, not ``Any``: each Gmail endpoint answers with a
    different JSON shape, so the honest type is "something was parsed" — and
    ``object`` forces every caller to validate it into a real model (or narrow
    it) before reading a single field off it.
    """
    return proxy_request_sync(
        user_id=user_id,
        toolkit=GMAIL_TOOLKIT,
        endpoint=endpoint,
        method=method,
        body=body,
        query=query,
    )


def _conversation_id(config: RunnableConfig) -> str | None:
    """Pull the session id (vfs_session_id / thread_id) from the run config.

    The session id lives in the LangGraph ``configurable``, not in the Composio
    ``auth_credentials`` dict (which only carries OAuth state plus the injected
    ``user_id``). Mirrors the conversation-id resolution in the compaction /
    summarization middleware.
    """
    configurable = agent_configurable(config)
    return cast("str | None", configurable.get("vfs_session_id") or configurable.get("thread_id"))


# =============================================================================
# FETCH_MESSAGES — timeframe resolution
# =============================================================================


def _timeframe_clause(timeframe: TimeframeLiteral, tz: Timezone) -> str:
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
        # "last N days" is inclusive of today, so the window spans N calendar
        # days: [today - (N-1), today]. _date_window_clause makes the end
        # exclusive (today + 1).
        start = today - datetime.timedelta(days=days - 1)
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
    timeframe: TimeframeLiteral | None,
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

    Caught at the top of ``FETCH_MESSAGES`` and rendered as a
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
) -> GmailMessagesListResponse:
    """Return the next ``users.me.messages`` page, validated at the proxy boundary.

    Lets proxy exceptions propagate; the aggregator attaches the
    partial-state context (already-fetched messages) before re-raising.
    """
    params: dict[str, Any] = {"q": query, "maxResults": per_page}
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
    force_body: bool = False,
) -> dict[str, Any] | None:
    """Fetch one message and build its full (unprojected) view.

    Requests ``format=metadata`` (headers + labels + snippet, no MIME payload)
    unless the caller's field selection will actually carry a body — the
    default field set doesn't, so the payload download and MIME decode are
    skipped on that path. Projection to the caller-requested fields happens
    in ``_summarize`` so the email card keeps id/threadId/time regardless of
    the selection.

    ``force_body`` overrides the metadata skip to fetch and normalize the body
    even when ``fields`` omits it — used on the offload path so the JSONL the
    agent mines with ``query_json``/``grep`` actually carries the body
    (``body_processing="none"`` still wins: an explicit no-body request is
    honored).

    Returns None if the proxy returned something that isn't a dict (we
    don't fail the whole tool call on a single weird response). Lets
    proxy exceptions propagate; the aggregator attaches the partial-
    state context before re-raising.
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
    return build_message_view(full, body_processing=body_processing if needs_body else "none")


def _aggregate_pages(
    user_id: str,
    request: FetchMessagesInput,
    *,
    combined_query: str,
    effective_max: int,
) -> tuple[list[dict[str, Any]], bool]:
    """Drive the list→fetch loop until exhausted, capped, or errored.

    Per-message fetches within a page fan out over a bounded thread pool
    (``FETCH_CONCURRENCY``); results keep the page order. Returns
    ``(messages, truncated)`` where messages are full (unprojected) views.
    Raises ``_PartialResultError`` for mid-loop errors, carrying the messages
    already aggregated.
    """
    all_messages: list[dict[str, Any]] = []
    page_token: str | None = None
    truncated = False
    # Resolved from the first list page's resultSizeEstimate: when the scan is
    # headed for offload, we fetch the body up front (one pass, no extra calls)
    # so the offloaded JSONL is minable. Off for an explicit no-body request.
    force_body = False

    def fetch_view(message_id: str) -> dict[str, Any] | None:
        return _fetch_message_view(
            user_id,
            message_id,
            fields=request.fields,
            body_processing=request.body_processing,
            force_body=force_body,
        )

    try:
        with ThreadPoolExecutor(max_workers=FETCH_CONCURRENCY) as executor:
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
                    expected = min(estimate, effective_max) if estimate is not None else 0
                    force_body = (
                        expected > OFFLOAD_MIN_MESSAGES and request.body_processing != "none"
                    )
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
            # Nothing was fetched before the error — this is a total failure
            # (e.g. an expired/missing Gmail connection rejected the very first
            # request), not a partial result. Let it propagate so the tool
            # reports `successful: false` instead of masking it as an empty
            # inbox.
            raise
        log.warning(
            "GMAIL_FETCH_MESSAGES: pagination aborted mid-loop",
            error=str(exc),
            error_type=type(exc).__name__,
            user_id=user_id,
        )
        raise _PartialResultError(reason=str(exc), partial_messages=all_messages) from exc

    return all_messages, truncated


def _offload_path() -> str:
    """Build a timestamped, unique offload path (relative to the session root)."""
    ts = datetime.datetime.now(datetime.UTC).strftime("%Y%m%d_%H%M%S")
    return f"{OFFLOAD_DIR}/{OFFLOAD_FILE_PREFIX}{ts}_{uuid.uuid4().hex[:8]}.jsonl"


def _human_size(num_bytes: int) -> str:
    """Format a byte count as a short human-readable string (KB/MB)."""
    if num_bytes < 1024:
        return f"{num_bytes} B"
    if num_bytes < 1024 * 1024:
        return f"{num_bytes / 1024:.0f} KB"
    return f"{num_bytes / (1024 * 1024):.1f} MB"


def _build_read_plan(total_messages: int, file_size_bytes: int) -> GmailReadPlan:
    """Split the offloaded JSONL into contiguous line-range chunks for parallel
    subagent reads.

    The file is one message per line, so a chunk maps directly to a
    ``read(offset, limit)`` call. Chunk count is the larger of the by-message
    and by-byte estimates (so both "many small" and "few huge" inboxes split
    sensibly), capped at MAX_READ_SUBAGENTS.
    """
    if total_messages <= 0:
        return {"total_lines": 0, "recommended_subagents": 0, "chunks": []}

    by_messages = math.ceil(total_messages / CHUNK_TARGET_MESSAGES)
    by_bytes = math.ceil(file_size_bytes / CHUNK_TARGET_BYTES) if file_size_bytes else 1
    num_chunks = min(MAX_READ_SUBAGENTS, max(1, by_messages, by_bytes))

    base, remainder = divmod(total_messages, num_chunks)
    chunks: list[GmailReadChunk] = []
    start = 1
    for index in range(num_chunks):
        count = base + (1 if index < remainder else 0)
        if count == 0:
            break
        chunks.append(
            {
                "part": len(chunks) + 1,
                "start_line": start,
                "line_count": count,
                "read": {"offset": start, "limit": count},
            }
        )
        start += count

    return {
        "total_lines": total_messages,
        "recommended_subagents": len(chunks),
        "chunks": chunks,
    }


def _format_offload_result(
    views: list[dict[str, Any]],
    *,
    truncated: bool,
    user_id: str,
    conversation_id: str,
    fields: Sequence[MessageFieldLiteral] | None,
    producer: str = "GMAIL_FETCH_MESSAGES",
) -> dict[str, Any]:
    """Write the full (unprojected) message views to a session JSONL file and
    return a digest plus a read-plan the subagent can fan out across parallel
    readers.

    The file carries every field — id, all headers, labels, and the normalized
    body — regardless of the caller's inline ``fields`` projection, because the
    offload exists precisely to be mined downstream (``query_json``/``grep``);
    a body query against a body-less file would silently find nothing. The
    inline ``preview`` is projected to ``fields`` to keep the in-context peek
    small.
    """
    rel_path = _offload_path()
    body = "\n".join(json.dumps(v, default=str) for v in views)
    file_size_bytes = len(body.encode("utf-8"))
    _, sandbox_path = write_session_file_sync(
        user_id=user_id,
        conversation_id=conversation_id,
        relative_path=rel_path,
        content=body,
    )
    read_plan = _build_read_plan(len(views), file_size_bytes)
    preview = [project_message_view(v, fields) for v in views[:OFFLOAD_PREVIEW_SIZE]]
    field_count = len(views[0]) if views else 0
    offload: OffloadInfo = {
        "path": sandbox_path,
        "bytes": file_size_bytes,
        "fmt": "jsonl",
        "producer": producer,
        "records": len(views),
    }
    return {
        "total_messages": len(views),
        "truncated": truncated,
        "offloaded_to": sandbox_path,
        "file_size_bytes": file_size_bytes,
        "file_size_human": _human_size(file_size_bytes),
        "field_count": field_count,
        "inline_preview": preview,
        "read_plan": read_plan,
        "hint": (
            f"{len(views)} messages ({_human_size(file_size_bytes)}) written to "
            f"{sandbox_path} (JSONL, one message per line, every field incl. the "
            f"normalized body). Too large to read inline. Spawn "
            f"{read_plan['recommended_subagents']} subagent(s) to read the line "
            f"ranges in read_plan.chunks in parallel (read offset/limit), each "
            f"triaging its slice, then merge. Or mine the file directly with the "
            f"`query_json` tool, e.g. query_json(path='{sandbox_path}', "
            f'where=[{{"field":"from","op":"contains","value":"github"}}], '
            f"fields=['subject','from']); the body is searchable too, e.g. "
            f'where=[{{"field":"body","op":"contains","value":"invoice"}}].'
        ),
        # Lifted into the structured offload marker by the tool node (this tool
        # returns a dict and cannot set additional_kwargs itself); stripped from
        # the model-facing content. Drives the query_json/grep auto-bind on offload.
        OFFLOAD_RESULT_KEY: offload,
    }


def _emit_email_card(views: list[dict[str, Any]]) -> None:
    """Stream the interactive email-list card to the chat for an inline result.

    Mirrors what the old GMAIL_FETCH_EMAILS after-hook rendered. Takes the
    full (unprojected) views so the card keeps id/threadId/time even when the
    caller narrowed ``fields``. No active run (background/silent execution,
    tests) just means no card; the data is still returned to the agent.
    """
    if not views:
        return
    try:
        writer = get_stream_writer()
    except RuntimeError:
        # No runnable context (background/silent/test): streaming unavailable.
        return
    if writer is None:
        return
    email_fetch_data = [
        {
            "from": view.get("from", ""),
            "subject": view.get("subject", ""),
            "time": view.get("time", ""),
            "thread_id": view.get("threadId", ""),
            "id": view.get("id", ""),
        }
        for view in views
    ]
    writer({"email_fetch_data": email_fetch_data, "resultSize": len(email_fetch_data)})


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


def _count_inline_fit(messages: list[dict[str, Any]]) -> int:
    """How many whole leading messages fit under ``INLINE_LIMIT_CHARS``."""
    budget = INLINE_LIMIT_CHARS
    count = 0
    for message in messages:
        budget -= len(json.dumps(message, default=str)) + 2  # +2 for separators
        if budget < 0:
            break
        count += 1
    return count


def _summarize(
    user_id: str,
    request: FetchMessagesInput,
) -> dict[str, Any]:
    """Top-level orchestrator: resolve → paginate → offload-or-inline."""
    config = current_run_config()
    tz = home_timezone_from_config(config)
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

    messages = [project_message_view(view, request.fields) for view in full_views]
    serialized = json.dumps({"messages": messages}, default=str)
    over_char_limit = len(serialized) > INLINE_LIMIT_CHARS
    over_message_limit = len(messages) > OFFLOAD_MIN_MESSAGES
    if not over_char_limit and not over_message_limit:
        _emit_email_card(full_views)
        return _format_inline_result(messages, truncated=truncated)

    conversation_id = _conversation_id(config)
    if conversation_id is None:
        return _no_session_inline_fallback(full_views, messages, truncated=truncated)

    return _format_offload_result(
        full_views,
        truncated=truncated,
        user_id=user_id,
        conversation_id=conversation_id,
        fields=request.fields,
    )


def _no_session_inline_fallback(
    full_views: list[dict[str, Any]],
    projected: list[dict[str, Any]],
    *,
    truncated: bool,
) -> dict[str, Any]:
    """Oversized result but no session to offload into: cap to whole messages
    that fit inline and surface that the rest was dropped.

    The self-offloading Gmail read tools are excluded from the compaction
    middleware (``SELF_OFFLOADING_TOOL_NAMES`` in factory.py), so nothing
    downstream shrinks an oversized inline result — the cap has to happen here.
    """
    shown = _count_inline_fit(projected)
    log.warning(
        "GMAIL read: no conversation_id for offload; returning / inline",
        shown=shown,
        projected_count=len(projected),
    )
    _emit_email_card(full_views[:shown])
    result = _format_inline_result(projected[:shown], truncated=truncated or shown < len(projected))
    if shown < len(projected):
        result["total_matched"] = len(projected)
        result["hint"] = (
            f"Showing {shown} of {len(projected)} matched messages; the result was too "
            f"large to return inline and no session was available to offload it. Narrow "
            f"the request (or reduce fields) to see the rest."
        )
    return result


# =============================================================================
# FETCH_THREAD — full-conversation reconstruction by id
# =============================================================================


def _thread_needs_full(request: FetchThreadInput) -> bool:
    """Whether the thread fetch must request ``format=full``.

    The thread endpoint returns every message inline, so unlike the per-message
    read there is no N+1 cost to full — one call per thread regardless. Full is
    needed for the body (any non-``none`` processing) or the attachment list.
    """
    wants_attachments = bool(request.fields) and "attachments" in request.fields
    return request.body_processing != "none" or wants_attachments


def _fetch_one_thread(
    user_id: str, thread_id: str, *, needs_full: bool, body_processing: BodyProcessingLiteral
) -> list[dict[str, Any]]:
    """Fetch one thread and return its messages as full views, in thread order.

    Reuses ``build_message_view`` so a thread message is shaped identically to a
    ``GMAIL_FETCH_MESSAGES`` result (normalized body, attachment metadata, same
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
        build_message_view(msg, body_processing=body_processing)
        for msg in data.get("messages", [])
        if isinstance(msg, dict)
    ]


def _aggregate_threads(
    user_id: str, request: FetchThreadInput
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], bool]:
    """Fetch every requested thread over the bounded pool, honoring the total
    message cap. Returns ``(threads, flat_views, truncated)`` where ``threads``
    keeps the per-thread grouping and ``flat_views`` is every message view.
    Raises ``_PartialResultError`` on a mid-fetch error once anything succeeded.
    """
    needs_full = _thread_needs_full(request)
    cap = min(request.max_messages or MAX_ABSOLUTE_MESSAGES, MAX_ABSOLUTE_MESSAGES)
    threads: list[dict[str, Any]] = []
    flat_views: list[dict[str, Any]] = []
    truncated = False

    def fetch(thread_id: str) -> tuple[str, list[dict[str, Any]]]:
        return thread_id, _fetch_one_thread(
            user_id, thread_id, needs_full=needs_full, body_processing=request.body_processing
        )

    try:
        with ThreadPoolExecutor(max_workers=FETCH_CONCURRENCY) as executor:
            for thread_id, views in executor.map(fetch, request.thread_ids):
                remaining = cap - len(flat_views)
                if remaining <= 0:
                    truncated = True
                    break
                if len(views) > remaining:
                    views = views[:remaining]
                    truncated = True
                threads.append({"id": thread_id, "message_count": len(views), "messages": views})
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


def _summarize_threads(user_id: str, request: FetchThreadInput) -> dict[str, Any]:
    """Top-level FETCH_THREAD orchestrator: fetch → offload-or-inline, mirroring
    ``_summarize`` (same thresholds, card, offload file, no-session fallback)."""
    config = current_run_config()
    try:
        threads, flat_views, truncated = _aggregate_threads(user_id, request)
    except _PartialResultError as exc:
        return _format_partial_result(
            [project_message_view(view, request.fields) for view in exc.partial_messages],
            reason=exc.reason,
        )

    grouped = [
        {
            "id": thread["id"],
            "message_count": thread["message_count"],
            "messages": [project_message_view(view, request.fields) for view in thread["messages"]],
        }
        for thread in threads
    ]
    projected_flat = [project_message_view(view, request.fields) for view in flat_views]
    serialized = json.dumps({"threads": grouped}, default=str)
    over_char_limit = len(serialized) > INLINE_LIMIT_CHARS
    over_message_limit = len(flat_views) > OFFLOAD_MIN_MESSAGES
    if not over_char_limit and not over_message_limit:
        _emit_email_card(flat_views)
        return {
            "fetched_threads": len(threads),
            "total_messages": len(flat_views),
            "truncated": truncated,
            "threads": grouped,
        }

    conversation_id = _conversation_id(config)
    if conversation_id is None:
        return _no_session_inline_fallback(flat_views, projected_flat, truncated=truncated)

    result = _format_offload_result(
        flat_views,
        truncated=truncated,
        user_id=user_id,
        conversation_id=conversation_id,
        fields=request.fields,
        producer="GMAIL_FETCH_THREAD",
    )
    result["total_threads"] = len(threads)
    return result


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
    """Apply label add/removes across ``message_ids`` via ``batchModify``,
    chunked at the Gmail 1000-id cap.

    Fail-loud + partial, mirroring ``_aggregate_pages``: if the first chunk
    fails with nothing yet modified it is a total failure and propagates (the
    tool reports ``successful: false`` rather than masking it); if some chunks
    already succeeded, the error is surfaced as a partial result carrying the
    modified/failed counts. Returns ``{modified_count, failed_count[, partial,
    error]}``.
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
    """Lightweight count via ``maxResults=1`` — uses ``resultSizeEstimate``."""
    params: dict[str, Any] = {
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
    messages_query: dict[str, Any] = {"labelIds": "INBOX", "maxResults": max_results}
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
        auth_credentials: dict[str, Any],
    ) -> GmailBatchModifyResult:
        """Mark Gmail messages as read (removes the UNREAD label)."""
        return _batch_modify(
            _user_id(auth_credentials),
            request.message_ids,
            remove_label_ids=["UNREAD"],
        )

    @composio.tools.custom_tool(toolkit="gmail")
    def MARK_AS_UNREAD(
        request: MarkAsUnreadInput,
        execute_request: ExecuteRequestFn,
        auth_credentials: dict[str, Any],
    ) -> GmailBatchModifyResult:
        """Mark Gmail messages as unread (adds the UNREAD label)."""
        return _batch_modify(
            _user_id(auth_credentials),
            request.message_ids,
            add_label_ids=["UNREAD"],
        )

    @composio.tools.custom_tool(toolkit="gmail")
    def ARCHIVE_EMAIL(
        request: ArchiveEmailInput,
        execute_request: ExecuteRequestFn,
        auth_credentials: dict[str, Any],
    ) -> GmailBatchModifyResult:
        """Archive Gmail messages (removes the INBOX label, moving to All Mail)."""
        return _batch_modify(
            _user_id(auth_credentials),
            request.message_ids,
            remove_label_ids=["INBOX"],
        )

    @composio.tools.custom_tool(toolkit="gmail")
    def STAR_EMAIL(
        request: StarEmailInput,
        execute_request: ExecuteRequestFn,
        auth_credentials: dict[str, Any],
    ) -> dict[str, Any]:
        """Star or unstar Gmail messages (adds/removes the STARRED label)."""
        user_id = _user_id(auth_credentials)
        if request.unstar:
            result = _batch_modify(user_id, request.message_ids, remove_label_ids=["STARRED"])
            action = "unstarred"
        else:
            result = _batch_modify(user_id, request.message_ids, add_label_ids=["STARRED"])
            action = "starred"
        return {"action": action, **result}

    @composio.tools.custom_tool(toolkit="gmail")
    def GET_UNREAD_COUNT(
        request: GetUnreadCountInput,
        execute_request: ExecuteRequestFn,
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
        execute_request: ExecuteRequestFn,
        auth_credentials: dict[str, Any],
    ) -> dict[str, Any]:
        """Extract unique contacts from email history matching a Gmail search query."""
        user_id = _user_id(auth_credentials)

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
        auth_credentials: dict[str, Any],
    ) -> dict[str, Any]:
        """Get Gmail context snapshot: profile info, inbox unread count, and recent message IDs.

        Zero required parameters. Returns current user's Gmail state for situational awareness.
        """
        user_id = _user_id(auth_credentials)
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
        auth_credentials: dict[str, Any],
    ) -> dict[str, Any]:
        """Fetch Gmail messages matching a query/timeframe, exhaustively.

        The canonical read tool. Server-side paginates the Gmail API and
        returns the full set of matching messages in one call, so a
        nextPageToken never escapes the process and results are never
        silently capped (unlike a single fixed-size list fetch).

        Supports a ``timeframe`` convenience enum (``today``, ``7d``,
        ``this_week``, etc.) resolved to Gmail's after:/before: operators
        in the user's home timezone (read from the run's LangGraph
        ``configurable``).

        Small results render the inbox email-list card in chat and are
        returned inline. When the aggregate is too large to inline, the
        tool writes a JSONL file to the session workspace and returns a
        digest + read_plan; the agent fans out parallel reads over the
        chunks or mines it with ``query_json``/``grep``.
        """
        return _summarize(_user_id(auth_credentials), request)

    @composio.tools.custom_tool(toolkit="gmail")
    def FETCH_THREAD(
        request: FetchThreadInput,
        execute_request: ExecuteRequestFn,
        auth_credentials: dict[str, Any],
    ) -> dict[str, Any]:
        """Reconstruct one or more Gmail conversation threads by id.

        The canonical thread-read tool. Fetches each ``thread_id`` (batched,
        concurrently) and returns its messages in conversation order, shaped
        exactly like ``GMAIL_FETCH_MESSAGES`` results: normalized body,
        attachment metadata, same ``fields``/``body_processing`` contract, so
        there is one read path, not a divergent raw thread view.

        Get thread ids from the ``threadId`` on ``GMAIL_FETCH_MESSAGES``
        results. Small results render the email-list card inline; large ones
        offload to a JSONL file (each line a message, carrying ``threadId`` to
        regroup) with a read_plan the agent mines with ``query_json``/``grep``.
        """
        return _summarize_threads(_user_id(auth_credentials), request)

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

    counts: dict[str, GmailLabelCounts] = {
        label_id: _label_stats(user_id, label_id) for label_id in resolved_label_ids
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
                    "format": GMAIL_FORMAT_METADATA,
                    "metadataHeaders": ["From", "To", "Cc", "Reply-To"],
                },
            )
            if isinstance(full, dict):
                messages.append(full)
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
