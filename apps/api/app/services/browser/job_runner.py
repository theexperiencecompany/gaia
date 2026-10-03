"""One browser task, run end to end with nothing of the request around it.

The process-agnostic half of the browser tool: no stream writer, no LangGraph
config, no tool result. Card snapshots go to the job's own Redis feed, bots are
mirrored here, and every failure becomes a terminal result card because nobody
is holding a tool call to hear an exception.
"""

import asyncio
from collections.abc import Awaitable, Callable
import contextlib
from functools import partial
from time import perf_counter
import uuid

from app.config.feature_flags import FeatureFlag
from app.config.settings import settings
from app.constants.browser import (
    BROWSER_AGENT_GUIDANCE_TIMEOUT_SECONDS,
    BROWSER_JOB_CRASHED_SUMMARY,
    BROWSER_JOB_WORKER_STOPPED_SUMMARY,
    BROWSER_NO_CHROME_HOST,
    BROWSER_RESULT_REPLACED_REQUEST,
    BROWSER_RESULT_USER_SAID,
    BROWSER_RUN_CANCELLED_SUMMARY,
    BROWSER_TOOL_CATEGORY,
    BrowserEngine,
    BrowserRunFailure,
    BrowserSessionStatus,
    EngineFailure,
    HandoffKind,
    HandoffStatus,
    JobEnding,
    SensitiveCategory,
)
from app.constants.log_tags import LogTag
from app.models.chat_models import SourceCategory
from app.models.stream_events import ToolOutputPayload
from app.schemas.browser import (
    AgentGuidanceRequest,
    BrowserActionOutput,
    BrowserCardSnapshot,
    BrowserHandoffSnapshot,
    BrowserResultSnapshot,
    BrowserSessionSnapshot,
    BrowserStepSnapshot,
    HandoffOutcome,
    HandoffRequest,
    NewHandoff,
    PendingAgentGuidance,
)
from app.schemas.browser_job import BrowserJobRequest, BrowserJobState, BrowserJobStatus
from app.services.analytics_service import AnalyticsEvents, capture_event
from app.services.browser import host_client
from app.services.browser.agent_guidance import (
    clear_guidance_request,
    put_guidance_request,
)
from app.services.browser.bot_delivery import BotProgressDelivery
from app.services.browser.exceptions import (
    BrowserConcurrencyLimit,
    BrowserSessionGone,
    BrowserUnavailableError,
)
from app.services.browser.fingerprint import reset_fingerprint_seed, set_fingerprint_seed
from app.services.browser.handoff import (
    await_handoff,
    cancel_handoff,
    create_pending_handoff,
    fail_handoff,
    reply_address,
)
from app.services.browser.jev.secrets import RunSecrets
from app.services.browser.job_events import (
    JOB_GUIDANCE_FRAME,
    JOB_TERMINAL_FRAME,
    card_frame,
    publish_job_event,
)
from app.services.browser.jobs import (
    clear_job_wait,
    job_cancel_requested,
    job_messages_waiting,
    joiner_lease_held,
    put_job_state,
    record_ending,
    set_job_wait,
    take_job_messages,
)
from app.services.browser.replay import create_replay_link
from app.services.browser.run_contract import FinishedRun
from app.services.browser.run_failure import record_run_result
from app.services.browser.runner import (
    BrowserRunConfig,
    BrowserRunnerCallbacks,
    BrowserTaskRunner,
)
from app.services.browser.session import (
    BrowserHostSession,
    LiveSessionState,
    browser_session,
)
from app.services.browser.tasks import BrowserTaskRecord, record_browser_task
from app.services.browser.user_notes import what_the_user_said
from app.services.chat.chunks import normalize_custom_event
from app.services.feature_flags import is_enabled
from app.utils.agent_utils import (
    SubagentStartDetails,
    format_browser_action_entry,
    format_subagent_end_event,
    format_subagent_start_event,
)
from app.utils.background_tasks import spawn_background_task
from shared.py.wide_events import log

#: Where one already-shaped stream frame goes: the job's own replayable feed.
FramePublisher = Callable[[dict[str, object]], Awaitable[None]]
#: Records that the run finished on this result unless the job's ending is recorded already; answers the ending of record.
RecordFinishedFn = Callable[[BrowserResultSnapshot], Awaitable[JobEnding]]

