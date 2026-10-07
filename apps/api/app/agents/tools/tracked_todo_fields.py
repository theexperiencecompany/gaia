"""Field parsing and validation for the tracked-todo tools.

Scheduling math, per-field update builders, and the refusal guard for
sub-todo Standing rules. The @tool entry points in tracked_todo_tools
compose these; nothing here does I/O except the user-timezone lookup.
"""

from datetime import UTC, datetime

from croniter import croniter
from langchain_core.runnables import RunnableConfig

from app.constants.todos import CANVAS_STANDING_RULES_SECTION, GAIA_TRACKED_LABEL
from app.models.agent_models import read_agent_configurable
from app.models.todo_models import Priority, TodoUpdate, UpdateFieldInputs
from app.services.canvas_markdown import section_body
from app.services.user_service import get_user_by_id
from app.utils.cron_utils import get_next_run_time
from app.utils.timezone import Timezone, is_valid_timezone
from shared.py.wide_events import log

RECURRENCE_SHORTCUTS = {"daily", "weekly", "every_4h", "every_1h"}


def gives_sub_todo_rules(
    config: RunnableConfig, parent_todo_id: str | None, initial_canvas: str | None
) -> bool:
    """Whether a background run is opening a sub-todo with Standing rules no user gave."""
    return (
        parent_todo_id is not None
        and read_agent_configurable(config).execution_mode == "background"
        and bool(section_body(initial_canvas, CANVAS_STANDING_RULES_SECTION))
    )


async def get_user_tz(user_id: str) -> str:
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


def compute_first_fire_from_cron(cron_expr: str, tz_name: str) -> datetime:
    """Next fire of a cron in ``tz_name``, returned as UTC.

    Thin wrapper over the canonical ``get_next_run_time`` so todo recurrence and
    reminder/workflow recurrence share one cron-in-timezone implementation.
    """
    return get_next_run_time(cron_expr, tz=Timezone.parse(tz_name))


def is_cron_expression(recurrence: str) -> bool:
    return recurrence not in RECURRENCE_SHORTCUTS


def parse_iso_datetime(iso_str: str, field_name: str) -> tuple[datetime | None, str | None]:
    """Parse an ISO datetime that carries its offset; a naive one would be saved as UTC."""
    try:
        parsed = datetime.fromisoformat(iso_str)
    except ValueError:
        return None, f"Error: invalid {field_name} format '{iso_str}'."
    if parsed.tzinfo is None:
        return None, f"Error: {field_name} '{iso_str}' must include a timezone offset."
    return parsed, None


def parse_iso_future_datetime(iso_str: str, field_name: str) -> tuple[datetime | None, str | None]:
    """Parse an ISO datetime; require it to be in the future. Returns (parsed, error)."""
    parsed, error = parse_iso_datetime(iso_str, field_name)
    if parsed is None:
        return None, error
    if parsed <= datetime.now(UTC):
        return None, f"Error: {field_name} must be in the future."
    return parsed, None


