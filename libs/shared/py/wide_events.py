"""
Wide event logging — one context-rich structured event per request.

╔══════════════════════════════════════════════════════════════════════════╗
║ CROSS-RUNTIME CONTRACT — MIRROR EVERY SHAPE CHANGE IN TYPESCRIPT         ║
║                                                                          ║
║ This file is ONE HALF of GAIA's wide-event shape. The other half is      ║
║   libs/shared/ts/src/bots/utils/wide-events.ts                           ║
║ (`withWideEvent` / `wideLog` / `BotWideEventFields`), which the four      ║
║ TypeScript bots use. One LogQL query has to span both surfaces, so the   ║
║ two MUST agree on key names and value types. Today's shared contract:    ║
║                                                                          ║
║   task        the boundary's unit-of-work name (NOT `operation` —        ║
║               `operation` is the domain verb app code sets, on both      ║
║               sides, and would clobber the boundary identity)            ║
║   trace_id    16 lowercase hex chars                                     ║
║   duration_ms number, milliseconds, 2 decimals                           ║
║   outcome     "success" | "failed" | "cancelled"                         ║
║   final_level loguru level name — "WARNING", never "WARN"                ║
║   errors[] / warnings[] / audit[]                                        ║
║               entries shaped {msg, ...kwargs}; an exception contributes  ║
║               error_type=<class name>, error=<str(exception)>. `error`   ║
║               is a STRING on every surface — never a nested object.      ║
║                                                                          ║
║ If you are an agent editing ONLY this file, before you finish:           ║
║  1. Open libs/shared/ts/src/bots/utils/wide-events.ts and make the       ║
║     matching change (`emitWideEvent`, `record`, `BotWideEventFields`).   ║
║  2. Update scripts/ci/wide-event-conformance/contract.json, the single   ║
║     shared description both runtimes are checked against.                ║
║  3. Run: python3 scripts/ci/wide-event-conformance/run.py                ║
║     It emits real events from BOTH runtimes and diffs their shapes, so   ║
║     skipping step 1 or 2 is a red CI lane, not a silent drift.           ║
║                                                                          ║
║ The line envelope (time/level/env/service/commit/logger/message) is NOT  ║
║ this file's job — it is stamped by the sink, `_build_json_entry` in      ║
║ libs/shared/py/logging.py, whose counterpart is `buildRecord` in         ║
║ libs/shared/ts/src/bots/utils/logger.ts. Never re-add it here.           ║
╚══════════════════════════════════════════════════════════════════════════╝

The canonical logging surface for all app code:

    from shared.py.wide_events import log

Key behaviors:
- .info()    → real-time Loguru line only (no wide event noise)
- .warning() → real-time Loguru line + appended to wide_event["warnings"]
- .error()   → real-time Loguru line + appended to wide_event["errors"]
- .audit()   → AUDIT-level Loguru line + appended to wide_event["audit"]
- .set()     → merges structured kwargs into the request's wide event
- .bind()    → Loguru-compat: calls .set() and returns self

The middleware calls log.reset() at the start of each request and merges
log.get() into the final emitted event. For worker tasks use wide_task().
"""

import asyncio
from collections.abc import AsyncIterator, Coroutine
import contextlib
import contextvars
import time
from typing import Any, TypedDict
import uuid

from loguru import logger as _loguru

_LEVEL_ORDER: dict[str, int] = {
    "DEBUG": 0,
    "INFO": 1,
    "WARNING": 2,
    "ERROR": 3,
    "CRITICAL": 4,
}


class _EventState:
    """Mutable per-request accumulator shared across context copies.

    The ContextVar below holds this object, and every write path MUTATES it
    in place rather than rebinding the var. That distinction is load-bearing:
    Starlette's ``BaseHTTPMiddleware`` runs the downstream app in a task with
    a *copy* of the middleware's context, so a rebound ContextVar value in a
    handler is invisible to the middleware after ``call_next`` — with the old
    immutable-rebind design every handler/service ``log.set()`` was silently
    dropped from the emitted HTTP event. A context copy still references the
    same state object, so in-place mutation crosses that boundary, while each
    request's ``reset()`` binds a fresh object, keeping requests isolated.
    """

    __slots__ = ("fields", "max_level")

    def __init__(self, fields: dict[str, Any] | None = None) -> None:
        self.fields: dict[str, Any] = fields if fields is not None else {}
        self.max_level: str = "INFO"


