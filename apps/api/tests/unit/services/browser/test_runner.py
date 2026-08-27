"""Tests for BrowserTaskRunner — progress, the agent-driven handoff, cancel, timeout.

Browser-Use is faked so the tests exercise the runner's orchestration without a
real browser: a scripted FakeAgent invokes the runner's step callback exactly as
Browser-Use does (after the model picks actions, before they execute). The runner
no longer judges sensitivity itself — the agent hands off for itself by calling
``_handle_takeover`` (the ``request_human_takeover`` / ``solve_captcha_with_help``
actions), which is what the takeover tests below exercise directly.
"""

import asyncio
from types import SimpleNamespace
from typing import ClassVar
from unittest.mock import AsyncMock, MagicMock, Mock, call

import browser_use
import pytest

from app.constants.browser import BrowserEventKind, BrowserSessionStatus, HandoffStatus
from app.constants.log_tags import LogTag
from app.schemas.browser import BrowserAction, HandoffOutcome
from app.services.browser import runner as runner_mod
from app.services.browser.runner import BrowserTaskRunner
from app.services.browser.session import BrowserHostSession


class _Action:
    def __init__(self, name: str, params: dict):
        self._name = name
        self._params = params

    def model_dump(self, exclude_none: bool = False):
        return {self._name: self._params}


class _Output:
    def __init__(self, goal: str, actions: list[_Action]):
        self.next_goal = goal
        self.thinking = goal
        self.action = actions


class _State:
    def __init__(self, url: str):
        self.url = url
        self.title = "Page"
        self.screenshot = "ZmFrZQ=="


class _History:
    def __init__(self, done=True, successful=True, result="Done.", usage=None):
        self._done, self._successful, self._result = done, successful, result
        self.usage = usage

    def final_result(self):
        return self._result

    def is_done(self):
        return self._done

    def is_successful(self):
        return self._successful


class _ActionResult:
    def __init__(self, extracted_content=None, error=None):
        self.extracted_content = extracted_content
        self.error = error
        self.long_term_memory = None


class _AgentState:
    def __init__(self, results):
        self.last_result = [_ActionResult(**r) for r in results]


class FakeAgent:
    script: ClassVar[list[dict]] = []
    history = _History()
    # What the runner actually handed Browser-Use, for the wiring assertions.
    last_kwargs: ClassVar[dict] = {}
    last_max_steps: ClassVar[int | None] = None
    last_on_step_end: ClassVar[object] = None
    last: ClassVar["FakeAgent | None"] = None

    def __init__(self, **kwargs):
        self._on_step = kwargs["register_new_step_callback"]
        self._should_stop = kwargs["register_should_stop_callback"]
        self.stopped = False
        self.executed: list[str] = []
        type(self).last_kwargs = kwargs
        type(self).last = self

    def stop(self):
        self.stopped = True

    async def run(self, max_steps: int, on_step_end=None):
        type(self).last_max_steps = max_steps
        type(self).last_on_step_end = on_step_end
        for i, step in enumerate(type(self).script, start=1):
            if await self._should_stop() or self.stopped:
                break
            output = _Output(step["goal"], [_Action(n, p) for n, p in step["actions"]])
            await self._on_step(_State(step.get("url", "https://x")), output, i)
            if self.stopped:
                break
            self.executed.append(step["goal"])
            # Browser-Use fires on_step_end AFTER the actions execute, with the
            # results on agent.state.last_result — model the same order here.
            if on_step_end is not None:
                self.state = _AgentState(step.get("results", []))
                await on_step_end(self)
        return type(self).history


# Kwargs the runner passed to ``Browser(...)`` on the last run.
BROWSER_KWARGS: dict = {}


@pytest.fixture
def patch_browser(monkeypatch):
    monkeypatch.setattr(browser_use, "Agent", FakeAgent)

    # The runner constructs a Browser over CDP; the fake needs an awaitable stub.
    def _browser(**kwargs):
        BROWSER_KWARGS.clear()
        BROWSER_KWARGS.update(kwargs)
        return AsyncMock()

    monkeypatch.setattr(browser_use, "Browser", _browser)
    # CDN off by default → screenshots fall back to inline data URLs.
    monkeypatch.setattr(runner_mod, "upload_step_screenshot", AsyncMock(return_value=None))
    FakeAgent.script = []
    FakeAgent.history = _History()
    FakeAgent.last_kwargs = {}
    FakeAgent.last_max_steps = None
    FakeAgent.last = None
    BROWSER_KWARGS.clear()


def _session() -> BrowserHostSession:
    return BrowserHostSession(
        session_id="s1",
        cdp_url="ws://x",  # NOSONAR
        live_view_url="http://v",  # NOSONAR
        context_id="ctx-1",
    )


def _make_runner(
    *,
    emit,
    request_handoff=None,
    is_cancelled=None,
    task_timeout=30,
    stream_screenshots=True,
    user_id=None,
    root_request_id=None,
    llm=None,
):
    return BrowserTaskRunner(
        session=_session(),
        conversation_id="c1",
        llm=llm if llm is not None else object(),
        emit=emit,
        request_handoff=request_handoff
        or AsyncMock(return_value=HandoffOutcome(status=HandoffStatus.COMPLETED)),
        is_cancelled=is_cancelled or AsyncMock(return_value=False),
        max_steps=10,
        max_actions_per_step=5,
        task_timeout_seconds=task_timeout,
        step_timeout_seconds=180,
        # 0 so the wall-clock stays equal to task_timeout in these tests (the real
        # runner adds a per-handoff allowance on top).
        handoff_timeout_seconds=0,
        stream_screenshots=stream_screenshots,
        use_vision=True,
        solve_captcha=False,
        user_id=user_id,
        root_request_id=root_request_id,
    )


def _collector():
    events: list = []

    async def emit(snapshot):
        events.append(snapshot)

    return events, emit


# The exact verify-before-you-continue instruction the runner appends to every
# completed takeover. Asserted verbatim so a reworded prompt has to be deliberate.
TAKEOVER_VERIFY_TAIL = (
    "Do NOT assume the page is in the state you expect. Look at the "
    "CURRENT page now and VERIFY before doing anything else — e.g. a solved CAPTCHA "
    "shows a green checkmark and no 'please verify that you are not a robot' error "
    "remains; a login lands on the signed-in page. If the step is NOT actually "
    "complete, call the takeover / solve_captcha_with_help action again instead of "
    "proceeding. Only continue toward the goal once you have confirmed the page state "
    "yourself, and never report success you cannot see on the page."
)
TAKEOVER_DEFAULT_PREFACE = "The user says they finished that step in the live browser. "


