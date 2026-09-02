"""
Tracked-todo LangChain tools for the executor agent.

Allows GAIA's executor to create tracked todos with VFS canvas
and search across canvas context via ChromaDB.
"""

from datetime import UTC, datetime
from typing import Annotated

from croniter import croniter as _croniter
from langchain_core.runnables import RunnableConfig
from langchain_core.tools import tool

from app.constants.todos import GAIA_TRACKED_LABEL
from app.db.repositories.todos import todo_repository
from app.models.todo_models import Priority, TodoDocument, TodoResponse, TodoUpdate
from app.models.trigger_subscription_models import (
    OPERATORS_BY_FIELD_TYPE,
    ConditionMatch,
    ConditionOperator,
    SubscriptionAction,
    SubscriptionCondition,
    SubscriptionStatus,
)
from app.services.todo_canvas_storage import append_canvas, read_canvas, write_canvas
from app.services.tracked_todo_service import tracked_todo_service
from app.services.triggers.matchable_fields import MATCHABLE_TRIGGERS, get_matchable_trigger
from app.services.triggers.subscription_service import (
    DEFAULT_COOLDOWN_SECONDS,
    SubscriptionError,
    register_subscription,
    unregister_subscription,
)
from app.services.user_service import get_user_by_id
from app.utils.canvas_vector_utils import search_canvas_context
from app.utils.cron_utils import get_next_run_time
from app.utils.timezone import Timezone, is_valid_timezone
from shared.py.wide_events import log, spawn_logged_task

_RECURRENCE_SHORTCUTS = {"daily", "weekly", "every_4h", "every_1h"}
_UTC_OFFSET = "+00:00"
_ERR_NO_USER_ID = "Error: user_id not found in config"


async def _get_user_tz(user_id: str) -> str:
    """Look up the user's IANA timezone from MongoDB.

    NOTE: This is an uncached DB call per invocation. Acceptable for now —
    recurrence math runs at tool-call time, not in a tight loop. Refactor
    to a cached read if it shows up in profiles.
    """
    try:
        user = await get_user_by_id(user_id)
        if user and user.get("timezone"):
            tz_name = user["timezone"]
            if isinstance(tz_name, str) and is_valid_timezone(tz_name):
                return tz_name
            log.debug("tracked_todo.invalid_user_tz", user_id=user_id, tz_name=tz_name)
    except Exception as e:
        log.warning("tracked_todo.user_tz_lookup_failed", user_id=user_id, error=str(e))
    log.warning("tracked_todo.user_tz_fallback_utc", user_id=user_id)
    return "UTC"


def _compute_first_fire_from_cron(cron_expr: str, tz_name: str) -> datetime:
    """Next fire of a cron in ``tz_name``, returned as UTC.

    Thin wrapper over the canonical ``get_next_run_time`` so todo recurrence and
    reminder/workflow recurrence share one cron-in-timezone implementation.
    """
    return get_next_run_time(cron_expr, tz=Timezone.parse(tz_name))


def _is_cron_expression(recurrence: str) -> bool:
    return recurrence not in _RECURRENCE_SHORTCUTS


def _parse_iso_future_datetime(iso_str: str, field_name: str) -> tuple[datetime | None, str | None]:
    """Parse an ISO datetime; require it to be in the future. Returns (parsed, error)."""
    try:
        parsed = datetime.fromisoformat(iso_str.replace("Z", _UTC_OFFSET))
    except ValueError:
        return None, f"Error: invalid {field_name} format '{iso_str}'."
    if parsed.tzinfo is None:
        return None, f"Error: {field_name} '{iso_str}' must include a timezone offset."
    if parsed <= datetime.now(UTC):
        return None, f"Error: {field_name} must be in the future."
    return parsed, None


def _resolve_cron_first_fire(
    recurrence: str, scheduled_at: str | None, user_tz_name: str | None
) -> tuple[datetime | None, list[str], str | None]:
    """Validate a cron recurrence and compute first fire in the user's timezone."""
    notes: list[str] = []
    try:
        _croniter(recurrence)
    except (ValueError, KeyError):
        return (
            None,
            [],
            (
                f"Error: invalid recurrence '{recurrence}'. "
                f"Use one of: {', '.join(sorted(_RECURRENCE_SHORTCUTS))}, "
                "or a valid 5-field cron expression."
            ),
        )
    # Cron is the source of truth; an explicit scheduled_at would be redundant.
    if scheduled_at:
        notes.append(
            "scheduled_at was ignored: for a cron recurrence the first fire "
            "is computed from the cron in the user's timezone."
        )
    try:
        parsed = _compute_first_fire_from_cron(recurrence, user_tz_name or "UTC")
    except Exception as e:
        return None, notes, (f"Error: could not compute first fire from cron '{recurrence}': {e}")
    return parsed, notes, None


