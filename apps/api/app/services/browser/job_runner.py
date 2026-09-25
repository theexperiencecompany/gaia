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
from urllib.parse import urlsplit
import uuid

from app.config.feature_flags import FeatureFlag
from app.config.settings import settings
from app.constants.browser import (
    BROWSER_AGENT_GUIDANCE_TIMEOUT_SECONDS,
    BROWSER_JOB_CRASHED_SUMMARY,
    BROWSER_TASK_EVENT,
    BROWSER_TOOL_CATEGORY,
    BrowserEngine,
    BrowserRunFailure,
    BrowserSessionStatus,
    HandoffKind,
    HandoffStatus,
    SensitiveCategory,
)
from app.constants.log_tags import LogTag
from app.core.stream_manager import stream_manager
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
from app.services.browser.exceptions import BrowserConcurrencyLimit, BrowserUnavailableError
from app.services.browser.fingerprint import reset_fingerprint_seed, set_fingerprint_seed
from app.services.browser.handoff import await_handoff, create_pending_handoff
from app.services.browser.jev.decision import goal_addresses
from app.services.browser.jev.secrets import RunSecrets
from app.services.browser.job_events import publish_job_event
from app.services.browser.jobs import (
    job_cancel_requested,
    job_messages_waiting,
    joiner_lease_held,
    put_job_state,
    take_job_messages,
)
from app.services.browser.replay import create_replay_link
from app.services.browser.run_failure import record_run_result
from app.services.browser.runner import (
    BrowserRunConfig,
    BrowserRunnerCallbacks,
    BrowserTaskRunner,
)
from app.services.browser.session import (
    BrowserHostSession,
    LiveSessionState,
    auto_resolve_handoff_on_navigation,
    browser_session,
    keep_session_alive,
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


def _redirect(notes: list[str]) -> str:
    """Lead with the instruction the user changed the request to, when they changed it mid-run.

    A trailing sentence lost to the model against the original request still in
    its own context: a run that read the headline closed with "the sign-in
    didn't finish", and a timed-out run blamed the user for a step they had
    cancelled. First line, before anything the run itself reported.
    """
    if not notes:
        return ""
    changed = ", then ".join(f'"{note}"' for note in notes)
    return (
        f"THE USER CHANGED THE REQUEST MID-RUN to: {changed}. Answer THAT, not the original "
        "request. The original request was not carried out and must not be reported as "
        "attempted-and-failed.\n\n"
    )


def agent_result_message(result: BrowserResultSnapshot) -> str:
    """Tell the assistant how to reply: confirm a real result, own a stop, or report a failure."""
    summary = result.summary.strip()
    redirect = _redirect(result.user_notes)
    if result.status == BrowserSessionStatus.COMPLETED and result.success:
        return (
            f"{redirect}{summary or 'The task finished.'}\n\n"
            f"{_FINISHED_LINE} Reply with a short, natural confirmation of what you found "
            f"or did. {_ONLY_THE_SUMMARY} {_NO_META}"
        )
    if result.status == BrowserSessionStatus.CANCELLED:
        return (
            f"{redirect}"
            "BROWSER TASK WAS STOPPED before it finished. It did NOT complete, so there is no "
            "result and you must not claim one. It was stopped either because the user asked, "
            "or because the request that started it ended early; never say the user stopped it "
            "unless the conversation shows they did.\n\n"
            f"Briefly say the browser task was stopped and ask if they'd like you to try again "
            f"or do something else. {_ONLY_THE_SUMMARY} {_NO_META}"
        )
    return (
        f"{redirect}"
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
    subagent's tool calls, instead of one opaque browser_task row.

    Stateful because only the session snapshot carries the session id, and the
    group id has to outlive it for the steps and the result that follow.
    """

    def __init__(self, publish: FramePublisher) -> None:
        self._publish = publish
        # "" reads as falsy exactly like None.
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
            await self._open(snapshot)
        elif isinstance(snapshot, BrowserStepSnapshot):
            await self._actions(snapshot)
        elif isinstance(snapshot, BrowserResultSnapshot):
            await self._close()

    async def _open(self, snapshot: BrowserSessionSnapshot) -> None:
        if self._group_id or not snapshot.session_id:
            return
        self._group_id = f"browser:{snapshot.session_id}"
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

    Records the CDN screenshots and captions the history recap reads back once
    the run finishes.
    """

    def __init__(
        self,
        publish: FramePublisher,
        thread_mirror: BrowserThreadMirror,
        bot_delivery: BotProgressDelivery | None,
    ) -> None:
        self._publish = publish
        self._thread_mirror = thread_mirror
        self._bot_delivery = bot_delivery
        # Captions for the recap ("what's going on" per step), keyed by step index.
        self.step_goals: dict[int, str] = {}
        # Only the screenshots that actually reached the CDN. A step whose upload
        # failed falls back to an inline data URL, which must not be stored as a
        # history frame — it would render as a permanently broken image.
        self.step_shots: dict[int, str] = {}

    async def note(self, text: str) -> None:
        """Send one plain line to a bot user; the web card has the live view to watch."""
        if self._bot_delivery is not None:
            await self._bot_delivery.note(text)

    async def emit(self, snapshot: BrowserCardSnapshot) -> None:
        await self._publish({BROWSER_TASK_EVENT: snapshot.model_dump(mode="json")})
        await self._thread_mirror.mirror(snapshot)
        if isinstance(snapshot, BrowserStepSnapshot):
            if snapshot.goal:
                self.step_goals[snapshot.index] = snapshot.goal
            if snapshot.screenshot and snapshot.screenshot.startswith("http"):
                self.step_shots[snapshot.index] = snapshot.screenshot
        if self._bot_delivery is not None:
            await _deliver_snapshot_to_bot(self._bot_delivery, snapshot)


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
    )


def _spawn_handoff_watchers(
    handoff_id: str, req: HandoffRequest, session: BrowserHostSession, user_id: str
) -> list[asyncio.Task[None]]:
    # The paused session produces no CDP/live-view traffic, so keep its idle
    # clock fresh until the user decides — otherwise the host reaps the browser
    # they were asked to come back to.
    watchers = [
        spawn_background_task(keep_session_alive(session), name="browser_handoff_keepalive")
    ]
    # A login handoff can auto-complete when the page navigates off the sign-in
    # URL — the user just signs in, no extra tap. Only for credentials; a
    # payment/confirmation has no such signal.
    if req.category == SensitiveCategory.CREDENTIALS:
        watchers.append(
            spawn_background_task(
                auto_resolve_handoff_on_navigation(handoff_id, session, user_id),
                name="browser_handoff_autoresolve",
            )
        )
    return watchers


async def _run_handoff(
    req: HandoffRequest,
    session: BrowserHostSession,
    *,
    emit: Callable[[BrowserCardSnapshot], Awaitable[None]],
    user_id: str,
    conversation_id: str,
) -> HandoffOutcome:
    """Pause the run and hand the user a live view to complete the step themselves.

    Returns the outcome (completed with optional note, cancelled, or timed out)
    so the loop resumes natively.
    """
    handoff_id = uuid.uuid4().hex
    await create_pending_handoff(handoff_id, user_id, conversation_id, req.reason)
    await emit(_handoff_snapshot(handoff_id, req, session, HandoffStatus.PENDING))
    watchers = _spawn_handoff_watchers(handoff_id, req, session, user_id)
    try:
        outcome = await await_handoff(handoff_id, settings.BROWSER_USE_HANDOFF_TIMEOUT_SECONDS)
    finally:
        for watcher in watchers:
            watcher.cancel()
    log.set_ns(
        "browser",
        handoff_kind=HandoffKind.USER.value,
        handoff_category=req.category.value,
        handoff_result=outcome.status.value,
    )
    if outcome.status == HandoffStatus.COMPLETED and req.category == SensitiveCategory.CREDENTIALS:
        page = await host_client.get_session(session.session_id, session.host_url)
        session.mark_authenticated(page.url)
    await emit(_handoff_snapshot(handoff_id, req, session, outcome.status))
    return outcome


async def _open_fallback_session(
    sessions: contextlib.AsyncExitStack,
    user_id: str,
    host_url: str,
    url: str | None,
    carried: LiveSessionState | None,
) -> BrowserHostSession:
    """Open a session on the fallback host for url, seeded with carried; released with the job's other sessions."""
    return await sessions.enter_async_context(
        browser_session(user_id=user_id, host_url=host_url, start_url=url, carried=carried)
    )


async def _run_guidance(
    request: AgentGuidanceRequest,
    *,
    job_id: str,
    user_id: str,
    conversation_id: str,
) -> HandoffOutcome:
    """Pause the run and ask the joined agent for one instruction.

    Deliberately silent to the user: an AGENT handoff takes no conversation key
    and emits no card, so their only sign of it is the step frame's caption.
    """
    handoff_id = uuid.uuid4().hex
    await create_pending_handoff(
        handoff_id, user_id, conversation_id, request.reason, kind=HandoffKind.AGENT
    )
    await put_guidance_request(job_id, PendingAgentGuidance(handoff_id=handoff_id, request=request))
    try:
        outcome = await await_handoff(handoff_id, BROWSER_AGENT_GUIDANCE_TIMEOUT_SECONDS)
    finally:
        await clear_guidance_request(job_id)
    log.set_ns("browser", guidance_result=outcome.status.value)
    return outcome


async def persist_run_outcome(
    request: BrowserJobRequest,
    *,
    session_id: str,
    result: BrowserResultSnapshot,
    actions: int,
    run_t0: float,
    emitter: ProgressEmitter,
    engine_fallback: bool,
) -> None:
    """Record analytics + the browser-history row for a finished run.

    A job has no authenticated request context, so the id must be explicit or
    the event lands on an anonymous profile (see analytics conventions in
    CLAUDE.md). The history write is awaited rather than spawned: in the worker
    the task body is the lifetime, and a fire-and-forget write dies with it.
    """
    if not request.user_id:
        return
    capture_event(
        request.user_id,
        AnalyticsEvents.BROWSER_TASK_FINISHED,
        {
            "status": result.status.value,
            "success": result.success,
            "steps": result.steps,
            "actions": actions,
            "duration_ms": round((perf_counter() - run_t0) * 1000),
            "source": request.source_category or "web",
            # With success, says whether the fallback engine recovered a run
            # the primary could not finish, and so points at engine gaps.
            "engine_fallback": engine_fallback,
        },
    )
    await record_browser_task(
        BrowserTaskRecord(
            user_id=request.user_id,
            conversation_id=request.conversation_id,
            task=request.task,
            session_id=session_id,
            source=request.conversation_source.value if request.conversation_source else "",
        ),
        result,
        actions=actions,
        step_goals=[emitter.step_goals.get(i, "") for i in range(1, result.steps + 1)],
        step_screenshots=[emitter.step_shots.get(i, "") for i in range(1, result.steps + 1)],
    )


def hosts_for(engine: BrowserEngine) -> tuple[str, str | None]:
    """Return the host a run on engine opens on, and the Chrome host it falls back to (Obscura only).

    BROWSER_HOST_URL is the host running BROWSER_ENGINE; BROWSER_FALLBACK_HOST_URL
    is a Chromium host. Chrome is the default engine, Obscura an opt-in one.
    """
    primary_is_chrome = settings.BROWSER_ENGINE is BrowserEngine.CHROMIUM
    chrome_host = (
        settings.BROWSER_HOST_URL if primary_is_chrome else settings.BROWSER_FALLBACK_HOST_URL
    )
    if engine is BrowserEngine.OBSCURA and not primary_is_chrome:
        return settings.BROWSER_HOST_URL, chrome_host
    if chrome_host is None:
        raise BrowserUnavailableError(
            "No Chrome browser host is configured (BROWSER_FALLBACK_HOST_URL)."
        )
    return chrome_host, None


async def _is_cancelled(request: BrowserJobRequest) -> bool:
    """Whether the user stopped this run, through the job itself or through the turn that asked for it."""
    if await job_cancel_requested(request.job_id):
        return True
    return bool(request.stream_id) and await stream_manager.is_cancelled(request.stream_id)


async def _terminal_failure(
    emitter: ProgressEmitter, summary: str, session_id: str | None = None
) -> BrowserResultSnapshot:
    """End the run on a failure card: the job's result is the only thing anyone reads back.

    Carries the same recap link a finished run gets when a session got far
    enough to produce screenshots; None when the browser never opened.
    """
    shots = [emitter.step_shots[index] for index in sorted(emitter.step_shots)]
    result = BrowserResultSnapshot(
        status=BrowserSessionStatus.FAILED,
        success=False,
        summary=summary,
        replay_url=await create_replay_link(session_id, shots) if session_id else None,
    )
    await emitter.emit(result)
    return result


async def execute_browser_job(request: BrowserJobRequest) -> BrowserResultSnapshot:
    """Run one browser task end to end, publishing cards to the job's feed and to bots.

    Every ending publishes a terminal card first: no failure reaches the caller
    as a bare exception, and a cancellation emits its card before propagating.
    """
    emit_frame = partial(publish_frame_to_job, request.job_id)
    thread_mirror = BrowserThreadMirror(emit_frame)
    emitter = ProgressEmitter(
        emit_frame,
        thread_mirror,
        _build_bot_delivery(request),
    )

    engine = (
        BrowserEngine.OBSCURA
        if await is_enabled(FeatureFlag.BROWSER_OBSCURA, request.user_id)
        else BrowserEngine.CHROMIUM
    )
    try:
        host_url, fallback_host = hosts_for(engine)
    except BrowserUnavailableError as exc:
        log.fail(BrowserRunFailure.HOST_UNAVAILABLE)
        return await _terminal_failure(emitter, str(exc))
    log.set_ns("browser", engine=engine.value)
    secrets = RunSecrets(
        request.secrets,
        sites=[
            host
            for url in (request.start_url, *goal_addresses(request.task))
            if url and (host := urlsplit(url).hostname)
        ],
    )

    # Pin this run's canvas/audio fingerprint to the user, so the same person
    # always presents the same device rather than a new one per task.
    seed_token = set_fingerprint_seed(request.user_id)

    full_task = (
        request.task
        if not request.start_url
        else f"{request.task}\n\nStart at: {request.start_url}"
    )

    # "" reads as falsy exactly like None.
    session_id: str | None = None  # pragma: no mutate

    try:
        async with contextlib.AsyncExitStack() as sessions:
            session = await sessions.enter_async_context(
                browser_session(
                    user_id=request.user_id,
                    host_url=host_url,
                    start_url=request.start_url,
                )
            )
            session_id = session.session_id
            log.set(browser={"session_id": session.session_id})
            await put_job_state(
                BrowserJobState(
                    job_id=request.job_id,
                    status=BrowserJobStatus.RUNNING,
                    task=request.task,
                    session_id=session.session_id,
                    live_view_url=session.live_view_url,
                )
            )

            runner = BrowserTaskRunner(
                session=session,
                secrets=secrets,
                callbacks=BrowserRunnerCallbacks(
                    emit=emitter.emit,
                    request_handoff=partial(
                        _run_handoff,
                        emit=emitter.emit,
                        user_id=request.user_id,
                        conversation_id=request.conversation_id,
                    ),
                    open_fallback_session=(
                        partial(_open_fallback_session, sessions, request.user_id, fallback_host)
                        if fallback_host
                        else None
                    ),
                    is_cancelled=partial(_is_cancelled, request),
                    user_waiting=partial(job_messages_waiting, request.job_id),
                    take_user_messages=partial(take_job_messages, request.job_id),
                    action_results=thread_mirror.results,
                    agent_joined=partial(joiner_lease_held, request.job_id),
                    note=emitter.note,
                    request_guidance=partial(
                        _run_guidance,
                        job_id=request.job_id,
                        user_id=request.user_id,
                        conversation_id=request.conversation_id,
                    ),
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
            result = await runner.run(full_task)
            record_run_result(
                result,
                actions=runner.ledger.action_count,
                engine_fallback=runner.used_fallback,
                run_ms=round((perf_counter() - run_t0) * 1000),
            )
            await persist_run_outcome(
                request,
                session_id=runner.session.session_id,
                result=result,
                actions=runner.ledger.action_count,
                run_t0=run_t0,
                emitter=emitter,
                engine_fallback=runner.used_fallback,
            )
            return result
    except BrowserConcurrencyLimit as exc:
        log.warning(f"{LogTag.BROWSER} Browser host at capacity", error=str(exc))
        log.fail(BrowserRunFailure.HOST_AT_CAPACITY)
        return await _terminal_failure(emitter, str(exc), session_id)
    except BrowserUnavailableError as exc:
        log.warning(
            f"{LogTag.BROWSER} Browser session unavailable",
            error_type=type(exc).__name__,
            error=str(exc),
        )
        log.fail(BrowserRunFailure.HOST_UNAVAILABLE)
        return await _terminal_failure(emitter, str(exc), session_id)
    except asyncio.CancelledError:
        log.fail(BrowserRunFailure.CANCELLED)
        # Nobody holds a tool call to hear this; without it the card stays RUNNING forever.
        await asyncio.shield(
            _terminal_failure(
                emitter, "the browser task was stopped before it finished", session_id
            )
        )
        raise
    except Exception as exc:
        log.error(
            f"{LogTag.BROWSER} Browser job crashed",
            error_type=type(exc).__name__,
            error=str(exc),
            browser={"job_id": request.job_id},
            exc_info=True,
        )
        log.fail(BrowserRunFailure.RUN_CRASHED)
        return await _terminal_failure(emitter, BROWSER_JOB_CRASHED_SUMMARY, session_id)
    finally:
        reset_fingerprint_seed(seed_token)