async def test_takeover_completed_lets_agent_continue():
    _, emit = _collector()
    runner = _make_runner(
        emit=emit,
        request_handoff=AsyncMock(return_value=HandoffOutcome(status=HandoffStatus.COMPLETED)),
    )
    out = await runner._handle_takeover("Enter your card", "payment")
    assert "verify" in out.lower() or "continue" in out.lower()
    assert runner._handed_off is True
    assert runner._stopped is False


async def test_takeover_cancelled_stops_run():
    from app.services.browser.exceptions import BrowserHandoffCancelled

    _, emit = _collector()
    runner = _make_runner(
        emit=emit,
        request_handoff=AsyncMock(return_value=HandoffOutcome(status=HandoffStatus.CANCELLED)),
    )
    with pytest.raises(BrowserHandoffCancelled):
        await runner._handle_takeover("Enter your card", "payment")
    assert runner._stopped is True
    assert runner._handed_off is False


async def test_takeover_bounded_by_max_handoffs():
    from app.constants.browser import MAX_HANDOFFS_PER_TASK
    from app.services.browser.exceptions import BrowserHandoffCancelled

    _, emit = _collector()
    runner = _make_runner(
        emit=emit,
        request_handoff=AsyncMock(return_value=HandoffOutcome(status=HandoffStatus.COMPLETED)),
    )
    for _ in range(MAX_HANDOFFS_PER_TASK):
        await runner._handle_takeover("step", "none")
    with pytest.raises(BrowserHandoffCancelled):
        await runner._handle_takeover("one too many", "none")


async def test_happy_path_emits_steps_and_result(patch_browser):
    FakeAgent.script = [
        {"goal": "Open site", "actions": [("navigate", {"url": "x"})]},
        {"goal": "Read results", "actions": [("extract", {})]},
    ]
    events, emit = _collector()
    result = await _make_runner(emit=emit).run("do a thing")

    kinds = [e.kind for e in events]
    assert kinds.count(BrowserEventKind.STEP) == 2
    assert kinds[0] == BrowserEventKind.SESSION
    assert result.status == BrowserSessionStatus.COMPLETED
    step = next(e for e in events if e.kind == BrowserEventKind.STEP)
    assert step.screenshot.startswith("data:image/png;base64,")


async def test_screenshot_uses_cdn_url_when_available(patch_browser, monkeypatch):
    monkeypatch.setattr(
        runner_mod,
        "upload_step_screenshot",
        AsyncMock(return_value="https://cdn.example.com/browser_steps/c1/step_1.png?sig=abc"),
    )
    FakeAgent.script = [{"goal": "Open", "actions": [("navigate", {"url": "x"})]}]
    events, emit = _collector()
    await _make_runner(emit=emit).run("x")

    step = next(e for e in events if e.kind == BrowserEventKind.STEP)
    assert step.screenshot.startswith("https://cdn.example.com/")


async def test_cancellation_stops_run(patch_browser):
    FakeAgent.script = [{"goal": "step", "actions": [("navigate", {})]}]
    events, emit = _collector()
    result = await _make_runner(emit=emit, is_cancelled=AsyncMock(return_value=True)).run("x")
    assert result.status == BrowserSessionStatus.CANCELLED


async def test_timeout_marks_failed(patch_browser, monkeypatch):
    async def _slow_run(self, max_steps, on_step_end=None):
        await asyncio.sleep(1)
        return _History()

    monkeypatch.setattr(FakeAgent, "run", _slow_run)
    events, emit = _collector()
    result = await _make_runner(emit=emit, task_timeout=0.01).run("x")
    assert result.status == BrowserSessionStatus.FAILED
    assert "timed out" in result.summary


async def test_unexpected_agent_error_finishes_failed(patch_browser, monkeypatch):
    """An unexpected runtime failure must not leave the card stuck in RUNNING.

    A terminal FAILED result is emitted so the UI resolves and the user gets an
    honest summary instead of a forever-spinning progress card.
    """

    async def _boom(self, max_steps: int, on_step_end=None):
        raise RuntimeError("LLM provider exploded")

    monkeypatch.setattr(FakeAgent, "run", _boom)
    events, emit = _collector()
    result = await _make_runner(emit=emit).run("do a thing")
    assert result.status == BrowserSessionStatus.FAILED
    assert "failed" in result.summary.lower()
    # The result snapshot ends the run — the card never stays in RUNNING.
    assert events[-1].kind == BrowserEventKind.RESULT
    assert events[-1].status == BrowserSessionStatus.FAILED


# ---------------------------------------------------------------------------
# _extract_actions — the agent's own tool calls, mirrored into the thread
# ---------------------------------------------------------------------------


class _RecordingAction:
    """An action that remembers how the runner dumped it."""

    def __init__(self, name: str, params: dict):
        self._name = name
        self._params = params
        self.dump_kwargs: dict = {}

    def model_dump(self, **kwargs):
        self.dump_kwargs = kwargs
        return {self._name: self._params}


class _Opaque:
    """An action object Browser-Use never gave a ``model_dump``."""


def test_extract_actions_keeps_every_action_with_its_params() -> None:
    output = _Output("goal", [_Action("navigate", {"url": "x"}), _Action("click", {"index": 2})])
    assert [(a.name, a.inputs) for a in runner_mod._extract_actions(output)] == [
        ("navigate", {"url": "x"}),
        ("click", {"index": 2}),
    ]


def test_extract_actions_gives_a_paramless_action_empty_inputs() -> None:
    output = _Output("goal", [_Action("go_back", {}), _Action("click", {"index": 1})])
    assert [(a.name, a.inputs) for a in runner_mod._extract_actions(output)] == [
        ("go_back", {}),
        ("click", {"index": 1}),
    ]


def test_extract_actions_is_empty_without_actions() -> None:
    assert runner_mod._extract_actions(_Output("goal", [])) == []
    assert runner_mod._extract_actions(_Opaque()) == []


def test_extract_actions_ignores_actions_it_cannot_dump() -> None:
    assert runner_mod._extract_actions(_Output("goal", [_Opaque()])) == []


def test_extract_actions_dumps_without_unset_params() -> None:
    action = _RecordingAction("click", {"index": 1})
    runner_mod._extract_actions(_Output("goal", [action]))
    assert action.dump_kwargs == {"exclude_none": True}


