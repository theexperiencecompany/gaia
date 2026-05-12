"""
Tracked-todo LangChain tools for the executor agent.

Allows GAIA's executor to create tracked todos with VFS canvas
and search across canvas context via ChromaDB.
"""

import asyncio
from datetime import datetime, timezone
from typing import Annotated, Optional
from zoneinfo import ZoneInfo

from app.db.mongodb.collections import todos_collection
from app.models.todo_models import Priority
from app.services.tracked_todo_service import tracked_todo_service
from app.services.user_service import get_user_by_id
from app.services.vfs.mongo_vfs import MongoVFS
from app.utils.canvas_vector_utils import search_canvas_context
from bson import ObjectId
from croniter import croniter as _croniter
from langchain_core.runnables import RunnableConfig
from langchain_core.tools import tool
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
            except Exception:
                pass
    except Exception as e:
        log.warning(f"_get_user_tz: lookup failed for {user_id}: {e}")
    log.warning("tracked_todo.user_tz_fallback_utc — no usable IANA tz")
    return "UTC"


def _compute_first_fire_from_cron(cron_expr: str, tz_name: str) -> datetime:
    """Compute the next fire of a cron expression in the given timezone, returned as UTC."""
    tz = ZoneInfo(tz_name)
    now_local = datetime.now(timezone.utc).astimezone(tz)
    cron = _croniter(cron_expr, now_local)
    next_dt: datetime = cron.get_next(datetime)
    if next_dt.tzinfo is None:
        next_dt = next_dt.replace(tzinfo=tz)
    return next_dt.astimezone(timezone.utc)


def _is_cron_expression(recurrence: str) -> bool:
    return recurrence not in _RECURRENCE_SHORTCUTS

_background_tasks: set[asyncio.Task] = set()


