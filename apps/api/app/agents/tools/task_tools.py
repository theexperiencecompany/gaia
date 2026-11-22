"""The agent's task tools: create, change and close a task, GAIA's or the user's own.

A GAIA task runs from its body and notes on its next check, its repeat or the app events
it subscribes to; a to-do (assignee user) is never run, only nudged when it falls due.
The notes are also notes.md under /workspace/tasks/, which the file tools edit.
"""

from datetime import UTC, datetime
from typing import Annotated, TypedDict

from langchain_core.runnables import RunnableConfig
from langchain_core.tools import tool
from pymongo.errors import DuplicateKeyError

from app.agents.tools.trigger_catalog import parse_conditions, parse_match, render_catalog
from app.config.oauth_config import get_integration_by_id
from app.constants.integrations import GMAIL_INTEGRATION_ID
from app.constants.tasks import (
    NEXT_CHECK_DURATION,
    NEXT_CHECK_DURATION_UNITS,
    Assignee,
    NoReplyPlan,
    TaskFlag,
    WaitingOn,
    WhenKind,
)
from app.constants.trigger_gates import GateAuthor
from app.db.repositories.tasks import task_repository
from app.decorators import with_doc
from app.models.agent_models import get_user_id, read_agent_configurable
from app.models.task_models import (
    DateWhen,
    ExternalRef,
    NoWhen,
    Priority,
    RepeatWhen,
    TaskDocument,
    TaskUpdate,
    Waiting,
    default_notify_on_run,
)
from app.models.trigger_gate_models import AuthoredGate, GateCondition
from app.models.trigger_subscription_models import ConditionMatch, SubscriptionAction
from app.schemas.tasks import TaskCreateRequest, TaskUpdateRequest
from app.services.canvas_markdown import canvas_problems, with_missing_sections
from app.services.integrations.user_integrations import get_connected_integration_ids
from app.services.tasks import task_service
from app.services.tasks.account_refs import owned_gmail_thread_ref, watched_account_id
from app.services.tasks.completion import complete_task as close_task
from app.services.tasks.errors import (
    OpenStateError,
    RepeatRuleError,
    SubtaskParentError,
    TaskNotFoundError,
)
from app.services.tasks.gaia_tasks import (
    create_gaia_task,
    reopen_for_its_ref,
    update_gaia_task,
)
from app.services.tasks.notes import CANVAS_TEMPLATE, with_ownership
from app.services.tasks.open_state import (
    NEXT_CHECK_HINT,
    WAITING_ON_CHOICES,
    describe_open_state,
    waiting_after,
)
from app.services.tasks.subscription_config import DEFAULT_COOLDOWN_SECONDS, SubscriptionError
from app.services.tasks.subscriptions import SubscriptionRequest, subscribe, unsubscribe
from app.services.tasks.thread_watch import watch_thread
from app.services.tasks.todo_rounds import first_repeat
from app.services.triggers.subscription_validation import validate_scope
from app.services.user_service import get_profile_timezone
from app.templates.docstrings.task_tool_docs import (
    COMPLETE_TASK,
    CREATE_TASK,
    LIST_EVENT_FIELDS,
    SUBSCRIBE_TASK,
    UNSUBSCRIBE_TASK,
    UPDATE_TASK,
)
from app.utils.schedule import InvalidScheduleError, validate_repeat_rule
from shared.py.analytics.catalog.properties import Identifier

