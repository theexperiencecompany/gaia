"""Jev's run state across steps: the plan, part judgements, the back list and what a blocked step reports."""

from __future__ import annotations

import asyncio
import json
from typing import Any
from unittest.mock import AsyncMock

import pytest

from app.constants.browser import BROWSER_GUIDANCE_PAGE_TEXT_MAX_CHARS
from app.services.browser.jev import chat_model as chat_model_mod
from app.services.browser.jev.chat_model import JevChatModel
from app.services.browser.jev.prompts import DONE_SUMMARY, PART_DONE, PLAN_STEPS
from tests.helpers import captured_wide_event

from .conftest import FakeNode, make_state
from .test_chat_model import (
    _HN,
    _HN_TASK,
    _LOGIN,
    _SECURE,
    _TOP_STORY_PLAN,
    FakeSession,
    FakeTextModel,
    ScriptedGateway,
    _action,
    _agent_output,
    _evidence_writer,
    _model,
    _on_part,
    _run_to_done,
    _writer_model,
)

pytestmark = pytest.mark.unit

_TASK = "Fly Zurich to London"
_A = "https://site.example/a"
_B = "https://site.example/b"


def _page(url: str, text: str = "Results") -> Any:
    return make_state({1: FakeNode("A", text=text)}, url=url)


def _offered(gateway: ScriptedGateway) -> set[str]:
    return set(gateway.requests[-1].questions["operation"].criteria)


def _goal(gateway: ScriptedGateway) -> str:
    return str(gateway.requests[-1].questions["operation"].instructions["goal"])


def _planner(parts: list[Any], part_done=None):
    """Return a writer with this plan; part_done(context, label) answers each judgement (not done by default)."""
    helper = FakeTextModel(replies=[{"text": "Answered."}] * 4)
    judged: list[dict[str, Any]] = []

    async def writer(schema, prompt, *, label, timeout=None, reasoning=None):
        if prompt[0].content.startswith(PLAN_STEPS):
            return schema.model_validate({"steps": parts})
        if prompt[0].content.startswith(PART_DONE):
            context = json.loads(prompt[1].content)
            judged.append(context)
            verdict = part_done(context, label) if part_done else {"done": False}
            return schema.model_validate(verdict)
        return await helper.structured(schema, prompt, label=label, timeout=timeout)

    return writer, helper, judged


async def _settle() -> None:
    for _ in range(20):
        await asyncio.sleep(0)


# ---------------------------------------------------------------------------
# What a blocked step shows the agent it asks for guidance
# ---------------------------------------------------------------------------


def test_a_request_before_any_page_carries_no_invented_page_or_task() -> None:
    model = JevChatModel(client=ScriptedGateway(script=[]), text_model=FakeTextModel())  # type: ignore[arg-type]  # a scripted gateway and a fake text model stand in for the real ones

    request = model.guidance_request("stuck")

    assert (request.task, request.url, request.title, request.page_text) == ("", "", "", "")
    assert request.elements == [] and request.recent_actions == []


async def test_the_request_carries_the_text_of_the_page_the_run_is_on() -> None:
    long_text = "Top story: " + "x" * (BROWSER_GUIDANCE_PAGE_TEXT_MAX_CHARS * 2)
    model, _, _, _ = _model(_page(_A, long_text), [("WAIT", None)])
    await model.ainvoke([], _agent_output())

    page_text = model.guidance_request("stuck").page_text

    assert page_text.startswith("[1]<a>Top story: ")
    assert len(page_text) == BROWSER_GUIDANCE_PAGE_TEXT_MAX_CHARS


async def test_each_recent_action_says_whether_it_changed_the_page() -> None:
    model, _, _, session = _model(_page(_A), [("CLICK", "1"), ("WAIT", None), ("WAIT", None)])
    await model.ainvoke([], _agent_output())
    session.state = _page(_B)
    await model.ainvoke([], _agent_output())
    await model.ainvoke([], _agent_output())

    changed = [a.page_changed for a in model.guidance_request("stuck").recent_actions]

    assert changed == [True, False, None]


