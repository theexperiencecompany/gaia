"""Tests for BrowserTaskRunner: progress, the agent-driven handoff, cancel, timeout.

Browser-Use is faked so the tests exercise the runner's orchestration without a
real browser: a scripted FakeAgent invokes the runner's step callback exactly as
Browser-Use does (after the model picks actions, before they execute). The runner
no longer judges sensitivity itself; the agent hands off for itself by calling
_handle_takeover (the request_human_takeover and solve_captcha_with_help
actions), which is what the takeover tests below exercise directly.
"""

import asyncio
from dataclasses import dataclass
from types import SimpleNamespace
from typing import Any, ClassVar
from unittest.mock import AsyncMock, MagicMock, Mock, call

import browser_use
import pytest

from app.constants.browser import (
    BROWSER_RUN_HANDOFF_TIMED_OUT,
    BrowserEventKind,
    BrowserSessionStatus,
    HandoffStatus,
)
from app.constants.log_tags import LogTag
from app.schemas.browser import BrowserAction, HandoffOutcome
from app.services.browser import agent_run, run_contract, runner as runner_mod
from app.services.browser.agent_run import outcome_from_history
from app.services.browser.jev.chat_model import JevChatModel
from app.services.browser.jev.policy import JevHistoryEntry
from app.services.browser.run_contract import ActionResultsFn, BrowserRunConfig, StepFrame
from app.services.browser.runner import BrowserRunnerCallbacks, BrowserTaskRunner
from app.services.browser.session import BrowserHostSession
from app.services.llm_metering import LLMCallContext, TokenUsage


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
    monkeypatch.setattr(runner_mod, "publish_step_screenshot", AsyncMock(return_value=None))
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


@dataclass(frozen=True)
class _RunnerOverrides:
    """The tuning knobs and identity a runner test may vary beyond its callbacks."""

    task_timeout: float = 30
    stream_screenshots: bool = True
    user_id: str | None = None
    root_request_id: str | None = None
    # The runner only ever forwards the llm to Browser-Use, so the tests pass an
    # identity sentinel rather than constructing a real BaseChatModel.
    llm: Any = None
    action_results: ActionResultsFn | None = None


def _make_runner(*, emit, request_handoff=None, is_cancelled=None, overrides=_RunnerOverrides()):
    return BrowserTaskRunner(
        session=_session(),
        llm=overrides.llm if overrides.llm is not None else object(),
        callbacks=BrowserRunnerCallbacks(
            emit=emit,
            request_handoff=request_handoff
            or AsyncMock(return_value=HandoffOutcome(status=HandoffStatus.COMPLETED)),
            is_cancelled=is_cancelled or AsyncMock(return_value=False),
            action_results=overrides.action_results,
        ),
        config=BrowserRunConfig(
            max_steps=10,
            max_actions_per_step=5,
            task_timeout_seconds=overrides.task_timeout,
            step_timeout_seconds=180,
            # 0 so the wall-clock stays equal to task_timeout in these tests (the real
            # runner adds a per-handoff allowance on top).
            handoff_timeout_seconds=0,
            stream_screenshots=overrides.stream_screenshots,
            solve_captcha=False,
        ),
        user_id=overrides.user_id,
        root_request_id=overrides.root_request_id,
    )


def _collector():
    events: list = []

    async def emit(snapshot):
        events.append(snapshot)

    return events, emit


async def test_takeover_completed_lets_agent_continue():
    _, emit = _collector()
    runner = _make_runner(
        emit=emit,
        request_handoff=AsyncMock(return_value=HandoffOutcome(status=HandoffStatus.COMPLETED)),
    )
    await runner._handle_takeover("Enter your card", "payment")
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
        "publish_step_screenshot",
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
    result = await _make_runner(emit=emit, overrides=_RunnerOverrides(task_timeout=0.01)).run("x")
    assert result.status == BrowserSessionStatus.FAILED
    assert "timed out" in result.summary


async def test_unexpected_agent_error_finishes_failed(patch_browser, monkeypatch):
    """Emit a terminal FAILED result instead of leaving the card stuck in RUNNING."""

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
    """An action object Browser-Use never gave a model_dump."""


def test_extract_actions_keeps_every_action_with_its_params() -> None:
    output = _Output("goal", [_Action("navigate", {"url": "x"}), _Action("click", {"index": 2})])
    assert [(a.name, a.inputs) for a in agent_run._extract_actions(output)] == [
        ("navigate", {"url": "x"}),
        ("click", {"index": 2}),
    ]


def test_extract_actions_gives_a_paramless_action_empty_inputs() -> None:
    output = _Output("goal", [_Action("go_back", {}), _Action("click", {"index": 1})])
    assert [(a.name, a.inputs) for a in agent_run._extract_actions(output)] == [
        ("go_back", {}),
        ("click", {"index": 1}),
    ]


def test_extract_actions_is_empty_without_actions() -> None:
    assert agent_run._extract_actions(_Output("goal", [])) == []
    assert agent_run._extract_actions(_Opaque()) == []


def test_extract_actions_ignores_actions_it_cannot_dump() -> None:
    assert agent_run._extract_actions(_Output("goal", [_Opaque()])) == []


def _targeted_state(index: int) -> SimpleNamespace:
    """Build step state where element index is a named button."""
    node = _LabelNode(text="", ax_node=SimpleNamespace(name="Sign in"), attributes={})
    return SimpleNamespace(dom_state=SimpleNamespace(selector_map={index: node}))


