"""The single executor-facing browser-automation tool.

The only place the browser host + Browser-Use are wired together. The executor
sees one tool, not the internals. The "do you want me to use a browser?"
confirmation is handled by the shared HIL system (``browser_task`` is registered
destructive). This tool composes the runner's seams: progress emission (SSE +
bots), cancellation (stream flag), and the mid-run live-view handoff. The
session context manager owns capacity limits, saved-login persistence, live-view
registration, and always releasing the browser context.
"""

from typing import Annotated
import uuid

from langchain_core.runnables.config import RunnableConfig
from langchain_core.tools import tool
from langgraph.config import get_stream_writer

from app.config.settings import settings
from app.constants.browser import BROWSER_TASK_EVENT, BrowserSessionStatus, HandoffStatus
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
    HandoffRequest,
)
from app.services.browser.bot_delivery import BotProgressDelivery
from app.services.browser.exceptions import BrowserConcurrencyLimit, BrowserUnavailableError
from app.services.browser.handoff import await_handoff, create_pending_handoff
from app.services.browser.llm import build_browser_llm, resolve_use_vision
from app.services.browser.runner import BrowserTaskRunner
from app.services.browser.session import browser_session
from app.templates.docstrings.browser_tool_docs import BROWSER_TASK
from shared.py.wide_events import log


@tool
@with_rate_limiting("browser_task")
@with_doc(BROWSER_TASK)
async def browser_task(
    config: RunnableConfig,
    task: Annotated[str, "Clear, self-contained description of what to do in the browser."],
    start_url: Annotated[str | None, "Optional URL to open first."] = None,
) -> str:
    configurable = config.get("configurable", {})
    user_id: str = configurable.get("user_id") or ""
    conversation_id: str = configurable.get("thread_id") or ""
    stream_id: str | None = configurable.get("stream_id")
    root_request_id: str | None = configurable.get("root_request_id")
    source_category = configurable.get("source_category")
    is_bot = source_category == SourceCategory.BOT.value

    log.set(browser={"operation": "task", "source_category": source_category})

    if not settings.BROWSER_USE_ENABLED:
        return "Browser automation is currently disabled."

    writer = get_stream_writer()

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

    async def emit(snapshot: BrowserCardSnapshot) -> None:
        writer({BROWSER_TASK_EVENT: snapshot.model_dump(mode="json")})
        if bot_delivery is None:
            return
        if isinstance(snapshot, BrowserStepSnapshot):
            await bot_delivery.step(snapshot)
        elif isinstance(snapshot, BrowserResultSnapshot):
            await bot_delivery.result(snapshot)
        elif isinstance(snapshot, BrowserHandoffSnapshot):
            await bot_delivery.handoff(snapshot)
        elif isinstance(snapshot, BrowserSessionSnapshot):
            await bot_delivery.session(snapshot)

    async def is_cancelled() -> bool:
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

            async def request_handoff(req: HandoffRequest) -> HandoffStatus:
                handoff_id = uuid.uuid4().hex
                await create_pending_handoff(handoff_id, user_id, conversation_id, req.reason)
                await emit(
                    BrowserHandoffSnapshot(
                        handoff_id=handoff_id,
                        category=req.category,
                        reason=req.reason,
                        live_view_url=session.live_view_url,
                        status=HandoffStatus.PENDING,
                    )
                )
                status = await await_handoff(
                    handoff_id, settings.BROWSER_USE_HANDOFF_TIMEOUT_SECONDS
                )
                await emit(
                    BrowserHandoffSnapshot(
                        handoff_id=handoff_id,
                        category=req.category,
                        reason=req.reason,
                        live_view_url=session.live_view_url,
                        status=status,
                    )
                )
                return status

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
                stream_screenshots=settings.BROWSER_USE_STREAM_SCREENSHOTS,
                use_vision=use_vision,
                solve_captcha=settings.BROWSER_USE_SOLVE_CAPTCHA,
                user_id=user_id or None,
                root_request_id=root_request_id,
            )
            result = await runner.run(full_task)
            return result.summary
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
