"""Browser task orchestration, the agent layer.

Run one browser task against an already-created browser-host session through
injected seams: emit (card snapshots to UI and bots), request_handoff (pause
for the human in live-view) and is_cancelled (cooperative cancellation).
Deciding and executing steps is the agent run's job; the runner owns progress,
handoff, cancellation, budgets, metering and the replay link, and never judges
whether a step is sensitive: the agent calls the takeover hook itself.
"""

from __future__ import annotations

import asyncio
import base64
from collections.abc import Awaitable, Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, replace
from hashlib import sha256
from time import perf_counter
from typing import Any
from urllib.parse import urlsplit

from browser_use.agent.views import AgentState

from app.constants.browser import (
    BROWSER_CDP_ATTACH_FAILED,
    BROWSER_CDP_ATTACH_HINT,
    BROWSER_ENGINE_FALLBACK_NOTE,
    BROWSER_ENGINE_FALLBACK_WITHOUT_STATE_NOTE,
    BROWSER_ENGINE_SWITCH_ACK,
    BROWSER_ENGINE_UNRESPONSIVE_SUMMARY,
    BROWSER_RUN_CANCELLED_SUMMARY,
    BROWSER_RUN_CRASHED_SUMMARY,
    BROWSER_RUN_DONE_SUMMARY,
    BROWSER_RUN_FOUND_NOTE,
    BROWSER_RUN_HANDOFF_LIMIT_SUMMARY,
    BROWSER_RUN_HANDOFF_TIMED_OUT,
    BROWSER_RUN_NOT_DONE_SUMMARY,
    BROWSER_RUN_SESSION_LOST_SUMMARY,
    BROWSER_RUN_STOPPED_SUMMARY,
    BROWSER_RUN_WALL_CLOCK_SUMMARY,
    BROWSER_RUN_WORK_BUDGET_SUMMARY,
    BROWSER_STALL_NOTE,
    BROWSER_STALL_NOTE_AFTER_SECONDS,
    MAX_HANDOFFS_PER_TASK,
    BrowserRunFailure,
    BrowserSessionStatus,
    EngineFailure,
    EngineSwitchReason,
    HandoffStatus,
    SensitiveCategory,
    StateCarry,
)
from app.constants.log_tags import LogTag
from app.schemas.browser import (
    BrowserCardSnapshot,
    BrowserResultSnapshot,
    BrowserSessionSnapshot,
    BrowserStepSnapshot,
    HandoffOutcome,
    HandoffRequest,
)
from app.services.analytics_service import capture
from app.services.browser.agent_run import AgentRunSetup, BrowserAgentRun
from app.services.browser.engine_watchdog import run_watched
from app.services.browser.exceptions import BrowserHandoffCancelled, BrowserUnavailableError
from app.services.browser.jev.secrets import RunSecrets
from app.services.browser.job_lifetime import run_wall_clock_seconds
from app.services.browser.ledger import ModelCall, RunLedger
from app.services.browser.replay import create_replay_link
from app.services.browser.run_contract import (
    ActionResultsFn,
    BrowserRunConfig,
    FlagFn,
    RunHooks,
    RunOutcome,
    StepFrame,
    TakeMessagesFn,
)
from app.services.browser.screenshots import publish_step_screenshot
from app.services.browser.session import (
    BrowserHostSession,
    LiveSessionState,
    engine_failure,
    hand_over_state,
)
from app.services.cost_budget import get_budget_stop_reason
from app.services.llm_metering import LLMCallContext, TokenUsage, record_llm_call
from app.utils.background_tasks import spawn_background_task
from shared.py.analytics import UserId
from shared.py.analytics.catalog.browser import BrowserEngineSwitched
from shared.py.wide_events import log

# How often the stall watcher looks; a fraction of the note delay, not a knob.
_STALL_POLL_SECONDS = 1.0

