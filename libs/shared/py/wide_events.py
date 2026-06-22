"""
Wide event logging — one context-rich structured event per request.

Drop-in replacement for any Loguru logger. Migration is one import line per file:

    # Before
    from app.config.loggers import chat_logger as logger

    # After — import as log and use log.set(), log.info(), etc.
    from shared.py.wide_events import log

Key behaviors:
- .info()    → real-time Loguru line only (no wide event noise)
- .warning() → real-time Loguru line + appended to wide_event["warnings"]
- .error()   → real-time Loguru line + appended to wide_event["errors"]
- .set()     → merges structured kwargs into the request's wide event
- .bind()    → Loguru-compat: calls .set() and returns self

The middleware calls log.reset() at the start of each request and merges
log.get() into the final emitted event. For worker tasks use wide_task().
"""

import contextlib
import contextvars
import functools
import os
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

# Loki/Promtail labels every backend log line with service="gaia-backend"
# (see infra/docker/observability/promtail-config.yaml). The in-event `service`
# field must match that label so `{service="gaia-backend"} | json` and
# `... | json | service="gaia-backend"` agree.
_SERVICE_NAME = "gaia-backend"


@functools.lru_cache(maxsize=1)
def env_context() -> dict[str, str]:
    """Environment characteristics stamped onto every emitted wide event.

    Single source of truth for the HTTP middleware and every background
    ``log_context`` / ``wide_task`` boundary, so a wide event emitted outside
    an HTTP request carries the same ``env`` / ``service`` / ``commit`` fields
    as one emitted inside it. Resolved once and cached.

    ``commit`` reads GIT_COMMIT_SHA (or COMMIT_SHA), set in the Docker image /
    CI, and falls back to "local" during development.
    """
    return {
        "env": os.getenv("ENV", "production"),
        "service": _SERVICE_NAME,
        "commit": os.getenv("GIT_COMMIT_SHA", os.getenv("COMMIT_SHA", "local"))[:8],
    }


