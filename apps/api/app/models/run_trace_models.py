"""The executor run trace: one run, the calls it made, and each call's full input and output."""

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict

from app.db.repositories.base import UserScopedDocument


class RunState(StrEnum):
    """Where an executor run stands; only RUNNING is ever reaped."""

    RUNNING = "running"
    PAUSED = "paused"
    FINISHED = "finished"
    FAILED = "failed"
    CANCELLED = "cancelled"
    ABANDONED = "abandoned"


class CallEffect(StrEnum):
    """Whether a tool only reads or changes something outside GAIA; unclassified counts as a write."""

    READ = "read"
    WRITE = "write"


class CallStatus(StrEnum):
    OK = "ok"
    ERROR = "error"


class RunDocument(UserScopedDocument):
    """One executor run. todo_id is set when the run belongs to a tracked todo, else it is a hidden record."""

    run_id: str
    conversation_id: str
    todo_id: str | None = None
    #: The run that dispatched this one; None for a top-level run.
    parent_run_id: str | None = None
    state: RunState
    started_at: datetime
    last_activity_at: datetime
    finished_at: datetime | None = None
    #: Calls finished up to here are already in the todo's activity log.
    activity_logged_through: datetime | None = None
    created_at: datetime | None = None


class RunUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    state: RunState | None = None
    last_activity_at: datetime | None = None
    finished_at: datetime | None = None
    activity_logged_through: datetime | None = None


class RunCallDocument(UserScopedDocument):
    """One tool call of a run; its full input and output live in the payload at payload_ref."""

    run_id: str
    call_id: str
    tool_call_id: str | None = None
    tool_name: str
    effect: CallEffect
    status: CallStatus
    started_at: datetime
    finished_at: datetime
    summary: str
    payload_ref: str
    created_at: datetime | None = None


class CallPayloadDocument(UserScopedDocument):
    """What a call was given and returned, as text; cut at the bound and flagged when it was longer."""

    input_json: str
    output_text: str
    truncated: bool = False
    created_at: datetime | None = None
