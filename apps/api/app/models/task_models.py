"""The task document: one record for a to-do the user does, or work GAIA does, once or on repeat.

A to-do (assignee user) is never run. A GAIA task runs from its body and notes. What brings
a task round is its `when`; the app events it listens to are its `subscriptions`, which a
GAIA task may carry beside any `when` (a dated thread task is also woken by the reply).
"""

from datetime import datetime
from typing import Annotated, Literal, Self
import uuid

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.constants.tasks import (
    TASK_ID_HEX_CHARS,
    TASK_ID_PREFIX,
    Assignee,
    TaskFlag,
    TaskRunState,
    ThresholdDirection,
    WatchEnd,
    WatchReading,
    WatchSourceRung,
    WatchTell,
    WatchTemplate,
    WhenKind,
)
from app.constants.todos import NoReplyPlan, WaitingOn
from app.models.document_models import UserScopedDocument
from app.models.scheduler_models import DeactivationReason
from app.models.todo_models import ExternalRef, Priority, SubTask, TodoDayWindow
from app.models.trigger_subscription_models import TriggerSubscription
from app.models.workflow_models import PlaybookDiscard


def new_task_id() -> str:
    return f"{TASK_ID_PREFIX}{uuid.uuid4().hex[:TASK_ID_HEX_CHARS]}"


# When.


class _WhenVariant(BaseModel):
    """A When variant whose kind always counts as set, so exclude_unset dumps keep the discriminator."""

    def model_post_init(self, _context: object, /) -> None:
        # Every partial $set and TaskDocument.updated_by dump with exclude_unset.
        self.__pydantic_fields_set__.add("kind")


class NoWhen(_WhenVariant):
    """Nothing brings the task round: an undated to-do, or GAIA work it runs when asked."""

    model_config = ConfigDict(frozen=True)

    kind: Literal[WhenKind.NONE] = WhenKind.NONE


class DateWhen(_WhenVariant):
    """Due at one moment: a to-do's due date, or the date a one-off GAIA task is due by."""

    model_config = ConfigDict(frozen=True)

    kind: Literal[WhenKind.DATE] = WhenKind.DATE
    at: datetime
    #: The zone the user picked the date in; None when they never picked one.
    timezone: str | None = None


class RepeatWhen(_WhenVariant):
    """Comes round on a schedule: a 5-field cron, or a shortcut (daily, weekly, every_4h, every_1h).

    The rule is checked where it is written, not here, so a stored schedule that breaks
    today's rule still loads and can be fixed (it is paused as invalid_schedule).
    """

    model_config = ConfigDict(frozen=True)

    kind: Literal[WhenKind.REPEAT] = WhenKind.REPEAT
    rule: str = Field(min_length=1)
    #: The zone the rule runs in; None runs it in the user's current zone.
    timezone: str | None = None
    #: The next occurrence: a GAIA task's next run, a to-do's next due time.
    next_run: datetime | None = None


class EventWhen(_WhenVariant):
    """Comes round only on the app events in the task's subscriptions."""

    model_config = ConfigDict(frozen=True)

    kind: Literal[WhenKind.EVENT] = WhenKind.EVENT


# Watches: the model picks the template and source once; code owns every check after it.


class WatchSource(BaseModel):
    """Where a watch reads its value, and how to read it there."""

    model_config = ConfigDict(frozen=True)

    rung: WatchSourceRung
    #: The tool, endpoint, feed or page the reading comes from.
    locator: str = Field(min_length=1)
    #: How the value is picked out of what the locator returns (a JSON path, a selector).
    extract: str | None = None
    #: The connected account a connector reading uses; None is the primary.
    account_id: str | None = None


class ThresholdCondition(BaseModel):
    model_config = ConfigDict(frozen=True)

    template: Literal[WatchTemplate.THRESHOLD] = WatchTemplate.THRESHOLD
    direction: ThresholdDirection
    value: float
    unit: str | None = None
    #: How far back past the threshold a value must go before the watch can fire again.
    rearm_band: float | None = Field(default=None, ge=0)


