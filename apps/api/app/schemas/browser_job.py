"""Payload, live state and terminal record of a browser task running as a background ARQ job.

The request crosses the ARQ queue as JSON and is re-validated in the worker. The
state says a job is queued or running and who it answers to; the ending record
is the one place a job's end lives, its result with it.
"""

from enum import StrEnum
from typing import Annotated, Literal, Self

from pydantic import BaseModel, Field, TypeAdapter

from app.constants.browser import JobEnding
from app.models.chat_models import ConversationSource
from app.schemas.browser import BrowserResultSnapshot, BrowserTaskSecret


class BrowserJobRequest(BaseModel):
    """Everything the worker needs to run one browser task on behalf of a turn."""

    job_id: str
    #: The browser_task call that started the run; the run's thread group is keyed by it.
    tool_call_id: str
    user_id: str
    conversation_id: str
    task: str
    #: Decided at enqueue: True lands the ending in the executor inbox, False has
    #: the starting tool call (a workflow's, a todo's) block until the ending.
    in_background: bool
    start_url: str | None = None
    stream_id: str | None = None
    root_request_id: str | None = None
    source_category: str | None = None
    conversation_source: ConversationSource | None = None
    #: Credentials the user gave for the task, by the name the task's <secret>name</secret> uses.
    secrets: dict[str, BrowserTaskSecret] = Field(default_factory=dict)


class BrowserJobStatus(StrEnum):
    """Where a job that has not ended is: waiting for a worker, or running in one."""

    QUEUED = "queued"
    RUNNING = "running"


class BrowserJobState(BaseModel):
    """A job that has not ended: where it is, and who its ending is told to."""

    job_id: str
    status: BrowserJobStatus
    task: str
    conversation_id: str
    user_id: str
    in_background: bool

    @classmethod
    def of(cls, request: BrowserJobRequest, status: BrowserJobStatus) -> Self:
        """Return the state of the job request asks for, at status."""
        return cls(
            job_id=request.job_id,
            status=status,
            task=request.task,
            conversation_id=request.conversation_id,
            user_id=request.user_id,
            in_background=request.in_background,
        )


class BrowserJobFinished(BaseModel):
    """The run ended first, on result: that result is the one the user hears."""

    ending: Literal[JobEnding.FINISHED] = JobEnding.FINISHED
    result: BrowserResultSnapshot


class BrowserJobStopped(BaseModel):
    """A stop was recorded first: the stop told the user, and the run's result is dropped."""

    ending: Literal[JobEnding.STOPPED] = JobEnding.STOPPED


#: The job's one terminal record: written once, by whoever ends it first.
BrowserJobEnding = Annotated[BrowserJobFinished | BrowserJobStopped, Field(discriminator="ending")]
BROWSER_JOB_ENDING: TypeAdapter[BrowserJobEnding] = TypeAdapter(BrowserJobEnding)