# Screenshots stream into the chat live, so the reply must never narrate them.
_NO_META = (
    "The step-by-step screenshots were already shown to the user in this chat, so do "
    "NOT mention screenshots, tools, steps, or 'browser vision'. Speak only to the outcome."
)


# The executor re-ran a finished task once because the tool result buried the
# run's answer; the answer now leads, and a failure says not to try again.
_FINISHED_LINE = "The browser task finished, and the text above is its own final answer."
_NO_RETRY = "Do not run the browser again for this request; tell the user what happened."

# The conversation still holds the original instruction, so without this the
# reply confirms that instead: a run that was told to skip the login and the
# upvote closed with "signed you into Reddit ... and upvoted the top post".
_ONLY_THE_SUMMARY = (
    "Report only what the summary states. Never claim an action it does not explicitly "
    "report: a login, a purchase, a vote, a message sent, a form submitted, a box ticked. "
    "That the task asked for a step is not evidence the step happened."
)


def agent_result_message(result: BrowserResultSnapshot) -> str:
    """Tell the assistant how to reply: confirm a real result, own a stop, or report a failure."""
    summary = result.summary.strip()
    # First, before anything the run itself reported: a trailing sentence lost to the
    # original request still in the model's context.
    said = what_the_user_said(
        result.user_notes,
        result.redirects,
        replaced=BROWSER_RESULT_REPLACED_REQUEST,
        said=BROWSER_RESULT_USER_SAID,
    )
    lead = f"{said}\n\n" if said else ""
    if result.status == BrowserSessionStatus.COMPLETED and result.success:
        return (
            f"{lead}{summary or 'The task finished.'}\n\n"
            f"{_FINISHED_LINE} Reply with a short, natural confirmation of what you found "
            f"or did. {_ONLY_THE_SUMMARY} {_NO_META}"
        )
    if result.status == BrowserSessionStatus.CANCELLED:
        return (
            f"{lead}"
            "BROWSER TASK WAS STOPPED before it finished. It did NOT complete, so there is no "
            "result and you must not claim one. It was stopped either because the user asked, "
            "or because the request that started it ended early; never say the user stopped it "
            "unless the conversation shows they did.\n\n"
            f"Briefly say the browser task was stopped and ask if they'd like you to try again "
            f"or do something else. {_ONLY_THE_SUMMARY} {_NO_META}"
        )
    return (
        f"{lead}"
        f"BROWSER TASK DID NOT COMPLETE. Last state: {summary or 'the task could not be finished'}.\n\n"
        f"{_NO_RETRY} Tell the user honestly and briefly that it couldn't be finished, and why "
        f"if it's clear. Do not fabricate a result, and offer no figure or answer from memory or from "
        f"an earlier run: a run that confirmed nothing gives nothing. {_ONLY_THE_SUMMARY} {_NO_META}"
    )


async def publish_frame_to_job(job_id: str, payload: dict[str, object]) -> None:
    """Normalize a raw frame once, here at the producer, and append it to the job's feed."""
    await publish_job_event(job_id, normalize_custom_event(payload))