def resolve_cron_first_fire(
    recurrence: str, scheduled_at: str | None, user_tz_name: str | None
) -> tuple[datetime | None, list[str], str | None]:
    """Validate a cron recurrence and compute first fire in the user's timezone."""
    notes: list[str] = []
    try:
        croniter(recurrence)
    except (ValueError, KeyError):
        return (
            None,
            [],
            (
                f"Error: invalid recurrence '{recurrence}'. "
                f"Use one of: {', '.join(sorted(RECURRENCE_SHORTCUTS))}, "
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
        parsed = compute_first_fire_from_cron(recurrence, user_tz_name or "UTC")
    except Exception as e:
        return None, notes, (f"Error: could not compute first fire from cron '{recurrence}': {e}")
    return parsed, notes, None


def resolve_first_fire(
    recurrence: str | None,
    scheduled_at: str | None,
    user_tz_name: str | None,
) -> tuple[datetime | None, list[str], str | None]:
    """Decide the first-fire datetime from recurrence + scheduled_at inputs."""
    if recurrence:
        if is_cron_expression(recurrence):
            return resolve_cron_first_fire(recurrence, scheduled_at, user_tz_name)
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
        parsed, error = parse_iso_future_datetime(scheduled_at, "scheduled_at")
        return parsed, [], error
    if scheduled_at:
        parsed, error = parse_iso_future_datetime(scheduled_at, "scheduled_at")
        return parsed, [], error
    return None, [], None


def creation_field_update(
    parsed_scheduled_at: datetime | None,
    recurrence: str | None,
    due_date: str | None,
    expires_at: str | None,
) -> tuple[TodoUpdate | None, str | None]:
    """Validate the scheduling fields a create saves with its insert, before anything is saved.

    Returns (update, error); update is None when there is nothing to set. An empty
    date means unset here, not the update tool's clear.
    """
    fields: dict[str, object] = {}
    if parsed_scheduled_at:
        fields["scheduled_at"] = parsed_scheduled_at
    if recurrence:
        fields["recurrence"] = recurrence
    for field_name, value in (("due_date", due_date), ("expires_at", expires_at)):
        if error := build_clearable_datetime_update(value or None, field_name, fields):
            return None, error
    return (TodoUpdate.model_validate(fields) if fields else None), None


def format_first_fire_note(parsed_scheduled_at: datetime, user_tz_name: str | None) -> str:
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


def build_labels_update(labels: list[str] | None, update_fields: dict[str, object]) -> str | None:
    """Apply a labels update, ensuring GAIA_TRACKED_LABEL is present."""
    if labels is None:
        return None
    if GAIA_TRACKED_LABEL not in labels:
        labels = [*labels, GAIA_TRACKED_LABEL]
    update_fields["labels"] = labels
    return None


def build_clearable_datetime_update(
    value: str | None, field_name: str, update_fields: dict[str, object]
) -> str | None:
    """Set, clear (""), or skip (None) a datetime field; returns user-facing error on bad format."""
    if value is None:
        return None
    if value == "":
        update_fields[field_name] = None
        return None
    parsed, error = parse_iso_datetime(value, field_name)
    if parsed is None:
        return error
    update_fields[field_name] = parsed
    return None


def build_priority_update(
    priority: Priority | None, update_fields: dict[str, object]
) -> str | None:
    """Apply a priority update."""
    if priority is not None:
        update_fields["priority"] = priority.value
    return None


def build_scheduled_at_update(
    scheduled_at: str | None, update_fields: dict[str, object]
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


def validate_recurrence_format(recurrence: str) -> str | None:
    """Return a user-facing error if `recurrence` is neither a valid cron nor a known shortcut.

    is_cron_expression is defined as "not a known shortcut", so the two cases
    are exhaustive: anything that isn't a shortcut is validated as a cron
    expression here — there is no separate "unknown shortcut-like string"
    branch to fall through to.
    """
    if not is_cron_expression(recurrence):
        return None
    try:
        croniter(recurrence)
    except (ValueError, KeyError):
        return (
            f"Error: invalid recurrence '{recurrence}'. "
            f"Use one of: {', '.join(sorted(RECURRENCE_SHORTCUTS))}, "
            "or a valid 5-field cron expression."
        )
    return None


async def apply_cron_first_fire(
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
        user_tz_name = await get_user_tz(user_id)
        update_fields["scheduled_at"] = compute_first_fire_from_cron(recurrence, user_tz_name)
    except Exception as e:
        return f"Error: could not compute first fire from cron: {e}"
    return None


async def build_recurrence_update(
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
    format_error = validate_recurrence_format(recurrence)
    if format_error:
        return format_error
    update_fields["recurrence"] = recurrence
    if is_cron_expression(recurrence):
        return await apply_cron_first_fire(recurrence, scheduled_at, user_id, update_fields, notes)
    return None


async def apply_field_updates(
    inputs: UpdateFieldInputs,
    user_id: str,
    update_fields: dict[str, object],
    notes: list[str],
) -> str | None:
    """Run each field validator in order, short-circuiting on the first error so the
    async get_user_tz Mongo lookup in the recurrence validator never runs after an
    earlier field already failed. Populates update_fields/notes in place.

    build_labels_update can never actually return an error today (there is no label
    validation yet); the check is kept for the same shape as the others so adding one
    later needs no restructuring.
    """
    if error := build_labels_update(inputs.labels, update_fields):  # pragma: no cover
        return error
    if error := build_clearable_datetime_update(inputs.due_date, "due_date", update_fields):
        return error
    if error := build_priority_update(inputs.priority, update_fields):
        return error
    if error := build_scheduled_at_update(inputs.scheduled_at, update_fields):
        return error
    if error := await build_recurrence_update(
        inputs.recurrence, inputs.scheduled_at, user_id, update_fields, notes
    ):
        return error
    if error := build_clearable_datetime_update(inputs.expires_at, "expires_at", update_fields):
        return error
    return None
