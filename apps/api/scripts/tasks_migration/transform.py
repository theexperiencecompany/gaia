"""Pure mappings from the legacy documents to tasks, runs, templates and task playbooks.

Nothing here reads or writes a database. A document the target model cannot hold
faithfully raises Unmappable naming why, instead of being bent to fit.
"""

from dataclasses import dataclass
from datetime import UTC, datetime
import re
from typing import Final

from bson import ObjectId
from scripts.tasks_migration.legacy import (
    DROPPED_SYSTEM_LABELS,
    GAIA_TRACKED_LABEL,
    LABEL_FLAGS,
    ONBOARDING_LABEL,
    LegacyExecution,
    LegacyPlaybook,
    LegacyRunState,
    LegacyTodo,
    LegacyTriggerType,
    LegacyWorkflow,
    legacy_playbook_valid,
)

from app.constants.tasks import (
    IMPORTED_RUN_TRIGGER,
    INBOX_DESK_SYSTEM_KEY,
    Assignee,
    TaskFlag,
    TaskRunKind,
    TaskRunState,
    TaskRunStatus,
    TemplateOrigin,
    WaitingOn,
)
from app.models.playbook_models import TaskPlaybookDocument
from app.models.task_models import (
    DateWhen,
    EventWhen,
    ExternalRefSource,
    NoWhen,
    RepeatWhen,
    TaskDocument,
    Waiting,
    WaitingQuestion,
    When,
)
from app.models.task_run_models import ImportedActivity, TaskRunDocument
from app.models.task_template_models import (
    TaskTemplateDocument,
    TemplateEventWhen,
    TemplateNoWhen,
    TemplateRepeatWhen,
    TemplateWhen,
)
from app.models.trigger_subscription_models import (
    SubscriptionAction,
    SubscriptionResolution,
    TriggerSubscription,
    TriggerSubscriptionStatus,
)
from app.services.tasks.body_hash import task_body_hash
from shared.py.utils.slugify import slugify

GMAIL: Final = "gmail"
#: The suffix of the one subscription a workflow's trigger becomes.
WORKFLOW_SUBSCRIPTION_SUFFIX: Final = ":trigger"
IMPORTED_RUN_PREFIX: Final = "imported_"
#: A slug made for a public workflow that never got one: its title and the tail of its id.
SLUG_ID_TAIL: Final = 6

_RUN_STATES: Final = {
    LegacyRunState.SCHEDULED.value: TaskRunState.IDLE,
    LegacyRunState.EXECUTING.value: TaskRunState.RUNNING,
    LegacyRunState.COMPLETED.value: TaskRunState.ENDED,
}
_EXECUTION_STATUSES: Final = {status.value: status for status in TaskRunStatus}
#: The activity.md events that close one run, and how that run ended.
RUN_END_EVENTS: Final = {
    "run_finished": TaskRunStatus.SUCCESS,
    "run_failed": TaskRunStatus.FAILED,
    "run_skipped": TaskRunStatus.SKIPPED,
    "run_cancelled": TaskRunStatus.CANCELLED,
}
RUN_START_EVENT: Final = "run_started"
#: One code-written activity.md entry: "- <iso time> [event] detail".
ACTIVITY_ENTRY: Final = re.compile(
    r"^- (?P<at>\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:[+-]\d{2}:\d{2}|Z)?) "
    r"\[(?P<event>[a-z_]+)\] ?(?P<detail>.*?)\s*$"
)


class Unmappable(ValueError):
    """A legacy document the task model cannot hold without losing or inventing something."""


@dataclass(frozen=True)
class ActivitySlice:
    """One cut of an activity log: a run's lines up to its end, or the lines since the last run."""

    seq: int
    text: str
    status: TaskRunStatus | None
    started_at: datetime | None
    ended_at: datetime | None
    summary: str | None


# Todos.


def flags_from_labels(labels: list[str]) -> list[TaskFlag]:
    """Every system label the engine reads, as its flag, in label order and once."""
    flags: list[TaskFlag] = []
    for label in labels:
        flag = LABEL_FLAGS.get(label)
        if flag is not None and flag not in flags:
            flags.append(flag)
    return flags


def dropped_labels(labels: list[str]) -> list[str]:
    """The labels no task field carries: user labels and the one dead system label."""
    kept = {GAIA_TRACKED_LABEL, ONBOARDING_LABEL, *LABEL_FLAGS}
    return [label for label in labels if label not in kept or label in DROPPED_SYSTEM_LABELS]


