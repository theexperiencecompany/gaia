"""Tests for the browser_task tool — gating, capacity, wiring, delivery resilience."""

import asyncio
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from typing import Any
from unittest.mock import AsyncMock, MagicMock

from langchain_core.runnables.config import RunnableConfig
import pytest

from app.agents.tools import browser_tool as tool_mod
from app.agents.tools.browser_tool import browser_task
from app.constants.browser import (
    BROWSER_TASK_EVENT,
    BrowserSessionStatus,
    HandoffStatus,
    SensitiveCategory,
)
from app.constants.log_tags import LogTag
from app.models.chat_models import ConversationSource
from app.schemas.browser import (
    BrowserAction,
    BrowserHandoffSnapshot,
    BrowserResultSnapshot,
    BrowserSessionSnapshot,
    BrowserStepSnapshot,
    HandoffOutcome,
    HandoffRequest,
)
from app.services.browser.exceptions import BrowserConcurrencyLimit, BrowserUnavailableError

UI_CONFIG: RunnableConfig = {
    "configurable": {"user_id": "u1", "thread_id": "c1", "stream_id": "s1", "source_category": "ui"}
}
BOT_CONFIG: RunnableConfig = {
    "configurable": {
        "user_id": "u1",
        "conversation_id": "c1",
        "stream_id": "s1",
        "source_category": "bot",
        "conversation_source": "discord",
    }
}

EmitFn = Callable[[object], Awaitable[None]]