_event_state: contextvars.ContextVar[_EventState | None] = contextvars.ContextVar(
    "wide_event_state", default=None
)
_trace_id: contextvars.ContextVar[str] = contextvars.ContextVar("wide_event_trace_id", default="")


def _generate_trace_id() -> str:
    return uuid.uuid4().hex[:16]


class UserContext(TypedDict, total=False):
    """Identity and plan of the authenticated user for the current request."""

    id: str
    email: str
    plan: str


class ChatContext(TypedDict, total=False):
    """Per chat-turn context: conversation, stream, attached files and tool routing."""

    conversation_id: str
    stream_id: str
    is_new_conversation: bool
    message_count: int
    has_files: bool
    file_count: int
    tool_category: str
    has_reply: bool
    has_calendar_event: bool
    selected_workflow_id: str


class ModelContext(TypedDict, total=False):
    """LLM-invocation accounting: model identity, token usage, cost and retry bookkeeping."""

    name: str
    provider: str
    tokens_used: int
    input_tokens: int
    output_tokens: int
    cost_usd: float
    # Caching / accounting fields added by the caching-optimization work.
    # Populated by the @after_model middleware hook via
    # `usage_metadata.input_token_details.cache_read` and
    # `cached_content_token_count`.
    cached_tokens: int
    reasoning_tokens: int  # subset of output_tokens spent on hidden thinking, when reported
    cache_hit_rate: float  # cached_tokens / max(input_tokens, 1)
    credits_charged: float
    step_index: int  # monotonic step counter within a single agent run
    agent_name: str  # "comms_agent" | "executor_agent" | "<subagent>"
    handoff_latency_ms: float  # call_executor/handoff → first LLM token
    retrieve_tools_calls_per_run: int
    # Retry / error bookkeeping.
    retry_attempt: int
    retry_of: str  # error_type of the previous failed attempt
    call_failed: bool


class ConversationContext(TypedDict, total=False):
    """Conversation CRUD/operation context (create, list, delete, star, …)."""

    id: str
    operation: str  # "create"|"list"|"get"|"delete"|"delete_all"|"star"|"pin_message"|"update_messages"|"batch_sync"|"mark_read"|"mark_unread"|"update_description"
    page: int
    limit: int
    total_returned: int
    is_new: bool
    is_starred: bool
    message_count: int


class TodoContext(TypedDict, total=False):
    """Todo and project operation context (CRUD, bulk ops, search, subtasks)."""

    id: str
    operation: str  # "create"|"list"|"get"|"update"|"delete"|"bulk_update"|"bulk_delete"|"bulk_move"|"bulk_complete"|"counts"|"create_project"|"list_projects"|"update_project"|"delete_project"|"subtask_op"
    priority: str
    has_due_date: bool
    project_id: str
    search_mode: str  # "text"|"semantic"|"hybrid"
    query: str
    result_count: int
    page: int
    per_page: int
    filters_applied: list[str]
    bulk_count: int
    completion_toggled: bool


class MemoryContext(TypedDict, total=False):
    """Long-term memory operation context.

    Covers the HTTP endpoints, agent tools, and background write/consolidation
    paths so a single LogQL query can chart memory activity across all three.
    Always set ``operation`` and (for anything that returns or affects a count)
    the canonical ``result_count`` — operation-specific counts are additive,
    never replacements for ``result_count``.
    """

    # Operation identity — use these exact canonical names:
    #   read:  "list"|"recall"|"overview"|"tree"|"graph"|"episodes"
    #          |"recall_episodes"|"recall_transcripts"|"get_documents"
    #          |"read_document"|"history"
    #   write: "create"|"update"|"delete"|"delete_all"|"update_document"
    #   background: "retain"|"consolidate"|"vfs_sync"
    operation: str
    source_type: str  # retain: "conversation"|"email"|"manual"|...
    memory_id: str
    new_memory_id: str  # update → superseding entry id
    content_length: int
    query: str
    category: str
    doc_type: str
    version: int
    page: int
    page_size: int
    start: str
    end: str
    success: bool
    error_type: str  # exception class name on failure
    # Canonical result metric — set for every op that returns/affects a count.
    result_count: int
    # Operation-specific counts (additive; do not replace result_count).
    total_memories: int
    total_count: int
    nodes: int
    edges: int
    deleted_count: int
    versions: int
    # recall retrieval diagnostics (which leg produced candidates).
    ann_hits: int
    fts_hits: int
    candidate_count: int
    # retain/consolidate write-path outcome.
    facts_extracted: int
    episode_entries: int
    episode_entries_deduped: int
    entities_linked: int
    edges_added: int
    new_count: int
    updated_count: int
    extended_count: int
    duplicate_count: int
    doc_types: list[str]
    outcomes: dict[str, str]  # consolidation: {doc_type: "rewritten"|"failed"}
    timings: dict[str, float]  # per-stage latency buckets (ms)


