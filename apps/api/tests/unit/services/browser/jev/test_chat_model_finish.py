"""How a Jev run moves through its plan, what each step offers, and how it ends."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

from browser_use.llm.messages import UserMessage
from pydantic import BaseModel, RootModel
import pytest

from app.constants.browser import BROWSER_RUN_BLOCKED_SUMMARY, JevNoteSource
from app.services.browser.jev import chat_model as chat_model_mod
from app.services.browser.jev.chat_model import (
    JevChatModel,
    _citations,
    _discard,
    _goal_from_messages,
    _https_or_none,
    _PlanStep,
    _registered_actions,
    _same_page,
    _site_of,
    _stalled_operations,
    build_jev_chat_model,
)
from app.services.browser.jev.gateway import JevGatewayClient
from app.services.browser.jev.policy import JevHistoryEntry
from app.services.browser.jev.prompts import DONE_SUMMARY, PLAN_STEPS
from app.services.browser.jev.viewport import ViewportRead

from .conftest import FakeNode, make_state
from .test_chat_model import (
    FakeSession,
    FakeTextModel,
    ScriptedGateway,
    _action,
    _agent_output,
    _Judge,
    _model,
    _writer_model,
)

pytestmark = pytest.mark.unit

_HN = "https://news.ycombinator.com/"


def _entry(kind: str, *, changed: bool | None = False, **extra: object) -> JevHistoryEntry:
    return JevHistoryEntry(action=kind.upper(), kind=kind, page_changed=changed, **extra)  # type: ignore[arg-type]  # the test varies one optional field per case


def _offered(gateway: ScriptedGateway, request: int = -1) -> set[str]:
    return set(gateway.requests[request].questions["operation"].criteria)


def _planned(steps: list[dict[str, object]]):
    """Return a writer that plans steps and answers everything else like the fake helper."""
    helper = FakeTextModel()

    async def writer(schema, prompt, *, label, timeout=None, reasoning=None):
        if prompt[0].content.startswith(PLAN_STEPS):
            return schema.model_validate({"steps": steps})
        return await helper.structured(schema, prompt, label=label, timeout=timeout)

    return writer


# ---------------------------------------------------------------------------
# A part on a site of its own is opened by the plan, once
# ---------------------------------------------------------------------------


async def test_a_part_on_another_site_is_opened_outright_then_decided_there(flights_state) -> None:
    writer = _planned([{"goal": "Read the top story", "url": _HN}, {"goal": "Summarise it"}])
    model, gateway, _ = _writer_model(flights_state, [("WAIT", None)], writer)

    opened = await model.ainvoke([], _agent_output())
    await model.ainvoke([], _agent_output())

    assert _action(opened.completion) == {"navigate": {"url": _HN, "new_tab": False}}
    assert opened.completion.next_goal == f"NAVIGATE {_HN}"
    assert opened.completion.memory == f"Step 1: opening {_HN}"
    # Opened once: the next step on the same page is Jev's, and it knows the move it made.
    assert len(gateway.requests) == 1
    assert gateway.requests[0].state["recent_actions"] == [
        {
            "action": f"NAVIGATE {_HN}",
            "kind": "navigate",
            "text": _HN,
            "page_changed": False,
            "url": flights_state.url,
            "note": None,
        }
    ]


async def test_off_the_parts_site_navigate_is_offered_but_nothing_else_comes_back(
    flights_state,
) -> None:
    """The way back to the part's site is a navigate; a GO_BACK to the blank tab is still not."""
    writer = _planned([{"goal": "Read the top story", "url": _HN}, {"goal": "Summarise it"}])
    model, gateway, _ = _writer_model(flights_state, [("WAIT", None)], writer)
    await model.ainvoke([], _agent_output())

    await model.ainvoke([], _agent_output())

    offered = _offered(gateway)
    assert "NAVIGATE" in offered
    assert "GO_BACK" not in offered


