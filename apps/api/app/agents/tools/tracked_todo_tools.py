"""
Tracked-todo LangChain tools for the executor agent.

Allows GAIA's executor to create tracked todos with VFS canvas
and search across canvas context via ChromaDB.
"""

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Annotated, Any

from croniter import croniter as _croniter
from langchain_core.runnables import RunnableConfig
from langchain_core.tools import tool

from app.constants.todos import ASSIGNEE_GAIA, FACET_FIELDS, FACET_NOTES
from app.db.repositories.todos import todo_repository
from app.models.agent_models import agent_configurable
from app.models.todo_models import (
    Priority,
    TodoDocument,
    TodoResponse,
    TodoUpdate,
    TrackedTodoDraft,
)
from app.models.trigger_subscription_models import (
    OPERATORS_BY_FIELD_TYPE,
    ConditionMatch,
    ConditionOperator,
    SubscriptionAction,
    SubscriptionCondition,
    SubscriptionStatus,
)
from app.services.payments.payment_service import payment_service
from app.services.todo_canvas_storage import append_facet, read_facet, write_facet
from app.services.todos import gaia_todo_lifecycle as lifecycle
from app.services.todos.gaia_todo_lifecycle import (
    BudgetExceededError,
    TraceabilityError,
)
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
        parsed = datetime.fromisoformat(iso_str)
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
    update_kwargs: dict[str, Any] = {}
    if parsed_scheduled_at:
        update_kwargs["scheduled_at"] = parsed_scheduled_at
    if recurrence:
        update_kwargs["recurrence"] = recurrence
    if expires_at:
        try:
            update_kwargs["expires_at"] = datetime.fromisoformat(expires_at)
        except ValueError:
            return f"Error: invalid expires_at format '{expires_at}'."
    await todo_repository.update(todo_id, user_id=user_id, update=TodoUpdate(**update_kwargs))
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


def _build_labels_update(labels: list[str] | None, update_fields: dict[str, Any]) -> str | None:
    """Apply a labels update, setting the labels exactly as passed."""
    if labels is None:
        return None
    update_fields["labels"] = labels
    return None


def _build_clearable_datetime_update(
    value: str | None, field_name: str, update_fields: dict[str, Any]
) -> str | None:
    """Set, clear (""), or skip (None) a datetime field; returns user-facing error on bad format."""
    if value is None:
        return None
    if value == "":
        update_fields[field_name] = None
        return None
    try:
        update_fields[field_name] = datetime.fromisoformat(value)
    except ValueError:
        return f"Error: invalid {field_name} format '{value}'."
    return None


def _build_priority_update(priority: Priority | None, update_fields: dict[str, Any]) -> str | None:
    """Apply a priority update."""
    if priority is not None:
        update_fields["priority"] = priority.value
    return None


def _build_scheduled_at_update(
    scheduled_at: str | None, update_fields: dict[str, Any]
) -> str | None:
    """Apply a scheduled_at update (must be in the future) or clear it."""
    if scheduled_at is None:
        return None
    if scheduled_at == "":
        update_fields["scheduled_at"] = None
        return None
    try:
        parsed_at = datetime.fromisoformat(scheduled_at)
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
    update_fields: dict[str, Any],
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
    update_fields: dict[str, Any],
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
class _TrackedTodoEdits:
    """The raw, agent-supplied property edits one update_tracked_todo call carries."""

    labels: list[str] | None
    due_date: str | None
    priority: Priority | None
    scheduled_at: str | None
    recurrence: str | None
    expires_at: str | None


async def _collect_update_fields(
    edits: _TrackedTodoEdits,
    user_id: str,
    update_fields: dict[str, Any],
    notes: list[str],
) -> str | None:
    """Validate every supplied edit into ``update_fields``; returns the first error.

    Validation short-circuits so no later work runs (in particular the async
    ``_get_user_tz`` Mongo lookup inside the recurrence validator) once a field
    has already failed.
    """
    # _build_labels_update can never actually return an error today (there is
    # no label validation yet) — the check-and-return is kept for the same
    # shape as every other field below, so adding label validation later
    # doesn't require restoring this line.
    if error := _build_labels_update(edits.labels, update_fields):  # pragma: no cover
        return error
    if error := _build_clearable_datetime_update(edits.due_date, "due_date", update_fields):
        return error
    if error := _build_priority_update(edits.priority, update_fields):
        return error
    if error := _build_scheduled_at_update(edits.scheduled_at, update_fields):
        return error
    if error := await _build_recurrence_update(
        edits.recurrence, edits.scheduled_at, user_id, update_fields, notes
    ):
        return error
    return _build_clearable_datetime_update(edits.expires_at, "expires_at", update_fields)