# ---------------------------------------------------------------------------
# __init__ — derived timeouts and initial state
# ---------------------------------------------------------------------------


def test_init_derives_timeouts_and_starts_from_a_clean_slate() -> None:
    from app.constants.browser import MAX_HANDOFFS_PER_TASK

    _, emit = _collector()
    runner = BrowserTaskRunner(
        session=_session(),
        conversation_id="c1",
        llm=object(),
        emit=emit,
        request_handoff=AsyncMock(),
        is_cancelled=AsyncMock(return_value=False),
        max_steps=7,
        max_actions_per_step=3,
        task_timeout_seconds=300,
        step_timeout_seconds=180,
        handoff_timeout_seconds=60,
        stream_screenshots=True,
        use_vision=True,
        solve_captcha=True,
    )

    # A step that hands off waits on the human on top of its own work budget, and
    # the wall clock allows every permitted handoff to run its full duration.
    assert runner._step_timeout == 240
    assert runner._wall_clock_timeout == 300 + MAX_HANDOFFS_PER_TASK * 60
    assert runner._conversation_id == "c1"
    assert runner._max_steps == 7
    assert runner._max_actions_per_step == 3
    assert runner._task_timeout == 300
    assert runner._flash_mode is True
    assert runner._agent is None
    assert runner._stopped is False
    assert runner._handed_off is False
    assert runner._handoffs == 0
    assert runner._last_step == 0
    assert runner._last_step_at == 0.0
    assert runner._shots == []
    assert runner._emit_tasks == set()


# ---------------------------------------------------------------------------
# run — how the agent and browser are configured
# ---------------------------------------------------------------------------


def test_element_viewport_fraction_maps_centre_minus_scroll_to_a_0_1_fraction() -> None:
    """The pulse point is the element centre in viewport space, normalised.

    A control at page-y 900 with the page scrolled 800 sits at viewport-y 100;
    over an 800px viewport that is 0.125 down. Normalising means the UI needs no
    pixel size to place the pulse.
    """
    node = SimpleNamespace(
        absolute_position=SimpleNamespace(x=200.0, y=900.0, width=100.0, height=40.0)
    )
    state = SimpleNamespace(
        dom_state=SimpleNamespace(selector_map={5: node}),
        page_info=SimpleNamespace(
            viewport_width=1280, viewport_height=800, scroll_x=0, scroll_y=800
        ),
    )
    fx, fy = runner_mod._element_viewport_fraction(state, 5)
    assert fx == round((200 + 50) / 1280, 4)
    assert fy == round((900 + 20 - 800) / 800, 4)


def test_element_viewport_fraction_is_none_when_the_centre_is_off_screen() -> None:
    # A target scrolled far above the viewport has nothing to point at.
    node = SimpleNamespace(
        absolute_position=SimpleNamespace(x=10.0, y=10.0, width=20.0, height=20.0)
    )
    state = SimpleNamespace(
        dom_state=SimpleNamespace(selector_map={1: node}),
        page_info=SimpleNamespace(
            viewport_width=1280, viewport_height=800, scroll_x=0, scroll_y=5000
        ),
    )
    assert runner_mod._element_viewport_fraction(state, 1) is None


async def test_on_step_end_reports_outputs_keyed_to_the_step_just_executed() -> None:
    """Browser-Use runs on_step_end AFTER the actions, so results exist there.

    The output must key to the step _on_step already emitted rows for
    (self._last_step), and only actions with content or an error produce an
    output — a silent success adds no row.
    """
    calls: list[tuple[int, list]] = []
    runner = _make_runner(emit=AsyncMock())
    runner._action_results = lambda step, outs: calls.append((step, outs))
    runner._last_step = 4

    agent = SimpleNamespace(
        state=SimpleNamespace(
            last_result=[
                _ActionResult(extracted_content="Total: $42"),
                _ActionResult(),  # silent success — no output row
                _ActionResult(error="element not found"),
            ]
        )
    )
    await runner._on_step_end(agent)

    assert len(calls) == 1
    step, outputs = calls[0]
    assert step == 4
    by_position = {o.position: o.output for o in outputs}
    assert by_position == {0: "Total: $42", 2: "element not found"}


async def test_on_step_end_is_a_noop_without_an_action_results_sink() -> None:
    runner = _make_runner(emit=AsyncMock())
    assert runner._action_results is None
    agent = SimpleNamespace(state=SimpleNamespace(last_result=[_ActionResult(error="x")]))
    await runner._on_step_end(agent)  # must not raise


def test_the_task_preamble_forbids_inventing_field_values() -> None:
    """A missing value must become a handoff, never a plausible-looking guess.

    Measured on a real investor-application form: given only a name and an email,
    the agent typed a phone number and a country it made up, then reported the
    form as correctly filled. On a form that submits, that is fabricated data
    sent under the user's name — so the rule and its escape hatch are part of the
    prompt contract, not advice.
    """
    from app.constants.browser import BROWSER_TAKEOVER_PREAMBLE

    assert "NEVER invent a value" in BROWSER_TAKEOVER_PREAMBLE
    # The rule is only safe because it names somewhere for the agent to go.
    assert "request_human_takeover" in BROWSER_TAKEOVER_PREAMBLE


def test_the_task_preamble_routes_dropdowns_through_the_native_actions() -> None:
    from app.constants.browser import BROWSER_TAKEOVER_PREAMBLE

    assert "`dropdown_options`" in BROWSER_TAKEOVER_PREAMBLE
    assert "`select_dropdown`" in BROWSER_TAKEOVER_PREAMBLE


def test_the_tool_docs_say_each_call_is_a_fresh_browser() -> None:
    """The executor re-ran a whole form fill believing the previous session's
    values were still on the page. The docs must not let it believe that."""
    from app.templates.docstrings.browser_tool_docs import BROWSER_TASK

    assert "Each call is a fresh browser" in BROWSER_TASK


async def test_run_configures_the_agent_from_the_runner_settings(patch_browser) -> None:
    from app.constants.browser import BROWSER_TAKEOVER_PREAMBLE

    _, emit = _collector()
    runner = _make_runner(emit=emit)
    await runner.run("book a table")

    kwargs = FakeAgent.last_kwargs
    assert kwargs["task"] == "book a table" + BROWSER_TAKEOVER_PREAMBLE
    assert kwargs["llm"] is runner._llm
    assert kwargs["use_vision"] is True
    assert kwargs["flash_mode"] is True
    assert kwargs["max_actions_per_step"] == 5
    assert kwargs["step_timeout"] == runner._step_timeout
    assert kwargs["register_new_step_callback"] == runner._on_step
    assert kwargs["register_should_stop_callback"] == runner._should_stop
    assert FakeAgent.last_max_steps == 10


