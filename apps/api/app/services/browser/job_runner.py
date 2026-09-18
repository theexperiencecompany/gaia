"""One browser task, run end to end with nothing of the request around it.

The process-agnostic half of the browser tool: no stream writer, no LangGraph
config, no tool result. Card snapshots go to an injected frame publisher (the
job's Redis feed in the worker, the turn's stream writer while the tool still
runs in-process), bots are mirrored here, and every failure becomes a terminal
result card because nobody is holding a tool call to hear an exception.
"""

import asyncio
from collections.abc import Awaitable, Callable
from functools import partial
from time import perf_counter
from typing import Any
import uuid

from app.config.settings import settings
from app.constants.browser import (
    BROWSER_TASK_EVENT,
    BROWSER_TOOL_CATEGORY,
    BrowserSessionStatus,
    HandoffStatus,
    SensitiveCategory,
)
from app.constants.log_tags import LogTag
from app.core.stream_manager import stream_manager
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
)
from app.schemas.browser_job import BrowserJobRequest, BrowserJobState, BrowserJobStatus
from app.services.analytics_service import AnalyticsEvents, capture_event
from app.services.browser.bot_delivery import BotProgressDelivery
from app.services.browser.exceptions import BrowserConcurrencyLimit, BrowserUnavailableError
from app.services.browser.fingerprint import reset_fingerprint_seed, set_fingerprint_seed
from app.services.browser.handoff import await_handoff, create_pending_handoff
from app.services.browser.job_events import publish_job_event
from app.services.browser.jobs import job_cancel_requested, put_job_state
from app.services.browser.llm import build_browser_llm
from app.services.browser.runner import (
    BrowserRunConfig,
    BrowserRunnerCallbacks,
    BrowserTaskRunner,
)
from app.services.browser.session import (
    BrowserHostSession,
    auto_resolve_handoff_on_navigation,
    browser_session,
    keep_session_alive,
)
from app.services.browser.tasks import BrowserTaskRecord, record_browser_task
from app.services.chat.chunks import normalize_custom_event
from app.utils.agent_utils import (
    SubagentStartDetails,
    format_browser_action_entry,
    format_subagent_end_event,
    format_subagent_start_event,
)
from app.utils.background_tasks import spawn_background_task
from shared.py.wide_events import log

#: Where one already-shaped stream frame goes: the job's feed, or the turn's own
#: writer while browser_task still runs the job in its own process.
FramePublisher = Callable[[dict[str, Any]], Awaitable[None]]

# Screenshots stream into the chat live, so the reply must never narrate them.
_NO_META = (
    "The step-by-step screenshots were already shown to the user in this chat, so do "
    "NOT mention screenshots, tools, steps, or 'browser vision'. Speak only to the outcome."
)


# The executor re-ran a finished task once because the tool result buried the
# run's answer; the answer now leads, and a failure says not to try again.
_FINISHED_LINE = "The browser task finished, and the text above is its own final answer."
_NO_RETRY = "Do not run the browser again for this request; tell the user what happened."


def agent_result_message(result: BrowserResultSnapshot) -> str:
    """Tell the assistant how to reply: confirm a real result, own a stop, or report a failure."""
    summary = result.summary.strip()
    if result.status == BrowserSessionStatus.COMPLETED and result.success:
        return (
            f"{summary or 'The task finished.'}\n\n"
            f"{_FINISHED_LINE} Reply with a short, natural confirmation of what you found "
            f"or did. {_NO_META}"
        )
    if result.status == BrowserSessionStatus.CANCELLED:
        return (
            "BROWSER TASK STOPPED BY THE USER before it finished. It did NOT complete, so "
            "there is no result and you must not claim one.\n\n"
            f"Briefly acknowledge you've stopped and ask if they'd like you to try again or "
            f"do something else. {_NO_META}"
        )
    return (
        f"BROWSER TASK DID NOT COMPLETE. Last state: {summary or 'the task could not be finished'}.\n\n"
        f"{_NO_RETRY} Tell the user honestly and briefly that it couldn't be finished, and why "
        f"if it's clear. Do not fabricate a result. {_NO_META}"
    )


async def publish_frame_to_job(job_id: str, payload: dict[str, Any]) -> None:
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
        self._group_id: str | None = None
        self._started_at = perf_counter()
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
        await self._publish({"tool_output": payload.model_dump(mode="json")})

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
        self._group_id = None


def _build_bot_delivery(request: BrowserJobRequest) -> BotProgressDelivery | None:
    is_bot = request.source_category == SourceCategory.BOT.value
    if not (is_bot and request.user_id and request.conversation_id):
        return None
    if request.conversation_source is None:
        return None
    return BotProgressDelivery(
        platform=request.conversation_source,
        user_id=request.user_id,
        conversation_id=request.conversation_id,
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
    handoff_id: str, req: HandoffRequest, session_id: str, user_id: str
) -> list[asyncio.Task[None]]:
    # The paused session produces no CDP/live-view traffic, so keep its idle
    # clock fresh until the user decides — otherwise the host reaps the browser
    # they were asked to come back to.
    watchers = [
        spawn_background_task(keep_session_alive(session_id), name="browser_handoff_keepalive")
    ]
    # A login handoff can auto-complete when the page navigates off the sign-in
    # URL — the user just signs in, no extra tap. Only for credentials; a
    # payment/confirmation has no such signal.
    if req.category == SensitiveCategory.CREDENTIALS:
        watchers.append(
            spawn_background_task(
                auto_resolve_handoff_on_navigation(handoff_id, session_id, user_id),
                name="browser_handoff_autoresolve",
            )
        )
    return watchers