_wide_event: contextvars.ContextVar[dict[str, Any] | None] = contextvars.ContextVar(
    "wide_event", default=None
)
_max_level: contextvars.ContextVar[str] = contextvars.ContextVar(
    "wide_event_max_level", default="INFO"
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

    operation: str  # "session_start"|"turn"|"tts"|"stt"|"tool_call"|"session_end"
    room: str
    participant: str
    model: str
    provider: str
    turn_index: int


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
    sandbox: SandboxContext
    mcp: McpContext
    trigger: TriggerContext
    mail: MailContext
    oauth: OAuthContext
    notification: NotificationContext
    skill: SkillContext
    vector: VectorContext
    voice: VoiceContext
    # Top-level convenience fields used across endpoints
    operation: str
    outcome: str
    platform: str
    result_count: int
    profile_fields_extracted: list[str]
    file_id: str
    file_name: str
    mime_type: str
    integration_id: str
    integration_name: str
    webhook: dict[str, Any]
    # Internal wide-event metadata
    task: str
    final_level: str
    trace_id: str
    duration_ms: float
    error: dict[str, Any]
    errors: list[dict[str, Any]]
    warnings: list[dict[str, Any]]


class WideEventLogger:
    """
    Drop-in replacement for a Loguru logger that accumulates a wide event.

    The wide event is stored in a ContextVar — each async task (request) gets
    its own isolated copy. No thread-safety issues, no cross-request leakage.
    """

    # --- Primary API ---

    def set(self, **kwargs: Any) -> None:
        """Merge structured context into the current request's wide event."""
        current = _wide_event.get() or {}
        _wide_event.set({**current, **kwargs})

    def set_ns(self, namespace: str, **kwargs: Any) -> None:
        """Merge ``kwargs`` into a nested ``namespace`` dict on the wide event.

        ``set`` shallow-merges at the top level, so re-setting a nested dict
        (e.g. ``set(sandbox={...})``) clobbers keys from earlier calls. ``set_ns``
        read-merges into ``event[namespace]`` instead, preserving every field
        accumulated across a multi-step path (the sandbox acquire path is the
        canonical case — see ``SandboxContext``).
        """
        current = _wide_event.get() or {}
        ns = {**current.get(namespace, {}), **kwargs}
        _wide_event.set({**current, namespace: ns})

    # --- Loguru-compatible message methods ---

    def debug(self, message: str, **kwargs: Any) -> None:
        """Emit a debug log line; not recorded in the wide event."""
        _loguru.opt(depth=1).debug(message, **kwargs)

    def info(self, message: str, **kwargs: Any) -> None:
        """Emit an info log line; not recorded in the wide event (info is noise there)."""
        # Emit real-time Loguru line for visibility.
        # Does NOT add to wide event — info messages are noise there.
        _loguru.opt(depth=1).info(message, **kwargs)

    def warning(self, message: str, **kwargs: Any) -> None:
        """Log a warning, append it to the event's ``warnings`` and raise its max level."""
        exc_info = kwargs.pop("exc_info", False)
        _loguru.opt(depth=1, exception=exc_info).warning(message, **kwargs)
        self._append("warnings", message, **kwargs)
        self._bump("WARNING")

    def error(self, message: str, **kwargs: Any) -> None:
        """Log an error, append it to the event's ``errors`` and raise its max level."""
        exc_info = kwargs.pop("exc_info", False)
        _loguru.opt(depth=1, exception=exc_info).error(message, **kwargs)
        self._append("errors", message, **kwargs)
        self._bump("ERROR")

    def critical(self, message: str, **kwargs: Any) -> None:
        """Log a critical error, append it to the event's ``errors`` and raise its max level."""
        exc_info = kwargs.pop("exc_info", False)
        _loguru.opt(depth=1, exception=exc_info).critical(message, **kwargs)
        self._append("errors", message, **kwargs)
        self._bump("CRITICAL")

    def bind(self, **kwargs: Any) -> "WideEventLogger":
        """Loguru compat: logger.bind(user_id=x).info(...) — merges into wide event."""
        self.set(**kwargs)
        return self

    def exception(self, message: str, **kwargs: Any) -> None:
        """Log exception with traceback — same as .error() but includes stack trace."""
        _loguru.opt(depth=1, exception=True).error(message, **kwargs)
        self._append("errors", message, **kwargs)
        self._bump("ERROR")

    # --- Internals called by middleware / wide_task ---

    def get(self) -> dict[str, Any]:
        """Return accumulated wide event dict for this request."""
        return _wide_event.get() or {}

    def get_max_level(self) -> str:
        """Return the highest severity level seen during this request."""
        return _max_level.get()

    def get_trace_id(self) -> str:
        """Return the trace_id for the current request/task."""
        return _trace_id.get()

    def reset(self) -> None:
        """Reset wide event for a new request. Called by middleware."""
        _max_level.set("INFO")
        tid = _generate_trace_id()
        _trace_id.set(tid)
        _wide_event.set({"trace_id": tid})

    # --- Private helpers ---

    def _append(self, category: str, message: str, **kwargs: Any) -> None:
        # NB: the first parameter is `category` (not `key`) on purpose — callers
        # routinely pass a `key=` field (e.g. redis ops log the cache key), and a
        # parameter named `key` would collide with it ("multiple values for 'key'").
        current = _wide_event.get() or {}
        entry: dict[str, Any] = {"msg": message, **kwargs}
        items = list(current.get(category, []))
        items.append(entry)
        _wide_event.set({**current, category: items})

    def _bump(self, level: str) -> None:
        current = _max_level.get()
        if _LEVEL_ORDER.get(level, 0) > _LEVEL_ORDER.get(current, 0):
            _max_level.set(level)


log = WideEventLogger()


@contextlib.asynccontextmanager
async def _wide_event_boundary(
    task_name: str,
    *,
    event_name: str,
    logger_name: str,
    trace_id: str | None = None,
    **initial_context: Any,
):
    """Bind a fresh wide event for non-request work and flush one canonical line.

    Shared core for ``wide_task`` and ``log_context``. Mirrors the HTTP
    middleware: it resets the ContextVar accumulator, stamps env/service/commit
    and the initial context, then on exit (success or exception) emits exactly
    one structured JSON event so every ``log.set()`` field reaches Loki.

    ``event_name`` is the log message dashboards filter on; ``logger_name`` is
    the ``logger`` field. Keeping these explicit lets worker rollups stay on
    ``message = "worker_task"`` while ad-hoc background work uses its own name.
    """
    log.reset()
    if trace_id:
        log.set(trace_id=trace_id)
        _trace_id.set(trace_id)
    log.set(**env_context())
    log.set(task=task_name, **initial_context)
    start = time.monotonic()
    try:
        yield log
        log.set(outcome="success")
    except Exception as exc:
        log.error(
            "task failed",
            error=str(exc),
            error_type=type(exc).__name__,
        )
        log.set(outcome="failed")
        raise
    finally:
        duration_ms = round((time.monotonic() - start) * 1000, 2)
        log.set(duration_ms=duration_ms)
        level = log.get_max_level()
        log.set(final_level=level)
        event = log.get()
        _loguru.bind(logger_name=logger_name, **event).log(level, event_name)


def wide_task(task_name: str, *, trace_id: str | None = None, **initial_context: Any):
    """
    Context manager for wide event logging in ARQ worker tasks.

    Worker tasks are not HTTP requests so there is no middleware to call
    reset()/get(). Use this context manager to wrap each task function.

    Usage:
        async def process_reminder(ctx: dict, reminder_id: str) -> str:
            async with wide_task("process_reminder", reminder_id=reminder_id):
                log.set(job_id=ctx.get("job_id"))
                await reminder_scheduler.process_task_execution(reminder_id)
    """
    return _wide_event_boundary(
        task_name,
        event_name="worker_task",
        logger_name="WORKER",
        trace_id=trace_id,
        **initial_context,
    )


def log_context(operation: str, *, trace_id: str | None = None, **initial_context: Any):
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


def get_trace_id() -> str:
    """Return the trace_id for the current request or worker task."""
    return log.get_trace_id()


__all__ = [
    "log",
    "wide_task",
    "log_context",
    "env_context",
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
    "SandboxContext",
    "McpContext",
    "TriggerContext",
    "MailContext",
    "OAuthContext",
    "NotificationContext",
    "SkillContext",
    "VectorContext",
    "VoiceContext",
    "get_trace_id",
]