async def test_off_the_parts_site_the_handoffs_the_user_declined_stay_off_the_table(
    flights_state,
) -> None:
    writer = _planned([{"goal": "Read the top story", "url": _HN}, {"goal": "Summarise it"}])
    model, gateway, _ = _writer_model(flights_state, [("WAIT", None)], writer)
    await model.ainvoke([], _agent_output())
    model.note_from_user("skip the login, just read the front page")

    await model.ainvoke([], _agent_output())

    offered = _offered(gateway)
    assert "NAVIGATE" in offered
    assert "REQUEST_HUMAN" not in offered


# ---------------------------------------------------------------------------
# What a step offers
# ---------------------------------------------------------------------------


async def test_a_navigate_that_found_no_url_is_not_offered_again_on_the_same_page(
    flights_state,
) -> None:
    model, gateway, _, _ = _model(flights_state, [("NAVIGATE", None), ("WAIT", None)], [{}])
    await model.ainvoke([], _agent_output())

    await model.ainvoke([], _agent_output())

    assert "NAVIGATE" not in _offered(gateway)
    assert "CLICK" in _offered(gateway)


async def test_a_navigate_that_found_no_url_is_offered_again_on_another_page(
    flights_state,
) -> None:
    model, gateway, _, session = _model(flights_state, [("NAVIGATE", None), ("WAIT", None)], [{}])
    await model.ainvoke([], _agent_output())
    session.state = make_state({1: FakeNode("A", text="Results")}, url="https://x/results")

    await model.ainvoke([], _agent_output())

    assert "NAVIGATE" in _offered(gateway)


async def test_a_navigate_that_went_out_leaves_navigate_on_offer(flights_state) -> None:
    model, gateway, _, _ = _model(
        flights_state, [("NAVIGATE", None), ("WAIT", None)], [{"text": "https://x/flights"}]
    )
    await model.ainvoke([], _agent_output())

    await model.ainvoke([], _agent_output())

    assert "NAVIGATE" in _offered(gateway)


async def test_a_rejected_decision_does_not_take_navigate_off_the_table(flights_state) -> None:
    """An answer naming no offered target is an error step, but not a navigate that found no URL."""
    model, gateway, _, _ = _model(flights_state, [("CLICK", "999"), ("WAIT", None)])
    await model.ainvoke([], _agent_output())

    await model.ainvoke([], _agent_output())

    assert gateway.requests[1].state["recent_actions"][0]["kind"] == "error"
    assert "NAVIGATE" in _offered(gateway)


async def test_the_bottom_of_a_page_takes_only_scroll_down_off_the_table(
    flights_state, monkeypatch
) -> None:
    async def bottom(*args: object) -> ViewportRead:
        return ViewportRead(text="", at_bottom=True)

    monkeypatch.setattr(chat_model_mod, "read_viewport", bottom)
    model, gateway, _, _ = _model(flights_state, [("WAIT", None)])

    await model.ainvoke([], _agent_output())

    offered = _offered(gateway)
    assert "SCROLL_DOWN" not in offered
    assert {"CLICK", "SCROLL_UP", "NAVIGATE"} <= offered


async def test_a_step_right_after_a_go_back_offers_no_second_one(flights_state) -> None:
    results = make_state({1: FakeNode("A", text="Results")}, url="https://x/results")
    more = make_state({1: FakeNode("A", text="More")}, url="https://x/more")
    model, gateway, _, session = _model(
        flights_state, [("CLICK", "4"), ("CLICK", "1"), ("GO_BACK", None), ("WAIT", None)]
    )
    await model.ainvoke([], _agent_output())
    session.state = results
    await model.ainvoke([], _agent_output())
    session.state = more
    await model.ainvoke([], _agent_output())
    assert "GO_BACK" in _offered(gateway)
    session.state = results

    await model.ainvoke([], _agent_output())

    assert "GO_BACK" not in _offered(gateway)