async def _run_handoff(
    req: HandoffRequest,
    *,
    emit: Callable[[BrowserCardSnapshot], Awaitable[None]],
    session: BrowserHostSession,
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
    watchers = _spawn_handoff_watchers(handoff_id, req, session.session_id, user_id)
    try:
        outcome = await await_handoff(handoff_id, settings.BROWSER_USE_HANDOFF_TIMEOUT_SECONDS)
    finally:
        for watcher in watchers:
            watcher.cancel()
    await emit(_handoff_snapshot(handoff_id, req, session, outcome.status))
    return outcome


async def persist_run_outcome(
    request: BrowserJobRequest,
    *,
    session_id: str,
    result: BrowserResultSnapshot,
    run_t0: float,
    emitter: ProgressEmitter,
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
            "duration_ms": round((perf_counter() - run_t0) * 1000),
            "source": request.source_category or "web",
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
        step_goals=[emitter.step_goals.get(i, "") for i in range(1, result.steps + 1)],
        step_screenshots=[emitter.step_shots.get(i, "") for i in range(1, result.steps + 1)],
    )


async def _is_cancelled(request: BrowserJobRequest) -> bool:
    """Whether the user stopped this run, through the job itself or through the turn that asked for it."""
    if await job_cancel_requested(request.job_id):
        return True
    return bool(request.stream_id) and await stream_manager.is_cancelled(request.stream_id)


async def _terminal_failure(emitter: ProgressEmitter, summary: str) -> BrowserResultSnapshot:
    """End the run on a failure card: the job's result is the only thing anyone reads back."""
    result = BrowserResultSnapshot(
        status=BrowserSessionStatus.FAILED, success=False, summary=summary
    )
    await emitter.emit(result)
    return result


async def execute_browser_job(
    request: BrowserJobRequest, *, publish: FramePublisher | None = None
) -> BrowserResultSnapshot:
    """Run one browser task end to end, publishing cards to the job's feed and to bots.

    publish overrides where the frames go, which is how browser_task keeps
    streaming them straight onto its own turn until it becomes an enqueue.
    Raises nothing the caller must handle — every failure is a FAILED card.
    """
    emit_frame = publish or partial(publish_frame_to_job, request.job_id)
    thread_mirror = BrowserThreadMirror(emit_frame)
    emitter = ProgressEmitter(emit_frame, thread_mirror, _build_bot_delivery(request))

    try:
        llm = build_browser_llm()
    except BrowserUnavailableError as exc:
        log.warning(f"{LogTag.BROWSER} Browser LLM unavailable", error_type=type(exc).__name__)
        return await _terminal_failure(emitter, str(exc))

    # Pin this run's canvas/audio fingerprint to the user, so the same person
    # always presents the same device rather than a new one per task.
    seed_token = set_fingerprint_seed(request.user_id)

    full_task = (
        request.task
        if not request.start_url
        else f"{request.task}\n\nStart at: {request.start_url}"
    )

    try:
        async with browser_session(user_id=request.user_id, start_url=request.start_url) as session:
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
                llm=llm,
                callbacks=BrowserRunnerCallbacks(
                    emit=emitter.emit,
                    request_handoff=partial(
                        _run_handoff,
                        emit=emitter.emit,
                        session=session,
                        user_id=request.user_id,
                        conversation_id=request.conversation_id,
                    ),
                    is_cancelled=partial(_is_cancelled, request),
                    action_results=thread_mirror.results,
                ),
                config=BrowserRunConfig(
                    max_steps=settings.BROWSER_USE_MAX_STEPS,
                    max_actions_per_step=settings.BROWSER_USE_MAX_ACTIONS_PER_STEP,
                    task_timeout_seconds=settings.BROWSER_USE_TASK_TIMEOUT_SECONDS,
                    step_timeout_seconds=settings.BROWSER_USE_STEP_TIMEOUT_SECONDS,
                    handoff_timeout_seconds=settings.BROWSER_USE_HANDOFF_TIMEOUT_SECONDS,
                    stream_screenshots=settings.BROWSER_USE_STREAM_SCREENSHOTS,
                    solve_captcha=settings.BROWSER_USE_SOLVE_CAPTCHA,
                    flash_mode=settings.BROWSER_USE_FLASH_MODE,
                ),
                user_id=request.user_id or None,
                root_request_id=request.root_request_id,
            )
            run_t0 = perf_counter()
            result = await runner.run(full_task)
            await persist_run_outcome(
                request,
                session_id=session.session_id,
                result=result,
                run_t0=run_t0,
                emitter=emitter,
            )
            return result
    except BrowserConcurrencyLimit as exc:
        return await _terminal_failure(emitter, str(exc))
    except BrowserUnavailableError as exc:
        log.warning(f"{LogTag.BROWSER} Browser session unavailable", error_type=type(exc).__name__)
        return await _terminal_failure(emitter, str(exc))
    finally:
        reset_fingerprint_seed(seed_token)