async def test_the_agents_own_instruction_is_not_reported_as_the_users() -> None:
    model, _, _, _ = _model(_page(_A), [("WAIT", None)])
    await model.ainvoke([], _agent_output())
    model.note_from_agent("open the second result")

    assert model.guidance_request("stuck").user_notes == []


async def test_the_first_page_on_a_fresh_browser_says_nothing_about_the_last_action() -> None:
    """The fallback's first page cannot be compared with the dead engine's last one."""
    model, _, _, session = _model(_page(_A), [("CLICK", "1"), ("WAIT", None)])
    model.fallback_available = True
    await model.ainvoke([], _agent_output())
    model.fall_back_after_engine_failure()
    model.continue_on_fallback()
    session.state = _page(_A)
    await model.ainvoke([], _agent_output())

    assert model.guidance_request("stuck").recent_actions[0].page_changed is None


def test_a_note_with_no_step_is_refused() -> None:
    model = JevChatModel(client=ScriptedGateway(script=[]), text_model=FakeTextModel())  # type: ignore[arg-type]  # a scripted gateway and a fake text model stand in for the real ones

    with pytest.raises(RuntimeError, match=chat_model_mod.NO_STEP_FOR_NOTE):
        model.note_from_user("skip it")


async def test_a_failed_step_photo_is_named_on_the_wide_event() -> None:
    model, _, _, session = _model(_page(_A), [("CLICK", "1")])
    session.take_screenshot = AsyncMock(side_effect=TimeoutError("render"))

    async with captured_wide_event() as event:
        await model.ainvoke([], _agent_output())
        await model.take_step_screenshot()

    (warning,) = [w for w in event["warnings"] if "screenshot failed" in w["msg"]]
    assert warning["error_type"] == "TimeoutError"


# ---------------------------------------------------------------------------
# GO_BACK is offered only while this browser has somewhere to go back to
# ---------------------------------------------------------------------------


async def test_going_back_to_the_first_page_leaves_nothing_to_go_back_to() -> None:
    model, gateway, _, session = _model(
        _page(_A), [("CLICK", "1"), ("GO_BACK", None), ("WAIT", None), ("WAIT", None)]
    )
    await model.ainvoke([], _agent_output())
    session.state = _page(_B)
    await model.ainvoke([], _agent_output())
    session.state = _page(_A)
    await model.ainvoke([], _agent_output())
    await model.ainvoke([], _agent_output())

    assert "GO_BACK" not in _offered(gateway)


async def test_a_link_back_to_an_earlier_page_can_still_be_gone_back_from() -> None:
    """Only GO_BACK retraces the history; a click that lands on an earlier page is a new page of it."""
    model, gateway, _, session = _model(_page(_A), [("CLICK", "1"), ("CLICK", "1"), ("WAIT", None)])
    await model.ainvoke([], _agent_output())
    session.state = _page(_B)
    await model.ainvoke([], _agent_output())
    session.state = _page(_A)
    await model.ainvoke([], _agent_output())

    assert "GO_BACK" in _offered(gateway)


# ---------------------------------------------------------------------------
# The plan
# ---------------------------------------------------------------------------


async def test_the_plan_is_asked_for_the_task_the_run_was_given() -> None:
    model, _, helper, _ = _model(_page(_A), [("WAIT", None)])

    await model.ainvoke([], _agent_output())

    ((_, context),) = helper.asked_with(PLAN_STEPS)
    assert context["goal"] == _TASK


async def test_a_model_given_a_browser_but_no_task_plans_on_no_invented_task() -> None:
    helper = FakeTextModel()
    model = JevChatModel(
        client=ScriptedGateway(script=[("WAIT", None)]),
        text_model=helper,
        structured_call=helper.structured,
    )  # type: ignore[arg-type]  # a scripted gateway and a fake text model stand in for the real ones
    model._browser = FakeSession(_page(_A))  # type: ignore[assignment]  # bound without a task, as test_chat_model's goal-fallback case is

    await model.ainvoke([], _agent_output())

    ((_, context),) = helper.asked_with(PLAN_STEPS)
    assert context["goal"] == ""


