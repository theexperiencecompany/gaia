"""The stored shapes of todos, workflows, executions and playbooks, frozen for the move to tasks.

The app's own models for these collections are deleted once tasks replace them, while
this migration still has to read the documents. So the migration owns a snapshot of
exactly the fields it reads, with the same read-time rules the app applied: a workflow's
prompt falls back to its description, legacy null text reads as empty, ISO-string dates
become UTC datetimes. The playbook fingerprint is frozen here for the same reason.
"""

from collections.abc import Mapping
from datetime import UTC, datetime
from enum import StrEnum
import hashlib
import json
from typing import Any, Final

from bson import ObjectId
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.constants.tasks import NoReplyPlan, TaskFlag, WaitingOn
from app.models.playbook_models import PlaybookRunStatus, PlaybookStep
from app.models.scheduler_models import DeactivationReason
from app.models.task_models import ExternalRef, Priority, SubTask
from app.models.trigger_gate_models import TriggerGate
from app.models.trigger_subscription_models import TriggerSubscription, TriggerSubscriptionStatus
from app.models.workflow_execution_models import RecordedCall
from app.models.workflow_models import PlaybookDiscard

#: The label that made a todo GAIA's.
GAIA_TRACKED_LABEL: Final = "gaia-tracked"
#: The label that marked a todo seeded during onboarding.
ONBOARDING_LABEL: Final = "onboarding"
#: The one system label nothing ever wrote or read; it is dropped with the user labels.
DROPPED_SYSTEM_LABELS: Final = frozenset({"needs-follow-up"})
#: Every system label the engine still reads, and the flag it becomes.
LABEL_FLAGS: Final[dict[str, TaskFlag]] = {
    "failed": TaskFlag.FAILED,
    "blocked": TaskFlag.BLOCKED,
    "waiting-for-reply": TaskFlag.WAITING_FOR_REPLY,
    "waiting-for-approval": TaskFlag.WAITING_FOR_APPROVAL,
    "needs-reply": TaskFlag.NEEDS_REPLY,
    "action-needed": TaskFlag.ACTION_NEEDED,
}


class LegacyTriggerType(StrEnum):
    MANUAL = "manual"
    SCHEDULE = "schedule"
    INTEGRATION = "integration"


class LegacyRunState(StrEnum):
    """The run-state values a workflow may hold since the liveness migration."""

    SCHEDULED = "scheduled"
    EXECUTING = "executing"
    COMPLETED = "completed"


def as_utc(value: object) -> object:
    """Read a stored date as an aware UTC datetime: naive BSON dates and ISO strings both occur."""
    if isinstance(value, str):
        value = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if isinstance(value, datetime) and value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value


class _Legacy(BaseModel):
    model_config = ConfigDict(extra="ignore", populate_by_name=True)


def with_stable_defaults(raw: Mapping[str, object]) -> dict[str, object]:
    """Give a todo's subtasks and subscriptions the defaults old writes left out, made stable.

    A subtask with no created_at and a subscription with no id, status or created_at load
    today with a fresh uuid and the current time, so two reads differ. The todo's own
    creation time and a position-derived id stand in, so every run maps them the same way.
    """
    todo_id = str(raw["_id"])
    made = raw.get("created_at") or ObjectId(todo_id).generation_time
    subtasks = [
        {**sub, "created_at": sub.get("created_at") or made}
        for sub in _mappings(raw.get("subtasks"))
    ]
    subscriptions = [
        {
            **sub,
            "id": sub.get("id") or f"{todo_id}:subscription{index}",
            "status": sub.get("status") or TriggerSubscriptionStatus.ACTIVE.value,
            "created_at": sub.get("created_at") or made,
        }
        for index, sub in enumerate(_mappings(raw.get("trigger_subscriptions")))
    ]
    return {**raw, "subtasks": subtasks, "trigger_subscriptions": subscriptions}


def _mappings(value: object) -> list[Mapping[str, object]]:
    return [item for item in value if isinstance(item, Mapping)] if isinstance(value, list) else []


class LegacyTodo(_Legacy):
    id: str = Field(alias="_id")
    user_id: str
    title: str
    description: str | None = None
    labels: list[str] = Field(default_factory=list)
    due_date: datetime | None = None
    due_date_timezone: str | None = None
    priority: Priority = Priority.NONE
    completed: bool = False
    completed_at: datetime | None = None
    subtasks: list[SubTask] = Field(default_factory=list)
    workflow_id: str | None = None
    scheduled_at: datetime | None = None
    recurrence: str | None = None
    gaia_retry_count: int = 0
    expires_at: datetime | None = None
    references: list[str] = Field(default_factory=list)
    parent_todo_id: str | None = None
    notify_on_run: bool = True
    pause_reason: DeactivationReason | None = None
    waiting_on: WaitingOn | None = None
    question: str | None = None
    if_no_reply: NoReplyPlan | None = None
    default_action: str | None = None
    reasks_used: int = 0
    hold_checks: int = 0
    canvas_content: str | None = None
    activity_content: str | None = None
    observations_content: str | None = None
    log_content: str | None = None
    trigger_subscriptions: list[TriggerSubscription] = Field(default_factory=list)
    source_email: str | None = None
    source_conversation_id: str | None = None
    external_ref: ExternalRef | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None

    @model_validator(mode="before")
    @classmethod
    def _stable_defaults(cls, data: object) -> object:
        return with_stable_defaults(data) if isinstance(data, Mapping) else data

    @field_validator("id", mode="before")
    @classmethod
    def _object_id_as_text(cls, value: object) -> object:
        return str(value) if isinstance(value, ObjectId) else value

    @field_validator(
        "due_date",
        "completed_at",
        "scheduled_at",
        "expires_at",
        "created_at",
        "updated_at",
        mode="before",
    )
    @classmethod
    def _utc(cls, value: object) -> object:
        return as_utc(value)

    @property
    def by_gaia(self) -> bool:
        return GAIA_TRACKED_LABEL in self.labels


