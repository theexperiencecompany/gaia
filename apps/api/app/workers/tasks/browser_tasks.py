"""The ARQ task that runs one browser job.

The run itself is the job runner's; this owns what only a worker can own: the
slot heartbeat that says the run is really alive, the terminal state a joiner
reads, and the hand-off of who speaks the result — a live executor if one is
waiting, this task otherwise.
"""

import asyncio
from collections.abc import Mapping

from app.agents.core.background.comms_narrator import narrate_executor_result
from app.agents.core.background.executor_capture import tool_data_from_events
from app.agents.core.background.result_delivery import deliver_message_to_conversation
from app.constants.browser import (
    BROWSER_JOB_HEARTBEAT_SECONDS,
    BROWSER_JOB_JOINER_LEASE_SECONDS,
    BROWSER_JOB_JOINER_REFRESH_SECONDS,
    BROWSER_JOB_POLL_INTERVAL_SECONDS,
)
from app.constants.log_tags import LogTag
from app.schemas.browser_job import BrowserJobRequest, BrowserJobState, BrowserJobStatus
from app.services.browser.job_events import (
    JOB_TERMINAL_FRAME,
    publish_job_event,
    read_job_events,
)
from app.services.browser.job_runner import agent_result_message, execute_browser_job
from app.services.browser.jobs import (
    claim_conversation_slot,
    heartbeat_conversation_slot,
    joiner_lease_held,
    put_job_state,
    release_conversation_slot,
)
from app.utils.auth_utils import load_user_context
from app.utils.background_tasks import spawn_background_task
from shared.py.wide_events import log


async def run_browser_job(
    ctx: Mapping[str, object],  # noqa: ARG001 -- ARQ injects ctx positionally into every registered task
    payload: dict[str, object],
) -> str:
    """Run one browser task to completion off the request path.

    Owns the slot heartbeat, the terminal state write, and the delivery
    hand-off: a live joiner speaks the result, otherwise this delivers it.
    """
    request = BrowserJobRequest.model_validate(payload)
    log.set(
        user={"id": request.user_id},
        platform=request.conversation_source.value if request.conversation_source else None,
        browser={
            "job_id": request.job_id,
            "conversation_id": request.conversation_id,
            "source_category": request.source_category,
        },
    )
    # Nobody heartbeats the enqueuer's slot lease until here, so a long queue wait
    # can have outlived it. Re-take it before the run, or the run holds no slot at
    # all: its release is a no-op and a joiner reads a RUNNING job as dead.
    holder = await claim_conversation_slot(request.conversation_id, request.job_id)
    if holder is not None and holder != request.job_id:
        log.warning(
            f"{LogTag.BROWSER} Browser job starting without its conversation slot",
            browser={"job_id": request.job_id, "slot_holder": holder},
        )
    heartbeat = spawn_background_task(_heartbeat(request), name="browser_job_heartbeat")
    try:
        result = await execute_browser_job(request)
        agent_message = agent_result_message(result)
        await put_job_state(
            BrowserJobState(
                job_id=request.job_id,
                status=BrowserJobStatus.DONE,
                task=request.task,
                agent_message=agent_message,
                result=result,
            )
        )
        await publish_job_event(request.job_id, JOB_TERMINAL_FRAME)
        await _deliver_if_unjoined(request, agent_message)
        return result.status.value
    finally:
        heartbeat.cancel()
        await release_conversation_slot(request.conversation_id, request.job_id)


async def _heartbeat(request: BrowserJobRequest) -> None:
    """Hold the conversation's browser slot for as long as this run is really running."""
    while True:
        await asyncio.sleep(BROWSER_JOB_HEARTBEAT_SECONDS)
        await heartbeat_conversation_slot(request.conversation_id, request.job_id)


async def _deliver_if_unjoined(request: BrowserJobRequest, agent_message: str) -> None:
    """Deliver the result as a follow-up unless a live executor is joining on it.

    Waits out the joiner's lease rather than sampling it once: the join deletes
    the lease as it collects, and an API that died mid-join lets it expire.
    """
    waited = 0.0
    was_held = False
    while waited < BROWSER_JOB_JOINER_LEASE_SECONDS + BROWSER_JOB_JOINER_REFRESH_SECONDS:
        if await joiner_lease_held(request.job_id):
            was_held = True
        elif was_held:
            log.set_ns("browser", delivered_by="joiner")
            return
        await asyncio.sleep(BROWSER_JOB_POLL_INTERVAL_SECONDS)
        waited += BROWSER_JOB_POLL_INTERVAL_SECONDS
    await _deliver(request, agent_message)


async def _deliver(request: BrowserJobRequest, agent_message: str) -> None:
    """Say what the run did, in the conversation's own voice, as a new message."""
    user = await load_user_context(request.user_id)
    if user is None:
        log.warning(
            f"{LogTag.BROWSER} Browser job result undelivered: user not found",
            browser={"job_id": request.job_id},
        )
        return
    text = await narrate_executor_result(agent_message, "result", request.conversation_id, user)
    if not text:
        log.warning(
            f"{LogTag.BROWSER} Browser job result undelivered: the narration was empty",
            browser={"job_id": request.job_id},
        )
        return
    log.set_ns("browser", delivered_by="worker")
    await deliver_message_to_conversation(
        conversation_id=request.conversation_id,
        user=user,
        text=text,
        # The relay died with the turn, so nothing in an API process collected
        # these: the job's own feed is the only copy of the run's cards left.
        tool_data=tool_data_from_events(
            [payload for _, payload in await read_job_events(request.job_id, "0-0", 0)]
        ),
        origin=f"browser task (job {request.job_id})",
    )