def _build_list_detail_parts(doc: TodoDocument, now: datetime) -> list[str]:
    """Build the pipe-separated detail fragments shown on the second line of each todo."""
    parts: list[str] = []
    if due_date := doc.due_date:
        days_until = (due_date - now).days
        parts.append(f"Due: OVERDUE {-days_until}d" if days_until < 0 else f"Due: {days_until}d")
    if scheduled := doc.scheduled_at:
        parts.append(f"Scheduled: {scheduled.isoformat()}")
    if recurrence := doc.recurrence:
        parts.append(f"Recurrence: {recurrence}")
    if expires := doc.expires_at:
        expires_days = (expires - now).days
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
    todo_id = doc.id
    title = doc.title or "Untitled"
    labels_str = f" [{', '.join(doc.labels)}]" if doc.labels else ""
    priority = doc.priority.value
    age_days = (now - (doc.created_at or now)).days
    last_update = (now - (doc.updated_at or now)).days

    parts = [
        f'- "{title}"{labels_str} (ID: {todo_id})',
        f"  Priority: {priority} | Age: {age_days}d | Last updated: {last_update}d ago",
    ]
    detail_parts = _build_list_detail_parts(doc, now)
    if detail_parts:
        parts.append(f"  {' | '.join(detail_parts)}")
    parts.extend(f"  {line}" for line in _format_subscription_lines(doc))
    return "\n".join(parts)