class BrowserThreadMirror:
    """Mirrors the browser agent's own actions into the chat's tool thread.

    The card shows what the browser is doing; this shows what it called — every
    action with its arguments, grouped under one "Browser" row exactly like a
    subagent's tool calls, instead of one opaque browser_task row. The group is
    keyed by the browser_task call that started the run, so a client pairs the
    call with its group by id, and a move to the fallback engine keeps it.
    """

    def __init__(self, publish: FramePublisher, tool_call_id: str) -> None:
        self._publish = publish
        self._group = f"browser:{tool_call_id}"
        # "" reads as falsy exactly like None: set while the group is open.
        self._group_id: str | None = None  # pragma: no mutate
        #: Set when the group opens; nothing reads it before then.
        self._started_at: float
        # tool_call_ids of the action rows emitted, so an output only ever
        # lands on a row that exists (an errored step emits no rows).
        self._emitted_ids: set[str] = set()
        # Outputs can arrive before their row: step rows go through a background
        # task that uploads the screenshot first (~1s), while action results
        # arrive synchronously. Buffer early outputs and flush on row arrival.
        self._pending_outputs: dict[str, str] = {}

    async def mirror(self, snapshot: BrowserCardSnapshot) -> None:
        if isinstance(snapshot, BrowserSessionSnapshot):
            await self._open()
        elif isinstance(snapshot, BrowserStepSnapshot):
            await self._actions(snapshot)
        elif isinstance(snapshot, BrowserResultSnapshot):
            await self._close()

    async def _open(self) -> None:
        if self._group_id:
            return
        self._group_id = self._group
        self._started_at = perf_counter()
        await self._publish(
            {
                "subagent_start": format_subagent_start_event(
                    subagent_name="Browser",
                    agent_type="spawned",
                    subagent_id=self._group_id,
                    details=SubagentStartDetails(tool_category=BROWSER_TOOL_CATEGORY),
                )
            }
        )

    async def _actions(self, snapshot: BrowserStepSnapshot) -> None:
        if not self._group_id:
            return
        for position, action in enumerate(snapshot.actions):
            tool_call_id = f"{self._group_id}:{snapshot.index}:{position}"
            self._emitted_ids.add(tool_call_id)
            await self._publish(
                {
                    "tool_data": format_browser_action_entry(
                        name=action.name,
                        inputs=action.inputs,
                        target=action.target,
                        subagent_id=self._group_id,
                        tool_call_id=tool_call_id,
                    )
                }
            )
            buffered = self._pending_outputs.pop(tool_call_id, None)
            if buffered is not None:
                await self._emit_output(tool_call_id, buffered)

    async def results(self, step_index: int, outputs: list[BrowserActionOutput]) -> None:
        """Attach each executed action's result to its row.

        Buffered until the row is emitted when it arrives first — the row's
        background task may still be uploading the step's screenshot.
        """
        if not self._group_id:
            return
        for output in outputs:
            tool_call_id = f"{self._group_id}:{step_index}:{output.position}"
            if tool_call_id in self._emitted_ids:
                await self._emit_output(tool_call_id, output.output)
            else:
                self._pending_outputs[tool_call_id] = output.output

    async def _emit_output(self, tool_call_id: str, output: str) -> None:
        payload = ToolOutputPayload(
            tool_call_id=tool_call_id,
            output=output,
            subagent_id=self._group_id,
        )
        # Every field is a str, so the json and python dump modes agree.
        dumped = payload.model_dump(mode="json")  # pragma: no mutate
        await self._publish({"tool_output": dumped})

    async def _close(self) -> None:
        if not self._group_id:
            return
        await self._publish(
            {
                "subagent_end": format_subagent_end_event(
                    subagent_id=self._group_id,
                    duration_ms=int((perf_counter() - self._started_at) * 1000),
                )
            }
        )
        # "" reads as falsy exactly like None.
        self._group_id = None  # pragma: no mutate


def _build_bot_delivery(request: BrowserJobRequest) -> BotProgressDelivery | None:
    """Mirror a bot-asked run to the requester's DM, never a group: its live link and shots are private."""
    is_bot = request.source_category == SourceCategory.BOT.value
    if not (is_bot and request.user_id and request.conversation_id):
        return None
    if request.conversation_source is None:
        return None
    return BotProgressDelivery(
        platform=request.conversation_source,
        user_id=request.user_id,
        stream_screenshots=settings.BROWSER_USE_STREAM_SCREENSHOTS,
    )


async def _deliver_snapshot_to_bot(
    bot_delivery: BotProgressDelivery, snapshot: BrowserCardSnapshot
) -> None:
    """Best-effort mirror of a card to the bot platform.

    The card is already published to the chat, so a messaging/queue outage is
    logged and swallowed — never a reason to abort the in-flight run.
    """
    try:
        if isinstance(snapshot, BrowserStepSnapshot):
            await bot_delivery.step(snapshot)
        elif isinstance(snapshot, BrowserResultSnapshot):
            await bot_delivery.result(snapshot)
        elif isinstance(snapshot, BrowserHandoffSnapshot):
            await bot_delivery.handoff(snapshot)
        elif isinstance(snapshot, BrowserSessionSnapshot):
            await bot_delivery.session(snapshot)
    except Exception as exc:
        log.error(
            f"{LogTag.BROWSER} Bot delivery failed; continuing browser task",
            error_type=type(exc).__name__,
            error=str(exc),
            browser={"snapshot_type": type(snapshot).__name__},
        )