EmitFn = Callable[[BrowserCardSnapshot], Awaitable[None]]
RequestHandoffFn = Callable[[HandoffRequest, BrowserHostSession], Awaitable[HandoffOutcome]]
OpenFallbackSessionFn = Callable[
    [str | None, LiveSessionState | None], Awaitable[BrowserHostSession]
]
IsCancelledFn = Callable[[], Awaitable[bool]]
NoteFn = Callable[[str], Awaitable[None]]

__all__ = [
    "ActionResultsFn",
    "BrowserRunConfig",
    "BrowserRunnerCallbacks",
    "BrowserTaskRunner",
]


@dataclass(frozen=True)
class RunEnd:
    """How a run ended: its card's status, the summary read, and why it did not succeed (None when it did)."""

    status: BrowserSessionStatus
    summary: str
    failure: BrowserRunFailure | None


_CANCELLED = RunEnd(
    BrowserSessionStatus.CANCELLED, BROWSER_RUN_CANCELLED_SUMMARY, BrowserRunFailure.CANCELLED
)
_STOPPED = RunEnd(
    BrowserSessionStatus.CANCELLED, BROWSER_RUN_STOPPED_SUMMARY, BrowserRunFailure.CANCELLED
)
#: How a handoff the user did not finish ends the run; any other status is a plain stop.
_HANDOFF_ENDS = {
    HandoffStatus.TIMEOUT: RunEnd(
        BrowserSessionStatus.FAILED,
        BROWSER_RUN_HANDOFF_TIMED_OUT,
        BrowserRunFailure.HANDOFF_TIMEOUT,
    ),
    HandoffStatus.FAILED: RunEnd(
        BrowserSessionStatus.FAILED,
        BROWSER_RUN_SESSION_LOST_SUMMARY,
        BrowserRunFailure.SESSION_LOST,
    ),
}


@dataclass(frozen=True)
class BrowserRunnerCallbacks:
    """The runner's injected seams — how it streams progress, pauses for the human, checks cancellation, and mirrors per-action results into the thread."""

    #: Where the run records its model calls, actions and Jev bursts, for the job to read back.
    ledger: RunLedger
    emit: EmitFn
    request_handoff: RequestHandoffFn
    is_cancelled: IsCancelledFn
    #: The user's mid-task messages: whether any wait, and taking them.
    user_waiting: FlagFn
    take_user_messages: TakeMessagesFn
    action_results: ActionResultsFn | None = None
    #: One plain line to the user when a step has shown nothing for a while.
    note: NoteFn | None = None
    #: Opens a fallback-engine session at a url (none when no page was read),
    #: seeded with the primary's live state when it could give it. Absent when
    #: the run has no fallback engine: an engine-failed run then just ends failed.
    open_fallback_session: OpenFallbackSessionFn | None = None