async def test_a_control_clicked_twice_for_nothing_is_no_longer_a_target(flights_state) -> None:
    model, gateway, _, _ = _model(
        flights_state, [("CLICK", "4"), ("WAIT", None), ("CLICK", "4"), ("WAIT", None)]
    )
    for _ in range(4):
        await model.ainvoke([], _agent_output())

    targets = set(gateway.requests[-1].questions["click_target"].criteria)
    assert "4" not in targets
    assert targets


# ---------------------------------------------------------------------------
# The goal Jev decides against when the task has parts
# ---------------------------------------------------------------------------


def _split_model(flights_state, index: int) -> JevChatModel:
    model, _, _, _ = _model(flights_state, [])
    model._plan = [_PlanStep(goal="Open HN"), _PlanStep(goal="Read #1"), _PlanStep(goal="Sum up")]
    model._plan_index = index
    return model


def _line(goal: str, prefix: str) -> str | None:
    return next((line for line in goal.split("\n") if line.startswith(prefix)), None)


async def test_the_part_in_progress_leads_and_the_parts_around_it_are_named(flights_state) -> None:
    model = _split_model(flights_state, 1)
    model._findings = ["Story: X", "Points: 217"]
    model._missing = (model._read_state(), ("the author", "the date"))

    goal = model._goal_with_plan("Summarise the top HN story")

    assert goal.split("\n")[0] == chat_model_mod._PART_CURRENT.format(
        part=2, parts=3, goal="Read #1"
    )
    assert _line(goal, chat_model_mod._PART_ALREADY_DONE) == (
        chat_model_mod._PART_ALREADY_DONE + "Open HN"
    )
    assert _line(goal, chat_model_mod._PART_STILL_TO_DO) == (
        chat_model_mod._PART_STILL_TO_DO + "Sum up"
    )
    found = _line(goal, chat_model_mod._PART_FOUND_SO_FAR)
    assert found is not None
    assert found.removeprefix(chat_model_mod._PART_FOUND_SO_FAR).split(" | ") == [
        "Story: X",
        "Points: 217",
    ]
    needed = _line(goal, chat_model_mod._PART_STILL_NEEDED)
    assert needed is not None
    assert needed.removeprefix(chat_model_mod._PART_STILL_NEEDED).split(" / ") == [
        "the author",
        "the date",
    ]
    assert goal.split("\n")[-1] == chat_model_mod._PART_DONE_MEANS.format(
        task="Summarise the top HN story"
    )


async def test_the_last_part_has_nothing_left_after_it(flights_state) -> None:
    goal = _split_model(flights_state, 2)._goal_with_plan("Summarise the top HN story")

    assert _line(goal, chat_model_mod._PART_STILL_TO_DO) is None
    assert _line(goal, chat_model_mod._PART_ALREADY_DONE) == (
        chat_model_mod._PART_ALREADY_DONE + "Open HN / Read #1"
    )


async def test_the_first_part_has_nothing_done_before_it(flights_state) -> None:
    goal = _split_model(flights_state, 0)._goal_with_plan("Summarise the top HN story")

    assert _line(goal, chat_model_mod._PART_ALREADY_DONE) is None
    assert _line(goal, chat_model_mod._PART_STILL_TO_DO) == (
        chat_model_mod._PART_STILL_TO_DO + "Read #1 / Sum up"
    )


async def test_what_an_earlier_parts_check_found_missing_is_not_asked_of_this_part(
    flights_state,
) -> None:
    model = _split_model(flights_state, 1)
    model._missing = (0, ("the author",))

    goal = model._goal_with_plan("Summarise the top HN story")

    assert _line(goal, chat_model_mod._PART_STILL_NEEDED) is None


async def test_a_check_that_found_nothing_missing_adds_no_line(flights_state) -> None:
    model = _split_model(flights_state, 1)
    model._missing = (1, ())

    goal = model._goal_with_plan("Summarise the top HN story")

    assert _line(goal, chat_model_mod._PART_STILL_NEEDED) is None


