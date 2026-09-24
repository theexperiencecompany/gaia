"""One Jev step end to end: what is read, what is asked, and which way the step goes.

The step's branches (a part judged done, a stalled page, a part opening its own
site, a DONE the evidence check refuses, a failed decision) each change what the
run does next; these tests drive them through ainvoke with a scripted gateway and
a scripted writer, and assert on the action, the requests and the writer's context.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
import json
from types import SimpleNamespace
from typing import Any

from browser_use.agent.views import ActionModel, AgentOutput
from browser_use.llm.messages import UserMessage
from browser_use.tools.views import ClickElementActionIndexOnly, DoneAction, InputTextAction
from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel, create_model
import pytest

from app.constants.llm import ReasoningLevel
from app.services.browser.jev import chat_model as chat_model_mod
from app.services.browser.jev.chat_model import (
    JevChatModel,
    _PartDone,
    canonical_structured_call,
)
from app.services.browser.jev.gateway import JevGatewayError
from app.services.browser.jev.prompts import (
    DONE_SUMMARY,
    GUIDANCE_REASON,
    PART_DONE,
    PLAN_STEPS,
    TEXT_VALUE,
)
from app.services.browser.jev.viewport import ViewportBox, ViewportRead
from tests.helpers import captured_wide_event

from .conftest import FakeNode, make_state
from .test_chat_model import FakeSession, FakeTextModel, ScriptedGateway, _action, _agent_output

pytestmark = pytest.mark.unit

TASK = "Fly Zurich to London"
TWO_PARTS = ["Find the flights", {"goal": "Pick the cheapest"}]
#: Browser-Use's own prompt carries the request; a run bound without a task decides on it.
REQUEST = [UserMessage(content=f"<user_request>\n{TASK}\n</user_request>")]
BOUND = pytest.mark.parametrize("task", [TASK, ""], ids=["bound-task", "request-in-prompt"])

Verdict = Callable[[dict[str, Any]], Awaitable[dict[str, Any]]]


async def _not_done(_: dict[str, Any]) -> dict[str, Any]:
    return {"done": False}


async def _done(context: dict[str, Any]) -> dict[str, Any]:
    return {
        "requirements": ["the page"],
        "done": True,
        "evidence": [
            {"requirement": "the page", "kind": "fact", "source": context["pages_read"][-1]["url"]}
        ],
    }


class Writer:
    """The writer seam: a plan, the two part checks, and typed values from a queue.

    judge answers the background part judgement, check the DONE evidence check.
    Every call is recorded as (instructions, label, context).
    """

    def __init__(
        self,
        plan: list[Any] | None = None,
        *,
        judge: Verdict = _not_done,
        check: Verdict = _done,
        replies: list[dict[str, Any]] | None = None,
        closing: Callable[[], Awaitable[None]] | None = None,
    ) -> None:
        self.plan = plan or []
        self.judge = judge
        self.check = check
        self.helper = FakeTextModel(replies=list(replies or []))
        self.closing = closing
        self.calls: list[tuple[str, str | None, dict[str, Any]]] = []
        self.closing_asked = asyncio.Event()

    async def __call__(self, schema, prompt, *, label, timeout=None, reasoning=None):
        instructions = prompt[0].content
        context = json.loads(prompt[1].content)
        self.calls.append((instructions, label, context))
        if instructions.startswith(PLAN_STEPS):
            return schema.model_validate({"steps": self.plan})
        if instructions.startswith(PART_DONE):
            verdict = self.check if label == "browser_done_check" else self.judge
            return schema.model_validate(await verdict(context))
        if instructions.startswith(DONE_SUMMARY):
            self.closing_asked.set()
            if self.closing is not None:
                await self.closing()
        return await self.helper.structured(schema, prompt, label=label, timeout=timeout)

    def contexts(self, instructions: str, label: str | None = "any") -> list[dict[str, Any]]:
        return [
            c
            for i, lab, c in self.calls
            if i.startswith(instructions) and (label == "any" or lab == label)
        ]


class AskedGateway(ScriptedGateway):
    """A scripted gateway that says when Jev was asked."""

    def __init__(self, script: list[tuple[Any, ...]]) -> None:
        super().__init__(script=script)
        self.asked = asyncio.Event()

    async def evaluate(self, request):
        self.asked.set()
        return await super().evaluate(request)


def _model(
    state, script, writer: Writer, gateway: ScriptedGateway | None = None, task: str = TASK
) -> tuple[JevChatModel, ScriptedGateway, FakeSession]:
    gateway = gateway or ScriptedGateway(script=list(script))
    model = JevChatModel(client=gateway, text_model=FakeTextModel(), structured_call=writer)  # type: ignore[arg-type]  # a scripted gateway and a fake text model stand in for the real ones
    session = FakeSession(state)
    model.bind(session, task)  # type: ignore[arg-type]  # a fake session stands in for Browser-Use's
    return model, gateway, session


def _goal(request) -> str:
    return str(request.questions["operation"].instructions["goal"])


# ---------------------------------------------------------------------------
# The writer's one-shot and the model's own seams
# ---------------------------------------------------------------------------


class _Filled(BaseModel):
    text: str = ""


@pytest.mark.parametrize(("user_id", "metered_to"), [("u1", "u1"), (None, None)])
async def test_the_writer_call_is_metered_to_the_runs_user_with_the_steps_deadline(
    monkeypatch, user_id, metered_to
) -> None:
    seen: dict[str, Any] = {}

    async def ainvoke_structured(schema, prompt, *, label, config, options):
        seen.update(schema=schema, prompt=prompt, label=label, config=config, options=options)
        return _Filled(text="ok")

    monkeypatch.setattr(chat_model_mod, "ainvoke_structured", ainvoke_structured)
    prompt = [SystemMessage(content="instructions"), HumanMessage(content="{}")]

    result = await canonical_structured_call(user_id)(
        _Filled, prompt, label="browser_value", timeout=7.5, reasoning=ReasoningLevel.OFF
    )

    assert result == _Filled(text="ok")
    assert (seen["schema"], seen["prompt"], seen["label"]) == (_Filled, prompt, "browser_value")
    config = seen["config"]
    assert (config["configurable"]["user_id"] if config else None) == metered_to
    assert (seen["options"].timeout, seen["options"].reasoning) == (7.5, ReasoningLevel.OFF)


async def test_a_model_built_for_a_user_meters_every_writer_call_to_them(
    flights_state, monkeypatch
) -> None:
    configs: list[Any] = []

    async def ainvoke_structured(schema, prompt, *, label, config, options):
        configs.append(config)
        return schema()

    monkeypatch.setattr(chat_model_mod, "ainvoke_structured", ainvoke_structured)
    model = JevChatModel(
        client=ScriptedGateway(script=[("WAIT", None)]), text_model=FakeTextModel(), user_id="u1"
    )  # type: ignore[arg-type]  # a scripted gateway and a fake text model stand in for the real ones
    model.bind(FakeSession(flights_state), TASK)  # type: ignore[arg-type]  # a fake session stands in for Browser-Use's

    await model.ainvoke([], _agent_output())

    assert configs
    assert {config["configurable"]["user_id"] for config in configs} == {"u1"}


async def test_a_model_names_openrouter_as_its_provider_unless_told_otherwise() -> None:
    model = JevChatModel(client=ScriptedGateway(script=[]), text_model=FakeTextModel())  # type: ignore[arg-type]  # a scripted gateway and a fake text model stand in for the real ones

    assert model.provider == "openrouter"


async def test_before_any_step_there_is_no_photo_and_nothing_to_pulse() -> None:
    model = JevChatModel(client=ScriptedGateway(script=[]), text_model=FakeTextModel())  # type: ignore[arg-type]  # a scripted gateway and a fake text model stand in for the real ones

    assert model.viewport_points() == {}
    assert await model.take_step_screenshot() is None


async def test_browser_uses_own_calls_reach_the_text_model_untouched() -> None:
    received: list[tuple[Any, Any, dict[str, Any]]] = []

    class TextModel:
        async def ainvoke(self, messages, output_format=None, **kwargs):
            received.append((messages, output_format, kwargs))
            return "plain"

    model = JevChatModel(client=ScriptedGateway(script=[]), text_model=TextModel())  # type: ignore[arg-type]  # a scripted gateway and a minimal text model stand in for the real ones
    messages = [HumanMessage(content="summarise the page")]

    assert await model.ainvoke(messages, None, session_id="s1") == "plain"  # type: ignore[arg-type]  # Browser-Use's own message list
    assert received == [(messages, None, {"session_id": "s1"})]


def test_a_requirement_is_covered_by_an_entry_naming_it_in_any_case_or_spacing() -> None:
    verdict = _PartDone(
        requirements=["The Title", "the price"],
        evidence=[{"requirement": "the   TITLE", "source": "https://x"}],
    )

    assert verdict.uncovered() == ["the price"]


# ---------------------------------------------------------------------------
# Reading the page
# ---------------------------------------------------------------------------


class _Screen:
    """read_viewport as the real one uses node handles: a node already resolved on this page is reused."""

    def __init__(self) -> None:
        self.reads: list[tuple[Any, Any]] = []
        self.resolved: list[list[int]] = []

    async def __call__(self, browser, selector_map, handles):
        self.reads.append((browser, selector_map))
        fresh = [index for index in selector_map if handles.get(index) is None]
        for index in fresh:
            handles.put(index, f"object-{index}")
        self.resolved.append(fresh)
        return ViewportRead(
            boxes={
                index: ViewportBox(on_screen=True, cx=0.123456, cy=0.654321)
                for index in selector_map
            }
        )


async def test_the_screen_is_measured_for_the_pages_elements_with_handles_kept_per_page(
    monkeypatch,
) -> None:
    screen = _Screen()
    monkeypatch.setattr(chat_model_mod, "read_viewport", screen)
    page = make_state({4: FakeNode("BUTTON", text="Search")}, url="https://x/search")
    model, _, session = _model(page, [("WAIT", None)] * 3, Writer())

    await model.ainvoke([], _agent_output())
    points = model.viewport_points()
    await model.ainvoke([], _agent_output())
    session.state = make_state({4: FakeNode("BUTTON", text="Next")}, url="https://x/results")
    await model.ainvoke([], _agent_output())

    assert screen.reads[0] == (session, page.dom_state.selector_map)
    # Resolved once on the first page, reused on its next step, resolved again on the next page.
    assert screen.resolved == [[4], [], [4]]
    assert points == {4: (0.1235, 0.6543)}


async def test_a_state_summary_with_no_dom_or_url_still_gets_a_step(monkeypatch) -> None:
    screen = _Screen()
    monkeypatch.setattr(chat_model_mod, "read_viewport", screen)
    model, _, _ = _model(SimpleNamespace(title="Blank"), [("WAIT", None)], Writer())

    result = await model.ainvoke([], _agent_output())

    assert _action(result.completion) == {"wait": {"seconds": 4}}
    assert screen.reads[0][1] == {}


# ---------------------------------------------------------------------------
# Plain decided steps
# ---------------------------------------------------------------------------


async def test_each_step_is_numbered_in_its_memory(flights_state) -> None:
    model, _, _ = _model(flights_state, [("WAIT", None), ("WAIT", None)], Writer())

    await model.ainvoke([], _agent_output())
    second = await model.ainvoke([], _agent_output())

    assert second.completion.memory.startswith("Step 2:")


async def test_a_run_costs_what_the_gateway_reported_for_every_decision(flights_state) -> None:
    model, gateway, _ = _model(flights_state, [("WAIT", None), ("WAIT", None)], Writer())
    gateway.costs = [0.002, 0.003]

    await model.ainvoke([], _agent_output())
    await model.ainvoke([], _agent_output())

    assert model.actual_cost_usd == pytest.approx(0.005)


async def test_a_row_the_run_opened_is_not_offered_again_on_its_list() -> None:
    listing = make_state(
        {1: FakeNode("A", text="Story one"), 2: FakeNode("A", text="Story two")},
        url="https://news.example/list",
    )
    story = make_state({1: FakeNode("P", text="The story")}, url="https://news.example/one")
    model, gateway, session = _model(
        listing, [("CLICK", "1"), ("WAIT", None), ("WAIT", None)], Writer()
    )

    await model.ainvoke([], _agent_output())
    session.state = story
    await model.ainvoke([], _agent_output())
    session.state = listing
    await model.ainvoke([], _agent_output())

    assert set(gateway.requests[2].questions["click_target"].criteria) == {"2"}


async def test_a_failed_decision_idles_the_step_and_tells_jev_why(flights_state) -> None:
    class FailingOnce(ScriptedGateway):
        async def evaluate(self, request):
            if not self.requests:
                self.requests.append(request)
                raise JevGatewayError("gateway down")
            return await super().evaluate(request)

    gateway = FailingOnce(script=[("WAIT", None)])
    model, _, _ = _model(flights_state, [], Writer(), gateway)

    async with captured_wide_event() as event:
        first = await model.ainvoke([], _agent_output())
    await model.ainvoke([], _agent_output())

    assert _action(first.completion) == {"wait": {"seconds": 1}}
    assert first.completion.memory == "gateway down"
    assert event["browser"]["llm_error"] == "JevGatewayError"
    (recent,) = gateway.requests[1].state["recent_actions"]
    assert (recent["action"], recent["kind"], recent["text"]) == ("WAIT", "error", "gateway down")


# ---------------------------------------------------------------------------
# The plan
# ---------------------------------------------------------------------------


async def test_the_plan_is_written_once_for_the_task_even_when_the_run_rebinds_first(
    flights_state,
) -> None:
    writer = Writer()
    model, _, session = _model(flights_state, [("WAIT", None)], writer)
    model.bind(session, TASK)  # type: ignore[arg-type]  # a fake session stands in for Browser-Use's

    await model.ainvoke([], _agent_output())
    for _ in range(5):
        await asyncio.sleep(0)

    (plan,) = writer.contexts(PLAN_STEPS)
    assert plan["goal"] == TASK
    # Nothing is found before a part finishes.
    assert plan["findings"] == []


async def test_a_part_on_a_site_of_its_own_is_opened_without_asking_jev(flights_state) -> None:
    books = "https://books.toscrape.com/travel"
    writer = Writer([{"goal": "Find the cheapest book", "url": books}, {"goal": "Look it up"}])
    model, gateway, _ = _model(flights_state, [], writer)

    result = await model.ainvoke([], _agent_output())

    assert _action(result.completion) == {"navigate": {"url": books, "new_tab": False}}
    assert result.completion.memory.startswith("Step 1:")
    assert gateway.requests == []


@BOUND
async def test_a_part_judged_done_moves_the_step_onto_the_next_part(flights_state, task) -> None:
    """Part 1 judged done while a handoff waits on it: the step is decided for part 2, on the same page."""

    async def judge(context: dict[str, Any]) -> dict[str, Any]:
        return await (_done if "(1 of 2)" in context["goal"] else _not_done)(context)

    writer = Writer(TWO_PARTS, judge=judge, replies=[{"text": "LHR"}])
    model, gateway, _ = _model(
        flights_state, [("REQUEST_HUMAN", None), ("TYPE_TEXT", "2")], writer, task=task
    )

    result = await model.ainvoke(REQUEST, _agent_output())

    assert _action(result.completion) == {"input_text": {"index": 23, "text": "LHR", "clear": True}}
    first_part, second_part = writer.contexts(PART_DONE, label="browser_partdone")
    assert "CURRENT PART (1 of 2), the only thing to do now: Find the flights" in first_part["goal"]
    assert "CURRENT PART (2 of 2)" in second_part["goal"]
    assert second_part["page"]["url"] == "https://x"
    assert "CURRENT PART (2 of 2)" in _goal(gateway.requests[-1])


# ---------------------------------------------------------------------------
# Steps that wait on the part's judgement
# ---------------------------------------------------------------------------


@BOUND
async def test_a_handoff_waits_for_the_judgement_and_a_part_already_done_ends_the_run(
    flights_state, task
) -> None:
    """Asking a person to finish a part the writer already judged done hands them nothing to do."""
    gateway = AskedGateway([("REQUEST_HUMAN", None), ("WAIT", None)])

    async def judge(context: dict[str, Any]) -> dict[str, Any]:
        await gateway.asked.wait()
        return await _done(context)

    writer = Writer(judge=judge, replies=[{"text": "The flights are listed."}])
    model, _, _ = _model(flights_state, [], writer, gateway, task)

    result = await asyncio.wait_for(model.ainvoke(REQUEST, _agent_output()), timeout=1)

    assert _action(result.completion)["done"]["text"] == "The flights are listed."
    (closing,) = writer.contexts(DONE_SUMMARY)
    assert closing["goal"] == TASK


@BOUND
async def test_the_closing_answer_is_written_while_the_judgement_decides_a_done(
    flights_state, task
) -> None:
    """A DONE on the last part settles on the judgement of the pages read now, with its answer already in the writing."""
    writer = Writer(check=_not_done, replies=[{"text": "The flights are listed."}])

    async def judge(context: dict[str, Any]) -> dict[str, Any]:
        await writer.closing_asked.wait()
        return await _done(context)

    writer.judge = judge
    model, _, _ = _model(flights_state, [("DONE", None), ("WAIT", None)], writer, task=task)

    result = await asyncio.wait_for(model.ainvoke(REQUEST, _agent_output()), timeout=1)

    assert _action(result.completion)["done"]["text"] == "The flights are listed."
    (closing,) = writer.contexts(DONE_SUMMARY)
    assert closing["goal"] == TASK


@BOUND
async def test_a_done_the_check_accepts_on_the_last_part_carries_the_answer_written_alongside(
    flights_state, task
) -> None:
    """Part 1 finishes by judgement; Jev's DONE on part 2 is checked while its answer is written."""
    writer = Writer(TWO_PARTS, replies=[{"text": "Cheapest is 90 CHF."}])

    async def judge(context: dict[str, Any]) -> dict[str, Any]:
        return await (_done if "(1 of 2)" in context["goal"] else _not_done)(context)

    async def check(context: dict[str, Any]) -> dict[str, Any]:
        await writer.closing_asked.wait()
        return await _done(context)

    writer.judge, writer.check = judge, check
    model, _, _ = _model(
        flights_state, [("REQUEST_HUMAN", None), ("DONE", None)], writer, task=task
    )

    result = await asyncio.wait_for(model.ainvoke(REQUEST, _agent_output()), timeout=1)

    assert _action(result.completion)["done"]["text"] == "Cheapest is 90 CHF."
    (checked,) = writer.contexts(PART_DONE, label="browser_done_check")
    assert "CURRENT PART (2 of 2)" in checked["goal"]
    assert checked["page"]["url"] == "https://x"
    (closing,) = writer.contexts(DONE_SUMMARY)
    assert closing["page"]["url"] == "https://x"
    assert TASK in closing["goal"]


