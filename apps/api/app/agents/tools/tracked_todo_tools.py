"""
Tracked-todo LangChain tools for the executor agent.

Lifecycle and metadata only. The working notes (canvas.md / activity.md) are
files under /workspace/gaia-tasks/ that the agent reads and edits with the
ordinary file tools; see ``app.services.gaia_task_files``.
"""

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Annotated

from croniter import croniter as _croniter
from langchain_core.runnables import RunnableConfig
from langchain_core.tools import tool
from pydantic import BaseModel, ConfigDict

from app.constants.todos import GAIA_TRACKED_LABEL
from app.db.repositories.todos import todo_repository
from app.models.agent_models import read_agent_configurable
from app.models.integrations.composio_hooks import RunMetadata
from app.models.todo_models import Priority, TodoDocument, TodoResponse, TodoUpdate
from app.models.trigger_subscription_models import (
    OPERATORS_BY_FIELD_TYPE,
    ConditionMatch,
    ConditionOperator,
    SubscriptionAction,
    SubscriptionCondition,
    TriggerSubscriptionStatus,
)
from app.services.storage._vfs_common import folder_name
from app.services.todo_canvas_storage import read_canvas, write_canvas
from app.services.tracked_todo_service import tracked_todo_service
from app.services.triggers.matchable_fields import MATCHABLE_TRIGGERS, get_matchable_trigger
from app.services.triggers.scope_catalog import scope_fields_for
from app.services.triggers.subscription_service import (
    DEFAULT_COOLDOWN_SECONDS,
    SubscriptionError,
    register_subscription,
    unregister_subscription,
)
from app.services.triggers.subscription_validation import validate_scope
from app.services.user_service import get_user_by_id
from app.utils.canvas_vector_utils import CanvasSearchMatch, search_canvas_context
from app.utils.cron_utils import get_next_run_time
from app.utils.timezone import Timezone, is_valid_timezone
from shared.py.wide_events import log

_RECURRENCE_SHORTCUTS = {"daily", "weekly", "every_4h", "every_1h"}
_UTC_OFFSET = "+00:00"
_NOTIFY_ON_RUN_DESC = (
    "Whether a scheduled or triggered run may message the user's chat app when it "
    "finds something that matters (routine runs never do). Default True. The "
    "user's setting: set it only when they ask to stop or resume hearing about "
    "this todo; a silent run can still reach them with send_notification when "
    "something genuinely needs them."
)
_ERR_NO_USER_ID = "Error: user_id not found in config"


async def _get_user_tz(user_id: str) -> str:
    """Look up the user's IANA timezone from MongoDB.

    NOTE: This is an uncached DB call per invocation. Acceptable for now —
    recurrence math runs at tool-call time, not in a tight loop. Refactor
    to a cached read if it shows up in profiles.
    """
    try:
        user = await get_user_by_id(user_id)
        if user and user.timezone:
            tz_name = user.timezone
            if is_valid_timezone(tz_name):
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


def _build_priority_update(
    priority: Priority | None, update_fields: dict[str, object]
) -> str | None:
    """Apply a priority update."""
    if priority is not None:
        update_fields["priority"] = priority.value
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


@dataclass(frozen=True)
class _UpdateFieldInputs:
    """The raw agent-supplied field values for update_tracked_todo, bundled so the
    validator chain that consumes them is one small helper instead of six inline
    guards on the tool body."""

    labels: list[str] | None
    due_date: str | None
    priority: Priority | None
    scheduled_at: str | None
    recurrence: str | None
    expires_at: str | None