class StateCondition(BaseModel):
    model_config = ConfigDict(frozen=True)

    template: Literal[WatchTemplate.STATE] = WatchTemplate.STATE
    #: The states that fire the watch.
    states: list[str] = Field(min_length=1)
    #: States after which nothing can change any more; reaching one ends the watch.
    terminal_states: list[str] = Field(default_factory=list)


class NewItemsCondition(BaseModel):
    model_config = ConfigDict(frozen=True)

    template: Literal[WatchTemplate.NEW_ITEMS] = WatchTemplate.NEW_ITEMS
    #: The field that names one item, the dedupe key.
    item_key: str = Field(min_length=1)
    #: Plain-language filter an item must meet, judged per item.
    matching: str | None = None


class ReplyByCondition(BaseModel):
    model_config = ConfigDict(frozen=True)

    template: Literal[WatchTemplate.REPLY_BY] = WatchTemplate.REPLY_BY
    #: The thread or conversation a reply is awaited on.
    thread_ref: str = Field(min_length=1)
    deadline: datetime


class UptimeCondition(BaseModel):
    model_config = ConfigDict(frozen=True)

    template: Literal[WatchTemplate.UPTIME] = WatchTemplate.UPTIME
    url: str = Field(min_length=1)
    expected_status: int = 200


class OpenCondition(BaseModel):
    """No single source: a daily model check, promoted to a typed watch once a source appears."""

    model_config = ConfigDict(frozen=True)

    template: Literal[WatchTemplate.OPEN] = WatchTemplate.OPEN
    question: str = Field(min_length=1)
    daily_call_cap: int = Field(default=1, ge=1)


WatchCondition = Annotated[
    ThresholdCondition
    | StateCondition
    | NewItemsCondition
    | ReplyByCondition
    | UptimeCondition
    | OpenCondition,
    Field(discriminator="template"),
]


class WatchConfirm(BaseModel):
    """How many consecutive readings must agree, and how far apart, before the watch fires."""

    model_config = ConfigDict(frozen=True)

    readings: int = Field(default=1, ge=1)
    gap_seconds: int = Field(default=0, ge=0)


class WatchBlindEpisode(BaseModel):
    """The source cannot be read: why, since when, and whether the user was told."""

    reason: str = Field(min_length=1)
    since: datetime
    checks: int = Field(default=1, ge=1)
    told: bool = False


class WatchState(BaseModel):
    """What code knows of a watch between checks; written only by the check, never by a model."""

    last_reading: WatchReading | None = None
    last_value: str | None = None
    last_checked_at: datetime | None = None
    #: Consecutive readings that matched, toward the confirm count.
    matched_streak: int = Field(default=0, ge=0)
    blind: WatchBlindEpisode | None = None
    #: Keys of items or values already told, so one is never told twice.
    told_keys: list[str] = Field(default_factory=list)
    fired_at: datetime | None = None
    #: The watch stopped: it ended, expired, or paused after staying blind.
    ended_at: datetime | None = None


class Watch(BaseModel):
    """A change the user asked GAIA to tell them about, as GAIA compiled it from their sentence."""

    #: The user's own words.
    sentence: str = Field(min_length=1)
    condition: WatchCondition
    #: None only on an open watch.
    source: WatchSource | None = None
    tell: WatchTell = WatchTell.FIRST_MATCH
    confirm: WatchConfirm = Field(default_factory=WatchConfirm)
    until: WatchEnd = WatchEnd.FIRST_ALERT
    expires_at: datetime
    cadence_seconds: int = Field(ge=60)
    state: WatchState = Field(default_factory=WatchState)

    @model_validator(mode="after")
    def _source_matches_template(self) -> Self:
        is_open = self.condition.template is WatchTemplate.OPEN
        if is_open != (self.source is None):
            raise ValueError("an open watch has no source, and every other watch has one")
        return self


class WatchWhen(_WhenVariant):
    """Comes round when a watched value changes the way the user asked."""

    kind: Literal[WhenKind.WATCH] = WhenKind.WATCH
    watch: Watch


When = Annotated[
    NoWhen | DateWhen | RepeatWhen | EventWhen | WatchWhen, Field(discriminator="kind")
]


# What a one-off GAIA task waits on.


