"""
Tracked-todo LangChain tools for the executor agent.

Lifecycle and metadata only. The working notes (canvas.md / activity.md) are
files under /workspace/gaia-tasks/ that the agent reads and edits with the
ordinary file tools; see ``app.services.gaia_task_files``.
"""

from datetime import UTC, datetime
from typing import Annotated

from langchain_core.runnables import RunnableConfig
from langchain_core.tools import tool

from app.agents.tools.tracked_todo_fields import (
    apply_field_updates,
    creation_field_update,
    get_user_tz,
    gives_sub_todo_rules,
    resolve_first_fire,
)
from app.agents.tools.tracked_todo_formatting import (
    format_canvas_match,
    format_create_output,
    format_refused_create_output,
    format_tracked_todo_full,
    parse_action,
    parse_conditions,
    parse_match,
    render_catalog,
)
from app.constants.todos import (
    GAIA_TRACKED_LABEL,
    LIST_TRACKED_TODOS_LIMIT,
)
from app.db.repositories.todos import todo_repository
from app.models.agent_models import read_agent_configurable
from app.models.integrations.composio_hooks import RunMetadata
from app.models.todo_models import (
    ExternalRef,
    ExternalRefSource,
    Priority,
    TodoDocument,
    TodoUpdate,
    UpdateFieldInputs,
)
from app.models.trigger_subscription_models import (
    ConditionMatch,
    SubscriptionAction,
)
from app.services.todo_activity import agent_actor, record_field_changes
from app.services.todos.errors import (
    CanvasShapeError,
    ExternalRefTakenError,
    SubTodoParentError,
    UnwatchedTodoKeptError,
)
from app.services.tracked_todo_service import require_sub_todo_parent, tracked_todo_service
from app.services.triggers.subscription_service import (
    DEFAULT_COOLDOWN_SECONDS,
    SubscriptionError,
    register_subscription,
    unregister_subscription,
)
from app.services.triggers.subscription_validation import validate_scope
from app.utils.canvas_vector_utils import search_canvas_context
from shared.py.analytics.catalog.properties import Identifier
from shared.py.wide_events import log

_NOTIFY_ON_RUN_DESC = (
    "Whether a scheduled or triggered run may message the user's chat app when it "
    "finds something that matters (routine runs never do). Default True, except for "
    "a sub-todo, which reports to its parent's runs instead. The user's setting: set "
    "it only when they ask to stop or resume hearing about this todo; a silent run "
    "can still reach them with send_notification when something genuinely needs them."
)
_PARENT_TODO_DESC = (
    "ID of the user's open tracked todo that owns this one as a sub-todo, when this is "
    "one piece of a larger tracked job (a thread todo the inbox desk opens). The "
    "sub-todo obeys its parent's Standing rules, reports to the parent's runs instead "
    "of messaging the user, and is completed or deleted with its parent. One level "
    "deep: a sub-todo cannot have sub-todos."
)
_ERR_NO_USER_ID = "Error: user_id not found in config"
# Nobody gave a background run's sub-todo rules, and its parent's Standing rules already bind it.
SUB_TODO_STANDING_RULES_REFUSAL = (
    "Not created: a sub-todo opened by a background run starts with an empty Standing rules "
    "section. Standing rules hold only the user's own instructions, and its parent's already "
    "bind it; put what you noticed under Context and call again. Nothing was saved."
)


async def _schedule_execution_after_create(
    todo_id: str, parsed_scheduled_at: datetime
) -> str | None:
    """Hand the new todo to the scheduler; translate any failure into user-facing text."""
    try:
        await tracked_todo_service.schedule_execution(todo_id, parsed_scheduled_at)
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
    return None


def _gmail_thread_ref(gmail_thread_id: str | None) -> ExternalRef | None:
    if not gmail_thread_id:
        return None
    return ExternalRef(source=ExternalRefSource.GMAIL_THREAD, id=gmail_thread_id)


