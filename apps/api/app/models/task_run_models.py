"""task_runs: one record per run of a GAIA task, plus a migrated todo's timeline between runs."""

from datetime import datetime
from typing import Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.constants.tasks import TaskRunKind, TaskRunStatus
from app.db.repositories.base import MongoDocument
from app.models.workflow_execution_models import RecordedCall


class ImportedActivity(BaseModel):
    """The slice of a todo's activity.md a record was cut from, verbatim, and its place in it.

    Joining every slice of one task in seq order gives back its activity.md byte for byte.
    """

    model_config = ConfigDict(frozen=True)

    seq: int = Field(ge=0)
    text: str


class TaskRunDocument(MongoDocument):
    """One run of a GAIA task, keyed by its business id run_id; Mongo's _id is incidental."""

    run_id: str
    task_id: str
    user_id: str
    kind: TaskRunKind = TaskRunKind.RUN
    #: None only on a history record, which was no run.
    status: TaskRunStatus | None = TaskRunStatus.RUNNING
    started_at: datetime
    completed_at: datetime | None = None
    duration_seconds: float | None = None
    conversation_id: str | None = None
    summary: str | None = None
    error_message: str | None = None
    #: What started the run: manual, schedule, an app event's trigger name, or imported_activity.
    trigger_type: str
    #: What the run did, in order; the next run reads it as what came before.
    trace: list[RecordedCall] = Field(default_factory=list)
    imported: ImportedActivity | None = None

    @model_validator(mode="after")
    def _history_is_no_run(self) -> Self:
        if (self.kind is TaskRunKind.HISTORY) != (self.status is None):
            raise ValueError("a history record has no status, and a run always has one")
        if self.kind is TaskRunKind.HISTORY and self.imported is None:
            raise ValueError("only an imported activity log has history records")
        return self


class TaskRunUpdate(BaseModel):
    """Partial $set for a run: the completion fields."""

    model_config = ConfigDict(extra="forbid")

    status: TaskRunStatus | None = None
    completed_at: datetime | None = None
    duration_seconds: float | None = None
    summary: str | None = None
    error_message: str | None = None
    conversation_id: str | None = None
    trace: list[RecordedCall] | None = None