def _fire_and_forget(coro) -> None:
    task = asyncio.create_task(coro)
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)


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
        Optional[str],
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
        Optional[str],
        "How often to repeat. Options: 'daily', 'weekly', 'every_4h', 'every_1h', "
        "or a 5-field cron expression. "
        "ALWAYS evaluated in the user's stored timezone — the backend handles "
        "the conversion. Just pass the cron in user-local wall-clock terms. "
        "Example: '0 9,20 * * *' fires at 9 AM and 8 PM in the user's timezone "
        "daily — ONE recurrence, two fires per day; do NOT create two todos. "
        "Do NOT bake timezone offsets into the cron string itself.",
    ] = None,
    expires_at: Annotated[
        Optional[str],
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

    notes: list[str] = []
    parsed_scheduled_at: datetime | None = None

    # Validate recurrence format
    if recurrence:
        if _is_cron_expression(recurrence):
            try:
                _croniter(recurrence)
            except (ValueError, KeyError):
                return (
                    f"Error: invalid recurrence '{recurrence}'. "
                    f"Use one of: {', '.join(sorted(_RECURRENCE_SHORTCUTS))}, "
                    "or a valid 5-field cron expression."
                )
            # Cron: compute first fire from the cron itself in the user's tz.
            # If the agent also passed scheduled_at, ignore it — the cron is
            # the source of truth and passing both is redundant/error-prone.
            if scheduled_at:
                notes.append(
                    "scheduled_at was ignored — for a cron recurrence the first fire "
                    "is computed from the cron in the user's timezone."
                )
            try:
                parsed_scheduled_at = _compute_first_fire_from_cron(
                    recurrence, user_tz_name or "UTC"
                )
            except Exception as e:
                return f"Error: could not compute first fire from cron '{recurrence}': {e}"
        else:
            # Shortcut recurrence — needs a first-fire anchor (scheduled_at).
            if not scheduled_at:
                return (
                    f"Error: recurrence '{recurrence}' is a shortcut and requires "
                    "scheduled_at as the first-fire anchor. Either provide scheduled_at "
                    "or use a cron expression that fully specifies when to fire."
                )
            try:
                parsed_scheduled_at = datetime.fromisoformat(
                    scheduled_at.replace("Z", "+00:00")
                )
            except ValueError:
                return f"Error: invalid scheduled_at format '{scheduled_at}'."
            if parsed_scheduled_at <= datetime.now(timezone.utc):
                return "Error: scheduled_at must be in the future."
    elif scheduled_at:
        # One-shot scheduled execution (no recurrence).
        try:
            parsed_scheduled_at = datetime.fromisoformat(
                scheduled_at.replace("Z", "+00:00")
            )
        except ValueError:
            return f"Error: invalid scheduled_at format '{scheduled_at}'."
        if parsed_scheduled_at <= datetime.now(timezone.utc):
            return "Error: scheduled_at must be in the future."

    result = await tracked_todo_service.create_tracked_todo(
        user_id=user_id,
        title=title,
        description=description,
        initial_canvas=initial_canvas,
        labels=labels,
        priority=Priority(priority),
    )

    # Persist scheduling fields
    if parsed_scheduled_at or recurrence or expires_at:
        update_fields: dict[str, object] = {}
        if parsed_scheduled_at:
            update_fields["scheduled_at"] = parsed_scheduled_at
        if recurrence:
            update_fields["recurrence"] = recurrence
        if expires_at:
            try:
                update_fields["expires_at"] = datetime.fromisoformat(
                    expires_at.replace("Z", "+00:00")
                )
            except ValueError:
                return f"Error: invalid expires_at format '{expires_at}'."
        await todos_collection.update_one(
            {"_id": ObjectId(result.id)},
            {"$set": update_fields},
        )

    # Schedule execution
    if parsed_scheduled_at:
        try:
            success = await tracked_todo_service.schedule_execution(
                result.id, parsed_scheduled_at
            )
            if not success:
                return (
                    f"Tracked todo created (ID: {result.id}) but scheduling failed. "
                    f"The todo exists but will NOT execute automatically."
                )
        except Exception as e:
            log.warning(
                "tracked_todo.schedule_after_create_failed",
                todo_id=result.id,
                error=str(e),
            )
            return (
                f"Tracked todo created (ID: {result.id}) but scheduling failed: {e}. "
                f"The todo exists but will NOT execute automatically."
            )

    out = (
        f"Tracked todo created: {result.id}\n"
        f"Title: {result.title}\n"
        f"VFS: {result.vfs_path}\n"
        f"Canvas: {result.vfs_path}/canvas.md\n"
        f"Log: {result.vfs_path}/log.md"
    )
    if parsed_scheduled_at and user_tz_name:
        try:
            local_fire = parsed_scheduled_at.astimezone(ZoneInfo(user_tz_name))
            out += (
                f"\nNote: scheduled in your timezone ({user_tz_name}). "
                f"First fire: {local_fire.strftime('%a %Y-%m-%d %H:%M %Z')}. "
                "If this isn't what you wanted, call update_tracked_todo with "
                "the corrected recurrence (or scheduled_at for one-shots)."
            )
        except Exception:
            out += f"\nFirst fire (UTC): {parsed_scheduled_at.isoformat()}"
    elif parsed_scheduled_at:
        out += (
            f"\nNote: first fire (UTC): {parsed_scheduled_at.isoformat()}. "
            "If this isn't what you wanted, call update_tracked_todo to correct it."
        )
    if notes:
        out += "\nDetails:\n  - " + "\n  - ".join(notes)
    return out


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
        Optional[str],
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

    doc = await todos_collection.find_one(
        {"_id": ObjectId(todo_id), "user_id": user_id}
    )
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
        heading = f"## {section}"
        heading_pos = current.find(f"\n{heading}")
        if heading_pos == -1:
            # Section does not exist — append it
            new_canvas = current.rstrip() + f"\n\n{heading}\n{content}"
        else:
            # Find where the section body starts and where the next ## heading begins
            body_start = heading_pos + len(f"\n{heading}") + 1
            next_section = current.find("\n## ", body_start)
            if next_section == -1:
                new_canvas = current[: heading_pos + len(f"\n{heading}")] + "\n" + content
            else:
                new_canvas = (
                    current[: heading_pos + len(f"\n{heading}")]
                    + "\n"
                    + content.rstrip()
                    + "\n"
                    + current[next_section:]
                )
        await vfs.write(path=canvas_path, content=new_canvas, user_id=user_id)

    _fire_and_forget(tracked_todo_service.reindex_canvas(todo_id=todo_id, user_id=user_id))
    await tracked_todo_service.system_log(
        todo_id=todo_id,
        user_id=user_id,
        event_type="CANVAS_UPDATED",
        details=f"Agent updated canvas (mode={mode}"
        + (f", section={section}" if section else "")
        + ")",
    )
    return f"Canvas updated (mode={mode}" + (f", section={section}" if section else "") + ")."


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
        Optional[list[str]],
        "New labels to SET on the todo (replaces all existing labels). "
        "Always include 'gaia-tracked' in the list.",
    ] = None,
    due_date: Annotated[
        Optional[str],
        "ISO datetime string for the deadline. Set to empty string '' to clear.",
    ] = None,
    priority: Annotated[
        Optional[str],
        "Priority: 'high', 'medium', 'low', or 'none'.",
    ] = None,
    scheduled_at: Annotated[
        Optional[str],
        "ISO datetime for one-shot scheduled execution, or first-fire anchor for "
        "shortcut recurrences ('daily', 'weekly', 'every_4h', 'every_1h'). "
        "OMIT for cron-style recurrence — first fire is computed from the cron. "
        "Always include the user's timezone offset. Set to empty string '' to clear.",
    ] = None,
    recurrence: Annotated[
        Optional[str],
        "Recurrence pattern: 'daily', 'weekly', 'every_4h', 'every_1h', or 5-field cron. "
        "ALWAYS evaluated in the user's stored timezone. "
        "Example: '0 9,20 * * *' = 9 AM and 8 PM daily in the user's tz. "
        "Set to empty string '' to clear.",
    ] = None,
    expires_at: Annotated[
        Optional[str],
        "ISO datetime when this todo becomes irrelevant. Set to empty string '' to clear. "
        "Different from due_date: due_date = deadline (overdue = still needs doing), "
        "expires_at = relevance window (expired = no longer worth tracking).",
    ] = None,
    references: Annotated[
        Optional[list[str]],
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

    if labels is not None:
        if "gaia-tracked" not in labels:
            labels.append("gaia-tracked")
        update_fields["labels"] = labels

    if due_date is not None:
        if due_date == "":
            update_fields["due_date"] = None
        else:
            try:
                update_fields["due_date"] = datetime.fromisoformat(
                    due_date.replace("Z", "+00:00")
                )
            except ValueError:
                return f"Error: invalid due_date format '{due_date}'."

    if priority is not None:
        update_fields["priority"] = priority

    if scheduled_at is not None:
        if scheduled_at == "":
            update_fields["scheduled_at"] = None
        else:
            try:
                parsed_at = datetime.fromisoformat(scheduled_at.replace("Z", "+00:00"))
            except ValueError:
                return f"Error: invalid scheduled_at format '{scheduled_at}'."
            if parsed_at <= datetime.now(timezone.utc):
                return "Error: scheduled_at must be in the future."
            update_fields["scheduled_at"] = parsed_at

    notes: list[str] = []

    if recurrence is not None:
        if recurrence == "":
            update_fields["recurrence"] = None
        else:
            if _is_cron_expression(recurrence):
                try:
                    _croniter(recurrence)
                except (ValueError, KeyError):
                    return f"Error: invalid recurrence '{recurrence}'."
            elif recurrence not in _RECURRENCE_SHORTCUTS:
                return (
                    f"Error: invalid recurrence '{recurrence}'. "
                    f"Use one of: {', '.join(sorted(_RECURRENCE_SHORTCUTS))}, or a cron expression."
                )
            update_fields["recurrence"] = recurrence
            # For cron: if scheduled_at was also passed, drop it — first fire
            # is computed from the cron in the user's stored timezone.
            if _is_cron_expression(recurrence):
                if scheduled_at:
                    notes.append(
                        "scheduled_at was ignored — for a cron recurrence the first fire "
                        "is computed from the cron in your timezone."
                    )
                try:
                    user_tz_name = await _get_user_tz(user_id)
                    first_fire = _compute_first_fire_from_cron(recurrence, user_tz_name)
                    update_fields["scheduled_at"] = first_fire
                except Exception as e:
                    return f"Error: could not compute first fire from cron: {e}"

    if expires_at is not None:
        if expires_at == "":
            update_fields["expires_at"] = None
        else:
            try:
                update_fields["expires_at"] = datetime.fromisoformat(
                    expires_at.replace("Z", "+00:00")
                )
            except ValueError:
                return f"Error: invalid expires_at format '{expires_at}'."

    if not update_fields:
        return "No fields to update. Provide at least one field to change."

    # Fetch existing doc to validate the resulting state after applying these updates.
    # The in-call guard alone is insufficient — the DB may already have recurrence/scheduled_at
    # set from a previous call, which this call could silently corrupt.
    existing = await todos_collection.find_one(
        {"_id": ObjectId(todo_id), "user_id": user_id, "vfs_path": {"$exists": True}}
    )
    if not existing:
        return f"Error: tracked todo {todo_id} not found or not a tracked todo."

    # Compute the effective post-update values for scheduling fields
    effective_scheduled_at = update_fields.get(
        "scheduled_at", existing.get("scheduled_at")
    )
    effective_recurrence = update_fields.get("recurrence", existing.get("recurrence"))

    if effective_recurrence and not effective_scheduled_at:
        return (
            "Error: cannot have recurrence without scheduled_at. "
            "Either clear recurrence or provide a scheduled_at value."
        )

    update_fields["updated_at"] = datetime.now(timezone.utc)

    result = await todos_collection.update_one(
        {"_id": ObjectId(todo_id), "user_id": user_id},
        {"$set": update_fields},
    )

    if result.matched_count == 0:
        return f"Error: tracked todo {todo_id} not found or not a tracked todo."

    # If scheduled_at landed in update_fields with a real datetime (either the
    # agent passed one, or we computed it from a cron), reschedule the ARQ job.
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

    now = datetime.now(timezone.utc)
    lines: list[str] = []

    for doc in docs:
        todo_id = str(doc["_id"])
        title = doc.get("title", "Untitled")
        labels = [lbl for lbl in doc.get("labels", []) if lbl != "gaia-tracked"]
        labels_str = f" [{', '.join(labels)}]" if labels else ""
        priority = doc.get("priority", "none")
        age_days = (now - doc.get("created_at", now)).days
        last_update = (now - doc.get("updated_at", now)).days

        parts = [f'- "{title}"{labels_str} (ID: {todo_id})']
        parts.append(
            f"  Priority: {priority} | Age: {age_days}d | Last updated: {last_update}d ago"
        )

        detail_parts: list[str] = []
        if doc.get("due_date"):
            days_until = (doc["due_date"] - now).days
            detail_parts.append(
                f"Due: {'OVERDUE ' + str(-days_until) + 'd' if days_until < 0 else str(days_until) + 'd'}"
            )
        if doc.get("scheduled_at"):
            detail_parts.append(f"Scheduled: {doc['scheduled_at'].isoformat()}")
        if doc.get("recurrence"):
            detail_parts.append(f"Recurrence: {doc['recurrence']}")
        if doc.get("expires_at"):
            expires_days = (doc["expires_at"] - now).days
            detail_parts.append(
                f"Expires: {'EXPIRED ' + str(-expires_days) + 'd ago' if expires_days < 0 else 'in ' + str(expires_days) + 'd'}"
            )
        if doc.get("gaia_retry_count", 0) > 0:
            detail_parts.append(f"Retries: {doc['gaia_retry_count']}")

        if detail_parts:
            parts.append(f"  {' | '.join(detail_parts)}")

        parts.append(f"  VFS: {doc.get('vfs_path', 'none')}")
        lines.append("\n".join(parts))

    return f"Active tracked todos ({len(docs)}):\n\n" + "\n\n".join(lines)


tools = [
    create_tracked_todo,
    search_todo_context,
    update_tracked_todo_canvas,
    complete_tracked_todo,
    update_tracked_todo,
    list_tracked_todos,
]