class ProgressEmitter:
    """Publishes each card snapshot into the run's feed and to the bot platform.

    Records the published screenshots and captions the history recap reads back
    once the run finishes, and the run's session and last result card, which a
    cancelled run is ended with.
    """

    def __init__(
        self,
        publish: FramePublisher,
        thread_mirror: BrowserThreadMirror,
        bot_delivery: BotProgressDelivery | None,
        record_finished: RecordFinishedFn,
    ) -> None:
        self._publish = publish
        self._record_finished = record_finished
        self.thread_mirror = thread_mirror
        self._bot_delivery = bot_delivery
        # Captions for the recap ("what's going on" per step), keyed by step index.
        self.step_goals: dict[int, str] = {}
        # The screenshots that were published, by step; a step with no photo has none.
        self.step_shots: dict[int, str] = {}
        #: The session the run opened, whose recap a failure still links; None until then.
        # Equivalent mutant: nothing is shot before a session opens, so "" links no recap either.
        self.session_id: str | None = None  # pragma: no mutate
        #: The result card the run ended on, once it emitted one.
        self.result: BrowserResultSnapshot | None = None

    async def note(self, text: str) -> None:
        """Send one plain line to a bot user; the web card has the live view to watch."""
        if self._bot_delivery is not None:
            await self._bot_delivery.note(text)

    async def emit(self, snapshot: BrowserCardSnapshot) -> None:
        if isinstance(snapshot, BrowserResultSnapshot):
            snapshot = await self._as_ended(snapshot)
        await self._publish(card_frame(snapshot))
        await self.thread_mirror.mirror(snapshot)
        if isinstance(snapshot, BrowserResultSnapshot):
            self.result = snapshot
        elif isinstance(snapshot, BrowserStepSnapshot):
            if snapshot.goal:
                self.step_goals[snapshot.index] = snapshot.goal
            if snapshot.screenshot is not None:
                self.step_shots[snapshot.index] = snapshot.screenshot
        if self._bot_delivery is not None:
            await _deliver_snapshot_to_bot(self._bot_delivery, snapshot)

    async def _as_ended(self, result: BrowserResultSnapshot) -> BrowserResultSnapshot:
        return await _ended_as_record_says(self._record_finished, result)


async def _ended_as_record_says(
    record_finished: RecordFinishedFn, result: BrowserResultSnapshot
) -> BrowserResultSnapshot:
    """Return the result card the job ends on: the run's own when it records the ending first, else the stop's.

    The run's end and a stop race to record the one ending (jobs.record_ending);
    a run that lost is shown as stopped, since the stop already told the user.
    """
    if await record_finished(result) is JobEnding.FINISHED:
        return result
    if result.status is BrowserSessionStatus.CANCELLED:
        return result
    return result.model_copy(
        update={
            "status": BrowserSessionStatus.CANCELLED,
            "success": False,
            "summary": BROWSER_RUN_CANCELLED_SUMMARY,
        }
    )


def _ended_on(emitter: ProgressEmitter, result: BrowserResultSnapshot) -> BrowserResultSnapshot:
    """Return the card the emitter ended the run on, which is the run's result as its ending of record left it."""
    return emitter.result if emitter.result is not None else result


def _handoff_snapshot(
    handoff_id: str,
    req: HandoffRequest,
    session: BrowserHostSession,
    status: HandoffStatus,
) -> BrowserHandoffSnapshot:
    return BrowserHandoffSnapshot(
        handoff_id=handoff_id,
        category=req.category,
        reason=req.reason,
        session_id=session.session_id,
        status=status,
        saves_login=req.category == SensitiveCategory.CREDENTIALS
        and settings.BROWSER_PERSIST_LOGINS,
    )


async def _await_unless_stopped(
    job_id: str, handoff_id: str, timeout_seconds: int
) -> HandoffOutcome:
    """Wait on the handoff the run is paused on; a stop settles it cancelled, whether it came before the wait or during it."""
    await set_job_wait(job_id, handoff_id)
    try:
        # A stop that landed before the wait was recorded found nothing to settle.
        if await job_cancel_requested(job_id):
            await cancel_handoff(handoff_id)
        return await await_handoff(handoff_id, timeout_seconds)
    finally:
        await clear_job_wait(job_id)


async def _fail_when_session_gone(session: BrowserHostSession, handoff_id: str) -> None:
    """End the handoff once the host has lost the paused browser: nobody can finish a step there."""
    await session.gone.wait()
    await fail_handoff(handoff_id, EngineFailure.SESSION_GONE)


