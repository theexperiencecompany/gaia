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
import time
import uuid
from typing import Any, TypedDict

from loguru import logger as _loguru

_LEVEL_ORDER: dict[str, int] = {
    "DEBUG": 0,
    "INFO": 1,
    "WARNING": 2,
    "ERROR": 3,
    "CRITICAL": 4,
}

_wide_event: contextvars.ContextVar[dict[str, Any] | None] = contextvars.ContextVar(
    "wide_event", default=None
)
_max_level: contextvars.ContextVar[str] = contextvars.ContextVar(
    "wide_event_max_level", default="INFO"
)
_trace_id: contextvars.ContextVar[str] = contextvars.ContextVar(
    "wide_event_trace_id", default=""
)


def _generate_trace_id() -> str:
    return uuid.uuid4().hex[:16]


class UserContext(TypedDict, total=False):
    id: str
    email: str
    plan: str


class ChatContext(TypedDict, total=False):
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
    name: str
    provider: str
    tokens_used: int
    input_tokens: int
    output_tokens: int
    cost_usd: float


class ConversationContext(TypedDict, total=False):
    id: str
    operation: str  # "create"|"list"|"get"|"delete"|"delete_all"|"star"|"pin_message"|"update_messages"|"batch_sync"|"mark_read"|"mark_unread"|"update_description"
    page: int
    limit: int
    total_returned: int
    is_new: bool
    is_starred: bool
    message_count: int


class TodoContext(TypedDict, total=False):
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
    operation: str  # "create"|"get_all"|"delete"|"delete_all"
    memory_id: str
    content_length: int
    result_count: int
    success: bool


class CalendarContext(TypedDict, total=False):
    calendar_id: str
    operation: str  # "list_calendars"|"get_events"|"create_event"|"update_event"|"delete_event"|"get_preferences"|"update_preferences"|"batch_create"|"batch_update"|"batch_delete"
    event_count: int
    time_range_days: int


class GoalContext(TypedDict, total=False):
    id: str
    operation: str  # "create"|"get"|"update"|"delete"|"list"|"generate_roadmap"|"update_node"
    roadmap_node_count: int
    result_count: int


class ReminderContext(TypedDict, total=False):
    id: str
    operation: str  # "create"|"list"|"get"|"update"|"delete"
    recurrence: str  # "once"|"daily"|"weekly"|"custom"
    next_run_time: str
    result_count: int


class WorkflowContext(TypedDict, total=False):
    id: str
    title: str
    trigger_type: str
    steps_count: int
    operation: str  # "create"|"list"|"get"|"update"|"delete"|"execute"|"status"|"list_executions"|"publish"|"generate_prompt"|"regenerate_steps"
    execution_id: str
    is_integration_trigger: bool
    result_count: int


class SearchContext(TypedDict, total=False):
    query: str
    mode: str
    result_count: int
    scope: list[str]  # which entity types were searched


class PaymentContext(TypedDict, total=False):
    operation: str  # "get_status"|"create_checkout"|"cancel_subscription"|"webhook"|"get_plans"
    plan_type: str
    provider: str


class OnboardingContext(TypedDict, total=False):
    operation: str  # "get_status"|"update_step"|"complete"|"set_house"|"update_personality"
    step: str
    house: str
    is_complete: bool


class IntegrationContext(TypedDict, total=False):
    id: str
    name: str
    operation: str  # "create"|"update"|"delete"|"publish"|"unpublish"|"list"|"get"
    category: str
    result_count: int


class ImageContext(TypedDict, total=False):
    operation: str  # "generate"|"analyze"|"generate_stream"
    prompt_length: int
    file_name: str
    mime_type: str


class BotContext(TypedDict, total=False):
    platform: str  # "discord"|"slack"|"telegram"
    operation: str


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

    # --- Loguru-compatible message methods ---

    def debug(self, message: str, **kwargs: Any) -> None:
        _loguru.opt(depth=1).debug(message, **kwargs)

    def info(self, message: str, **kwargs: Any) -> None:
        # Emit real-time Loguru line for visibility.
        # Does NOT add to wide event — info messages are noise there.
        _loguru.opt(depth=1).info(message, **kwargs)

    def warning(self, message: str, **kwargs: Any) -> None:
        _loguru.opt(depth=1).warning(message, **kwargs)
        self._append("warnings", message, **kwargs)
        self._bump("WARNING")

    def error(self, message: str, **kwargs: Any) -> None:
        _loguru.opt(depth=1).error(message, **kwargs)
        self._append("errors", message, **kwargs)
        self._bump("ERROR")

    def critical(self, message: str, **kwargs: Any) -> None:
        _loguru.opt(depth=1).critical(message, **kwargs)
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

    def _append(self, key: str, message: str, **kwargs: Any) -> None:
        current = _wide_event.get() or {}
        entry: dict[str, Any] = {"msg": message, **kwargs}
        items = list(current.get(key, []))
        items.append(entry)
        _wide_event.set({**current, key: items})

    def _bump(self, level: str) -> None:
        current = _max_level.get()
        if _LEVEL_ORDER.get(level, 0) > _LEVEL_ORDER.get(current, 0):
            _max_level.set(level)


log = WideEventLogger()


@contextlib.asynccontextmanager
async def wide_task(task_name: str, *, trace_id: str | None = None, **initial_context: Any):
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
    log.reset()
    if trace_id:
        log.set(trace_id=trace_id)
        _trace_id.set(trace_id)
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
        _loguru.bind(logger_name="WORKER", **event).log(level, "worker_task")


def get_trace_id() -> str:
    """Return the trace_id for the current request or worker task."""
    return log.get_trace_id()


__all__ = [
    "log",
    "wide_task",
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
    "get_trace_id",
]