def test_extract_actions_names_the_element_and_points_where_the_page_said_it_is() -> None:
    """An index is meaningless to a reader: the step state names the control, and the centre comes from the page's own measurement, never from the snapshot's boxes."""
    output = _Output("goal", [_Action("click", {"index": 4})])
    [action] = agent_run._extract_actions(output, _targeted_state(4), {4: (0.25, 0.5)})
    assert action.target == "Sign in"
    assert action.point == (0.25, 0.5)


def test_extract_actions_leaves_point_unset_when_the_page_did_not_measure_it() -> None:
    output = _Output("goal", [_Action("click", {"index": 4})])
    [action] = agent_run._extract_actions(output, _targeted_state(4), {9: (0.1, 0.1)})
    assert action.point is None


def test_extract_actions_leaves_target_and_point_unset_for_a_different_element() -> None:
    # The index is looked up in the map, not assumed present — a stale index names
    # nothing rather than mislabelling another control.
    output = _Output("goal", [_Action("click", {"index": 4})])
    [action] = agent_run._extract_actions(output, _targeted_state(9))
    assert action.target is None
    assert action.point is None


def test_extract_actions_leaves_target_and_point_unset_for_an_untargeted_action() -> None:
    # An action with no element index (scroll, go_back) targets nothing on the page.
    output = _Output("goal", [_Action("go_back", {})])
    [action] = agent_run._extract_actions(output, _targeted_state(4))
    assert action.target is None
    assert action.point is None


def test_extract_actions_leaves_target_and_point_unset_without_step_state() -> None:
    # Without the state the agent saw there is no DOM to resolve the index against.
    output = _Output("goal", [_Action("click", {"index": 4})])
    [action] = agent_run._extract_actions(output)
    assert action.target is None
    assert action.point is None


def test_extract_actions_dumps_without_unset_params() -> None:
    action = _RecordingAction("click", {"index": 1})
    agent_run._extract_actions(_Output("goal", [action]))
    assert action.dump_kwargs == {"exclude_none": True}


# ---------------------------------------------------------------------------
# _summarize_action_result — one action's outcome as short display text
# ---------------------------------------------------------------------------


class _SparseResult:
    """A Browser-Use action result carrying only the attributes it was given."""

    def __init__(self, **attrs: object) -> None:
        for key, value in attrs.items():
            setattr(self, key, value)


def test_summarize_action_result_shows_the_error_over_any_content() -> None:
    # A failed action's reason is the thing worth reading, whatever it also returned.
    result = _SparseResult(error="element not found", extracted_content="partial page text")
    assert agent_run._summarize_action_result(result) == "element not found"


def test_summarize_action_result_falls_back_to_the_long_term_memory() -> None:
    # An action that stored something but extracted no content still has an outcome.
    result = _SparseResult(
        error=None, extracted_content=None, long_term_memory="Saved 3 rows to memory"
    )
    assert agent_run._summarize_action_result(result) == "Saved 3 rows to memory"


def test_summarize_action_result_is_none_for_a_result_with_no_outcome_fields() -> None:
    """Browser-Use result shapes differ per action; one missing every text field is a silent success, which needs no output row rather than a crashed step."""
    assert agent_run._summarize_action_result(_SparseResult()) is None
    assert agent_run._summarize_action_result(_SparseResult(error=None)) is None


def test_summarize_action_result_collapses_whitespace_to_one_line() -> None:
    # Extracted page text arrives with the page's own wrapping; the row is one line.
    result = _SparseResult(extracted_content="  Total:\n\n   $42  ")
    assert agent_run._summarize_action_result(result) == "Total: $42"


def test_summarize_action_result_keeps_text_at_the_limit_whole() -> None:
    # Exactly at the limit is short enough to show — truncation starts past it.
    at_limit = "c" * agent_run._OUTPUT_MAX_CHARS
    assert agent_run._summarize_action_result(_SparseResult(extracted_content=at_limit)) == at_limit


def test_summarize_action_result_truncates_longer_text_to_the_limit() -> None:
    """Over the limit the row is cut one character short and given an ellipsis, so the whole thing is still exactly the limit and reads as continuing."""
    limit = agent_run._OUTPUT_MAX_CHARS
    long_text = "c" * (limit + 50)
    summary = agent_run._summarize_action_result(_SparseResult(extracted_content=long_text))
    assert summary == "c" * (limit - 1) + "…"
    assert len(summary) == limit

    # A cut landing on a space must not leave the ellipsis floating off the word.
    on_a_space = "a" * (limit - 2) + " " + "b" * 50
    assert (
        agent_run._summarize_action_result(_SparseResult(extracted_content=on_a_space))
        == "a" * (limit - 2) + "…"
    )


# ---------------------------------------------------------------------------
# __init__ — derived timeouts and initial state
# ---------------------------------------------------------------------------


def test_init_derives_timeouts_and_starts_from_a_clean_slate() -> None:
    from app.constants.browser import MAX_HANDOFFS_PER_TASK

    _, emit = _collector()
    runner = BrowserTaskRunner(
        session=_session(),
        llm=object(),
        callbacks=BrowserRunnerCallbacks(
            emit=emit,
            request_handoff=AsyncMock(),
            is_cancelled=AsyncMock(return_value=False),
        ),
        config=BrowserRunConfig(
            max_steps=7,
            max_actions_per_step=3,
            task_timeout_seconds=300,
            step_timeout_seconds=180,
            handoff_timeout_seconds=60,
            stream_screenshots=True,
            solve_captcha=True,
        ),
    )

    # A step that hands off waits on the human on top of its own work budget, and
    # the wall clock allows every permitted handoff to run its full duration.
    assert runner._step_timeout == 240
    assert runner._wall_clock_timeout == 300 + MAX_HANDOFFS_PER_TASK * 60
    assert runner._config.max_steps == 7
    assert runner._config.max_actions_per_step == 3
    assert runner._task_timeout == 300
    assert runner._config.flash_mode is True
    assert runner._agent_run._agent is None
    assert runner._stopped is False
    assert runner._handed_off is False
    assert runner._handoffs == 0
    assert runner._last_step == 0
    assert runner._shots == []
    assert runner._emit_tasks == set()