async def _references_refusal(
    user_id: str, references: list[str], todo_id: str | None = None
) -> str | None:
    """Refuse reference ids that name none of the user's other tracked todos; None when all do.

    A run reads its references' Learnings, so a foreign, untracked or mistyped id must not link.
    """
    valid = [ref for ref in references if todo_repository.is_valid_id(ref)]
    docs = await todo_repository.find_by_ids(user_id, valid)
    tracked = {doc.id for doc in docs if GAIA_TRACKED_LABEL in doc.labels and doc.id != todo_id}
    unknown = [ref for ref in references if ref not in tracked]
    if not unknown:
        return None
    return (
        f"Error: no other tracked todo of this user has the id {', '.join(unknown)}. "
        "Nothing was saved; pass ids from list_tracked_todos or search_todo_context."
    )


async def _link_refusal(
    user_id: str, todo_id: str, references: list[str] | None, parent_todo_id: str | None
) -> str | None:
    """Refuse links the update may not make; None when every link is allowed."""
    if references and (refusal := await _references_refusal(user_id, references, todo_id)):
        return refusal
    if parent_todo_id:
        try:
            await require_sub_todo_parent(user_id, parent_todo_id, child_id=todo_id)
        except SubTodoParentError as refused:
            return f"Error: {refused.message} Nothing was saved."
    return None


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
    due_date: Annotated[
        str | None,
        "ISO datetime deadline: when this should be done by. Include the user's timezone "
        "offset. May be in the past: an overdue todo still needs doing.",
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
        bool | None,
        _NOTIFY_ON_RUN_DESC,
    ] = None,
    gmail_thread_id: Annotated[
        str | None,
        "When the todo is about an email thread, pass its Gmail thread id. The todo "
        "then watches the thread for new mail and for the user's own replies, and "
        "the thread can have only one open todo: if it already has one, that todo "
        "comes back instead, for you to update.",
    ] = None,
    references: Annotated[
        list[str] | None,
        "IDs of the user's other tracked todos this one builds on, usually completed "
        "ones found with search_todo_context. Every run of this todo reads their Learnings.",
    ] = None,
    parent_todo_id: Annotated[str | None, _PARENT_TODO_DESC] = None,
) -> str:
    """
    Create a tracked todo: a GAIA-managed todo with a working-memory canvas.

    A tracked todo shows on the user's todos page like a normal todo, but GAIA
    owns it: it carries canvas.md (GAIA's recall doc: the user's standing rules,
    key IDs, current state, context, learnings) and activity.md (dated log of what happened) plus an
    optional schedule/recurrence so GAIA can act on it over time. It is distinct from the user's own hand-created action items
    (which live in providers like Todoist, Google Tasks, Apple Reminders, Gaia
    Todos).

    Create one ONLY when GAIA itself performs or schedules a real action on an
    external system that it needs to remember, follow up on, or repeat: sent an
    email and awaits a reply, created an issue, posted to Slack, scheduled
    recurring work, or an ongoing multi-step initiative.

    Judge the work by what it does, not by what it reports. Do NOT create one for
    work that only reads (fetching, listing, searching, or summarizing data), no
    matter how complex it is or how often it runs; saving or persisting a summary,
    digest, or briefing is NOT tracking: return the summary instead. Recurring work
    that also writes on the user's behalf does qualify even when its final message
    is a summary (an inbox desk that opens a todo per email thread and saves reply
    drafts, then briefs the user). Search existing tracked todos first
    (search_todo_context) and update a match instead of creating a duplicate.

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
    due_date: ISO datetime deadline, validated like update_tracked_todo's due_date.
    expires_at: ISO datetime string when this todo becomes irrelevant regardless of completion.
                Different from due_date: due_date = deadline (overdue = still needs doing),
                expires_at = relevance window (expired = no longer worth tracking).
    notify_on_run: Whether each run's final message is delivered to the user's chat app.
                On by default, off by default for a sub-todo.
    gmail_thread_id: The Gmail thread id when the todo is about an email thread; it is
                watched both ways and allowed one open todo. If the thread already has
                one, nothing is created and that todo comes back: update it instead.
    references: IDs of the user's tracked todos this one builds on; its runs read their
                Learnings. An id that is not one of the user's todos creates nothing.
    parent_todo_id: The open tracked todo this one is a sub-todo of; a parent that is not
                usable creates nothing and says why.
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
    user_tz_name = await get_user_tz(user_id) if recurrence else None

    parsed_scheduled_at, notes, error = resolve_first_fire(recurrence, scheduled_at, user_tz_name)
    if error:
        return error
    creation_update, error = creation_field_update(
        parsed_scheduled_at, recurrence, due_date, expires_at
    )
    if error:
        return error

    if references and (refusal := await _references_refusal(user_id, references)):
        return refusal
    if gives_sub_todo_rules(config, parent_todo_id, initial_canvas):
        return SUB_TODO_STANDING_RULES_REFUSAL

    external_ref = _gmail_thread_ref(gmail_thread_id)
    try:
        result = await tracked_todo_service.create_tracked_todo(
            user_id=user_id,
            title=title,
            description=description,
            initial_canvas=initial_canvas,
            labels=labels,
            priority=priority,
            source_conversation_id=source_conversation_id,
            notify_on_run=notify_on_run,
            external_ref=external_ref,
            references=references,
            parent_todo_id=parent_todo_id,
            schedule=creation_update,
        )
    except (
        ExternalRefTakenError,
        SubTodoParentError,
        CanvasShapeError,
        SubscriptionError,
        UnwatchedTodoKeptError,
    ) as refused:
        return format_refused_create_output(refused)

    if parsed_scheduled_at:
        schedule_error = await _schedule_execution_after_create(result.id, parsed_scheduled_at)
        if schedule_error:
            return schedule_error

    return format_create_output(result, parsed_scheduled_at, user_tz_name, notes)


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

    return "\n".join(format_canvas_match(match) for match in matches)


@tool
async def complete_tracked_todo(
    config: RunnableConfig,
    todo_id: Annotated[str, "ID of the tracked todo to complete"],
    summary: Annotated[str, "One or two sentences describing what was achieved"],
) -> str:
    """Complete a tracked todo: mark done and flag its canvas as completed in search.

    Call on your own as soon as the goal is clearly resolved: the fix is live
    and verified, the PR is merged, the external system shows done, the watched
    event arrived and is handled, or the user confirmed it. Do not wait for the
    user to report it or ask for closure. Use the regular todo update for
    partial completion or status changes only. Never repeat the todo ID in
    user-visible text.

    Refuses a todo with an active recurrence: one finished run never ends a
    standing schedule. To stop one entirely, clear its recurrence (and
    scheduled_at) with update_tracked_todo first, then complete it.
    """
    user_id = RunMetadata.model_validate(config.get("metadata", {})).user_id
    if not user_id:
        return _ERR_NO_USER_ID

    doc = await todo_repository.get(todo_id, user_id=user_id)
    if doc is None:
        return f"Error: could not complete tracked todo {todo_id}, not found or missing vfs_path"
    if doc.recurrence:
        return (
            f"Error: tracked todo {todo_id} still has an active recurrence "
            f"({doc.recurrence}). One finished run never ends a standing schedule: "
            "leave it open, or if the user asked to stop it entirely, clear its "
            "recurrence (and scheduled_at) with update_tracked_todo first, "
            "then complete it."
        )

    success = await tracked_todo_service.complete_tracked_todo(
        todo_id=todo_id, user_id=user_id, summary=summary
    )
    if not success:
        return f"Error: could not complete tracked todo {todo_id}, not found or missing vfs_path"
    return f"Tracked todo {todo_id} completed and archived."


async def _rollback_stale_move(user_id: str, todo_id: str, parent_todo_id: str) -> str | None:
    """Re-check a move after its write; roll back when the parent closed meanwhile."""
    try:
        await require_sub_todo_parent(user_id, parent_todo_id)
    except SubTodoParentError:
        await todo_repository.update(
            todo_id, user_id=user_id, update=TodoUpdate(parent_todo_id=None)
        )
        return (
            f"Error: the parent no longer accepts sub-todos, "
            f"so moving todo {todo_id} under it was rolled back. "
            "Reopen the parent first, or pick an open one."
        )
    return None


async def _save_field_update(existing: TodoDocument, update: TodoUpdate, actor: str) -> str | None:
    """Persist a field update and move the scheduled run; an error string when refused."""
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
    if await todo_repository.update(existing.id, user_id=existing.user_id, update=update) is None:
        return f"Error: tracked todo {existing.id} not found or not a tracked todo."
    # A real datetime here (agent-passed or cron-derived) means the ARQ job moves.
    if update.scheduled_at is not None:
        await tracked_todo_service.schedule_execution(existing.id, update.scheduled_at)
    await record_field_changes(existing.id, existing.user_id, update, by=actor)
    # The link check and this write are two separate writes: when the parent
    # closed in between, the move is rolled back rather than completing the
    # user's open todo out from under them.
    if update.parent_todo_id is not None:
        return await _rollback_stale_move(existing.user_id, existing.id, update.parent_todo_id)
    return None


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
        "ISO datetime string for the deadline, with the user's timezone offset. "
        "Set to empty string '' to clear.",
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
        "ISO datetime when this todo becomes irrelevant, with the user's timezone offset. "
        "Set to empty string '' to clear. "
        "Different from due_date: due_date = deadline (overdue = still needs doing), "
        "expires_at = relevance window (expired = no longer worth tracking).",
    ] = None,
    references: Annotated[
        list[str] | None,
        "IDs of the user's other tracked todos to link; appended to existing references. "
        "Every run of this todo reads their Learnings.",
    ] = None,
    notify_on_run: Annotated[
        bool | None,
        _NOTIFY_ON_RUN_DESC,
    ] = None,
    parent_todo_id: Annotated[
        str | None, "Move this todo under that parent as its sub-todo. " + _PARENT_TODO_DESC
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
        references: IDs of the user's tracked todos to link (appended to existing).
        notify_on_run: Turn this todo's run-result delivery on or off.
        parent_todo_id: Make this todo a sub-todo of that parent.
    """
    user_id = RunMetadata.model_validate(config.get("metadata", {})).user_id
    if not user_id:
        return _ERR_NO_USER_ID

    update_fields: dict[str, object] = {}
    notes: list[str] = []
    inputs = UpdateFieldInputs(
        labels=labels,
        due_date=due_date,
        priority=priority,
        scheduled_at=scheduled_at,
        recurrence=recurrence,
        expires_at=expires_at,
    )
    if error := await apply_field_updates(inputs, user_id, update_fields, notes):
        return error
    # Moved under a parent, a todo reports to it like a new sub-todo unless told otherwise.
    moved_default = False if parent_todo_id else None
    plain_fields = {
        "notify_on_run": moved_default if notify_on_run is None else notify_on_run,
        "parent_todo_id": parent_todo_id or None,
    }
    update_fields.update({name: value for name, value in plain_fields.items() if value is not None})

    if not update_fields and not references:
        return "No fields to update. Provide at least one field to change."

    # Validate the resulting state against the existing doc — the in-call guards
    # alone can't catch corruption when the DB already has scheduling fields set.
    existing = await todo_repository.get(todo_id, user_id=user_id)
    if not existing:
        return f"Error: tracked todo {todo_id} not found or not a tracked todo."
    if refusal := await _link_refusal(user_id, todo_id, references, parent_todo_id):
        return refusal

    if update_fields:
        actor = agent_actor(read_agent_configurable(config).conversation_id)
        update = TodoUpdate.model_validate(update_fields)
        if error := await _save_field_update(existing, update, actor):
            return error
    updated_keys = list(update_fields)
    if references:
        if (
            await todo_repository.add_references(todo_id, user_id=user_id, references=references)
            is None
        ):
            return f"Error: tracked todo {todo_id} was gone before its references were saved."
        updated_keys.append("references")

    msg = f"Updated tracked todo {todo_id}: {', '.join(updated_keys)}"
    if notes:
        msg += "\nNotes:\n  - " + "\n  - ".join(notes)
    return msg


