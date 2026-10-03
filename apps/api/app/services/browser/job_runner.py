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
    BROWSER_JOB_CRASHED_SUMMARY,
    BROWSER_JOB_WORKER_STOPPED_SUMMARY,
    BROWSER_NO_CHROME_HOST,
    BROWSER_RUN_CANCELLED_SUMMARY,
    BROWSER_TOOL_CATEGORY,
    BrowserEngine,
    BrowserRunFailure,
    BrowserSessionStatus,
    EngineFailure,
    HandoffStatus,
    SensitiveCategory,
)
from app.constants.log_tags import LogTag
from app.models.chat_models import SourceCategory
from app.models.stream_events import ToolOutputPayload
from app.schemas.browser import (
    BrowserActionOutput,
    BrowserCardSnapshot,
    BrowserHandoffSnapshot,
    BrowserResultSnapshot,
    BrowserSessionSnapshot,
    BrowserStepSnapshot,
    HandoffOutcome,
    HandoffRequest,
    NewHandoff,
)
from app.schemas.browser_job import (
    BrowserJobEnding,
    BrowserJobFinished,
    BrowserJobRequest,
    BrowserJobState,
    BrowserJobStatus,
)
from app.services.analytics_service import AnalyticsEvents, capture_event
from app.services.browser import host_client
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
from app.services.browser.job_events import JOB_TERMINAL_FRAME, card_frame, publish_job_event
from app.services.browser.job_teller import end_job
from app.services.browser.jobs import (
    clear_job_wait,
    job_cancel_requested,
    job_messages_waiting,
    put_job_state,
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
RecordFinishedFn = Callable[[BrowserResultSnapshot], Awaitable[BrowserJobEnding]]


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
            await self.end(snapshot)
        else:
            await self._show(snapshot)

    async def end(self, result: BrowserResultSnapshot) -> BrowserResultSnapshot:
        """Show the card the job ends on, as its ending of record says, and return it."""
        card = await self._ending_card(result)
        self.result = card
        await self._show(card)
        return card

    async def _show(self, snapshot: BrowserCardSnapshot) -> None:
        await self._publish(card_frame(snapshot))
        await self.thread_mirror.mirror(snapshot)
        if isinstance(snapshot, BrowserStepSnapshot):
            if snapshot.goal:
                self.step_goals[snapshot.index] = snapshot.goal
            if snapshot.screenshot is not None:
                self.step_shots[snapshot.index] = snapshot.screenshot
        if self._bot_delivery is not None:
            await _deliver_snapshot_to_bot(self._bot_delivery, snapshot)

    async def _ending_card(self, result: BrowserResultSnapshot) -> BrowserResultSnapshot:
        """Record that the run finished on result; return the card the job ends on, as its ending of record says.

        The run's end, a stop and the reaper race to record the one ending
        (jobs.record_ending): a run that lost to a stop is shown as stopped,
        since the stop already told the user.
        """
        recorded = await self._record_finished(result)
        if isinstance(recorded, BrowserJobFinished):
            return recorded.result
        if result.status is BrowserSessionStatus.CANCELLED:
            return result
        return result.model_copy(
            update={
                "status": BrowserSessionStatus.CANCELLED,
                "success": False,
                "summary": BROWSER_RUN_CANCELLED_SUMMARY,
            }
        )


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
        live_view_url=session.live_view_url,
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
    """Return the card the run ends on: the one it already ended on, else one the job writes now.

    Once a result card is out it is the run's result: a failure after it (a
    teardown, a cancel landing late) never puts a second, contradicting card
    on top. Carries the recap link a finished run gets once a session opened.
    """
    if emitter.result is not None:
        return emitter.result
    shots = [emitter.step_shots[index] for index in sorted(emitter.step_shots)]
    session_id = emitter.session_id
    return await emitter.end(
        BrowserResultSnapshot(
            status=status,
            success=False,
            summary=summary,
            replay_url=await create_replay_link(session_id, shots) if session_id else None,
        )
    )


async def close_job_feed(job_id: str) -> None:
    """Close the job's feed, once its last card is on it: what a follower of the feed stops on."""
    await publish_job_event(job_id, JOB_TERMINAL_FRAME)


async def _record_finished(
    request: BrowserJobRequest, result: BrowserResultSnapshot
) -> BrowserJobEnding:
    """Record that the run finished on result, told with it, unless the job's ending is recorded already.

    Kept with the decision, the result outlives a worker that dies before it
    publishes the card or closes the feed.
    """
    return await end_job(request.job_id, BrowserJobFinished(result=result))


def _emitter_for(request: BrowserJobRequest) -> ProgressEmitter:
    emit_frame = partial(publish_frame_to_job, request.job_id)
    return ProgressEmitter(
        emit_frame,
        BrowserThreadMirror(emit_frame, request.tool_call_id),
        _build_bot_delivery(request),
        partial(_record_finished, request),
    )


async def refuse_browser_job(request: BrowserJobRequest, summary: str) -> BrowserResultSnapshot:
    """End a job that must not run at all on a failure card, told like any ending."""
    result = await _end_on(_emitter_for(request), BrowserSessionStatus.FAILED, summary)
    await close_job_feed(request.job_id)
    return result


async def execute_browser_job(request: BrowserJobRequest) -> BrowserResultSnapshot:
    """Run one browser task end to end: its last card, its ending told, the end of its feed.

    Every ending publishes a terminal card and closes the feed, a cancellation
    included (a stop's abort, or the worker shutting down), which then propagates.
    """
    emitter = _emitter_for(request)
    # Pin this run's canvas/audio fingerprint to the user, so the same person
    # always presents the same device rather than a new one per task.
    seed_token = set_fingerprint_seed(request.user_id)
    try:
        result = await _run_job(request, emitter)
    except asyncio.CancelledError:
        log.fail(BrowserRunFailure.CANCELLED)
        # Nobody holds a tool call to hear this; without it the card stays RUNNING forever.
        await asyncio.shield(_end_cancelled(request, emitter))
        raise
    finally:
        reset_fingerprint_seed(seed_token)
    await close_job_feed(request.job_id)
    return result


async def _end_cancelled(request: BrowserJobRequest, emitter: ProgressEmitter) -> None:
    """End a job whose task was cancelled: on the card the run already ended on, else on a stopped one."""
    if await job_cancel_requested(request.job_id):
        await _end_on(emitter, BrowserSessionStatus.CANCELLED, BROWSER_RUN_CANCELLED_SUMMARY)
    else:
        await _end_on(emitter, BrowserSessionStatus.FAILED, BROWSER_JOB_WORKER_STOPPED_SUMMARY)
    await close_job_feed(request.job_id)


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
            await put_job_state(BrowserJobState.of(request, BrowserJobStatus.RUNNING))

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
                    note=emitter.note,
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
            returned = await runner.run(full_task)
            # The card the run ended on, as its ending of record left it: a stop that won makes it the stopped card.
            result = emitter.result or await emitter.end(returned)
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