async def _run_handoff(
    req: HandoffRequest,
    session: BrowserHostSession,
    *,
    emit: Callable[[BrowserCardSnapshot], Awaitable[None]],
    request: BrowserJobRequest,
) -> HandoffOutcome:
    """Pause the run and hand the user a live view to complete the step themselves.

    Only the user ends it, by saying they are done or tapping the button; the
    outcome (completed with optional note, cancelled, timed out, or failed with
    the browser) resumes the loop.
    """
    handoff_id = uuid.uuid4().hex
    if req.category == SensitiveCategory.CREDENTIALS:
        # Asked to sign in again here, so an earlier "done" did not leave a login to save.
        try:
            session.forget_login(await _page_url(session))
        except BrowserSessionGone:
            return HandoffOutcome(status=HandoffStatus.FAILED, cause=EngineFailure.SESSION_GONE)
    await create_pending_handoff(
        handoff_id,
        NewHandoff(
            job_id=request.job_id,
            user_id=request.user_id,
            conversation_id=request.conversation_id,
            reason=req.reason,
            reply_to=reply_address(
                request.conversation_id, request.user_id, request.conversation_source
            ),
        ),
    )
    await emit(_handoff_snapshot(handoff_id, req, session, HandoffStatus.PENDING))
    # The job holds the session's lease for its whole life; a browser the host
    # lost meanwhile leaves the user nothing to come back to.
    watch = spawn_background_task(
        _fail_when_session_gone(session, handoff_id), name="browser_handoff_session_watch"
    )
    try:
        outcome = await _await_unless_stopped(
            request.job_id, handoff_id, settings.BROWSER_USE_HANDOFF_TIMEOUT_SECONDS
        )
    except asyncio.CancelledError:
        # Cut off mid-wait (a stop's abort, the worker shutting down): the card and
        # the record must not go on asking the user to finish a step nobody waits for.
        await asyncio.shield(_abandon_handoff(handoff_id, req, session, emit))
        raise
    finally:
        watch.cancel()
    if outcome.status == HandoffStatus.COMPLETED and req.category == SensitiveCategory.CREDENTIALS:
        outcome = await _mark_signed_in(session, outcome)
    log.set_ns(
        "browser",
        handoff_kind=HandoffKind.USER.value,
        handoff_category=req.category.value,
        handoff_result=outcome.status.value,
    )
    await emit(_handoff_snapshot(handoff_id, req, session, outcome.status))
    return outcome


async def _page_url(session: BrowserHostSession) -> str | None:
    """Return the page the session shows now; raises BrowserSessionGone, marking it gone, once the host has lost it."""
    try:
        page = await host_client.get_session(session.session_id, session.host_url)
    except BrowserSessionGone:
        session.gone.set()
        raise
    return page.url


async def _mark_signed_in(session: BrowserHostSession, outcome: HandoffOutcome) -> HandoffOutcome:
    """Record the site the user said they signed in on, so its login is saved; a lost browser ends the handoff with it."""
    try:
        session.mark_authenticated(await _page_url(session))
    except BrowserSessionGone:
        return HandoffOutcome(status=HandoffStatus.FAILED, cause=EngineFailure.SESSION_GONE)
    except BrowserUnavailableError as exc:
        # The run goes on; with the site unknown, no login is saved for it.
        log.warning(
            f"{LogTag.BROWSER} Could not read where the user signed in; their login is not saved",
            error_type=type(exc).__name__,
            browser={"session_id": session.session_id, "operation": "mark_signed_in"},
        )
    return outcome


async def _abandon_handoff(
    handoff_id: str,
    req: HandoffRequest,
    session: BrowserHostSession,
    emit: Callable[[BrowserCardSnapshot], Awaitable[None]],
) -> None:
    status = await cancel_handoff(handoff_id)
    await emit(_handoff_snapshot(handoff_id, req, session, status))


async def _hand_over_to_fallback(
    sessions: contextlib.AsyncExitStack,
    primary: contextlib.AsyncExitStack,
    user_id: str,
    host_url: str,
    url: str | None,
    carried: LiveSessionState | None,
) -> BrowserHostSession:
    """Open the fallback host's session for url, seeded with carried, then release the primary at once.

    The primary holds nothing the run still needs: its logins moved to the
    fallback with its state, and an idle browser only costs the host capacity.
    """
    fallback = await sessions.enter_async_context(
        browser_session(user_id=user_id, host_url=host_url, start_url=url, carried=carried)
    )
    await primary.aclose()
    return fallback