def _resolve_first_fire(
    recurrence: str | None,
    scheduled_at: str | None,
    user_tz_name: str | None,
) -> tuple[datetime | None, list[str], str | None]:
    """Decide the first-fire datetime from recurrence + scheduled_at inputs."""
    if recurrence:
        if _is_cron_expression(recurrence):
            return _resolve_cron_first_fire(recurrence, scheduled_at, user_tz_name)
        # Shortcut recurrence ('daily', 'weekly', …) needs a first-fire anchor.
        if not scheduled_at:
            return (
                None,
                [],
                (
                    f"Error: recurrence '{recurrence}' is a shortcut and requires "
                    "scheduled_at as the first-fire anchor. Either provide scheduled_at "
                    "or use a cron expression that fully specifies when to fire."
                ),
            )
        parsed, error = _parse_iso_future_datetime(scheduled_at, "scheduled_at")
        return parsed, [], error
    if scheduled_at:
        parsed, error = _parse_iso_future_datetime(scheduled_at, "scheduled_at")
        return parsed, [], error
    return None, [], None


async def _persist_scheduling_fields(
    todo_id: str,
    user_id: str,
    parsed_scheduled_at: datetime | None,
    recurrence: str | None,
    expires_at: str | None,
) -> str | None:
    """Save scheduled_at / recurrence / expires_at onto a freshly-created todo doc."""
    if not (parsed_scheduled_at or recurrence or expires_at):
        return None
    fields: dict[str, object] = {}
    if parsed_scheduled_at:
        fields["scheduled_at"] = parsed_scheduled_at
    if recurrence:
        fields["recurrence"] = recurrence
    if expires_at:
        try:
            fields["expires_at"] = datetime.fromisoformat(expires_at.replace("Z", _UTC_OFFSET))
        except ValueError:
            return f"Error: invalid expires_at format '{expires_at}'."
    await todo_repository.update(todo_id, user_id=user_id, update=TodoUpdate.model_validate(fields))
    return None


async def _schedule_execution_after_create(
    todo_id: str, parsed_scheduled_at: datetime
) -> str | None:
    """Hand the new todo to the scheduler; translate any failure into user-facing text."""
    try:
        success = await tracked_todo_service.schedule_execution(todo_id, parsed_scheduled_at)
    except Exception as e:
        log.warning(
            "tracked_todo.schedule_after_create_failed",
            todo_id=todo_id,
            error=str(e),
        )
        return (
            f"Tracked todo created (ID: {todo_id}) but scheduling failed: {e}. "
            f"The todo exists but will NOT execute automatically."
        )
    if not success:
        return (
            f"Tracked todo created (ID: {todo_id}) but scheduling failed. "
            f"The todo exists but will NOT execute automatically."
        )
    return None


def _format_first_fire_note(parsed_scheduled_at: datetime, user_tz_name: str | None) -> str:
    """Append a human-readable note about the first fire, timezone-aware when possible."""
    if user_tz_name:
        try:
            local_fire = parsed_scheduled_at.astimezone(Timezone.parse(user_tz_name).tzinfo)
        except Exception:
            return f"\nFirst fire (UTC): {parsed_scheduled_at.isoformat()}"
        return (
            f"\nNote: scheduled in your timezone ({user_tz_name}). "
            f"First fire: {local_fire.strftime('%a %Y-%m-%d %H:%M %Z')}. "
            "If this isn't what you wanted, call update_tracked_todo with "
            "the corrected recurrence (or scheduled_at for one-shots)."
        )
    return (
        f"\nNote: first fire (UTC): {parsed_scheduled_at.isoformat()}. "
        "If this isn't what you wanted, call update_tracked_todo to correct it."
    )


def _build_labels_update(labels: list[str] | None, update_fields: dict[str, object]) -> str | None:
    """Apply a labels update, ensuring GAIA_TRACKED_LABEL is present."""
    if labels is None:
        return None
    if GAIA_TRACKED_LABEL not in labels:
        labels = [*labels, GAIA_TRACKED_LABEL]
    update_fields["labels"] = labels
    return None


def _build_clearable_datetime_update(
    value: str | None, field_name: str, update_fields: dict[str, object]
) -> str | None:
    """Set, clear (""), or skip (None) a datetime field; returns user-facing error on bad format."""
    if value is None:
        return None
    if value == "":
        update_fields[field_name] = None
        return None
    try:
        update_fields[field_name] = datetime.fromisoformat(value.replace("Z", _UTC_OFFSET))
    except ValueError:
        return f"Error: invalid {field_name} format '{value}'."
    return None


def _build_priority_update(priority: str | None, update_fields: dict[str, object]) -> str | None:
    """Validate + apply a priority update."""
    if priority is None:
        return None
    try:
        update_fields["priority"] = Priority(priority).value
    except ValueError:
        return f"Error: invalid priority '{priority}'. Use one of: high, medium, low, none"
    return None


def _build_scheduled_at_update(
    scheduled_at: str | None, update_fields: dict[str, object]
) -> str | None:
    """Apply a scheduled_at update (must be in the future) or clear it."""
    if scheduled_at is None:
        return None
    if scheduled_at == "":
        update_fields["scheduled_at"] = None
        return None
    try:
        parsed_at = datetime.fromisoformat(scheduled_at.replace("Z", _UTC_OFFSET))
    except ValueError:
        return f"Error: invalid scheduled_at format '{scheduled_at}'."
    if parsed_at.tzinfo is None:
        return f"Error: scheduled_at '{scheduled_at}' must include a timezone offset."
    if parsed_at <= datetime.now(UTC):
        return "Error: scheduled_at must be in the future."
    update_fields["scheduled_at"] = parsed_at
    return None