@tool
async def list_tracked_todos(
    config: RunnableConfig,
    labels: Annotated[
        list[str] | None,
        "Only todos carrying every one of these labels, e.g. ['needs-reply'].",
    ] = None,
    gmail_thread_id: Annotated[
        str | None,
        "Only the open todo that owns this Gmail thread, if there is one.",
    ] = None,
    parent_todo_id: Annotated[
        str | None,
        "Only the open sub-todos of this tracked todo.",
    ] = None,
) -> str:
    """List active tracked todos with full metadata, optionally filtered.

    Returns open tracked todos, most recently updated first, with their
    ID, title, labels, due_date, scheduled_at, recurrence, expires_at, priority,
    age, watches, the email thread a thread todo owns, and a sub-todo's parent. Use
    this when you need a complete picture of tracked work, beyond the ACTIVE TRACKED
    TODOS context block (which folds sub-todos into a count), or to read the todos in
    one state by label (e.g. every thread waiting on a reply), the todo for one
    thread, or the sub-todos of one todo.
    """
    user_id = RunMetadata.model_validate(config.get("metadata", {})).user_id
    if not user_id:
        return _ERR_NO_USER_ID

    docs = await todo_repository.list_active_tracked(
        user_id,
        limit=LIST_TRACKED_TODOS_LIMIT,
        labels=labels,
        external_ref=_gmail_thread_ref(gmail_thread_id),
        parent_todo_id=parent_todo_id,
    )
    if not docs:
        if labels or gmail_thread_id or parent_todo_id:
            return "No active tracked todos match those filters."
        return "No active tracked todos."

    now = datetime.now(UTC)
    lines = [format_tracked_todo_full(doc, now) for doc in docs]
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
    return render_catalog(trigger_name)


