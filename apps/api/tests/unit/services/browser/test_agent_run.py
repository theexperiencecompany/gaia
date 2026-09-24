"""The step frames a browser run hands the user: numbered by what was emitted, never silent on an errored step.

Browser-Use's own counter advances for steps that never reach a frame (an action
that errors, an observation the watchdog times out), so the user saw photos 2, 3,
4 and then 100s of nothing until 7.
"""

from collections.abc import Awaitable
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.services.browser.agent_run import STEP_ERROR_CAPTION, BrowserAgentRun
from app.services.browser.jev import JevChatModel
from app.services.browser.run_contract import BrowserRunConfig, RunHooks, StepFrame

CONFIG = BrowserRunConfig(
    max_steps=20,
    max_actions_per_step=2,
    task_timeout_seconds=300,
    step_timeout_seconds=30,
    handoff_timeout_seconds=60,
    stream_screenshots=True,
    solve_captcha=False,
)


class _Action:
    """One of Browser-Use's own action models: every action a field, all but the chosen one None."""

    def __init__(self, name: str, params: dict[str, Any]) -> None:
        self._fields: dict[str, Any] = {"click": None, "navigate": None, "done": None}
        self._fields[name] = params

    def model_dump(self, exclude_none: bool = False) -> dict[str, Any]:
        if not exclude_none:
            return dict(self._fields)
        return {
            name: {key: value for key, value in params.items() if value is not None}
            for name, params in self._fields.items()
            if params is not None
        }


class _Result:
    """One executed action's ActionResult, errored or not."""

    def __init__(self, *, error: str | None = None, content: str = "") -> None:
        self.error = error
        self.extracted_content = content
        self.long_term_memory = None


def _page(url: str = "https://example.test/page") -> Any:
    return SimpleNamespace(
        dom_state=SimpleNamespace(selector_map={}),
        url=url,
        title="Example",
        screenshot="c2hvdA==",
    )


def _output(name: str, params: dict[str, Any]) -> Any:
    return SimpleNamespace(action=[_Action(name, params)])


async def _never_stop() -> bool:
    return False


class _Harness:
    """A run wired to record what it emitted, plus the two Browser-Use callbacks."""

    def __init__(self, *, llm: Any = None, steps_before: int | None = None) -> None:
        self.frames: list[StepFrame] = []
        self.outputs: list[tuple[int, list[str]]] = []
        self.takeovers: list[tuple[str, str]] = []
        self.run = BrowserAgentRun(
            session=SimpleNamespace(cdp_url="ws://browser.test/cdp", session_id="sess-1"),
            llm=llm,
            config=CONFIG,
            hooks=RunHooks(
                step=self.frames.append,
                takeover=self._record_takeover,
                should_stop=_never_stop,
                action_results=self._record_outputs,
            ),
            step_timeout=30.0,
            # A fresh run takes the constructor's own default.
            **({} if steps_before is None else {"steps_before": steps_before}),
        )

    async def _record_takeover(self, reason: str, category: str) -> str | None:
        self.takeovers.append((reason, category))
        return None

    async def _record_outputs(self, step_index: int, outputs: list[Any]) -> None:
        self.outputs.append((step_index, [out.output for out in outputs]))

    async def step(self, n_steps: int, name: str = "click", **params: Any) -> None:
        await self.run._on_step(_page(), _output(name, params), n_steps)

    def end(self, *results: _Result) -> Awaitable[None]:
        return self.run._on_step_end(SimpleNamespace(state=SimpleNamespace(last_result=results)))


@pytest.fixture
def harness() -> _Harness:
    return _Harness()


@pytest.mark.unit
class TestFrameNumbering:
    async def test_frames_are_numbered_by_what_the_user_saw_not_by_browser_uses_counter(
        self, harness: _Harness
    ) -> None:
        await harness.step(2, index=4)
        await harness.end(_Result(content="clicked"))
        await harness.end(_Result(error="Step 3 timed out after 30 seconds"))
        await harness.step(7, index=9)
        await harness.end(_Result(content="clicked"))

        assert [frame.index for frame in harness.frames] == [1, 2, 3]

    async def test_a_step_that_never_reached_a_frame_still_gets_one_saying_so(
        self, harness: _Harness
    ) -> None:
        await harness.step(2, index=4)
        await harness.end(_Result(content="clicked"))
        await harness.end(_Result(error="Step 3 timed out after 30 seconds"))

        assert [frame.goal for frame in harness.frames][-1] == STEP_ERROR_CAPTION
        assert harness.frames[-1].actions == []
        assert harness.frames[-1].raw_screenshot is None

    async def test_a_step_that_errored_after_its_frame_is_not_framed_twice(
        self, harness: _Harness
    ) -> None:
        await harness.step(2, index=4)
        await harness.end(_Result(error="element is not clickable"))

        assert len(harness.frames) == 1
        assert harness.frames[0].goal != STEP_ERROR_CAPTION

    async def test_an_action_result_lands_on_the_frame_number_the_user_can_see(
        self, harness: _Harness
    ) -> None:
        await harness.step(2, index=4)
        await harness.end(_Result(content="clicked"))
        await harness.end(_Result(error="Step 3 timed out after 30 seconds"))
        await harness.step(7, index=9)
        await harness.end(_Result(content="confirmed"))

        assert harness.outputs[0] == (1, ["clicked"])
        assert harness.outputs[-1] == (3, ["confirmed"])


