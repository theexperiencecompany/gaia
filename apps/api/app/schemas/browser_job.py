"""Payload and durable state for a browser task running as a background ARQ job.

The request crosses the ARQ queue as JSON and is re-validated in the worker; the
state crosses Redis and is what a joiner (or a restarted API) reads to answer
"is it still running, and what did it say?".
"""

from enum import StrEnum
from urllib.parse import urlsplit

from pydantic import BaseModel, Field, field_validator

from app.models.chat_models import ConversationSource
from app.schemas.browser import BrowserResultSnapshot


class BrowserTaskSecret(BaseModel):
    """One credential the user gave for a task, and the one site it may be typed on."""

    value: str = Field(description="The credential exactly as the user gave it.")
    site: str = Field(
        description="The site it belongs to, e.g. github.com: it is typed only there and on "
        "its subdomains."
    )

    @field_validator("site")
    @classmethod
    def _host(cls, site: str) -> str:
        """Keep the site's host alone, without www.; a site naming no host is refused."""
        host = urlsplit(site if "://" in site else f"https://{site}").hostname
        if not host:
            raise ValueError(f"{site!r} names no site")
        return host.removeprefix("www.")


class BrowserJobRequest(BaseModel):
    """Everything the worker needs to run one browser task on behalf of a turn."""

    job_id: str
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
    session_id: str | None = None
    live_view_url: str | None = None
    #: The executor-facing guidance string (agent_result_message), set at terminal.
    agent_message: str | None = None
    result: BrowserResultSnapshot | None = None