async def _run_guidance(
    request: AgentGuidanceRequest,
    *,
    job: BrowserJobRequest,
) -> HandoffOutcome:
    """Pause the run and ask the joined agent for one instruction.

    Deliberately silent to the user: an AGENT handoff takes no reply address
    and emits no card, so their only sign of it is the step frame's caption.
    """
    handoff_id = uuid.uuid4().hex
    await create_pending_handoff(
        handoff_id,
        NewHandoff(
            job_id=job.job_id,
            user_id=job.user_id,
            conversation_id=job.conversation_id,
            reason=request.reason,
            kind=HandoffKind.AGENT,
        ),
    )
    await put_guidance_request(
        job.job_id, PendingAgentGuidance(handoff_id=handoff_id, request=request)
    )
    # Wakes a join parked on the feed; the request itself is read from its key.
    await publish_job_event(job.job_id, JOB_GUIDANCE_FRAME)
    try:
        outcome = await _await_unless_stopped(
            job.job_id, handoff_id, BROWSER_AGENT_GUIDANCE_TIMEOUT_SECONDS
        )
    finally:
        await clear_guidance_request(job.job_id)
    log.set_ns("browser", guidance_result=outcome.status.value)
    return outcome


async def persist_run_outcome(
    request: BrowserJobRequest, run: FinishedRun, *, emitter: ProgressEmitter
) -> None:
    """Record analytics + the browser-history row for a finished run.

    A job has no authenticated request context, so the id must be explicit or
    the event lands on an anonymous profile (see analytics conventions in
    CLAUDE.md). The history write is awaited rather than spawned: in the worker
    the task body is the lifetime, and a fire-and-forget write dies with it.
    """
    if not request.user_id:
        return
    result = run.result
    capture_event(
        request.user_id,
        AnalyticsEvents.BROWSER_TASK_FINISHED,
        {
            "status": result.status.value,
            "success": result.success,
            "steps": result.steps,
            "actions": run.actions,
            "duration_ms": run.run_ms,
            "source": request.source_category or "web",
            # With success, says whether the fallback engine recovered a run
            # the primary could not finish, and so points at engine gaps.
            "engine_fallback": run.engine_fallback,
        },
    )
    await record_browser_task(
        BrowserTaskRecord(
            user_id=request.user_id,
            conversation_id=request.conversation_id,
            task=request.task,
            session_id=run.session_id,
            source=request.conversation_source.value if request.conversation_source else "",
        ),
        result,
        actions=run.actions,
        step_goals=[emitter.step_goals.get(i, "") for i in range(1, result.steps + 1)],
        step_screenshots=[emitter.step_shots.get(i, "") for i in range(1, result.steps + 1)],
    )


async def _record_finished_run(
    request: BrowserJobRequest, finished: FinishedRun, emitter: ProgressEmitter
) -> None:
    """Record a run that has its result; a failure here is logged and never turns that result into a crash."""
    record_run_result(finished)
    try:
        await persist_run_outcome(request, finished, emitter=emitter)
    except Exception as exc:
        log.error(
            f"{LogTag.BROWSER} Browser run finished but its history was not recorded",
            error_type=type(exc).__name__,
            error=str(exc),
            browser={"job_id": request.job_id},
        )


def hosts_for(engine: BrowserEngine) -> tuple[str, str | None]:
    """Return the host a run that wants engine opens on, and the Chrome host behind it.

    BROWSER_FALLBACK_HOST_URL, when set, is a Chrome host. BROWSER_HOST_URL is the
    primary, whichever engine it runs; its sessions report that engine. Chrome is
    the default engine, Obscura an opt-in one.
    """
    chrome_host = settings.BROWSER_FALLBACK_HOST_URL
    if engine is BrowserEngine.OBSCURA:
        return settings.BROWSER_HOST_URL, chrome_host
    return chrome_host or settings.BROWSER_HOST_URL, None


async def _end_on(
    emitter: ProgressEmitter, status: BrowserSessionStatus, summary: str
) -> BrowserResultSnapshot:
    """End the run on a result card the job itself writes, unless the run already ended on its own.

    Once a result card is out it is the run's result: a failure after it (a
    teardown, a cancel landing late) never puts a second, contradicting card
    on top. Carries the recap link a finished run gets once a session opened.
    """
    if emitter.result is not None:
        return emitter.result
    shots = [emitter.step_shots[index] for index in sorted(emitter.step_shots)]
    session_id = emitter.session_id
    result = BrowserResultSnapshot(
        status=status,
        success=False,
        summary=summary,
        replay_url=await create_replay_link(session_id, shots) if session_id else None,
    )
    await emitter.emit(result)
    return result