class CalendarContext(TypedDict, total=False):
    """Calendar operation context (events, preferences, batch ops)."""

    calendar_id: str
    operation: str  # "list_calendars"|"get_events"|"create_event"|"update_event"|"delete_event"|"get_preferences"|"update_preferences"|"batch_create"|"batch_update"|"batch_delete"
    event_count: int
    time_range_days: int


class GoalContext(TypedDict, total=False):
    """Goal and roadmap operation context."""

    id: str
    operation: str  # "create"|"get"|"update"|"delete"|"list"|"generate_roadmap"|"update_node"
    roadmap_node_count: int
    result_count: int


class ReminderContext(TypedDict, total=False):
    """Reminder operation context (including recurrence and next run time)."""

    id: str
    operation: str  # "create"|"list"|"get"|"update"|"delete"
    recurrence: str  # "once"|"daily"|"weekly"|"custom"
    next_run_time: str
    result_count: int


class WorkflowContext(TypedDict, total=False):
    """Workflow definition and execution context."""

    id: str
    title: str
    trigger_type: str
    steps_count: int
    operation: str  # "create"|"list"|"get"|"update"|"delete"|"execute"|"status"|"list_executions"|"publish"|"generate_prompt"|"regenerate_steps"
    execution_id: str
    is_integration_trigger: bool
    result_count: int


class SearchContext(TypedDict, total=False):
    """Cross-entity search operation context."""

    query: str
    mode: str
    result_count: int
    scope: list[str]  # which entity types were searched


class PaymentContext(TypedDict, total=False):
    """Billing and subscription operation context."""

    operation: str  # "get_status"|"create_checkout"|"cancel_subscription"|"webhook"|"get_plans"
    plan_type: str
    provider: str


class OnboardingContext(TypedDict, total=False):
    """User onboarding-flow operation context."""

    operation: str  # "get_status"|"update_step"|"complete"|"set_house"|"update_personality"
    step: str
    house: str
    is_complete: bool


class IntegrationContext(TypedDict, total=False):
    """Integration management operation context."""

    id: str
    name: str
    operation: str  # "create"|"update"|"delete"|"publish"|"unpublish"|"list"|"get"
    category: str
    result_count: int


class ImageContext(TypedDict, total=False):
    """Image generation/analysis operation context."""

    operation: str  # "generate"|"analyze"|"generate_stream"
    prompt_length: int
    file_name: str
    mime_type: str


class BotContext(TypedDict, total=False):
    """Chat-bot platform operation context."""

    platform: str  # "discord"|"slack"|"telegram"
    operation: str


class FileContext(TypedDict, total=False):
    """User-uploaded file operation context."""

    operation: str  # "upload"|"delete"|"update"|"seed"|"descriptions"
    file_id: str
    content_type: str
    size_bytes: int
    conversation_id: str
    has_summary: bool
    page_count: int


class SandboxContext(TypedDict, total=False):
    """Per-user E2B sandbox lifecycle context.

    Accumulated across the multi-step acquire path (cache reuse → resume →
    create → mount → canary), so callers must MERGE into this namespace rather
    than overwrite it. ``source`` is the headline field: how the live sandbox
    serving this request was obtained. Per-stage latency lives separately on the
    ``fs`` field (``fs.sbx_create``, ``fs.sbx_connect_resume`` …).
    """

    operation: str  # "acquire"|"pause"|"evict"|"mark_dead"|"sweep"
    sandbox_id: str
    shard_id: int
    source: str  # "cache"|"resume"|"create"
    created: bool
    template_id: str
    workspace_version: int
    refcount: int
    mount_status: str  # "mounted"|"ephemeral_fallback"
    resume_status: str  # "ok"|"unhealthy"|"failed"
    cache_evicted: str  # "unhealthy"|"canary_stale"
    health_ok: bool
    watcher_active: bool
    artifact_mode: str  # artifact watcher detection mode: "watch_dir"|"accesslog"
    marked_dead: bool
    rate_limited: bool
    rate_limit_reset: str
    rate_limit_plan: str
    evicted_count: int  # sweep task: number of idle sandboxes evicted