async def test_a_users_instruction_and_the_task_are_separate_lines_of_the_goal(
    flights_state,
) -> None:
    model, _, _, _ = _model(flights_state, [])
    model._history = [
        _entry("request_human", note="just read the title", note_source=JevNoteSource.USER)
    ]

    lines = model._effective_goal().split("\n")

    assert lines[0].endswith("just read the title")
    assert lines[-1].endswith("Fly Zurich to London")


# ---------------------------------------------------------------------------
# Finishing on the writer's judgement
# ---------------------------------------------------------------------------


async def test_a_run_the_writer_judged_done_finishes_named_after_its_part(flights_state) -> None:
    judge = _Judge(done=True)
    writer = judge

    async def planning(schema, prompt, *, label, timeout=None, reasoning=None):
        if prompt[0].content.startswith(PLAN_STEPS):
            return schema.model_validate({"steps": [{"goal": "List the fares"}]})
        return await writer(schema, prompt, label=label, timeout=timeout, reasoning=reasoning)

    model, _, _ = _writer_model(flights_state, [("CLICK", "4")], planning)
    await asyncio.wait_for(model.ainvoke([], _agent_output()), timeout=1)
    judge.release.set()
    for _ in range(20):
        await asyncio.sleep(0)

    result = await asyncio.wait_for(model.ainvoke([], _agent_output()), timeout=1)

    assert result.completion.next_goal == "List the fares"
    assert result.completion.memory == "Step 2: DONE"


async def test_a_run_with_no_bound_task_writes_its_answer_against_the_request_and_page(
    flights_state,
) -> None:
    judge = _Judge(done=True)
    model = JevChatModel(
        client=ScriptedGateway(script=[("CLICK", "4")]),
        text_model=judge.helper,
        structured_call=judge,
    )  # type: ignore[arg-type]  # a scripted gateway and a fake text model stand in for the real ones
    model._browser = FakeSession(flights_state)  # bound without a task
    messages = [UserMessage(content="<user_request>\nList the fares\n</user_request>")]
    await asyncio.wait_for(model.ainvoke(messages, _agent_output()), timeout=1)
    judge.release.set()
    for _ in range(20):
        await asyncio.sleep(0)

    result = await asyncio.wait_for(model.ainvoke(messages, _agent_output()), timeout=1)

    assert _action(result.completion)["done"]["success"] is True
    (context,) = [c for i, _, c in judge.helper.asked if i.startswith(DONE_SUMMARY)]
    assert context["goal"] == "List the fares"
    assert context["page"]["url"] == flights_state.url


# ---------------------------------------------------------------------------
# Resuming on a fresh browser
# ---------------------------------------------------------------------------


async def test_what_a_step_did_is_unknown_once_the_run_moved_to_a_fresh_browser(
    flights_state,
) -> None:
    """The new browser's page says nothing about what the old one's click changed."""
    model, gateway, _, _ = _model(flights_state, [("CLICK", "4"), ("WAIT", None)])
    model.fallback_available = True
    await model.ainvoke([], _agent_output())
    model.fall_back_after_engine_failure()
    model.continue_on_fallback()
    await model.ainvoke([], _agent_output())

    await model.ainvoke([], _agent_output())

    click = gateway.requests[-1].state["recent_actions"][0]
    assert click["kind"] == "click"
    assert click["page_changed"] is None


async def test_a_fresh_browser_has_no_photo_of_the_page_the_run_left(flights_state) -> None:
    model, _, _, _ = _model(flights_state, [("CLICK", "4")])
    model.fallback_available = True
    await model.ainvoke([], _agent_output())
    model.fall_back_after_engine_failure()

    model.continue_on_fallback()

    assert await model.take_step_screenshot() is None


async def test_a_stall_the_run_already_acted_on_is_not_a_stall_again(flights_state) -> None:
    model, _, _, _ = _model(flights_state, [])
    model._history = [_entry("click", url="https://x")] * chat_model_mod._STALLED_STEPS
    assert model._page_stalled() is True

    model._stall_handled_at = len(model._history)

    assert model._page_stalled() is False


# ---------------------------------------------------------------------------
# The small readers the loop leans on
# ---------------------------------------------------------------------------