async def test_run_builds_the_tools_with_the_runner_takeover_and_captcha_policy(
    patch_browser, monkeypatch
) -> None:
    captured: dict = {}

    def _build(**kwargs):
        captured.update(kwargs)
        return "tools-sentinel"

    monkeypatch.setattr(runner_mod, "build_browser_tools", _build)
    _, emit = _collector()
    runner = _make_runner(emit=emit)
    await runner.run("x")

    assert captured["solve_captcha"] is False
    assert captured["handle_takeover"] == runner._handle_takeover
    assert FakeAgent.last_kwargs["tools"] == "tools-sentinel"


async def test_run_attaches_the_browser_to_the_session_cdp_at_desktop_resolution(
    patch_browser,
) -> None:
    from app.constants.browser import BROWSER_VIEWPORT_HEIGHT, BROWSER_VIEWPORT_WIDTH

    _, emit = _collector()
    await _make_runner(emit=emit).run("x")

    assert BROWSER_KWARGS["cdp_url"] == "ws://x"
    assert BROWSER_KWARGS["viewport"] == {
        "width": BROWSER_VIEWPORT_WIDTH,
        "height": BROWSER_VIEWPORT_HEIGHT,
    }
    # The live-view DPR is set host-side; Browser-Use ignores it over CDP.
    assert BROWSER_KWARGS["device_scale_factor"] == 1
    assert BROWSER_KWARGS["no_viewport"] is False


async def test_run_opens_with_a_running_session_card(patch_browser) -> None:
    events, emit = _collector()
    await _make_runner(emit=emit).run("find me a flight")

    header = events[0]
    assert header.kind == BrowserEventKind.SESSION
    assert header.task == "find me a flight"
    assert header.status == BrowserSessionStatus.RUNNING
    assert header.session_id == "s1"
    assert header.live_view_url == "http://v"


async def test_run_bounds_the_agent_by_the_wall_clock_budget(patch_browser, monkeypatch) -> None:
    seen: dict = {}
    real_wait_for = asyncio.wait_for

    async def _spy(awaitable, timeout):
        seen["timeout"] = timeout
        return await real_wait_for(awaitable, timeout)

    monkeypatch.setattr(runner_mod.asyncio, "wait_for", _spy)
    _, emit = _collector()
    # A handoff allowance on top, so the wall clock is distinct from every other
    # budget the runner holds (task 42, step 180 + 60).
    runner = BrowserTaskRunner(
        session=_session(),
        conversation_id="c1",
        llm=object(),
        emit=emit,
        request_handoff=AsyncMock(),
        is_cancelled=AsyncMock(return_value=False),
        max_steps=10,
        max_actions_per_step=5,
        task_timeout_seconds=42,
        step_timeout_seconds=180,
        handoff_timeout_seconds=60,
        stream_screenshots=True,
        use_vision=True,
        solve_captcha=False,
    )
    await runner.run("x")

    assert seen["timeout"] == runner._wall_clock_timeout
    assert seen["timeout"] not in (42, 240)


# ---------------------------------------------------------------------------
# run — terminal outcomes
# ---------------------------------------------------------------------------


async def _run_raising(monkeypatch, exc: BaseException, **runner_kwargs):
    async def _boom(self, max_steps: int, on_step_end=None):
        raise exc

    monkeypatch.setattr(FakeAgent, "run", _boom)
    events, emit = _collector()
    runner = _make_runner(emit=emit, **runner_kwargs)
    return runner, events


async def test_handoff_cancellation_after_a_takeover_completes_the_task(
    patch_browser, monkeypatch
) -> None:
    from app.services.browser.exceptions import BrowserHandoffCancelled

    runner, _ = await _run_raising(monkeypatch, BrowserHandoffCancelled("completed"))
    runner._handed_off = True
    result = await runner.run("x")

    assert result.status == BrowserSessionStatus.COMPLETED
    assert result.success is True
    assert result.summary == "You completed the sensitive step in the live browser."


async def test_handoff_cancellation_without_a_takeover_cancels_the_task(
    patch_browser, monkeypatch
) -> None:
    from app.services.browser.exceptions import BrowserHandoffCancelled

    runner, _ = await _run_raising(monkeypatch, BrowserHandoffCancelled("cancelled"))
    result = await runner.run("x")

    assert result.status == BrowserSessionStatus.CANCELLED
    assert result.success is False
    assert result.summary == "Browser task was stopped."


async def test_interrupted_agent_is_treated_as_a_stop(patch_browser, monkeypatch) -> None:
    runner, _ = await _run_raising(monkeypatch, InterruptedError())
    result = await runner.run("x")

    assert result.status == BrowserSessionStatus.CANCELLED
    assert result.summary == "Browser task was stopped."


async def test_timeout_stops_the_agent_and_names_the_task_budget(
    patch_browser, monkeypatch
) -> None:
    async def _slow_run(self, max_steps, on_step_end=None):
        await asyncio.sleep(1)
        return _History()

    monkeypatch.setattr(FakeAgent, "run", _slow_run)
    _, emit = _collector()
    result = await _make_runner(emit=emit, task_timeout=0.01).run("x")

    assert result.status == BrowserSessionStatus.FAILED
    assert result.success is False
    assert result.summary == "Browser task timed out after 0.01s."
    # The agent must actually be told to stop, not just abandoned.
    assert FakeAgent.last.stopped is True


@pytest.mark.parametrize("exc", [ConnectionError("refused"), OSError("no route")])
async def test_cdp_attach_failure_surfaces_as_browser_unavailable(
    patch_browser, monkeypatch, exc: Exception
) -> None:
    from app.services.browser.exceptions import BrowserUnavailableError

    runner, _ = await _run_raising(monkeypatch, exc)
    with pytest.raises(BrowserUnavailableError) as err:
        await runner.run("x")

    message = str(err.value)
    assert "ws://x" in message
    assert str(exc) in message
    assert "BROWSER_HOST_URL" in message


async def test_unexpected_failure_summary_carries_the_reason(patch_browser, monkeypatch) -> None:
    runner, _ = await _run_raising(monkeypatch, RuntimeError("LLM provider exploded"))
    result = await runner.run("x")

    assert result.summary == "Browser task failed: LLM provider exploded"
    assert result.success is False