@pytest.fixture(autouse=True)
def base_patches(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(tool_mod, "get_stream_writer", lambda: lambda payload: None)
    monkeypatch.setattr(tool_mod.stream_manager, "is_cancelled", AsyncMock(return_value=False))
    monkeypatch.setattr(tool_mod, "create_pending_handoff", AsyncMock())
    monkeypatch.setattr(tool_mod.settings, "BROWSER_USE_ENABLED", True)


def _patch_runner(monkeypatch: pytest.MonkeyPatch, result: BrowserResultSnapshot) -> MagicMock:
    fake_session = MagicMock(
        session_id="s1",
        cdp_url="ws://x",  # NOSONAR
        live_view_url="http://v",  # NOSONAR
        context_id="ctx-1",
    )

    @asynccontextmanager
    async def _fake_session(**kwargs: object) -> AsyncIterator[MagicMock]:
        yield fake_session

    monkeypatch.setattr(tool_mod, "browser_session", _fake_session)
    monkeypatch.setattr(tool_mod, "build_browser_llm", lambda: object())
    # Vision resolution hits a live model catalog; unit tests pin it.
    monkeypatch.setattr(tool_mod, "resolve_use_vision", AsyncMock(return_value=True))
    runner = MagicMock()
    runner.run = AsyncMock(return_value=result)
    monkeypatch.setattr(tool_mod, "BrowserTaskRunner", MagicMock(return_value=runner))
    return runner


async def test_disabled_returns_message(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(tool_mod.settings, "BROWSER_USE_ENABLED", False)
    out = await browser_task.ainvoke({"task": "do it"}, config=UI_CONFIG)
    assert "disabled" in out.lower()


async def test_llm_unavailable_returns_clean_message(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        tool_mod, "build_browser_llm", MagicMock(side_effect=BrowserUnavailableError("no key"))
    )
    out = await browser_task.ainvoke({"task": "do it"}, config=UI_CONFIG)
    assert "can't use the browser" in out.lower()


async def test_happy_path_runs_and_returns_summary(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runner = _patch_runner(
        monkeypatch,
        BrowserResultSnapshot(
            status=BrowserSessionStatus.COMPLETED, success=True, summary="Booked the table."
        ),
    )
    out = await browser_task.ainvoke({"task": "book a table"}, config=UI_CONFIG)
    # The tool returns the runner's summary wrapped in outcome-specific guidance,
    # so the assistant confirms a real result instead of narrating the mechanics.
    assert "Booked the table." in out
    assert "COMPLETED" in out
    runner.run.assert_awaited_once()


async def test_capacity_limit_returns_message(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(tool_mod, "build_browser_llm", lambda: object())
    monkeypatch.setattr(tool_mod, "resolve_use_vision", AsyncMock(return_value=True))

    @asynccontextmanager
    async def _at_capacity(**kwargs: object) -> AsyncIterator[MagicMock]:
        raise BrowserConcurrencyLimit("The browser host is at capacity; try again shortly.")
        yield MagicMock()  # pragma: no cover — never reached

    monkeypatch.setattr(tool_mod, "browser_session", _at_capacity)
    out = await browser_task.ainvoke({"task": "x"}, config=UI_CONFIG)
    assert "at capacity" in out.lower()


async def test_bot_delivery_outage_does_not_abort_run(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A messaging/platform outage must never kill the in-flight browser run.

    The web card is already on the SSE stream before the bot mirror runs, so a
    failing platform delivery is logged and skipped — the tool still returns the
    result summary instead of surfacing a delivery exception.
    """

    class _FailingDelivery:
        def __init__(self, **kwargs: object) -> None:
            pass

        async def session(self, snapshot: object) -> None:
            raise RuntimeError("rabbitmq down")

        async def step(self, snapshot: object) -> None:
            raise RuntimeError("rabbitmq down")

        async def handoff(self, snapshot: object) -> None:
            raise RuntimeError("rabbitmq down")

        async def result(self, snapshot: object) -> None:
            raise RuntimeError("rabbitmq down")

    class _Runner:
        def __init__(self, *, emit: EmitFn, **kwargs: object) -> None:
            self._emit = emit

        async def run(self, task: str) -> BrowserResultSnapshot:
            await self._emit(
                BrowserStepSnapshot(index=1, goal="g", url="https://x", title="t", screenshot=None)
            )
            await self._emit(
                BrowserResultSnapshot(
                    status=BrowserSessionStatus.COMPLETED, success=True, summary="Done it."
                )
            )
            return BrowserResultSnapshot(
                status=BrowserSessionStatus.COMPLETED, success=True, summary="Done it."
            )

    monkeypatch.setattr(tool_mod, "BotProgressDelivery", _FailingDelivery)
    monkeypatch.setattr(tool_mod, "BrowserTaskRunner", _Runner)
    monkeypatch.setattr(tool_mod, "build_browser_llm", lambda: object())
    monkeypatch.setattr(tool_mod, "resolve_use_vision", AsyncMock(return_value=True))

    fake_session = MagicMock(
        session_id="s1",
        cdp_url="ws://x",  # NOSONAR
        live_view_url="http://v",  # NOSONAR
        context_id="ctx-1",
    )

    @asynccontextmanager
    async def _fake_session(**kwargs: object) -> AsyncIterator[MagicMock]:
        yield fake_session

    monkeypatch.setattr(tool_mod, "browser_session", _fake_session)

    out = await browser_task.ainvoke({"task": "do it"}, config=BOT_CONFIG)
    assert "Done it." in out


# ---------------------------------------------------------------------------
# _agent_result_message — the exact guidance handed back to the executor
# ---------------------------------------------------------------------------

# Repeated verbatim (not imported) so a change to the copy has to be made twice
# on purpose: these strings are the tool's whole user-visible contract.
NO_META = (
    "The step-by-step screenshots were already shown to the user in this chat, so do "
    "NOT mention screenshots, tools, steps, or 'browser vision' — speak only to the outcome."
)


def _completed_message(summary: str) -> str:
    return (
        f"BROWSER TASK COMPLETED. What was accomplished: {summary}.\n\n"
        f"Reply with a short, natural confirmation of what you found or did. {NO_META}"
    )


def _failed_message(summary: str) -> str:
    return (
        f"BROWSER TASK DID NOT COMPLETE. Last state: {summary}.\n\n"
        f"Tell the user honestly and briefly that it couldn't be finished, and why if it's "
        f"clear. Do not fabricate a result. {NO_META}"
    )


CANCELLED_MESSAGE = (
    "BROWSER TASK STOPPED BY THE USER before it finished — it did NOT complete, so "
    "there is no result and you must not claim one.\n\n"
    "Briefly acknowledge you've stopped and ask if they'd like you to try again or "
    f"do something else. {NO_META}"
)


def _result(
    status: BrowserSessionStatus, success: bool, summary: str, steps: int = 0
) -> BrowserResultSnapshot:
    return BrowserResultSnapshot(status=status, success=success, summary=summary, steps=steps)


def test_result_message_completed_success_is_exact() -> None:
    out = tool_mod._agent_result_message(
        _result(BrowserSessionStatus.COMPLETED, True, "  Booked the table.  ")
    )
    assert out == _completed_message("Booked the table.")


def test_result_message_completed_without_success_reports_failure() -> None:
    """`status == COMPLETED and success` — a completed-but-unsuccessful run must
    never be reported as an accomplishment."""
    out = tool_mod._agent_result_message(
        _result(BrowserSessionStatus.COMPLETED, False, "Login wall")
    )
    assert out == _failed_message("Login wall")


def test_result_message_success_flag_alone_is_not_completion() -> None:
    out = tool_mod._agent_result_message(_result(BrowserSessionStatus.FAILED, True, "Crashed"))
    assert out == _failed_message("Crashed")


def test_result_message_completed_with_blank_summary_uses_fallback() -> None:
    out = tool_mod._agent_result_message(_result(BrowserSessionStatus.COMPLETED, True, "   "))
    assert out == _completed_message("the task finished")


def test_result_message_failure_with_blank_summary_uses_fallback() -> None:
    out = tool_mod._agent_result_message(_result(BrowserSessionStatus.FAILED, False, ""))
    assert out == _failed_message("the task could not be finished")


def test_result_message_cancelled_is_exact_and_ignores_summary() -> None:
    out = tool_mod._agent_result_message(
        _result(BrowserSessionStatus.CANCELLED, False, "half done")
    )
    assert out == CANCELLED_MESSAGE


def test_result_message_cancelled_wins_over_success_flag() -> None:
    out = tool_mod._agent_result_message(_result(BrowserSessionStatus.CANCELLED, True, "x"))
    assert out == CANCELLED_MESSAGE


# ---------------------------------------------------------------------------
# browser_task — harness
# ---------------------------------------------------------------------------

LLM_SENTINEL = object()

RunBody = Callable[["Harness"], Awaitable[BrowserResultSnapshot]]


class Harness:
    """Everything the tool hands to its seams, captured for assertion."""

    def __init__(self) -> None:
        self.writes: list[dict[str, Any]] = []
        self.session = MagicMock(session_id="sess-1", live_view_url="https://live/abc")
        self.session_kwargs: dict[str, Any] = {}
        self.runner_kwargs: dict[str, Any] = {}
        self.run_task: str | None = None
        self.record_calls: list[dict[str, Any]] = []
        self.spawn_names: list[str | None] = []
        self.delivery_kwargs: list[dict[str, Any]] = []
        self.delivered: list[tuple[str, Any]] = []
        self.handoffs_created: list[tuple[Any, ...]] = []
        self.handoffs_awaited: list[tuple[Any, ...]] = []
        self.cancel_checks: list[str] = []

    @property
    def cards(self) -> list[dict[str, Any]]:
        """The card payloads written onto the SSE stream, in order."""
        return [w[BROWSER_TASK_EVENT] for w in self.writes]

    async def emit(self, snapshot: object) -> None:
        await self.runner_kwargs["emit"](snapshot)

    async def is_cancelled(self) -> bool:
        result: bool = await self.runner_kwargs["is_cancelled"]()
        return result

    async def request_handoff(self, req: HandoffRequest) -> HandoffOutcome:
        outcome: HandoffOutcome = await self.runner_kwargs["request_handoff"](req)
        return outcome

    def action_results(self, step_index: int, outputs: object) -> None:
        # The tool wires this to the mirror's `results`; the runner calls it from
        # `on_step_end`. Driving it directly mirrors that call.
        self.runner_kwargs["action_results"](step_index, outputs)


class RecordingDelivery:
    def __init__(self, harness: Harness) -> None:
        self._h = harness

    async def step(self, snapshot: object) -> None:
        self._h.delivered.append(("step", snapshot))

    async def result(self, snapshot: object) -> None:
        self._h.delivered.append(("result", snapshot))

    async def handoff(self, snapshot: object) -> None:
        self._h.delivered.append(("handoff", snapshot))

    async def session(self, snapshot: object) -> None:
        self._h.delivered.append(("session", snapshot))


async def _noop() -> None:
    return None


def _install(
    monkeypatch: pytest.MonkeyPatch,
    *,
    result: BrowserResultSnapshot | None = None,
    run_body: RunBody | None = None,
    session_error: Exception | None = None,
    handoff_outcome: HandoffOutcome | None = None,
    use_vision: bool = True,
) -> Harness:
    """Wire every seam of ``browser_task`` to a recorder and return the recording."""
    h = Harness()
    final = result if result is not None else _result(BrowserSessionStatus.COMPLETED, True, "Done")

    monkeypatch.setattr(tool_mod, "get_stream_writer", lambda: h.writes.append)
    monkeypatch.setattr(tool_mod, "build_browser_llm", lambda: LLM_SENTINEL)
    monkeypatch.setattr(tool_mod, "resolve_use_vision", AsyncMock(return_value=use_vision))

    @asynccontextmanager
    async def _session(**kwargs: Any) -> AsyncIterator[MagicMock]:
        h.session_kwargs = kwargs
        if session_error is not None:
            raise session_error
        yield h.session

    monkeypatch.setattr(tool_mod, "browser_session", _session)

    class _Runner:
        def __init__(self, **kwargs: Any) -> None:
            h.runner_kwargs = kwargs

        async def run(self, task: str) -> BrowserResultSnapshot:
            h.run_task = task
            if run_body is not None:
                return await run_body(h)
            return final

    monkeypatch.setattr(tool_mod, "BrowserTaskRunner", _Runner)

    def _record(**kwargs: Any) -> Any:
        h.record_calls.append(kwargs)
        return _noop()

    monkeypatch.setattr(tool_mod, "record_browser_task", _record)

    real_spawn = tool_mod.spawn_background_task

    def _spawn(coro: Any, **kwargs: Any) -> Any:
        h.spawn_names.append(kwargs.get("name"))
        return real_spawn(coro, **kwargs)

    monkeypatch.setattr(tool_mod, "spawn_background_task", _spawn)

    def _delivery(**kwargs: Any) -> RecordingDelivery:
        h.delivery_kwargs.append(kwargs)
        return RecordingDelivery(h)

    monkeypatch.setattr(tool_mod, "BotProgressDelivery", _delivery)

    async def _create_pending(*args: Any) -> None:
        h.handoffs_created.append(args)

    monkeypatch.setattr(tool_mod, "create_pending_handoff", _create_pending)

    async def _await_handoff(*args: Any) -> HandoffOutcome:
        h.handoffs_awaited.append(args)
        return handoff_outcome or HandoffOutcome(status=HandoffStatus.COMPLETED)

    monkeypatch.setattr(tool_mod, "await_handoff", _await_handoff)

    async def _is_cancelled(stream_id: str) -> bool:
        h.cancel_checks.append(stream_id)
        return True

    monkeypatch.setattr(tool_mod.stream_manager, "is_cancelled", _is_cancelled)
    return h


# ---------------------------------------------------------------------------
# browser_task — gating and early returns
# ---------------------------------------------------------------------------


async def test_disabled_message_is_exact_and_nothing_runs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    h = _install(monkeypatch)
    monkeypatch.setattr(tool_mod.settings, "BROWSER_USE_ENABLED", False)
    out = await browser_task.ainvoke({"task": "do it"}, config=UI_CONFIG)
    assert out == "Browser automation is currently disabled."
    assert h.session_kwargs == {}
    assert h.writes == []


async def test_llm_unavailable_message_carries_the_reason(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    h = _install(monkeypatch)
    monkeypatch.setattr(
        tool_mod,
        "build_browser_llm",
        MagicMock(side_effect=BrowserUnavailableError("no API key for 'google'")),
    )
    fake_log = MagicMock()
    monkeypatch.setattr(tool_mod, "log", fake_log)
    out = await browser_task.ainvoke({"task": "do it"}, config=UI_CONFIG)
    assert out == "I can't use the browser right now: no API key for 'google'"
    assert h.session_kwargs == {}
    fake_log.warning.assert_called_once_with(
        f"{LogTag.BROWSER} Browser LLM unavailable", error_type="BrowserUnavailableError"
    )


async def test_capacity_limit_returns_the_exception_text_verbatim(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install(
        monkeypatch,
        session_error=BrowserConcurrencyLimit("Too many browser tasks already running."),
    )
    out = await browser_task.ainvoke({"task": "x"}, config=UI_CONFIG)
    assert out == "Too many browser tasks already running."


async def test_session_unavailable_emits_failed_card_and_explains(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    h = _install(monkeypatch, session_error=BrowserUnavailableError("host is down"))
    fake_log = MagicMock()
    monkeypatch.setattr(tool_mod, "log", fake_log)
    out = await browser_task.ainvoke({"task": "x"}, config=UI_CONFIG)
    assert out == "I couldn't start the browser: host is down"
    assert h.cards == [
        {
            "kind": "result",
            "status": "failed",
            "success": False,
            "summary": "host is down",
            "steps": 0,
            "replay_url": None,
        }
    ]
    fake_log.warning.assert_called_once_with(
        f"{LogTag.BROWSER} Browser session unavailable", error_type="BrowserUnavailableError"
    )
    # UI runs have no bot_delivery, so emitting the failed card above must not
    # touch it — the closure's initial value must be `None`, not a falsy
    # sentinel a snapshot could be handed to and blow up against.
    fake_log.error.assert_not_called()


# ---------------------------------------------------------------------------
# browser_task — the task text and the session it opens
# ---------------------------------------------------------------------------


async def test_task_is_passed_through_unchanged_without_a_start_url(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    h = _install(monkeypatch)
    await browser_task.ainvoke({"task": "book a table"}, config=UI_CONFIG)
    assert h.run_task == "book a table"
    assert h.session_kwargs == {"user_id": "u1", "start_url": None}


async def test_start_url_is_appended_to_the_task_and_opened(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    h = _install(monkeypatch)
    await browser_task.ainvoke(
        {"task": "book a table", "start_url": "https://resy.com"}, config=UI_CONFIG
    )
    assert h.run_task == "book a table\n\nStart at: https://resy.com"
    assert h.session_kwargs == {"user_id": "u1", "start_url": "https://resy.com"}


async def test_blank_start_url_is_not_appended(monkeypatch: pytest.MonkeyPatch) -> None:
    h = _install(monkeypatch)
    await browser_task.ainvoke({"task": "book a table", "start_url": ""}, config=UI_CONFIG)
    assert h.run_task == "book a table"


# ---------------------------------------------------------------------------
# browser_task — runner wiring
# ---------------------------------------------------------------------------


async def test_runner_is_configured_from_settings_and_config(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Every knob the runner gets must come from its own setting — not a
    neighbouring one, and not a hardcoded default."""
    h = _install(monkeypatch, use_vision=False)
    monkeypatch.setattr(tool_mod.settings, "BROWSER_USE_MAX_STEPS", 7)
    monkeypatch.setattr(tool_mod.settings, "BROWSER_USE_MAX_ACTIONS_PER_STEP", 3)
    monkeypatch.setattr(tool_mod.settings, "BROWSER_USE_TASK_TIMEOUT_SECONDS", 111)
    monkeypatch.setattr(tool_mod.settings, "BROWSER_USE_STEP_TIMEOUT_SECONDS", 22)
    monkeypatch.setattr(tool_mod.settings, "BROWSER_USE_HANDOFF_TIMEOUT_SECONDS", 333)
    monkeypatch.setattr(tool_mod.settings, "BROWSER_USE_STREAM_SCREENSHOTS", False)
    monkeypatch.setattr(tool_mod.settings, "BROWSER_USE_SOLVE_CAPTCHA", False)
    monkeypatch.setattr(tool_mod.settings, "BROWSER_USE_FLASH_MODE", True)

    config: RunnableConfig = {
        "configurable": {
            "user_id": "u1",
            "conversation_id": "conv-9",
            "stream_id": "s1",
            "root_request_id": "req-42",
            "source_category": "ui",
        }
    }
    await browser_task.ainvoke({"task": "x"}, config=config)

    kwargs = dict(h.runner_kwargs)
    for seam in ("emit", "request_handoff", "is_cancelled", "action_results"):
        assert callable(kwargs.pop(seam))
    assert kwargs == {
        "session": h.session,
        "conversation_id": "conv-9",
        "llm": LLM_SENTINEL,
        "max_steps": 7,
        "max_actions_per_step": 3,
        "task_timeout_seconds": 111,
        "step_timeout_seconds": 22,
        "handoff_timeout_seconds": 333,
        "stream_screenshots": False,
        "use_vision": False,
        "solve_captcha": False,
        "flash_mode": True,
        "user_id": "u1",
        "root_request_id": "req-42",
    }


async def test_conversation_id_prefers_the_user_facing_conversation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A handoff is resolved by a chat reply keyed on the comms conversation id,
    so the executor's derived thread_id must never win."""
    h = _install(monkeypatch)
    config: RunnableConfig = {
        "configurable": {
            "user_id": "u1",
            "conversation_id": "conv-9",
            "thread_id": "executor_conv-9",
        }
    }
    await browser_task.ainvoke({"task": "x"}, config=config)
    assert h.runner_kwargs["conversation_id"] == "conv-9"


async def test_conversation_id_falls_back_to_thread_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    h = _install(monkeypatch)
    config: RunnableConfig = {"configurable": {"user_id": "u1", "thread_id": "t-7"}}
    await browser_task.ainvoke({"task": "x"}, config=config)
    assert h.runner_kwargs["conversation_id"] == "t-7"


async def test_missing_identifiers_degrade_to_blank_and_none(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    h = _install(monkeypatch)
    await browser_task.ainvoke({"task": "x"}, config={"configurable": {}})
    assert h.runner_kwargs["conversation_id"] == ""
    assert h.runner_kwargs["user_id"] is None
    assert h.runner_kwargs["root_request_id"] is None
    assert h.session_kwargs == {"user_id": "", "start_url": None}


async def test_a_config_with_no_configurable_key_still_degrades_cleanly(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Same degradation as above, for a config missing ``configurable`` entirely.

    Called through the raw coroutine rather than ``ainvoke``: LangChain's
    ``ensure_config`` injects ``configurable`` into every config it normalises, so
    the tool's own ``config.get("configurable", {})`` fallback is unreachable via
    the public path — and a fallback nothing exercises is one nothing would notice
    losing. Without the ``{}`` the next line would raise AttributeError on None.
    """
    h = _install(monkeypatch)

    await browser_task.coroutine(config={}, task="x")

    assert h.runner_kwargs["conversation_id"] == ""
    assert h.runner_kwargs["user_id"] is None
    assert h.session_kwargs == {"user_id": "", "start_url": None}


# ---------------------------------------------------------------------------
# browser_task — cancellation seam
# ---------------------------------------------------------------------------


async def test_is_cancelled_consults_the_stream_manager_for_this_stream(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def body(h: Harness) -> BrowserResultSnapshot:
        assert await h.is_cancelled() is True
        return _result(BrowserSessionStatus.CANCELLED, False, "stopped")

    h = _install(monkeypatch, run_body=body)
    await browser_task.ainvoke({"task": "x"}, config=UI_CONFIG)
    assert h.cancel_checks == ["s1"]


async def test_is_cancelled_is_false_without_a_stream_and_never_queries(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """No stream id means no cancel flag to read — the runner must not be told
    it was cancelled just because the lookup would have said so."""

    async def body(h: Harness) -> BrowserResultSnapshot:
        assert await h.is_cancelled() is False
        return _result(BrowserSessionStatus.COMPLETED, True, "done")

    h = _install(monkeypatch, run_body=body)
    config: RunnableConfig = {"configurable": {"user_id": "u1", "thread_id": "c1"}}
    await browser_task.ainvoke({"task": "x"}, config=config)
    assert h.cancel_checks == []


async def test_is_cancelled_reports_a_live_stream_as_running(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def body(h: Harness) -> BrowserResultSnapshot:
        assert await h.is_cancelled() is False
        return _result(BrowserSessionStatus.COMPLETED, True, "done")

    _install(monkeypatch, run_body=body)
    monkeypatch.setattr(tool_mod.stream_manager, "is_cancelled", AsyncMock(return_value=False))
    await browser_task.ainvoke({"task": "x"}, config=UI_CONFIG)


# ---------------------------------------------------------------------------
# browser_task — card emission
# ---------------------------------------------------------------------------


async def test_step_card_is_written_as_json_under_the_browser_event_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def body(h: Harness) -> BrowserResultSnapshot:
        await h.emit(
            BrowserStepSnapshot(
                index=2,
                goal="find the menu",
                actions=[BrowserAction(name="click", inputs={"index": 2})],
                url="https://x",
                title="Menu",
                screenshot="https://cdn/2.png",
            )
        )
        return _result(BrowserSessionStatus.COMPLETED, True, "done")

    h = _install(monkeypatch, run_body=body)
    await browser_task.ainvoke({"task": "x"}, config=UI_CONFIG)
    assert list(h.writes[0]) == [BROWSER_TASK_EVENT]
    # JSON mode, not python mode: the payload goes onto the SSE wire, so the
    # discriminator must be a plain string rather than an enum member.
    assert type(h.cards[0]["kind"]) is str
    assert h.cards[0] == {
        "kind": "step",
        "index": 2,
        "goal": "find the menu",
        "actions": [{"name": "click", "inputs": {"index": 2}, "target": None, "point": None}],
        "url": "https://x",
        "title": "Menu",
        "screenshot": "https://cdn/2.png",
        "elapsed_ms": None,
    }


async def test_mirrored_action_row_names_the_element_it_touched(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The tool-thread row must use the resolved target, like the step caption does.

    The runner resolves each action's element against the DOM the model saw and
    puts it on ``BrowserAction.target``. The step caption used it; the mirrored
    row did not, so a form fill rendered as "Clicking" twice with nothing to tell
    the two apart.
    """

    async def body(h: Harness) -> BrowserResultSnapshot:
        # The mirror opens its group on the session snapshot; without one there
        # is no group to hang the action rows off.
        await h.emit(
            BrowserSessionSnapshot(task="x", status=BrowserSessionStatus.RUNNING, session_id="s1")
        )
        await h.emit(
            BrowserStepSnapshot(
                index=1,
                goal="submit the form",
                actions=[BrowserAction(name="click", inputs={"index": 7}, target="Submit")],
                url="https://x",
                title="Form",
                screenshot=None,
            )
        )
        return _result(BrowserSessionStatus.COMPLETED, True, "done")

    h = _install(monkeypatch, run_body=body)
    await browser_task.ainvoke({"task": "x"}, config=UI_CONFIG)

    rows = [w["tool_data"] for w in h.writes if "tool_data" in w]
    messages = [r["data"]["message"] for r in rows]
    assert 'Clicking "Submit"' in messages, messages


async def test_action_output_lands_on_the_row_for_that_step_and_position(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A per-action output frame must key to the same tool_call_id as its row.

    The row is emitted before the action runs (Browser-Use fires the step
    callback pre-execution), so the output arrives later via on_step_end and has
    to match the row by {group}:{step}:{position} or it renders detached.
    """
    from app.schemas.browser import BrowserActionOutput

    async def body(h: Harness) -> BrowserResultSnapshot:
        await h.emit(
            BrowserSessionSnapshot(task="x", status=BrowserSessionStatus.RUNNING, session_id="s1")
        )
        await h.emit(
            BrowserStepSnapshot(
                index=3,
                goal="read the total",
                actions=[BrowserAction(name="extract", inputs={"index": 4}, target="Total")],
                url="https://x",
                title="Cart",
                screenshot=None,
            )
        )
        # The tool hands the mirror's `results` callback to the runner; call it
        # the way the runner would after the step executes.
        h.action_results(3, [BrowserActionOutput(position=0, output="Total: $42.00")])
        return _result(BrowserSessionStatus.COMPLETED, True, "done")

    h = _install(monkeypatch, run_body=body)
    await browser_task.ainvoke({"task": "x"}, config=UI_CONFIG)

    rows = [w["tool_data"] for w in h.writes if "tool_data" in w]
    outs = [w["tool_output"] for w in h.writes if "tool_output" in w]
    row_id = rows[0]["data"]["tool_call_id"]
    assert len(outs) == 1
    assert outs[0]["tool_call_id"] == row_id, (outs[0]["tool_call_id"], row_id)
    assert outs[0]["output"] == "Total: $42.00"


async def test_action_output_arriving_before_its_row_is_buffered_then_flushed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The live ordering: results arrive before the row.

    The runner emits step rows through a background task that uploads the
    screenshot first (~1s), while the action result arrives synchronously on the
    next hook. So `results` can run before `_actions` for the same step. The
    output must still attach — buffered, then flushed when the row lands.
    """
    from app.schemas.browser import BrowserActionOutput

    async def body(h: Harness) -> BrowserResultSnapshot:
        await h.emit(
            BrowserSessionSnapshot(task="x", status=BrowserSessionStatus.RUNNING, session_id="s1")
        )
        # Result first — the row for step 2 has NOT been emitted yet.
        h.action_results(2, [BrowserActionOutput(position=0, output="Total: $42.00")])
        assert [w for w in h.writes if "tool_output" in w] == []  # buffered, not emitted
        # Now the row lands; the buffered output flushes with it.
        await h.emit(
            BrowserStepSnapshot(
                index=2,
                goal="read the total",
                actions=[BrowserAction(name="extract", inputs={"index": 4}, target="Total")],
                url="https://x",
                title="Cart",
                screenshot=None,
            )
        )
        return _result(BrowserSessionStatus.COMPLETED, True, "done")

    h = _install(monkeypatch, run_body=body)
    await browser_task.ainvoke({"task": "x"}, config=UI_CONFIG)

    rows = [w["tool_data"] for w in h.writes if "tool_data" in w]
    outs = [w["tool_output"] for w in h.writes if "tool_output" in w]
    assert len(outs) == 1
    assert outs[0]["tool_call_id"] == rows[0]["data"]["tool_call_id"]
    assert outs[0]["output"] == "Total: $42.00"


async def test_action_output_for_an_unknown_row_is_dropped(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An output whose row never arrives (an errored step emits no rows) stays
    buffered and never produces an orphan frame the UI cannot attach."""
    from app.schemas.browser import BrowserActionOutput

    async def body(h: Harness) -> BrowserResultSnapshot:
        await h.emit(
            BrowserSessionSnapshot(task="x", status=BrowserSessionStatus.RUNNING, session_id="s1")
        )
        h.action_results(9, [BrowserActionOutput(position=0, output="orphan")])
        return _result(BrowserSessionStatus.COMPLETED, True, "done")

    h = _install(monkeypatch, run_body=body)
    await browser_task.ainvoke({"task": "x"}, config=UI_CONFIG)

    assert [w for w in h.writes if "tool_output" in w] == []


# ---------------------------------------------------------------------------
# browser_task — mid-run handoff
# ---------------------------------------------------------------------------


async def test_handoff_registers_emits_pending_then_resolution_and_returns_outcome(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    resolved = HandoffOutcome(status=HandoffStatus.CANCELLED, message="not now")

    async def body(h: Harness) -> BrowserResultSnapshot:
        outcome = await h.request_handoff(
            HandoffRequest(category=SensitiveCategory.PAYMENT, reason="card details needed")
        )
        assert outcome is resolved
        return _result(BrowserSessionStatus.CANCELLED, False, "user cancelled")

    h = _install(monkeypatch, run_body=body, handoff_outcome=resolved)
    monkeypatch.setattr(tool_mod.settings, "BROWSER_USE_HANDOFF_TIMEOUT_SECONDS", 333)
    config: RunnableConfig = {
        "configurable": {"user_id": "u1", "conversation_id": "conv-9", "stream_id": "s1"}
    }
    await browser_task.ainvoke({"task": "x"}, config=config)

    (created,) = h.handoffs_created
    handoff_id = created[0]
    assert len(handoff_id) == 32
    assert created == (handoff_id, "u1", "conv-9", "card details needed")
    assert h.handoffs_awaited == [(handoff_id, 333)]
    assert h.cards == [
        {
            "kind": "handoff",
            "handoff_id": handoff_id,
            "category": "payment",
            "reason": "card details needed",
            "session_id": "sess-1",
            "live_view_url": "https://live/abc",
            "status": "pending",
        },
        {
            "kind": "handoff",
            "handoff_id": handoff_id,
            "category": "payment",
            "reason": "card details needed",
            "session_id": "sess-1",
            "live_view_url": "https://live/abc",
            "status": "cancelled",
        },
    ]


async def test_handoff_keepalive_is_cancelled_after_the_handoff_resolves(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A paused session gets no CDP/live-view traffic, so ``request_handoff``
    spawns a keepalive to hold the host's idle clock open. Once the handoff
    resolves, that keepalive must be cancelled -- otherwise it keeps touching a
    session nobody is waiting on anymore."""
    tasks: list[asyncio.Task[None]] = []

    async def _fake_keep_alive(session_id: str) -> None:
        await asyncio.Event().wait()  # runs until cancelled

    def _spawn(coro: Any, **kwargs: Any) -> asyncio.Task[None]:
        task = asyncio.create_task(coro)
        if kwargs.get("name") == "browser_handoff_keepalive":
            tasks.append(task)
        return task

    async def body(h: Harness) -> BrowserResultSnapshot:
        await h.request_handoff(HandoffRequest(reason="verify"))
        return _result(BrowserSessionStatus.COMPLETED, True, "done")

    _install(monkeypatch, run_body=body)
    monkeypatch.setattr(tool_mod, "keep_session_alive", _fake_keep_alive)
    monkeypatch.setattr(tool_mod, "spawn_background_task", _spawn)

    await browser_task.ainvoke({"task": "x"}, config=UI_CONFIG)
    await asyncio.sleep(0)

    assert len(tasks) == 1
    assert tasks[0].cancelled()


async def test_handoff_keepalive_is_cancelled_when_await_handoff_raises(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The keepalive must be cancelled on the failure path too -- a raised
    ``await_handoff`` must not leak the keepalive task running forever."""
    tasks: list[asyncio.Task[None]] = []

    async def _fake_keep_alive(session_id: str) -> None:
        await asyncio.Event().wait()

    def _spawn(coro: Any, **kwargs: Any) -> asyncio.Task[None]:
        task = asyncio.create_task(coro)
        if kwargs.get("name") == "browser_handoff_keepalive":
            tasks.append(task)
        return task

    async def _boom_await_handoff(*args: Any) -> HandoffOutcome:
        raise RuntimeError("redis down")

    async def body(h: Harness) -> BrowserResultSnapshot:
        await h.request_handoff(HandoffRequest(reason="verify"))
        return _result(BrowserSessionStatus.COMPLETED, True, "unreachable")

    _install(monkeypatch, run_body=body)
    monkeypatch.setattr(tool_mod, "keep_session_alive", _fake_keep_alive)
    monkeypatch.setattr(tool_mod, "spawn_background_task", _spawn)
    monkeypatch.setattr(tool_mod, "await_handoff", _boom_await_handoff)

    with pytest.raises(RuntimeError, match="redis down"):
        await browser_task.coroutine(config=UI_CONFIG, task="x")
    await asyncio.sleep(0)

    assert len(tasks) == 1
    assert tasks[0].cancelled()


async def test_each_handoff_gets_its_own_id(monkeypatch: pytest.MonkeyPatch) -> None:
    async def body(h: Harness) -> BrowserResultSnapshot:
        await h.request_handoff(HandoffRequest(reason="one"))
        await h.request_handoff(HandoffRequest(reason="two"))
        return _result(BrowserSessionStatus.COMPLETED, True, "done")

    h = _install(monkeypatch, run_body=body)
    await browser_task.ainvoke({"task": "x"}, config=UI_CONFIG)
    assert h.handoffs_created[0][0] != h.handoffs_created[1][0]


# ---------------------------------------------------------------------------
# browser_task — history recording
# ---------------------------------------------------------------------------


async def test_history_records_step_captions_and_uploaded_screenshots_in_order(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Steps are 1-indexed, gaps stay blank, and a data-URL fallback is never
    stored — it would render as a permanently broken thumbnail in the recap."""

    async def body(h: Harness) -> BrowserResultSnapshot:
        await h.emit(BrowserStepSnapshot(index=1, goal="open", screenshot="https://cdn/1.png"))
        await h.emit(BrowserStepSnapshot(index=2, goal="", screenshot="data:image/png;base64,zz"))
        await h.emit(BrowserStepSnapshot(index=3, goal="submit", screenshot=None))
        await h.emit(BrowserStepSnapshot(index=4, goal="done", screenshot="http://cdn/4.png"))
        return _result(BrowserSessionStatus.COMPLETED, True, "done", steps=4)

    h = _install(monkeypatch, run_body=body)
    config: RunnableConfig = {
        "configurable": {
            "user_id": "u1",
            "conversation_id": "conv-9",
            "conversation_source": "web",
        }
    }
    await browser_task.ainvoke(
        {"task": "book a table", "start_url": "https://resy.com"}, config=config
    )
    await asyncio.sleep(0)

    assert h.spawn_names == ["record_browser_task"]
    (call,) = h.record_calls
    assert call == {
        "user_id": "u1",
        "conversation_id": "conv-9",
        "task": "book a table",
        "session_id": "sess-1",
        "result": _result(BrowserSessionStatus.COMPLETED, True, "done", steps=4),
        "step_goals": ["open", "", "submit", "done"],
        "step_screenshots": ["https://cdn/1.png", "", "", "http://cdn/4.png"],
        "source": "web",
    }


async def test_history_lists_are_sized_by_the_reported_step_count(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def body(h: Harness) -> BrowserResultSnapshot:
        await h.emit(BrowserStepSnapshot(index=1, goal="open", screenshot="https://cdn/1.png"))
        await h.emit(BrowserStepSnapshot(index=2, goal="close", screenshot="https://cdn/2.png"))
        return _result(BrowserSessionStatus.COMPLETED, True, "done", steps=1)

    h = _install(monkeypatch, run_body=body)
    await browser_task.ainvoke({"task": "x"}, config=UI_CONFIG)
    await asyncio.sleep(0)
    assert h.record_calls[0]["step_goals"] == ["open"]
    assert h.record_calls[0]["step_screenshots"] == ["https://cdn/1.png"]


async def test_history_source_is_blank_for_an_unknown_conversation_source(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    h = _install(monkeypatch)
    config: RunnableConfig = {
        "configurable": {"user_id": "u1", "thread_id": "c1", "conversation_source": "carrier-dove"}
    }
    await browser_task.ainvoke({"task": "x"}, config=config)
    await asyncio.sleep(0)
    assert h.record_calls[0]["source"] == ""


async def test_no_history_is_recorded_for_an_anonymous_run(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    h = _install(monkeypatch)
    config: RunnableConfig = {"configurable": {"thread_id": "c1"}}
    out = await browser_task.ainvoke({"task": "x"}, config=config)
    await asyncio.sleep(0)
    assert h.record_calls == []
    assert out == _completed_message("Done")


async def test_history_is_recorded_for_a_failed_run_too(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    h = _install(monkeypatch, result=_result(BrowserSessionStatus.FAILED, False, "blocked"))
    out = await browser_task.ainvoke({"task": "x"}, config=UI_CONFIG)
    await asyncio.sleep(0)
    assert h.record_calls[0]["result"].status == BrowserSessionStatus.FAILED
    assert out == _failed_message("blocked")


# ---------------------------------------------------------------------------
# browser_task — bot mirroring
# ---------------------------------------------------------------------------


async def test_bot_delivery_is_built_for_the_originating_platform(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    h = _install(monkeypatch)
    monkeypatch.setattr(tool_mod.settings, "BROWSER_USE_STREAM_SCREENSHOTS", False)
    await browser_task.ainvoke({"task": "x"}, config=BOT_CONFIG)
    assert h.delivery_kwargs == [
        {
            "platform": ConversationSource.DISCORD,
            "user_id": "u1",
            "conversation_id": "c1",
            "stream_screenshots": False,
        }
    ]


async def test_every_snapshot_kind_is_mirrored_to_its_own_delivery_channel(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    step = BrowserStepSnapshot(index=1, goal="g")
    session = BrowserSessionSnapshot(task="x", status=BrowserSessionStatus.RUNNING)
    handoff = BrowserHandoffSnapshot(handoff_id="h1", reason="r", status=HandoffStatus.PENDING)
    final = _result(BrowserSessionStatus.COMPLETED, True, "done")

    async def body(h: Harness) -> BrowserResultSnapshot:
        for snapshot in (session, step, handoff, final):
            await h.emit(snapshot)
        return final

    h = _install(monkeypatch, run_body=body)
    await browser_task.ainvoke({"task": "x"}, config=BOT_CONFIG)
    assert h.delivered == [
        ("session", session),
        ("step", step),
        ("handoff", handoff),
        ("result", final),
    ]


async def test_ui_runs_are_not_mirrored_to_a_bot(monkeypatch: pytest.MonkeyPatch) -> None:
    async def body(h: Harness) -> BrowserResultSnapshot:
        await h.emit(BrowserStepSnapshot(index=1, goal="g"))
        return _result(BrowserSessionStatus.COMPLETED, True, "done")

    h = _install(monkeypatch, run_body=body)
    await browser_task.ainvoke({"task": "x"}, config=UI_CONFIG)
    assert h.delivery_kwargs == []
    assert h.delivered == []


async def test_bot_run_without_a_known_platform_is_not_mirrored(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    h = _install(monkeypatch)
    config: RunnableConfig = {
        "configurable": {
            "user_id": "u1",
            "conversation_id": "c1",
            "source_category": "bot",
            "conversation_source": "carrier-dove",
        }
    }
    await browser_task.ainvoke({"task": "x"}, config=config)
    assert h.delivery_kwargs == []


async def test_bot_run_without_a_user_is_not_mirrored(monkeypatch: pytest.MonkeyPatch) -> None:
    h = _install(monkeypatch)
    config: RunnableConfig = {
        "configurable": {
            "conversation_id": "c1",
            "source_category": "bot",
            "conversation_source": "discord",
        }
    }
    await browser_task.ainvoke({"task": "x"}, config=config)
    assert h.delivery_kwargs == []


async def test_bot_run_without_a_conversation_is_not_mirrored(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    h = _install(monkeypatch)
    config: RunnableConfig = {
        "configurable": {
            "user_id": "u1",
            "source_category": "bot",
            "conversation_source": "discord",
        }
    }
    await browser_task.ainvoke({"task": "x"}, config=config)
    assert h.delivery_kwargs == []


async def test_failed_mirror_is_logged_with_the_snapshot_that_failed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The card is already on the stream, so a platform outage is a logged
    warning — but it must say which snapshot and which error."""

    class _Failing:
        async def step(self, snapshot: object) -> None:
            raise RuntimeError("rabbitmq down")

    async def body(h: Harness) -> BrowserResultSnapshot:
        await h.emit(BrowserStepSnapshot(index=1, goal="g"))
        return _result(BrowserSessionStatus.COMPLETED, True, "done")

    h = _install(monkeypatch, run_body=body)
    monkeypatch.setattr(tool_mod, "BotProgressDelivery", lambda **kwargs: _Failing())
    fake_log = MagicMock()
    monkeypatch.setattr(tool_mod, "log", fake_log)

    out = await browser_task.ainvoke({"task": "x"}, config=BOT_CONFIG)

    assert out == _completed_message("done")
    assert len(h.cards) == 1
    (error_call,) = fake_log.error.call_args_list
    assert error_call.args == (f"{LogTag.BROWSER} Bot delivery failed; continuing browser task",)
    assert error_call.kwargs == {
        "error_type": "RuntimeError",
        "browser": {"snapshot_type": "BrowserStepSnapshot"},
    }


async def test_run_context_is_logged_for_the_task_and_its_session(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install(monkeypatch)
    fake_log = MagicMock()
    monkeypatch.setattr(tool_mod, "log", fake_log)
    await browser_task.ainvoke({"task": "x"}, config=BOT_CONFIG)
    logged = [call.kwargs["browser"] for call in fake_log.set.call_args_list]
    assert {"operation": "task", "source_category": "bot"} in logged
    assert {"session_id": "sess-1"} in logged