class WaitingQuestion(BaseModel):
    """What GAIA asked the user, and what it does if they never answer."""

    text: str = Field(min_length=1)
    if_no_reply: NoReplyPlan | None = None
    default_action: str | None = None
    #: Checks spent holding for the answer; a new question starts again at zero.
    hold_checks: int = Field(default=0, ge=0)


class Waiting(BaseModel):
    """What an open one-off GAIA task waits for until its next check."""

    on: WaitingOn
    question: WaitingQuestion | None = None

    @model_validator(mode="after")
    def _question_only_on_the_user(self) -> Self:
        if self.question is not None and self.on is not WaitingOn.USER:
            raise ValueError("only a task waiting on the user carries a question")
        return self


class TaskDocument(UserScopedDocument):
    """A task as stored in the tasks collection; its id is the string _id (task_, wf_ or a todo's)."""

    id: str = Field(default_factory=new_task_id)
    title: str = Field(min_length=1)
    body: str = ""
    assignee: Assignee
    priority: Priority = Priority.NONE
    completed: bool = False
    completed_at: datetime | None = None
    #: The checklist inside this task.
    subtasks: list[SubTask] = Field(default_factory=list)
    #: The task this one is a subtask of.
    parent_id: str | None = None
    when: When = Field(default_factory=NoWhen)
    #: When a one-off GAIA task next looks at its work; not its due date.
    next_check_at: datetime | None = None
    #: When a to-do's owed nudge goes out: its due time, or the end of the quiet hours it fell in.
    nudge_at: datetime | None = None
    subscriptions: list[TriggerSubscription] = Field(default_factory=list)

    # Liveness, kept apart from run state: an inactive task never runs.
    active: bool = True
    #: Why the system switched the task off; None with active=False means the user stopped it.
    pause_reason: DeactivationReason | None = None
    run_state: TaskRunState = TaskRunState.IDLE
    retry_count: int = Field(default=0, ge=0)
    waiting: Waiting | None = None
    #: Re-asks spent over the task's life; one per task, ever.
    reasks_used: int = Field(default=0, ge=0)
    status_flags: list[TaskFlag] = Field(default_factory=list)

    # GAIA's notes: canvas.md, observations.md and the system log.
    notes: str | None = None
    observations: str | None = None
    log: str | None = None

    #: The outside object this task is about; one open task per user per object.
    external_ref: ExternalRef | None = None
    source_conversation_id: str | None = None
    #: Ids of earlier tasks whose learnings this one reads.
    references: list[str] = Field(default_factory=list)
    expires_at: datetime | None = None
    #: The sender of the email an onboarding-seeded task was drawn from.
    source_email: str | None = None
    #: Seeded during onboarding, so an onboarding reset removes it.
    from_onboarding: bool = False

    icon: str | None = Field(default=None, max_length=64)
    icon_color: str | None = Field(default=None, pattern=r"^#[0-9a-fA-F]{6}$")
    #: Whether a run's result is sent to the user.
    notify: bool = True
    #: Apps the task uses, picked by the user or read from their intent.
    integration_ids: list[str] = Field(default_factory=list)
    #: What a blocked run named as missing when it paused the task.
    blocked_on_integrations: list[str] = Field(default_factory=list)

    # Run limits and counters.
    max_occurrences: int | None = Field(default=None, gt=0)
    stop_after: datetime | None = None
    occurrence_count: int = Field(default=0, ge=0)
    total_runs: int = Field(default=0, ge=0)
    successful_runs: int = Field(default=0, ge=0)
    last_run_at: datetime | None = None
    last_playbook_discard: PlaybookDiscard | None = None

    #: Links a system task to its definition in code; unique per user.
    system_key: str | None = None
    #: The app whose connection set the task up.
    source_integration: str | None = None

    created_at: datetime | None = None
    updated_at: datetime | None = None

    @model_validator(mode="after")
    def _a_todo_carries_no_gaia_state(self) -> Self:
        if self.assignee is Assignee.GAIA:
            return self
        held = [name for name, value in self._gaia_only_values().items() if value]
        if held:
            raise ValueError(f"a to-do is never run, so it holds no {', '.join(held)}")
        return self

    @model_validator(mode="after")
    def _a_repeating_task_never_waits(self) -> Self:
        if self.when.kind is WhenKind.REPEAT and (
            self.waiting is not None or self.next_check_at is not None
        ):
            raise ValueError("a repeating task never waits; its next run is its schedule")
        return self

    @model_validator(mode="after")
    def _an_event_task_has_events(self) -> Self:
        if self.when.kind is WhenKind.EVENT and not self.subscriptions:
            raise ValueError("an event task needs at least one subscription")
        return self

    @model_validator(mode="after")
    def _a_system_pause_is_off(self) -> Self:
        if self.pause_reason is not None and self.active:
            raise ValueError("a task the system paused is not active")
        return self

    def updated_by(self, update: "TaskUpdate") -> "TaskDocument":
        """Return the task as it reads once update is written, validated like a stored one."""
        return TaskDocument.model_validate(
            {**self.model_dump(), **update.model_dump(exclude_unset=True)}
        )

    def _gaia_only_values(self) -> dict[str, object]:
        return {
            "watch": self.when.kind is WhenKind.WATCH,
            "next_check_at": self.next_check_at,
            "subscriptions": self.subscriptions,
            "pause_reason": self.pause_reason,
            "run_state": self.run_state is not TaskRunState.IDLE,
            "retry_count": self.retry_count,
            "waiting": self.waiting,
            "reasks_used": self.reasks_used,
            "notes": self.notes,
            "observations": self.observations,
            "log": self.log,
            "integration_ids": self.integration_ids,
            "blocked_on_integrations": self.blocked_on_integrations,
            "total_runs": self.total_runs,
            "last_run_at": self.last_run_at,
            "last_playbook_discard": self.last_playbook_discard,
            "system_key": self.system_key,
        }