async def test_a_done_the_check_refuses_stops_its_answer_and_decides_again(flights_state) -> None:
    cancelled = asyncio.Event()

    async def never_written() -> None:
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            cancelled.set()
            raise

    writer = Writer(check=_not_done, closing=never_written, replies=[{"text": "London"}])
    model, _, _ = _model(flights_state, [("DONE", None), ("TYPE_TEXT", "2")], writer)

    result = await asyncio.wait_for(model.ainvoke([], _agent_output()), timeout=1)
    for _ in range(5):
        await asyncio.sleep(0)

    assert _action(result.completion) == {
        "input_text": {"index": 23, "text": "London", "clear": True}
    }
    assert cancelled.is_set()
    (typed,) = writer.contexts(TEXT_VALUE)
    assert typed["goal"] == TASK


@BOUND
async def test_a_done_the_check_accepts_on_an_earlier_part_decides_the_next_one(
    flights_state, task
) -> None:
    writer = Writer(TWO_PARTS, replies=[{"text": "LHR"}])
    model, gateway, _ = _model(
        flights_state, [("DONE", None), ("TYPE_TEXT", "2")], writer, task=task
    )

    result = await model.ainvoke(REQUEST, _agent_output())

    assert _action(result.completion) == {"input_text": {"index": 23, "text": "LHR", "clear": True}}
    assert "CURRENT PART (2 of 2)" in _goal(gateway.requests[-1])
    (typed,) = writer.contexts(TEXT_VALUE)
    assert "CURRENT PART (2 of 2)" in typed["goal"]


