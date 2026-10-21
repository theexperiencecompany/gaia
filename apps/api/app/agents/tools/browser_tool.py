"""The executor-facing browser-automation tool: start a run, told its ending once.

The "do you want me to use a browser?" confirmation is handled by the shared HIL
system (browser_task is registered destructive). This file owns only the turn's
half of a run: the settings and URL gates, the identity read off the run's
config, the enqueue, and how the ending reaches the executor. A run in a live
conversation runs in the background: the tool acks at once, its cards fold into
this turn's message, and its ending lands in the executor inbox (job_teller). A
headless run (a workflow's, a todo's) blocks here until the ending and returns it.
The run itself belongs to the ARQ worker, through app/services/browser/job_runner.py.
"""

from dataclasses import dataclass
from functools import partial
from typing import Annotated
import uuid

from langchain_core.runnables.config import RunnableConfig
from langchain_core.tools import InjectedToolCallId, tool
from pydantic import BaseModel, ConfigDict

from app.agents.core.background.redis_writer import publish_to_stream
from app.agents.core.subagents.delegation import runs_in_background
from app.constants.browser import (
    BROWSER_JOB_QUEUE,
    BROWSER_JOB_TASK,
    BrowserSessionStatus,
)
from app.constants.log_tags import LogTag
from app.decorators import with_doc, with_rate_limiting
from app.models.agent_models import agent_configurable
from app.models.chat_models import ConversationSource
from app.schemas.browser import BrowserResultSnapshot, BrowserTaskSecret
from app.schemas.browser_job import (
    BrowserJobFinished,
    BrowserJobRequest,
    BrowserJobState,
    BrowserJobStatus,
)
from app.services.browser.handoff import reply_address
from app.services.browser.jev.secrets import RunSecrets
from app.services.browser.job_relay import follow_job_cards, relay_job_cards
from app.services.browser.job_teller import ending_message
from app.services.browser.jobs import (
    claim_conversation_slot,
    done_state,
    put_job_state,
    record_ending,
    release_conversation_slot,
    restore_latest_job,
    set_latest_job,
)
from app.templates.docstrings.browser_tool_docs import BROWSER_TASK
from app.utils.redis_utils import RedisPoolManager
from app.utils.url_safety import assert_safe_url_shape
from app.workers.queue import enqueue_worker_job
from shared.py.wide_events import log, spawn_logged_task

# What the tool tells the model, one name per outcome: the reply is how the model
# learns which branch it landed in and what to do next.
_UNSAFE_START_URL = "I can't open {url}: {error}. Only public http(s) sites are reachable."
_SLOT_HELD = (
    "A browser task is already running in this conversation (job {holder}). Its result "
    "arrives on its own when it ends; do not start another browser task until then."
)
_NOT_QUEUED = "I couldn't start the browser task right now. Try again in a moment."
_STARTED = (
    "Browser task started in the background (job {job_id}). It has NOT finished: do not "
    "report an outcome, and do not wait for one. Its result arrives in your inbox as a "
    "<browser_result> message when it ends, and wakes you if you have already finished."
)
_NO_ENDING = (
    "The browser task (job {job_id}) stopped reporting before it recorded how it ended. "
    "Tell the user it could not be finished; do not claim any result."
)


@dataclass(frozen=True)
class _RunParams:
    """The run's identity and provenance, read once from the tool's config."""

    user_id: str
    conversation_id: str
    stream_id: str | None
    root_request_id: str | None
    source_category: str | None
    conversation_source: ConversationSource | None
    #: The message this turn renders into, which a background run's cards fold into.
    message_id: str | None
    in_background: bool


class _RunConfigurable(BaseModel):
    """The keys of the run's configurable this tool reads; the rest is the graph's."""

    model_config = ConfigDict(extra="ignore")

    user_id: str | None = None
    conversation_id: str | None = None
    thread_id: str | None = None
    stream_id: str | None = None
    root_request_id: str | None = None
    source_category: str | None = None
    conversation_source: str | None = None
    bot_message_id: str | None = None


def _run_params(config: RunnableConfig) -> _RunParams:
    configurable = _RunConfigurable.model_validate(config.get("configurable", {}))
    conv_source = ConversationSource.coerce(configurable.conversation_source)
    return _RunParams(
        user_id=configurable.user_id or "",
        # The USER-facing conversation, never the executor's derived thread_id
        # (executor_<conv>): a handoff is resolved by a chat reply arriving on the
        # comms conversation id, so a prefixed key would never match.
        conversation_id=configurable.conversation_id or configurable.thread_id or "",
        stream_id=configurable.stream_id,
        root_request_id=configurable.root_request_id,
        source_category=configurable.source_category,
        conversation_source=conv_source,
        message_id=configurable.bot_message_id,
        in_background=runs_in_background(True, agent_configurable(config)),
    )


def _job_request(
    params: _RunParams,
    job_id: str,
    tool_call_id: str,
    task: str,
    start_url: str | None,
    secrets: dict[str, BrowserTaskSecret],
) -> BrowserJobRequest:
    return BrowserJobRequest(
        secrets=secrets,
        job_id=job_id,
        tool_call_id=tool_call_id,
        user_id=params.user_id,
        conversation_id=params.conversation_id,
        task=task,
        in_background=params.in_background,
        start_url=start_url,
        stream_id=params.stream_id,
        message_id=params.message_id,
        root_request_id=params.root_request_id,
        source_category=params.source_category,
        conversation_source=params.conversation_source,
    )