def _todo_when(todo: LegacyTodo) -> When:
    if todo.recurrence:
        if todo.by_gaia and todo.due_date is not None:
            raise Unmappable("a repeating GAIA todo with a due date: a repeat has no due date")
        next_run = todo.scheduled_at if todo.by_gaia else todo.due_date
        return RepeatWhen(rule=todo.recurrence, timezone=todo.due_date_timezone, next_run=next_run)
    if todo.due_date is not None:
        return DateWhen(at=todo.due_date, timezone=todo.due_date_timezone)
    if todo.trigger_subscriptions:
        return EventWhen()
    return NoWhen()


def _todo_waiting(todo: LegacyTodo) -> Waiting | None:
    asked = todo.question is not None or todo.if_no_reply is not None or todo.default_action
    if todo.waiting_on is None:
        if asked or todo.hold_checks:
            raise Unmappable("question fields set on a todo that waits on nothing")
        return None
    if todo.waiting_on is not WaitingOn.USER:
        if asked or todo.hold_checks:
            raise Unmappable(f"question fields set on a todo waiting on {todo.waiting_on.value}")
        return Waiting(on=todo.waiting_on)
    if todo.question is None:
        if asked or todo.hold_checks:
            raise Unmappable("a reply plan or hold count with no question")
        return Waiting(on=WaitingOn.USER)
    return Waiting(
        on=WaitingOn.USER,
        question=WaitingQuestion(
            text=todo.question,
            if_no_reply=todo.if_no_reply,
            default_action=todo.default_action,
            hold_checks=todo.hold_checks,
        ),
    )


def owed_nudge(todo: LegacyTodo, *, now: datetime) -> datetime | None:
    """Return the nudge an open, dated plain todo owes: its due time while that is still ahead."""
    owes = (
        not todo.by_gaia
        and not todo.completed
        and not todo.recurrence
        and todo.notify_on_run
        and todo.due_date is not None
        and todo.due_date > now
    )
    return todo.due_date if owes else None


def _is_desk(todo: LegacyTodo) -> bool:
    return (
        todo.external_ref is not None and todo.external_ref.source is ExternalRefSource.INBOX_DESK
    )


def task_from_todo(todo: LegacyTodo) -> TaskDocument:
    """Map a todo to its task; every Inbox desk becomes the desk system task, a stopped one switched off."""
    by_gaia = todo.by_gaia
    if not by_gaia and todo.scheduled_at is not None:
        raise Unmappable("a plain todo with scheduled_at, which nothing runs")
    when = _todo_when(todo)
    repeats = isinstance(when, RepeatWhen)
    desk = _is_desk(todo)
    return TaskDocument(
        id=todo.id,
        user_id=todo.user_id,
        title=todo.title,
        body=todo.description or "",
        assignee=Assignee.GAIA if by_gaia else Assignee.USER,
        priority=todo.priority,
        completed=todo.completed,
        completed_at=todo.completed_at,
        subtasks=todo.subtasks,
        parent_id=todo.parent_todo_id,
        when=when,
        next_check_at=None if repeats else todo.scheduled_at,
        nudge_at=owed_nudge(todo, now=datetime.now(UTC)),
        subscriptions=todo.trigger_subscriptions,
        active=todo.pause_reason is None and not (desk and todo.completed),
        pause_reason=todo.pause_reason,
        retry_count=todo.gaia_retry_count,
        waiting=_todo_waiting(todo),
        reasks_used=todo.reasks_used,
        status_flags=flags_from_labels(todo.labels),
        notes=todo.canvas_content,
        observations=todo.observations_content,
        log=todo.log_content,
        external_ref=todo.external_ref,
        source_conversation_id=todo.source_conversation_id,
        references=todo.references,
        expires_at=todo.expires_at,
        source_email=todo.source_email,
        from_onboarding=ONBOARDING_LABEL in todo.labels,
        notify=todo.notify_on_run,
        system_key=INBOX_DESK_SYSTEM_KEY if desk else None,
        source_integration=GMAIL if desk else None,
        created_at=todo.created_at,
        updated_at=todo.updated_at,
    )


def _entry_time(match: re.Match[str]) -> datetime:
    return datetime.fromisoformat(match.group("at").replace("Z", "+00:00"))


def slice_activity(text: str) -> list[ActivitySlice]:
    """Cut an activity log at every line that ends a run; the slices joined in order are the log."""
    slices: list[ActivitySlice] = []
    lines: list[str] = []
    started: datetime | None = None
    first_seen: datetime | None = None
    last_seen: datetime | None = None
    for line in text.splitlines(keepends=True):
        lines.append(line)
        entry = ACTIVITY_ENTRY.match(line)
        if entry is None:
            continue
        at = _entry_time(entry)
        first_seen = first_seen or at
        last_seen = at
        event = entry.group("event")
        if event == RUN_START_EVENT:
            started = at
        elif event in RUN_END_EVENTS:
            slices.append(
                ActivitySlice(
                    seq=len(slices),
                    text="".join(lines),
                    status=RUN_END_EVENTS[event],
                    started_at=started or at,
                    ended_at=at,
                    summary=entry.group("detail") or None,
                )
            )
            lines, started, first_seen, last_seen = [], None, None, None
    if lines:
        slices.append(
            ActivitySlice(
                seq=len(slices),
                text="".join(lines),
                status=None,
                started_at=first_seen,
                ended_at=last_seen,
                summary=None,
            )
        )
    return slices