async def test_an_agent_run_with_no_chat_model_says_so_instead_of_crashing_deep_inside(
    patch_browser,
) -> None:
    """A run built without a chat model refuses loudly rather than handing None to an Agent."""
    from app.services.browser.exceptions import BrowserUnavailableError

    _, emit = _collector()
    runner = _make_runner(emit=emit, overrides=_RunnerOverrides(llm=object()))
    runner._agent_run._llm = None

    with pytest.raises(BrowserUnavailableError, match="chat model"):
        await runner._agent_run.execute("x")


# ---------------------------------------------------------------------------
# run — how the agent and browser are configured
# ---------------------------------------------------------------------------


class _LabelNode:
    """A DOM node that only carries the label sources a test explicitly gives it."""

    def __init__(self, *, text: str = "", node_name: str = "BUTTON", **attrs: Any) -> None:
        self._text = text
        self.node_name = node_name
        # ax_node/attributes are set only when asked for, so a test can prove the
        # code copes with a node shape that lacks them entirely.
        for key, value in attrs.items():
            setattr(self, key, value)

    def get_meaningful_text_for_llm(self) -> str:
        return self._text


def _label_state(node: object, index: int = 3) -> SimpleNamespace:
    return SimpleNamespace(dom_state=SimpleNamespace(selector_map={index: node}))


def test_element_label_prefers_the_accessibility_name() -> None:
    """The a11y name is what a person calls the control, and it is the only label an icon-only button has — it must win over every other source."""
    node = _LabelNode(
        text="",
        ax_node=SimpleNamespace(name="Submit application"),
        attributes={"aria-label": "ignored", "id": "btn-1"},
    )
    assert agent_run._element_label(_label_state(node), 3) == "Submit application"


def test_element_label_falls_back_to_visible_text_on_a_node_with_no_ax_node() -> None:
    # Browser-Use nodes do not all carry ax_node/attributes; a missing one is a
    # fallback, never a lost caption.
    node = _LabelNode(text="  Sign in  ", node_name="A")
    assert agent_run._element_label(_label_state(node), 3) == "Sign in"


def test_element_label_falls_back_to_a_labelling_attribute() -> None:
    node = _LabelNode(text="   ", ax_node=None, attributes={"aria-label": "Close dialog"})
    assert agent_run._element_label(_label_state(node), 3) == "Close dialog"


def test_element_label_falls_back_to_the_lowercased_tag_name() -> None:
    node = _LabelNode(text="", ax_node=None, attributes={})
    assert agent_run._element_label(_label_state(node), 3) == "button"


def test_element_label_is_none_for_an_index_that_is_not_an_int() -> None:
    node = _LabelNode(text="Sign in")
    assert agent_run._element_label(_label_state(node), "3") is None
    assert agent_run._element_label(_label_state(node), None) is None


def test_element_label_is_none_when_the_index_is_not_in_the_selector_map() -> None:
    assert agent_run._element_label(_label_state(_LabelNode(text="Sign in")), 99) is None


class _NamelessNode:
    """A node shape carrying no tag name at all — Browser-Use does not promise one."""

    def __init__(self) -> None:
        self.ax_node = None
        self.attributes: dict[str, str] = {}

    def get_meaningful_text_for_llm(self) -> str:
        return ""


def test_element_label_is_none_and_silent_for_a_node_with_no_tag_name(monkeypatch) -> None:
    """A node with nothing to name it yields no label — and that is an ordinary outcome, not a DOM shape worth warning about."""
    warning = Mock()
    monkeypatch.setattr(runner_mod.log, "warning", warning)
    assert agent_run._element_label(_label_state(_NamelessNode()), 3) is None
    warning.assert_not_called()


def test_element_label_is_none_when_the_tag_name_is_empty() -> None:
    # A blank tag names nothing — "Clicking" beats "Clicking <blank>".
    node = _LabelNode(text="", node_name=None, ax_node=None, attributes={})
    assert agent_run._element_label(_label_state(node), 3) is None


class _ExplodingNode:
    """A node whose text accessor raises — an unrecognised Browser-Use shape."""

    node_name = "BUTTON"

    def get_meaningful_text_for_llm(self) -> str:
        raise ValueError("unexpected node shape")


def test_element_label_warns_with_the_error_type_when_a_node_shape_is_unrecognised(
    monkeypatch,
) -> None:
    """Losing one caption's name must not kill the step, but a systematic DOM shape change has to be visible in the wide event."""
    warning = Mock()
    monkeypatch.setattr(runner_mod.log, "warning", warning)

    assert agent_run._element_label(_label_state(_ExplodingNode()), 3) is None

    warning.assert_called_once_with(
        f"{LogTag.BROWSER} Could not resolve element label from DOM node",
        error_type="ValueError",
    )