_NEXT_CHECK_DESC = (
    "GAIA tasks: when GAIA next looks at it, as a duration from now ('30m', '4h', '3d', '1w') "
    f"or an ISO datetime with the user's offset. {NEXT_CHECK_HINT}"
)
_WAITING_ON_DESC = (
    f"GAIA tasks that do not repeat: what it waits for until next_check: {WAITING_ON_CHOICES}."
)
_QUESTION_DESC = "With waiting_on='user': the exact question you asked them."
_IF_NO_REPLY_DESC = (
    "With waiting_on='user': what happens when the question expires unanswered: 'ask_again' "
    "(one re-ask per task), 'proceed' (carry out default_action), 'hold' (nothing can move "
    "without the answer)."
)
_DEFAULT_ACTION_DESC = "With if_no_reply='proceed': exactly what you will do if they never answer."
_DUE_DESC = "ISO datetime, with the user's offset, it is due by."
_PRIORITY_DESC = "'high', 'medium', 'low' or 'none'"
_REPEAT_DESC = (
    "How often it repeats: 'daily', 'weekly', 'every_4h', 'every_1h', or a 5-field cron in the "
    "user's own wall-clock time ('0 9 * * 1-5'). A repeating task needs no next_check."
)
_NOTIFY_DESC = (
    "Whether the user hears about it: a GAIA task's results, a to-do's nudge when due. "
    "Set it only when the user asks to stop or resume hearing about it; left out, a subtask "
    "reports to its parent instead of the user."
)
_PARENT_DESC = (
    "The open, top-level task this one is a subtask of; GAIA's subtasks go under GAIA's tasks, "
    "one level deep"
)
_FLAGS_DESC = (
    "GAIA tasks: the states it is in, replacing those set before: 'blocked', "
    "'waiting_for_reply', 'waiting_for_approval' (an unblock subscription clears these), "
    "'needs_reply', 'action_needed'. [] clears them."
)


class _Refused(Exception):
    """A tool input the model must fix; its message is returned to the model as is."""


def _actor(config: RunnableConfig) -> str:
    conversation_id = read_agent_configurable(config).conversation_id
    return f"GAIA in conversation {conversation_id[:8]}" if conversation_id else "GAIA"


def _parse_moment(value: str, field: str, *, future: bool) -> datetime:
    """Read a duration from now ('4h') or an ISO datetime that carries its offset."""
    if duration := NEXT_CHECK_DURATION.fullmatch(value.strip()):
        amount = int(duration[1])
        if amount == 0:
            raise _Refused(f"Error: {field} must be in the future.")
        return datetime.now(UTC) + NEXT_CHECK_DURATION_UNITS[duration[2]] * amount
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        raise _Refused(
            f"Error: invalid {field} '{value}'. Pass an ISO datetime with offset, or a "
            "duration like '4h', '3d', '1w'."
        ) from None
    if parsed.tzinfo is None:
        raise _Refused(f"Error: {field} '{value}' must include a timezone offset.")
    if future and parsed <= datetime.now(UTC):
        raise _Refused(f"Error: {field} must be in the future.")
    return parsed


async def _when(
    user_id: str, due: str | None, repeat: str | None
) -> NoWhen | DateWhen | RepeatWhen:
    if repeat:
        try:
            validate_repeat_rule(repeat)
        except InvalidScheduleError as e:
            raise _Refused(f"Error: {e}") from e
        return first_repeat(RepeatWhen(rule=repeat), (await get_profile_timezone(user_id)).value)
    if due:
        return DateWhen(at=_parse_moment(due, "due", future=False))
    return NoWhen()


async def _missing_apps(user_id: str, needed: list[str]) -> str | None:
    connected = await get_connected_integration_ids(user_id)
    missing = [i for i in needed if i not in connected]
    if not missing:
        return None
    names = ", ".join(app.name if (app := get_integration_by_id(i)) else i for i in missing)
    return (
        f"Error: {names} is not connected, so no later run of this task could do its work. "
        "Nothing was saved. Activate it first and create the task once it is connected."
    )


async def _owned_references(user_id: str, references: list[str], task_id: str | None) -> None:
    found = {t.id for t in await task_repository.find_by_ids(user_id, references)}
    unknown = [r for r in references if r not in found or r == task_id]
    if unknown:
        raise _Refused(
            f"Error: no other task of this user has the id {', '.join(unknown)}. "
            "Nothing was saved; pass ids from list_tasks."
        )


