"""What a browser run hands the user and the agent between steps.

Cards are numbered by what the user saw, never silent on an errored step, and
never shown twice for a step Jev's own burst card already covers; the agent
hears the user's mid-task words and any load the browser stopped; a wedged
connection is reported.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Awaitable
from contextlib import asynccontextmanager
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from typing import Any, ClassVar
from unittest.mock import MagicMock

from browser_use.agent.views import (
    ActionResult,
    AgentHistory,
    AgentHistoryList,
    AgentOutput,
    AgentState,
)
from browser_use.browser.views import BrowserStateHistory
from browser_use.tools.registry.views import ActionModel
import pytest

from app.constants.browser import (
    BROWSER_AGENT_FAST_ENGINE_NOTE,
    BROWSER_ENGINE_RESUMED_NOTE,
    BROWSER_GUIDANCE_MAX_ELEMENTS,
    BROWSER_GUIDANCE_PAGE_TEXT_MAX_CHARS,
    BROWSER_GUIDANCE_RECENT_ACTIONS,
    BROWSER_NO_GUIDANCE_AVAILABLE,
    BROWSER_TAKEOVER_DONE_NOTE,
    BrowserEngine,
    BrowserHandoffAction,
    BrowserRunFailure,
    EngineSwitchReason,
    JevOperation,
    JevStop,
)
from app.constants.log_tags import LogTag
from app.schemas.browser import (
    AgentGuidanceRequest,
    BrowserAction,
    BrowserTaskSecret,
    GuidanceElement,
)
from app.services.browser import agent_run as agent_run_mod
from app.services.browser.agent_run import (
    STEP_ERROR_CAPTION,
    AgentRunSetup,
    BrowserAgentRun,
    found_in_history,
)
from app.services.browser.exceptions import BrowserHandoffCancelled, BrowserUnavailableError
from app.services.browser.jev import loop as loop_mod
from app.services.browser.jev.decision import GENERATE
from app.services.browser.jev.gateway import JevEvaluation
from app.services.browser.jev.page import EngineScriptError, PageAction, PageUnresponsive
from app.services.browser.jev.secrets import RunSecrets
from app.services.browser.jev.tool import JEV_ACTION
from app.services.browser.ledger import CallComponent, ExecutedAction, RunLedger
from app.services.browser.run_contract import BrowserRunConfig, RunHooks, StepFrame
from app.services.browser.session import BrowserHostSession
from app.services.browser.stalled_loads import StalledLoads
from tests.helpers import captured_wide_event
from tests.unit.services.browser.jev.conftest import BUTTON, FIELD, FakePage, decision, page_state

pytestmark = pytest.mark.unit

CONFIG = BrowserRunConfig(
    max_steps=20,
    max_actions_per_step=2,
    task_timeout_seconds=300,
    step_timeout_seconds=30,
    handoff_timeout_seconds=60,
    stream_screenshots=True,
    solve_captcha=False,
)
SECRET = "hunter2-secret"


class _Action:
    """One of Browser-Use's action models: every action a field, all but the chosen one None."""

    def __init__(self, name: str, params: dict[str, Any]) -> None:
        self._fields: dict[str, Any] = {
            "click": None,
            "navigate": None,
            "done": None,
            JEV_ACTION: None,
        }
        self._fields[name] = params

    def model_dump(self, exclude_none: bool = False) -> dict[str, Any]:
        if not exclude_none:
            return dict(self._fields)
        return {name: params for name, params in self._fields.items() if params is not None}


class _Result:
    def __init__(
        self, *, error: str | None = None, content: str | None = "", memory: str | None = None
    ) -> None:
        self.error = error
        self.extracted_content = content
        self.long_term_memory = memory


def _output(*actions: _Action) -> SimpleNamespace:
    return SimpleNamespace(action=list(actions), next_goal=None)


def _node(
    *,
    name: str | None = None,
    text: str = "",
    attributes: dict[str, str] | None = None,
    tag: str = "BUTTON",
) -> SimpleNamespace:
    """Build a Browser-Use DOM node: its accessibility name, visible text, attributes and tag."""
    return SimpleNamespace(
        ax_node=SimpleNamespace(name=name) if name is not None else None,
        get_meaningful_text_for_llm=lambda: text,
        attributes=attributes or {},
        node_name=tag,
    )


#: The photo Browser-Use took of the page when it read the step's url and title.
STATE_PHOTO = "c3RhdGU="


def _state(
    url: str = "https://example.test/page", selector_map: dict[int, Any] | None = None
) -> Any:
    return SimpleNamespace(
        dom_state=SimpleNamespace(selector_map=selector_map or {}),
        url=url,
        title="Example",
        screenshot=STATE_PHOTO,
    )


class _Harness:
    """A run wired to record its cards and outputs, with Browser-Use's callbacks driven by hand."""

    def __init__(
        self,
        *,
        messages: list[str] | None = None,
        started: bool = True,
        engine: BrowserEngine = BrowserEngine.CHROMIUM,
        resumed_from: AgentState | None = None,
    ) -> None:
        self.frames: list[StepFrame] = []
        self.outputs: list[tuple[int, list[str]]] = []
        self.ledger = RunLedger()
        self._messages = list(messages or [])
        self.run = BrowserAgentRun(
            session=BrowserHostSession(
                session_id="sess-1",
                cdp_url="ws://browser.test/cdp",
                host_url="http://browser.test",
                engine=engine,
            ),
            config=CONFIG,
            hooks=RunHooks(
                step=self.frames.append,
                takeover=self._takeover,
                should_stop=self._never,
                user_waiting=self._never,
                take_user_messages=self._take_messages,
                action_results=self._record_outputs,
            ),
            setup=AgentRunSetup(
                user_id="user-1",
                ledger=self.ledger,
                secrets=RunSecrets(
                    {"password": BrowserTaskSecret(value=SECRET, site="example.test")}
                ),
                resumed_from=resumed_from,
            ),
        )
        self.new_tasks: list[str] = []
        if started:
            self.run._agent = SimpleNamespace(
                browser_session=MagicMock(),
                message_manager=SimpleNamespace(add_new_task=self.new_tasks.append),
                state=SimpleNamespace(last_result=None),
            )

    @staticmethod
    async def _never() -> bool:
        return False

    @staticmethod
    async def _takeover(reason: str, category: str) -> str | None:
        return None

    async def _take_messages(self) -> list[str]:
        taken, self._messages = self._messages, []
        return taken

    async def _record_outputs(self, step_index: int, outputs: list[Any]) -> None:
        self.outputs.append((step_index, [out.output for out in outputs]))

    async def step(
        self,
        name: str = "click",
        url: str = "https://example.test/page",
        selector_map: dict[int, Any] | None = None,
        **params: Any,
    ) -> None:
        await self.run._on_step(_state(url, selector_map), _output(_Action(name, params)), 0)  # type: ignore[arg-type]  # duck-typed Browser-Use views

    def end(self, *results: _Result) -> Awaitable[None]:
        return self.run._on_step_end(SimpleNamespace(state=SimpleNamespace(last_result=results)))


