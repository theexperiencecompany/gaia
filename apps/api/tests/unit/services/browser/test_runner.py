"""Tests for BrowserTaskRunner: progress, the agent-driven handoff, cancel, timeout.

Browser-Use is faked so the tests exercise the runner's orchestration without a
real browser: a scripted FakeAgent invokes the runner's step callback exactly as
Browser-Use does (after the model picks actions, before they execute). The runner
no longer judges sensitivity itself; the agent hands off for itself by calling
_handle_takeover (the request_human_takeover and solve_captcha_with_help
actions), which is what the takeover tests below exercise directly.
"""

import asyncio
from dataclasses import dataclass, replace
from types import SimpleNamespace
from typing import Any, ClassVar
from unittest.mock import ANY, AsyncMock, MagicMock, Mock

import browser_use
import httpx
import pytest

from app.constants.browser import (
    BROWSER_ENGINE_FALLBACK_NOTE,
    BROWSER_ENGINE_FALLBACK_WITHOUT_STATE_NOTE,
    BROWSER_RUN_HANDOFF_TIMED_OUT,
    HANDOFF_AUTORESOLVED_NOTE,
    BrowserEventKind,
    BrowserSessionStatus,
    HandoffStatus,
    StateCarry,
)
from app.constants.log_tags import LogTag
from app.schemas.browser import BrowserSessionSnapshot, HandoffOutcome, HandoffRequest
from app.services.browser import (
    agent_run,
    host_client,
    runner as runner_mod,
    session as session_mod,
)
from app.services.browser.agent_run import outcome_from_history
from app.services.browser.jev.chat_model import JevChatModel
from app.services.browser.jev.policy import JevHistoryEntry
from app.services.browser.run_contract import (
    ActionResultsFn,
    BrowserRunConfig,
    RunOutcome,
    RunUsage,
    StepFrame,
)
from app.services.browser.runner import BrowserRunnerCallbacks, BrowserTaskRunner
from app.services.browser.session import BrowserHostSession
from app.services.llm_metering import LLMCallContext, TokenUsage
from shared.py.wide_events import log, log_context


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
        host_url="http://browser-host:8930",
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
    start_url: str | None = None


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
            start_url=overrides.start_url,
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
    # A step that already emitted frame 4, so its outputs key to that frame.
    runner._agent_run._last_step = 4
    runner._agent_run._framed = True

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

    # The handoff also gets the session the run is on, so it pauses that browser.
    assert handoff.await_args.args == (
        HandoffRequest(
            category=SensitiveCategory.CREDENTIALS,
            reason="Enter your password and click Login",
        ),
        runner.session,
    )


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


def _runner_answering_a_takeover_with(message: str) -> BrowserTaskRunner:
    _, emit = _collector()
    return _make_runner(
        emit=emit,
        request_handoff=AsyncMock(
            return_value=HandoffOutcome(status=HandoffStatus.COMPLETED, message=message)
        ),
    )


async def test_the_note_the_user_left_rides_on_the_result() -> None:
    """Regression: the reply confirmed the original "upvote it" after the user cancelled the upvote."""
    runner = _runner_answering_a_takeover_with("skip the upvote, just tell me the title")
    await runner._handle_takeover("Log in", "credentials")

    result = await runner._finish(BrowserSessionStatus.COMPLETED, True, "The top post is X.")

    assert result.user_notes == ["skip the upvote, just tell me the title"]


async def test_the_auto_resolvers_own_resume_note_is_not_a_user_instruction() -> None:
    runner = _runner_answering_a_takeover_with(HANDOFF_AUTORESOLVED_NOTE)
    await runner._handle_takeover("Log in", "credentials")

    result = await runner._finish(BrowserSessionStatus.COMPLETED, True, "Signed in.")

    assert result.user_notes == []


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
    # The first frame of the run, whatever Browser-Use's own counter reads.
    assert step.index == 1
    assert step.goal == "Clicking"
    assert [(a.name, a.inputs) for a in step.actions] == [("click", {"index": 4})]
    assert step.url == "https://example.com/cart"
    assert step.title == "Your cart"
    assert runner._last_step == 1


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


# ---------------------------------------------------------------------------
# _render_screenshot
# ---------------------------------------------------------------------------


def _shot_frame(raw: str | None, index: int = 1, session_id: str = "s1") -> StepFrame:
    return StepFrame(
        index=index,
        session_id=session_id,
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


async def test_a_step_captured_before_a_switch_is_uploaded_under_the_session_it_was_on(
    patch_browser, monkeypatch
) -> None:
    """Regression: the deferred upload read the runner's session, the fallback's once the run moved."""
    upload = AsyncMock(return_value=None)
    monkeypatch.setattr(runner_mod, "publish_step_screenshot", upload)
    _, emit = _collector()
    runner = _make_runner(emit=emit)
    runner._session = _fallback_session()

    await runner._render_screenshot(_shot_frame("ZmFrZQ==", 3, session_id="s1"))

    assert upload.await_args.args == (b"fake", "s1", 3)


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
        "user_notes": [],
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
        "user_notes": [],
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
        "provider_cost": None,
        "context": LLMCallContext(
            agent_name="browser_task", background=False, charge_to_budget=True
        ),
    }
    assert by_model["claude-sonnet"]["usage"]["input_tokens"] == 90
    assert by_model["claude-sonnet"]["usage"]["output_tokens"] == 7
    assert by_model["claude-sonnet"]["context"].charge_to_budget is True