#: What a subscribed task does when its event arrives, by the subscription's action.
_REACTS: dict[SubscriptionAction, str] = {
    SubscriptionAction.EXECUTE: "runs",
    SubscriptionAction.NOTIFY: "tells the user",
    SubscriptionAction.COMPLETE: "is completed",
    SubscriptionAction.UNBLOCK: "is unblocked",
}

_NO_FIELDS = "No fields to update. Provide at least one field to change."


def _move_fields(
    task: TaskDocument, parent_id: str | None, notify: bool | None
) -> dict[str, object]:
    """The fields that file a GAIA task under parent_id; moved, it reports like a new subtask."""
    if parent_id is None:
        return {}
    if task.assignee is Assignee.USER:
        raise _Refused(
            f"Error: {task.id} is the user's own to-do; a to-do is filed under a parent when "
            "it is created. Nothing was saved."
        )
    if notify is not None:
        return {"parent_id": parent_id}
    return {
        "parent_id": parent_id,
        "notify": default_notify_on_run(parent_id=parent_id, external_ref=task.external_ref),
    }


class _GaiaOnly(TypedDict):
    """The fields of an update only GAIA's own tasks hold."""

    notes: str | None
    observations: str | None
    expires_at: str | None
    references: list[str] | None
    flags: list[TaskFlag] | None


async def _update_todo(task: TaskDocument, fields: dict[str, object], gaia_only: _GaiaOnly) -> str:
    if held := [name for name, value in gaia_only.items() if value is not None]:
        return (
            f"Error: {task.id} is the user's own to-do; only GAIA's tasks keep {', '.join(held)}."
        )
    if not fields:
        return _NO_FIELDS
    await task_service.update_task(task.user_id, task.id, TaskUpdateRequest.model_validate(fields))
    return f"Updated to-do {task.id}: {', '.join(fields)}."


def _waiting_with(
    task: TaskDocument,
    on: WaitingOn | None,
    question: str | None,
    if_no_reply: NoReplyPlan | None,
    default_action: str | None,
) -> Waiting:
    """What the task waits on once this change lands; what the change leaves out stays as it was."""
    asked = task.waiting.question if task.waiting else None
    return waiting_after(
        task.waiting,
        on=on or (task.waiting.on if task.waiting else WaitingOn.TIME),
        question=question or (asked.text if asked else None),
        if_no_reply=if_no_reply or (asked.if_no_reply if asked else None),
        default_action=default_action or (asked.default_action if asked else None),
    )


def _twin_refusal(twin: TaskDocument) -> _Refused:
    return _Refused(
        f"Task {twin.id} ({twin.title}) already follows this thread, so nothing new was "
        "created. Update that one instead."
    )


async def _new_thread_ref(
    user_id: str, gmail_thread_id: str | None, gmail_account: str | None
) -> ExternalRef | None:
    """The thread a new task is about, pinned to its account; refused when it has an open task."""
    thread = await owned_gmail_thread_ref(user_id, gmail_thread_id, gmail_account)
    if isinstance(thread, str):
        raise _Refused(thread)
    if thread is not None and (
        twin := await task_repository.find_open_by_external_ref(user_id, thread)
    ):
        raise _twin_refusal(twin)
    return thread


async def _refused_as_taken(user_id: str, thread: ExternalRef) -> _Refused:
    """The refusal for a create a concurrent one beat to the thread, naming the winner."""
    twin = await task_repository.find_open_by_external_ref(user_id, thread)
    if twin is None:
        raise LookupError(f"the thread {thread.id} was taken, yet no open task follows it")
    return _twin_refusal(twin)


def _starting_notes(title: str, notes: str | None) -> str:
    """The notes a new GAIA task starts with: the template, or the given ones in its shape."""
    if notes is None:
        return CANVAS_TEMPLATE.format(title=title)
    shaped = with_missing_sections(
        notes if notes.lstrip().startswith("# ") else f"# {title}\n\n{notes}"
    )
    if problems := canvas_problems(shaped):
        raise _Refused(
            f"Error: the notes break the notes' shape: {'; '.join(problems)}. Nothing was saved."
        )
    return shaped