async def test_a_blank_part_the_writer_lists_is_not_a_part() -> None:
    writer, _, _ = _planner(
        [{"goal": "Read the top story"}, {"goal": "   "}, {"goal": "Search it"}]
    )
    model, gateway, _ = _writer_model(_page(_A), [("WAIT", None)], writer)

    await model.ainvoke([], _agent_output())

    assert "CURRENT PART (1 of 2)" in _goal(gateway)


async def test_a_run_without_a_plan_invents_no_part_name_for_its_finishing_step() -> None:
    helper = FakeTextModel(replies=[{"text": "Flights are listed."}])
    model, _, _ = _writer_model(_page(_A), [("DONE", None)], helper.structured)

    result = await model.ainvoke([], _agent_output())

    assert _action(result.completion)["done"]["success"] is True
    assert result.completion.next_goal is None


async def test_finishing_a_part_that_is_not_the_last_writes_no_closing_answer() -> None:
    writer = _evidence_writer(
        _TOP_STORY_PLAN, [{"requirement": "title", "kind": "fact", "source": _HN}], []
    )
    helper_calls: list[str] = []

    async def counting(schema, prompt, *, label, timeout=None, reasoning=None):
        helper_calls.append(prompt[0].content)
        return await writer(schema, prompt, label=label, timeout=timeout, reasoning=reasoning)

    _, gateway = await _run_to_done(
        _page(_HN, "TTS"),
        _page(_HN, "TTS"),
        [("WAIT", None), ("DONE", None), ("WAIT", None)],
        counting,
        _HN_TASK,
    )

    assert _on_part(gateway) == "2 of 2"
    assert not [c for c in helper_calls if c.startswith(DONE_SUMMARY)]


async def test_three_parts_are_worked_through_in_order() -> None:
    parts = [{"goal": "First"}, {"goal": "Second"}, {"goal": "Third"}]
    finished: set[str] = set()

    def judge(context, label):
        # Each of the first two parts is found done once; the third never is.
        part = next(
            p["goal"] for p in parts if f"only thing to do now: {p['goal']}" in context["goal"]
        )
        done = part != "Third" and part not in finished
        finished.add(part)
        return {
            "requirements": ["it"],
            "done": done,
            "evidence": [{"requirement": "it", "kind": "fact", "source": _A}],
            "findings": "",
        }

    writer, _, _ = _planner(parts, judge)
    model, gateway, _ = _writer_model(_page(_A), [("WAIT", None)] * 3, writer)
    await model.ainvoke([], _agent_output())
    await _settle()
    await model.ainvoke([], _agent_output())

    assert "CURRENT PART (3 of 3)" in _goal(gateway)
    assert "ALREADY DONE, never redo: First / Second" in _goal(gateway)


# ---------------------------------------------------------------------------
# Part judgements
# ---------------------------------------------------------------------------


async def test_the_judge_is_asked_about_the_part_the_run_is_on() -> None:
    writer, _, judged = _planner(_TOP_STORY_PLAN)
    model, _, _ = _writer_model(_page(_HN), [("WAIT", None)], writer)

    await model.ainvoke([], _agent_output())
    await _settle()

    assert judged and _TOP_STORY_PLAN[0]["goal"] in judged[0]["goal"]


async def test_a_page_already_judged_is_not_judged_again() -> None:
    writer, _, judged = _planner(_TOP_STORY_PLAN)
    model, _, _ = _writer_model(_page(_HN), [("WAIT", None), ("WAIT", None)], writer)

    await model.ainvoke([], _agent_output())
    await _settle()
    await model.ainvoke([], _agent_output())
    await _settle()

    assert len(judged) == 1


async def test_the_judge_sees_every_action_of_the_run_not_the_recent_few(monkeypatch) -> None:
    monkeypatch.setattr(chat_model_mod, "JEV_TEXT_HELPER_RECENT_ACTIONS", 1)
    writer, _, judged = _planner(_TOP_STORY_PLAN)
    model, _, session = _writer_model(_page(_HN), [("CLICK", "1")] * 3, writer)
    for url in (_A, _B):
        await model.ainvoke([], _agent_output())
        await _settle()
        session.state = _page(url, text=url)
    await model.ainvoke([], _agent_output())
    await _settle()

    assert len(judged[-1]["recent_actions"]) == 2