async def _apply_field_updates(
    inputs: _UpdateFieldInputs,
    user_id: str,
    update_fields: dict[str, object],
    notes: list[str],
) -> str | None:
    """Run each field validator in order, short-circuiting on the first error so the
    async _get_user_tz Mongo lookup in the recurrence validator never runs after an
    earlier field already failed. Populates update_fields/notes in place.

    _build_labels_update can never actually return an error today (there is no label
    validation yet); the check is kept for the same shape as the others so adding one
    later needs no restructuring.
    """
    if error := _build_labels_update(inputs.labels, update_fields):  # pragma: no cover
        return error
    if error := _build_clearable_datetime_update(inputs.due_date, "due_date", update_fields):
        return error
    if error := _build_priority_update(inputs.priority, update_fields):
        return error
    if error := _build_scheduled_at_update(inputs.scheduled_at, update_fields):
        return error
    if error := await _build_recurrence_update(
        inputs.recurrence, inputs.scheduled_at, user_id, update_fields, notes
    ):
        return error
    if error := _build_clearable_datetime_update(inputs.expires_at, "expires_at", update_fields):
        return error
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
        f"  files: /workspace/gaia-tasks/{folder_name(doc.id, doc.title)}/",
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
            " (PAUSED: integration disconnected)"
            if sub.status is TriggerSubscriptionStatus.PAUSED
            else ""
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
    scope = scope_fields_for(trigger_name)
    if scope:
        lines.append("Scope this watch with (registration config, passed via the scope argument):")
        lines.extend(
            f"  {s.name} ({s.type}{', required' if s.required else ''}): {s.description}"
            for s in scope
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


def _format_create_output(
    result: TodoResponse,
    parsed_scheduled_at: datetime | None,
    user_tz_name: str | None,
    notes: list[str],
) -> str:
    """Assemble the user-facing summary returned by create_tracked_todo."""
    folder = f"/workspace/gaia-tasks/{folder_name(result.id, result.title)}"
    out = (
        f"Tracked todo created: {result.id}\n"
        f"Title: {result.title}\n"
        f"Working notes: {folder}/canvas.md (recall doc) and {folder}/activity.md "
        "(dated log). Read and edit them with the read / edit / write tools."
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
    priority: Annotated[Priority, "Priority"] = Priority.NONE,
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
    notify_on_run: Annotated[
        bool,
        _NOTIFY_ON_RUN_DESC,
    ] = True,
) -> str:
    """
    Create a tracked todo: a GAIA-managed todo with a working-memory canvas.

    A tracked todo shows on the user's todos page like a normal todo, but GAIA
    owns it: it carries canvas.md (GAIA's recall doc: key IDs, current state,
    context, learnings) and activity.md (dated log of what happened) plus an
    optional schedule/recurrence so GAIA can act on it over time. It is distinct from the user's own hand-created action items
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
    notify_on_run: Whether each run's final message is delivered to the user's chat app.
                On by default; turn it off for runs the user should not hear about.
    """
    user_id = RunMetadata.model_validate(config.get("metadata", {})).user_id
    if not user_id:
        return _ERR_NO_USER_ID
    # conversation_id lives in `configurable`, not `metadata` (matching
    # reminder_tool). None for a non-chat root (onboarding/REST).
    source_conversation_id = read_agent_configurable(config).conversation_id

    # Recurrence is always evaluated in the user's stored timezone. We only
    # look it up here to (a) compute the first cron fire correctly and (b)
    # surface a user-readable note in the return value.
    user_tz_name = await _get_user_tz(user_id) if recurrence else None

    parsed_scheduled_at, notes, error = _resolve_first_fire(recurrence, scheduled_at, user_tz_name)
    if error:
        return error

    result = await tracked_todo_service.create_tracked_todo(
        user_id=user_id,
        title=title,
        description=description,
        initial_canvas=initial_canvas,
        labels=labels,
        priority=priority,
        source_conversation_id=source_conversation_id,
        notify_on_run=notify_on_run,
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
    user_id = RunMetadata.model_validate(config.get("metadata", {})).user_id
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

    return "\n".join(_format_canvas_match(match) for match in matches)


def _format_canvas_match(match: CanvasSearchMatch) -> str:
    status = " [completed]" if match["completed"] else ""
    folder = folder_name(match["todo_id"], match["title"])
    return (
        f"- [{match['title']}]{status} (todo_id: {match['todo_id']}, score: {match['score']})\n"
        f"  files: /workspace/gaia-tasks/{folder}/\n"
        f"  {match['snippet'][:200]}"
    )


@tool
async def complete_tracked_todo(
    config: RunnableConfig,
    todo_id: Annotated[str, "ID of the tracked todo to complete"],
    summary: Annotated[str, "One or two sentences describing what was achieved"],
) -> str:
    """Complete a tracked todo: mark done and flag its canvas as completed in search.

    Call when the todo's goal is fully achieved. Use the regular todo update for
    partial completion or status changes only.
    """
    user_id = RunMetadata.model_validate(config.get("metadata", {})).user_id
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
    priority: Annotated[Priority | None, "Priority"] = None,
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
    notify_on_run: Annotated[
        bool | None,
        _NOTIFY_ON_RUN_DESC,
    ] = None,
) -> str:
    """Update properties of an existing tracked todo.

    Use this to change labels, due dates, priority, scheduling, or recurrence
    after a tracked todo has been created. The working notes are files: edit
    /workspace/gaia-tasks/<folder>/canvas.md or activity.md with the file tools.

    Args:
        todo_id: The tracked todo ID (from ACTIVE TRACKED TODOS context block).
        labels: Replace labels. Always include 'gaia-tracked'.
        due_date: Set or clear due date.
        priority: Change priority.
        scheduled_at: Schedule or reschedule execution. Must be in the future.
        recurrence: Set or clear recurrence pattern.
        expires_at: Set or clear the expiry datetime (when the todo becomes irrelevant).
        references: IDs of related past tracked todos to link (appended to existing).
        notify_on_run: Turn this todo's run-result delivery on or off.
    """
    user_id = RunMetadata.model_validate(config.get("metadata", {})).user_id
    if not user_id:
        return _ERR_NO_USER_ID

    update_fields: dict[str, object] = {}
    notes: list[str] = []
    inputs = _UpdateFieldInputs(
        labels=labels,
        due_date=due_date,
        priority=priority,
        scheduled_at=scheduled_at,
        recurrence=recurrence,
        expires_at=expires_at,
    )
    if error := await _apply_field_updates(inputs, user_id, update_fields, notes):
        return error
    if notify_on_run is not None:
        update_fields["notify_on_run"] = notify_on_run

    if not update_fields:
        return "No fields to update. Provide at least one field to change."

    # Validate the resulting state against the existing doc — the in-call guards
    # alone can't catch corruption when the DB already has scheduling fields set.
    existing = await todo_repository.get(todo_id, user_id=user_id)
    if not existing:
        return f"Error: tracked todo {todo_id} not found or not a tracked todo."

    update = TodoUpdate.model_validate(update_fields)
    effective_scheduled_at = (
        update.scheduled_at if "scheduled_at" in update.model_fields_set else existing.scheduled_at
    )
    effective_recurrence = (
        update.recurrence if "recurrence" in update.model_fields_set else existing.recurrence
    )
    if effective_recurrence and not effective_scheduled_at:
        return (
            "Error: cannot have recurrence without scheduled_at. "
            "Either clear recurrence or provide a scheduled_at value."
        )

    updated = await todo_repository.update(todo_id, user_id=user_id, update=update)
    if updated is None:
        return f"Error: tracked todo {todo_id} not found or not a tracked todo."

    # A real datetime here (agent-passed or cron-derived) means the ARQ job moves.
    if update.scheduled_at is not None:
        await tracked_todo_service.schedule_execution(todo_id, update.scheduled_at)

    updated_keys = list(update_fields)
    if references is not None:
        await todo_repository.add_references(todo_id, user_id=user_id, references=references)
        updated_keys.append("references")

    msg = f"Updated tracked todo {todo_id}: {', '.join(updated_keys)}"
    if notes:
        msg += "\nNotes:\n  - " + "\n  - ".join(notes)
    return msg


@tool
async def update_tracked_todo_canvas(
    config: RunnableConfig,
    todo_id: Annotated[str, "ID of the tracked todo whose canvas to update"],
    content: Annotated[
        str,
        "New canvas content (mode='replace') or text to add at the end (mode='append')",
    ],
    mode: Annotated[
        str,
        "How to apply the update: 'replace' overwrites the whole canvas, "
        "'append' adds to the end of it.",
    ] = "replace",  # pragma: no mutate: mode is strip().lower()-normalized before any use
) -> str:
    """Update a tracked todo's working-memory canvas.

    Use this to record progress, outcomes, IDs, learnings, or follow-ups that
    must survive this turn. Prefer 'append' for progress notes; use 'replace'
    when rewriting the canvas to reflect what is true right now.
    """
    user_id = RunMetadata.model_validate(config.get("metadata", {})).user_id
    if not user_id:
        return _ERR_NO_USER_ID

    normalized = mode.strip().lower()
    if normalized not in ("replace", "append"):
        return f"Error: invalid mode '{mode}'. Use 'replace' or 'append'."
    if normalized == "append":
        current = await read_canvas(todo_id, user_id)
        if current is None:
            return f"Error: tracked todo {todo_id} not found."
        if current:
            suffix = content if content.startswith("\n") else f"\n{content}"
            content = f"{current}{suffix}"

    ok = await write_canvas(todo_id, user_id, content)
    if not ok:
        return f"Error: tracked todo {todo_id} not found."
    return f"Canvas updated for tracked todo {todo_id} (mode: {normalized})."


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
    user_id = RunMetadata.model_validate(config.get("metadata", {})).user_id
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
    scope: Annotated[
        dict[str, str | bool | int | float | list[str]] | None,
        "Registration config telling the trigger which resource to watch, e.g. "
        "{'repos': ['owner/name']} for a github trigger, {'minutes_before_start': "
        "60} for calendar_event_starting_soon. This is NOT a payload condition: "
        "per-resource triggers (github, slack, sheets, notion, linear, asana) do "
        "not fire without it. Call list_trigger_fields to see which scope a "
        "trigger needs.",
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

    Per-resource triggers (github, slack, sheets, notion, linear, asana) need a
    scope naming which resource to watch, e.g. scope={'repos': ['owner/name']}.
    Without it the trigger registers against nothing and never fires;
    list_trigger_fields shows the scope each trigger needs.
    """
    user_id = RunMetadata.model_validate(config.get("metadata", {})).user_id
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

    scope_errors = validate_scope(trigger_name, scope)
    if scope_errors:
        return f"Error: {' '.join(scope_errors)}\n\n{_render_catalog(trigger_name)}"

    trigger_data = scope or None

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
    user_id = RunMetadata.model_validate(config.get("metadata", {})).user_id
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


class _ConditionArgs(BaseModel):
    """One condition as the model sent it; each key keeps its original type or is absent."""

    model_config = ConfigDict(extra="ignore")

    field_name: str | int | float | None = None
    operator: str | int | float | None = None
    value: str | int | float | None = None


def _parse_conditions(
    raw: list[dict[str, str | int | float]],
) -> tuple[list[SubscriptionCondition], str | None]:
    """Turn the tool's loose condition dicts into typed conditions.

    Shape errors are caught here and reported with the catalog rather than raising
    a validation traceback the model cannot read.
    """
    parsed: list[SubscriptionCondition] = []
    for item in raw:
        args = _ConditionArgs.model_validate(item)
        field_name, operator, value = args.field_name, args.operator, args.value
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
    complete_tracked_todo,
    update_tracked_todo,
    update_tracked_todo_canvas,
    list_tracked_todos,
    list_trigger_fields,
    subscribe_todo_to_trigger,
    unsubscribe_todo_from_trigger,
]