class LegacyStep(_Legacy):
    """A workflow step exactly as the old fingerprint dumped it."""

    model_config = ConfigDict(extra="ignore")

    id: str = ""
    title: str
    category: str = "general"
    description: str


class LegacyTriggerConfig(_Legacy):
    type: str
    enabled: bool = True
    trigger_name: str | None = None
    trigger_data: dict[str, Any] | None = None
    composio_trigger_ids: list[str] | None = None
    cron_expression: str | None = None
    timezone: str | None = None
    next_run: datetime | None = None

    @field_validator("next_run", mode="before")
    @classmethod
    def _utc(cls, value: object) -> object:
        return as_utc(value)


class LegacyWorkflow(_Legacy):
    id: str = Field(alias="_id")
    user_id: str
    title: str
    description: str = ""
    prompt: str = ""
    icon: str | None = None
    icon_color: str | None = None
    steps: list[LegacyStep] = Field(default_factory=list)
    trigger_config: LegacyTriggerConfig
    gate: TriggerGate | None = None
    activated: bool = True
    deactivated_reason: DeactivationReason | None = None
    notify_on_completion: bool = True
    last_executed_at: datetime | None = None
    is_public: bool = False
    is_explore: bool = False
    slug: str | None = None
    created_by: str | None = None
    total_executions: int = 0
    successful_executions: int = 0
    is_todo_workflow: bool = False
    source_todo_id: str | None = None
    is_system_workflow: bool = False
    source_integration: str | None = None
    system_workflow_key: str | None = None
    integration_ids: list[str] = Field(default_factory=list)
    blocked_on_integrations: list[str] = Field(default_factory=list)
    last_playbook_discard: PlaybookDiscard | None = None
    status: str = LegacyRunState.SCHEDULED.value
    occurrence_count: int = 0
    max_occurrences: int | None = None
    stop_after: datetime | None = None
    scheduled_at: datetime | None = None
    use_case_categories: list[str] = Field(default_factory=lambda: ["featured"])
    created_at: datetime
    updated_at: datetime

    @field_validator("description", "prompt", mode="before")
    @classmethod
    def _null_text_is_empty(cls, value: object) -> object:
        return "" if value is None else value

    @field_validator(
        "last_executed_at", "stop_after", "scheduled_at", "created_at", "updated_at", mode="before"
    )
    @classmethod
    def _utc(cls, value: object) -> object:
        return as_utc(value)

    @property
    def effective_prompt(self) -> str:
        """The prompt a run executed: a legacy record with none ran on its description."""
        return self.prompt or self.description

    @property
    def is_community(self) -> bool:
        return self.is_public and not self.is_explore


class LegacyExecution(_Legacy):
    execution_id: str
    workflow_id: str
    user_id: str
    status: str
    started_at: datetime
    completed_at: datetime | None = None
    duration_seconds: float | None = None
    conversation_id: str | None = None
    summary: str | None = None
    error_message: str | None = None
    trigger_type: str = "manual"
    trace: list[RecordedCall] = Field(default_factory=list)

    @field_validator("started_at", "completed_at", mode="before")
    @classmethod
    def _utc(cls, value: object) -> object:
        return as_utc(value)


class LegacyPlaybook(_Legacy):
    playbook_id: str
    workflow_id: str
    user_id: str
    workflow_hash: str
    description: str
    steps: list[PlaybookStep]
    result_brief: str
    authored_run: str | None = None
    last_run_status: PlaybookRunStatus = PlaybookRunStatus.NOT_RUN
    last_run_reason: str | None = None
    suspect_streak: int = 0
    heal_attempts: int = 0
    revision: int = 0
    created_at: datetime
    updated_at: datetime

    @field_validator("created_at", "updated_at", mode="before")
    @classmethod
    def _utc(cls, value: object) -> object:
        return as_utc(value)


def legacy_workflow_hash(prompt: str, steps: list[LegacyStep]) -> str:
    """The fingerprint a legacy playbook was valid under: sha256 of {prompt, steps} as compact JSON."""
    payload = json.dumps(
        {"prompt": prompt, "steps": [step.model_dump(mode="json") for step in steps]},
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode()).hexdigest()


def legacy_playbook_valid(playbook: LegacyPlaybook, workflow: LegacyWorkflow) -> bool:
    """Whether today's worker would replay this playbook on the workflow's next run."""
    return playbook.workflow_hash == legacy_workflow_hash(workflow.effective_prompt, workflow.steps)