def _strip_redundant_heading(content: str, section: str) -> str:
    """Drop a leading `## {section}` line the caller repeated inside the body.

    The patch re-emits the heading itself, so a copy at the top of `content`
    would double it (`## Key Details` / `## Key Details`) — the exact structural
    bug seen in the wild when the model includes the heading in its section body.
    """
    body = content.lstrip("\n")
    first_line, _, rest = body.partition("\n")
    if first_line.strip().lower() == f"## {section}".strip().lower():
        return rest.lstrip("\n")
    return content


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
    content = _strip_redundant_heading(content, section)
    heading = f"## {section}"
    head_end: int | None = None
    # `str.find(sub, None)` behaves exactly like `str.find(sub, 0)`, and every
    # later pass reassigns this to an int, so swapping the initial 0 for None is
    # a provably-equivalent mutation with no test that could tell the two apart.
    search_start = 0  # pragma: no mutate
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
        "Its facets (deliverable / notes / log) are stored on this todo. Edit them "
        f"ONLY via update_tracked_todo_canvas(todo_id='{result.id}', facet=..., ...), "
        "never with filesystem tools."
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
    serves: Annotated[
        str,
        "REQUIRED traceability: the goal, memory item, or explicit user request "
        "this todo advances (e.g. 'raising a pre-seed round'). Shown to the user "
        "as 'because: ...'. Creation is rejected when empty.",
    ],
    *,
    requires_approval: Annotated[
        bool,
        "Approval rule (outward-visibility): True when executing this todo takes "
        "an action the outside world can see - sending email/DMs, posting, "
        "inviting others to events, spending money. The todo then enters "
        "'proposed' and waits for the user's Approve tap. False when the work is "
        "visible only to the user and GAIA - research, drafts, triage, prep - "
        "which enters 'queued' and executes without permission. "
        "EXPLICIT-INSTRUCTION EXCEPTION: when the user's own words directly "
        "instructed this exact outward action with its target ('send Bob the "
        "invoice reminder tomorrow at 9'), their instruction IS the approval - "
        "use False so it executes on schedule instead of re-asking. This only "
        "applies when the user named the action AND the recipient/target "
        "themselves; a goal ('help me collect invoices') or a vague ask does NOT "
        "qualify - propose those. The send-time approval gate independently "
        "verifies the user's words authorized the action, so an over-eager False "
        "still cannot send anything the user never asked for. "
        "STAGING INVARIANT: a proposal (True) is rejected unless `initial_deliverable` "
        "carries the exact content approving will release. Do the prep first "
        "(internal todo), then create the proposal with the finished content.",
    ],
    kind: Annotated[
        str,
        "'task' (default) or 'goal'. A goal is a long-lived lane (raising a "
        "round, growing users): its canvas is the living strategy the nightly "
        "pass advances. Create a goal ONLY after the user has confirmed it in "
        "conversation, never silently. Goals skip the in-flight budget but are "
        "capped at 3 active.",
    ] = "task",
    goal_id: Annotated[
        str | None,
        "ID of the goal-todo this task advances. Set it on every task that "
        "belongs to a goal lane so traceability is a real link.",
    ] = None,
    description: Annotated[
        str | None,
        "Optional description of what this todo is tracking",
    ] = None,
    initial_deliverable: Annotated[
        str | None,
        "The deliverable facet: the polished, send-ready output (markdown). For a "
        "proposal (requires_approval=True) this is REQUIRED and is the exact "
        "content Approve releases. For internal work it is optional (a light "
        "template is used if omitted).",
    ] = None,
    initial_notes: Annotated[
        str | None,
        "Optional initial notes facet content (GAIA's private working memory: "
        "plan, key details, current state). If omitted, a template is used.",
    ] = None,
    labels: Annotated[
        list[str] | None,
        "Optional labels for categorization",
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

    IMPORTANT: Read the "tracked-todo-working-memory" skill for the search-first workflow,
    canvas structure, and goal lanes before creating. Scheduling specifics live in the
    scheduled_at / recurrence / expires_at args below.

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
    metadata = config.get("metadata", {})
    user_id = metadata.get("user_id")
    if not user_id:
        return _ERR_NO_USER_ID
    # The chat this tracked todo was created in, captured for a later push back
    # into it. build_agent_config puts conversation_id in `configurable` (not
    # `metadata`), so read it there — matching reminder_tool. None for a non-chat
    # root (onboarding/REST).
    source_conversation_id = agent_configurable(config).get("conversation_id")

    # Recurrence is always evaluated in the user's stored timezone. We only
    # look it up here to (a) compute the first cron fire correctly and (b)
    # surface a user-readable note in the return value.
    user_tz_name = await _get_user_tz(user_id) if recurrence else None

    parsed_scheduled_at, notes, error = _resolve_first_fire(recurrence, scheduled_at, user_tz_name)
    if error:
        return error

    try:
        result = await tracked_todo_service.create_tracked_todo(
            user_id,
            TrackedTodoDraft(
                title=title,
                serves=serves,
                requires_approval=requires_approval,
                kind=kind,
                goal_id=goal_id,
                description=description,
                initial_deliverable=initial_deliverable,
                initial_notes=initial_notes,
                labels=labels,
                priority=priority,
                source_conversation_id=source_conversation_id,
                # A todo with its own schedule/recurrence fires at that time, not
                # now (the scheduling below arms it); everything else starts
                # immediately.
                auto_execute=not (parsed_scheduled_at or recurrence),
            ),
        )
    except (TraceabilityError, BudgetExceededError) as e:
        return f"Error: {e}"

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
    facet: Annotated[
        str,
        "Which facet to write: "
        "'notes' (default): GAIA's private working memory (plan, key details, current state). "
        "'deliverable': the polished, send-ready output the user sees (what Approve releases). "
        "'log': the activity/timeline audit trail. "
        "Write drafts, decisions, and scratch to 'notes'; write only finished, "
        "user-facing output to 'deliverable'.",
    ] = FACET_NOTES,
) -> str:
    """Update a facet (notes / deliverable / log) of an EXISTING tracked todo.

    PRECONDITION: call this only when you already hold a tracked todo for THIS initiative,
    one you created this turn or the run's "🎯 ACTIVE TODO". For a one-off fetch, deploy,
    build, lookup, or edit with no tracked todo, do not call it. Facets live on the todo,
    not the filesystem, so never reach for read/write/edit. See the `facet` and `mode` args
    for which facet holds what and how each write mode behaves.
    """
    user_id = config.get("metadata", {}).get("user_id")
    if not user_id:
        return _ERR_NO_USER_ID

    if mode not in ("replace", "append", "section"):
        return f"Error: invalid mode '{mode}'. Use 'replace', 'append', or 'section'."

    if facet not in FACET_FIELDS:
        return f"Error: invalid facet '{facet}'. Use one of: {', '.join(sorted(FACET_FIELDS))}."

    if mode == "section" and not section:
        return "Error: 'section' mode requires a section name."

    doc = await todo_repository.get(todo_id, user_id=user_id)
    if not doc:
        return f"Error: tracked todo {todo_id} not found"

    if mode == "replace":
        await write_facet(todo_id, user_id, facet, content)
    elif mode == "append":
        await append_facet(todo_id, user_id, facet, content)
    else:  # section
        current = await read_facet(todo_id, user_id, facet) or ""
        # Reaching here means mode == "section", and the guard above already
        # returned for a section mode with no name — so `section` is a non-empty
        # str and the fallback is unreachable. It exists only to narrow
        # `str | None`, which makes mutating it provably equivalent.
        section_name = section or ""  # pragma: no mutate
        patched = _patch_canvas_section(current, section_name, content)
        await write_facet(todo_id, user_id, facet, patched)

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
        details=f"Agent updated {facet} (mode={mode}{section_suffix})",
    )
    return f"Updated {facet} (mode={mode}{section_suffix})."