def _recorder(calls: list[tuple[int, list]]) -> ActionResultsFn:
    """Record the calls to an awaited sink — publishing a row crosses a process boundary."""

    async def record(step: int, outputs: list) -> None:
        calls.append((step, outputs))

    return record


async def test_on_step_end_reports_outputs_keyed_to_the_step_just_executed() -> None:
    """Key the output to the step _on_step already emitted rows for; a silent success adds no row."""
    calls: list[tuple[int, list]] = []
    runner = _make_runner(
        emit=AsyncMock(),
        overrides=_RunnerOverrides(action_results=_recorder(calls)),
    )
    runner._agent_run._last_step = 4

    agent = SimpleNamespace(
        state=SimpleNamespace(
            last_result=[
                _ActionResult(extracted_content="Total: $42"),
                _ActionResult(),  # silent success — no output row
                _ActionResult(error="element not found"),
            ]
        )
    )
    await runner._agent_run._on_step_end(agent)

    assert len(calls) == 1
    step, outputs = calls[0]
    assert step == 4
    by_position = {o.position: o.output for o in outputs}
    assert by_position == {0: "Total: $42", 2: "element not found"}


async def test_on_step_end_reports_nothing_for_an_agent_with_no_results_yet() -> None:
    """Report nothing instead of failing the run when Browser-Use does not promise state or last_result on a call."""
    calls: list[tuple[int, list]] = []
    runner = _make_runner(
        emit=AsyncMock(),
        overrides=_RunnerOverrides(action_results=_recorder(calls)),
    )

    await runner._agent_run._on_step_end(SimpleNamespace())
    await runner._agent_run._on_step_end(SimpleNamespace(state=SimpleNamespace()))
    await runner._agent_run._on_step_end(SimpleNamespace(state=SimpleNamespace(last_result=None)))

    assert calls == []


async def test_on_step_end_is_a_noop_without_an_action_results_sink() -> None:
    runner = _make_runner(emit=AsyncMock())
    assert runner._action_results is None
    agent = SimpleNamespace(state=SimpleNamespace(last_result=[_ActionResult(error="x")]))
    await runner._agent_run._on_step_end(agent)  # must not raise


def test_the_task_preamble_forbids_inventing_field_values() -> None:
    """A missing value must become a handoff, never a plausible-looking guess."""
    from app.constants.browser import BROWSER_TAKEOVER_PREAMBLE

    assert "NEVER invent a value" in BROWSER_TAKEOVER_PREAMBLE
    # The rule is only safe because it names somewhere for the agent to go.
    assert "request_human_takeover" in BROWSER_TAKEOVER_PREAMBLE


def test_the_task_preamble_routes_dropdowns_through_the_native_actions() -> None:
    from app.constants.browser import BROWSER_TAKEOVER_PREAMBLE

    assert "`dropdown_options`" in BROWSER_TAKEOVER_PREAMBLE
    assert "`select_dropdown`" in BROWSER_TAKEOVER_PREAMBLE


def test_the_tool_docs_say_each_call_is_a_fresh_browser() -> None:
    """Regression: the executor re-ran a whole form fill believing prior values were still on the page."""
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
    assert kwargs["use_vision"] is False
    assert kwargs["flash_mode"] is True
    assert kwargs["max_actions_per_step"] == 5
    assert kwargs["step_timeout"] == runner._step_timeout
    assert kwargs["register_new_step_callback"] == runner._agent_run._on_step
    assert kwargs["register_should_stop_callback"] == runner._should_stop
    assert FakeAgent.last_max_steps == 10
    # Browser-Use's own prompt suggests todo.md; small models then burn a whole
    # step writing one for a 3-step form. The counter-instruction is asserted
    # verbatim so rewording it is a deliberate change, not a silent regression.
    assert kwargs["extend_system_message"] == (
        "Do NOT create or update todo.md (or any planning file) unless the task "
        "genuinely needs more than 10 steps. For short tasks, act on the page "
        "directly from the first step."
    )


async def test_run_mirrors_each_steps_action_results_into_the_thread(patch_browser) -> None:
    """The per-action outcomes only exist after the actions execute, so the runner has to be wired into Browser-Use's post-step hook for any of them to arrive."""
    calls: list[tuple[int, list]] = []
    _, emit = _collector()
    runner = _make_runner(
        emit=emit,
        overrides=_RunnerOverrides(action_results=_recorder(calls)),
    )
    FakeAgent.script = [
        {"goal": "Sign in", "actions": [("click", {"index": 1})], "results": [{"error": "nope"}]}
    ]

    await runner.run("sign in")

    assert [(step, [(o.position, o.output) for o in outs]) for step, outs in calls] == [
        (1, [(0, "nope")])
    ]


async def test_run_builds_the_tools_with_the_runner_takeover_and_captcha_policy(
    patch_browser, monkeypatch
) -> None:
    captured: dict = {}

    def _build(**kwargs):
        captured.update(kwargs)
        return "tools-sentinel"

    monkeypatch.setattr(agent_run, "build_browser_tools", _build)
    _, emit = _collector()
    runner = _make_runner(emit=emit)
    await runner.run("x")

    assert captured["solve_captcha"] is False
    assert captured["handle_takeover"] == runner._agent_run._takeover
    assert FakeAgent.last_kwargs["tools"] == "tools-sentinel"