def _validate_recurrence_format(recurrence: str) -> str | None:
    """Return a user-facing error if `recurrence` is neither a valid cron nor a known shortcut.

    _is_cron_expression is defined as "not a known shortcut", so the two cases
    are exhaustive: anything that isn't a shortcut is validated as a cron
    expression here — there is no separate "unknown shortcut-like string"
    branch to fall through to.
    """
    if not _is_cron_expression(recurrence):
        return None
    try:
        _croniter(recurrence)
    except (ValueError, KeyError):
        return (
            f"Error: invalid recurrence '{recurrence}'. "
            f"Use one of: {', '.join(sorted(_RECURRENCE_SHORTCUTS))}, "
            "or a valid 5-field cron expression."
        )
    return None


async def _apply_cron_first_fire(
    recurrence: str,
    scheduled_at: str | None,
    user_id: str,
    update_fields: dict[str, object],
    notes: list[str],
) -> str | None:
    """For a cron recurrence, derive first fire in the user's tz and override scheduled_at."""
    if scheduled_at:
        notes.append(
            "scheduled_at was ignored: for a cron recurrence the first fire "
            "is computed from the cron in your timezone."
        )
    try:
        user_tz_name = await _get_user_tz(user_id)
        update_fields["scheduled_at"] = _compute_first_fire_from_cron(recurrence, user_tz_name)
    except Exception as e:
        return f"Error: could not compute first fire from cron: {e}"
    return None


async def _build_recurrence_update(
    recurrence: str | None,
    scheduled_at: str | None,
    user_id: str,
    update_fields: dict[str, object],
    notes: list[str],
) -> str | None:
    """Validate + apply a recurrence update; for cron, also recompute first-fire."""
    if recurrence is None:
        return None
    if recurrence == "":
        update_fields["recurrence"] = None
        return None
    format_error = _validate_recurrence_format(recurrence)
    if format_error:
        return format_error
    update_fields["recurrence"] = recurrence
    if _is_cron_expression(recurrence):
        return await _apply_cron_first_fire(recurrence, scheduled_at, user_id, update_fields, notes)
    return None


def _build_list_detail_parts(doc: TodoDocument, now: datetime) -> list[str]:
    """Build the pipe-separated detail fragments shown on the second line of each todo."""
    parts: list[str] = []
    if doc.due_date:
        days_until = (doc.due_date - now).days
        parts.append(f"Due: OVERDUE {-days_until}d" if days_until < 0 else f"Due: {days_until}d")
    if doc.scheduled_at:
        parts.append(f"Scheduled: {doc.scheduled_at.isoformat()}")
    if doc.recurrence:
        parts.append(f"Recurrence: {doc.recurrence}")
    if doc.expires_at:
        expires_days = (doc.expires_at - now).days
        parts.append(
            f"Expires: EXPIRED {-expires_days}d ago"
            if expires_days < 0
            else f"Expires: in {expires_days}d"
        )
    if doc.gaia_retry_count > 0:
        parts.append(f"Retries: {doc.gaia_retry_count}")
    return parts


def _format_tracked_todo_full(doc: TodoDocument, now: datetime) -> str:
    """Format one tracked-todo doc as the multi-line block used by list_tracked_todos."""
    labels = [lbl for lbl in doc.labels if lbl != GAIA_TRACKED_LABEL]
    labels_str = f" [{', '.join(labels)}]" if labels else ""
    age_days = (now - (doc.created_at or now)).days
    last_update = (now - (doc.updated_at or now)).days

    parts = [
        f'- "{doc.title}"{labels_str} (ID: {doc.id})',
        f"  Priority: {doc.priority.value} | Age: {age_days}d | Last updated: {last_update}d ago",
    ]
    detail_parts = _build_list_detail_parts(doc, now)
    if detail_parts:
        parts.append(f"  {' | '.join(detail_parts)}")
    parts.extend(f"  {line}" for line in _format_subscription_lines(doc))
    return "\n".join(parts)


def _format_subscription_lines(doc: TodoDocument) -> list[str]:
    """Render a todo's watches, with the ids unsubscribing needs.

    Shown here rather than behind a separate list tool: the model already reads
    this block, and a watch it cannot see is one it will duplicate.
    """
    lines = []
    for sub in doc.trigger_subscriptions:
        joiner = " OR " if sub.match is ConditionMatch.ANY else " AND "
        conditions = (
            joiner.join(f"{c.field_name} {c.operator} {c.value}" for c in sub.conditions)
            or "any event"
        )
        paused = (
            " (PAUSED: integration disconnected)" if sub.status is SubscriptionStatus.PAUSED else ""
        )
        lines.append(
            f"Watching {sub.trigger_name} -> {sub.action} when {conditions}"
            f" (subscription: {sub.id}){paused}"
        )
    return lines


def _render_catalog(trigger_name: str) -> str:
    """The matchable fields for a trigger, as the model should see them."""
    entry = get_matchable_trigger(trigger_name)
    if entry is None:
        available = ", ".join(sorted(MATCHABLE_TRIGGERS))
        return f"'{trigger_name}' is not a subscribable trigger. Available triggers: {available}"

    lines = [f"Matchable fields for {trigger_name}:"]
    lines.extend(
        f"  {f.name} ({f.type}): {f.description}. Example: {f.example}" for f in entry.fields
    )
    if entry.excluded:
        lines.append("Not matchable:")
        lines.extend(f"  {name}: {reason}" for name, reason in sorted(entry.excluded.items()))
    lines.append(
        "Operators by type: "
        + "; ".join(
            f"{field_type} -> {', '.join(sorted(ops))}"
            for field_type, ops in OPERATORS_BY_FIELD_TYPE.items()
        )
    )
    return "\n".join(lines)