class _JevPages:
    """Opens the run's Jev page, only ever on the agent's own browser session."""

    def __init__(self, run: BrowserAgentRun, page: FakePage) -> None:
        self._run = run
        self.page = page
        self.engines: list[BrowserEngine] = []

    def __call__(self, browser_session: object, engine: BrowserEngine) -> FakePage:
        assert browser_session is self._run._agent.browser_session
        self.engines.append(engine)
        return self.page


@pytest.fixture
def harness(monkeypatch: pytest.MonkeyPatch) -> _Harness:
    harness = _Harness()
    monkeypatch.setattr(agent_run_mod, "JevPage", _JevPages(harness.run, FakePage(page_state())))
    return harness


class TestCards:
    async def test_cards_are_numbered_by_what_the_user_saw(self, harness: _Harness) -> None:
        await harness.step(index=4)
        await harness.end(_Result(content="clicked"))
        await harness.end(_Result(error="Step 3 timed out after 30 seconds"))
        await harness.step(index=9)
        await harness.end(_Result(content="confirmed"))

        assert [frame.index for frame in harness.frames] == [1, 2, 3]
        assert harness.frames[1].goal == STEP_ERROR_CAPTION
        # A step that errored shows the page it errored on.
        assert harness.frames[1].photo == "c2hvdA=="
        assert harness.outputs[-1] == (3, ["confirmed"])

    async def test_a_step_that_errored_after_its_card_is_not_shown_twice(
        self, harness: _Harness
    ) -> None:
        await harness.step(index=4)
        await harness.end(_Result(error="element is not clickable"))

        assert [frame.goal == STEP_ERROR_CAPTION for frame in harness.frames] == [False]

    async def test_a_step_that_only_hands_jev_a_goal_gets_no_card_of_its_own(
        self, harness: _Harness
    ) -> None:
        await harness.step(JEV_ACTION, goal="open the pricing page")
        await harness.end(_Result(content="Jev ran"))

        assert harness.frames == []

    async def test_a_secret_in_an_action_or_its_output_never_reaches_the_user(
        self, harness: _Harness
    ) -> None:
        await harness.step("click", index=3, text=SECRET)
        await harness.end(_Result(content=f"typed {SECRET}"))

        assert SECRET not in repr(harness.frames)
        assert SECRET not in repr(harness.outputs)

    async def test_a_password_the_agent_types_is_hidden_from_the_user_from_then_on(
        self, harness: _Harness
    ) -> None:
        fields = {8: _node(attributes={"type": "PASSWORD"}, tag="INPUT")}

        await harness.step("input", selector_map=fields, index=8, text="gaia-test-123")
        await harness.end(_Result(content="submitted-form.html?my-password=gaia-test-123"))

        assert "gaia-test-123" not in repr(harness.frames)
        assert "gaia-test-123" not in repr(harness.outputs)

    @pytest.mark.parametrize(
        ("action", "attributes"),
        [("input", {"type": "text"}), ("input", {}), ("click", {"type": "password"})],
    )
    async def test_what_the_agent_types_anywhere_else_stays_readable(
        self, harness: _Harness, action: str, attributes: dict[str, str]
    ) -> None:
        fields = {8: _node(attributes=attributes, tag="INPUT")}

        await harness.step(action, selector_map=fields, index=8, text="Ada Lovelace")
        await harness.end(_Result(content="Hello Ada Lovelace"))

        assert harness.outputs == [(1, ["Hello Ada Lovelace"])]

    @pytest.mark.parametrize(
        ("node", "label"),
        [
            (_node(name="Sign in", text="Log in", attributes={"aria-label": "Enter"}), "Sign in"),
            (_node(name="  ", text="Log in", attributes={"aria-label": "Enter"}), "Log in"),
            (_node(attributes={"value": "Submit", "aria-label": "Send form"}), "Send form"),
            (_node(attributes={"name": "q", "placeholder": "Search"}), "Search"),
            (_node(attributes={"id": "go"}), "go"),
            (_node(tag="BUTTON"), "button"),
            (_node(tag=" "), None),
        ],
    )
    async def test_a_card_names_the_element_an_action_targets(
        self, harness: _Harness, node: SimpleNamespace, label: str | None
    ) -> None:
        await harness.step(selector_map={4: node}, index=4)

        [action] = harness.frames[0].actions
        assert (action.name, action.target) == ("click", label)

    @pytest.mark.parametrize("params", [{"index": 9}, {"url": "https://example.test/"}])
    async def test_an_action_on_no_known_element_names_none(
        self, harness: _Harness, params: dict[str, Any]
    ) -> None:
        await harness.step("navigate", selector_map={4: _node(name="Sign in")}, **params)

        [action] = harness.frames[0].actions
        assert action.target is None

    @pytest.mark.parametrize(
        ("result", "shown"),
        [
            (_Result(error="element is gone", content="clicked"), ["element is gone"]),
            (_Result(content=None, memory="noted the price"), ["noted the price"]),
            (_Result(content="  two\n  lines "), ["two lines"]),
            (_Result(content="x" * 1000), ["x" * 1000]),
            (_Result(content="y" * 1200), ["y" * 999 + "…"]),
            (_Result(content="y" * 998 + " " + "z" * 300), ["y" * 998 + "…"]),
        ],
    )
    async def test_an_actions_outcome_is_shown_short_and_on_one_line(
        self, harness: _Harness, result: _Result, shown: list[str]
    ) -> None:
        await harness.step(index=4)
        await harness.end(result)

        assert harness.outputs == [(1, shown)]

    @pytest.mark.parametrize(
        "result",
        [_Result(content="  ", memory=None), _Result(content=None, memory=None)],
        ids=["blank", "nothing"],
    )
    async def test_an_action_with_nothing_to_show_adds_no_output(
        self, harness: _Harness, result: _Result
    ) -> None:
        await harness.step(index=4)
        await harness.end(result)

        assert harness.outputs == []

    async def test_a_step_that_only_hands_jev_a_goal_attaches_no_output(
        self, harness: _Harness
    ) -> None:
        await harness.step(JEV_ACTION, goal="open the pricing page")
        await harness.end(_Result(content="Jev ran: opened the pricing page"))

        assert harness.outputs == []

    async def test_every_step_is_recorded_as_an_executed_agent_action(
        self, harness: _Harness
    ) -> None:
        await harness.step(index=4)
        await harness.end(_Result(content="clicked"))

        [action] = harness.ledger.actions
        assert (action.component, action.description, action.count) == (
            CallComponent.AGENT,
            "Clicking",
            1,
        )

    async def test_a_step_that_hands_jev_a_goal_counts_no_action_of_its_own(
        self, harness: _Harness
    ) -> None:
        # Jev records each action it executes; the hand-off itself does nothing on the page.
        await harness.step(JEV_ACTION, goal="open the pricing page")
        await harness.end(_Result(content="Jev ran"))

        assert harness.ledger.action_count == 0