class McpContext(TypedDict, total=False):
    """Model Context Protocol server/tool operation context."""

    operation: str  # "connect"|"disconnect"|"list_tools"|"call_tool"|"discover"|"health"
    server_id: str
    server_name: str
    tool_name: str
    tool_count: int
    transport: str  # "stdio"|"sse"|"http"
    success: bool
    error_type: str
    result_count: int


class TriggerContext(TypedDict, total=False):
    """Integration trigger / event-routing operation context."""

    operation: str  # "register"|"evaluate"|"fire"|"list"|"delete"|"dispatch"
    trigger_id: str
    trigger_type: str
    integration_id: str
    matched_count: int
    fired: bool
    result_count: int


class MailContext(TypedDict, total=False):
    """Email sync / send / classification operation context."""

    operation: str  # "sync"|"fetch"|"send"|"classify"|"summarize"|"watch"
    provider: str  # "gmail"|"outlook"|...
    account_id: str
    folder: str
    message_count: int
    result_count: int
    success: bool


class OAuthContext(TypedDict, total=False):
    """OAuth / connection-lifecycle operation context."""

    operation: str  # "authorize"|"callback"|"refresh"|"revoke"|"status"|"connect"
    provider: str
    integration_id: str
    success: bool
    error_type: str


class NotificationContext(TypedDict, total=False):
    """Notification dispatch operation context."""

    operation: str  # "send"|"schedule"|"dispatch"|"read"|"mark_all_read"|"list"
    channel: str  # "push"|"email"|"in_app"
    notification_id: str
    result_count: int
    success: bool


class SkillContext(TypedDict, total=False):
    """Agent skill management operation context."""

    operation: str  # "install"|"list"|"run"|"sync"|"delete"|"get"
    skill_id: str
    skill_name: str
    result_count: int
    success: bool


class VectorContext(TypedDict, total=False):
    """Vector-store (ChromaDB) operation context."""

    operation: str  # "query"|"upsert"|"delete"|"get"|"embed"|"create_collection"
    collection: str
    n_results: int
    result_count: int
    embedded_count: int


class VoiceContext(TypedDict, total=False):
    """Voice-agent (LiveKit) session/turn operation context."""

    operation: (
        str  # "session_start"|"turn"|"drain"|"credentials"|"tts"|"stt"|"tool_call"|"session_end"
    )
    room: str
    participant: str
    model: str
    provider: str
    turn_index: int
    # Session-end aggregate. The LiveKit session lifecycle callbacks fire after
    # the entrypoint's setup event has emitted, so the worker accumulates them
    # and reports the whole session once from its shutdown callback (see
    # apps/voice-agent/src/agent.py). LLM tokens go on ModelContext instead.
    shutdown_reason: str
    user_turns: int
    user_speaking_ms: float
    stt_final_count: int
    stt_transcript_chars: int
    stt_latency_ms_avg: float
    false_interruptions: int
    tts_characters: int
    stt_audio_duration_s: float


class DeviceContext(TypedDict, total=False):
    """Device-bridge pairing/token/registration operation context."""

    operation: str  # "pair_start"|"pair_poll"|"pair_approve"|"token"|"list"|"revoke"|"register"
    device_id: str
    pairing_status: str  # "pending"|"approved"|"expired"
    result_count: int
    success: bool
    # Per-pod listener context (revoke_listener / up_listener).
    socket_owned: bool  # revoke enforcement: this pod held the device's socket
    session_id: str  # MCP session a device up-frame is addressed to


class DesktopContext(TypedDict, total=False):
    """Desktop-app release/bridge operation context."""

    operation: str  # "latest_release"|"tool_result"
    platform: str  # "darwin"|"win32"|"linux"
    version: str


class DevContext(TypedDict, total=False):
    """Development-only identity/agent-harness endpoint context (dev router)."""

    operation: (
        str  # "create_user"|"seed"|"remove_user"|"list_subagents"|"run_executor"|"run_subagent"
    )
    target_email: str
    subagent_id: str