async def test_gateway_reported_cost_wins_over_the_table(monkeypatch) -> None:
    """A Jev run whose gateway reported per-decision cost is metered at that actual number."""
    from app.services.browser.jev.chat_model import JevChatModel

    record = AsyncMock()
    monkeypatch.setattr(runner_mod, "record_llm_call", record)
    _, emit = _collector()
    llm = JevChatModel(client=MagicMock(), text_model=MagicMock())
    llm._gateway_cost_usd = 0.0
    runner = _make_runner(
        emit=emit,
        overrides=_RunnerOverrides(user_id="u1", root_request_id="req-1", llm=llm),
    )
    llm.model = "jev-test"

    await runner._record_usage(
        outcome_from_history(_History(usage=_Usage({"jev-test": _Stats(100, 5)}))).usage
    )

    (call,) = record.await_args_list
    assert call.kwargs["model_name"] == "jev-test"
    assert call.kwargs["provider_cost"] == 0.0


async def test_missing_gateway_cost_falls_back_to_the_table(monkeypatch) -> None:
    """A Jev run with a cost-blind decision prices from the catalog instead."""
    from app.services.browser.jev.chat_model import JevChatModel

    record = AsyncMock()
    monkeypatch.setattr(runner_mod, "record_llm_call", record)
    _, emit = _collector()
    llm = JevChatModel(client=MagicMock(), text_model=MagicMock())
    llm._gateway_cost_usd = None
    runner = _make_runner(
        emit=emit,
        overrides=_RunnerOverrides(user_id="u1", root_request_id="req-1", llm=llm),
    )
    llm.model = "jev-test"

    await runner._record_usage(
        outcome_from_history(_History(usage=_Usage({"jev-test": _Stats(100, 5)}))).usage
    )

    (call,) = record.await_args_list
    assert call.kwargs["provider_cost"] is None


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
    "use_judge",
    "llm_timeout",
    "max_failures",
}


async def test_browser_uses_own_judge_is_off(patch_browser) -> None:
    """Nothing reads its verdict, it bills a whole extra call, and it judged a cancelled instruction as a failed run."""
    _, emit = _collector()
    await _make_runner(emit=emit).run("x")

    assert FakeAgent.last_kwargs["use_judge"] is False


async def test_the_start_url_is_opened_before_the_first_decision(patch_browser) -> None:
    """Browser-Use finds a start URL in the task only when it holds one; the books task named three and began on about:blank."""
    _, emit = _collector()
    start = "https://books.toscrape.com/"
    task = f"Open {start}, go to {start}catalogue/category/books/travel_2/index.html\n\nStart at: {start}"

    await _make_runner(emit=emit, overrides=_RunnerOverrides(start_url=start)).run(task)

    assert FakeAgent.last_kwargs["initial_actions"] == [
        {"navigate": {"url": start, "new_tab": False}}
    ]


async def test_a_run_with_no_start_url_adds_no_first_action(patch_browser) -> None:
    _, emit = _collector()

    await _make_runner(emit=emit).run("x")

    assert "initial_actions" not in FakeAgent.last_kwargs


async def test_a_jev_model_is_bound_to_the_session_and_its_helper_extracts(patch_browser) -> None:
    """Jev reads the observation off the session Browser-Use drives, gets the raw task (not the takeover preamble), and its text helper is what Browser-Use meters and extracts with."""
    from app.services.browser.jev import JevChatModel

    helper = object()
    jev = MagicMock(spec=JevChatModel)
    jev.text_model = helper
    _, emit = _collector()

    await _make_runner(emit=emit, overrides=_RunnerOverrides(llm=jev)).run("Book it")

    jev.bind.assert_called_once_with(FakeAgent.last_kwargs["browser"], "Book it", ANY)
    assert FakeAgent.last_kwargs["llm"] is jev
    assert FakeAgent.last_kwargs["page_extraction_llm"] is helper
    assert set(FakeAgent.last_kwargs) == AGENT_KWARG_KEYS | {"page_extraction_llm"}


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
        error="LLM provider exploded",
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

    model = JevChatModel(client=MagicMock(), text_model=MagicMock())
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


async def test_a_finished_step_emit_releases_its_slot(patch_browser) -> None:
    _, emit = _collector()
    runner = _make_runner(emit=emit)
    await runner._agent_run._on_step(_State("https://x"), _Output("a", []), 1)
    await _drain(runner)
    await asyncio.sleep(0)

    # The done-callback discards the task, so the flush set never grows unbounded.
    assert runner._emit_tasks == set()