async def _reopened_for_thread(
    previous: TaskDocument, draft: TaskDocument, config: RunnableConfig
) -> str:
    """Take a thread's closed task on again with the new task's plan; its notes are kept."""
    plan = TaskUpdate(
        title=draft.title,
        priority=draft.priority,
        parent_id=draft.parent_id,
        notify=draft.notify,
        when=draft.when,
        waiting=draft.waiting,
        next_check_at=draft.next_check_at,
        status_flags=draft.status_flags,
        integration_ids=draft.integration_ids,
    )
    if draft.body:
        plan.body = draft.body
    reopened = await reopen_for_its_ref(previous, plan, by=_actor(config))
    if reopened is None:
        if previous.external_ref is None:
            raise LookupError(f"task {previous.id} lost its thread while it was reopened")
        raise await _refused_as_taken(previous.user_id, previous.external_ref)
    return (
        f"Task {reopened.id} ({reopened.title}) followed this thread before and was done, so "
        "it was reopened instead of creating a new one. Its notes kept their history and the "
        "notes passed now were not written: write this thread's state into its Current State "
        f"with update_task. {describe_open_state(reopened, datetime.now(UTC))}."
    )


async def _watch_or_undo(task: TaskDocument, thread: ExternalRef | None) -> None:
    """Watch the new task's thread, if any; a task that cannot watch it is deleted, the model told."""
    if thread is None:
        return
    try:
        await watch_thread(task, thread)
    except SubscriptionError as refused:
        await task_service.delete_tasks(task.user_id, [task.id])
        raise _Refused(
            f"Error: the thread could not be watched ({refused}). Nothing was saved."
        ) from refused


async def _gaia_plan_fields(task: TaskDocument, gaia_only: _GaiaOnly) -> dict[str, object]:
    """The GAIA-only fields of an update: notes, when it stops mattering, what it reads, its states."""
    expires_at, references, flags = (
        gaia_only["expires_at"],
        gaia_only["references"],
        gaia_only["flags"],
    )
    fields: dict[str, object] = {}
    if gaia_only["notes"] is not None:
        fields["notes"] = gaia_only["notes"]
    if gaia_only["observations"] is not None:
        fields["observations"] = gaia_only["observations"]
    if expires_at is not None:
        fields["expires_at"] = _parse_moment(expires_at, "expires_at", future=True)
    if references is not None:
        await _owned_references(task.user_id, references, task.id)
        fields["references"] = references
    if flags is not None:
        kept = [f for f in task.status_flags if f is TaskFlag.FAILED]
        fields["status_flags"] = [*kept, *_set_flags(flags)]
    return fields


def _set_flags(flags: list[TaskFlag]) -> list[TaskFlag]:
    """The states GAIA set on a task, once each; 'failed' is the engine's alone."""
    if TaskFlag.FAILED in flags:
        raise _Refused("Error: 'failed' is set by the engine only. Nothing was saved.")
    return list(dict.fromkeys(flags))


def _refusal(refused: OpenStateError, verb: str) -> str:
    problems = "\n".join(f"- {p}" for p in refused.problems)
    return f"Error: the task was not {verb}, because it would have no valid next step:\n{problems}"


async def _take_on(draft: TaskDocument, config: RunnableConfig) -> str:
    """Create GAIA's task, or reopen the done task its thread had; returns what the tool says."""
    thread = draft.external_ref
    previous = (
        await task_repository.find_latest_by_external_ref(draft.user_id, thread) if thread else None
    )
    if previous is not None and previous.completed:
        return await _reopened_for_thread(previous, draft, config)
    try:
        created = await create_gaia_task(draft, by=_actor(config))
    except DuplicateKeyError:
        if thread is None:
            raise
        raise await _refused_as_taken(draft.user_id, thread) from None
    await _watch_or_undo(created, thread)
    return (
        f"Task created (id {created.id}): {created.title}. "
        f"{describe_open_state(created, datetime.now(UTC))}."
    )