async def _registered_takeover(monkeypatch, message: str | None) -> tuple[str, JevChatModel]:
    """Run the agent with a Jev model bound, then call the takeover the tools got."""
    captured: dict = {}

    def _build(**kwargs):
        captured.update(kwargs)
        return "tools-sentinel"

    monkeypatch.setattr(agent_run, "build_browser_tools", _build)
    llm = JevChatModel(client=MagicMock(), text_model=MagicMock())
    llm._history.append(
        JevHistoryEntry(action="REQUEST_HUMAN", kind="request_human", text="Log in")
    )
    _, emit = _collector()
    runner = _make_runner(
        emit=emit,
        request_handoff=AsyncMock(
            return_value=HandoffOutcome(status=HandoffStatus.COMPLETED, message=message)
        ),
        overrides=_RunnerOverrides(llm=llm),
    )
    await runner.run("x")

    return await captured["handle_takeover"]("Log in", "credentials"), llm


async def test_the_registered_takeover_puts_the_note_on_the_models_takeover_step(
    patch_browser, monkeypatch
) -> None:
    result, llm = await _registered_takeover(monkeypatch, "just grab the photo")

    assert result == "just grab the photo"
    assert llm._history[-1].note == "just grab the photo"


async def test_the_registered_takeover_without_a_note_tells_the_agent_the_step_is_done(
    patch_browser, monkeypatch
) -> None:
    result, llm = await _registered_takeover(monkeypatch, None)

    assert result == "The user finished that step in the live browser."
    assert llm._history[-1].note is None


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
        llm=object(),
        callbacks=BrowserRunnerCallbacks(
            emit=emit,
            request_handoff=AsyncMock(),
            is_cancelled=AsyncMock(return_value=False),
        ),
        config=BrowserRunConfig(
            max_steps=10,
            max_actions_per_step=5,
            task_timeout_seconds=42,
            step_timeout_seconds=180,
            handoff_timeout_seconds=60,
            stream_screenshots=True,
            solve_captcha=False,
        ),
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


async def test_a_timed_out_handoff_is_reported_even_when_browser_use_swallows_the_cancel(
    patch_browser, monkeypatch
) -> None:
    """Browser-Use catches the cancel inside the registered action, so the run returns normally and only the recorded flag still says the handoff expired."""
    import contextlib

    from app.services.browser.exceptions import BrowserHandoffCancelled

    holder: dict[str, BrowserTaskRunner] = {}

    async def _swallowed(self, max_steps: int, on_step_end=None):
        with contextlib.suppress(BrowserHandoffCancelled):
            await holder["runner"]._handle_takeover("Log in", "credentials")
        return _History()

    monkeypatch.setattr(FakeAgent, "run", _swallowed)
    _, emit = _collector()
    runner = _make_runner(
        emit=emit,
        request_handoff=AsyncMock(return_value=HandoffOutcome(status=HandoffStatus.TIMEOUT)),
    )
    holder["runner"] = runner

    result = await runner.run("x")

    assert result.status == BrowserSessionStatus.FAILED
    assert result.success is False
    assert result.summary == BROWSER_RUN_HANDOFF_TIMED_OUT


@pytest.mark.parametrize(
    ("second", "expected"),
    [
        (
            HandoffStatus.TIMEOUT,
            (BrowserSessionStatus.FAILED, False, BROWSER_RUN_HANDOFF_TIMED_OUT),
        ),
        (
            HandoffStatus.CANCELLED,
            (
                BrowserSessionStatus.COMPLETED,
                True,
                "You completed the sensitive step in the live browser.",
            ),
        ),
    ],
)
async def test_a_handoff_that_times_out_after_one_completed_fails_the_run(
    patch_browser, monkeypatch, second, expected
) -> None:
    """Regression: an expired second handoff reported the run as a success."""
    holder: dict[str, BrowserTaskRunner] = {}

    async def _two_takeovers(self, max_steps: int, on_step_end=None):
        await holder["runner"]._handle_takeover("Log in", "credentials")
        await holder["runner"]._handle_takeover("Pay now", "payment")
        return _History()

    monkeypatch.setattr(FakeAgent, "run", _two_takeovers)
    _, emit = _collector()
    runner = _make_runner(
        emit=emit,
        request_handoff=AsyncMock(
            side_effect=[
                HandoffOutcome(status=HandoffStatus.COMPLETED),
                HandoffOutcome(status=second),
            ]
        ),
    )
    holder["runner"] = runner

    result = await runner.run("x")

    assert (result.status, result.success, result.summary) == expected


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
    result = await _make_runner(emit=emit, overrides=_RunnerOverrides(task_timeout=0.01)).run("x")

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


async def test_a_takeover_hands_the_note_back_verbatim() -> None:
    _, emit = _collector()
    runner = _make_runner(
        emit=emit,
        request_handoff=AsyncMock(
            return_value=HandoffOutcome(
                status=HandoffStatus.COMPLETED, message="  just grab the photo "
            )
        ),
    )

    assert await runner._handle_takeover("Log in", "credentials") == "just grab the photo"


@pytest.mark.parametrize("message", [None, "   "])
async def test_a_takeover_with_no_note_hands_back_none(message: str | None) -> None:
    _, emit = _collector()
    runner = _make_runner(
        emit=emit,
        request_handoff=AsyncMock(
            return_value=HandoffOutcome(status=HandoffStatus.COMPLETED, message=message)
        ),
    )

    assert await runner._handle_takeover("Log in", "credentials") is None


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
    await runner._agent_run._on_step(
        state, _Output("Check out", [_Action("click", {"index": 4})]), 3
    )
    await _drain(runner)

    step = events[-1]
    assert step.kind == BrowserEventKind.STEP
    assert step.index == 3
    assert step.goal == "Clicking"
    assert [(a.name, a.inputs) for a in step.actions] == [("click", {"index": 4})]
    assert step.url == "https://example.com/cart"
    assert step.title == "Your cart"
    assert runner._last_step == 3