async def test_a_judge_that_fails_costs_the_step_nothing() -> None:
    def judge(context, label):
        raise RuntimeError("writer down")

    writer, _, _ = _planner(_TOP_STORY_PLAN, judge)
    model, _, _ = _writer_model(_page(_HN), [("WAIT", None), ("WAIT", None)], writer)
    await model.ainvoke([], _agent_output())
    await _settle()

    result = await model.ainvoke([], _agent_output())

    assert "wait" in _action(result.completion)


def _found(done: bool):
    """Judge the first part (only) with findings, done or not."""

    def judge(context, label):
        return {
            "requirements": ["title"],
            "done": done and "(1 of 2)" in context["goal"],
            "evidence": [{"requirement": "title", "kind": "fact", "source": _HN}],
            "findings": "  Gemini TTS, 217 points  ",
        }

    return judge


_SITELESS_PLAN = [{"goal": "Top story's title and points"}, {"goal": "Look the story up"}]


async def test_what_a_done_part_found_is_carried_into_the_next_part() -> None:
    writer, _, _ = _planner(_SITELESS_PLAN, _found(True))
    model, gateway, _ = _writer_model(_page(_HN), [("WAIT", None)] * 2, writer)
    await model.ainvoke([], _agent_output())
    await _settle()

    await model.ainvoke([], _agent_output())

    assert "CURRENT PART (2 of 2)" in _goal(gateway)
    assert "FOUND SO FAR, what the parts done produced: Part 1: Gemini TTS, 217 points" in _goal(
        gateway
    )


async def test_what_a_part_not_yet_done_found_is_not_reported_as_found() -> None:
    writer, _, _ = _planner(_SITELESS_PLAN, _found(False))
    model, gateway, _ = _writer_model(_page(_HN), [("WAIT", None)] * 2, writer)
    await model.ainvoke([], _agent_output())
    await _settle()

    await model.ainvoke([], _agent_output())

    assert "217 points" not in _goal(gateway)


async def test_a_bare_citation_of_an_action_the_run_took_is_evidence() -> None:
    writer = _evidence_writer(
        [{"goal": "Log in", "url": _LOGIN}],
        ["Enter your username and password and sign in."],
        [
            {"text": "Enter your username and password and sign in.", "category": "credentials"},
            {"text": "You logged into a secure area!"},
        ],
        requirements=[""],
    )

    action, _ = await _run_to_done(
        make_state({1: FakeNode("INPUT", {"name": "password"})}, url=_LOGIN),
        make_state({1: FakeNode("H2", text="Secure Area")}, url=_SECURE),
        [("REQUEST_HUMAN", None), ("DONE", None), ("WAIT", None)],
        writer,
        f"Go to {_LOGIN} and log me in; I'll type the password myself.",
    )

    assert action["done"]["success"] is True


class _HeldJudge:
    """Background judgements answer done only after Jev has chosen; the DONE check never confirms."""

    def __init__(self) -> None:
        self.helper = FakeTextModel(replies=[{"text": "Flights are listed."}])
        self.chosen = asyncio.Event()
        self.cancelled = False

    async def __call__(self, schema, prompt, *, label, timeout=None, reasoning=None):
        if not prompt[0].content.startswith(PART_DONE):
            return await self.helper.structured(schema, prompt, label=label, timeout=timeout)
        if label == "browser_done_check":
            return schema.model_validate({"done": False})
        await self.chosen.wait()
        await _settle()
        url = json.loads(prompt[1].content)["pages_read"][0]["url"]
        return schema.model_validate(
            {"requirements": ["it"], "done": True, "evidence": [url], "findings": ""}
        )


class _SignallingGateway(ScriptedGateway):
    def __init__(self, script, chosen: asyncio.Event) -> None:
        super().__init__(script=script)
        self.chosen = chosen

    async def evaluate(self, request):
        answer = await super().evaluate(request)
        self.chosen.set()
        return answer


