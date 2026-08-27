"""The single executor-facing browser-automation tool.

The only place the browser host + Browser-Use are wired together. The executor
sees one tool, not the internals. The "do you want me to use a browser?"
confirmation is handled by the shared HIL system (``browser_task`` is registered
destructive). This tool composes the runner's seams: progress emission (SSE +
bots), cancellation (stream flag), and the mid-run live-view handoff. The
session context manager owns capacity limits, saved-login persistence, live-view
registration, and always releasing the browser context.
"""

from time import perf_counter
from typing import Annotated
import uuid

from langchain_core.runnables.config import RunnableConfig
from langchain_core.tools import tool
from langgraph.config import get_stream_writer
from langgraph.types import StreamWriter

from app.config.settings import settings
from app.constants.browser import (
    BROWSER_TASK_EVENT,
    BROWSER_TOOL_CATEGORY,
    BrowserSessionStatus,
    HandoffStatus,
)
from app.constants.log_tags import LogTag
from app.core.stream_manager import stream_manager
from app.decorators import with_doc, with_rate_limiting
from app.models.chat_models import ConversationSource, SourceCategory
from app.schemas.browser import (
    BrowserCardSnapshot,
    BrowserHandoffSnapshot,
    BrowserResultSnapshot,
    BrowserSessionSnapshot,
    BrowserStepSnapshot,
    HandoffOutcome,
    HandoffRequest,
)
from app.services.analytics_service import AnalyticsEvents, capture_event
from app.services.browser.bot_delivery import BotProgressDelivery
from app.services.browser.exceptions import BrowserConcurrencyLimit, BrowserUnavailableError
from app.services.browser.handoff import await_handoff, create_pending_handoff
from app.services.browser.llm import build_browser_llm, resolve_use_vision
from app.services.browser.runner import BrowserTaskRunner
from app.services.browser.session import browser_session, keep_session_alive
from app.services.browser.tasks import record_browser_task
from app.templates.docstrings.browser_tool_docs import BROWSER_TASK
from app.utils.agent_utils import (
    format_browser_action_entry,
    format_subagent_end_event,
    format_subagent_start_event,
)
from app.utils.background_tasks import spawn_background_task
from shared.py.wide_events import log

# Screenshots stream into the chat live, so the reply must never narrate them.
_NO_META = (
    "The step-by-step screenshots were already shown to the user in this chat, so do "
    "NOT mention screenshots, tools, steps, or 'browser vision' — speak only to the outcome."
)


def _agent_result_message(result: BrowserResultSnapshot) -> str:
    """Outcome-specific guidance for the assistant's reply — so it confirms a real
    result, owns a stop, or reports a failure, but never claims success it didn't get."""
    summary = result.summary.strip()
    if result.status == BrowserSessionStatus.COMPLETED and result.success:
        return (
            f"BROWSER TASK COMPLETED. What was accomplished: {summary or 'the task finished'}.\n\n"
            f"Reply with a short, natural confirmation of what you found or did. {_NO_META}"
        )
    if result.status == BrowserSessionStatus.CANCELLED:
        return (
            "BROWSER TASK STOPPED BY THE USER before it finished — it did NOT complete, so "
            "there is no result and you must not claim one.\n\n"
            f"Briefly acknowledge you've stopped and ask if they'd like you to try again or "
            f"do something else. {_NO_META}"
        )
    return (
        f"BROWSER TASK DID NOT COMPLETE. Last state: {summary or 'the task could not be finished'}.\n\n"
        f"Tell the user honestly and briefly that it couldn't be finished, and why if it's clear. "
        f"Do not fabricate a result. {_NO_META}"
    )


class _BrowserThreadMirror:
    """Mirrors the browser agent's own actions into the chat's tool thread.

    The card shows *what the browser is doing*; this shows *what it called* —
    every action with its arguments, grouped under one "Browser" row exactly
    like a subagent's tool calls. Before this the thread carried a single
    opaque ``browser_task`` row and the agent's real work was invisible.

    Stateful because only the session snapshot carries the session id, and the
    group id has to outlive it for the steps and the result that follow.
    """

    def __init__(self, writer: StreamWriter) -> None:
        self._writer = writer
        self._group_id: str | None = None
        self._started_at = perf_counter()

    def mirror(self, snapshot: BrowserCardSnapshot) -> None:
        if isinstance(snapshot, BrowserSessionSnapshot):
            self._open(snapshot)
        elif isinstance(snapshot, BrowserStepSnapshot):
            self._actions(snapshot)
        elif isinstance(snapshot, BrowserResultSnapshot):
            self._close()

    def _open(self, snapshot: BrowserSessionSnapshot) -> None:
        if self._group_id or not snapshot.session_id:
            return
        self._group_id = f"browser:{snapshot.session_id}"
        self._started_at = perf_counter()
        self._writer(
            {
                "subagent_start": format_subagent_start_event(
                    subagent_name="Browser",
                    agent_type="spawned",
                    subagent_id=self._group_id,
                    tool_category=BROWSER_TOOL_CATEGORY,
                )
            }
        )

    def _actions(self, snapshot: BrowserStepSnapshot) -> None:
        if not self._group_id:
            return
        for position, action in enumerate(snapshot.actions):
            self._writer(
                {
                    "tool_data": format_browser_action_entry(
                        name=action.name,
                        inputs=action.inputs,
                        subagent_id=self._group_id,
                        tool_call_id=f"{self._group_id}:{snapshot.index}:{position}",
                    )
                }
            )

    def _close(self) -> None:
        if not self._group_id:
            return
        self._writer(
            {
                "subagent_end": format_subagent_end_event(
                    subagent_id=self._group_id,
                    duration_ms=int((perf_counter() - self._started_at) * 1000),
                )
            }
        )
        self._group_id = None