async def test_step_goal_falls_back_to_a_caption_from_the_actions(patch_browser) -> None:
    events, emit = _collector()
    runner = _make_runner(emit=emit)
    output = _Output("", [_Action("navigate", {"url": "https://www.example.com/x"})])
    output.thinking = ""
    await runner._agent_run._on_step(_State("https://x"), output, 1)
    await _drain(runner)

    assert events[-1].goal == "Opening example.com"


async def test_a_step_with_no_actions_carries_no_actions(patch_browser) -> None:
    events, emit = _collector()
    runner = _make_runner(emit=emit)
    await runner._agent_run._on_step(_State("https://x"), _Output("Waiting", []), 1)
    await _drain(runner)

    assert events[-1].actions == []


async def test_only_uploaded_screenshots_become_replay_frames(patch_browser, monkeypatch) -> None:
    monkeypatch.setattr(
        runner_mod,
        "publish_step_screenshot",
        AsyncMock(side_effect=["https://cdn.example.com/step_1.png", None]),
    )
    _, emit = _collector()
    runner = _make_runner(emit=emit)
    await runner._agent_run._on_step(_State("https://x"), _Output("a", []), 1)
    await _drain(runner)
    await runner._agent_run._on_step(_State("https://x"), _Output("b", []), 2)
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


def _shot_frame(raw: str | None, index: int = 1) -> StepFrame:
    return StepFrame(
        index=index,
        goal="goal",
        actions=[],
        url="https://x",
        title="Page",
        raw_screenshot=raw,
        since_prev_ms=0,
    )


async def test_no_screenshot_when_streaming_is_off() -> None:
    _, emit = _collector()
    runner = _make_runner(emit=emit, overrides=_RunnerOverrides(stream_screenshots=False))
    assert await runner._render_screenshot(_shot_frame("ZmFrZQ==")) is None


async def test_no_screenshot_when_the_state_has_none() -> None:
    _, emit = _collector()
    runner = _make_runner(emit=emit)
    assert await runner._render_screenshot(_shot_frame(None)) is None
    assert await runner._render_screenshot(_shot_frame("")) is None


async def test_undecodable_screenshot_is_dropped(patch_browser) -> None:
    _, emit = _collector()
    runner = _make_runner(emit=emit)
    assert await runner._render_screenshot(_shot_frame("abc")) is None


async def test_screenshot_is_uploaded_under_the_session_and_step(
    patch_browser, monkeypatch
) -> None:
    upload = AsyncMock(return_value="https://cdn.example.com/browser_steps/s1/step_4.png")
    monkeypatch.setattr(runner_mod, "publish_step_screenshot", upload)
    _, emit = _collector()
    runner = _make_runner(emit=emit)

    url = await runner._render_screenshot(_shot_frame("ZmFrZQ==", 4))

    assert url == "https://cdn.example.com/browser_steps/s1/step_4.png"
    # Keyed by session id (not conversation) so each run is its own replay folder.
    assert upload.await_args.args == (b"fake", "s1", 4)


async def test_screenshot_falls_back_to_an_inline_data_url(patch_browser) -> None:
    _, emit = _collector()
    runner = _make_runner(emit=emit)
    assert (
        await runner._render_screenshot(_shot_frame("ZmFrZQ==")) == "data:image/png;base64,ZmFrZQ=="
    )


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
# _finish_from_outcome — what the agent's history says the run achieved
# ---------------------------------------------------------------------------


class _BrokenHistory(_History):
    def final_result(self):
        raise RuntimeError("history unreadable")


class _HalfReadableHistory(_History):
    """Reads the result and the done flag, then breaks — so the success flag keeps whatever the runner initialised it to."""

    def is_successful(self):
        raise RuntimeError("success flag unreadable")