def _patch_canvas_section(current: str, section: str, content: str) -> str:
    """Replace (or append) a `## {section}` block within a canvas markdown string."""
    heading = f"## {section}"
    head_end: int | None = None
    search_start = 0
    while True:
        pos = current.find(heading, search_start)
        if pos == -1:
            break
        # A real heading match must (a) start a line — position 0 or right
        # after a "\n" — and (b) end the heading exactly — end-of-string or
        # right before a "\n". Without both checks a plain substring search
        # either misses the section when it's the canvas's first line (no
        # leading "\n" to match against), or false-positives on a DIFFERENT
        # section whose name happens to start with this one (e.g. searching
        # for "Current" would otherwise match inside "## Current State").
        at_line_start = pos == 0 or current[pos - 1] == "\n"
        end_pos = pos + len(heading)
        is_exact_heading = end_pos == len(current) or current[end_pos] == "\n"
        if at_line_start and is_exact_heading:
            head_end = end_pos
            break
        search_start = pos + 1
    if head_end is None:
        # Section does not exist — append it as a fresh trailing block.
        return current.rstrip() + f"\n\n{heading}\n{content}"
    next_section = current.find("\n## ", head_end + 1)
    if next_section == -1:
        return current[:head_end] + "\n" + content
    return current[:head_end] + "\n" + content.rstrip() + "\n" + current[next_section:]


def _format_create_output(
    result: TodoResponse,
    parsed_scheduled_at: datetime | None,
    user_tz_name: str | None,
    notes: list[str],
) -> str:
    """Assemble the user-facing summary returned by create_tracked_todo."""
    out = (
        f"Tracked todo created: {result.id}\n"
        f"Title: {result.title}\n"
        "Canvas + activity log are stored on this todo. Edit them ONLY via "
        f"update_tracked_todo_canvas(todo_id='{result.id}', ...), never with filesystem tools."
    )
    if parsed_scheduled_at:
        out += _format_first_fire_note(parsed_scheduled_at, user_tz_name)
    if notes:
        out += "\nDetails:\n  - " + "\n  - ".join(notes)
    return out