@tool
@with_doc(CREATE_TASK)
async def create_task(
    config: RunnableConfig,
    title: Annotated[str, "Short title for the task"],
    assignee: Annotated[Assignee, "'gaia' for work GAIA does, 'user' for the user's own to-do"],
    body: Annotated[str | None, "What the task is about, in a few sentences"] = None,
    priority: Annotated[Priority, _PRIORITY_DESC] = Priority.NONE,
    due: Annotated[str | None, _DUE_DESC] = None,
    repeat: Annotated[str | None, _REPEAT_DESC] = None,
    waiting_on: Annotated[WaitingOn | None, _WAITING_ON_DESC] = None,
    next_check: Annotated[str | None, _NEXT_CHECK_DESC] = None,
    question: Annotated[str | None, _QUESTION_DESC] = None,
    if_no_reply: Annotated[NoReplyPlan | None, _IF_NO_REPLY_DESC] = None,
    default_action: Annotated[str | None, _DEFAULT_ACTION_DESC] = None,
    notify: Annotated[bool | None, _NOTIFY_DESC] = None,
    parent_id: Annotated[str | None, _PARENT_DESC] = None,
    done_when: Annotated[
        list[str] | None,
        "GAIA tasks: the checkable conditions that make it done, one each, as the user means "
        "them ('the feature is live for users', not 'a PR exists'). Every run checks them.",
    ] = None,
    evidence: Annotated[
        str | None, "GAIA tasks: where proof of each condition will show up and how a run checks it"
    ] = None,
    expires_at: Annotated[
        str | None, "GAIA tasks: ISO datetime after which it no longer matters, with offset"
    ] = None,
    references: Annotated[
        list[str] | None, "GAIA tasks: ids of earlier tasks whose Learnings every run reads"
    ] = None,
    needs_integrations: Annotated[
        list[str] | None,
        "GAIA tasks: integration ids its later runs depend on; nothing is created while one "
        "is not connected",
    ] = None,
    notes: Annotated[
        str | None,
        "GAIA tasks: its starting notes (notes.md) in the notes' '## ' sections, like "
        "'## Key Details' and '## Current State'; sections left out start empty. Omit for the "
        "empty template.",
    ] = None,
    flags: Annotated[list[TaskFlag] | None, _FLAGS_DESC] = None,
    gmail_thread_id: Annotated[
        str | None,
        "GAIA tasks about one email thread: its Gmail thread id. The task then runs on new "
        "mail and on the user's own replies there, and a thread has one task: an open one is "
        "named back to update instead, and a done one is reopened.",
    ] = None,
    gmail_account: Annotated[
        str | None,
        "With gmail_thread_id: the Gmail account the thread is in, by its listed name; "
        "needed when the user has several.",
    ] = None,
) -> str:
    user_id = get_user_id(config)
    try:
        when = await _when(user_id, due, repeat)
        if assignee is Assignee.USER:
            if held := [n for n, v in (("notes", notes), ("flags", flags)) if v is not None]:
                return (
                    f"Error: a to-do is the user's own; only GAIA's tasks keep {', '.join(held)}."
                )
            created = await task_service.create_task(
                user_id,
                TaskCreateRequest(
                    title=title,
                    body=body or "",
                    priority=priority,
                    when=when,
                    parent_id=parent_id,
                    notify=(
                        default_notify_on_run(parent_id=parent_id, external_ref=None)
                        if notify is None
                        else notify
                    ),
                ),
            )
            return f"To-do created (id {created.id}): {created.title}."
        thread = await _new_thread_ref(user_id, gmail_thread_id, gmail_account)
        if notify is None:
            notify = default_notify_on_run(parent_id=parent_id, external_ref=thread)
        # A thread's task reads and drafts in Gmail on every run.
        thread_app = [GMAIL_INTEGRATION_ID] if thread is not None else []
        needed = list(dict.fromkeys([*(needs_integrations or []), *thread_app]))
        if refusal := await _missing_apps(user_id, needed):
            return refusal
        if references:
            await _owned_references(user_id, references, None)
        draft = TaskDocument(
            user_id=user_id,
            title=title,
            body=body or "",
            assignee=Assignee.GAIA,
            priority=priority,
            when=when,
            parent_id=parent_id,
            notify=notify,
            notes=with_ownership(_starting_notes(title, notes), done_when or [], evidence),
            status_flags=_set_flags(flags or []),
            references=references or [],
            integration_ids=needed,
            external_ref=thread,
            source_conversation_id=read_agent_configurable(config).conversation_id,
            expires_at=_parse_moment(expires_at, "expires_at", future=True) if expires_at else None,
        )
        if when.kind is not WhenKind.REPEAT:
            draft.next_check_at = (
                _parse_moment(next_check, "next_check", future=True) if next_check else None
            )
            if waiting_on is not None:
                draft.waiting = waiting_after(
                    None,
                    on=waiting_on,
                    question=question,
                    if_no_reply=if_no_reply,
                    default_action=default_action,
                )
        return await _take_on(draft, config)
    except _Refused as refused:
        return str(refused)
    except OpenStateError as refused:
        return _refusal(refused, "created")
    except (TaskNotFoundError, SubtaskParentError, RepeatRuleError) as refused:
        return f"Error: {refused.message} Nothing was saved."