async def test_unreadable_history_reports_an_honest_failure() -> None:
    """Fall back to a complete, honest FAILED snapshot, every field of it, when a history cannot be read."""
    events, emit = _collector()
    result = await _make_runner(emit=emit)._finish_from_outcome(
        outcome_from_history(_BrokenHistory())
    )

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
    """Judge the run done when is_done succeeded even though is_successful raised, using the final result it did read as the summary."""
    events, emit = _collector()
    result = await _make_runner(emit=emit)._finish_from_outcome(
        outcome_from_history(_HalfReadableHistory(result="Booked seat 14C."))
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
    result = await _make_runner(emit=emit)._finish_from_outcome(
        outcome_from_history(_History(done=True, successful=True, result=None))
    )

    assert result.status == BrowserSessionStatus.COMPLETED
    assert result.success is True
    assert result.summary == "Completed the browser task."


async def test_an_explicitly_unsuccessful_history_fails() -> None:
    _, emit = _collector()
    result = await _make_runner(emit=emit)._finish_from_outcome(
        outcome_from_history(_History(done=True, successful=False, result=None))
    )

    assert result.status == BrowserSessionStatus.FAILED
    assert result.success is False
    assert result.summary == "Could not complete the browser task."


async def test_an_unfinished_history_fails_even_when_not_marked_unsuccessful() -> None:
    _, emit = _collector()
    result = await _make_runner(emit=emit)._finish_from_outcome(
        outcome_from_history(_History(done=False, successful=True, result=None))
    )

    assert result.status == BrowserSessionStatus.FAILED
    assert result.success is False


async def test_an_unknown_success_flag_still_counts_as_done() -> None:
    """Treat only an explicit False as a failure; Browser-Use reports None when it cannot judge."""
    _, emit = _collector()
    result = await _make_runner(emit=emit)._finish_from_outcome(
        outcome_from_history(_History(done=True, successful=None, result="Booked."))
    )

    assert result.status == BrowserSessionStatus.COMPLETED
    assert result.success is True
    assert result.summary == "Booked."


async def test_the_agents_final_result_becomes_the_summary() -> None:
    _, emit = _collector()
    result = await _make_runner(emit=emit)._finish_from_outcome(
        outcome_from_history(
            _History(done=True, successful=True, result="The cheapest flight is 42 pounds.")
        )
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
    await _make_runner(emit=emit)._record_usage(outcome_from_history(_History(usage=None)).usage)

    assert record.await_count == 0


async def test_each_models_tokens_are_charged_to_the_users_budget(monkeypatch) -> None:
    record = AsyncMock()
    monkeypatch.setattr(runner_mod, "record_llm_call", record)
    _, emit = _collector()
    runner = _make_runner(
        emit=emit, overrides=_RunnerOverrides(user_id="u1", root_request_id="req-1")
    )

    await runner._record_usage(
        outcome_from_history(
            _History(
                usage=_Usage({"gemini-flash": _Stats(1200, 34), "claude-sonnet": _Stats(90, 7)})
            )
        ).usage
    )

    by_model = {call.kwargs["model_name"]: call.kwargs for call in record.await_args_list}
    assert by_model["gemini-flash"] == {
        "user_id": "u1",
        "model_name": "gemini-flash",
        "usage": TokenUsage(
            input_tokens=1200, output_tokens=34, cached_tokens=0, reasoning_tokens=0
        ),
        "root_request_id": "req-1",
        "context": LLMCallContext(
            agent_name="browser_task", background=False, charge_to_budget=True
        ),
    }
    assert by_model["claude-sonnet"]["usage"]["input_tokens"] == 90
    assert by_model["claude-sonnet"]["usage"]["output_tokens"] == 7
    assert by_model["claude-sonnet"]["context"].charge_to_budget is True


async def test_a_completed_run_charges_its_llm_usage(patch_browser, monkeypatch) -> None:
    record = AsyncMock()
    monkeypatch.setattr(runner_mod, "record_llm_call", record)
    FakeAgent.history = _History(usage=_Usage({"gemini-flash": _Stats(10, 2)}))
    _, emit = _collector()
    await _make_runner(emit=emit, overrides=_RunnerOverrides(user_id="u1")).run("x")

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


async def test_a_jev_model_is_bound_to_the_session_and_its_helper_extracts(patch_browser) -> None:
    """Jev reads the observation off the session Browser-Use drives, gets the raw task (not the takeover preamble), and its text helper is what Browser-Use meters and extracts with."""
    from app.services.browser.jev import JevChatModel

    helper = object()
    jev = MagicMock(spec=JevChatModel)
    jev.text_model = helper
    _, emit = _collector()

    await _make_runner(emit=emit, overrides=_RunnerOverrides(llm=jev)).run("Book it")

    jev.bind.assert_called_once_with(FakeAgent.last_kwargs["browser"], "Book it")
    assert FakeAgent.last_kwargs["llm"] is jev
    assert FakeAgent.last_kwargs["page_extraction_llm"] is helper
    assert set(FakeAgent.last_kwargs) == AGENT_KWARG_KEYS | {"page_extraction_llm"}


async def test_run_gives_the_agent_the_llm_it_was_constructed_with(patch_browser) -> None:
    sentinel = object()
    _, emit = _collector()
    await _make_runner(emit=emit, overrides=_RunnerOverrides(llm=sentinel)).run("x")

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


class _GoalOutput:
    """A step output whose goal fields are set independently, unlike _Output."""

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


async def test_a_step_with_no_thinking_attribute_captions_from_its_actions(patch_browser) -> None:
    events, emit = _collector()
    runner = _make_runner(emit=emit)
    output = _ThinklessOutput([_Action("navigate", {"url": "https://www.example.com/x"})])
    await runner._agent_run._on_step(_State("https://x"), output, 1)
    await _drain(runner)

    assert events[-1].goal == "Opening example.com"


class _GoallessOutput:
    """A step output Browser-Use gave no next_goal attribute at all."""

    def __init__(self, actions: list[_Action]):
        self.thinking = "Deciding what to click"
        self.action = actions


async def test_a_step_output_with_no_goal_attribute_still_captions_its_actions(
    patch_browser,
) -> None:
    # Browser-Use's output shape varies by mode; a missing field is never a failed step.
    events, emit = _collector()
    runner = _make_runner(emit=emit)
    await runner._agent_run._on_step(
        _State("https://x"), _GoallessOutput([_Action("navigate", {"url": "https://x.dev/a"})]), 1
    )
    await _drain(runner)

    assert events[-1].goal == "Opening x.dev"


async def test_a_step_names_and_locates_the_element_its_actions_target(patch_browser) -> None:
    """The step card resolves the agent's element index against the state the agent saw, so the row reads as the control's own name and the UI can pulse over it."""
    events, emit = _collector()
    runner = _make_runner(emit=emit)
    state = _targeted_state(4)
    state.url, state.title, state.screenshot = "https://x", "Page", None

    from app.services.browser.jev.chat_model import JevChatModel
    from app.services.browser.jev.viewport import ViewportBox

    model = object.__new__(JevChatModel)
    model._viewport = {4: ViewportBox(on_screen=True, cx=0.25, cy=0.5)}
    runner._agent_run._llm = model

    await runner._agent_run._on_step(state, _Output("Sign in", [_Action("click", {"index": 4})]), 1)
    await _drain(runner)

    [action] = events[-1].actions
    assert action.target == "Sign in"
    assert action.point == (0.25, 0.5)


async def test_a_state_without_url_title_or_screenshot_still_emits_a_step(patch_browser) -> None:
    events, emit = _collector()
    runner = _make_runner(emit=emit)
    await runner._agent_run._on_step(_BareState(), _Output("Waiting", []), 1)
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
    monkeypatch.setattr(run_contract, "perf_counter", Mock(side_effect=[100.0, 102.5]))

    output = _Output("Check out", [_Action("click", {"index": 4})])
    state = _State("https://example.com/cart")
    await runner._agent_run._on_step(state, output, 1)
    await _drain(runner)
    await runner._agent_run._on_step(state, output, 2)
    await _drain(runner)

    # The first step has no predecessor to measure against; the second reports 2.5s.
    assert emit_step.await_args_list == [
        call(
            StepFrame(
                index=1,
                goal="Clicking",
                actions=[BrowserAction(name="click", inputs={"index": 4})],
                url="https://example.com/cart",
                title="Page",
                raw_screenshot="ZmFrZQ==",
                since_prev_ms=0,
            )
        ),
        call(
            StepFrame(
                index=2,
                goal="Clicking",
                actions=[BrowserAction(name="click", inputs={"index": 4})],
                url="https://example.com/cart",
                title="Page",
                raw_screenshot="ZmFrZQ==",
                since_prev_ms=2500,
            )
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
    await runner._agent_run._on_step(_State("https://x"), _Output("a", []), 1)
    await _drain(runner)

    assert spawned == [{"name": "browser_step_emit"}]


async def test_a_finished_step_emit_releases_its_slot(patch_browser) -> None:
    _, emit = _collector()
    runner = _make_runner(emit=emit)
    await runner._agent_run._on_step(_State("https://x"), _Output("a", []), 1)
    await _drain(runner)
    await asyncio.sleep(0)

    # The done-callback discards the task, so the flush set never grows unbounded.
    assert runner._emit_tasks == set()


async def test_the_step_frame_is_uploaded_under_that_steps_index(
    patch_browser, monkeypatch
) -> None:
    upload = AsyncMock(return_value="https://cdn.example.com/step_7.png")
    monkeypatch.setattr(runner_mod, "publish_step_screenshot", upload)
    _, emit = _collector()
    runner = _make_runner(emit=emit)

    await runner._emit_step(
        StepFrame(
            index=7,
            goal="goal",
            actions=[BrowserAction(name="click")],
            url="https://x",
            title="Page",
            raw_screenshot="ZmFrZQ==",
            since_prev_ms=12,
        )
    )

    assert upload.await_args.args == (b"fake", "s1", 7)


async def test_a_step_card_carries_the_time_the_previous_step_took(patch_browser) -> None:
    """The card shows how long the step took; the very first step has no predecessor to measure, and reports no duration rather than a bogus zero."""
    events, emit = _collector()
    runner = _make_runner(emit=emit)

    def _frame(since_prev_ms: int) -> object:
        return StepFrame(
            index=1,
            goal="goal",
            actions=[],
            url="https://x",
            title="Page",
            raw_screenshot=None,
            since_prev_ms=since_prev_ms,
        )

    await runner._emit_step(_frame(2500))
    assert events[-1].elapsed_ms == 2500

    await runner._emit_step(_frame(0))
    assert events[-1].elapsed_ms is None


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
        StepFrame(
            index=7,
            goal="goal",
            actions=[BrowserAction(name="click")],
            url="https://x",
            title="Page",
            raw_screenshot="ZmFrZQ==",
            since_prev_ms=12,
        )
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
    monkeypatch.setattr(agent_run, "log", logger)
    _, emit = _collector()

    await _make_runner(emit=emit)._finish_from_outcome(outcome_from_history(_BrokenHistory()))

    logger.warning.assert_called_once_with(
        f"{LogTag.BROWSER} Could not read browser history result",
        error_type="RuntimeError",
    )


async def test_the_step_caption_describes_the_step_not_the_models_label(patch_browser) -> None:
    """JevChatModel fills next_goal with its raw decision label ("CLICK [6] Log In")."""
    events, emit = _collector()
    runner = _make_runner(emit=emit)
    state = _targeted_state(4)
    state.url, state.title, state.screenshot = "https://x", "Page", None
    output = _GoalOutput(
        next_goal="CLICK [4] Sign in",
        thinking="CLICK [4] Sign in",
        actions=[_Action("click", {"index": 4})],
    )

    await runner._agent_run._on_step(state, output, 1)
    await _drain(runner)

    assert events[-1].goal == 'Clicking "Sign in"'


async def test_a_blocked_finish_reads_as_a_sentence(patch_browser) -> None:
    events, emit = _collector()
    runner = _make_runner(emit=emit)
    output = _GoalOutput(
        next_goal="BLOCKED",
        thinking="BLOCKED",
        actions=[_Action("done", {"text": "", "success": False})],
    )

    await runner._agent_run._on_step(_State("https://x"), output, 1)
    await _drain(runner)

    assert events[-1].goal == "Could not find a way forward on this page"