@pytest.mark.parametrize(
    "order",
    [["click", JEV_ACTION], [JEV_ACTION, "click"]],
    ids=["jev-after", "jev-before"],
)
async def test_an_actions_outcome_lands_on_its_own_row_of_its_steps_card_never_on_jevs(
    harness: _Harness, order: list[str]
) -> None:
    landed: list[tuple[int, list[tuple[int, str]]]] = []

    async def _record(step_index: int, outputs: list[Any]) -> None:
        landed.append((step_index, [(out.position, out.output) for out in outputs]))

    harness.run._hooks = replace(harness.run._hooks, action_results=_record)
    params = {"click": {"index": 3}, JEV_ACTION: {"goal": "open the pricing page"}}
    step = _output(*(_Action(name, params[name]) for name in order))
    await harness.run._on_step(_state(), step, 0)  # type: ignore[arg-type]  # duck-typed Browser-Use views
    # The burst that runs inside the step shows its own card.
    await harness.run._emit_burst([BrowserAction(name="click", inputs={})], "https://x.test", "X")
    results = {"click": _Result(content="clicked"), JEV_ACTION: _Result(content="Jev ran: ...")}

    await harness.end(*(results[name] for name in order))

    step_card = harness.frames[0].index
    assert landed == [(step_card, [(0, "clicked")])]