@tool
@with_doc(UPDATE_TASK)
async def update_task(
    config: RunnableConfig,
    task_id: Annotated[str, "Id of the task to change"],
    title: Annotated[str | None, "New title"] = None,
    body: Annotated[str | None, "New details"] = None,
    priority: Annotated[Priority | None, _PRIORITY_DESC] = None,
    notes: Annotated[
        str | None, "GAIA tasks: the whole new working notes (notes.md), as get_task shows them"
    ] = None,
    observations: Annotated[
        str | None,
        "GAIA tasks: the whole new observations (observations.md), as get_task shows them",
    ] = None,
    due: Annotated[str | None, _DUE_DESC] = None,
    waiting_on: Annotated[WaitingOn | None, _WAITING_ON_DESC] = None,
    next_check: Annotated[str | None, _NEXT_CHECK_DESC] = None,
    question: Annotated[str | None, _QUESTION_DESC] = None,
    if_no_reply: Annotated[NoReplyPlan | None, _IF_NO_REPLY_DESC] = None,
    default_action: Annotated[str | None, _DEFAULT_ACTION_DESC] = None,
    notify: Annotated[bool | None, _NOTIFY_DESC] = None,
    parent_id: Annotated[
        str | None, "Move it under this task as its subtask. " + _PARENT_DESC
    ] = None,
    repeat: Annotated[str | None, _REPEAT_DESC + " Replaces its date."] = None,
    expires_at: Annotated[
        str | None, "GAIA tasks: ISO datetime after which it no longer matters, with offset"
    ] = None,
    references: Annotated[
        list[str] | None,
        "GAIA tasks: ids of earlier tasks whose Learnings every run reads; replaces the list",
    ] = None,
    flags: Annotated[list[TaskFlag] | None, _FLAGS_DESC] = None,
) -> str:
    user_id = get_user_id(config)
    try:
        task = await task_service.require_task(user_id, task_id)
        fields: dict[str, object] = {
            name: value
            for name, value in {
                "title": title,
                "body": body,
                "priority": priority,
                "notify": notify,
            }.items()
            if value is not None
        }
        if due is not None or repeat is not None:
            fields["when"] = await _when(user_id, None if repeat else due, repeat)
        fields.update(_move_fields(task, parent_id, notify))
        gaia_only = _GaiaOnly(
            notes=notes,
            observations=observations,
            expires_at=expires_at,
            references=references,
            flags=flags,
        )
        if task.assignee is Assignee.USER:
            return await _update_todo(task, fields, gaia_only)
        fields.update(await _gaia_plan_fields(task, gaia_only))
        if repeat is not None:
            # A repeating task never waits: its schedule is its next step.
            fields.update(waiting=None, next_check_at=None)
        elif next_check is not None:
            fields["next_check_at"] = _parse_moment(next_check, "next_check", future=True)
        if repeat is None and any(
            v is not None for v in (waiting_on, question, if_no_reply, default_action)
        ):
            fields["waiting"] = _waiting_with(
                task, waiting_on, question, if_no_reply, default_action
            )
        if not fields:
            return _NO_FIELDS
        updated = await update_gaia_task(task, TaskUpdate.model_validate(fields), by=_actor(config))
    except _Refused as refused:
        return str(refused)
    except OpenStateError as refused:
        return _refusal(refused, "updated")
    except (SubtaskParentError, TaskNotFoundError) as refused:
        return f"Error: {refused.message} Nothing was saved."
    return (
        f"Updated task {task_id}: {', '.join(fields)}. "
        f"{describe_open_state(updated, datetime.now(UTC))}."
    )