async def settle_job(request: BrowserJobRequest, result: BrowserResultSnapshot) -> None:
    """Write the job's ending: the DONE state a join reads, then the frame that closes its feed."""
    await put_job_state(_done_state(request, result))
    await publish_job_event(request.job_id, JOB_TERMINAL_FRAME)


def _done_state(request: BrowserJobRequest, result: BrowserResultSnapshot) -> BrowserJobState:
    """Return the state the job ends in on result: what a join reads to tell it."""
    return BrowserJobState(
        job_id=request.job_id,
        status=BrowserJobStatus.DONE,
        task=request.task,
        relay_stream_id=request.stream_id,
        agent_message=agent_result_message(result),
        result=result,
    )


async def _record_finished(request: BrowserJobRequest, result: BrowserResultSnapshot) -> JobEnding:
    """Record that the run finished on result, its DONE state in the same write, unless the job's ending is recorded already.

    Kept with the decision, the result outlives a worker that dies before it
    publishes the card or settles the job: any later join reads and tells it.
    """
    return await record_ending(request.job_id, JobEnding.FINISHED, _done_state(request, result))


def _emitter_for(request: BrowserJobRequest) -> ProgressEmitter:
    emit_frame = partial(publish_frame_to_job, request.job_id)
    return ProgressEmitter(
        emit_frame,
        BrowserThreadMirror(emit_frame, request.tool_call_id),
        _build_bot_delivery(request),
        partial(_record_finished, request),
    )


async def refuse_browser_job(request: BrowserJobRequest, summary: str) -> BrowserResultSnapshot:
    """End a job that must not run at all on a failure card, with the ending a join waits for."""
    result = await _end_on(_emitter_for(request), BrowserSessionStatus.FAILED, summary)
    await settle_job(request, result)
    return result


async def execute_browser_job(request: BrowserJobRequest) -> BrowserResultSnapshot:
    """Run one browser task end to end, then settle the job: its last card, its DONE state, the end of its feed.

    Every ending publishes a terminal card and settles the job, a cancellation
    included (a stop's abort, or the worker shutting down), which then propagates.
    """
    emitter = _emitter_for(request)
    # Pin this run's canvas/audio fingerprint to the user, so the same person
    # always presents the same device rather than a new one per task.
    seed_token = set_fingerprint_seed(request.user_id)
    try:
        result = _ended_on(emitter, await _run_job(request, emitter))
    except asyncio.CancelledError:
        log.fail(BrowserRunFailure.CANCELLED)
        # Nobody holds a tool call to hear this; without it the card stays RUNNING forever.
        await asyncio.shield(_end_cancelled(request, emitter))
        raise
    finally:
        reset_fingerprint_seed(seed_token)
    await settle_job(request, result)
    return result


async def _end_cancelled(request: BrowserJobRequest, emitter: ProgressEmitter) -> None:
    """Settle a job whose task was cancelled: on the card the run already ended on, else on a stopped one."""
    if await job_cancel_requested(request.job_id):
        result = await _end_on(
            emitter, BrowserSessionStatus.CANCELLED, BROWSER_RUN_CANCELLED_SUMMARY
        )
    else:
        result = await _end_on(
            emitter, BrowserSessionStatus.FAILED, BROWSER_JOB_WORKER_STOPPED_SUMMARY
        )
    await settle_job(request, result)