@tool
async def create_tracked_todo(
    config: RunnableConfig,
    title: Annotated[str, "Short title for the tracked todo"],
    description: Annotated[
        str | None,
        "Optional description of what this todo is tracking",
    ] = None,
    initial_canvas: Annotated[
        str | None,
        "Optional initial canvas content (markdown). If omitted, a template is used.",
    ] = None,
    labels: Annotated[
        list[str] | None,
        "Optional labels for categorization (gaia-tracked is added automatically)",
    ] = None,
    priority: Annotated[
        str,
        "Priority: 'high', 'medium', 'low', or 'none'",
    ] = "none",
    scheduled_at: Annotated[
        str | None,
        "ISO datetime for a ONE-TIME future execution. "
        "Use this ONLY when there is no recurrence, or when the recurrence is a "
        "delta-style shortcut ('daily', 'weekly', 'every_4h', 'every_1h') that "
        "needs a first-fire anchor. "
        "For cron-style recurrence (e.g. '0 9 * * *' or '0 9,20 * * *'), OMIT this: "
        "the first fire is computed automatically in the user's timezone. "
        "Always include the user's timezone offset (e.g., '2026-03-20T09:00:00+05:30'); "
        "never 'Z' unless the user explicitly says UTC.",
    ] = None,
    recurrence: Annotated[
        str | None,
        "How often to repeat. Options: 'daily', 'weekly', 'every_4h', 'every_1h', "
        "or a 5-field cron expression. "
        "ALWAYS evaluated in the user's stored timezone: the backend handles "
        "the conversion. Just pass the cron in user-local wall-clock terms. "
        "Example: '0 9,20 * * *' fires at 9 AM and 8 PM in the user's timezone "
        "daily, ONE recurrence, two fires per day; do NOT create two todos. "
        "Do NOT bake timezone offsets into the cron string itself.",
    ] = None,
    expires_at: Annotated[
        str | None,
        "ISO datetime string when this todo becomes irrelevant. "
        "Always include the user's timezone offset (e.g., '2026-04-01T23:59:00+05:30'). "
        "Use for time-sensitive context like 'check if package arrived' (expires in 3 days) "
        "or 'follow up if no reply' (expires in 2 weeks). "
        "Different from due_date: due_date means 'should be done by'; expires_at means 'no longer matters after'.",
    ] = None,
) -> str:
    """
    Create a tracked todo: a GAIA-managed todo with a working-memory canvas.

    A tracked todo shows on the user's todos page like a normal todo, but GAIA
    owns it: it carries canvas.md (GAIA's working notes: key IDs, current state,
    activity log, learnings) plus an optional schedule/recurrence so GAIA can act
    on it over time. It is distinct from the user's own hand-created action items
    (which live in providers like Todoist, Google Tasks, Apple Reminders, Gaia
    Todos).

    Create one ONLY when GAIA itself performs or schedules a real action on an
    external system that it needs to remember, follow up on, or repeat: sent an
    email and awaits a reply, created an issue, posted to Slack, scheduled
    recurring work, or an ongoing multi-step initiative.

    Do NOT create one for read-only work (fetching, listing, searching, or
    summarizing data), no matter how complex it is or how often it runs (a
    recurring daily summary is still a read). Saving or persisting a summary,
    digest, or briefing is NOT tracking: return the summary, do not store it as a
    tracked todo. Search existing tracked todos first (search_todo_context) and
    update a match instead of creating a duplicate.

    IMPORTANT: Before creating a tracked todo with scheduling (scheduled_at, recurrence),
    read the "tracked-todo-working-memory" skill first for scheduling best practices,
    canvas template guidelines, and lifecycle rules.

    scheduled_at: ISO datetime with the user's timezone offset (e.g., "2026-03-20T09:00:00+05:30").
                  For a one-time run, or as the first-fire anchor for a delta recurrence
                  ('daily'/'weekly'/'every_4h'). For cron recurrence, OMIT it: the first fire is
                  computed in the user's timezone. Never use raw 'Z' unless the user says UTC.
    recurrence: How often to repeat. Options: 'daily', 'weekly', 'every_4h', or a cron expression.
                Cron does NOT require scheduled_at; delta shortcuts use scheduled_at as their
                first-fire anchor.
    expires_at: ISO datetime string when this todo becomes irrelevant regardless of completion.
                Different from due_date: due_date = deadline (overdue = still needs doing),
                expires_at = relevance window (expired = no longer worth tracking).
    """
    user_id = config.get("metadata", {}).get("user_id")
    if not user_id:
        return _ERR_NO_USER_ID

    # Recurrence is always evaluated in the user's stored timezone. We only
    # look it up here to (a) compute the first cron fire correctly and (b)
    # surface a user-readable note in the return value.
    user_tz_name = await _get_user_tz(user_id) if recurrence else None

    parsed_scheduled_at, notes, error = _resolve_first_fire(recurrence, scheduled_at, user_tz_name)
    if error:
        return error

    try:
        parsed_priority = Priority(priority)
    except ValueError:
        return f"Error: invalid priority '{priority}'. Use one of: high, medium, low, none"

    result = await tracked_todo_service.create_tracked_todo(
        user_id=user_id,
        title=title,
        description=description,
        initial_canvas=initial_canvas,
        labels=labels,
        priority=parsed_priority,
    )

    persist_error = await _persist_scheduling_fields(
        result.id, user_id, parsed_scheduled_at, recurrence, expires_at
    )
    if persist_error:
        return persist_error

    if parsed_scheduled_at:
        schedule_error = await _schedule_execution_after_create(result.id, parsed_scheduled_at)
        if schedule_error:
            return schedule_error

    return _format_create_output(result, parsed_scheduled_at, user_tz_name, notes)


@tool
async def search_todo_context(
    config: RunnableConfig,
    query: Annotated[str, "Search query to find relevant tracked todo context"],
    top_k: Annotated[int, "Max results to return"] = 5,
    include_completed: Annotated[
        bool,
        "Include completed todos in search results (default True for full history)",
    ] = True,
) -> str:
    """
    Semantic search across all tracked todo canvases for the current user.

    Use to find relevant context from existing tracked todos before
    creating a new one or to recall details from past work.
    """
    user_id = config.get("metadata", {}).get("user_id")
    if not user_id:
        return _ERR_NO_USER_ID

    matches = await search_canvas_context(
        query=query,
        user_id=user_id,
        top_k=top_k,
        include_completed=include_completed,
    )

    if not matches:
        return "No matching tracked todo context found."

    lines = []
    for m in matches:
        status = " [completed]" if m.get("completed") else ""
        lines.append(
            f"- [{m['title']}]{status} (todo_id: {m['todo_id']}, score: {m['score']})\n"
            f"  {m['snippet'][:200]}"
        )
    return "\n".join(lines)