@tool
async def complete_tracked_todo(
    config: RunnableConfig,
    todo_id: Annotated[str, "ID of the tracked todo to complete"],
    summary: Annotated[str, "One or two sentences describing what was achieved"],
) -> str:
    """Complete a tracked todo: mark it done and archive its canvas. The canvas
    stays in the search index (flagged completed) so past work remains findable.

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
        return f"Error: could not complete tracked todo {todo_id}: not found"
    return f"Tracked todo {todo_id} completed and archived."


@tool
async def update_tracked_todo(
    config: RunnableConfig,
    todo_id: Annotated[str, "ID of the tracked todo to update"],
    *,
    labels: Annotated[
        list[str] | None,
        "New labels to SET on the todo (replaces all existing labels).",
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
) -> str:
    """Update properties of an existing tracked todo.

    Use this to change labels, due dates, priority, scheduling, or recurrence
    after a tracked todo has been created. For updating canvas content,
    use update_tracked_todo_canvas instead.

    Args:
        todo_id: The tracked todo ID (from ACTIVE TRACKED TODOS context block).
        labels: Replace labels.
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

    update_fields: dict[str, Any] = {}
    notes: list[str] = []
    edits = _TrackedTodoEdits(
        labels=labels,
        due_date=due_date,
        priority=priority,
        scheduled_at=scheduled_at,
        recurrence=recurrence,
        expires_at=expires_at,
    )
    if error := await _collect_update_fields(edits, user_id, update_fields, notes):
        return error

    if not update_fields and references is None:
        return "No fields to update. Provide at least one field to change."

    # Validate the resulting state against the existing doc — the in-call guards
    # alone can't catch corruption when the DB already has scheduling fields set.
    existing = await todo_repository.get(todo_id, user_id=user_id)
    if not existing or existing.assignee != ASSIGNEE_GAIA:
        return f"Error: tracked todo {todo_id} not found or not a tracked todo."

    effective_scheduled_at = update_fields.get("scheduled_at", existing.scheduled_at)
    effective_recurrence = update_fields.get("recurrence", existing.recurrence)
    if effective_recurrence and not effective_scheduled_at:
        return (
            "Error: cannot have recurrence without scheduled_at. "
            "Either clear recurrence or provide a scheduled_at value."
        )

    if update_fields:
        updated = await todo_repository.update(
            todo_id, user_id=user_id, update=TodoUpdate(**update_fields)
        )
        if updated is None:
            return f"Error: tracked todo {todo_id} not found or not a tracked todo."

        # If scheduled_at landed in update_fields with a real datetime (agent-passed
        # or cron-derived), reschedule the ARQ job.
        new_scheduled_at = update_fields.get("scheduled_at")
        if isinstance(new_scheduled_at, datetime):
            await tracked_todo_service.reschedule_execution(todo_id, new_scheduled_at)

    updated_keys = list(update_fields.keys())
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
async def approve_todo(
    config: RunnableConfig,
    todo_id: Annotated[str, "ID of the proposed todo the user is approving"],
    instruction: Annotated[
        str | None,
        "The user's VERBATIM qualifying words about how to execute, whenever "
        "their approval narrowed or adjusted the staged work (e.g. 'only send "
        "the Sequoia one', 'drop the deck link'). Pass their exact words, never "
        "a paraphrase; omit only when they approved without qualification.",
    ] = None,
) -> str:
    """Approve a proposed GAIA todo on the user's explicit say-so, releasing its
    staged work for execution.

    Use ONLY when the user has clearly told you to go ahead in this conversation
    ("send them", "approve it", "yes, post it"). Their words are the approval;
    this tool records it and queues the execution. If their go-ahead came with a
    qualification ("send only...", "but change..."), pass it as ``instruction``
    so the run obeys it. Never call it on your own initiative: proposals exist
    precisely because this decision belongs to the user. To adjust the staged
    content first, edit the canvas, then approve.
    """
    user_id = config.get("metadata", {}).get("user_id")
    if not user_id:
        return _ERR_NO_USER_ID
    plan = await payment_service.get_cached_plan_type(user_id)
    try:
        await lifecycle.approve(todo_id, user_id, plan, channel="chat", instruction=instruction)
    except lifecycle.ExecutionQuotaError as e:
        return (
            f"Blocked by the free plan's execution quota. Tell the user: {e.pitch} "
            f"(resets {e.reset_time or 'next month'}; upgrading to {e.plan_required} lifts it)."
        )
    except lifecycle.InvalidTransitionError as e:
        return f"Error: {e}"
    return f"Approved: todo {todo_id} is queued and its staged work is executing."