@tool
@with_rate_limiting("browser_task")
@with_doc(BROWSER_TASK)
async def browser_task(
    config: RunnableConfig,
    task: Annotated[str, "Clear, self-contained description of what to do in the browser."],
    start_url: Annotated[str | None, "Optional URL to open first."] = None,
) -> str:
    """Drive a browser task end to end: allocate a session, run the agent loop,
    and stream progress/result cards. Returns the outcome guidance message the
    executor surfaces to the user (never a fabricated success).
    """
    configurable = config.get("configurable", {})
    user_id: str = configurable.get("user_id") or ""
    # The USER-facing conversation, never the executor's derived `thread_id`
    # (`executor_<conv>`). A handoff registered here is resolved by a chat reply
    # ("done"/"stop") that arrives on the comms conversation id — keying it by the
    # prefixed thread_id would make that lookup miss and the handoff never resume.
    conversation_id: str = (
        configurable.get("conversation_id") or configurable.get("thread_id") or ""
    )
    stream_id: str | None = configurable.get("stream_id")
    root_request_id: str | None = configurable.get("root_request_id")
    source_category = configurable.get("source_category")
    is_bot = source_category == SourceCategory.BOT.value
    _conv_source = ConversationSource.coerce(configurable.get("conversation_source"))
    task_source = _conv_source.value if _conv_source else ""

    log.set(browser={"operation": "task", "source_category": source_category})

    if not settings.BROWSER_USE_ENABLED:
        return "Browser automation is currently disabled."

    writer = get_stream_writer()
    thread_mirror = _BrowserThreadMirror(writer)

    bot_delivery: BotProgressDelivery | None = None
    if is_bot and user_id and conversation_id:
        platform = ConversationSource.coerce(configurable.get("conversation_source"))
        if platform is not None:
            bot_delivery = BotProgressDelivery(
                platform=platform,
                user_id=user_id,
                conversation_id=conversation_id,
                stream_screenshots=settings.BROWSER_USE_STREAM_SCREENSHOTS,
            )

    # Captions for the recap ("what's going on" per step), keyed by step index.
    step_goals: dict[int, str] = {}
    # Only the screenshots that actually reached the CDN. A step whose upload
    # failed falls back to an inline data URL, which must not be stored as a
    # history frame — it would render as a permanently broken image.
    step_shots: dict[int, str] = {}

    async def emit(snapshot: BrowserCardSnapshot) -> None:
        """Stream a card snapshot into the chat (progress/step/result).

        Emits into the conversation so the user sees the live browser card;
        failures here are logged and swallowed — a card hiccup must never kill
        the browser run itself.
        """
        writer({BROWSER_TASK_EVENT: snapshot.model_dump(mode="json")})
        thread_mirror.mirror(snapshot)
        if isinstance(snapshot, BrowserStepSnapshot):
            if snapshot.goal:
                step_goals[snapshot.index] = snapshot.goal
            if snapshot.screenshot and snapshot.screenshot.startswith("http"):
                step_shots[snapshot.index] = snapshot.screenshot
        if bot_delivery is None:
            return
        try:
            # The platform mirror is best-effort: the card has already been
            # written above, so a messaging/queue outage must never abort the
            # in-flight browser run — the user keeps seeing progress regardless.
            if isinstance(snapshot, BrowserStepSnapshot):
                await bot_delivery.step(snapshot)
            elif isinstance(snapshot, BrowserResultSnapshot):
                await bot_delivery.result(snapshot)
            elif isinstance(snapshot, BrowserHandoffSnapshot):
                await bot_delivery.handoff(snapshot)
            elif isinstance(snapshot, BrowserSessionSnapshot):
                await bot_delivery.session(snapshot)
        except Exception as exc:
            # Swallowed by design (see the emit() docstring): a failed mirror is
            # a logged warning, never a reason to kill the task.
            log.error(
                f"{LogTag.BROWSER} Bot delivery failed; continuing browser task",
                error_type=type(exc).__name__,
                browser={"snapshot_type": type(snapshot).__name__},
            )

    async def is_cancelled() -> bool:
        """Check whether the user cancelled this task mid-run (via the card or
        chat), so the agent loop can stop early instead of finishing unprompted.
        """
        return bool(stream_id) and await stream_manager.is_cancelled(stream_id)

    try:
        llm = build_browser_llm()
    except BrowserUnavailableError as exc:
        log.warning(f"{LogTag.BROWSER} Browser LLM unavailable", error_type=type(exc).__name__)
        return f"I can't use the browser right now: {exc}"

    full_task = task if not start_url else f"{task}\n\nStart at: {start_url}"
    use_vision = await resolve_use_vision()

    try:
        async with browser_session(user_id=user_id, start_url=start_url) as session:
            log.set(browser={"session_id": session.session_id})

            async def request_handoff(req: HandoffRequest) -> HandoffOutcome:
                """Pause the run and hand the user a live view to complete the
                step themselves. Returns the outcome (completed with optional
                note, cancelled, or timed out) so the loop resumes natively.
                """
                handoff_id = uuid.uuid4().hex
                await create_pending_handoff(handoff_id, user_id, conversation_id, req.reason)
                await emit(
                    BrowserHandoffSnapshot(
                        handoff_id=handoff_id,
                        category=req.category,
                        reason=req.reason,
                        session_id=session.session_id,
                        live_view_url=session.live_view_url,
                        status=HandoffStatus.PENDING,
                    )
                )
                # The paused session produces no CDP/live-view traffic, so keep
                # its idle clock fresh until the user decides — otherwise the
                # host reaps the browser they were asked to come back to.
                keepalive = spawn_background_task(
                    keep_session_alive(session.session_id),
                    name="browser_handoff_keepalive",
                )
                try:
                    outcome = await await_handoff(
                        handoff_id, settings.BROWSER_USE_HANDOFF_TIMEOUT_SECONDS
                    )
                finally:
                    keepalive.cancel()
                await emit(
                    BrowserHandoffSnapshot(
                        handoff_id=handoff_id,
                        category=req.category,
                        reason=req.reason,
                        session_id=session.session_id,
                        live_view_url=session.live_view_url,
                        status=outcome.status,
                    )
                )
                return outcome

            runner = BrowserTaskRunner(
                session=session,
                conversation_id=conversation_id,
                llm=llm,
                emit=emit,
                request_handoff=request_handoff,
                is_cancelled=is_cancelled,
                max_steps=settings.BROWSER_USE_MAX_STEPS,
                max_actions_per_step=settings.BROWSER_USE_MAX_ACTIONS_PER_STEP,
                task_timeout_seconds=settings.BROWSER_USE_TASK_TIMEOUT_SECONDS,
                step_timeout_seconds=settings.BROWSER_USE_STEP_TIMEOUT_SECONDS,
                handoff_timeout_seconds=settings.BROWSER_USE_HANDOFF_TIMEOUT_SECONDS,
                stream_screenshots=settings.BROWSER_USE_STREAM_SCREENSHOTS,
                use_vision=use_vision,
                solve_captcha=settings.BROWSER_USE_SOLVE_CAPTCHA,
                flash_mode=settings.BROWSER_USE_FLASH_MODE,
                user_id=user_id or None,
                root_request_id=root_request_id,
            )
            run_t0 = perf_counter()
            result = await runner.run(full_task)
            if user_id:
                # Graph-background execution has no authenticated request context,
                # so the id must be explicit or the event lands on an anonymous
                # profile (see analytics conventions in CLAUDE.md).
                capture_event(
                    user_id,
                    AnalyticsEvents.BROWSER_TASK_FINISHED,
                    {
                        "status": result.status.value,
                        "success": result.success,
                        "steps": result.steps,
                        "duration_ms": round((perf_counter() - run_t0) * 1000),
                        "source": source_category or "web",
                    },
                )
            if user_id:
                # Record the finished task for the user's browser history (settings).
                # Best-effort background write: a completed task must still return
                # its result even if history persistence hiccups.
                spawn_background_task(
                    record_browser_task(
                        user_id=user_id,
                        conversation_id=conversation_id,
                        task=task,
                        session_id=session.session_id,
                        result=result,
                        step_goals=[step_goals.get(i, "") for i in range(1, result.steps + 1)],
                        step_screenshots=[
                            step_shots.get(i, "") for i in range(1, result.steps + 1)
                        ],
                        source=task_source,
                    ),
                    name="record_browser_task",
                )
            return _agent_result_message(result)
    except BrowserConcurrencyLimit as exc:
        return str(exc)
    except BrowserUnavailableError as exc:
        log.warning(f"{LogTag.BROWSER} Browser session unavailable", error_type=type(exc).__name__)
        await emit(
            BrowserResultSnapshot(
                status=BrowserSessionStatus.FAILED, success=False, summary=str(exc)
            )
        )
        return f"I couldn't start the browser: {exc}"