@tool
async def update_tracked_todo_canvas(
    config: RunnableConfig,
    todo_id: Annotated[str, "ID of the tracked todo"],
    content: Annotated[
        str,
        "Content to write. "
        "For mode='replace': full canvas markdown. "
        "For mode='append': only the new content to add at the end. "
        "For mode='section': only the new body of the target section (without the heading line).",
    ],
    mode: Annotated[
        str,
        "How to write: "
        "'append' (default): add content at the end of the canvas. Use for activity log entries, timeline events, new notes. No read needed. "
        "'section': replace a specific ## Section by name. Use for targeted updates (e.g. Current State). Tool reads and patches internally, no read needed. "
        "'replace': overwrite the entire canvas. Only use for initial setup or full restructure.",
    ] = "append",
    section: Annotated[
        str | None,
        "Section heading to replace when mode='section'. "
        "Exact heading text without ## (e.g. 'Current State', 'Key Details', 'Learnings'). "
        "If the section does not exist, it is appended as a new section.",
    ] = None,
) -> str:
    """Update GAIA's working notes on an EXISTING tracked todo's canvas.

    PRECONDITION: only call this when you already have a tracked todo for THIS initiative:
    one you created this turn (you hold its todo_id) or the run's "🎯 ACTIVE TODO". If no
    tracked todo exists for the task (a one-off fetch / deploy / build / lookup / edit), do
    NOT call this. The canvas lives on the todo, not the filesystem, never use read/write/edit.

    Modes (once you have a todo_id):
    append  → activity log entries, timeline events, new context. No read needed.
    section → update a single named section (e.g. Current State). No read needed.
    replace → full rewrite. Only when restructuring the entire canvas.
    """
    user_id = config.get("metadata", {}).get("user_id")
    if not user_id:
        return _ERR_NO_USER_ID

    if mode not in ("replace", "append", "section"):
        return f"Error: invalid mode '{mode}'. Use 'replace', 'append', or 'section'."

    if mode == "section" and not section:
        return "Error: 'section' mode requires a section name."

    doc = await todo_repository.get(todo_id, user_id=user_id)
    if not doc:
        return f"Error: tracked todo {todo_id} not found"

    if mode == "replace":
        await write_canvas(todo_id, user_id, content)
    elif mode == "append":
        await append_canvas(todo_id, user_id, content)
    else:  # section
        current = await read_canvas(todo_id, user_id) or ""
        new_canvas = _patch_canvas_section(current, section or "", content)
        await write_canvas(todo_id, user_id, new_canvas)

    spawn_logged_task(
        "canvas_reindex",
        tracked_todo_service.reindex_canvas(todo_id=todo_id, user_id=user_id),
        user={"id": user_id},
        todo={"id": todo_id},
    )
    section_suffix = f", section={section}" if section else ""
    await tracked_todo_service.system_log(
        todo_id=todo_id,
        user_id=user_id,
        event_type="CANVAS_UPDATED",
        details=f"Agent updated canvas (mode={mode}{section_suffix})",
    )
    return f"Canvas updated (mode={mode}{section_suffix})."


@tool
async def complete_tracked_todo(
    config: RunnableConfig,
    todo_id: Annotated[str, "ID of the tracked todo to complete"],
    summary: Annotated[str, "One or two sentences describing what was achieved"],
) -> str:
    """Complete a tracked todo: archive VFS canvas, remove from search index, mark done.

    Call when the todo's goal is fully achieved. Use the regular todo update for
    partial completion or status changes only.
    """
    user_id = config.get("metadata", {}).get("user_id")
    if not user_id:
        return _ERR_NO_USER_ID

    success = await tracked_todo_service.complete_tracked_todo(
        todo_id=todo_id, user_id=user_id, summary=summary
    )
    if not success:
        return f"Error: could not complete tracked todo {todo_id}, not found or missing vfs_path"
    return f"Tracked todo {todo_id} completed and archived."


@tool
async def update_tracked_todo(
    config: RunnableConfig,
    todo_id: Annotated[str, "ID of the tracked todo to update"],
    labels: Annotated[
        list[str] | None,
        "New labels to SET on the todo (replaces all existing labels). "
        "Always include 'gaia-tracked' in the list.",
    ] = None,
    due_date: Annotated[
        str | None,
        "ISO datetime string for the deadline. Set to empty string '' to clear.",
    ] = None,
    priority: Annotated[
        str | None,
        "Priority: 'high', 'medium', 'low', or 'none'.",
    ] = None,
    scheduled_at: Annotated[
        str | None,
        "ISO datetime for one-shot scheduled execution, or first-fire anchor for "
        "shortcut recurrences ('daily', 'weekly', 'every_4h', 'every_1h'). "
        "OMIT for cron-style recurrence: first fire is computed from the cron. "
        "Always include the user's timezone offset. Set to empty string '' to clear.",
    ] = None,
    recurrence: Annotated[
        str | None,
        "Recurrence pattern: 'daily', 'weekly', 'every_4h', 'every_1h', or 5-field cron. "
        "ALWAYS evaluated in the user's stored timezone. "
        "Example: '0 9,20 * * *' = 9 AM and 8 PM daily in the user's tz. "
        "Set to empty string '' to clear.",
    ] = None,
    expires_at: Annotated[
        str | None,
        "ISO datetime when this todo becomes irrelevant. Set to empty string '' to clear. "
        "Different from due_date: due_date = deadline (overdue = still needs doing), "
        "expires_at = relevance window (expired = no longer worth tracking).",
    ] = None,
    references: Annotated[
        list[str] | None,
        "IDs of related past tracked todos to link. Appended to existing references.",
    ] = None,
) -> str:
    """Update properties of an existing tracked todo.

    Use this to change labels, due dates, priority, scheduling, or recurrence
    after a tracked todo has been created. For updating canvas content,
    use update_tracked_todo_canvas instead.

    Args:
        todo_id: The tracked todo ID (from ACTIVE TRACKED TODOS context block).
        labels: Replace labels. Always include 'gaia-tracked'.
        due_date: Set or clear due date.
        priority: Change priority.
        scheduled_at: Schedule or reschedule execution. Must be in the future.
        recurrence: Set or clear recurrence pattern.
        expires_at: Set or clear the expiry datetime (when the todo becomes irrelevant).
        references: IDs of related past tracked todos to link (appended to existing).
    """
    user_id = config.get("metadata", {}).get("user_id")
    if not user_id:
        return _ERR_NO_USER_ID

    update_fields: dict[str, object] = {}
    notes: list[str] = []

    # Validate each field sequentially with short-circuit so we don't keep doing
    # work (in particular the async _get_user_tz Mongo lookup inside the
    # recurrence validator) after an earlier field has already failed.
    # _build_labels_update can never actually return an error today (there is
    # no label validation yet) — the check-and-return is kept for the same
    # shape as every other field below, so adding label validation later
    # doesn't require restoring this line.
    if error := _build_labels_update(labels, update_fields):  # pragma: no cover
        return error
    if error := _build_clearable_datetime_update(due_date, "due_date", update_fields):
        return error
    if error := _build_priority_update(priority, update_fields):
        return error
    if error := _build_scheduled_at_update(scheduled_at, update_fields):
        return error
    if error := await _build_recurrence_update(
        recurrence, scheduled_at, user_id, update_fields, notes
    ):
        return error
    if error := _build_clearable_datetime_update(expires_at, "expires_at", update_fields):
        return error

    if not update_fields:
        return "No fields to update. Provide at least one field to change."

    # Validate the resulting state against the existing doc — the in-call guards
    # alone can't catch corruption when the DB already has scheduling fields set.
    existing = await todo_repository.get(todo_id, user_id=user_id)
    if not existing:
        return f"Error: tracked todo {todo_id} not found or not a tracked todo."

    effective_scheduled_at = update_fields.get("scheduled_at", existing.scheduled_at)
    effective_recurrence = update_fields.get("recurrence", existing.recurrence)
    if effective_recurrence and not effective_scheduled_at:
        return (
            "Error: cannot have recurrence without scheduled_at. "
            "Either clear recurrence or provide a scheduled_at value."
        )

    updated = await todo_repository.update(
        todo_id, user_id=user_id, update=TodoUpdate.model_validate(update_fields)
    )
    if updated is None:
        return f"Error: tracked todo {todo_id} not found or not a tracked todo."

    # If scheduled_at landed in update_fields with a real datetime (agent-passed or
    # cron-derived), reschedule the ARQ job.
    new_scheduled_at = update_fields.get("scheduled_at")
    if isinstance(new_scheduled_at, datetime):
        await tracked_todo_service.reschedule_execution(todo_id, new_scheduled_at)

    updated_keys = list(update_fields)
    if references is not None:
        await todo_repository.add_references(todo_id, user_id=user_id, references=references)
        updated_keys.append("references")

    msg = f"Updated tracked todo {todo_id}: {', '.join(updated_keys)}"
    if notes:
        msg += "\nNotes:\n  - " + "\n  - ".join(notes)
    return msg


