"""
Tracked-todo LangChain tools for the executor agent.

Allows GAIA's executor to create tracked todos with VFS canvas
and search across canvas context via ChromaDB.
"""

import asyncio
from datetime import UTC, datetime
from typing import Annotated
from zoneinfo import ZoneInfo

from bson import ObjectId
from croniter import croniter as _croniter
from langchain_core.runnables import RunnableConfig
from langchain_core.tools import tool

from app.db.mongodb.collections import todos_collection
from app.models.todo_models import Priority, TodoResponse
from app.services.tracked_todo_service import GAIA_TRACKED_LABEL, tracked_todo_service
from app.services.user_service import get_user_by_id
from app.services.vfs.mongo_vfs import MongoVFS
from app.utils.canvas_vector_utils import search_canvas_context
from shared.py.wide_events import log

_RECURRENCE_SHORTCUTS = {"daily", "weekly", "every_4h", "every_1h"}


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
            try:
                ZoneInfo(tz_name)
                return tz_name
            except Exception as tz_err:
                log.warning(
                    "tracked_todo.user_tz_invalid",
                    user_id=user_id,
                    tz_name=tz_name,
                    error=str(tz_err),
                )
    except Exception as e:
        log.warning("tracked_todo.user_tz_lookup_failed", user_id=user_id, error=str(e))
    log.warning("tracked_todo.user_tz_fallback_utc", user_id=user_id)
    return "UTC"


def _compute_first_fire_from_cron(cron_expr: str, tz_name: str) -> datetime:
    """Compute the next fire of a cron expression in the given timezone, returned as UTC."""
    tz = ZoneInfo(tz_name)
    now_local = datetime.now(UTC).astimezone(tz)
    cron = _croniter(cron_expr, now_local)
    next_dt: datetime = cron.get_next(datetime)
    if next_dt.tzinfo is None:
        next_dt = next_dt.replace(tzinfo=tz)
    return next_dt.astimezone(UTC)


def _is_cron_expression(recurrence: str) -> bool:
    return recurrence not in _RECURRENCE_SHORTCUTS


_background_tasks: set[asyncio.Task] = set()


def _fire_and_forget(coro) -> None:
    task = asyncio.create_task(coro)
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)


def _parse_iso_future_datetime(iso_str: str, field_name: str) -> tuple[datetime | None, str | None]:
    """Parse an ISO datetime; require it to be in the future. Returns (parsed, error)."""
    try:
        parsed = datetime.fromisoformat(iso_str.replace("Z", "+00:00"))
    except ValueError:
        return None, f"Error: invalid {field_name} format '{iso_str}'."
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
            "scheduled_at was ignored — for a cron recurrence the first fire "
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
    parsed_scheduled_at: datetime | None,
    recurrence: str | None,
    expires_at: str | None,
) -> str | None:
    """Save scheduled_at / recurrence / expires_at onto a freshly-created todo doc."""
    if not (parsed_scheduled_at or recurrence or expires_at):
        return None
    update_fields: dict[str, object] = {}
    if parsed_scheduled_at:
        update_fields["scheduled_at"] = parsed_scheduled_at
    if recurrence:
        update_fields["recurrence"] = recurrence
    if expires_at:
        try:
            update_fields["expires_at"] = datetime.fromisoformat(expires_at.replace("Z", "+00:00"))
        except ValueError:
            return f"Error: invalid expires_at format '{expires_at}'."
    await todos_collection.update_one(
        {"_id": ObjectId(todo_id)},
        {"$set": update_fields},
    )
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
            local_fire = parsed_scheduled_at.astimezone(ZoneInfo(user_tz_name))
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
        update_fields[field_name] = datetime.fromisoformat(value.replace("Z", "+00:00"))
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
        parsed_at = datetime.fromisoformat(scheduled_at.replace("Z", "+00:00"))
    except ValueError:
        return f"Error: invalid scheduled_at format '{scheduled_at}'."
    if parsed_at <= datetime.now(UTC):
        return "Error: scheduled_at must be in the future."
    update_fields["scheduled_at"] = parsed_at
    return None