def imported_run_id(todo_id: str, seq: int) -> str:
    return f"{IMPORTED_RUN_PREFIX}{todo_id}_{seq}"


def runs_from_activity(todo: LegacyTodo) -> list[TaskRunDocument]:
    """One record per run in the todo's activity log, and one for the lines after its last run."""
    if not todo.activity_content:
        return []
    fallback = todo.created_at or ObjectId(todo.id).generation_time
    records: list[TaskRunDocument] = []
    for cut in slice_activity(todo.activity_content):
        started = cut.started_at or fallback
        records.append(
            TaskRunDocument(
                run_id=imported_run_id(todo.id, cut.seq),
                task_id=todo.id,
                user_id=todo.user_id,
                kind=TaskRunKind.RUN if cut.status is not None else TaskRunKind.HISTORY,
                status=cut.status,
                started_at=started,
                completed_at=cut.ended_at,
                duration_seconds=(
                    (cut.ended_at - started).total_seconds() if cut.ended_at is not None else None
                ),
                summary=cut.summary,
                trigger_type=IMPORTED_RUN_TRIGGER,
                imported=ImportedActivity(seq=cut.seq, text=cut.text),
            )
        )
    return records


# Workflows.


def workflow_subscription_id(workflow_id: str) -> str:
    return f"{workflow_id}{WORKFLOW_SUBSCRIPTION_SUFFIX}"


def _trigger_type(workflow: LegacyWorkflow) -> LegacyTriggerType:
    try:
        return LegacyTriggerType(workflow.trigger_config.type)
    except ValueError as unknown:
        raise Unmappable(
            f"trigger type {workflow.trigger_config.type!r} is not one a task has"
        ) from unknown


def _workflow_when(workflow: LegacyWorkflow) -> When:
    trigger = workflow.trigger_config
    match _trigger_type(workflow):
        case LegacyTriggerType.MANUAL:
            return NoWhen()
        case LegacyTriggerType.SCHEDULE:
            if not trigger.cron_expression:
                raise Unmappable("a schedule trigger with no cron expression")
            return RepeatWhen(
                rule=trigger.cron_expression, timezone=trigger.timezone, next_run=trigger.next_run
            )
        case LegacyTriggerType.INTEGRATION:
            return EventWhen()


def _workflow_subscriptions(workflow: LegacyWorkflow) -> list[TriggerSubscription]:
    if _trigger_type(workflow) is not LegacyTriggerType.INTEGRATION:
        if workflow.gate is not None:
            raise Unmappable("a gate on a trigger with no event")
        return []
    trigger = workflow.trigger_config
    if not trigger.trigger_name:
        raise Unmappable("an app-event trigger with no trigger name")
    return [
        TriggerSubscription(
            id=workflow_subscription_id(workflow.id),
            trigger_name=trigger.trigger_name,
            action=SubscriptionAction.EXECUTE,
            cooldown_seconds=0,
            resolution=SubscriptionResolution.TRIGGER_ID,
            composio_trigger_ids=trigger.composio_trigger_ids or [],
            trigger_data=trigger.trigger_data or {},
            gate=workflow.gate,
            status=TriggerSubscriptionStatus.ACTIVE,
            created_at=workflow.created_at,
        )
    ]


def task_from_workflow(workflow: LegacyWorkflow, *, parent_id: str | None) -> TaskDocument:
    """Map a workflow to its GAIA task; a todo's generated workflow comes in under parent_id."""
    if workflow.status not in _RUN_STATES:
        raise Unmappable(f"run state {workflow.status!r}, which the liveness migration retired")
    return TaskDocument(
        id=workflow.id,
        user_id=workflow.user_id,
        title=workflow.title,
        body=workflow.effective_prompt,
        assignee=Assignee.GAIA,
        parent_id=parent_id,
        when=_workflow_when(workflow),
        subscriptions=_workflow_subscriptions(workflow),
        active=workflow.activated,
        # An activate clears the reason; one left on a workflow that is on explains nothing.
        pause_reason=None if workflow.activated else workflow.deactivated_reason,
        run_state=_RUN_STATES[workflow.status],
        icon=workflow.icon,
        icon_color=workflow.icon_color,
        notify=workflow.notify_on_completion,
        integration_ids=workflow.integration_ids,
        blocked_on_integrations=workflow.blocked_on_integrations,
        max_occurrences=workflow.max_occurrences,
        stop_after=workflow.stop_after,
        occurrence_count=workflow.occurrence_count,
        total_runs=workflow.total_executions,
        successful_runs=workflow.successful_executions,
        last_run_at=workflow.last_executed_at,
        last_playbook_discard=workflow.last_playbook_discard,
        system_key=workflow.system_workflow_key if workflow.is_system_workflow else None,
        source_integration=workflow.source_integration,
        created_at=workflow.created_at,
        updated_at=workflow.updated_at,
    )


