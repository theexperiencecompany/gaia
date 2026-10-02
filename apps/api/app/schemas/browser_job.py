"""Payload and durable state for a browser task running as a background ARQ job.

The request crosses the ARQ queue as JSON and is re-validated in the worker; the
state crosses Redis and is what a joiner (or a restarted API) reads to answer
"is it still running, and what did it say?".
"""

from enum import StrEnum

from pydantic import BaseModel, Field

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
    start_url: str | None = None
    stream_id: str | None = None
    root_request_id: str | None = None
    source_category: str | None = None
    conversation_source: ConversationSource | None = None
    #: Credentials the user gave for the task, by the name the task's <secret>name</secret> uses.
    secrets: dict[str, BrowserTaskSecret] = Field(default_factory=dict)


class BrowserJobStatus(StrEnum):
    """Where the job is: queued, running in the worker, or finished."""

    QUEUED = "queued"
    RUNNING = "running"
    DONE = "done"


class BrowserJobState(BaseModel):
    """The job's durable state: what a joiner reads and what a restart recovers."""

    job_id: str
    status: BrowserJobStatus
    task: str
    #: The stream the turn that started the job relays its cards to.
    relay_stream_id: str | None = None
    #: The executor-facing guidance string (agent_result_message), set at terminal.
    agent_message: str = ""
    result: BrowserResultSnapshot | None = None