async def test_a_step_card_carries_the_time_the_previous_step_took(patch_browser) -> None:
    """The card shows how long the step took; the very first step has no predecessor to measure, and reports no duration rather than a bogus zero."""
    events, emit = _collector()
    runner = _make_runner(emit=emit)

    def _frame(since_prev_ms: int) -> object:
        return StepFrame(
            index=1,
            session_id="s1",
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


async def test_a_step_that_shows_nothing_for_a_while_gets_one_line_saying_so(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The Berlin article rendered cleanly for 40 to 71 s with no error left to caption."""
    from app.constants.browser import BROWSER_STALL_NOTE
    from app.services.browser import runner as runner_mod

    monkeypatch.setattr(runner_mod, "BROWSER_STALL_NOTE_AFTER_SECONDS", 0.05)
    monkeypatch.setattr(runner_mod, "_STALL_POLL_SECONDS", 0.01)
    note = AsyncMock()
    runner = _make_runner(emit=AsyncMock())
    runner._note = note

    async def slow_run(task: str) -> RunOutcome:
        await asyncio.sleep(0.3)
        return RunOutcome(success=True, summary="done")

    runner._agent_run = SimpleNamespace(execute=slow_run, stop=lambda: None)
    await runner.run("read the page")

    note.assert_awaited_once_with(BROWSER_STALL_NOTE)


async def test_waiting_on_the_user_is_not_a_stall(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.services.browser import runner as runner_mod

    monkeypatch.setattr(runner_mod, "BROWSER_STALL_NOTE_AFTER_SECONDS", 0.05)
    monkeypatch.setattr(runner_mod, "_STALL_POLL_SECONDS", 0.01)
    note = AsyncMock()

    async def a_slow_human(request: HandoffRequest, session: BrowserHostSession) -> HandoffOutcome:
        await asyncio.sleep(0.3)
        return HandoffOutcome(status=HandoffStatus.COMPLETED)

    runner = _make_runner(emit=AsyncMock(), request_handoff=a_slow_human)
    runner._note = note

    async def run_that_hands_off(task: str) -> RunOutcome:
        await runner._handle_takeover("sign in", "credentials")
        return RunOutcome(success=True, summary="done")

    runner._agent_run = SimpleNamespace(execute=run_that_hands_off, stop=lambda: None)
    await runner.run("sign in and read")

    note.assert_not_awaited()


# ---------------------------------------------------------------------------
# Engine fallback: a page the primary engine could not pass is retried once
# ---------------------------------------------------------------------------

_BLOCKED_URL = "https://flights.example.com/results"


def _fallback_session() -> BrowserHostSession:
    return BrowserHostSession(
        session_id="s-fallback",
        cdp_url="ws://fallback",  # NOSONAR
        live_view_url="http://v-fallback",  # NOSONAR
        context_id="ctx-2",
        host_url="http://fallback-host:8930",
    )


class _AgentRunThatBlocksOnce:
    """Stands in for BrowserAgentRun: the first run gives up on a page and asks for the fallback."""

    runs: ClassVar[list[tuple[BrowserHostSession, bool]]] = []

    def __init__(self, *, session, llm, config, hooks, step_timeout, steps_before) -> None:
        self._session = session
        self._llm = llm

    async def execute(self, task: str) -> RunOutcome:
        type(self).runs.append((self._session, self._llm.fallback_available))
        if len(type(self).runs) == 1:
            self._llm.fallback_url = _BLOCKED_URL
            return RunOutcome(success=False, summary="blocked on the primary")
        return RunOutcome(success=True, summary="fares found on the fallback")

    def stop(self) -> None:
        return None


def _fallback_callbacks(
    emit,
    open_fallback_session,
    *,
    is_cancelled: AsyncMock | None = None,
    request_handoff: AsyncMock | None = None,
    note: AsyncMock | None = None,
) -> BrowserRunnerCallbacks:
    return BrowserRunnerCallbacks(
        emit=emit,
        request_handoff=request_handoff or AsyncMock(),
        is_cancelled=is_cancelled or AsyncMock(return_value=False),
        note=note,
        open_fallback_session=open_fallback_session,
    )


def _fallback_config(*, task_timeout: float = 30, start_url: str | None = None) -> BrowserRunConfig:
    return BrowserRunConfig(
        max_steps=10,
        max_actions_per_step=5,
        task_timeout_seconds=task_timeout,
        step_timeout_seconds=180,
        handoff_timeout_seconds=0,
        stream_screenshots=False,
        solve_captcha=False,
        start_url=start_url,
    )


def _fallback_runner(
    monkeypatch,
    callbacks: BrowserRunnerCallbacks,
    *,
    agent_run: type = _AgentRunThatBlocksOnce,
    config: BrowserRunConfig | None = None,
) -> BrowserTaskRunner:
    _AgentRunThatBlocksOnce.runs = []
    monkeypatch.setattr(runner_mod, "BrowserAgentRun", agent_run)
    return BrowserTaskRunner(
        session=_session(),
        llm=JevChatModel(client=MagicMock(), text_model=MagicMock()),
        callbacks=callbacks,
        config=config if config is not None else _fallback_config(),
    )


async def test_a_run_blocked_on_the_primary_engine_finishes_on_the_fallback(monkeypatch) -> None:
    events, emit = _collector()
    _host_answers(monkeypatch, _host_holding(_SIGNED_IN_STATE, []))
    fallback = _fallback_session()
    open_fallback = AsyncMock(return_value=fallback)
    runner = _fallback_runner(monkeypatch, _fallback_callbacks(emit, open_fallback))

    result = await runner.run("find fares")

    open_fallback.assert_awaited_once_with(_BLOCKED_URL, ANY)
    # The user's card moves to the browser the run is now on.
    running = [e for e in events if isinstance(e, BrowserSessionSnapshot)]
    assert [(e.session_id, e.live_view_url) for e in running] == [
        ("s1", "http://v"),
        ("s-fallback", "http://v-fallback"),
    ]
    # The second run is on the fallback session, and may not ask for a fallback again.
    assert [(s.session_id, available) for s, available in _AgentRunThatBlocksOnce.runs] == [
        ("s1", True),
        ("s-fallback", False),
    ]
    assert runner.used_fallback is True
    assert runner.session is fallback
    assert (result.status, result.success, result.summary) == (
        BrowserSessionStatus.COMPLETED,
        True,
        "fares found on the fallback",
    )


async def test_a_run_blocked_with_no_fallback_engine_ends_on_its_first_outcome(
    monkeypatch,
) -> None:
    events, emit = _collector()
    runner = _fallback_runner(monkeypatch, _fallback_callbacks(emit, None))

    result = await runner.run("find fares")

    assert [(s.session_id, available) for s, available in _AgentRunThatBlocksOnce.runs] == [
        ("s1", False)
    ]
    assert runner.used_fallback is False
    assert runner.session.session_id == "s1"
    assert (result.status, result.success, result.summary) == (
        BrowserSessionStatus.FAILED,
        False,
        "blocked on the primary",
    )


class _AgentRunRecordingStart(_AgentRunThatBlocksOnce):
    """The blocking stand-in, recording the start URL each run was built to open."""

    starts: ClassVar[list[str | None]] = []

    def __init__(self, *, config: BrowserRunConfig, **kwargs: Any) -> None:
        super().__init__(config=config, **kwargs)
        type(self).starts.append(config.start_url)


async def test_a_run_resumed_on_the_fallback_at_its_page_does_not_reopen_the_start_url(
    monkeypatch,
) -> None:
    """Jev reopens the page it gave up on; opening the start URL first as well navigated twice."""
    _, emit = _collector()
    _host_answers(monkeypatch, _host_holding(_SIGNED_IN_STATE, []))
    _AgentRunRecordingStart.starts = []
    runner = _fallback_runner(
        monkeypatch,
        _fallback_callbacks(emit, AsyncMock(return_value=_fallback_session())),
        agent_run=_AgentRunRecordingStart,
        config=_fallback_config(start_url="https://flights.example.com/"),
    )

    await runner.run("find fares")

    assert _AgentRunRecordingStart.starts == ["https://flights.example.com/", None]


#: What the primary's browser holds after the user signed in on it: the site's
#: session cookie and the token its app keeps in localStorage.
_SIGNED_IN_STATE = {
    "cookies": [
        {
            "name": "session",
            "value": "signed-in",
            "domain": "flights.example.com",
            "path": "/",
            "expires": -1,
            "httpOnly": True,
            "secure": True,
            "sameSite": "Lax",
        }
    ],
    "origins": [
        {
            "origin": "https://flights.example.com",
            "localStorage": [{"name": "token", "value": "abc"}],
        }
    ],
}


def _host_holding(state: dict[str, Any], reads: list[str]):
    """Answer as a host whose live session holds state, recording each storage read."""

    def respond(request: httpx.Request) -> httpx.Response:
        reads.append(request.url.path)
        return httpx.Response(200, json={"storage_state": state})

    return respond


async def test_a_login_made_on_the_primary_engine_moves_with_the_run_to_the_fallback(
    monkeypatch,
) -> None:
    """A user signed in on Obscura, the next page blocked it, and the Chromium fallback opened signed out: only saved logins seeded it."""
    _, emit = _collector()
    reads: list[str] = []
    _host_answers(monkeypatch, _host_holding(_SIGNED_IN_STATE, reads))
    open_fallback = AsyncMock(return_value=_fallback_session())
    runner = _fallback_runner(monkeypatch, _fallback_callbacks(emit, open_fallback))
    primary = runner.session

    async with log_context("run_browser_job"):
        await runner.run("find fares")
        event = dict(log.get())

    assert reads == ["/sessions/s1/storage-state"]
    open_fallback.assert_awaited_once_with(
        _BLOCKED_URL,
        session_mod.LiveSessionState(storage_state=_SIGNED_IN_STATE, source=primary),
    )
    assert event["browser"]["state_carry"] == StateCarry.CARRIED


async def test_a_primary_whose_state_cannot_be_read_moves_without_it_and_says_so(
    monkeypatch,
) -> None:
    """The unreadable primary was swallowed into None: the run moved on signed out and nothing recorded why."""
    _, emit = _collector()
    _host_answers(monkeypatch, _session_gone)
    open_fallback = AsyncMock(return_value=_fallback_session())
    note = AsyncMock()
    runner = _fallback_runner(monkeypatch, _fallback_callbacks(emit, open_fallback, note=note))

    async with log_context("run_browser_job"):
        await runner.run("find fares")
        event = dict(log.get())

    open_fallback.assert_awaited_once_with(_BLOCKED_URL, None)
    assert event["browser"]["state_carry"] == StateCarry.UNREADABLE
    note.assert_awaited_once_with(BROWSER_ENGINE_FALLBACK_WITHOUT_STATE_NOTE)


# ---------------------------------------------------------------------------
# Engine failure: the primary engine crashed, dropped or wedged under the run
# ---------------------------------------------------------------------------

_LAST_PAGE = "https://news.example.com/item?id=1"
#: What Browser-Use's run returns once the engine stopped answering: its loop
#: ends on consecutive failures and nothing is raised.
_ENGINE_GAVE_OUT = RunOutcome(success=False, summary="Could not complete the browser task.")


def _host_answers(monkeypatch, respond) -> None:
    """Stand in for the browser host's HTTP API, answering every call with respond."""
    real_client = httpx.AsyncClient
    monkeypatch.setattr(
        host_client.httpx,
        "AsyncClient",
        lambda **kwargs: real_client(transport=httpx.MockTransport(respond), **kwargs),
    )


def _session_gone(request: httpx.Request) -> httpx.Response:
    return httpx.Response(404, json={"detail": "session not found"})


def _session_dead(request: httpx.Request) -> httpx.Response:
    return httpx.Response(200, json={"session_id": "s1", "live": False, "last_activity_at": 0})


def _engine_wedged(request: httpx.Request) -> httpx.Response:
    raise httpx.ReadTimeout("the host did not answer", request=request)


def _session_live(request: httpx.Request) -> httpx.Response:
    return httpx.Response(200, json={"session_id": "s1", "live": True, "last_activity_at": 0})


class _AgentRunOnFailingEngine:
    """Stands in for BrowserAgentRun: each run plays the next scripted ending, an outcome or a raise."""

    endings: ClassVar[list[RunOutcome | Exception]] = []
    runs: ClassVar[list[tuple[str, bool]]] = []
    #: The page the run had read when its engine gave out; None when it never read one.
    last_page: ClassVar[str | None] = _LAST_PAGE

    def __init__(self, *, session, llm, config, hooks, step_timeout, steps_before) -> None:
        self._session = session
        self._llm = llm
        self._hooks = hooks

    async def execute(self, task: str) -> RunOutcome:
        cls = type(self)
        cls.runs.append((self._session.session_id, self._llm.fallback_available))
        if cls.last_page is not None:
            # What Jev's observation records for the page it read last.
            self._llm._observation = SimpleNamespace(url=cls.last_page)
        ending = cls.endings.pop(0)
        if isinstance(ending, Exception):
            raise ending
        return ending

    def stop(self) -> None:
        return None


def _failing_engine(*endings: RunOutcome | Exception, last_page: str | None = _LAST_PAGE):
    _AgentRunOnFailingEngine.endings = list(endings)
    _AgentRunOnFailingEngine.runs = []
    _AgentRunOnFailingEngine.last_page = last_page
    return _AgentRunOnFailingEngine


@pytest.mark.parametrize("host", [_session_gone, _session_dead, _engine_wedged])
async def test_a_run_whose_engine_failed_finishes_on_the_fallback_from_the_page_it_was_on(
    monkeypatch, host
) -> None:
    events, emit = _collector()
    _host_answers(monkeypatch, host)
    open_fallback = AsyncMock(return_value=_fallback_session())
    agent = _failing_engine(_ENGINE_GAVE_OUT, RunOutcome(success=True, summary="67 comments"))
    runner = _fallback_runner(
        monkeypatch, _fallback_callbacks(emit, open_fallback), agent_run=agent
    )

    result = await runner.run("count the comments")

    # A dead engine has no state to give: the fallback opens on saved logins.
    open_fallback.assert_awaited_once_with(_LAST_PAGE, None)
    assert agent.runs == [("s1", True), ("s-fallback", False)]
    running = [e.session_id for e in events if isinstance(e, BrowserSessionSnapshot)]
    assert running == ["s1", "s-fallback"]
    assert runner.used_fallback is True
    assert (result.status, result.success, result.summary) == (
        BrowserSessionStatus.COMPLETED,
        True,
        "67 comments",
    )


async def test_an_engine_that_died_before_the_agent_attached_starts_the_task_over_on_the_fallback(
    monkeypatch,
) -> None:
    _, emit = _collector()
    _host_answers(monkeypatch, _session_gone)
    open_fallback = AsyncMock(return_value=_fallback_session())
    agent = _failing_engine(
        RuntimeError("Failed to establish CDP connection to browser: HTTP 403"),
        RunOutcome(success=True, summary="67 comments"),
        last_page=None,
    )
    runner = _fallback_runner(
        monkeypatch, _fallback_callbacks(emit, open_fallback), agent_run=agent
    )

    result = await runner.run("count the comments")

    open_fallback.assert_awaited_once_with(None, None)
    assert (result.status, result.summary) == (BrowserSessionStatus.COMPLETED, "67 comments")


@pytest.mark.parametrize(
    ("ending", "summary"),
    [
        # A site that never loaded, or a model that gave out, on a healthy engine.
        (_ENGINE_GAVE_OUT, "Could not complete the browser task."),
        (RuntimeError("LLM provider exploded"), "Browser task failed: LLM provider exploded"),
    ],
)
async def test_a_run_that_failed_on_a_live_engine_ends_failed_without_the_fallback(
    monkeypatch, ending, summary
) -> None:
    _, emit = _collector()
    _host_answers(monkeypatch, _session_live)
    open_fallback = AsyncMock(return_value=_fallback_session())
    runner = _fallback_runner(
        monkeypatch, _fallback_callbacks(emit, open_fallback), agent_run=_failing_engine(ending)
    )

    result = await runner.run("count the comments")

    open_fallback.assert_not_awaited()
    assert runner.used_fallback is False
    assert (result.status, result.summary) == (BrowserSessionStatus.FAILED, summary)


async def test_a_run_the_user_stopped_never_moves_to_the_fallback_even_with_its_engine_gone(
    monkeypatch,
) -> None:
    _, emit = _collector()
    _host_answers(monkeypatch, _session_gone)
    open_fallback = AsyncMock(return_value=_fallback_session())
    runner = _fallback_runner(
        monkeypatch,
        _fallback_callbacks(emit, open_fallback, is_cancelled=AsyncMock(return_value=True)),
        agent_run=_failing_engine(_ENGINE_GAVE_OUT),
    )

    result = await runner.run("count the comments")

    open_fallback.assert_not_awaited()
    assert result.status == BrowserSessionStatus.CANCELLED


class _AgentRunHandedOffThenLostItsEngine(_AgentRunOnFailingEngine):
    """The user declined a handoff, and the engine was gone by the time the run ended."""

    async def execute(self, task: str) -> RunOutcome:
        from app.services.browser.exceptions import BrowserHandoffCancelled

        # Browser-Use turns the cancelled handoff into an action error and carries on.
        with pytest.raises(BrowserHandoffCancelled):
            await self._hooks.takeover("Sign in", "credentials")
        return await super().execute(task)


async def test_a_run_ended_by_a_declined_handoff_never_moves_to_the_fallback(monkeypatch) -> None:
    _, emit = _collector()
    _host_answers(monkeypatch, _session_gone)
    open_fallback = AsyncMock(return_value=_fallback_session())
    _failing_engine(_ENGINE_GAVE_OUT)
    runner = _fallback_runner(
        monkeypatch,
        _fallback_callbacks(
            emit,
            open_fallback,
            request_handoff=AsyncMock(return_value=HandoffOutcome(status=HandoffStatus.CANCELLED)),
        ),
        agent_run=_AgentRunHandedOffThenLostItsEngine,
    )

    result = await runner.run("count the comments")

    open_fallback.assert_not_awaited()
    assert result.status == BrowserSessionStatus.CANCELLED


class _AgentRunThatNeverEnds(_AgentRunOnFailingEngine):
    async def execute(self, task: str) -> RunOutcome:
        await asyncio.Event().wait()
        raise AssertionError("unreachable")


async def test_a_run_that_spent_its_whole_budget_never_moves_to_the_fallback(monkeypatch) -> None:
    _, emit = _collector()
    _host_answers(monkeypatch, _engine_wedged)
    open_fallback = AsyncMock(return_value=_fallback_session())
    runner = _fallback_runner(
        monkeypatch,
        _fallback_callbacks(emit, open_fallback),
        agent_run=_AgentRunThatNeverEnds,
        config=_fallback_config(task_timeout=0.05),
    )

    result = await runner.run("count the comments")

    open_fallback.assert_not_awaited()
    assert (result.status, result.summary) == (
        BrowserSessionStatus.FAILED,
        "Browser task timed out after 0.05s.",
    )


async def test_a_run_whose_fallback_engine_fails_too_ends_there_without_a_second_switch(
    monkeypatch,
) -> None:
    _, emit = _collector()
    _host_answers(monkeypatch, _session_gone)
    open_fallback = AsyncMock(return_value=_fallback_session())
    fallback_gave_out = RunOutcome(success=False, summary="The fallback gave out too.")
    agent = _failing_engine(_ENGINE_GAVE_OUT, fallback_gave_out)
    runner = _fallback_runner(
        monkeypatch, _fallback_callbacks(emit, open_fallback), agent_run=agent
    )

    result = await runner.run("count the comments")

    open_fallback.assert_awaited_once()
    assert agent.runs == [("s1", True), ("s-fallback", False)]
    assert (result.status, result.summary) == (
        BrowserSessionStatus.FAILED,
        "The fallback gave out too.",
    )


async def test_a_run_finished_on_the_fallback_bills_the_tokens_both_engines_spent(
    monkeypatch,
) -> None:
    """Regression: only the fallback half of a run was metered; the primary's tokens went unbilled."""
    record = AsyncMock()
    monkeypatch.setattr(runner_mod, "record_llm_call", record)
    _, emit = _collector()
    _host_answers(monkeypatch, _session_gone)
    agent = _failing_engine(
        replace(_ENGINE_GAVE_OUT, usage=[RunUsage("jev", 1000, 40), RunUsage("writer", 300, 20)]),
        RunOutcome(success=True, summary="67 comments", usage=[RunUsage("jev", 500, 10)]),
    )
    runner = _fallback_runner(
        monkeypatch,
        _fallback_callbacks(emit, AsyncMock(return_value=_fallback_session())),
        agent_run=agent,
    )

    await runner.run("count the comments")

    billed = {
        call.kwargs["model_name"]: (
            call.kwargs["usage"]["input_tokens"],
            call.kwargs["usage"]["output_tokens"],
        )
        for call in record.await_args_list
    }
    assert billed == {"jev": (1500, 50), "writer": (300, 20)}


# ---------------------------------------------------------------------------
# One run, two engines: the step count, the recap and the note span the switch
# ---------------------------------------------------------------------------


class _EngineAgent(FakeAgent):
    """Browser-Use on each engine in turn: every run plays the next scripted run.

    A step marked hang sits on the engine forever, as a click on a frozen engine does.
    """

    runs: ClassVar[list[tuple[list[dict], _History]]] = []
    made: ClassVar[list["_EngineAgent"]] = []
    #: Browser-Use's per-model token meter, read by a run the watchdog cut short.
    spent_by_model: ClassVar[dict[str, tuple[int, int]]] = {}

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.token_cost_service = SimpleNamespace(get_usage_summary=self._usage_summary)
        self.browser_session = SimpleNamespace(reset=AsyncMock())
        type(self).made.append(self)

    async def _usage_summary(self):
        return _Usage(
            {
                name: _Stats(prompt_tokens=inputs, completion_tokens=outputs)
                for name, (inputs, outputs) in type(self).spent_by_model.items()
            }
        )

    async def run(self, max_steps: int, on_step_end=None):
        script, history = type(self).runs.pop(0)
        type(self).script = [step for step in script if not step.get("hang")]
        type(self).history = history
        ended = await super().run(max_steps, on_step_end)
        if any(step.get("hang") for step in script):
            await asyncio.Event().wait()
        return ended


def _steps(*goals: str) -> list[dict]:
    return [
        {
            "goal": goal,
            "actions": [("click", {"index": 1})],
            "results": [{"extracted_content": goal}],
        }
        for goal in goals
    ]


@pytest.fixture
def two_engines(patch_browser, monkeypatch):
    """Jev on the real agent run, with the page reads it would make over CDP stubbed."""
    monkeypatch.setattr(browser_use, "Agent", _EngineAgent)
    monkeypatch.setattr(JevChatModel, "bind", lambda self, browser, task, gate: None)
    monkeypatch.setattr(JevChatModel, "viewport_points", lambda self: {})
    monkeypatch.setattr(JevChatModel, "take_step_screenshot", AsyncMock(return_value="ZmFrZQ=="))

    async def _upload(image: bytes, session_id: str, index: int) -> str:
        return f"https://cdn.test/{session_id}/{index}.png"

    monkeypatch.setattr(runner_mod, "publish_step_screenshot", _upload)
    _EngineAgent.runs = []
    _EngineAgent.made = []
    _EngineAgent.spent_by_model = {}


def _two_engine_runner(
    *,
    emit,
    note: AsyncMock | None = None,
    action_results: ActionResultsFn | None = None,
    is_cancelled: AsyncMock | None = None,
) -> tuple[BrowserTaskRunner, AsyncMock]:
    open_fallback = AsyncMock(return_value=_fallback_session())
    runner = BrowserTaskRunner(
        session=_session(),
        llm=JevChatModel(client=MagicMock(), text_model=MagicMock()),
        callbacks=BrowserRunnerCallbacks(
            emit=emit,
            request_handoff=AsyncMock(),
            is_cancelled=is_cancelled or AsyncMock(return_value=False),
            action_results=action_results,
            note=note,
            open_fallback_session=open_fallback,
        ),
        config=BrowserRunConfig(
            max_steps=10,
            max_actions_per_step=5,
            task_timeout_seconds=30,
            step_timeout_seconds=180,
            handoff_timeout_seconds=0,
            stream_screenshots=True,
            solve_captcha=False,
        ),
    )
    return runner, open_fallback


_GAVE_OUT = _History(done=False, successful=False, result=None)


async def test_a_run_that_moves_engines_numbers_its_steps_on_from_where_the_primary_stopped(
    two_engines, monkeypatch
) -> None:
    """Regression: the fallback run counted from 1 again, so its steps overwrote the primary's on the card and in the recap."""
    replay = AsyncMock(return_value="https://gaia.test/replay/r")
    monkeypatch.setattr(runner_mod, "create_replay_link", replay)
    _host_answers(monkeypatch, _session_gone)
    events, emit = _collector()
    outputs: list[int] = []

    async def _results(step: int, rows: list) -> None:
        outputs.append(step)

    _EngineAgent.runs = [
        (_steps("open the story", "open comments", "scroll"), _GAVE_OUT),
        (_steps("open comments again", "read the count"), _History()),
    ]
    runner, _ = _two_engine_runner(emit=emit, action_results=_results)

    result = await runner.run("count the comments")

    steps = [e for e in events if e.kind == BrowserEventKind.STEP]
    assert [(s.index, s.url) for s in steps] == [(i, "https://x") for i in range(1, 6)]
    assert outputs == [1, 2, 3, 4, 5]
    assert result.steps == 5
    assert replay.await_args.args == (
        "s-fallback",
        [
            "https://cdn.test/s1/1.png",
            "https://cdn.test/s1/2.png",
            "https://cdn.test/s1/3.png",
            "https://cdn.test/s-fallback/4.png",
            "https://cdn.test/s-fallback/5.png",
        ],
    )


@pytest.mark.parametrize("cause", ["engine_failed", "page_blocked"])
async def test_a_run_that_moves_engines_tells_the_user_once(
    two_engines, monkeypatch, cause
) -> None:
    """Regression: the user watched the steps start over with no word of why."""
    _host_answers(
        monkeypatch,
        _session_gone if cause == "engine_failed" else _host_holding(_SIGNED_IN_STATE, []),
    )
    note = AsyncMock()
    _, emit = _collector()
    _EngineAgent.runs = [(_steps("open"), _GAVE_OUT), (_steps("read"), _History())]
    runner, open_fallback = _two_engine_runner(emit=emit, note=note)
    if cause == "page_blocked":
        runner._llm.fallback_url = _BLOCKED_URL

    async with log_context("run_browser_job"):
        await runner.run("count the comments")
        event = dict(log.get())

    open_fallback.assert_awaited_once()
    assert event["browser"]["state_carry"] == (
        StateCarry.ENGINE_FAILED if cause == "engine_failed" else StateCarry.CARRIED
    )
    # A failed engine has no state to carry, and the user is told it starts from saved logins.
    note.assert_awaited_once_with(
        BROWSER_ENGINE_FALLBACK_WITHOUT_STATE_NOTE
        if cause == "engine_failed"
        else BROWSER_ENGINE_FALLBACK_NOTE
    )


async def test_a_run_that_stays_on_its_engine_says_nothing_about_engines(
    two_engines, monkeypatch
) -> None:
    _host_answers(monkeypatch, _session_live)
    note = AsyncMock()
    _, emit = _collector()
    _EngineAgent.runs = [(_steps("open", "read"), _History())]
    runner, open_fallback = _two_engine_runner(emit=emit, note=note)

    result = await runner.run("count the comments")

    open_fallback.assert_not_awaited()
    note.assert_not_awaited()
    assert result.steps == 2


# ---------------------------------------------------------------------------
# Engine watchdog: a frozen primary engine is caught while the run is on it
# ---------------------------------------------------------------------------


class _HostProbe:
    """The browser host's session endpoint, counting every liveness read the run makes."""

    def __init__(self, respond) -> None:
        self.reads = 0
        self._respond = respond

    async def __call__(self, request: httpx.Request) -> httpx.Response:
        self.reads += 1
        answer = self._respond(request)
        return await answer if asyncio.iscoroutine(answer) else answer


@pytest.fixture
def fast_watchdog(monkeypatch):
    from app.services.browser import engine_watchdog

    monkeypatch.setattr(engine_watchdog, "BROWSER_ENGINE_WATCH_INTERVAL_SECONDS", 0.01)
    monkeypatch.setattr(engine_watchdog, "BROWSER_ENGINE_WATCH_CANCEL_GRACE_SECONDS", 0.1)


def _watched_host(monkeypatch, respond) -> _HostProbe:
    probe = _HostProbe(respond)
    _host_answers(monkeypatch, probe)
    return probe


async def test_a_frozen_engine_moves_the_run_to_the_fallback_while_the_step_is_still_stuck(
    two_engines, fast_watchdog, monkeypatch
) -> None:
    """A SIGSTOPped engine took ~285 s to notice: a 15 s click timeout, then two 120 s state reads."""
    from app.constants.browser import BROWSER_ENGINE_WATCH_STRIKES

    probe = _watched_host(monkeypatch, _engine_wedged)
    events, emit = _collector()
    _EngineAgent.runs = [
        (_steps("open the story") + [{"hang": True}], _GAVE_OUT),
        (_steps("read the count"), _History(result="67 comments")),
    ]
    runner, open_fallback = _two_engine_runner(emit=emit)

    result = await asyncio.wait_for(runner.run("count the comments"), timeout=5)

    open_fallback.assert_awaited_once_with(None, None)
    assert probe.reads == BROWSER_ENGINE_WATCH_STRIKES
    # The frozen run's calls are failed at once rather than left holding
    # Browser-Use's global event lock, and so the fallback's first step, to a timeout.
    _EngineAgent.made[0].browser_session.reset.assert_awaited_once()
    assert (result.status, result.summary, result.steps) == (
        BrowserSessionStatus.COMPLETED,
        "67 comments",
        2,
    )


async def test_a_frozen_run_cut_short_still_bills_what_the_primary_spent(
    two_engines, fast_watchdog, monkeypatch
) -> None:
    record = AsyncMock()
    monkeypatch.setattr(runner_mod, "record_llm_call", record)
    _watched_host(monkeypatch, _engine_wedged)
    _, emit = _collector()
    _EngineAgent.spent_by_model = {"jev": (700, 30)}
    _EngineAgent.runs = [([{"hang": True}], _GAVE_OUT), (_steps("read"), _History())]
    runner, _ = _two_engine_runner(emit=emit)

    await asyncio.wait_for(runner.run("count the comments"), timeout=5)

    billed = [
        (call.kwargs["model_name"], call.kwargs["usage"]["input_tokens"])
        for call in record.await_args_list
    ]
    assert billed == [("jev", 700)]


async def test_a_frozen_engine_under_a_run_the_user_stopped_ends_it_cancelled_not_on_the_fallback(
    two_engines, fast_watchdog, monkeypatch
) -> None:
    _watched_host(monkeypatch, _engine_wedged)
    _, emit = _collector()
    _EngineAgent.runs = [([{"hang": True}], _GAVE_OUT)]
    runner, open_fallback = _two_engine_runner(emit=emit, is_cancelled=AsyncMock(return_value=True))

    result = await asyncio.wait_for(runner.run("count the comments"), timeout=5)

    open_fallback.assert_not_awaited()
    assert result.status == BrowserSessionStatus.CANCELLED


async def _slow_but_alive(request: httpx.Request) -> httpx.Response:
    await asyncio.sleep(0.03)
    return _session_live(request)


class _AgentRunOnASlowPage(_AgentRunOnFailingEngine):
    """A step on a heavy page: many watchdog intervals long, then it finishes."""

    async def execute(self, task: str) -> RunOutcome:
        type(self).runs.append((self._session.session_id, self._llm.fallback_available))
        await asyncio.sleep(0.3)
        return RunOutcome(success=True, summary="read it")

    async def spent(self) -> list[RunUsage]:
        return []


async def test_a_slow_page_on_a_live_engine_is_never_mistaken_for_a_frozen_one(
    fast_watchdog, monkeypatch
) -> None:
    probe = _watched_host(monkeypatch, _slow_but_alive)
    _, emit = _collector()
    open_fallback = AsyncMock(return_value=_fallback_session())
    runner = _fallback_runner(
        monkeypatch, _fallback_callbacks(emit, open_fallback), agent_run=_AgentRunOnASlowPage
    )

    result = await runner.run("read the page")

    open_fallback.assert_not_awaited()
    assert probe.reads >= 3  # the watchdog was reading the whole time
    assert (result.status, result.summary) == (BrowserSessionStatus.COMPLETED, "read it")


class _AgentRunPausedOnTheUser(_AgentRunOnFailingEngine):
    """The run hands the browser to the user and waits, many watchdog intervals long."""

    async def execute(self, task: str) -> RunOutcome:
        type(self).runs.append((self._session.session_id, self._llm.fallback_available))
        await self._hooks.takeover("Sign in", "credentials")
        return RunOutcome(success=True, summary="signed in and read it")

    async def spent(self) -> list[RunUsage]:
        return []


async def test_a_run_paused_on_the_user_is_never_cut_short_by_the_watchdog(
    fast_watchdog, monkeypatch
) -> None:
    probe = _watched_host(monkeypatch, _engine_wedged)
    _, emit = _collector()

    async def _user_takes_their_time(request, session) -> HandoffOutcome:
        await asyncio.sleep(0.3)
        return HandoffOutcome(status=HandoffStatus.COMPLETED)

    open_fallback = AsyncMock(return_value=_fallback_session())
    runner = _fallback_runner(
        monkeypatch,
        _fallback_callbacks(
            emit, open_fallback, request_handoff=AsyncMock(side_effect=_user_takes_their_time)
        ),
        agent_run=_AgentRunPausedOnTheUser,
    )

    result = await runner.run("sign in and read")

    open_fallback.assert_not_awaited()
    assert probe.reads == 0
    assert (result.status, result.summary) == (
        BrowserSessionStatus.COMPLETED,
        "signed in and read it",
    )


async def test_the_watchdog_stops_reading_the_host_once_the_run_ends(
    fast_watchdog, monkeypatch
) -> None:
    probe = _watched_host(monkeypatch, _session_live)
    _, emit = _collector()
    runner = _fallback_runner(
        monkeypatch,
        _fallback_callbacks(emit, AsyncMock(return_value=_fallback_session())),
        agent_run=_AgentRunOnASlowPage,
    )

    await runner.run("read the page")
    reads_at_the_end = probe.reads
    await asyncio.sleep(0.1)

    assert probe.reads == reads_at_the_end


class _AgentRunThatNeverEndsOnALiveEngine(_AgentRunThatNeverEnds):
    async def spent(self) -> list[RunUsage]:
        return []


async def test_the_watchdog_stops_reading_the_host_once_the_run_spent_its_budget(
    fast_watchdog, monkeypatch
) -> None:
    probe = _watched_host(monkeypatch, _session_live)
    _, emit = _collector()
    runner = _fallback_runner(
        monkeypatch,
        _fallback_callbacks(emit, AsyncMock(return_value=_fallback_session())),
        agent_run=_AgentRunThatNeverEndsOnALiveEngine,
        config=_fallback_config(task_timeout=0.1),
    )

    result = await runner.run("read the page")
    reads_at_the_end = probe.reads
    await asyncio.sleep(0.1)

    assert result.summary == "Browser task timed out after 0.1s."
    assert reads_at_the_end > 0
    assert probe.reads == reads_at_the_end