@tool
@with_doc(COMPLETE_TASK)
async def complete_task(
    config: RunnableConfig,
    task_id: Annotated[str, "Id of the task to mark done"],
    summary: Annotated[str, "One or two sentences on what was achieved"],
    stop_repeat: Annotated[
        bool, "True only when the user asked to stop a repeating task entirely"
    ] = False,
) -> str:
    user_id = get_user_id(config)
    try:
        task = await task_service.require_task(user_id, task_id)
    except TaskNotFoundError as missing:
        return f"Error: {missing.message}"
    if isinstance(task.when, RepeatWhen) and not stop_repeat:
        return (
            f"Error: task {task_id} repeats ({task.when.rule}). One finished run never ends a "
            "standing schedule: leave it open, or if the user asked to stop it entirely, call "
            "complete_task again with stop_repeat=true."
        )
    if await close_task(task, summary) is None:
        return f"Task {task_id} was already done."
    return f"{'To-do' if task.assignee is Assignee.USER else 'Task'} {task_id} completed."


@tool
@with_doc(LIST_EVENT_FIELDS)
async def list_event_fields(
    trigger_name: Annotated[
        str,
        "GAIA event slug, e.g. 'gmail_new_message', 'calendar_event_starting_soon', "
        "'slack_new_message'. A wrong name returns every event a task can subscribe to.",
    ],
) -> str:
    return render_catalog(trigger_name)