class WideEventFields(TypedDict, total=False):
    """Canonical schema for wide event fields set via log.set().

    Using consistent field names ensures LogQL queries work uniformly
    across all endpoints. Example:
        log.set(user=UserContext(id=user_id))
        log.set(chat=ChatContext(conversation_id=conv_id, message_count=5))
        log.set(model=ModelContext(name="gpt-4", provider="openai"))
    """

    user: UserContext
    chat: ChatContext
    model: ModelContext
    conversation: ConversationContext
    todo: TodoContext
    memory: MemoryContext
    calendar: CalendarContext
    goal: GoalContext
    reminder: ReminderContext
    workflow: WorkflowContext
    search: SearchContext
    payment: PaymentContext
    onboarding: OnboardingContext
    integration: IntegrationContext
    image: ImageContext
    bot: BotContext
    file: FileContext
    sandbox: SandboxContext
    mcp: McpContext
    trigger: TriggerContext
    mail: MailContext
    oauth: OAuthContext
    notification: NotificationContext
    skill: SkillContext
    vector: VectorContext
    voice: VoiceContext
    device: DeviceContext
    desktop: DesktopContext
    dev: DevContext
    # Top-level convenience fields used across endpoints
    operation: str
    outcome: str
    platform: str
    # Which module/service-layer function produced the context. Named to match
    # the bots' `component` field so one query reads both surfaces; distinct
    # from the reserved `service`, which is the process's Promtail identity.
    component: str
    result_count: int
    profile_fields_extracted: list[str]
    file_id: str
    file_name: str
    mime_type: str
    integration_id: str
    integration_name: str
    webhook: dict[str, Any]
    # Internal wide-event metadata. `task` is the boundary's unit-of-work name
    # (wide_task/log_context), matching the bots' boundary key in
    # libs/shared/ts/src/bots/utils/wide-events.ts so `sum by (task)` spans both.
    task: str
    final_level: str
    trace_id: str
    duration_ms: float
    # An exception is described by exactly these two scalars on every surface —
    # never a nested object, which `| json` cannot unwrap. Same names in the
    # bots' sanitizeErrorForLog (libs/shared/ts/src/bots/utils/logger.ts).
    error: str  # str(exception)
    error_type: str  # exception class name
    errors: list[dict[str, Any]]
    warnings: list[dict[str, Any]]
    audit: list[dict[str, Any]]