async def test_a_done_on_the_pages_the_running_judgement_reads_waits_for_it() -> None:
    judge = _HeldJudge()
    model = JevChatModel(
        client=_SignallingGateway([("DONE", None), ("WAIT", None)], judge.chosen),
        text_model=FakeTextModel(),
        structured_call=judge,
    )  # type: ignore[arg-type]  # a scripted gateway and a fake text model stand in for the real ones
    model.bind(FakeSession(_page(_A)), _TASK)  # type: ignore[arg-type]  # a fake session stands in for Browser-Use's

    result = await asyncio.wait_for(model.ainvoke([], _agent_output()), timeout=1)

    assert _action(result.completion)["done"]["success"] is True


async def test_a_judgement_of_a_finished_part_is_stopped_when_the_part_advances() -> None:
    started = asyncio.Event()
    stopped: list[bool] = []
    helper = FakeTextModel()

    async def writer(schema, prompt, *, label, timeout=None, reasoning=None):
        if prompt[0].content.startswith(PLAN_STEPS):
            return schema.model_validate({"steps": _TOP_STORY_PLAN})
        if prompt[0].content.startswith(PART_DONE) and label != "browser_done_check":
            started.set()
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                stopped.append(True)
                raise
        if label == "browser_done_check":
            return schema.model_validate(
                {
                    "requirements": ["it"],
                    "done": True,
                    "evidence": [{"requirement": "it", "kind": "fact", "source": _HN}],
                    "findings": "",
                }
            )
        return await helper.structured(schema, prompt, label=label, timeout=timeout)

    model, _, session = _writer_model(
        _page(_HN), [("WAIT", None), ("DONE", None), ("WAIT", None)], writer
    )
    await asyncio.wait_for(model.ainvoke([], _agent_output()), timeout=1)
    await _settle()
    session.state = _page(_HN + "item?id=1", text="Article")

    await asyncio.wait_for(model.ainvoke([], _agent_output()), timeout=1)
    await _settle()

    assert started.is_set() and stopped == [True]


async def test_what_a_finished_part_lacked_is_not_asked_of_the_next_part() -> None:
    def judge(context, label):
        if "(2 of 2)" in context["goal"]:
            raise RuntimeError("writer down")
        if label == "browser_done_check":
            # Done on two citations, both of the title: the summary stays unevidenced.
            return {
                "requirements": ["title", "summary of its article"],
                "done": True,
                "evidence": [{"requirement": "title", "kind": "fact", "source": _HN}] * 2,
            }
        return {
            "requirements": ["title", "summary of its article"],
            "done": False,
            "evidence": [{"requirement": "title", "kind": "fact", "source": _HN}],
        }

    writer, _, _ = _planner(_SITELESS_PLAN, judge)
    model, gateway, _ = _writer_model(
        _page(_HN), [("WAIT", None), ("DONE", None)] + [("WAIT", None)] * 3, writer
    )
    await model.ainvoke([], _agent_output())
    await _settle()
    await model.ainvoke([], _agent_output())
    await _settle()
    await model.ainvoke([], _agent_output())

    assert "CURRENT PART (2 of 2)" in _goal(gateway)
    assert "summary of its article" not in _goal(gateway)


async def test_jev_is_shown_the_part_it_finished_among_its_recent_actions() -> None:
    long_goal = "Read the top story's title, its points and the first paragraph of its article " * 2
    parts = [{"goal": long_goal}, {"goal": "Look the story up"}]
    writer, _, _ = _planner(parts, _found(True))
    model, gateway, _ = _writer_model(_page(_HN), [("WAIT", None)] * 2, writer)
    await model.ainvoke([], _agent_output())
    await _settle()

    await model.ainvoke([], _agent_output())

    finished = [a for a in gateway.requests[-1].state["recent_actions"] if a["kind"] == "done_part"]
    assert [a["action"] for a in finished] == [f"DONE part 1: {long_goal.strip()[:80]}"]