@pytest.mark.unit
class TestStepCaption:
    async def test_a_finishing_step_is_named_after_the_part_it_finished(
        self, harness: _Harness
    ) -> None:
        """Regression: the only step of a one-step run read "Step 1 · Finished"."""
        output = SimpleNamespace(
            next_goal="Read the top story on news.ycombinator.com",
            action=[_Action("done", {"text": "The top story is X.", "success": True})],
        )

        await harness.run._on_step(_page(), output, 1)

        assert harness.frames[-1].goal == "Read the top story on news.ycombinator.com"

    async def test_a_finish_that_did_not_achieve_the_goal_says_so_not_the_part(
        self, harness: _Harness
    ) -> None:
        output = SimpleNamespace(
            next_goal="Buy the item on shop.test",
            action=[_Action("done", {"text": "There is no Buy button.", "success": False})],
        )

        await harness.run._on_step(_page(), output, 1)

        assert harness.frames[-1].goal == "Could not find a way forward on this page"


@pytest.mark.unit
class TestTheFrame:
    async def test_it_lists_only_the_action_the_model_picked(self, harness: _Harness) -> None:
        """Browser-Use's action model carries every action as a field; the unset ones are None."""
        await harness.step(1, "click", index=4, text=None)

        assert [(a.name, a.inputs) for a in harness.frames[0].actions] == [("click", {"index": 4})]

    async def test_it_carries_the_steps_screenshot(self, harness: _Harness) -> None:
        await harness.step(1, index=4)

        assert harness.frames[0].raw_screenshot == "c2hvdA=="

    async def test_a_jev_run_shows_the_photo_jev_took_for_the_step(self) -> None:
        """Jev's session reads state without a screenshot; its own capture is the step's photo."""
        jev = MagicMock(spec=JevChatModel)
        jev.viewport_points.return_value = {}
        jev.take_step_screenshot = AsyncMock(return_value="amV2")
        harness = _Harness(llm=jev)

        await harness.step(1, index=4)

        assert harness.frames[0].raw_screenshot == "amV2"

    async def test_a_jev_step_with_no_photo_of_its_own_shows_the_states(self) -> None:
        """A run resumed on the fallback engine frames its first step before Jev captured anything."""
        jev = MagicMock(spec=JevChatModel)
        jev.viewport_points.return_value = {}
        jev.take_step_screenshot = AsyncMock(return_value=None)
        harness = _Harness(llm=jev)

        await harness.step(1, index=4)

        assert harness.frames[0].raw_screenshot == "c2hvdA=="

    async def test_a_password_typed_in_the_step_is_masked_in_the_frame(self) -> None:
        """A frame is shown to people and kept, so what went into a password field never reaches it."""
        jev = MagicMock(spec=JevChatModel)
        jev.viewport_points.return_value = {}
        jev.take_step_screenshot = AsyncMock(return_value="amV2")
        jev.redact.side_effect = lambda text: text.replace("hunter2", "********")
        harness = _Harness(llm=jev)

        await harness.step(1, "click", index=4, text="hunter2")

        assert harness.frames[0].actions[0].inputs == {"index": 4, "text": "********"}

    async def test_the_first_frame_reports_no_time_since_a_previous_one(
        self, harness: _Harness
    ) -> None:
        await harness.step(1, index=4)

        assert harness.frames[0].since_prev_ms == 0

    async def test_a_first_step_that_errors_before_any_frame_still_gets_one(
        self, harness: _Harness
    ) -> None:
        """The start URL's navigation runs before Browser-Use's first step callback."""
        await harness.end(_Result(error="net::ERR_NAME_NOT_RESOLVED"))

        assert [frame.goal for frame in harness.frames] == [STEP_ERROR_CAPTION]


@pytest.mark.unit
class TestAResumedRun:
    async def test_a_result_before_its_first_frame_lands_on_the_last_frame_the_user_saw(
        self,
    ) -> None:
        """The fallback engine's start navigation reports before it frames anything."""
        harness = _Harness(steps_before=5)

        await harness.end(_Result(content="navigated"))
        await harness.step(1, index=4)

        assert harness.outputs == [(5, ["navigated"])]
        assert [frame.index for frame in harness.frames] == [6]


@pytest.mark.unit
async def test_a_takeover_hands_the_user_the_reason_and_its_category(harness: _Harness) -> None:
    """The category picks the card the user gets (a password step is not a payment)."""
    await harness.run._takeover("Enter your password", "credentials")

    assert harness.takeovers == [("Enter your password", "credentials")]