class WideEventLogger:
    """
    Drop-in replacement for a Loguru logger that accumulates a wide event.

    The accumulator is a mutable ``_EventState`` held in a ContextVar: each
    request binds a fresh state (isolation), and every write mutates it in
    place so fields set inside ``BaseHTTPMiddleware``'s context-copied handler
    task still reach the middleware's emit (see ``_EventState``).
    """

    # --- Primary API ---

    def _state(self) -> _EventState:
        """The current accumulator; a throwaway when no boundary is active.

        Deliberately does NOT bind the throwaway into the context: a lazily
        bound ambient state gets inherited by every task spawned from that
        context, turning one dict into a process-global sink that grows
        forever and mixes users (observed with WebSocket connections and ARQ
        jobs inheriting the main context). Outside a boundary every write is
        discarded either way — a fresh throwaway makes that leak-free and
        isolation-safe. Accumulation requires a boundary: the HTTP middleware,
        ``wide_task``, ``log_context`` or ``spawn_logged_task``.
        """
        state = _event_state.get()
        if state is None:
            return _EventState()
        return state

    def set(self, **kwargs: Any) -> None:
        """Merge structured context into the current request's wide event.

        A namespace dict is merged INTO whatever is already on the event rather
        than replacing it, so every layer of a request accumulates onto one
        namespace instead of the last writer silently winning. A flat
        ``fields.update()`` here is what erased ``trigger_type`` from 34,247 of
        34,413 production workflow fires: the final ``set(workflow={...})``
        carried no ``trigger_type``, so it took the whole namespace with it.
        The merge is one level deep and dict-into-dict only — a scalar still
        overwrites, because accumulating a namespace is the goal, not making
        fields immutable.

        ``trace_id`` is the one field that also lives outside the event: it
        backs the ``_trace_id`` ContextVar that ``get_trace_id()`` returns and
        that ``spawn_logged_task`` hands to child work. Setting only the field
        (which is what adopting an upstream ``x-trace-id`` header does) would
        emit an event under one id while every task spawned from it correlates
        under another, so the write is routed through both here — there is no
        second, easy-to-forget way to adopt a trace id.
        """
        trace_id = kwargs.get("trace_id")
        if trace_id:
            _trace_id.set(trace_id)
        fields = self._state().fields
        for key, value in kwargs.items():
            existing = fields.get(key)
            if isinstance(existing, dict) and isinstance(value, dict):
                fields[key] = {**existing, **value}
            else:
                fields[key] = value

    def set_ns(self, namespace: str, **kwargs: Any) -> None:
        """Merge ``kwargs`` into a nested ``namespace`` dict on the wide event.

        Identical to ``set(namespace={...})`` — kept because naming the namespace
        explicitly reads better on a multi-step path, and because it is used
        widely. It delegates so the two can never drift apart again.
        """
        self.set(**{namespace: kwargs})

    # --- Loguru-compatible message methods ---
    #
    # kwargs travel via ``.bind(**kwargs)`` — NEVER as loguru format args.
    # Passing them to the log call itself makes loguru ``str.format`` the
    # message at the call site, so any brace in dynamic message content (JSON
    # in an exception's text, LLM output) raised ValueError/KeyError *inside*
    # the log call — masking the real error and skipping the code after it.
    # bind() delivers the same fields to record["extra"] without formatting.

    def debug(self, message: str, /, **kwargs: Any) -> None:
        """Emit a debug log line; not recorded in the wide event."""
        _loguru.opt(depth=1).bind(**kwargs).debug(message)

    def info(self, message: str, /, **kwargs: Any) -> None:
        """Emit an info log line; not recorded in the wide event (info is noise there)."""
        # Emit real-time Loguru line for visibility.
        # Does NOT add to wide event — info messages are noise there.
        _loguru.opt(depth=1).bind(**kwargs).info(message)

    def warning(self, message: str, /, **kwargs: Any) -> None:
        """Log a warning, append it to the event's ``warnings`` and raise its max level."""
        exc_info = kwargs.pop("exc_info", False)
        _loguru.opt(depth=1, exception=exc_info).bind(**kwargs).warning(message)
        self._append("warnings", message, **kwargs)
        self._bump("WARNING")

    def error(self, message: str, /, **kwargs: Any) -> None:
        """Log an error, append it to the event's ``errors`` and raise its max level."""
        exc_info = kwargs.pop("exc_info", False)
        _loguru.opt(depth=1, exception=exc_info).bind(**kwargs).error(message)
        self._append("errors", message, **kwargs)
        self._bump("ERROR")

    def critical(self, message: str, /, **kwargs: Any) -> None:
        """Log a critical error, append it to the event's ``errors`` and raise its max level."""
        exc_info = kwargs.pop("exc_info", False)
        _loguru.opt(depth=1, exception=exc_info).bind(**kwargs).critical(message)
        self._append("errors", message, **kwargs)
        self._bump("CRITICAL")

    def audit(self, message: str, /, **kwargs: Any) -> None:
        """Record an audit-trail entry for a sensitive operation (auth, money, PII).

        Emits a real-time AUDIT-level line (level registered in
        ``shared.py.logging``) and appends ``{"msg": message, **kwargs}`` to the
        event's ``audit`` array. The key is absent when nothing was audited, and
        bare ``| json`` drops arrays anyway, so the query that finds every
        request that performed an audited operation is
        `{...} | json first_audit="audit[0].msg" | first_audit != ""`
        (or just `{..., level="AUDIT"}` for the real-time lines). Does not bump
        the event's severity — an audit entry is a record, not a problem.

        Usage:
            log.audit("subscription cancelled", actor=user_id, resource=sub_id)
        """
        exc_info = kwargs.pop("exc_info", False)
        _loguru.opt(depth=1, exception=exc_info).bind(**kwargs).log("AUDIT", message)
        self._append("audit", message, **kwargs)

    def bind(self, **kwargs: Any) -> "WideEventLogger":
        """Loguru-compat shim: merges ``kwargs`` into the wide event and returns self.

        Unlike loguru's ``bind``, this does NOT attach fields to subsequent
        real-time lines — the fields land on the request's wide event only.
        """
        self.set(**kwargs)
        return self

    def exception(self, message: str, /, **kwargs: Any) -> None:
        """Log exception with traceback — same as .error() but includes stack trace."""
        _loguru.opt(depth=1, exception=True).bind(**kwargs).error(message)
        self._append("errors", message, **kwargs)
        self._bump("ERROR")

    # --- Internals called by middleware / wide_task ---

    def get(self) -> dict[str, Any]:
        """Return accumulated wide event dict for this request."""
        return self._state().fields

    def get_max_level(self) -> str:
        """Return the highest severity level seen during this request."""
        return self._state().max_level

    def get_trace_id(self) -> str:
        """Return the trace_id for the current request/task."""
        return _trace_id.get()

    def reset(self) -> None:
        """Bind a fresh accumulator for a new request. Called by middleware."""
        tid = _generate_trace_id()
        _trace_id.set(tid)
        _event_state.set(_EventState({"trace_id": tid}))

    # --- Private helpers ---

    def _append(self, category: str, message: str, /, **kwargs: Any) -> None:
        # Both parameters are positional-only, and the first is `category` (not
        # `key`), for the same reason: callers pass arbitrary field names as
        # kwargs, and any of them colliding with a parameter name raises
        # "multiple values for X" — a crash, not a mislabelled field. `key=` is
        # routine (redis ops log the cache key) and `message=` shipped twice and
        # took startup down. The `/` makes the whole class impossible: a
        # colliding kwarg lands in **kwargs, the sink renames it ctx_<key>, and
        # tools/lints/wide_events_logging.py flags it.
        fields = self._state().fields
        entry: dict[str, Any] = {"msg": message, **kwargs}
        fields.setdefault(category, []).append(entry)

    def _bump(self, level: str) -> None:
        state = self._state()
        if _LEVEL_ORDER.get(level, 0) > _LEVEL_ORDER.get(state.max_level, 0):
            state.max_level = level