async def _run_job(request: BrowserJobRequest, emitter: ProgressEmitter) -> BrowserResultSnapshot:
    """Open the browser and run the task; every failure becomes a terminal result card here."""
    if await job_cancel_requested(request.job_id):
        # Stopped while it queued: ARQ is never asked to drop a queued job, so it ends here.
        return await _end_on(emitter, BrowserSessionStatus.CANCELLED, BROWSER_RUN_CANCELLED_SUMMARY)
    full_task = (
        request.task
        if not request.start_url
        else f"{request.task}\n\nStart at: {request.start_url}"
    )
    try:
        engine = (
            BrowserEngine.OBSCURA
            if await is_enabled(FeatureFlag.BROWSER_OBSCURA, request.user_id)
            else BrowserEngine.CHROMIUM
        )
        host_url, fallback_host = hosts_for(engine)
        secrets = RunSecrets(request.secrets)
        async with contextlib.AsyncExitStack() as sessions:
            # Its own stack, so a run handed over to the fallback releases it there and then.
            primary = contextlib.AsyncExitStack()
            sessions.push_async_callback(primary.aclose)
            session = await primary.enter_async_context(
                browser_session(
                    user_id=request.user_id,
                    host_url=host_url,
                    start_url=request.start_url,
                )
            )
            log.set(browser={"session_id": session.session_id})
            # A run that fails before its first card still links the recap of this session.
            emitter.session_id = session.session_id
            log.set_ns("browser", engine=session.engine.value)
            if engine is BrowserEngine.CHROMIUM and session.engine is not BrowserEngine.CHROMIUM:
                # The host says it is not Chrome: a user who never chose Obscura is not run on it.
                raise BrowserUnavailableError(BROWSER_NO_CHROME_HOST)
            await put_job_state(
                BrowserJobState(
                    job_id=request.job_id,
                    status=BrowserJobStatus.RUNNING,
                    task=request.task,
                    relay_stream_id=request.stream_id,
                )
            )

            runner = BrowserTaskRunner(
                session=session,
                secrets=secrets,
                callbacks=BrowserRunnerCallbacks(
                    emit=emitter.emit,
                    request_handoff=partial(_run_handoff, emit=emitter.emit, request=request),
                    # Only a run the host put on Obscura has anywhere to move to.
                    open_fallback_session=(
                        partial(
                            _hand_over_to_fallback,
                            sessions,
                            primary,
                            request.user_id,
                            fallback_host,
                        )
                        if fallback_host and session.engine is BrowserEngine.OBSCURA
                        else None
                    ),
                    is_cancelled=partial(job_cancel_requested, request.job_id),
                    user_waiting=partial(job_messages_waiting, request.job_id),
                    take_user_messages=partial(take_job_messages, request.job_id),
                    action_results=emitter.thread_mirror.results,
                    agent_joined=partial(joiner_lease_held, request.job_id),
                    note=emitter.note,
                    request_guidance=partial(_run_guidance, job=request),
                ),
                config=BrowserRunConfig(
                    max_steps=settings.BROWSER_USE_MAX_STEPS,
                    max_actions_per_step=settings.BROWSER_USE_MAX_ACTIONS_PER_STEP,
                    task_timeout_seconds=settings.BROWSER_USE_TASK_TIMEOUT_SECONDS,
                    step_timeout_seconds=settings.BROWSER_USE_STEP_TIMEOUT_SECONDS,
                    handoff_timeout_seconds=settings.BROWSER_USE_HANDOFF_TIMEOUT_SECONDS,
                    stream_screenshots=settings.BROWSER_USE_STREAM_SCREENSHOTS,
                    solve_captcha=settings.BROWSER_USE_SOLVE_CAPTCHA,
                    start_url=request.start_url or None,
                ),
                user_id=request.user_id or None,
                root_request_id=request.root_request_id,
            )
            run_t0 = perf_counter()
            # The card the run ended on, as its ending of record left it: a stop that won makes it the stopped card.
            result = _ended_on(emitter, await runner.run(full_task))
            finished = FinishedRun(
                result=result,
                session_id=runner.session.session_id,
                actions=runner.ledger.action_count,
                engine_fallback=runner.used_fallback,
                run_ms=round((perf_counter() - run_t0) * 1000),
                failure=runner.failure,
            )
        await _record_finished_run(request, finished, emitter)
        return result
    except BrowserConcurrencyLimit as exc:
        log.warning(f"{LogTag.BROWSER} Browser host at capacity", error=str(exc))
        log.fail(BrowserRunFailure.HOST_AT_CAPACITY)
        return await _end_on(emitter, BrowserSessionStatus.FAILED, str(exc))
    except BrowserUnavailableError as exc:
        log.warning(
            f"{LogTag.BROWSER} Browser session unavailable",
            error_type=type(exc).__name__,
            error=str(exc),
        )
        log.fail(BrowserRunFailure.HOST_UNAVAILABLE)
        return await _end_on(emitter, BrowserSessionStatus.FAILED, str(exc))
    except Exception as exc:
        log.error(
            f"{LogTag.BROWSER} Browser job crashed",
            error_type=type(exc).__name__,
            error=str(exc),
            browser={"job_id": request.job_id},
            exc_info=True,
        )
        log.fail(BrowserRunFailure.RUN_CRASHED)
        return await _end_on(emitter, BrowserSessionStatus.FAILED, BROWSER_JOB_CRASHED_SUMMARY)