# ---------------------------------------------------------------------------
# A page that stopped changing
# ---------------------------------------------------------------------------


class _Guide(BaseModel):
    reason: str


def _output_with_guidance() -> type[AgentOutput]:
    actions = create_model(
        "ActionModel",
        __base__=ActionModel,
        click=(ClickElementActionIndexOnly | None, None),
        input_text=(InputTextAction | None, None),
        wait=(create_model("Wait", seconds=(int, 3)) | None, None),
        done=(DoneAction | None, None),
        request_agent_guidance=(_Guide | None, None),
    )
    return AgentOutput.type_with_custom_actions_flash_mode(actions)


async def test_a_page_unchanged_for_a_run_of_steps_asks_the_agent_without_spending_a_decision(
    flights_state,
) -> None:
    stalled_after = chat_model_mod._STALLED_STEPS
    writer = Writer(replies=[{"text": "The search never submits."}])
    model, gateway, session = _model(flights_state, [("WAIT", None)] * (stalled_after + 1), writer)

    async def allowed() -> bool:
        return True

    model.bind(session, TASK, guidance_allowed=allowed)  # type: ignore[arg-type]  # a fake session stands in for Browser-Use's
    output = _output_with_guidance()
    for _ in range(stalled_after):
        await model.ainvoke([], output)

    result = await asyncio.wait_for(model.ainvoke([], output), timeout=1)

    assert _action(result.completion) == {
        "request_agent_guidance": {"reason": "The search never submits."}
    }
    assert len(gateway.requests) == stalled_after
    assert result.completion.next_goal == "BLOCKED"
    assert result.completion.memory.startswith(f"Step {stalled_after + 1}:")
    (asked,) = writer.contexts(GUIDANCE_REASON)
    assert asked["goal"] == TASK

    # One stall is one BLOCKED: the next step is Jev's again, told what the stall asked.
    after = await asyncio.wait_for(model.ainvoke([], output), timeout=1)

    assert "wait" in _action(after.completion)
    blocked = gateway.requests[-1].state["recent_actions"][-1]
    assert (blocked["action"], blocked["kind"], blocked["text"], blocked["url"]) == (
        "BLOCKED",
        "blocked",
        "The search never submits.",
        "https://x",
    )