log = WideEventLogger()


@contextlib.asynccontextmanager
async def _wide_event_boundary(
    task_name: str,
    *,
    event_name: str,
    logger_name: str,
    trace_id: str | None = None,
    **initial_context: Any,
) -> AsyncIterator[WideEventLogger]:
    """Bind a fresh wide event for non-request work and flush one canonical line.

    Shared core for ``wide_task`` and ``log_context``. Mirrors the HTTP
    middleware: it resets the ContextVar accumulator, stamps env/service/commit
    and the initial context, then on exit (success or exception) emits exactly
    one structured JSON event so every ``log.set()`` field reaches Loki.

    ``event_name`` is the log message dashboards filter on; ``logger_name`` is
    the ``logger`` field. Keeping these explicit lets worker rollups stay on
    ``message = "worker_task"`` while ad-hoc background work uses its own name.

    Boundaries nest. ``log.reset()`` rebinds the accumulator in the *caller's*
    context (an ``asynccontextmanager`` body is not a task, so it gets no
    context copy), so without restoring it an inner boundary would keep the
    outer one's ContextVar pointed at the inner state — the outer event would
    emit the inner's fields twice and lose its own. The enclosing accumulator
    and trace_id are therefore restored after the emit, which also keeps a
    long-lived loop's per-iteration boundary usable inside an outer one.
    """
    outer_state = _event_state.get()
    outer_trace_id = _trace_id.get()
    log.reset()
    if trace_id:
        log.set(trace_id=trace_id)  # keeps the field and the ContextVar in sync
    log.set(task=task_name, **initial_context)
    start = time.monotonic()
    # Bound in `except` and consumed in `finally`, which runs before the raise
    # propagates. Recording the failure there rather than in the handler keeps
    # every field of the canonical event written in one place — and .error()
    # stays correct instead of .exception(), which would print the traceback a
    # second time for a task that re-raises it anyway.
    failure: Exception | None = None
    try:
        yield log
        log.set(outcome="success")
    except asyncio.CancelledError:
        # Shutdown and client disconnects cancel long-lived work: a clean exit,
        # not a failure. Record it (an outcome-less event reads as "still
        # running") and propagate so cancellation semantics are unchanged.
        log.set(outcome="cancelled")
        raise
    except Exception as exc:
        failure = exc
        log.set(outcome="failed")
        raise
    finally:
        if failure is not None:
            log.error(
                "task failed",
                error=str(failure),
                error_type=type(failure).__name__,
            )
        duration_ms = round((time.monotonic() - start) * 1000, 2)
        log.set(duration_ms=duration_ms)
        level = log.get_max_level()
        log.set(final_level=level)
        # env/service/commit are NOT added here: the sink stamps them on every
        # line (shared.py.logging._build_json_entry) and re-emits a colliding
        # app field as ctx_<key>, so the infra identity is authoritative for
        # real-time lines too — not just for the boundary event.
        _loguru.bind(logger_name=logger_name, **log.get()).log(level, event_name)
        _event_state.set(outer_state)
        _trace_id.set(outer_trace_id)


