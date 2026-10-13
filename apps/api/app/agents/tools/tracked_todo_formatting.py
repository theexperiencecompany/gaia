"""Response formatting for the tracked-todo tools.

How todos, subscriptions, conditions, and creation outcomes render as the
model-facing strings the @tool entry points in tracked_todo_tools return.
"""

from datetime import UTC, datetime

from app.agents.tools.tracked_todo_fields import format_first_fire_note
from app.constants.todos import (
    CANVAS_CURRENT_STATE_SECTION,
    EXISTING_TODO_STATE_EXCERPT_CHARS,
    GAIA_TRACKED_LABEL,
)
from app.models.todo_models import TodoDocument, TodoResponse
from app.models.trigger_subscription_models import (
    OPERATORS_BY_FIELD_TYPE,
    ConditionArgs,
    ConditionMatch,
    ConditionOperator,
    SubscriptionAction,
    SubscriptionCondition,
    TriggerSubscriptionStatus,
)
from app.services.canvas_markdown import section_body
from app.services.storage._vfs_common import folder_name
from app.services.todos.errors import (
    CanvasShapeError,
    ExternalRefTakenError,
    SubTodoParentError,
    UnwatchedTodoKeptError,
)
from app.services.triggers.matchable_fields import MATCHABLE_TRIGGERS, get_matchable_trigger
from app.services.triggers.scope_catalog import scope_fields_for
from app.services.triggers.subscription_service import SubscriptionError
from app.utils.canvas_vector_utils import CanvasSearchMatch
from app.utils.general_utils import clip_text


def build_list_detail_parts(doc: TodoDocument, now: datetime) -> list[str]:
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


def format_tracked_todo_full(doc: TodoDocument, now: datetime) -> str:
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
    if doc.external_ref:
        parts.append(f"  Owns {doc.external_ref.source.value}: {doc.external_ref.id}")
    if doc.parent_todo_id:
        parts.append(f"  Sub-todo of {doc.parent_todo_id}")
    detail_parts = build_list_detail_parts(doc, now)
    if detail_parts:
        parts.append(f"  {' | '.join(detail_parts)}")
    parts.extend(f"  {line}" for line in format_subscription_lines(doc))
    return "\n".join(parts)


def format_subscription_lines(doc: TodoDocument) -> list[str]:
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


def render_catalog(trigger_name: str) -> str:
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


def format_create_output(
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
        out += format_first_fire_note(parsed_scheduled_at, user_tz_name)
    if notes:
        out += "\nDetails:\n  - " + "\n  - ".join(notes)
    return out


def format_refused_create_output(
    refused: ExternalRefTakenError
    | SubTodoParentError
    | CanvasShapeError
    | SubscriptionError
    | UnwatchedTodoKeptError,
) -> str:
    """Tell the model why nothing (or only part) was created and what to do instead."""
    if isinstance(refused, ExternalRefTakenError):
        return format_ref_taken_output(refused.existing, datetime.now(UTC))
    if isinstance(refused, UnwatchedTodoKeptError):
        return (
            f"Not fully created: {refused.message} Complete it with complete_tracked_todo "
            f"(todo_id={refused.todo_id}) before creating this todo again."
        )
    if isinstance(refused, SubTodoParentError | CanvasShapeError):
        return f"Not created: {refused.message} Nothing was saved."
    return f"Not created: the thread could not be watched ({refused}). Nothing was saved."


def format_ref_taken_output(existing: TodoDocument, now: datetime) -> str:
    """Point the model at the open todo that already owns the thread, instead of a new one."""
    state = section_body(existing.canvas_content, CANVAS_CURRENT_STATE_SECTION)
    return (
        "Not created: this thread already has an open tracked todo. Update it with "
        "update_tracked_todo and its canvas.md instead of creating another.\n"
        f"{format_tracked_todo_full(existing, now)}\n"
        f"  Current State: {clip_text(state or '(empty)', EXISTING_TODO_STATE_EXCERPT_CHARS)}"
    )


def format_canvas_match(match: CanvasSearchMatch) -> str:
    status = " [completed]" if match["completed"] else ""
    folder = folder_name(match["todo_id"], match["title"])
    return (
        f"- [{match['title']}]{status} (todo_id: {match['todo_id']}, score: {match['score']})\n"
        f"  files: /workspace/gaia-tasks/{folder}/\n"
        f"  {match['snippet'][:200]}"
    )


def parse_action(action: str) -> SubscriptionAction | None:
    try:
        return SubscriptionAction(action.strip().lower())
    except ValueError:
        return None


def parse_match(match: str) -> ConditionMatch | None:
    try:
        return ConditionMatch(match.strip().lower())
    except ValueError:
        return None


def parse_conditions(
    raw: list[dict[str, str | int | float]],
) -> tuple[list[SubscriptionCondition], str | None]:
    """Turn the tool's loose condition dicts into typed conditions.

    Shape errors are caught here and reported with the catalog rather than raising
    a validation traceback the model cannot read.
    """
    parsed: list[SubscriptionCondition] = []
    for item in raw:
        args = ConditionArgs.model_validate(item)
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