async def test_a_stopped_run_without_a_takeover_is_cancelled(patch_browser) -> None:
    _, emit = _collector()
    runner = _make_runner(emit=emit)
    runner._stopped = True
    result = await runner.run("x")

    assert result.status == BrowserSessionStatus.CANCELLED
    assert result.success is False
    assert result.summary == "Browser task stopped."


async def test_a_stopped_run_after_a_takeover_counts_as_completed(patch_browser) -> None:
    _, emit = _collector()
    runner = _make_runner(emit=emit)
    runner._stopped = True
    runner._handed_off = True
    result = await runner.run("x")

    assert result.status == BrowserSessionStatus.COMPLETED
    assert result.success is True
    assert result.summary == "Browser task stopped."


async def test_cancelled_run_reports_the_cancellation_not_the_history(patch_browser) -> None:
    FakeAgent.history = _History(done=True, successful=True, result="Done.")
    _, emit = _collector()
    result = await _make_runner(emit=emit, is_cancelled=AsyncMock(return_value=True)).run("x")

    assert result.status == BrowserSessionStatus.CANCELLED
    assert result.success is False
    assert result.summary == "Browser task was cancelled."


async def test_should_stop_fires_on_either_signal() -> None:
    _, emit = _collector()
    runner = _make_runner(emit=emit, is_cancelled=AsyncMock(return_value=False))
    assert await runner._should_stop() is False
    runner._stopped = True
    assert await runner._should_stop() is True

    stopped_by_chat = _make_runner(emit=emit, is_cancelled=AsyncMock(return_value=True))
    assert await stopped_by_chat._should_stop() is True


# ---------------------------------------------------------------------------
# _handle_takeover
# ---------------------------------------------------------------------------


async def test_takeover_forwards_the_reason_and_category_to_the_handoff() -> None:
    from app.constants.browser import SensitiveCategory

    _, emit = _collector()
    handoff = AsyncMock(return_value=HandoffOutcome(status=HandoffStatus.COMPLETED))
    runner = _make_runner(emit=emit, request_handoff=handoff)
    await runner._handle_takeover("Enter your password and click Login", "credentials")

    request = handoff.await_args.args[0]
    assert request.category == SensitiveCategory.CREDENTIALS
    assert request.reason == "Enter your password and click Login"


async def test_unknown_takeover_category_falls_back_to_irreversible() -> None:
    from app.constants.browser import SensitiveCategory

    _, emit = _collector()
    handoff = AsyncMock(return_value=HandoffOutcome(status=HandoffStatus.COMPLETED))
    runner = _make_runner(emit=emit, request_handoff=handoff)
    await runner._handle_takeover("Confirm the order", "not-a-category")

    assert handoff.await_args.args[0].category == SensitiveCategory.IRREVERSIBLE


async def test_takeover_note_becomes_a_direct_instruction_for_the_agent() -> None:
    _, emit = _collector()
    runner = _make_runner(
        emit=emit,
        request_handoff=AsyncMock(
            return_value=HandoffOutcome(
                status=HandoffStatus.COMPLETED, message="  just grab the photo  "
            )
        ),
    )
    out = await runner._handle_takeover("Log in", "credentials")

    assert out == (
        'The user handed control back with this instruction: "just grab the photo". '
        "Follow it.\n\n" + TAKEOVER_VERIFY_TAIL
    )


async def test_takeover_without_a_note_uses_the_default_preface() -> None:
    _, emit = _collector()
    runner = _make_runner(
        emit=emit,
        request_handoff=AsyncMock(
            return_value=HandoffOutcome(status=HandoffStatus.COMPLETED, message="   ")
        ),
    )
    out = await runner._handle_takeover("Log in", "credentials")

    assert out == TAKEOVER_DEFAULT_PREFACE + TAKEOVER_VERIFY_TAIL


@pytest.mark.parametrize(
    "status", [HandoffStatus.CANCELLED, HandoffStatus.TIMEOUT, HandoffStatus.PENDING]
)
async def test_a_non_completed_handoff_stops_the_run_and_names_its_status(
    status: HandoffStatus,
) -> None:
    from app.services.browser.exceptions import BrowserHandoffCancelled

    _, emit = _collector()
    runner = _make_runner(
        emit=emit, request_handoff=AsyncMock(return_value=HandoffOutcome(status=status))
    )
    with pytest.raises(BrowserHandoffCancelled) as err:
        await runner._handle_takeover("Pay now", "payment")

    assert str(err.value) == status.value
    assert runner._stopped is True
    assert runner._handed_off is False


async def test_the_handoff_over_the_limit_never_reaches_the_user() -> None:
    from app.constants.browser import MAX_HANDOFFS_PER_TASK
    from app.services.browser.exceptions import BrowserHandoffCancelled

    _, emit = _collector()
    handoff = AsyncMock(return_value=HandoffOutcome(status=HandoffStatus.COMPLETED))
    runner = _make_runner(emit=emit, request_handoff=handoff)
    for _ in range(MAX_HANDOFFS_PER_TASK):
        await runner._handle_takeover("step", "none")
    assert runner._handoffs == MAX_HANDOFFS_PER_TASK

    with pytest.raises(BrowserHandoffCancelled) as err:
        await runner._handle_takeover("one too many", "none")

    assert str(err.value) == "max-handoffs"
    assert runner._stopped is True
    assert handoff.await_count == MAX_HANDOFFS_PER_TASK


# ---------------------------------------------------------------------------
# _on_step / _emit_step — the progress card
# ---------------------------------------------------------------------------


async def _drain(runner: BrowserTaskRunner) -> None:
    """Await the step emits the callback spawned off Browser-Use's loop."""
    for task in list(runner._emit_tasks):
        await task


async def test_step_card_carries_the_goal_actions_and_page(patch_browser) -> None:
    events, emit = _collector()
    runner = _make_runner(emit=emit)
    state = _State("https://example.com/cart")
    state.title = "Your cart"
    await runner._on_step(state, _Output("Check out", [_Action("click", {"index": 4})]), 3)
    await _drain(runner)

    step = events[-1]
    assert step.kind == BrowserEventKind.STEP
    assert step.index == 3
    assert step.goal == "Check out"
    assert [(a.name, a.inputs) for a in step.actions] == [("click", {"index": 4})]
    assert step.url == "https://example.com/cart"
    assert step.title == "Your cart"
    assert runner._last_step == 3