@tool
@with_doc(SUBSCRIBE_TASK)
async def subscribe_task(
    config: RunnableConfig,
    task_id: Annotated[str, "Id of the GAIA task that runs when the event arrives"],
    # Identifier-typed: a slug analytics cannot carry fails the args schema before registering.
    trigger_name: Annotated[Identifier, "GAIA event slug to listen for, e.g. 'gmail_new_message'"],
    action: Annotated[
        SubscriptionAction,
        "What the event does: 'execute' (run the task with the event), 'notify' (tell the "
        "user only), 'complete' (close the task), 'unblock' (clear its waiting flag).",
    ] = SubscriptionAction.EXECUTE,
    conditions: Annotated[
        list[dict[str, str | int | float]] | None,
        "Narrowing tests, each {'field_name': ..., 'operator': ..., 'value': ...} on fields from "
        "list_event_fields. Omit to run on every event, sensible only for an event already "
        "scoped to one channel or calendar.",
    ] = None,
    match: Annotated[
        str,
        "How the conditions combine: 'all' (every one holds, the default) or 'any' (one is "
        "enough). For an OR of several ANDs, subscribe several times.",
    ] = ConditionMatch.ALL.value,
    cooldown_seconds: Annotated[
        int, "Events within this many seconds of a run ride the next run together."
    ] = DEFAULT_COOLDOWN_SECONDS,
    scope: Annotated[
        dict[str, str | bool | int | float | list[str]] | None,
        "Registration config naming the resource to watch, e.g. {'repos': ['owner/name']} "
        "for github, {'minutes_before_start': 60} for calendar_event_starting_soon. Not a "
        "payload condition; list_event_fields shows the scope an event needs.",
    ] = None,
    account: Annotated[
        str | None,
        "Only events on this one connected account, by its listed name or id. Omit to "
        "listen on every account of the app.",
    ] = None,
    runs_only_when: Annotated[
        GateCondition | None,
        "One short sentence about the event itself, from the task's intent, naming which "
        "events are worth a run, e.g. 'The reply confirms the invoice is paid or asks about "
        "it.' GAIA checks it before each run and skips an event that clearly fails it, so "
        "keep it as broad as the task needs. Omit when every matching event should run.",
    ] = None,
) -> str:
    user_id = get_user_id(config)
    parsed_match = parse_match(match)
    if parsed_match is None:
        valid = ", ".join(m.value for m in ConditionMatch)
        return f"Error: '{match}' is not a valid match mode. Valid modes: {valid}."
    parsed_conditions, condition_error = parse_conditions(conditions or [])
    if condition_error:
        return f"Error: {condition_error}\n\n{render_catalog(trigger_name)}"
    if scope_errors := validate_scope(trigger_name, scope):
        return f"Error: {' '.join(scope_errors)}\n\n{render_catalog(trigger_name)}"
    account_id = await watched_account_id(user_id, trigger_name, account) if account else None
    if account and account_id is None:
        return f"Error: no connected account for {trigger_name} is named {account!r}."
    gate = (
        None
        if runs_only_when is None
        else AuthoredGate(condition=runs_only_when, author=GateAuthor.GAIA)
    )
    try:
        task = await task_service.require_task(user_id, task_id)
        stored = await subscribe(
            task,
            SubscriptionRequest(
                trigger_name=trigger_name,
                action=action,
                conditions=parsed_conditions,
                match=parsed_match,
                cooldown_seconds=cooldown_seconds,
                trigger_data=scope or None,
                account_id=account_id,
                gate=gate,
            ),
        )
    except TaskNotFoundError as missing:
        return f"Error: {missing.message}"
    except SubscriptionError as refused:
        # The catalog rides along on failure, so the retry has what it needs.
        return f"Could not subscribe: {refused}\n\n{render_catalog(trigger_name)}"
    subscription = stored.subscription
    if not stored.created:
        runs_on = (
            f"runs only when: {subscription.gate.display_condition}"
            if subscription.gate
            else "runs on every matching event"
        )
        return (
            f"Task {task_id} already listens for {trigger_name} with these settings "
            f"(subscription id: {subscription.id}), so nothing new was stored and it still "
            f"{runs_on}. To change runs_only_when, unsubscribe it and subscribe again."
        )
    lines = [
        f"Task {task_id} now {_REACTS[action]} when {trigger_name} arrives.",
        f"Subscription id: {subscription.id}",
    ]
    if stored.outcome.repairs:
        lines.append("Repaired: " + "; ".join(r.reason for r in stored.outcome.repairs))
    return "\n".join(lines)


@tool
@with_doc(UNSUBSCRIBE_TASK)
async def unsubscribe_task(
    config: RunnableConfig,
    task_id: Annotated[str, "Id of the GAIA task"],
    subscription_id: Annotated[str, "Subscription id, as subscribe_task returned it"],
) -> str:
    user_id = get_user_id(config)
    try:
        task = await task_service.require_task(user_id, task_id)
        removed = await unsubscribe(task, subscription_id)
    except TaskNotFoundError as missing:
        return f"Error: {missing.message}"
    except SubscriptionError as refused:
        return f"Error: {refused} Nothing was changed."
    if removed is None:
        return f"Task {task_id} has no subscription {subscription_id}."
    return f"Task {task_id} has stopped listening for {removed.trigger_name}."


tools = [
    create_task,
    update_task,
    complete_task,
    list_event_fields,
    subscribe_task,
    unsubscribe_task,
]