def _validate_recurrence_format(recurrence: str) -> str | None:
    """Return a user-facing error if `recurrence` is neither a valid cron nor a known shortcut."""
    if _is_cron_expression(recurrence):
        try:
            _croniter(recurrence)
        except (ValueError, KeyError):
            return f"Error: invalid recurrence '{recurrence}'."
        return None
    if recurrence not in _RECURRENCE_SHORTCUTS:
        return (
            f"Error: invalid recurrence '{recurrence}'. "
            f"Use one of: {', '.join(sorted(_RECURRENCE_SHORTCUTS))}, or a cron expression."
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
            "scheduled_at was ignored — for a cron recurrence the first fire "
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


def _build_list_detail_parts(doc: dict, now: datetime) -> list[str]:
    """Build the pipe-separated detail fragments shown on the second line of each todo."""
    parts: list[str] = []
    if due_date := doc.get("due_date"):
        days_until = (due_date - now).days
        parts.append(f"Due: OVERDUE {-days_until}d" if days_until < 0 else f"Due: {days_until}d")
    if scheduled := doc.get("scheduled_at"):
        parts.append(f"Scheduled: {scheduled.isoformat()}")
    if recurrence := doc.get("recurrence"):
        parts.append(f"Recurrence: {recurrence}")
    if expires := doc.get("expires_at"):
        expires_days = (expires - now).days
        parts.append(
            f"Expires: EXPIRED {-expires_days}d ago"
            if expires_days < 0
            else f"Expires: in {expires_days}d"
        )
    if doc.get("gaia_retry_count", 0) > 0:
        parts.append(f"Retries: {doc['gaia_retry_count']}")
    return parts


def _format_tracked_todo_full(doc: dict, now: datetime) -> str:
    """Format one tracked-todo doc as the multi-line block used by list_tracked_todos."""
    todo_id = str(doc["_id"])
    title = doc.get("title", "Untitled")
    labels = [lbl for lbl in doc.get("labels", []) if lbl != "gaia-tracked"]
    labels_str = f" [{', '.join(labels)}]" if labels else ""
    priority = doc.get("priority", "none")
    age_days = (now - doc.get("created_at", now)).days
    last_update = (now - doc.get("updated_at", now)).days

    parts = [
        f'- "{title}"{labels_str} (ID: {todo_id})',
        f"  Priority: {priority} | Age: {age_days}d | Last updated: {last_update}d ago",
    ]
    detail_parts = _build_list_detail_parts(doc, now)
    if detail_parts:
        parts.append(f"  {' | '.join(detail_parts)}")
    parts.append(f"  VFS: {doc.get('vfs_path', 'none')}")
    return "\n".join(parts)


def _patch_canvas_section(current: str, section: str, content: str) -> str:
    """Replace (or append) a `## {section}` block within a canvas markdown string."""
    heading = f"## {section}"
    heading_pos = current.find(f"\n{heading}")
    if heading_pos == -1:
        # Section does not exist — append it as a fresh trailing block.
        return current.rstrip() + f"\n\n{heading}\n{content}"
    head_end = heading_pos + len(f"\n{heading}")
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
        f"VFS: {result.vfs_path}\n"
        f"Canvas: {result.vfs_path}/canvas.md\n"
        f"Log: {result.vfs_path}/log.md"
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
        "For cron-style recurrence (e.g. '0 9 * * *' or '0 9,20 * * *'), OMIT this — "
        "the first fire is computed automatically in the user's timezone. "
        "Always include the user's timezone offset (e.g., '2026-03-20T09:00:00+05:30'); "
        "never 'Z' unless the user explicitly says UTC.",
    ] = None,
    recurrence: Annotated[
        str | None,
        "How often to repeat. Options: 'daily', 'weekly', 'every_4h', 'every_1h', "
        "or a 5-field cron expression. "
        "ALWAYS evaluated in the user's stored timezone — the backend handles "
        "the conversion. Just pass the cron in user-local wall-clock terms. "
        "Example: '0 9,20 * * *' fires at 9 AM and 8 PM in the user's timezone "
        "daily — ONE recurrence, two fires per day; do NOT create two todos. "
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
    Create a tracked todo with VFS canvas for persistent working memory.

    These are GAIA's internal memory for long-term goals, projects, and multi-conversation
    initiatives — NOT the user's personal action-item todos (those live in providers like
    Todoist, Google Tasks, Apple Reminders, Gaia Todos, etc.).

    Use when work will span multiple conversations, expects external
    responses, or needs future follow-up. The todo gets a VFS directory
    with canvas.md (your brain) and log.md (system audit trail).

    Do NOT use for one-shot actions with no expected follow-up.

    IMPORTANT: Before creating a tracked todo with scheduling (scheduled_at, recurrence),
    read the "tracked-todo-working-memory" skill first for scheduling best practices,
    canvas template guidelines, and lifecycle rules.

    scheduled_at: ISO datetime with the user's timezone offset (e.g., "2026-03-20T09:00:00+05:30").
                  Always use the user's timezone offset from config, never raw 'Z' unless user says UTC.
    recurrence: How often to repeat. Options: 'daily', 'weekly', 'every_4h', or a cron expression.
                Requires scheduled_at to also be set.
    expires_at: ISO datetime string when this todo becomes irrelevant regardless of completion.
                Different from due_date: due_date = deadline (overdue = still needs doing),
                expires_at = relevance window (expired = no longer worth tracking).
    """
    user_id = config.get("metadata", {}).get("user_id")
    if not user_id:
        return "Error: user_id not found in config"

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
        result.id, parsed_scheduled_at, recurrence, expires_at
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
        return "Error: user_id not found in config"

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
        "'append' (default) — add content at the end of the canvas. Use for activity log entries, timeline events, new notes. No read needed. "
        "'section' — replace a specific ## Section by name. Use for targeted updates (e.g. Current State). Tool reads and patches internally — no read needed. "
        "'replace' — overwrite the entire canvas. Only use for initial setup or full restructure.",
    ] = "append",
    section: Annotated[
        str | None,
        "Section heading to replace when mode='section'. "
        "Exact heading text without ## (e.g. 'Current State', 'Key Details', 'Learnings'). "
        "If the section does not exist, it is appended as a new section.",
    ] = None,
) -> str:
    """Update canvas.md for a tracked todo.

    Three modes — pick the right one to avoid unnecessary reads:

    append  → Add activity log entries, timeline events, new context. No read needed.
    section → Update a single named section (e.g. Current State). Tool patches internally. No read needed.
    replace → Full rewrite. Only use when restructuring the entire canvas.
    """
    user_id = config.get("metadata", {}).get("user_id")
    if not user_id:
        return "Error: user_id not found in config"

    if mode not in ("replace", "append", "section"):
        return f"Error: invalid mode '{mode}'. Use 'replace', 'append', or 'section'."

    if mode == "section" and not section:
        return "Error: 'section' mode requires a section name."

    vfs = MongoVFS()

    doc = await todos_collection.find_one({"_id": ObjectId(todo_id), "user_id": user_id})
    if not doc:
        return f"Error: tracked todo {todo_id} not found"
    vfs_path = doc.get("vfs_path")
    if not vfs_path:
        return f"Error: todo {todo_id} has no vfs_path"

    canvas_path = f"{vfs_path}/canvas.md"

    if mode == "replace":
        await vfs.write(path=canvas_path, content=content, user_id=user_id)
    elif mode == "append":
        suffix = content if content.startswith("\n") else f"\n{content}"
        await vfs.append(path=canvas_path, content=suffix, user_id=user_id)
    else:  # section
        current = await vfs.read(path=canvas_path, user_id=user_id) or ""
        new_canvas = _patch_canvas_section(current, section or "", content)
        await vfs.write(path=canvas_path, content=new_canvas, user_id=user_id)

    _fire_and_forget(tracked_todo_service.reindex_canvas(todo_id=todo_id, user_id=user_id))
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
        return "Error: user_id not found in config"

    success = await tracked_todo_service.complete_tracked_todo(
        todo_id=todo_id, user_id=user_id, summary=summary
    )
    if not success:
        return f"Error: could not complete tracked todo {todo_id} — not found or missing vfs_path"
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
        "OMIT for cron-style recurrence — first fire is computed from the cron. "
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
        return "Error: user_id not found in config"

    update_fields: dict[str, object] = {}
    notes: list[str] = []

    # Validate each field sequentially with short-circuit so we don't keep doing
    # work (in particular the async _get_user_tz Mongo lookup inside the
    # recurrence validator) after an earlier field has already failed.
    if error := _build_labels_update(labels, update_fields):
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
    existing = await todos_collection.find_one(
        {"_id": ObjectId(todo_id), "user_id": user_id, "vfs_path": {"$exists": True}}
    )
    if not existing:
        return f"Error: tracked todo {todo_id} not found or not a tracked todo."

    effective_scheduled_at = update_fields.get("scheduled_at", existing.get("scheduled_at"))
    effective_recurrence = update_fields.get("recurrence", existing.get("recurrence"))
    if effective_recurrence and not effective_scheduled_at:
        return (
            "Error: cannot have recurrence without scheduled_at. "
            "Either clear recurrence or provide a scheduled_at value."
        )

    update_fields["updated_at"] = datetime.now(UTC)
    result = await todos_collection.update_one(
        {"_id": ObjectId(todo_id), "user_id": user_id},
        {"$set": update_fields},
    )
    if result.matched_count == 0:
        return f"Error: tracked todo {todo_id} not found or not a tracked todo."

    # If scheduled_at landed in update_fields with a real datetime (agent-passed or
    # cron-derived), reschedule the ARQ job.
    new_scheduled_at = update_fields.get("scheduled_at")
    if isinstance(new_scheduled_at, datetime):
        await tracked_todo_service.reschedule_execution(todo_id, new_scheduled_at)

    updated_keys = [k for k in update_fields if k != "updated_at"]
    if references is not None:
        await todos_collection.update_one(
            {"_id": ObjectId(todo_id), "user_id": user_id},
            {"$addToSet": {"references": {"$each": references}}},
        )
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
        return "Error: user_id not found in config"

    cursor = (
        todos_collection.find(
            {
                "user_id": user_id,
                "labels": "gaia-tracked",
                "completed": False,
            }
        )
        .sort("updated_at", -1)
        .limit(50)
    )

    docs = await cursor.to_list(length=50)
    if not docs:
        return "No active tracked todos."

    now = datetime.now(UTC)
    lines = [_format_tracked_todo_full(doc, now) for doc in docs]
    return f"Active tracked todos ({len(docs)}):\n\n" + "\n\n".join(lines)


tools = [
    create_tracked_todo,
    search_todo_context,
    update_tracked_todo_canvas,
    complete_tracked_todo,
    update_tracked_todo,
    list_tracked_todos,
]