async def test_step_goal_falls_back_to_the_models_thinking(patch_browser) -> None:
    events, emit = _collector()
    runner = _make_runner(emit=emit)
    output = _Output("", [_Action("click", {})])
    output.thinking = "Deciding what to click"
    await runner._on_step(_State("https://x"), output, 1)
    await _drain(runner)

    assert events[-1].goal == "Deciding what to click"


async def test_step_goal_falls_back_to_a_caption_from_the_actions(patch_browser) -> None:
    events, emit = _collector()
    runner = _make_runner(emit=emit)
    output = _Output("", [_Action("navigate", {"url": "https://www.example.com/x"})])
    output.thinking = ""
    await runner._on_step(_State("https://x"), output, 1)
    await _drain(runner)

    assert events[-1].goal == "Opening example.com"


async def test_a_step_with_no_actions_carries_no_actions(patch_browser) -> None:
    events, emit = _collector()
    runner = _make_runner(emit=emit)
    await runner._on_step(_State("https://x"), _Output("Waiting", []), 1)
    await _drain(runner)

    assert events[-1].actions == []


async def test_only_uploaded_screenshots_become_replay_frames(patch_browser, monkeypatch) -> None:
    monkeypatch.setattr(
        runner_mod,
        "upload_step_screenshot",
        AsyncMock(side_effect=["https://cdn.example.com/step_1.png", None]),
    )
    _, emit = _collector()
    runner = _make_runner(emit=emit)
    await runner._on_step(_State("https://x"), _Output("a", []), 1)
    await _drain(runner)
    await runner._on_step(_State("https://x"), _Output("b", []), 2)
    await _drain(runner)

    # The inline data-URL fallback is not a frame the recap can play back.
    assert runner._shots == ["https://cdn.example.com/step_1.png"]


async def test_step_cards_are_flushed_before_the_result(patch_browser) -> None:
    FakeAgent.script = [
        {"goal": "Open site", "actions": [("navigate", {"url": "x"})]},
        {"goal": "Read results", "actions": [("extract", {})]},
    ]
    events, emit = _collector()
    await _make_runner(emit=emit).run("x")

    kinds = [e.kind for e in events]
    assert kinds == [
        BrowserEventKind.SESSION,
        BrowserEventKind.STEP,
        BrowserEventKind.STEP,
        BrowserEventKind.RESULT,
    ]


# ---------------------------------------------------------------------------
# _render_screenshot
# ---------------------------------------------------------------------------


async def test_no_screenshot_when_streaming_is_off() -> None:
    _, emit = _collector()
    runner = _make_runner(emit=emit, stream_screenshots=False)
    assert await runner._render_screenshot("ZmFrZQ==", 1) is None


async def test_no_screenshot_when_the_state_has_none() -> None:
    _, emit = _collector()
    runner = _make_runner(emit=emit)
    assert await runner._render_screenshot(None, 1) is None
    assert await runner._render_screenshot("", 1) is None


async def test_undecodable_screenshot_is_dropped(patch_browser) -> None:
    _, emit = _collector()
    runner = _make_runner(emit=emit)
    assert await runner._render_screenshot("abc", 1) is None


async def test_screenshot_is_uploaded_under_the_session_and_step(
    patch_browser, monkeypatch
) -> None:
    upload = AsyncMock(return_value="https://cdn.example.com/browser_steps/s1/step_4.png")
    monkeypatch.setattr(runner_mod, "upload_step_screenshot", upload)
    _, emit = _collector()
    runner = _make_runner(emit=emit)

    url = await runner._render_screenshot("ZmFrZQ==", 4)

    assert url == "https://cdn.example.com/browser_steps/s1/step_4.png"
    # Keyed by session id (not conversation) so each run is its own replay folder.
    assert upload.await_args.args == (b"fake", "s1", 4)


async def test_screenshot_falls_back_to_an_inline_data_url(patch_browser) -> None:
    _, emit = _collector()
    runner = _make_runner(emit=emit)
    assert await runner._render_screenshot("ZmFrZQ==", 1) == "data:image/png;base64,ZmFrZQ=="


# ---------------------------------------------------------------------------
# _finish
# ---------------------------------------------------------------------------


async def test_finish_links_a_recap_built_from_the_uploaded_frames(monkeypatch) -> None:
    replay = AsyncMock(return_value="https://browser.example.com/replays/abc")
    monkeypatch.setattr(runner_mod, "create_replay_link", replay)
    events, emit = _collector()
    runner = _make_runner(emit=emit)
    runner._shots = ["https://cdn.example.com/step_1.png"]
    runner._last_step = 6

    result = await runner._finish(BrowserSessionStatus.COMPLETED, True, "All done.")

    assert replay.await_args.args == ("s1", ["https://cdn.example.com/step_1.png"])
    assert result.replay_url == "https://browser.example.com/replays/abc"
    assert result.steps == 6
    assert result.status == BrowserSessionStatus.COMPLETED
    assert result.success is True
    assert result.summary == "All done."
    assert events[-1] is result


# ---------------------------------------------------------------------------
# _finish_from_history
# ---------------------------------------------------------------------------


class _BrokenHistory(_History):
    def final_result(self):
        raise RuntimeError("history unreadable")


class _HalfReadableHistory(_History):
    """Reads the result and the done flag, then breaks — so the success flag keeps
    whatever the runner initialised it to."""

    def is_successful(self):
        raise RuntimeError("success flag unreadable")


async def test_unreadable_history_reports_an_honest_failure() -> None:
    """A history that cannot be read falls back to a complete, honest FAILED
    snapshot — every field of it, so the fallbacks the ``try`` leaves in place
    stay pinned."""
    events, emit = _collector()
    result = await _make_runner(emit=emit)._finish_from_history(_BrokenHistory())

    assert result.model_dump() == {
        "kind": BrowserEventKind.RESULT,
        "status": BrowserSessionStatus.FAILED,
        "success": False,
        "summary": "Could not complete the browser task.",
        "steps": 0,
        "replay_url": None,
    }
    assert events == [result]


async def test_a_history_that_breaks_midway_still_reports_what_it_read() -> None:
    """``is_done`` succeeded and ``is_successful`` raised: the run is judged done
    and the final result it did read becomes the summary."""
    events, emit = _collector()
    result = await _make_runner(emit=emit)._finish_from_history(
        _HalfReadableHistory(result="Booked seat 14C.")
    )

    assert result.model_dump() == {
        "kind": BrowserEventKind.RESULT,
        "status": BrowserSessionStatus.COMPLETED,
        "success": True,
        "summary": "Booked seat 14C.",
        "steps": 0,
        "replay_url": None,
    }
    assert events == [result]


