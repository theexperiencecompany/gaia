"""What a browser run hands the user and the agent between steps.

Cards are numbered by what the user saw, never silent on an errored step, and
never shown twice for a step Jev's own burst card already covers; the agent
hears the user's mid-task words and any load the browser stopped; a run that
repeats itself on an unchanged page ends; a wedged connection is reported.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock

import pytest

from app.constants.browser import BROWSER_AGENT_NO_PROGRESS_STEPS
from app.services.browser import agent_run as agent_run_mod
from app.services.browser.agent_run import STEP_ERROR_CAPTION, BrowserAgentRun
from app.services.browser.jev.secrets import RunSecrets
from app.services.browser.jev.tool import JEV_ACTION
from app.services.browser.ledger import CallComponent, RunLedger
from app.services.browser.run_contract import BrowserRunConfig, RunHooks, StepFrame

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
        return {name: params for name, params in self._fields.items() if params is not None}


class _Result:
    def __init__(self, *, error: str | None = None, content: str = "") -> None:
        self.error = error
        self.extracted_content = content
        self.long_term_memory = None


class _Page:
    async def screenshot(self) -> str:
        return "c2hvdA=="


def _state(
    url: str = "https://example.test/page", selector_map: dict[int, Any] | None = None
) -> Any:
    return SimpleNamespace(
        dom_state=SimpleNamespace(selector_map=selector_map or {}), url=url, title="Example"
    )


class _Harness:
    """A run wired to record its cards and outputs, with Browser-Use's callbacks driven by hand."""

    def __init__(self, *, messages: list[str] | None = None) -> None:
        self.frames: list[StepFrame] = []
        self.outputs: list[tuple[int, list[str]]] = []
        self.ledger = RunLedger()
        self._messages = list(messages or [])
        self.run = BrowserAgentRun(
            session=SimpleNamespace(cdp_url="ws://browser.test/cdp", session_id="sess-1"),  # type: ignore[arg-type]  # a duck-typed host session
            config=CONFIG,
            hooks=RunHooks(
                step=self.frames.append,
                takeover=self._takeover,
                should_stop=self._never,
                user_waiting=self._never,
                take_user_messages=self._take_messages,
                action_results=self._record_outputs,
            ),
            step_timeout=30.0,
            secrets=RunSecrets({"password": SECRET}, ["example.test"]),
            ledger=self.ledger,
            user_id="user-1",
        )
        self.new_tasks: list[str] = []
        self.run._agent = SimpleNamespace(
            browser_session=MagicMock(),
            message_manager=SimpleNamespace(add_new_task=self.new_tasks.append),
            state=SimpleNamespace(last_result=None),
        )
        self.run._page = _Page()  # type: ignore[assignment]  # the screenshot is all a card reads

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
        self, name: str = "click", url: str = "https://example.test/page", **params: Any
    ) -> None:
        await self.run._on_step(_state(url), SimpleNamespace(action=[_Action(name, params)]), 0)  # type: ignore[arg-type]  # duck-typed Browser-Use views

    def end(self, *results: _Result) -> Awaitable[None]:
        return self.run._on_step_end(SimpleNamespace(state=SimpleNamespace(last_result=results)))


@pytest.fixture
def harness() -> _Harness:
    return _Harness()


class TestCards:
    async def test_cards_are_numbered_by_what_the_user_saw(self, harness: _Harness) -> None:
        await harness.step(index=4)
        await harness.end(_Result(content="clicked"))
        await harness.end(_Result(error="Step 3 timed out after 30 seconds"))
        await harness.step(index=9)
        await harness.end(_Result(content="confirmed"))

        assert [frame.index for frame in harness.frames] == [1, 2, 3]
        assert harness.frames[1].goal == STEP_ERROR_CAPTION
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
        password_field = SimpleNamespace(
            attributes={"type": "password"}, ax_node=None, node_name="INPUT"
        )
        password_field.get_meaningful_text_for_llm = lambda: ""
        state = _state(selector_map={8: password_field})

        await harness.run._on_step(
            state,
            SimpleNamespace(action=[_Action("input", {"index": 8, "text": "gaia-test-123"})]),
            0,
        )  # type: ignore[arg-type]  # duck-typed Browser-Use views
        await harness.end(_Result(content="submitted-form.html?my-password=gaia-test-123"))

        assert "gaia-test-123" not in repr(harness.frames)
        assert "gaia-test-123" not in repr(harness.outputs)

    async def test_every_step_is_recorded_as_an_executed_agent_action(
        self, harness: _Harness
    ) -> None:
        await harness.step(index=4)
        await harness.end(_Result(content="clicked"))

        [action] = harness.ledger.actions
        assert (action.component, action.description, action.count) == (
            CallComponent.AGENT,
            "click",
            1,
        )

    async def test_a_step_that_hands_jev_a_goal_counts_no_action_of_its_own(
        self, harness: _Harness
    ) -> None:
        # Jev records each action it executes; the hand-off itself does nothing on the page.
        await harness.step(JEV_ACTION, goal="open the pricing page")
        await harness.end(_Result(content="Jev ran"))

        assert harness.ledger.action_count == 0


async def test_the_same_actions_on_an_unchanged_page_end_the_run(harness: _Harness) -> None:
    for _ in range(BROWSER_AGENT_NO_PROGRESS_STEPS - 1):
        await harness.step(index=4)
    assert harness.run.no_progress is False

    await harness.step(index=4)

    assert harness.run.no_progress is True
    assert await harness.run._should_stop() is True


async def test_a_different_page_is_progress_even_with_the_same_action(harness: _Harness) -> None:
    for n in range(BROWSER_AGENT_NO_PROGRESS_STEPS):
        await harness.step(index=4, url=f"https://example.test/page/{n}")

    assert harness.run.no_progress is False


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
        harness.run._stalls = SimpleNamespace(
            take=lambda: ["https://slow.test/ sent nothing for 15 s"]
        )  # type: ignore[assignment]  # the take() the run reads

        await harness.run._on_step_start(None)

        [note] = harness.run._agent.state.last_result
        assert "slow.test" in note.long_term_memory


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