def wide_task(
    task_name: str, *, trace_id: str | None = None, **initial_context: Any
) -> contextlib.AbstractAsyncContextManager[WideEventLogger]:
    """
    Context manager for wide event logging in ARQ worker tasks.

    Worker tasks are not HTTP requests so there is no middleware to call
    reset()/get(). Use this context manager to wrap each task function.

    Usage:
        async def run_nightly_sweep() -> None:
            async with wide_task("nightly_sweep", trace_id=get_trace_id() or None):
                log.set(swept=await sweep())

    GAIA's ARQ tasks do not call this themselves — ``app.workers.task_envelope``
    applies it once per task at registration so the trace id propagated by the
    enqueuer and ARQ's ``job_id``/``job_try`` land on every task's event without
    21 call sites having to remember. Task bodies just call ``log.set(...)``.
    """
    return _wide_event_boundary(
        task_name,
        event_name="worker_task",
        logger_name="WORKER",
        trace_id=trace_id,
        **initial_context,
    )


def log_context(
    operation: str, *, trace_id: str | None = None, **initial_context: Any
) -> contextlib.AbstractAsyncContextManager[WideEventLogger]:
    """
    Context manager that establishes a wide event boundary for background work.

    Code that runs outside an HTTP request — fire-and-forget asyncio tasks,
    post-OAuth background connects, callbacks — has no logging middleware to
    bind/flush the wide event accumulator, so every ``log.set()`` field is
    silently discarded. Wrap that work in ``log_context`` and the accumulated
    fields are emitted as one canonical ``background_task`` JSON line on exit
    (success or exception), exactly like the HTTP middleware does per request.

    Usage:
        async def _bg_connect_after_oauth() -> None:
            async with log_context("mcp_background_connect", integration_id=iid):
                await self.connect(iid)  # its log.set(mcp_connect=...) now emits
    """
    return _wide_event_boundary(
        operation,
        event_name="background_task",
        logger_name="BG",
        trace_id=trace_id,
        **initial_context,
    )


_spawned_tasks: set[asyncio.Task[Any]] = set()


def spawn_logged_task(
    operation: str, coro: Coroutine[Any, Any, Any], **initial_context: Any
) -> asyncio.Task[Any]:
    """``asyncio.create_task`` with a wide-event boundary and GC-safe bookkeeping.

    The sanctioned way to spawn fire-and-forget work from a request handler or
    service: without a boundary the task's ``log.set()`` fields are silently
    discarded (the request's event has already emitted by the time it runs).
    The spawned work emits one ``background_task`` event carrying the spawning
    request's ``trace_id``, and the task reference is retained until done so
    it cannot be garbage-collected mid-flight.
    """

    async def _run() -> Any:
        async with log_context(operation, trace_id=get_trace_id() or None, **initial_context):
            return await coro

    task = asyncio.create_task(_run())
    _spawned_tasks.add(task)
    task.add_done_callback(_spawned_tasks.discard)
    return task


def get_trace_id() -> str:
    """Return the trace_id for the current request or worker task."""
    return log.get_trace_id()


__all__ = [
    "log",
    "wide_task",
    "log_context",
    "spawn_logged_task",
    "WideEventLogger",
    "WideEventFields",
    "UserContext",
    "ChatContext",
    "ModelContext",
    "ConversationContext",
    "TodoContext",
    "MemoryContext",
    "CalendarContext",
    "GoalContext",
    "ReminderContext",
    "WorkflowContext",
    "SearchContext",
    "PaymentContext",
    "OnboardingContext",
    "IntegrationContext",
    "ImageContext",
    "BotContext",
    "FileContext",
    "SandboxContext",
    "McpContext",
    "TriggerContext",
    "MailContext",
    "OAuthContext",
    "NotificationContext",
    "SkillContext",
    "VectorContext",
    "VoiceContext",
    "DeviceContext",
    "DesktopContext",
    "DevContext",
    "get_trace_id",
]