async def test_a_finished_history_without_a_final_result_gets_a_default_summary() -> None:
    _, emit = _collector()
    result = await _make_runner(emit=emit)._finish_from_history(
        _History(done=True, successful=True, result=None)
    )

    assert result.status == BrowserSessionStatus.COMPLETED
    assert result.success is True
    assert result.summary == "Completed the browser task."


async def test_an_explicitly_unsuccessful_history_fails() -> None:
    _, emit = _collector()
    result = await _make_runner(emit=emit)._finish_from_history(
        _History(done=True, successful=False, result=None)
    )

    assert result.status == BrowserSessionStatus.FAILED
    assert result.success is False
    assert result.summary == "Could not complete the browser task."


async def test_an_unfinished_history_fails_even_when_not_marked_unsuccessful() -> None:
    _, emit = _collector()
    result = await _make_runner(emit=emit)._finish_from_history(
        _History(done=False, successful=True, result=None)
    )

    assert result.status == BrowserSessionStatus.FAILED
    assert result.success is False


async def test_an_unknown_success_flag_still_counts_as_done() -> None:
    """Browser-Use reports ``None`` when it cannot judge — only an explicit
    ``False`` is a failure."""
    _, emit = _collector()
    result = await _make_runner(emit=emit)._finish_from_history(
        _History(done=True, successful=None, result="Booked.")
    )

    assert result.status == BrowserSessionStatus.COMPLETED
    assert result.success is True
    assert result.summary == "Booked."


async def test_the_agents_final_result_becomes_the_summary() -> None:
    _, emit = _collector()
    result = await _make_runner(emit=emit)._finish_from_history(
        _History(done=True, successful=True, result="The cheapest flight is 42 pounds.")
    )

    assert result.summary == "The cheapest flight is 42 pounds."


# ---------------------------------------------------------------------------
# _record_usage
# ---------------------------------------------------------------------------


class _Stats:
    def __init__(self, prompt_tokens: int, completion_tokens: int):
        self.prompt_tokens = prompt_tokens
        self.completion_tokens = completion_tokens


class _Usage:
    def __init__(self, by_model: dict):
        self.by_model = by_model


async def test_no_usage_is_recorded_when_browser_use_reports_none(monkeypatch) -> None:
    record = AsyncMock()
    monkeypatch.setattr(runner_mod, "record_llm_call", record)
    _, emit = _collector()
    await _make_runner(emit=emit)._record_usage(_History(usage=None))

    assert record.await_count == 0


async def test_each_models_tokens_are_charged_to_the_users_budget(monkeypatch) -> None:
    record = AsyncMock()
    monkeypatch.setattr(runner_mod, "record_llm_call", record)
    _, emit = _collector()
    runner = _make_runner(emit=emit, user_id="u1", root_request_id="req-1")

    await runner._record_usage(
        _History(usage=_Usage({"gemini-flash": _Stats(1200, 34), "claude-sonnet": _Stats(90, 7)}))
    )

    by_model = {call.kwargs["model_name"]: call.kwargs for call in record.await_args_list}
    assert by_model["gemini-flash"] == {
        "user_id": "u1",
        "model_name": "gemini-flash",
        "input_tokens": 1200,
        "output_tokens": 34,
        "root_request_id": "req-1",
        "charge_to_budget": True,
    }
    assert by_model["claude-sonnet"]["input_tokens"] == 90
    assert by_model["claude-sonnet"]["output_tokens"] == 7


async def test_a_completed_run_charges_its_llm_usage(patch_browser, monkeypatch) -> None:
    record = AsyncMock()
    monkeypatch.setattr(runner_mod, "record_llm_call", record)
    FakeAgent.history = _History(usage=_Usage({"gemini-flash": _Stats(10, 2)}))
    _, emit = _collector()
    await _make_runner(emit=emit, user_id="u1").run("x")

    assert record.await_args.kwargs["model_name"] == "gemini-flash"
    assert record.await_args.kwargs["user_id"] == "u1"


# ---------------------------------------------------------------------------
# The exact wiring, wording and timing the wave-1 assertions let slide
# ---------------------------------------------------------------------------


AGENT_KWARG_KEYS = {
    "task",
    "llm",
    "browser",
    "register_new_step_callback",
    "register_should_stop_callback",
    "use_vision",
    "flash_mode",
    "max_actions_per_step",
    "step_timeout",
    "tools",
    "extend_system_message",
}


async def test_run_hands_browser_use_exactly_the_expected_agent_keys(patch_browser) -> None:
    _, emit = _collector()
    await _make_runner(emit=emit).run("x")

    assert set(FakeAgent.last_kwargs) == AGENT_KWARG_KEYS


async def test_run_gives_the_agent_the_llm_it_was_constructed_with(patch_browser) -> None:
    sentinel = object()
    _, emit = _collector()
    await _make_runner(emit=emit, llm=sentinel).run("x")

    assert FakeAgent.last_kwargs["llm"] is sentinel


async def test_cdp_attach_failure_names_the_url_the_error_and_the_setting(
    patch_browser, monkeypatch
) -> None:
    from app.services.browser.exceptions import BrowserUnavailableError

    runner, _ = await _run_raising(monkeypatch, ConnectionError("refused"))
    with pytest.raises(BrowserUnavailableError) as err:
        await runner.run("x")

    assert str(err.value) == (
        "Could not attach to the browser over CDP at ws://x: refused. "
        "Check that the browser host is reachable from the API at BROWSER_HOST_URL."
    )


async def test_an_unexpected_failure_is_logged_with_its_type_and_session(
    patch_browser, monkeypatch
) -> None:
    logger = MagicMock()
    monkeypatch.setattr(runner_mod, "log", logger)
    runner, _ = await _run_raising(monkeypatch, RuntimeError("LLM provider exploded"))

    await runner.run("x")

    logger.error.assert_called_once_with(
        f"{LogTag.BROWSER} Browser agent failed unexpectedly",
        error_type="RuntimeError",
        browser={"session_id": "s1"},
    )


async def test_a_takeover_without_any_note_uses_the_default_preface_verbatim() -> None:
    _, emit = _collector()
    runner = _make_runner(
        emit=emit,
        request_handoff=AsyncMock(
            return_value=HandoffOutcome(status=HandoffStatus.COMPLETED, message=None)
        ),
    )
    out = await runner._handle_takeover("Log in", "credentials")

    assert out == TAKEOVER_DEFAULT_PREFACE + TAKEOVER_VERIFY_TAIL