def test_every_action_with_text_is_citable_by_its_action_its_text_or_both() -> None:
    history = [
        _entry("click"),
        JevHistoryEntry(action="TYPE_TEXT [2] To", kind="type_text", text=" London "),
    ]

    assert _citations(history) == {
        "CLICK",
        "TYPE_TEXT [2] To",
        "London",
        "TYPE_TEXT [2] To: London",
    }


def test_two_uses_of_an_operation_that_changed_nothing_take_it_off_the_table() -> None:
    assert _stalled_operations([_entry("click"), _entry("click")]) == {"CLICK"}
    assert _stalled_operations([_entry("wait"), _entry("click"), _entry("click")]) == {"CLICK"}


@pytest.mark.parametrize(
    "history",
    [
        [_entry("click")],
        [_entry("click", changed=True), _entry("click")],
        [_entry("click"), _entry("click", changed=True)],
        [_entry("click", changed=None), _entry("click")],
        [_entry("click"), _entry("scroll_down")],
        [_entry("scroll_down"), _entry("click"), _entry("click", changed=True)],
        [_entry("wait"), _entry("wait")],
        [_entry("error"), _entry("error")],
    ],
    ids=[
        "one-use",
        "first-changed",
        "last-changed",
        "first-unsettled",
        "different",
        "last-two-differ",
        "waits",
        "errors",
    ],
)
def test_an_operation_stays_on_the_table_unless_its_last_two_uses_changed_nothing(
    history,
) -> None:
    assert _stalled_operations(history) == frozenset()


def test_the_same_document_is_the_same_page_whatever_its_fragment() -> None:
    assert _same_page("https://a.test/doc#section-2", "https://a.test/doc") is True
    assert _same_page("https://a.test/other", "https://a.test/doc") is False


def test_a_site_is_its_host_whatever_the_case_or_www() -> None:
    assert _site_of("https://WWW.Example.com/a") == "example.com"
    assert _site_of("https://news.example.com/b") == "news.example.com"
    assert _site_of(None) == ""


def test_only_a_web_address_is_a_page_to_resume_on() -> None:
    assert _https_or_none(" http://a.test/x ") == "http://a.test/x"
    assert _https_or_none("HTTPS://a.test/") == "HTTPS://a.test/"
    assert _https_or_none("about:blank") is None
    assert _https_or_none(None) is None


def test_the_task_is_read_from_the_latest_user_request_past_messages_without_text() -> None:
    messages = [
        UserMessage(content="<user_request>\nOpen the article\n</user_request>"),
        SimpleNamespace(),
    ]

    assert _goal_from_messages(messages) == "Open the article"  # type: ignore[arg-type]  # a message with no text stands in for Browser-Use's image parts
    assert _goal_from_messages([]) == ""


async def test_dropping_finished_or_cancelled_work_never_raises() -> None:
    async def fails() -> None:
        raise RuntimeError("boom")

    failed = asyncio.create_task(fails())
    cancelled = asyncio.create_task(asyncio.Event().wait())
    await asyncio.sleep(0)
    cancelled.cancel()
    await asyncio.wait({failed, cancelled})

    _discard(failed)
    _discard(cancelled)
    _discard(None)

    assert cancelled.cancelled()


def test_the_actions_of_a_union_action_model_are_all_registered() -> None:
    class Go(BaseModel):
        go: dict[str, object]

    class Stop(BaseModel):
        stop: dict[str, object]

    class Actions(RootModel[Go | Stop]):
        pass

    class Output(BaseModel):
        action: list[Actions]

    assert _registered_actions(Output) == {"go", "stop"}


# ---------------------------------------------------------------------------
# Wiring
# ---------------------------------------------------------------------------


