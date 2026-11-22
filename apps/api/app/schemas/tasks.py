"""The /tasks API: what a client sends to make or change a task, and what it reads back."""

from datetime import datetime
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field

from app.constants.general import MAX_PAGE_NUMBER
from app.constants.tasks import Assignee, TaskFlag, TaskRunKind, TaskRunState, TaskRunStatus
from app.models.scheduler_models import DeactivationReason
from app.models.task_models import (
    DateWhen,
    NoWhen,
    RepeatWhen,
    TaskDocument,
    TaskQuery,
    Waiting,
    When,
)
from app.models.task_run_models import TaskRunDocument
from app.models.todo_models import (
    ExternalRef,
    PendingApprovalRef,
    Priority,
    SubTask,
    TodoDayWindow,
)
from app.models.trigger_subscription_models import TriggerSubscriptionView
from app.schemas.common import ResponseModel

#: What brings a to-do round: nothing, its date, or its repeat.
TodoWhen = Annotated[NoWhen | DateWhen | RepeatWhen, Field(discriminator="kind")]


class TaskCreateRequest(BaseModel):
    """A task the user makes from the app or a chat app; GAIA's own tasks come from its tools."""

    model_config = ConfigDict(extra="forbid")

    title: str = Field(min_length=1, max_length=500)
    body: str = Field(default="", max_length=20_000)
    priority: Priority = Priority.NONE
    when: TodoWhen | None = Field(default=None, description="A date, a repeat, or nothing")
    subtasks: list[SubTask] = Field(default_factory=list)
    parent_id: str | None = None
    notify: bool = Field(default=True, description="Whether the user is told when it comes due")


class TaskUpdateRequest(BaseModel):
    """A partial edit: a field left out stays as it is."""

    model_config = ConfigDict(extra="forbid")

    title: str | None = Field(default=None, min_length=1, max_length=500)
    body: str | None = Field(default=None, max_length=20_000)
    priority: Priority | None = None
    completed: bool | None = None
    when: TodoWhen | None = None
    notify: bool | None = None


class TaskListParams(BaseModel):
    """The query string of GET /tasks, bound with Depends() so each field is its own param."""

    model_config = ConfigDict(frozen=True)

    q: str | None = Field(default=None, description="Text the title or body contains")
    assignee: Assignee | None = None
    completed: bool | None = None
    priority: Priority | None = None
    parent_id: str | None = Field(default=None, description="Only the subtasks of this task")
    top_level: bool = Field(default=False, description="Only tasks that are no one's subtask")
    has_due: bool | None = None
    overdue: bool = False
    due_after: datetime | None = None
    due_before: datetime | None = None
    flag: TaskFlag | None = None
    page: int = Field(default=1, ge=1, le=MAX_PAGE_NUMBER)
    per_page: int = Field(default=50, ge=1, le=100)

    def to_query(self, window: TodoDayWindow) -> TaskQuery:
        return TaskQuery(
            **self.model_dump(exclude={"flag"}),
            flags=[self.flag] if self.flag is not None else [],
            day_window=window,
        )


class ChecklistItemCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str = Field(min_length=1, max_length=500)


class ChecklistItemUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str | None = Field(default=None, min_length=1, max_length=500)
    completed: bool | None = None


class TaskIdsRequest(BaseModel):
    """The tasks a bulk action applies to."""

    model_config = ConfigDict(extra="forbid")

    task_ids: list[str] = Field(min_length=1, max_length=100)


class TaskResponse(ResponseModel):
    """A task as the list and its side panel show it."""

    id: str
    title: str
    body: str
    assignee: Assignee
    priority: Priority
    completed: bool
    completed_at: datetime | None
    subtasks: list[SubTask]
    parent_id: str | None
    open_subtask_count: int = Field(description="Open tasks filed under this one")
    when: When
    next_check_at: datetime | None = Field(description="When GAIA next looks at a one-off task")
    subscriptions: list[TriggerSubscriptionView]
    active: bool
    pause_reason: DeactivationReason | None = Field(
        description="Why the system switched it off; none when the user stopped it"
    )
    run_state: TaskRunState
    waiting: Waiting | None
    pending_approval: PendingApprovalRef | None = Field(
        description="The oldest live approval a run of this GAIA task waits on"
    )
    status_flags: list[TaskFlag]
    notify: bool
    external_ref: ExternalRef | None
    expires_at: datetime | None
    icon: str | None
    icon_color: str | None
    integration_ids: list[str]
    missing_integrations: list[str] = Field(description="Apps the task uses that are not connected")
    total_runs: int
    successful_runs: int
    last_run_at: datetime | None
    system_key: str | None
    source_integration: str | None
    created_at: datetime | None
    updated_at: datetime | None

    @classmethod
    def from_document(
        cls,
        task: TaskDocument,
        *,
        open_subtask_count: int,
        connected: set[str],
        pending_approval: PendingApprovalRef | None,
    ) -> "TaskResponse":
        return cls(
            **task.model_dump(
                include=set(cls.model_fields)
                - {"subscriptions", "missing_integrations"}
                - {"open_subtask_count", "pending_approval"}
            ),
            subscriptions=[
                TriggerSubscriptionView.model_validate(sub.model_dump())
                for sub in task.subscriptions
            ],
            open_subtask_count=open_subtask_count,
            pending_approval=pending_approval,
            missing_integrations=[i for i in task.integration_ids if i not in connected],
        )


class TaskRunResponse(ResponseModel):
    """One run of a GAIA task as its Runs tab lists it, or a migrated stretch of its old log."""

    run_id: str
    kind: TaskRunKind
    status: TaskRunStatus | None
    started_at: datetime
    completed_at: datetime | None
    duration_seconds: float | None
    trigger_type: str
    summary: str | None
    error_message: str | None
    conversation_id: str | None
    #: What became of the run's result: sent on a chat app, in the app, or why it was not.
    delivery: str | None
    #: The old activity log's lines for this stretch, verbatim, on a migrated record.
    log_text: str | None

    @classmethod
    def from_document(cls, run: TaskRunDocument) -> "TaskRunResponse":
        return cls(
            **run.model_dump(include=set(cls.model_fields) - {"log_text"}),
            log_text=run.imported.text if run.imported else None,
        )


class TaskRunListResponse(ResponseModel):
    runs: list[TaskRunResponse]
    total: int


class TaskChatResponse(ResponseModel):
    """The chat a GAIA task's runs execute in, opened from the task."""

    conversation_id: str


class TaskNotesResponse(ResponseModel):
    """GAIA's notes on a task: what it keeps (notes), what it noticed, and the system log."""

    notes: str
    observations: str
    log: str


class TaskListResponse(ResponseModel):
    tasks: list[TaskResponse]
    total: int
    page: int
    per_page: int


class TaskCountsResponse(ResponseModel):
    today: int
    upcoming: int
    overdue: int
    completed: int


class TaskBulkResponse(ResponseModel):
    """Which of the requested tasks a bulk action changed, and which it could not find."""

    succeeded: list[str]
    not_found: list[str]