@tool
async def subscribe_todo_to_trigger(
    config: RunnableConfig,
    todo_id: Annotated[str, "ID of the tracked todo that should watch for this event"],
    # Identifier-typed: a slug analytics cannot carry fails the args schema before registering.
    trigger_name: Annotated[Identifier, "GAIA trigger slug to watch, e.g. 'gmail_new_message'"],
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
        # parse_match lowercases before ConditionMatch(), so the default's CASE
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

    parsed_action = parse_action(action)
    if parsed_action is None:
        valid = ", ".join(a.value for a in SubscriptionAction)
        return f"Error: '{action}' is not a valid action. Valid actions: {valid}."

    parsed_match = parse_match(match)
    if parsed_match is None:
        valid = ", ".join(m.value for m in ConditionMatch)
        return f"Error: '{match}' is not a valid match mode. Valid modes: {valid}."

    parsed_conditions, condition_error = parse_conditions(conditions or [])
    if condition_error:
        return f"Error: {condition_error}\n\n{render_catalog(trigger_name)}"

    scope_errors = validate_scope(trigger_name, scope)
    if scope_errors:
        return f"Error: {' '.join(scope_errors)}\n\n{render_catalog(trigger_name)}"

    trigger_data = scope or None

    try:
        subscription, outcome, _created = await register_subscription(
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
        return f"Could not subscribe: {e}\n\n{render_catalog(trigger_name)}"

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


tools = [
    create_tracked_todo,
    search_todo_context,
    complete_tracked_todo,
    update_tracked_todo,
    list_tracked_todos,
    list_trigger_fields,
    subscribe_todo_to_trigger,
    unsubscribe_todo_from_trigger,
]