class TestStepRecords:
    async def test_a_first_step_that_errors_before_its_card_still_gets_one(
        self, harness: _Harness
    ) -> None:
        await harness.end(_Result(error="Browser-Use could not read the page"))

        [frame] = harness.frames
        assert frame.goal == STEP_ERROR_CAPTION
        # No page was open yet to photograph, and no step ran to record.
        assert frame.photo is None
        assert harness.ledger.actions == []

    async def test_a_step_card_carries_the_page_the_step_acted_on(self, harness: _Harness) -> None:
        await harness.step(url="https://example.test/cart", index=4)

        [frame] = harness.frames
        assert (frame.session_id, frame.url, frame.title) == (
            "sess-1",
            "https://example.test/cart",
            "Example",
        )
        # The photo of the moment its url and title were read, not one racing the step's actions.
        assert (frame.photo, frame.since_prev_ms) == (STATE_PHOTO, 0)

    async def test_a_burst_card_shows_the_page_jev_ended_on_unless_it_does_not_answer(
        self, harness: _Harness, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        async def _unanswered() -> str:
            raise PageUnresponsive("Page.captureScreenshot got no answer in 20s")

        await harness.step(index=4)
        burst = [BrowserAction(name="click", inputs={})]
        await harness.run._emit_burst(burst, "https://x.test", "X")
        monkeypatch.setattr(harness.run._page, "screenshot", _unanswered)
        async with captured_wide_event() as event:
            await harness.run._emit_burst(burst, "https://x.test", "X")
        assert [frame.photo for frame in harness.frames[1:]] == ["c2hvdA==", None]
        [warning] = event["warnings"]
        assert (warning["msg"].endswith("Step photo not taken"), warning["error_type"]) == (
            True,
            "PageUnresponsive",
        )

    async def test_the_last_page_a_card_showed_is_where_a_resume_would_reopen(
        self, harness: _Harness
    ) -> None:
        await harness.step(url="https://example.test/cart", index=4)

        assert harness.run.last_url == "https://example.test/cart"

    async def test_a_run_with_nowhere_to_mirror_results_still_records_its_steps(
        self, harness: _Harness
    ) -> None:
        harness.run._hooks = replace(harness.run._hooks, action_results=None)

        await harness.step(index=4)
        await harness.end(_Result(content="clicked"))

        assert harness.ledger.action_count == 1

    async def test_a_step_is_recorded_with_its_actions_and_how_long_they_took(
        self, harness: _Harness, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        clock = iter([10.0, 12.0])
        monkeypatch.setattr(agent_run_mod, "perf_counter", lambda: next(clock))

        await harness.run._on_step(
            _state(),
            _output(_Action("click", {"index": 4}), _Action("navigate", {"url": "https://x.test"})),
            0,
        )  # type: ignore[arg-type]  # duck-typed Browser-Use views
        await harness.end(_Result(content="ok"), _Result(content="ok"))

        [action] = harness.ledger.actions
        assert (action.description, action.duration_ms, action.count) == (
            "Clicking, Opening x.test",
            2000,
            2,
        )

    async def test_a_finishing_step_is_captioned_with_what_it_found(
        self, harness: _Harness
    ) -> None:
        output = SimpleNamespace(
            action=[_Action("done", {"success": True, "text": "3 orders"})],
            next_goal="Read the 3 open orders",
        )

        await harness.run._on_step(_state(), output, 0)  # type: ignore[arg-type]  # duck-typed Browser-Use views

        assert harness.frames[0].goal == "Read the 3 open orders"

    async def test_a_run_that_has_not_started_answers_and_stops_cleanly(self) -> None:
        run = _Harness(started=False).run

        assert await run.connection_answers() is True
        run.stop()
        assert run.last_url is None


class _ReportingLoads(StalledLoads):
    """The run's load watcher, with loads it already saw stall or not finish."""

    def __init__(self, *, stalled: list[str], unfinished: list[str]) -> None:
        super().__init__(MagicMock())
        self._seen_stalled = stalled
        self._seen_unfinished = unfinished

    def take(self) -> list[str]:
        return self._seen_stalled

    def take_unfinished(self) -> list[str]:
        return self._seen_unfinished


class TestBetweenSteps:
    async def test_the_users_words_reach_the_agent_as_a_follow_up_request_with_secrets_masked(
        self,
    ) -> None:
        harness = _Harness(messages=[f"use {SECRET} instead"])

        await harness.run._on_step_start(None)

        assert len(harness.new_tasks) == 1
        assert SECRET not in harness.new_tasks[0]

    async def test_a_load_the_browser_stopped_reaches_the_agent_as_a_result(
        self, harness: _Harness
    ) -> None:
        harness.run._stalls = _ReportingLoads(
            stalled=["https://slow.test/ sent nothing for 15 s"],
            unfinished=["https://late.test/ had not finished loading"],
        )

        await harness.run._on_step_start(None)

        stalled, unfinished = harness.run._agent.state.last_result
        assert "slow.test" in stalled.long_term_memory
        assert "late.test" in unfinished.long_term_memory


class _Client:
    def __init__(self, answers: bool) -> None:
        self._answers = answers
        self.send = SimpleNamespace(Target=SimpleNamespace(getTargets=self._get_targets))

    async def _get_targets(self) -> dict[str, list[object]]:
        if not self._answers:
            await asyncio.Event().wait()
        return {"targetInfos": []}


class TestConnectionProbe:
    async def test_a_run_that_has_not_connected_yet_is_not_judged(self, harness: _Harness) -> None:
        harness.run._agent = None

        assert await harness.run.connection_answers() is True

    @pytest.mark.parametrize("answers", [True, False])
    async def test_it_reports_whether_the_runs_own_connection_answers_in_time(
        self, harness: _Harness, monkeypatch: pytest.MonkeyPatch, answers: bool
    ) -> None:
        monkeypatch.setattr(agent_run_mod, "BROWSER_ENGINE_PROBE_TIMEOUT_SECONDS", 0.05)
        harness.run._agent.browser_session = SimpleNamespace(
            is_cdp_connected=True, cdp_client=_Client(answers)
        )

        assert await harness.run.connection_answers() is answers


async def test_a_model_that_cannot_be_built_is_named_on_the_runs_event(
    harness: _Harness, monkeypatch: pytest.MonkeyPatch
) -> None:
    def _no_model(ledger: RunLedger) -> None:
        raise BrowserUnavailableError("OPENROUTER_API_KEY is not set")

    monkeypatch.setattr(agent_run_mod, "build_agent_llm", _no_model)

    async with captured_wide_event() as event:
        with pytest.raises(BrowserUnavailableError):
            await harness.run.execute("read the page")

    assert event["browser"]["llm_error"] == "BrowserUnavailableError"


class _History:
    def __init__(
        self,
        answer: str | None,
        *,
        done: bool = True,
        successful: bool = True,
        errors: list[str | None] | None = None,
        steps: int = 1,
    ) -> None:
        self._answer = answer
        self._done = done
        self._successful = successful
        self._errors = errors or [None]
        self._steps = steps

    def errors(self) -> list[str | None]:
        return self._errors

    def number_of_steps(self) -> int:
        return self._steps

    def final_result(self) -> str | None:
        return self._answer

    def is_done(self) -> bool:
        return self._done

    def is_successful(self) -> bool:
        return self._successful


class _Browser:
    """The run's GaiaBrowserSession: records what listens on its event bus and its CDP connection."""

    def __init__(self, **options: Any) -> None:
        self.options = options
        self.listeners: list[tuple[object, Any]] = []
        self.watched: list[str] = []
        self.event_bus = SimpleNamespace(
            on=lambda event, handler: self.listeners.append((event, handler))
        )
        page_events = {
            name: (lambda handler, name=name: self.watched.append(name))
            for name in (
                "frameRequestedNavigation",
                "frameStartedNavigating",
                "frameNavigated",
                "frameStoppedLoading",
                "loadEventFired",
            )
        }
        self.cdp_client = SimpleNamespace(
            register=SimpleNamespace(Page=SimpleNamespace(**page_events))
        )


class _Agent:
    """Browser-Use's Agent: runs scripted steps through the callbacks the run gave it."""

    steps: ClassVar[list[_Action]] = []
    history: ClassVar[_History] = _History("done")
    raises: ClassVar[BaseException | None] = None
    built: ClassVar[list[_Agent]] = []
    #: Where it writes to disk, as Browser-Use does under the temp dir.
    files: ClassVar[Path]

    def __init__(self, **options: Any) -> None:
        self.options = options
        # Step screenshots, and the file system, which a resumed agent restores where the primary had it.
        self.agent_directory = self.files / f"agent_{len(_Agent.built)}"
        (self.agent_directory / "screenshots").mkdir(parents=True)
        self.file_system_path = str(self.files / "file_system")
        Path(self.file_system_path).mkdir(exist_ok=True)
        self.ran_steps = 0
        self.stopped = False
        self.browser_session = SimpleNamespace(
            get_current_page_url=self._url, reset=self._noop, is_cdp_connected=False
        )
        self.message_manager = SimpleNamespace(add_new_task=lambda task: None)
        self.state = SimpleNamespace(last_result=None)
        self.task = options["task"]
        _Agent.built.append(self)

    @staticmethod
    async def _url() -> str:
        return "https://example.test/orders"

    @staticmethod
    async def _noop() -> None:
        return None

    def stop(self) -> None:
        self.stopped = True

    async def act(self, action: str, params: dict[str, Any]) -> Any:
        """Call one of the run's tools the way the agent does."""
        return await self.options["tools"].registry.execute_action(action, params)

    async def run(self, max_steps: int, on_step_start: Any, on_step_end: Any) -> _History:
        if self.raises is not None:
            raise self.raises
        for action in self.steps[:max_steps]:
            if await self.options["register_should_stop_callback"]():
                break
            await on_step_start(self)
            await self.options["register_new_step_callback"](_state(), _output(action), 1)
            self.state.last_result = [_Result(content="ok")]
            self.ran_steps += 1
            await on_step_end(self)
        return self.history


class _Stalls(agent_run_mod.StalledLoads):
    """The run's stall watcher, recording whether the run closed it."""

    closed = False

    def close(self) -> None:
        type(self).closed = True
        super().close()


class _TextModel:
    """The tiny model Jev writes a value with when the goal implies one."""

    async def ainvoke(self, messages: list[object], output_format: object) -> SimpleNamespace:
        return SimpleNamespace(completion=SimpleNamespace(text="Ada"))


_LLM = object()
_TEXT_MODEL = _TextModel()
_JEV_CLIENT = MagicMock(model="jev")


class _JevGateway:
    """The run's decisions client, opened for the run and closed when it ends."""

    open: ClassVar[bool] = False

    @classmethod
    @asynccontextmanager
    async def opened(cls) -> AsyncIterator[MagicMock]:
        cls.open = True
        try:
            yield _JEV_CLIENT
        finally:
            cls.open = False


@pytest.fixture
def built_with(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> list[tuple[str, object]]:
    """Stand Browser-Use, the models and the stall watcher in for a run; record what each model was built for."""
    built: list[tuple[str, object]] = []

    def _llm(ledger: RunLedger) -> object:
        built.append(("agent", ledger))
        return _LLM

    def _text_model(ledger: RunLedger) -> _TextModel:
        built.append(("text", ledger))
        return _TEXT_MODEL

    monkeypatch.setattr(agent_run_mod, "Agent", _Agent)
    monkeypatch.setattr(agent_run_mod, "GaiaBrowserSession", _Browser)
    monkeypatch.setattr(agent_run_mod, "build_agent_llm", _llm)
    monkeypatch.setattr(agent_run_mod, "build_text_model", _text_model)
    monkeypatch.setattr(agent_run_mod, "open_jev_client", _JevGateway.opened)
    monkeypatch.setattr(agent_run_mod, "StalledLoads", _Stalls)
    monkeypatch.setattr(_Agent, "steps", [])
    monkeypatch.setattr(_Agent, "history", _History("done"))
    monkeypatch.setattr(_Agent, "raises", None)
    monkeypatch.setattr(_Agent, "built", [])
    monkeypatch.setattr(_Agent, "files", tmp_path, raising=False)
    monkeypatch.setattr(_Stalls, "closed", False)
    return built


@pytest.mark.usefixtures("built_with")
class TestExecute:
    async def test_the_answer_reaches_the_user_with_secrets_hidden_and_the_page_it_ended_on(
        self, harness: _Harness
    ) -> None:
        _Agent.history = _History(f"Signed in with {SECRET}; 3 orders.")

        outcome = await harness.run.execute("read my orders")

        assert outcome.success is True
        assert SECRET not in outcome.summary
        assert "3 orders" in outcome.summary
        assert harness.run.last_url == "https://example.test/orders"

    @pytest.mark.parametrize(
        ("history", "success"),
        [
            (_History("partial", done=False), False),
            (_History("gave up", successful=False), False),
            (_History(None), True),
        ],
    )
    async def test_the_outcome_is_what_the_agent_finished_with(
        self, harness: _Harness, history: _History, success: bool
    ) -> None:
        _Agent.history = history

        outcome = await harness.run.execute("read my orders")

        assert (outcome.success, outcome.summary) == (success, history.final_result() or "")

    @pytest.mark.parametrize(
        ("history", "failure"),
        [
            (_History("gave up", successful=False), BrowserRunFailure.GOAL_NOT_ACHIEVED),
            (_History(None, done=False, errors=[None, "page gone"]), BrowserRunFailure.STEP_FAILED),
            (_History(None, done=False, steps=CONFIG.max_steps), BrowserRunFailure.STEP_LIMIT),
            (_History(None, done=False), None),
            (_History("done"), None),
        ],
    )
    async def test_a_run_that_did_not_succeed_says_why_from_its_history(
        self, harness: _Harness, history: _History, failure: BrowserRunFailure | None
    ) -> None:
        _Agent.history = history

        outcome = await harness.run.execute("read my orders")

        assert outcome.failure == failure

    async def test_the_agent_runs_on_the_browser_models_and_this_runs_browser(
        self, harness: _Harness, built_with: list[tuple[str, object]]
    ) -> None:
        await harness.run.execute("read my orders")

        agent = _Agent.built[-1]
        assert agent.options["task"].startswith("read my orders")
        assert (agent.options["llm"], agent.options["page_extraction_llm"]) == (_LLM, _TEXT_MODEL)
        assert built_with == [("agent", harness.ledger), ("text", harness.ledger)]
        browser = agent.options["browser"]
        # The run's own session, fingerprinted for the run's user.
        assert browser.options == {"cdp_url": "ws://browser.test/cdp", "user_id": "user-1"}

    async def test_the_stall_watcher_listens_on_every_connect_of_this_browser(
        self, harness: _Harness
    ) -> None:
        await harness.run.execute("read my orders")
        browser = _Agent.built[-1].options["browser"]

        (connected, mark), (_, attach), (navigated, note) = browser.listeners
        assert harness.run.connected is False
        mark(SimpleNamespace())
        await attach(SimpleNamespace())
        note(SimpleNamespace(target_id="tab", error_message=None))

        assert harness.run.connected is True
        assert [event.__name__ for event, _ in browser.listeners] == [
            "BrowserConnectedEvent",
            "BrowserConnectedEvent",
            "NavigationCompleteEvent",
        ]
        assert browser.watched == [
            "frameRequestedNavigation",
            "frameStartedNavigating",
            "frameNavigated",
            "frameStoppedLoading",
            "loadEventFired",
        ]

    @pytest.mark.parametrize("ending", [RuntimeError("engine gone"), asyncio.CancelledError()])
    async def test_the_stall_watcher_and_jevs_gateway_are_closed_however_the_run_ends(
        self, harness: _Harness, ending: BaseException
    ) -> None:
        _Agent.raises = ending

        with pytest.raises(type(ending)):
            await harness.run.execute("read my orders")

        assert (_Stalls.closed, _JevGateway.open) == (True, False)
        assert list(_Agent.files.iterdir()) == []
        # A run that never finished has no page to resume at.
        assert harness.run.last_url is None

    async def test_files_that_cannot_be_removed_are_named_and_the_run_keeps_its_own_ending(
        self, harness: _Harness, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        class _Unremovable(_Agent):
            def __init__(self, **options: Any) -> None:
                super().__init__(**options)
                # A file where a directory should be: removing it fails.
                self.file_system_path = str(self.files / "not_a_directory")
                Path(self.file_system_path).write_text("")

        monkeypatch.setattr(agent_run_mod, "Agent", _Unremovable)
        _Agent.raises = RuntimeError("engine gone")

        async with captured_wide_event() as event:
            with pytest.raises(RuntimeError, match="engine gone"):
                await harness.run.execute("read my orders")

        assert {
            "msg": f"{LogTag.BROWSER} Browser agent files not removed",
            "path": str(_Agent.files / "not_a_directory"),
            "error_type": "NotADirectoryError",
        } in event["warnings"]

    @pytest.mark.parametrize(
        ("start_url", "page"),
        [("https://shop.test/cart", "https://shop.test/cart"), (None, "about:blank")],
    )
    async def test_a_run_resumed_on_the_fallback_goes_on_from_the_primarys_state(
        self, monkeypatch: pytest.MonkeyPatch, start_url: str | None, page: str
    ) -> None:
        primary = AgentState(n_steps=7, stopped=True, paused=True, consecutive_failures=3)
        run = _Harness(started=False, resumed_from=primary).run
        monkeypatch.setattr(
            agent_run_mod, "JevPage", lambda session, engine: FakePage(page_state())
        )
        run._config = replace(CONFIG, start_url=start_url)

        await run.execute("buy the ticket")

        options = _Agent.built[-1].options
        resumed = options["injected_agent_state"]
        assert (resumed.n_steps, resumed.stopped, resumed.paused) == (7, False, False)
        assert (resumed.consecutive_failures, options["initial_actions"]) == (0, None)
        # The request it reads each step says the move is done (h_switch_told asked again),
        # and the page the fallback opened is not replaced by the task's first URL.
        assert BROWSER_ENGINE_RESUMED_NOTE.format(page=page) in options["task"]
        assert options["directly_open_url"] is False

    @pytest.mark.parametrize("engine", list(BrowserEngine))
    async def test_jev_drives_the_page_on_the_engine_its_host_reported(
        self, monkeypatch: pytest.MonkeyPatch, engine: BrowserEngine
    ) -> None:
        harness = _Harness(started=False, engine=engine)
        pages = _JevPages(harness.run, FakePage(page_state()))
        monkeypatch.setattr(agent_run_mod, "JevPage", pages)
        _Agent.steps = [_Action("click", {"index": 1})]

        await harness.run.execute("read my orders")

        assert set(pages.engines) == {engine}

    async def test_a_run_stops_at_its_step_limit(self, harness: _Harness) -> None:
        _Agent.steps = [_Action("click", {"index": n}) for n in range(CONFIG.max_steps + 5)]

        await harness.run.execute("read my orders")

        assert _Agent.built[-1].ran_steps == CONFIG.max_steps

    async def test_a_run_that_finishes_closes_its_stall_watcher_and_jevs_gateway(
        self, harness: _Harness
    ) -> None:
        await harness.run.execute("read my orders")

        assert (_Stalls.closed, _JevGateway.open) == (True, False)
        assert list(_Agent.files.iterdir()) == []


@pytest.mark.usefixtures("built_with")
class TestTools:
    @pytest.mark.parametrize(
        ("note", "read"), [("Paid.", "Paid."), (None, BROWSER_TAKEOVER_DONE_NOTE)]
    )
    async def test_the_agent_can_hand_the_browser_to_the_user_and_reads_their_note(
        self, harness: _Harness, note: str | None, read: str
    ) -> None:
        asked: list[tuple[str, str]] = []

        async def _takeover(reason: str, category: str) -> str | None:
            asked.append((reason, category))
            return note

        harness.run._hooks = replace(harness.run._hooks, takeover=_takeover)
        await harness.run.execute("buy the ticket")
        agent = _Agent.built[-1]

        await agent.act(
            "request_human_takeover", {"reason": "Enter your card.", "category": "payment"}
        )
        # The wait runs once the step ends, outside the step's own budget.
        assert asked == []
        await harness.run._on_step_end(agent)

        assert asked == [("Enter your card.", "payment")]
        assert agent.state.last_result[-1].long_term_memory == read

    async def test_a_handoff_that_ends_the_run_reaches_the_agent_as_an_error(
        self, harness: _Harness
    ) -> None:
        async def _cancelled(reason: str, category: str) -> str | None:
            raise BrowserHandoffCancelled("cancelled")

        harness.run._hooks = replace(harness.run._hooks, takeover=_cancelled)
        await harness.run.execute("buy the ticket")
        agent = _Agent.built[-1]
        await agent.act(
            "request_human_takeover", {"reason": "Enter your card.", "category": "payment"}
        )

        await harness.run._on_step_end(agent)

        assert "cancelled" in agent.state.last_result[-1].error

    async def test_guidance_is_asked_with_the_task_the_run_was_given(
        self, harness: _Harness
    ) -> None:
        asked: list[AgentGuidanceRequest] = []

        async def _guidance(request: AgentGuidanceRequest) -> str:
            asked.append(request)
            return "Click Next."

        async def _allowed() -> bool:
            return True

        harness.run._hooks = replace(
            harness.run._hooks, guidance=_guidance, guidance_allowed=_allowed
        )
        _Agent.steps = [_Action("click", {"index": 1})]
        await harness.run.execute("buy the ticket")
        agent = _Agent.built[-1]

        await agent.act("request_agent_guidance", {"reason": "stuck"})
        await harness.run._on_step_end(agent)

        [request] = asked
        assert request.task == "buy the ticket"

    async def test_the_agent_asking_for_guidance_hears_that_none_is_available(
        self, harness: _Harness
    ) -> None:
        await harness.run.execute("buy the ticket")

        result = await _Agent.built[-1].act("request_agent_guidance", {"reason": "stuck"})

        assert BROWSER_NO_GUIDANCE_AVAILABLE in str(result)

    async def test_only_a_run_that_can_move_engines_offers_it_or_a_captcha_tool_when_asked(
        self, harness: _Harness
    ) -> None:
        await harness.run.execute("buy the ticket")

        offered = set(_Agent.built[-1].options["tools"].registry.registry.actions)
        assert {JEV_ACTION, "request_human_takeover", "request_agent_guidance"} <= offered
        assert "continue_in_full_browser" not in offered
        assert BrowserHandoffAction.SOLVE_CAPTCHA_WITH_HELP not in offered
        assert (
            BROWSER_AGENT_FAST_ENGINE_NOTE not in _Agent.built[-1].options["extend_system_message"]
        )

    @pytest.mark.parametrize(
        ("page", "handed"), [("https://shop.test/cart", True), ("https://ads.test/x", False)]
    )
    async def test_a_bot_check_goes_to_the_user_only_on_a_site_the_task_named(
        self, harness: _Harness, page: str, handed: bool
    ) -> None:
        asked: list[str] = []

        async def _takeover(reason: str, category: str) -> str | None:
            asked.append(reason)
            return None

        harness.run._hooks = replace(harness.run._hooks, takeover=_takeover)
        harness.run._config = replace(CONFIG, solve_captcha=True, start_url="https://shop.test/")
        await harness.run.execute("buy the ticket")
        agent = _Agent.built[-1]

        async def _on_page() -> str:
            return page

        captcha = agent.options["tools"].registry.registry.actions["solve_captcha_with_help"]
        await captcha.function(
            params=captcha.param_model(challenge="Tick the box."),
            browser_session=SimpleNamespace(get_current_page_url=_on_page),
        )
        await harness.run._on_step_end(agent)

        assert asked == (["Tick the box."] if handed else [])

    async def test_the_agent_on_the_fast_engine_can_move_the_run_to_chrome(
        self, harness: _Harness
    ) -> None:
        switched: list[tuple[EngineSwitchReason, str | None]] = []

        async def _switch(reason: EngineSwitchReason, url: str | None) -> str:
            switched.append((reason, url))
            return "moving"

        harness.run._hooks = replace(harness.run._hooks, switch_engine=_switch)
        harness.run._config = replace(CONFIG, solve_captcha=True)
        await harness.run.execute("buy the ticket")
        agent = _Agent.built[-1]

        result = await agent.act("continue_in_full_browser", {"category": "renders_wrong"})

        assert "moving" in str(result)
        assert switched == [(EngineSwitchReason.RENDERS_WRONG, "https://example.test/orders")]
        assert agent.stopped is True
        offered = set(agent.options["tools"].registry.registry.actions)
        assert BrowserHandoffAction.SOLVE_CAPTCHA_WITH_HELP in offered
        assert agent.options["extend_system_message"].endswith(BROWSER_AGENT_FAST_ENGINE_NOTE)


@pytest.mark.usefixtures("built_with")
class TestJevInTheRun:
    """A Jev burst the agent starts works on the run's page, ledger, secrets and signals."""

    @pytest.fixture
    def page(self, monkeypatch: pytest.MonkeyPatch, harness: _Harness) -> FakePage:
        page = FakePage(page_state(text=f"welcome {SECRET}"), page_state(url="https://site.test/b"))
        monkeypatch.setattr(agent_run_mod, "JevPage", _JevPages(harness.run, page))
        return page

    @pytest.fixture
    def decisions(self, monkeypatch: pytest.MonkeyPatch) -> list[object]:
        clients: list[object] = []
        script = [
            decision(JevOperation.TYPE_TEXT, FIELD),
            decision(JevOperation.CLICK, BUTTON),
            decision(JevOperation.DONE),
        ]

        async def _decide(client: object, *args: Any, **kwargs: Any) -> Any:
            clients.append(client)
            return script.pop(0)

        async def _choose(*args: Any, **kwargs: Any) -> tuple[str, JevEvaluation]:
            return GENERATE, JevEvaluation(answers={}, provider="openrouter")

        monkeypatch.setattr(loop_mod, "decide", _decide)
        monkeypatch.setattr(loop_mod, "choose_value", _choose)
        return clients

    async def _burst(self, harness: _Harness) -> str:
        await harness.run.execute("fill the form")
        result = await _Agent.built[-1].act(
            JEV_ACTION, {"goal": "fill the form", "done_when": "the form is sent"}
        )
        return str(result.extracted_content)

    async def test_a_script_the_fast_engine_cannot_run_moves_the_run_to_chrome(
        self, harness: _Harness, monkeypatch: pytest.MonkeyPatch, decisions: list[object]
    ) -> None:
        """Obscura lacked createTreeWalker; the run asked the user about Bing instead of moving."""
        gap = EngineScriptError("Jev's page script failed: TypeError: createTreeWalker")
        page = FakePage(page_state(), read_fails=(0, gap))
        monkeypatch.setattr(agent_run_mod, "JevPage", _JevPages(harness.run, page))
        switched: list[EngineSwitchReason] = []

        async def _switch(reason: EngineSwitchReason, url: str | None) -> str:
            switched.append(reason)
            return "moving"

        harness.run._hooks = replace(harness.run._hooks, switch_engine=_switch)

        report = await self._burst(harness)

        assert switched == [EngineSwitchReason.SCRIPT_UNSUPPORTED]
        assert "moving" in report
        assert _Agent.built[-1].stopped is True

    async def test_a_goal_quoting_a_secrets_name_reaches_no_burst(
        self, harness: _Harness, page: FakePage, decisions: list[object]
    ) -> None:
        """The run's secrets are the delegate's: the agent's untagged "password" is refused."""
        await harness.run.execute("log in")

        result = await _Agent.built[-1].act(
            JEV_ACTION, {"goal": 'type "password" and sign in', "done_when": "signed in"}
        )

        assert "the name of a secret" in str(result.error)
        assert decisions == []

    async def test_a_burst_types_clicks_and_reports_through_the_run(
        self, harness: _Harness, page: FakePage, decisions: list[object]
    ) -> None:
        report = await self._burst(harness)

        assert page.typed == ["Ada", None]
        assert set(decisions) == {_JEV_CLIENT}
        assert [a.component for a in harness.ledger.actions] == [CallComponent.JEV] * 2
        assert SECRET not in report
        # The burst's actions reach the user as one card, on the page Jev ended on.
        [frame] = harness.frames
        assert (frame.url, frame.title) == ("https://site.test/b", "Site")

    async def test_a_run_asked_to_stop_ends_the_burst(
        self, harness: _Harness, page: FakePage, decisions: list[object]
    ) -> None:
        async def _stop() -> bool:
            return True

        harness.run._hooks = replace(harness.run._hooks, should_stop=_stop)

        report = await self._burst(harness)

        assert f"Stopped: {JevStop.STOPPED.value}." in report

    async def test_a_user_message_ends_the_burst(
        self, harness: _Harness, page: FakePage, decisions: list[object]
    ) -> None:
        async def _waiting() -> bool:
            return True

        harness.run._hooks = replace(harness.run._hooks, user_waiting=_waiting)

        report = await self._burst(harness)

        assert f"Stopped: {JevStop.USER_MESSAGE.value}." in report


class TestGuidance:
    """A stuck agent asks the agent that started the run, with the page as it stands, secrets hidden."""

    @pytest.fixture
    def asked(self, harness: _Harness) -> list[AgentGuidanceRequest]:
        asked: list[AgentGuidanceRequest] = []

        async def _guidance(request: AgentGuidanceRequest) -> str:
            asked.append(request)
            return "Click Next."

        async def _allowed() -> bool:
            return True

        harness.run._hooks = replace(
            harness.run._hooks, guidance=_guidance, guidance_allowed=_allowed
        )
        harness.run._task = "buy the ticket"
        # An inner area to scroll is on the page, but is no control to name.
        scroll = PageAction(
            id="scroll_down_99", node=99, kind="scroll", label="Scroll down in List", delta=240
        )
        links = [
            PageAction(id=f"e{n}", node=n, kind="click", label=f"Link {n}", role="link")
            for n in range(BROWSER_GUIDANCE_MAX_ELEMENTS + 5)
        ]
        links[1] = PageAction(id="e1", node=1, kind="fill", label="Name")
        page = replace(
            page_state(url=f"https://example.test/?pw={SECRET}", text=SECRET + "x" * 2000),
            actions=[scroll, *links],
        )
        harness.run._page = FakePage(page)  # type: ignore[assignment]  # the page the run observes
        for n in range(BROWSER_GUIDANCE_RECENT_ACTIONS + 2):
            harness.ledger.executed(
                ExecutedAction(
                    component=CallComponent.AGENT, description=f"step {n}", duration_ms=1
                )
            )
        return asked

    async def test_the_agent_that_started_the_run_answers_with_the_page_in_view(
        self, harness: _Harness, asked: list[AgentGuidanceRequest]
    ) -> None:
        await harness.run._guidance("nothing moves the task forward")
        await harness.run._on_step_end(harness.run._agent)

        assert harness.run._agent.state.last_result[-1].long_term_memory == "Click Next."
        [request] = asked
        assert (request.reason, request.task, request.title) == (
            "nothing moves the task forward",
            "buy the ticket",
            "Site",
        )
        assert SECRET not in request.url
        assert request.url.startswith("https://example.test/")
        assert SECRET not in request.page_text
        assert len(request.page_text) == BROWSER_GUIDANCE_PAGE_TEXT_MAX_CHARS
        # Controls only, numbered as listed; a control with no role goes by its kind.
        assert request.elements[:2] == [
            GuidanceElement(label="Link 0", role="link"),
            GuidanceElement(label="Name", role="fill"),
        ]
        assert len(request.elements) == BROWSER_GUIDANCE_MAX_ELEMENTS - 1
        assert [a.action for a in request.recent_actions] == [
            f"step {n}" for n in range(2, BROWSER_GUIDANCE_RECENT_ACTIONS + 2)
        ]

    @pytest.mark.parametrize("missing", ["guidance", "guidance_allowed", "page", "refused"])
    async def test_with_no_one_to_ask_the_agent_hears_none_is_available(
        self, harness: _Harness, asked: list[AgentGuidanceRequest], missing: str
    ) -> None:
        async def _refused() -> bool:
            return False

        if missing == "page":
            harness.run._page = None
        elif missing == "refused":
            harness.run._hooks = replace(harness.run._hooks, guidance_allowed=_refused)
        else:
            harness.run._hooks = replace(harness.run._hooks, **{missing: None})

        assert await harness.run._guidance("stuck") == BROWSER_NO_GUIDANCE_AVAILABLE
        assert asked == []


class _Actions(ActionModel):
    """Two of Browser-Use's actions, as an agent step names them."""

    extract: dict[str, str] | None = None
    click: dict[str, int] | None = None


def _did(memory: str | None, *acts: tuple[str, dict[str, Any], ActionResult]) -> AgentHistory:
    return AgentHistory(
        model_output=AgentOutput(
            memory=memory, action=[_Actions(**{name: params}) for name, params, _ in acts]
        ),
        result=[result for _, _, result in acts],
        state=BrowserStateHistory(url="", title="", tabs=[], interacted_element=[]),
    )


def test_what_a_run_found_is_each_page_it_read_and_its_last_note() -> None:
    read = ("extract", {"query": "price"}, ActionResult(extracted_content="Price: $12"))
    failed = ("extract", {"query": "x"}, ActionResult(error="no page", extracted_content="?"))
    clicked = ("click", {"index": 3}, ActionResult(extracted_content="Clicked Next"))
    # A step cut short ran fewer actions than it chose.
    cut_short = _did("Opened the shop.", read, clicked)
    cut_short.result.pop()
    history = AgentHistoryList(
        history=[cut_short, _did("Price is $12; reviews next.", failed), _did(None, clicked)]
    )

    assert found_in_history(history) == ["Price: $12", "Price is $12; reviews next."]
    # With no note at all, only what it read.
    assert found_in_history(AgentHistoryList(history=[_did(None, read)])) == ["Price: $12"]