@tool
async def list_tracked_todos(
    config: RunnableConfig,
) -> str:
    """List all active tracked todos with full metadata.

    Returns a formatted list of all tracked todos (not completed) with their
    ID, title, labels, due_date, scheduled_at, recurrence, expires_at,
    priority, and age. Use this when you need a complete picture of all
    tracked work, beyond what's in the ACTIVE TRACKED TODOS context block.
    """
    user_id = config.get("metadata", {}).get("user_id")
    if not user_id:
        return _ERR_NO_USER_ID

    docs = await todo_repository.list_active_tracked(user_id, limit=50)
    if not docs:
        return "No active tracked todos."

    now = datetime.now(UTC)
    lines = [_format_tracked_todo_full(doc, now) for doc in docs]
    return f"Active tracked todos ({len(docs)}):\n\n" + "\n\n".join(lines)


@tool
async def list_trigger_fields(
    trigger_name: Annotated[
        str,
        "GAIA trigger slug, e.g. 'gmail_new_message', 'calendar_event_starting_soon', "
        "'slack_new_message'. Call with a wrong name to get the full list of "
        "subscribable triggers back.",
    ],
) -> str:
    """Show exactly what an integration trigger delivers, before subscribing to it.

    Returns the trigger's matchable fields with types, descriptions and example
    values, which fields are deliberately not matchable and why, and the operators
    each type accepts. Call this first whenever you are about to watch a trigger
    you have not used in this conversation: the conditions you write must name
    real fields, and this is where you learn what they are instead of guessing.
    """
    return _render_catalog(trigger_name)