class BrowserTaskRunner:
    """Orchestrates one browser task: session, agent run, handoffs, delivery."""

    def __init__(
        self,
        *,
        session: BrowserHostSession,
        callbacks: BrowserRunnerCallbacks,
        config: BrowserRunConfig,
        secrets: RunSecrets,
        user_id: str | None = None,
        root_request_id: str | None = None,
    ) -> None:
        self._session = session
        self._secrets = secrets
        self._callbacks = callbacks
        self._emit = callbacks.emit
        self._request_handoff = callbacks.request_handoff
        self._is_cancelled = callbacks.is_cancelled
        self._action_results = callbacks.action_results
        self._note = callbacks.note
        self._open_fallback_session = callbacks.open_fallback_session
        #: Whether the run moved to the fallback engine, for a page it could not pass
        #: or an engine that failed under it.
        self.used_fallback = False
        #: How the primary engine failed under the run, when it did; its session
        #: then has no state left to carry to the fallback.
        self._engine_failure: EngineFailure | None = None
        #: Why the agent asked to move the run to the full browser, when it did.
        self._engine_switch: EngineSwitchReason | None = None
        self._config = config
        self._task_timeout = config.task_timeout_seconds
        # Every permitted handoff wait on top of the active-work budget, so
        # waiting on the user is never starved by a timeout.
        self._wall_clock_timeout = run_wall_clock_seconds(
            config.task_timeout_seconds, config.handoff_timeout_seconds
        )
        self._user_id = user_id
        self._root_request_id = root_request_id
        #: Every model call, action and Jev burst of the run; each call is metered the moment it lands.
        self.ledger = callbacks.ledger
        self.ledger.on_call = self._meter
        self._started_at = perf_counter()
        #: Seconds spent waiting on the user: the task budget does not run then.
        self._waited = 0.0
        #: How a hook or a bound ended the run, set once: the first ending is the one it had.
        self._end: RunEnd | None = None
        #: Why the run did not succeed, set when it ends; None when it succeeded.
        self.failure: BrowserRunFailure | None
        #: What the user said while the run went: messages and handoff notes, in order.
        self._user_notes: list[str] = []
        #: The notes among them the reply classifier read as replacing the request.
        self._redirects: list[str] = []
        #: What agents on engines the run already left had gathered.
        self._found_before: list[str] = []
        self._handoffs = 0
        self._last_step = 0
        # CDN URLs that really uploaded, in step order — the recap's frames.
        self._shots: list[str] = []
        # Step emits run off the agent's loop; the lock keeps them ordered and the
        # set lets _finish() flush them before the result (see _record_step / _finish).
        self._emit_lock = asyncio.Lock()
        self._emit_tasks: set[asyncio.Task[Any]] = set()
        self._last_frame_at = perf_counter()
        # None reads as falsy exactly like False.
        self._stall_noted = False  # pragma: no mutate
        # Waiting on the user is not a stall; the watcher stands down.
        self._waiting_on_someone = False  # pragma: no mutate
        self._agent_run = self._build_agent_run()

    @property
    def session(self) -> BrowserHostSession:
        """The browser session the run is on now; the fallback's after a switch."""
        return self._session

    def _build_agent_run(self, resumed_from: AgentState | None = None) -> BrowserAgentRun:
        hooks = RunHooks(
            step=self._record_step,
            takeover=self._handle_takeover,
            should_stop=self._should_stop,
            user_waiting=self._callbacks.user_waiting,
            take_user_messages=self._take_user_messages,
            action_results=self._action_results,
            # Only on the fast engine: a run already on the fallback has nowhere to move.
            switch_engine=(
                self._handle_engine_switch
                if self._open_fallback_session is not None and not self.used_fallback
                else None
            ),
        )
        return BrowserAgentRun(
            session=self._session,
            config=self._config,
            hooks=hooks,
            setup=AgentRunSetup(
                user_id=self._user_id,
                ledger=self.ledger,
                secrets=self._secrets,
                steps_before=self._last_step,
                resumed_from=resumed_from,
            ),
        )

    async def run(self, task: str) -> BrowserResultSnapshot:
        """Run the task to completion and return the final result snapshot."""
        await self._emit(
            BrowserSessionSnapshot(
                task=task,
                status=BrowserSessionStatus.RUNNING,
                session_id=self._session.session_id,
            )
        )

        stall_watch = spawn_background_task(self._watch_for_stalls(), name="browser_stall_watch")
        try:
            try:
                outcome = await asyncio.wait_for(
                    self._execute(task), timeout=self._wall_clock_timeout
                )
            except TimeoutError:
                self._agent_run.stop()
                return await self._finish_unanswered(
                    RunEnd(
                        BrowserSessionStatus.FAILED,
                        BROWSER_RUN_WALL_CLOCK_SUMMARY.format(seconds=self._wall_clock_timeout),
                        BrowserRunFailure.TASK_TIMEOUT,
                    )
                )
            except BrowserUnavailableError:
                raise
            except Exception as exc:
                if not self._agent_run.connected:
                    # The host made the session but the agent never attached: almost
                    # always the host's CDP proxy is not reachable from here.
                    log.error(
                        f"{LogTag.BROWSER} Browser agent could not attach over CDP",
                        error_type=type(exc).__name__,
                        error=str(exc),
                        hint=BROWSER_CDP_ATTACH_HINT,
                        browser={"session_id": self._session.session_id},
                    )
                    raise BrowserUnavailableError(BROWSER_CDP_ATTACH_FAILED) from exc
                # An unexpected failure must not leave the card RUNNING; the
                # exception is for the logs, the user reads a fixed line.
                log.error(
                    f"{LogTag.BROWSER} Browser agent failed unexpectedly",
                    error_type=type(exc).__name__,
                    error=str(exc),
                    browser={"session_id": self._session.session_id},
                )
                return await self._finish(
                    RunEnd(
                        BrowserSessionStatus.FAILED,
                        BROWSER_RUN_CRASHED_SUMMARY,
                        BrowserRunFailure.RUN_CRASHED,
                    )
                )

            return await self._finish_after_execute(outcome)
        finally:
            stall_watch.cancel()

    async def _execute(self, task: str) -> RunOutcome:
        """Run the agent; finish on the fallback engine, once, when the primary engine failed under the run.

        While the run is on a primary that has a fallback, a watchdog reads the
        engine's liveness, so a frozen engine moves the run in seconds, not after
        Browser-Use's own timeouts give out.
        """
        if self._open_fallback_session is None:
            return await self._agent_run.execute(task)
        try:
            ended = await run_watched(
                self._agent_run, task, self._session, paused=lambda: self._waiting_on_someone
            )
        except Exception as exc:
            # Browser-Use raises only when it cannot attach at all; the host says
            # whether that was the engine or something the fallback would not fix.
            if not await self._engine_failed_under_run():
                raise
            log.warning(
                f"{LogTag.BROWSER} Browser agent could not run on the failed engine",
                error_type=type(exc).__name__,
                browser={"session_id": self._session.session_id},
            )
            return await self._resume_on_fallback(task, self._open_fallback_session)
        if self._engine_switch is not None or isinstance(ended, EngineFailure):
            if await self._should_stop():
                # Never read: _finish_after_execute judges the stop before the outcome.
                return RunOutcome(False, BROWSER_ENGINE_UNRESPONSIVE_SUMMARY)  # pragma: no mutate
            if isinstance(ended, EngineFailure):
                self._fall_back_after_engine_failure(ended)
            return await self._resume_on_fallback(task, self._open_fallback_session)
        if not ended.success and await self._engine_failed_under_run():
            return await self._resume_on_fallback(task, self._open_fallback_session)
        return ended

    async def _handle_engine_switch(self, reason: EngineSwitchReason, url: str | None) -> str:
        """Record why the run leaves the fast engine (the agent's call, a bot check, a script it cannot run); the run resumes on the full one."""
        self._engine_switch = reason
        host = urlsplit(url).hostname if url else None
        log.set_ns("browser", engine_switch=reason.value, engine_switch_host=host)
        log.info(f"{LogTag.BROWSER} Browser agent moved the run to the full browser")
        if self._user_id:
            # The host alone: which sites the fast engine falls short on, never what the user opened.
            capture(
                UserId(self._user_id),
                BrowserEngineSwitched(
                    reason=reason.value, host=host, engine=self._session.engine.value
                ),
            )
        return BROWSER_ENGINE_SWITCH_ACK

    async def _engine_failed_under_run(self) -> bool:
        """Whether the primary engine itself failed the run; a run the user stopped or a handoff ended is never retried."""
        if await self._should_stop():
            return False
        failure = await engine_failure(self._session)
        if failure is None:
            return False
        self._fall_back_after_engine_failure(failure)
        return True

    def _fall_back_after_engine_failure(self, failure: EngineFailure) -> None:
        self._engine_failure = failure
        log.warning(
            f"{LogTag.BROWSER} Browser engine failed under the run",
            browser={"session_id": self._session.session_id, "operation": "engine_failure"},
            engine_failure=failure.value,
        )
        log.set_ns("browser", fallback_reason=failure.value)

    async def _resume_on_fallback(
        self, task: str, open_session: OpenFallbackSessionFn
    ) -> RunOutcome:
        """Open the fallback engine on the last page the run was seen on and go on from there, its history kept."""
        url = self._agent_run.last_url or self._config.start_url
        self._config = replace(self._config, start_url=url)
        log.info(
            f"{LogTag.BROWSER} Browser run moving to the fallback engine",
            browser={
                "session_id": self._session.session_id,
                "operation": "engine_fallback",
                "resume_url": self._secrets.redact(url)[:120] if url is not None else None,
            },
        )
        log.set_ns("browser", primary_session_id=self._session.session_id)
        carried = await self._primary_state()
        self._session = await open_session(url, carried)
        self.used_fallback = True
        await self._emit(
            BrowserSessionSnapshot(
                task=task,
                status=BrowserSessionStatus.RUNNING,
                session_id=self._session.session_id,
            )
        )
        if self._note is not None:
            await self._note(
                BROWSER_ENGINE_FALLBACK_NOTE
                if carried is not None
                else BROWSER_ENGINE_FALLBACK_WITHOUT_STATE_NOTE
            )
        # Continues the step count, so the fallback's first step follows the
        # primary's last on the card, in the recap and in the history.
        self._found_before.extend(self._agent_run.found())
        self._agent_run = self._build_agent_run(resumed_from=self._agent_run.agent_state)
        return await self._agent_run.execute(task)

    async def _primary_state(self) -> LiveSessionState | None:
        """Read the primary's live state for the fallback, or None when its engine cannot give it; the wide event says which."""
        state: LiveSessionState | None = None
        if self._engine_failure is not None:
            carry = StateCarry.ENGINE_FAILED
        else:
            try:
                state = await hand_over_state(self._session)
                carry = StateCarry.CARRIED
            except BrowserUnavailableError as exc:
                carry = StateCarry.UNREADABLE
                log.warning(
                    f"{LogTag.BROWSER} Could not read the primary browser's state to carry over",
                    error_type=type(exc).__name__,
                    browser={
                        "session_id": self._session.session_id,
                        "operation": "hand_over_state",
                    },
                )
        log.set_ns("browser", state_carry=carry.value)
        return state

    async def _finish_after_execute(self, outcome: RunOutcome) -> BrowserResultSnapshot:
        """Judge a run whose agent loop returned: a stop first, then how a hook or a bound ended it.

        A handoff that ends the run reaches the agent as an error result, so the
        loop returns normally and only the run's ending knows. A stop wins over
        it: the wait it cut short would otherwise read as blocked or timed out.
        """
        if await self._is_cancelled():
            return await self._finish_unanswered(_CANCELLED)
        if self._end is not None:
            return await self._finish_unanswered(self._end)
        return await self._finish_from_outcome(outcome)

    def _end_with(self, end: RunEnd) -> None:
        """End the run this way unless something already ended it: the first ending stands."""
        if self._end is None:
            self._end = end

    async def _should_stop(self) -> bool:
        """Whether the run must end now: ended, cancelled, or past its time or cost budget."""
        if self._end is not None or await self._is_cancelled():
            return True
        active = perf_counter() - self._started_at - self._waited
        if active > self._task_timeout:
            self._end_with(
                RunEnd(
                    BrowserSessionStatus.FAILED,
                    BROWSER_RUN_WORK_BUDGET_SUMMARY.format(seconds=self._task_timeout),
                    BrowserRunFailure.TASK_TIMEOUT,
                )
            )
            return True
        check = await get_budget_stop_reason(self._user_id, None, self._root_request_id)
        if check.stop_reason is not None:
            self._end_with(
                RunEnd(
                    BrowserSessionStatus.FAILED, check.stop_reason, BrowserRunFailure.COST_BUDGET
                )
            )
            return True
        return False

    @contextmanager
    def _waiting(self) -> Iterator[None]:
        """Wait on the user: no stall note meanwhile, and the work budget does not run."""
        self._waiting_on_someone = True
        since = perf_counter()
        try:
            yield
        finally:
            # None reads as falsy exactly like False.
            self._waiting_on_someone = False  # pragma: no mutate
            self._last_frame_at = perf_counter()
            self._waited += self._last_frame_at - since

    async def _take_user_messages(self) -> list[str]:
        """Take what the user said mid-task, kept for the result too: the reply weighs what they said last."""
        messages = await self._callbacks.take_user_messages()
        self._user_notes.extend(messages)
        return messages

    def _meter(self, call: ModelCall) -> None:
        """Record one model call's spend now, so the user's budget sees the run as it goes."""
        spawn_background_task(
            record_llm_call(
                user_id=self._user_id,
                model_name=call.model,
                usage=TokenUsage(
                    input_tokens=call.input_tokens,
                    output_tokens=call.output_tokens,
                    cached_tokens=call.cached_tokens,
                    reasoning_tokens=0,
                ),
                root_request_id=self._root_request_id,
                provider_cost=call.cost_usd,
                context=LLMCallContext(
                    agent_name="browser_task", background=False, charge_to_budget=True
                ),
            ),
            name="browser_meter_call",
        )

    async def _handle_takeover(self, reason: str, category: SensitiveCategory) -> str | None:
        """Pause for the human (the agent's takeover hook) and return the note they left, if any.

        Raises to stop the run on cancel, timeout, one handoff past the limit, or a run already over."""
        await self._refuse_wait_when_stopping()
        self._handoffs += 1
        if self._handoffs > MAX_HANDOFFS_PER_TASK:
            self._end_with(
                RunEnd(
                    BrowserSessionStatus.FAILED,
                    BROWSER_RUN_HANDOFF_LIMIT_SUMMARY.format(limit=MAX_HANDOFFS_PER_TASK),
                    BrowserRunFailure.HANDOFF_LIMIT,
                )
            )
            raise BrowserHandoffCancelled("max-handoffs")

        with self._waiting():
            outcome = await self._request_handoff(
                HandoffRequest(category=category, reason=reason), self._session
            )
        if outcome.status == HandoffStatus.COMPLETED:
            log.info(f"{LogTag.BROWSER} Browser takeover completed by user; agent continuing.")
            note = (outcome.message or "").strip() or None
            if note:
                self._user_notes.append(note)
                if outcome.redirect:
                    self._redirects.append(note)
            return note
        self._end_with(_HANDOFF_ENDS.get(outcome.status, _STOPPED))
        if outcome.status == HandoffStatus.FAILED:
            log.set_ns("browser", handoff_failure=outcome.cause)
        log.info(f"{LogTag.BROWSER} Browser takeover ended", status=outcome.status.value)
        raise BrowserHandoffCancelled(outcome.status.value)

    async def _refuse_wait_when_stopping(self) -> None:
        """Raise before asking anyone anything once the run must end: nobody is to wait on a run that is over."""
        if await self._should_stop():
            raise BrowserHandoffCancelled(BROWSER_RUN_STOPPED_SUMMARY)

    async def _watch_for_stalls(self) -> None:
        """Say once, per silence, how long no frame has shown."""
        while True:
            await asyncio.sleep(_STALL_POLL_SECONDS)
            quiet_for = perf_counter() - self._last_frame_at
            if (
                self._note is None
                or self._waiting_on_someone
                or self._stall_noted
                or quiet_for < BROWSER_STALL_NOTE_AFTER_SECONDS
            ):
                continue
            self._stall_noted = True
            await self._note(BROWSER_STALL_NOTE.format(seconds=int(quiet_for)))

    def _record_step(self, frame: StepFrame) -> None:
        """Emit one executed step off the agent loop's critical path.

        The screenshot upload is a ~1s CDN round-trip that Browser-Use awaits
        before the step's actions run, so it is spawned; the per-runner lock
        keeps emits ordered and _finish() flushes them before the result.
        """
        self._last_step = frame.index
        self._last_frame_at = perf_counter()
        # None reads as falsy exactly like False.
        self._stall_noted = False  # pragma: no mutate
        self._emit_tasks.add(
            spawn_background_task(self._emit_step(frame), name="browser_step_emit")
        )

    async def _emit_step(self, frame: StepFrame) -> None:
        async with self._emit_lock:
            shot_t0 = perf_counter()
            screenshot = await self._render_screenshot(frame)
            if screenshot is not None:
                self._shots.append(screenshot)
            # Feeds only the info-level step timing line.
            screenshot_ms = round((perf_counter() - shot_t0) * 1000)  # pragma: no mutate
            # Feeds only the info-level step timing line.
            emit_t0 = perf_counter()  # pragma: no mutate
            await self._emit(
                BrowserStepSnapshot(
                    index=frame.index,
                    goal=frame.goal,
                    actions=frame.actions,
                    url=frame.url,
                    title=frame.title,
                    screenshot=screenshot,
                    elapsed_ms=frame.since_prev_ms or None,
                    frame_digest=sha256(frame.photo.encode()).hexdigest() if frame.photo else None,
                )
            )
            # Feeds only the info-level step timing line.
            emit_ms = round((perf_counter() - emit_t0) * 1000)  # pragma: no mutate
            log.info(
                f"{LogTag.BROWSER} step timing",
                step=frame.index,
                since_prev_ms=frame.since_prev_ms,
                screenshot_ms=screenshot_ms,
                emit_ms=emit_ms,
            )

    async def _render_screenshot(self, frame: StepFrame) -> str | None:
        """Return the URL that serves a step frame's photo, or None when it has none to show."""
        if frame.photo is None:
            return None
        # Keyed by session id (not conversation) so each run is its own replay folder.
        return await publish_step_screenshot(
            base64.b64decode(frame.photo), frame.session_id, frame.index
        )

    async def _finish(self, end: RunEnd) -> BrowserResultSnapshot:
        """Emit the result card for how the run ended."""
        self.failure = end.failure
        # Flush any in-flight step emits before the result so their photos land in
        # order and the SSE writer is still open when they do.
        if self._emit_tasks:
            await asyncio.gather(*self._emit_tasks, return_exceptions=True)
        # A recap slideshow of every step — surfaced whether the task succeeded or not.
        replay_url = await create_replay_link(self._session.session_id, self._shots)
        result = BrowserResultSnapshot(
            status=end.status,
            success=end.failure is None,
            summary=end.summary,
            steps=self._last_step,
            replay_url=replay_url,
            user_notes=list(self._user_notes),
            redirects=list(self._redirects),
        )
        await self._emit(result)
        return result

    async def _finish_unanswered(self, end: RunEnd) -> BrowserResultSnapshot:
        """Finish a run that ended before the agent wrote its answer, with what it had gathered by then."""
        found = [*self._found_before, *self._agent_run.found()]
        if not found:
            return await self._finish(end)
        note = BROWSER_RUN_FOUND_NOTE.format(found="\n\n".join(found))
        return await self._finish(replace(end, summary=f"{end.summary}{note}"))

    async def _finish_from_outcome(self, outcome: RunOutcome) -> BrowserResultSnapshot:
        if outcome.success:
            return await self._finish(
                RunEnd(
                    BrowserSessionStatus.COMPLETED,
                    outcome.summary or BROWSER_RUN_DONE_SUMMARY,
                    None,
                )
            )
        failure = outcome.failure or BrowserRunFailure.GOAL_NOT_ACHIEVED
        if not outcome.summary:
            return await self._finish_unanswered(
                RunEnd(BrowserSessionStatus.FAILED, BROWSER_RUN_NOT_DONE_SUMMARY, failure)
            )
        return await self._finish(RunEnd(BrowserSessionStatus.FAILED, outcome.summary, failure))