def test_build_hands_the_text_helper_and_the_users_metering_to_the_model(monkeypatch) -> None:
    monkeypatch.setattr(chat_model_mod.settings, "BROWSER_JEV_PROVIDER", "openrouter")
    monkeypatch.setattr(chat_model_mod.settings, "OPENROUTER_API_KEY", "sk-or-test")
    monkeypatch.setattr(chat_model_mod.settings, "BROWSER_JEV_VERCEL_API_KEY", None)
    helper = FakeTextModel()
    seen: dict[str, object] = {}

    async def ainvoke_structured(schema, prompt, *, label, config, options):
        seen["config"] = config
        return schema()

    monkeypatch.setattr(chat_model_mod, "ainvoke_structured", ainvoke_structured)
    model = build_jev_chat_model(text_model=helper, user_id="u1")  # type: ignore[arg-type]  # the test hands a fake text model in place of the real one

    class Empty(BaseModel):
        pass

    asyncio.run(model._structured_call(Empty, [], label="x"))

    assert model.text_model is helper
    assert seen["config"]["configurable"]["user_id"] == "u1"  # type: ignore[index]  # a RunnableConfig dict


def test_the_openrouter_gateway_runs_the_configured_model_on_its_key(monkeypatch) -> None:
    monkeypatch.setattr(chat_model_mod.settings, "BROWSER_JEV_PROVIDER", "openrouter")
    monkeypatch.setattr(chat_model_mod.settings, "OPENROUTER_API_KEY", "sk-or-test")
    monkeypatch.setattr(chat_model_mod.settings, "BROWSER_JEV_VERCEL_API_KEY", None)
    monkeypatch.setattr(chat_model_mod.settings, "BROWSER_USE_JEV_MODEL", "~typesafe/jev-test")

    model = build_jev_chat_model(text_model=FakeTextModel())  # type: ignore[arg-type]  # the test hands a fake text model in place of the real one

    client = model._client
    assert isinstance(client, JevGatewayClient)
    assert (client.provider, client.model) == ("openrouter", "~typesafe/jev-test")
    assert client._headers == {"Authorization": "Bearer sk-or-test"}


@pytest.mark.parametrize(
    ("provider", "message"),
    [
        ("vercel", chat_model_mod._NO_VERCEL_KEY),
        ("openrouter", chat_model_mod._NO_OPENROUTER_KEY),
    ],
)
def test_a_gateway_without_its_key_names_that_key(monkeypatch, provider, message) -> None:
    monkeypatch.setattr(chat_model_mod.settings, "BROWSER_JEV_PROVIDER", provider)
    monkeypatch.setattr(chat_model_mod.settings, "OPENROUTER_API_KEY", None)
    monkeypatch.setattr(chat_model_mod.settings, "BROWSER_JEV_VERCEL_API_KEY", None)

    with pytest.raises(chat_model_mod.BrowserUnavailableError) as raised:
        build_jev_chat_model(text_model=FakeTextModel())  # type: ignore[arg-type]  # the test hands a fake text model in place of the real one

    assert str(raised.value) == message


# ---------------------------------------------------------------------------
# A site that never loaded
# ---------------------------------------------------------------------------


async def test_the_site_named_is_the_one_whose_navigate_never_loaded_not_a_later_step(
    flights_state,
) -> None:
    flights_state.url = "about:blank"
    model, _, _, _ = _model(
        flights_state,
        [("NAVIGATE", None), ("WAIT", None), ("BLOCKED", None)],
        [{"text": "https://nowhere.invalid/"}],
    )
    await model.ainvoke([], _agent_output())
    await model.ainvoke([], _agent_output())

    result = await model.ainvoke([], _agent_output())

    assert _action(result.completion)["done"]["text"] == (
        "I couldn't open https://nowhere.invalid/: the page never loaded."
    )


async def test_a_blank_tab_with_no_navigate_behind_it_blocks_without_naming_a_site(
    flights_state,
) -> None:
    flights_state.url = "about:blank"
    model, _, _, _ = _model(flights_state, [("BLOCKED", None)])

    result = await model.ainvoke([], _agent_output())

    assert _action(result.completion)["done"] == {
        "text": BROWSER_RUN_BLOCKED_SUMMARY,
        "success": False,
        "files_to_display": [],
    }