@tool
async def dismiss_todo(
    config: RunnableConfig,
    todo_id: Annotated[str, "ID of the proposed todo the user is declining"],
    reason: Annotated[
        str | None,
        "The user's reason in their own words, when they gave one. It teaches "
        "what not to propose again.",
    ] = None,
) -> str:
    """Dismiss a proposed GAIA todo on the user's explicit say-so.

    Use ONLY when the user has clearly declined the proposal in this
    conversation ("don't send those", "skip it", "not this"). The rejection is
    recorded as a memory signal so this kind of proposal stops recurring.
    """
    user_id = config.get("metadata", {}).get("user_id")
    if not user_id:
        return _ERR_NO_USER_ID
    try:
        await lifecycle.dismiss(todo_id, user_id, reason=reason, channel="chat")
    except lifecycle.InvalidTransitionError as e:
        return f"Error: {e}"
    return f"Dismissed: todo {todo_id} will not run, and the rejection was recorded."


@tool
async def block_todo(
    config: RunnableConfig,
    todo_id: Annotated[str, "ID of the todo whose run is blocked"],
    question: Annotated[str, "The decision you need from the user, phrased as one clear question"],
) -> str:
    """Pause a todo you are executing on a decision only the user can make.

    Use mid-run when continuing would mean guessing (which recipient, which
    figure, spend or not) or when an approved plan grows a NEW outward action.
    The question is shown on the dashboard and asked in chat; the run resumes
    automatically once the user answers. Never guess instead of blocking.
    """
    user_id = config.get("metadata", {}).get("user_id")
    if not user_id:
        return _ERR_NO_USER_ID
    try:
        await lifecycle.block(todo_id, user_id, question)
    except lifecycle.InvalidTransitionError as e:
        return f"Error: {e}"
    return f"Blocked: todo {todo_id} is waiting on the user's answer to: {question}"


@tool
async def answer_todo(
    config: RunnableConfig,
    todo_id: Annotated[str, "ID of the needs_you todo the user is answering"],
    answer: Annotated[str, "The user's answer, in their own words"],
) -> str:
    """Resume a blocked (needs_you) todo with the user's answer.

    Use ONLY when the user has answered the blocking question in this
    conversation. Records the answer in the todo's notes and re-queues the
    run; the next execution reads it and continues where it stopped.
    """
    user_id = config.get("metadata", {}).get("user_id")
    if not user_id:
        return _ERR_NO_USER_ID
    try:
        await lifecycle.answer(todo_id, user_id, answer, channel="chat")
    except lifecycle.InvalidTransitionError as e:
        return f"Error: {e}"
    return f"Answered: todo {todo_id} is queued again and will continue with the user's answer."


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
    approve_todo,
    dismiss_todo,
    block_todo,
    answer_todo,
    list_trigger_fields,
    subscribe_todo_to_trigger,
    unsubscribe_todo_from_trigger,
]
