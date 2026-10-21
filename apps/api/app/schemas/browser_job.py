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
    #: The message of the turn that started the job, which its cards fold into.
    message_id: str | None = None
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
    """A job that has not ended: where it is, and the request it runs, secrets withheld.

    Kept so whoever ends the job (the run, a stop, the reaper) can tell its
    ending where the run would have: its conversation, its cards, its bot chat.
    """

    status: BrowserJobStatus
    request: BrowserJobRequest
    #: Epoch seconds the run started at, for a card a reaper closes; None while queued.
    running_since: float | None = None

    @classmethod
    def of(
        cls,
        request: BrowserJobRequest,
        status: BrowserJobStatus,
        running_since: float | None = None,
    ) -> Self:
        """Return the state of the job request asks for, at status; its secrets never reach Redis."""
        return cls(
            status=status,
            request=request.model_copy(update={"secrets": {}}),
            running_since=running_since,
        )

    @property
    def job_id(self) -> str:
        return self.request.job_id

    @property
    def task(self) -> str:
        return self.request.task

    @property
    def conversation_id(self) -> str:
        return self.request.conversation_id

    @property
    def user_id(self) -> str:
        return self.request.user_id

    @property
    def in_background(self) -> bool:
        return self.request.in_background


class BrowserJobWake(BaseModel):
    """A finished background job whose result waits in the executor inbox for a run to tell it.

    Recorded with the landing, and kept until that entry is read, so a worker
    that died before waking anyone is made good by the next sweep.
    """

    job_id: str
    conversation_id: str
    user_id: str
    #: The inbox entry that tells the result; once it is gone, it was told.
    entry_id: str
    #: Epoch seconds it landed at: a sweep leaves a fresh one to the run reading it now.
    landed_at: float


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
