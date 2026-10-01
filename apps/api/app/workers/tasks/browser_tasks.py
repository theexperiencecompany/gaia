"""The ARQ task that runs one browser job.

The run itself is the job runner's; this owns what only a worker can own: the
slot the run holds while it really runs, and who speaks the result: a live
executor if one is joined on it, this task otherwise.
"""

import asyncio
from collections.abc import Mapping

from app.agents.core.background.comms_narrator import narrate_executor_result
from app.agents.core.background.executor_capture import tool_data_from_events
from app.agents.core.background.result_delivery import deliver_message_to_conversation
from app.agents.core.comms_directive import interpret_comms_output
from app.agents.prompts.comms_prompts import INTERACTIVE_DELIVERY_NOTE
from app.constants.browser import (
    BROWSER_JOB_HEARTBEAT_SECONDS,
    BROWSER_JOB_SLOT_TAKEN_SUMMARY,
    ResultSpeaker,
)
from app.constants.comms import CommsDirectiveKind
from app.constants.log_tags import LogTag
from app.schemas.browser_job import BrowserJobRequest
from app.services.browser.job_events import is_card_frame, read_job_events
from app.services.browser.job_runner import (
    agent_result_message,
    execute_browser_job,
    refuse_browser_job,
)
from app.services.browser.jobs import (
    await_result_unclaimed,
    claim_conversation_slot,
    claim_result_delivery,
    heartbeat_conversation_slot,
    job_cancel_requested,
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

    Owns the slot heartbeat and the delivery hand-off: a live joiner speaks the
    result, otherwise this delivers it. A stopped run is not narrated: the stop
    already said so.
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
    # can have outlived it, and another run may have taken the conversation since.
    holder = await claim_conversation_slot(request.conversation_id, request.job_id)
    if holder is not None and holder != request.job_id:
        log.warning(
            f"{LogTag.BROWSER} Browser job refused: its conversation slot was taken",
            browser={"job_id": request.job_id, "slot_holder": holder},
        )
        return (await refuse_browser_job(request, BROWSER_JOB_SLOT_TAKEN_SUMMARY)).status.value
    heartbeat = spawn_background_task(_heartbeat(request), name="browser_job_heartbeat")
    try:
        result = await execute_browser_job(request)
        if await job_cancel_requested(request.job_id):
            log.set_ns("browser", delivered_by="stop")
        else:
            await _deliver_if_unjoined(request, agent_result_message(result))
        return result.status.value
    finally:
        heartbeat.cancel()
        await release_conversation_slot(request.conversation_id, request.job_id)


async def _heartbeat(request: BrowserJobRequest) -> None:
    """Hold the conversation's browser slot for as long as this run is really running.

    One Redis error costs one beat, not the lease: a heartbeat that died on it
    would let the slot lapse under a live run.
    """
    while True:
        await asyncio.sleep(BROWSER_JOB_HEARTBEAT_SECONDS)
        try:
            held = await heartbeat_conversation_slot(request.conversation_id, request.job_id)
        except Exception as exc:
            log.error(
                f"{LogTag.BROWSER} Browser job slot heartbeat failed",
                error_type=type(exc).__name__,
                error=str(exc),
                browser={"job_id": request.job_id},
            )
            continue
        if not held:
            log.warning(
                f"{LogTag.BROWSER} Browser job lost its conversation slot while running",
                browser={"job_id": request.job_id},
            )


async def _deliver_if_unjoined(request: BrowserJobRequest, agent_message: str) -> None:
    """Deliver the result as a follow-up unless an executor run that may still join speaks it.

    The run that started the job, and any turn joined on it, hold the result
    until they end; the one that collects it claims the telling, and once no
    claim is held this tells it, at once.
    """
    await await_result_unclaimed(request.job_id)
    if (
        await claim_result_delivery(request.job_id, ResultSpeaker.WORKER)
        is not ResultSpeaker.WORKER
    ):
        log.set_ns("browser", delivered_by=ResultSpeaker.JOINER.value)
        return
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
    # No SILENCE note: the result of a run the user asked for is never a no-op update.
    text = await narrate_executor_result(
        agent_message, "result", request.conversation_id, user, preamble=INTERACTIVE_DELIVERY_NOTE
    )
    if not text:
        log.warning(
            f"{LogTag.BROWSER} Browser job result undelivered: the narration was empty",
            browser={"job_id": request.job_id},
        )
        return
    directive = interpret_comms_output(text)
    if directive.kind is not CommsDirectiveKind.REPLY:
        log.warning(
            f"{LogTag.BROWSER} Browser job result undelivered: the narration was a directive",
            browser={"job_id": request.job_id, "directive": directive.kind.value},
        )
        return
    log.set_ns("browser", delivered_by=ResultSpeaker.WORKER.value)
    await deliver_message_to_conversation(
        conversation_id=request.conversation_id,
        user=user,
        text=directive.payload,
        # The message that speaks the result carries the run's cards: the job's
        # own feed is their one full copy.
        tool_data=tool_data_from_events(
            [
                payload
                for _, payload in await read_job_events(request.job_id, "0-0", 0)
                if is_card_frame(payload)
            ]
        ),
        origin=f"browser task (job {request.job_id})",
    )