@tool
@with_rate_limiting("browser_task")
@with_doc(BROWSER_TASK)
async def browser_task(
    config: RunnableConfig,
    tool_call_id: Annotated[str, InjectedToolCallId],
    task: Annotated[str, "Clear, self-contained description of what to do in the browser."],
    start_url: Annotated[
        str | None,
        "The page to open first. Pass it whenever the task names a site or page: the run "
        "starts there with the user's saved login for that site.",
    ] = None,
    secrets: Annotated[
        dict[str, BrowserTaskSecret] | None,
        "Credentials the user gave for this task (passwords, usernames of accounts), by a short "
        'name, each with the site it belongs to, e.g. {"password": {"value": "...", "site": '
        '"github.com"}}. Each is typed only on its site. In the task write <secret>name</secret> '
        "wherever one is used, never the value.",
    ] = None,
) -> str:
    """Start a browser run as a background job: ack at once, or block until it ends when headless.

    Claims the conversation's one browser slot and hands the run to the worker.
    """
    params = _run_params(config)
    log.set(
        browser={
            "operation": "task",
            "source_category": params.source_category,
            "in_background": params.in_background,
        }
    )

    if start_url:
        try:
            assert_safe_url_shape(start_url)
        except ValueError as exc:
            log.warning(
                f"{LogTag.BROWSER} Browser task refused: start URL is not a public http(s) site",
                error=str(exc),
            )
            return _UNSAFE_START_URL.format(url=start_url, error=exc)

    job_id = uuid.uuid4().hex
    holder = await claim_conversation_slot(params.conversation_id, job_id)
    if holder is not None:
        log.set_ns("browser", refused="slot_held", slot_holder=holder)
        return _SLOT_HELD.format(holder=holder)

    given = {name: secret for name, secret in (secrets or {}).items() if secret.value}
    # The task is the executor's own; a secret value it wrote is put back as its placeholder.
    task = RunSecrets(given).mask(task)
    request = _job_request(params, job_id, tool_call_id, task, start_url, given)
    await put_job_state(BrowserJobState.of(request, BrowserJobStatus.QUEUED))
    # Findable before a worker can take it, so a stop from the moment it is queued reaches it.
    # A bot run is also reached from the requester's bot chat: its handoffs are answered,
    # and a /stop lands, there.
    bot_chat = reply_address(params.conversation_id, params.user_id, params.conversation_source)
    replaced = {
        key: await set_latest_job(key, job_id)
        for key in dict.fromkeys([params.conversation_id, bot_chat])
    }
    if not await _enqueue(request):
        # A job that never ran must not hide the one before it from a /stop at the same chat.
        for key, previous in replaced.items():
            await restore_latest_job(key, job_id, previous)
        # Ended without running, told by this reply alone: nothing lands in the inbox.
        await record_ending(
            job_id,
            BrowserJobFinished(
                result=BrowserResultSnapshot(
                    status=BrowserSessionStatus.FAILED, success=False, summary=_NOT_QUEUED
                )
            ),
        )
        await release_conversation_slot(params.conversation_id, job_id)
        return _NOT_QUEUED

    log.set_ns("browser", job_id=job_id)
    if params.in_background:
        spawn_logged_task("browser_job_relay", relay_job_cards(request))
        return _STARTED.format(job_id=job_id)
    return await _await_ending(request)


async def _enqueue(request: BrowserJobRequest) -> bool:
    """Put the run on the worker queue; False when it did not get there.

    A browser run is not idempotent, so there is no in-process fallback: a run
    that cannot be queued has not started, and the user is told so.
    """
    try:
        pool = await RedisPoolManager.get_pool()
        job = await enqueue_worker_job(
            pool,
            BROWSER_JOB_TASK,
            request.model_dump(mode="json"),
            _queue_name=BROWSER_JOB_QUEUE,
            # The job's own id, so a stop can abort exactly this ARQ task.
            _job_id=request.job_id,
        )
    except Exception as exc:
        log.error(
            f"{LogTag.BROWSER} Could not enqueue the browser job",
            error_type=type(exc).__name__,
            error=str(exc),
            browser={"job_id": request.job_id},
        )
        return False
    if job is None:
        log.error(
            f"{LogTag.BROWSER} Browser job was not queued",
            browser={"job_id": request.job_id},
        )
        return False
    return True


async def _await_ending(request: BrowserJobRequest) -> str:
    """Block a headless run until its job ends, its cards on the run's own stream; return how it ended."""
    sink = partial(publish_to_stream, request.stream_id) if request.stream_id else _ignore
    await follow_job_cards(request.job_id, request.conversation_id, sink)
    ending = await done_state(request.job_id)
    if ending is None:
        log.error(
            f"{LogTag.BROWSER} Browser job feed closed with no ending recorded",
            browser={"job_id": request.job_id},
        )
        return _NO_ENDING.format(job_id=request.job_id)
    log.set_ns("browser", ending=ending.ending.value)
    return ending_message(request.job_id, ending)


async def _ignore(_card: dict[str, object]) -> None:
    """Drop a card: a headless run with no stream has nowhere to show it."""