class TaskUpdate(BaseModel):
    """Partial $set for a task: every field a write may change, all optional."""

    model_config = ConfigDict(extra="forbid")

    title: str | None = None
    body: str | None = None
    priority: Priority | None = None
    completed: bool | None = None
    completed_at: datetime | None = None
    subtasks: list[SubTask] | None = None
    parent_id: str | None = None
    when: When | None = None
    next_check_at: datetime | None = None
    nudge_at: datetime | None = None
    subscriptions: list[TriggerSubscription] | None = None
    active: bool | None = None
    pause_reason: DeactivationReason | None = None
    run_state: TaskRunState | None = None
    retry_count: int | None = None
    waiting: Waiting | None = None
    reasks_used: int | None = None
    status_flags: list[TaskFlag] | None = None
    notes: str | None = None
    observations: str | None = None
    log: str | None = None
    source_conversation_id: str | None = None
    references: list[str] | None = None
    expires_at: datetime | None = None
    icon: str | None = None
    icon_color: str | None = None
    notify: bool | None = None
    integration_ids: list[str] | None = None
    blocked_on_integrations: list[str] | None = None
    max_occurrences: int | None = None
    stop_after: datetime | None = None
    occurrence_count: int | None = None
    last_playbook_discard: PlaybookDiscard | None = None


class TaskPage(BaseModel):
    """A page of tasks plus the unpaginated total for the same filter."""

    items: list[TaskDocument] = Field(default_factory=list)
    total: int = 0


class TaskCounts(BaseModel):
    """The sidebar counts of a user's open tasks."""

    today: int = 0
    upcoming: int = 0
    overdue: int = 0
    completed: int = 0


class OpenSubtaskCount(BaseModel):
    """One $group row: a parent (its _id) with the number of its open subtasks."""

    parent_id: str = Field(validation_alias="_id")
    count: int


class TaskQuery(BaseModel):
    """One list read's filter and page; every field narrows, none widens."""

    model_config = ConfigDict(frozen=True)

    q: str | None = None
    assignee: Assignee | None = None
    completed: bool | None = None
    priority: Priority | None = None
    parent_id: str | None = None
    top_level: bool = False
    has_due: bool | None = None
    overdue: bool = False
    due_after: datetime | None = None
    due_before: datetime | None = None
    flags: list[TaskFlag] = Field(default_factory=list)
    #: The user's day; the overdue filter reads its start.
    day_window: TodoDayWindow | None = None
    page: int = Field(default=1, ge=1)
    per_page: int = Field(default=50, ge=1, le=100)