@tool
async def subscribe_todo_to_trigger(
    config: RunnableConfig,
    todo_id: Annotated[str, "ID of the tracked todo that should watch for this event"],
    trigger_name: Annotated[str, "GAIA trigger slug to watch, e.g. 'gmail_new_message'"],
    action: Annotated[
        str,
        "What to do when it fires: 'execute' (run the todo with the event in its "
        "context), 'notify' (tell the user, change nothing), 'complete' (mark the "
        "todo done), or 'unblock' (clear its waiting label).",
    ],
    conditions: Annotated[
        list[dict[str, str | int | float]] | None,
        "Narrowing tests. Each is "
        "{'field_name': ..., 'operator': ..., 'value': ...} using fields from "
        "list_trigger_fields. Omit to fire on every event for this trigger, which is only "
        "sensible for a trigger already scoped to one channel or calendar.",
    ] = None,
    match: Annotated[
        str,
        "How the conditions combine: 'all' (every condition must hold, the "
        "default) or 'any' (fire if any one holds). For an OR of several ANDs, "
        "make several 'all' subscriptions instead.",
        # _parse_match lowercases before ConditionMatch(), so the default's CASE
        # is unobservable ("ALL" behaves identically to "all") — mutating it is a
        # provably-equivalent mutant with no possible killing test.
    ] = "all",  # pragma: no mutate
    cooldown_seconds: Annotated[
        int, "Minimum gap between two fires of this subscription."
    ] = DEFAULT_COOLDOWN_SECONDS,
    minutes_before_start: Annotated[
        int | None,
        "For 'calendar_event_starting_soon' only: how long before the event to "
        "fire (1-1440). This is registration config, not a condition, so use one "
        "subscription per reminder window.",
    ] = None,
) -> str:
    """Make a tracked todo react to an integration event instead of only a schedule.

    Use when a todo is waiting on something outside GAIA: a reply to an email you
    sent, a calendar event about to start, a Linear issue changing, a row landing
    in a sheet. The todo then wakes itself when that happens.

    Write conditions against real payload fields. Call list_trigger_fields first
    if you are unsure what a trigger delivers. Obvious mistakes (a camelCased
    field name, an operator that cannot apply to the field's type, a number sent
    as text) are repaired automatically and reported back. Anything ambiguous is
    rejected with the fields that do exist, so you can correct it and call again;
    nothing is ever quietly widened to make it fit.
    """
    user_id = config.get("metadata", {}).get("user_id")
    if not user_id:
        return _ERR_NO_USER_ID

    parsed_action = _parse_action(action)
    if parsed_action is None:
        valid = ", ".join(a.value for a in SubscriptionAction)
        return f"Error: '{action}' is not a valid action. Valid actions: {valid}."

    parsed_match = _parse_match(match)
    if parsed_match is None:
        valid = ", ".join(m.value for m in ConditionMatch)
        return f"Error: '{match}' is not a valid match mode. Valid modes: {valid}."

    parsed_conditions, condition_error = _parse_conditions(conditions or [])
    if condition_error:
        return f"Error: {condition_error}\n\n{_render_catalog(trigger_name)}"

    trigger_data = (
        {"minutes_before_start": minutes_before_start} if minutes_before_start is not None else None
    )

    try:
        subscription, outcome = await register_subscription(
            todo_id=todo_id,
            user_id=user_id,
            trigger_name=trigger_name,
            conditions=parsed_conditions,
            action=parsed_action,
            match=parsed_match,
            cooldown_seconds=cooldown_seconds,
            trigger_data=trigger_data,
        )
    except SubscriptionError as e:
        # The catalog rides along on failure so the retry has what it needs.
        return f"Could not subscribe: {e}\n\n{_render_catalog(trigger_name)}"

    lines = [
        f"Todo {todo_id} is now watching {trigger_name} and will {parsed_action} when it fires.",
        f"Subscription id: {subscription.id}",
    ]
    if outcome.repairs:
        lines.append("Repaired automatically: " + "; ".join(r.reason for r in outcome.repairs))
    return "\n".join(lines)


@tool
async def unsubscribe_todo_from_trigger(
    config: RunnableConfig,
    todo_id: Annotated[str, "ID of the tracked todo"],
    subscription_id: Annotated[
        str, "Subscription id, as shown by list_tracked_todos on the todo's Watching line"
    ],
) -> str:
    """Stop a tracked todo watching one event it subscribed to.

    Use when the thing it was waiting for is no longer relevant but the todo is
    still open. Completing a todo tears its watches down on its own, so you do not
    need to call this first.
    """
    user_id = config.get("metadata", {}).get("user_id")
    if not user_id:
        return _ERR_NO_USER_ID

    removed = await unregister_subscription(todo_id, user_id, subscription_id)
    if not removed:
        return f"No subscription {subscription_id} on todo {todo_id}."
    return f"Todo {todo_id} has stopped watching {removed.trigger_name}."


def _parse_action(action: str) -> SubscriptionAction | None:
    try:
        return SubscriptionAction(action.strip().lower())
    except ValueError:
        return None


def _parse_match(match: str) -> ConditionMatch | None:
    try:
        return ConditionMatch(match.strip().lower())
    except ValueError:
        return None


def _parse_conditions(
    raw: list[dict[str, str | int | float]],
) -> tuple[list[SubscriptionCondition], str | None]:
    """Turn the tool's loose condition dicts into typed conditions.

    Shape errors are caught here and reported with the catalog rather than raising
    a validation traceback the model cannot read.
    """
    parsed: list[SubscriptionCondition] = []
    for item in raw:
        field_name = item.get("field_name")
        operator = item.get("operator")
        value = item.get("value")
        if not isinstance(field_name, str) or not isinstance(operator, str) or value is None:
            return [], (f"each condition needs 'field_name', 'operator' and 'value'; got {item!r}")
        try:
            parsed_operator = ConditionOperator(operator.strip().lower())
        except ValueError:
            valid = ", ".join(o.value for o in ConditionOperator)
            return [], f"'{operator}' is not a valid operator. Valid operators: {valid}."
        parsed.append(
            SubscriptionCondition(field_name=field_name, operator=parsed_operator, value=value)
        )
    return parsed, None


tools = [
    create_tracked_todo,
    search_todo_context,
    update_tracked_todo_canvas,
    complete_tracked_todo,
    update_tracked_todo,
    list_tracked_todos,
    list_trigger_fields,
    subscribe_todo_to_trigger,
    unsubscribe_todo_from_trigger,
]