class _GoalOutput:
    """A step output whose goal fields are set independently, unlike ``_Output``."""

    def __init__(self, *, next_goal: str, thinking: str, actions: list[_Action]):
        self.next_goal = next_goal
        self.thinking = thinking
        self.action = actions


class _ThinklessOutput:
    """Flash mode: the model returned neither a goal nor any thinking text."""

    def __init__(self, actions: list[_Action]):
        self.next_goal = ""
        self.action = actions


class _BareState:
    """A browser state summary Browser-Use gave no url, title or screenshot."""


async def test_the_models_next_goal_wins_over_its_thinking(patch_browser) -> None:
    events, emit = _collector()
    runner = _make_runner(emit=emit)
    output = _GoalOutput(
        next_goal="Check out", thinking="Deciding what to click", actions=[_Action("click", {})]
    )
    await runner._on_step(_State("https://x"), output, 1)
    await _drain(runner)

    assert events[-1].goal == "Check out"


async def test_a_step_with_no_thinking_attribute_captions_from_its_actions(patch_browser) -> None:
    events, emit = _collector()
    runner = _make_runner(emit=emit)
    output = _ThinklessOutput([_Action("navigate", {"url": "https://www.example.com/x"})])
    await runner._on_step(_State("https://x"), output, 1)
    await _drain(runner)

    assert events[-1].goal == "Opening example.com"


async def test_a_state_without_url_title_or_screenshot_still_emits_a_step(patch_browser) -> None:
    events, emit = _collector()
    runner = _make_runner(emit=emit)
    await runner._on_step(_BareState(), _Output("Waiting", []), 1)
    await _drain(runner)

    step = events[-1]
    assert step.url is None
    assert step.title is None
    assert step.screenshot is None


async def test_each_step_reports_the_wall_clock_since_the_previous_one(
    patch_browser, monkeypatch
) -> None:
    _, emit = _collector()
    runner = _make_runner(emit=emit)
    emit_step = AsyncMock()
    monkeypatch.setattr(runner, "_emit_step", emit_step)
    monkeypatch.setattr(runner_mod, "perf_counter", Mock(side_effect=[100.0, 102.5]))

    output = _Output("Check out", [_Action("click", {"index": 4})])
    state = _State("https://example.com/cart")
    await runner._on_step(state, output, 1)
    await _drain(runner)
    await runner._on_step(state, output, 2)
    await _drain(runner)

    # The first step has no predecessor to measure against; the second reports 2.5s.
    assert emit_step.await_args_list == [
        call(
            1,
            "Check out",
            [BrowserAction(name="click", inputs={"index": 4})],
            "https://example.com/cart",
            "Page",
            "ZmFrZQ==",
            0,
        ),
        call(
            2,
            "Check out",
            [BrowserAction(name="click", inputs={"index": 4})],
            "https://example.com/cart",
            "Page",
            "ZmFrZQ==",
            2500,
        ),
    ]


async def test_the_step_emit_is_spawned_as_a_named_background_task(
    patch_browser, monkeypatch
) -> None:
    spawned: list[dict] = []
    real_spawn = runner_mod.spawn_background_task

    def _spy(coro, **kwargs):
        spawned.append(kwargs)
        return real_spawn(coro, **kwargs)

    monkeypatch.setattr(runner_mod, "spawn_background_task", _spy)
    _, emit = _collector()
    runner = _make_runner(emit=emit)
    await runner._on_step(_State("https://x"), _Output("a", []), 1)
    await _drain(runner)

    assert spawned == [{"name": "browser_step_emit"}]


async def test_a_finished_step_emit_releases_its_slot(patch_browser) -> None:
    _, emit = _collector()
    runner = _make_runner(emit=emit)
    await runner._on_step(_State("https://x"), _Output("a", []), 1)
    await _drain(runner)
    await asyncio.sleep(0)

    # The done-callback discards the task, so the flush set never grows unbounded.
    assert runner._emit_tasks == set()


async def test_the_step_frame_is_uploaded_under_that_steps_index(
    patch_browser, monkeypatch
) -> None:
    upload = AsyncMock(return_value="https://cdn.example.com/step_7.png")
    monkeypatch.setattr(runner_mod, "upload_step_screenshot", upload)
    _, emit = _collector()
    runner = _make_runner(emit=emit)

    await runner._emit_step(
        7, "goal", [BrowserAction(name="click")], "https://x", "Page", "ZmFrZQ==", 12
    )

    assert upload.await_args.args == (b"fake", "s1", 7)


async def test_the_step_timing_log_reports_the_screenshot_and_emit_cost(
    patch_browser, monkeypatch
) -> None:
    logger = MagicMock()
    monkeypatch.setattr(runner_mod, "log", logger)
    # shot_t0, after-screenshot, emit_t0, after-emit.
    monkeypatch.setattr(runner_mod, "perf_counter", Mock(side_effect=[10.0, 12.5, 20.0, 21.0]))
    _, emit = _collector()
    runner = _make_runner(emit=emit)

    await runner._emit_step(
        7, "goal", [BrowserAction(name="click")], "https://x", "Page", "ZmFrZQ==", 12
    )

    logger.info.assert_called_once_with(
        f"{LogTag.BROWSER} step timing",
        step=7,
        since_prev_ms=12,
        screenshot_ms=2500,
        emit_ms=1000,
    )


async def test_a_failed_step_emit_never_sinks_the_result(patch_browser) -> None:
    _, emit = _collector()
    runner = _make_runner(emit=emit)

    async def _boom() -> None:
        raise RuntimeError("emit exploded")

    runner._emit_tasks.add(asyncio.create_task(_boom()))
    result = await runner._finish(BrowserSessionStatus.COMPLETED, True, "All done.")

    assert result.status == BrowserSessionStatus.COMPLETED
    assert result.summary == "All done."


async def test_an_unreadable_history_is_logged_with_the_error_type(monkeypatch) -> None:
    logger = MagicMock()
    monkeypatch.setattr(runner_mod, "log", logger)
    _, emit = _collector()

    await _make_runner(emit=emit)._finish_from_history(_BrokenHistory())

    logger.warning.assert_called_once_with(
        f"{LogTag.BROWSER} Could not read browser history result",
        error_type="RuntimeError",
    )