def template_slug(workflow: LegacyWorkflow) -> str:
    """The workflow's public slug, or the one its lazy backfill would give it, made deterministic."""
    if workflow.slug:
        return workflow.slug
    return f"{slugify(workflow.title) or 'workflow'}-{workflow.id[-SLUG_ID_TAIL:]}"


def _template_when(workflow: LegacyWorkflow) -> TemplateWhen:
    when = _workflow_when(workflow)
    if isinstance(when, RepeatWhen):
        return TemplateRepeatWhen(rule=when.rule, timezone=when.timezone)
    if isinstance(when, EventWhen):
        (subscription,) = _workflow_subscriptions(workflow)
        return TemplateEventWhen(
            trigger_name=subscription.trigger_name, trigger_data=subscription.trigger_data
        )
    return TemplateNoWhen()


def tool_categories(workflow: LegacyWorkflow) -> list[str]:
    """The distinct step categories, in step order: what the card's icons and related list read."""
    return list(dict.fromkeys(step.category for step in workflow.steps))


def template_from_workflow(workflow: LegacyWorkflow) -> TaskTemplateDocument:
    """Map a published or curated workflow to its template; its id stays the workflow's."""
    curated = workflow.is_explore
    return TaskTemplateDocument(
        id=workflow.id,
        title=workflow.title,
        body=workflow.effective_prompt,
        summary=workflow.description,
        icon=workflow.icon,
        icon_color=workflow.icon_color,
        when=_template_when(workflow),
        integration_ids=workflow.integration_ids,
        tool_categories=tool_categories(workflow),
        slug=template_slug(workflow),
        origin=TemplateOrigin.CURATED if curated else TemplateOrigin.COMMUNITY,
        creator_id=workflow.created_by or workflow.user_id,
        categories=workflow.use_case_categories if curated else [],
        run_count=workflow.total_executions,
        source_task_id=None if curated else workflow.id,
        system_key=workflow.system_workflow_key,
        source_integration=workflow.source_integration,
        created_at=workflow.created_at,
        updated_at=workflow.updated_at,
    )


def run_from_execution(execution: LegacyExecution) -> TaskRunDocument:
    """Map one workflow execution to its run record, id unchanged."""
    status = _EXECUTION_STATUSES.get(execution.status)
    if status is None:
        raise Unmappable(f"execution status {execution.status!r}")
    return TaskRunDocument(
        run_id=execution.execution_id,
        task_id=execution.workflow_id,
        user_id=execution.user_id,
        status=status,
        started_at=execution.started_at,
        completed_at=execution.completed_at,
        duration_seconds=execution.duration_seconds,
        conversation_id=execution.conversation_id,
        summary=execution.summary,
        error_message=execution.error_message,
        trigger_type=execution.trigger_type,
        trace=execution.trace,
    )


def playbook_for_task(playbook: LegacyPlaybook, workflow: LegacyWorkflow) -> TaskPlaybookDocument:
    """Re-key a playbook to its task and carry its validity across the change of fingerprint.

    A playbook valid today gets the hash of the task's body, which is the prompt it was
    valid for, so its next run replays it. A stale one keeps its old {prompt, steps} hash,
    which no body hash can equal, so it stays stale exactly as today.
    """
    body_hash = (
        task_body_hash(workflow.effective_prompt)
        if legacy_playbook_valid(playbook, workflow)
        else playbook.workflow_hash
    )
    return TaskPlaybookDocument(
        playbook_id=playbook.playbook_id,
        task_id=playbook.workflow_id,
        user_id=playbook.user_id,
        body_hash=body_hash,
        description=playbook.description,
        steps=playbook.steps,
        result_brief=playbook.result_brief,
        authored_run=playbook.authored_run,
        last_run_status=playbook.last_run_status,
        last_run_reason=playbook.last_run_reason,
        suspect_streak=playbook.suspect_streak,
        heal_attempts=playbook.heal_attempts,
        revision=playbook.revision,
        created_at=playbook.created_at,
        updated_at=playbook.updated_at,
    )
