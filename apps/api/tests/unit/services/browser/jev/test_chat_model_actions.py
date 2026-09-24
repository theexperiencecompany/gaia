"""The Browser-Use action each Jev decision executes as, and what the writer is asked for it."""

from __future__ import annotations

from typing import Any

from browser_use.agent.views import ActionModel, AgentOutput
from browser_use.llm.messages import UserMessage
from browser_use.tools.views import (
    ClickElementActionIndexOnly,
    NoParamsAction,
    SelectDropdownOptionAction,
)
from pydantic import BaseModel, ConfigDict, create_model
import pytest

from app.constants.browser import (
    BROWSER_FALLBACK_PAGE_BLOCKED,
    JEV_CLOSING_ANSWER_HEDGE_SECONDS,
    JEV_CLOSING_ANSWER_TIMEOUT_SECONDS,
    JEV_MIN_DONE_CONFIDENCE,
    JEV_TEXT_HEDGE_SECONDS,
    JEV_TEXT_HELPER_RECENT_ACTIONS,
    JEV_TEXT_TIMEOUT_SECONDS,
    BrowserRunFailure,
    JevOperation,
)
from app.services.browser.jev import chat_model as chat_model_mod
from app.services.browser.jev.chat_model import JevChatModel
from app.services.browser.jev.policy import JevDecision, JevDecisionError
from app.services.browser.jev.prompts import (
    CAPTCHA_CHALLENGE,
    DONE_SUMMARY,
    GUIDANCE_REASON,
    PLAN_STEPS,
    TAKEOVER_REASON,
    TEXT_VALUE,
    URL_VALUE,
)
from tests.helpers import captured_wide_event

from .conftest import FakeNode, make_state
from .test_chat_model import (
    Captcha,
    FakeSession,
    FakeTextModel,
    ScriptedGateway,
    Takeover,
    _action,
    _model,
)

pytestmark = pytest.mark.unit

TASK = "Fly Zurich to London"


class _Strict(BaseModel):
    """An action's parameters with no defaults: every argument the loop relies on must be named."""

    model_config = ConfigDict(extra="forbid")


class StrictScroll(_Strict):
    down: bool
    pages: float


class StrictInput(_Strict):
    index: int
    text: str
    clear: bool


class StrictNavigate(_Strict):
    url: str
    new_tab: bool


class StrictDone(_Strict):
    text: str
    success: bool


class StrictWait(_Strict):
    seconds: int


class Guidance(_Strict):
    reason: str


def _strict_output(*, guidance: bool = False) -> type[AgentOutput]:
    """Return an AgentOutput whose parameters carry no defaults.

    Browser-Use's own defaults (scroll one page down, clear before typing, same
    tab, success=True) would otherwise stand in for anything the loop left out,
    and one upstream default change would silently alter what runs.
    """
    fields: dict[str, Any] = {
        "click": (ClickElementActionIndexOnly | None, None),
        "input_text": (StrictInput | None, None),
        "select_dropdown": (SelectDropdownOptionAction | None, None),
        "scroll": (StrictScroll | None, None),
        "wait": (StrictWait | None, None),
        "navigate": (StrictNavigate | None, None),
        "go_back": (NoParamsAction | None, None),
        "done": (StrictDone | None, None),
        "request_human_takeover": (Takeover | None, None),
        "solve_captcha_with_help": (Captcha | None, None),
    }
    if guidance:
        fields["request_agent_guidance"] = (Guidance | None, None)
    actions = create_model("StrictActionModel", __base__=ActionModel, **fields)
    return AgentOutput.type_with_custom_actions_flash_mode(actions)


class RecordingWriter(FakeTextModel):
    """The writer seam, also recording the label and deadline of every call it answers."""

    def __init__(self, replies: list[Any] | None = None, plan: list[dict[str, Any]] | None = None):
        super().__init__(replies=list(replies or []))
        self.plan = plan
        self.lanes: list[tuple[str, str, float | None]] = []

    async def structured(self, schema, prompt, *, label, timeout=None, reasoning=None):
        if self.plan is not None and prompt[0].content.startswith(PLAN_STEPS):
            return schema.model_validate({"steps": self.plan})
        self.lanes.append((prompt[0].content, label, timeout))
        return await super().structured(
            schema, prompt, label=label, timeout=timeout, reasoning=reasoning
        )

    def lane(self, instructions: str) -> tuple[str, float | None]:
        (found,) = [(label, t) for i, label, t in self.lanes if i.startswith(instructions)]
        return found

    def context_for(self, instructions: str) -> dict[str, Any]:
        (found,) = [c for _, c in self.asked_with(instructions)]
        return found


def _recorded(state, script, writer: RecordingWriter, *, task: str = TASK, guidance=None):
    gateway = ScriptedGateway(script=list(script))
    model = JevChatModel(client=gateway, text_model=writer, structured_call=writer.structured)  # type: ignore[arg-type]  # a scripted gateway and a fake writer stand in for the real ones
    session = FakeSession(state)
    model.bind(session, task, guidance)  # type: ignore[arg-type]  # a fake session stands in for Browser-Use's
    return model, gateway, session


# ---------------------------------------------------------------------------
# Every action names the arguments it relies on
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("script", "replies", "expected"),
    [
        ([("SCROLL_UP", None)], [], {"scroll": {"down": False, "pages": 1.0}}),
        ([("SCROLL_DOWN", None)], [], {"scroll": {"down": True, "pages": 1.0}}),
        (
            [("TYPE_TEXT", "2")],
            [{"text": "London"}],
            {"input_text": {"index": 23, "text": "London", "clear": True}},
        ),
        (
            [("NAVIGATE", None)],
            [{"text": "https://www.google.com/travel/flights"}],
            {"navigate": {"url": "https://www.google.com/travel/flights", "new_tab": False}},
        ),
        (
            [("DONE", None)],
            [{"text": "Flights are listed."}],
            {"done": {"text": "Flights are listed.", "success": True}},
        ),
    ],
)
async def test_every_action_names_each_argument_instead_of_leaning_on_browser_use_defaults(
    flights_state, script, replies, expected
) -> None:
    model, _, _, _ = _model(flights_state, script, replies)

    result = await model.ainvoke([], _strict_output())

    assert _action(result.completion) == expected


async def test_a_site_that_never_loaded_ends_the_run_as_failed(flights_state) -> None:
    flights_state.url = "about:blank"
    model, _, _, _ = _model(
        flights_state,
        [("NAVIGATE", None), ("BLOCKED", None)],
        [{"text": "https://nowhere.invalid/"}],
    )
    await model.ainvoke([], _strict_output())

    result = await model.ainvoke([], _strict_output())

    assert _action(result.completion)["done"]["success"] is False


async def test_a_never_loaded_site_is_recorded_as_the_runs_failure_reason(flights_state) -> None:
    flights_state.url = "about:blank"
    model, _, _, _ = _model(
        flights_state,
        [("NAVIGATE", None), ("BLOCKED", None)],
        [{"text": "https://nowhere.invalid/"}],
    )
    await model.ainvoke([], _strict_output())

    async with captured_wide_event() as event:
        await model.ainvoke([], _strict_output())

    assert event["browser"]["blocked"] == BrowserRunFailure.NEVER_OPENED.value


async def test_a_page_blocked_with_no_one_to_ask_is_recorded_as_blocked(flights_state) -> None:
    model, _, _, _ = _model(flights_state, [("BLOCKED", None)], [{"text": None}])

    async with captured_wide_event() as event:
        await model.ainvoke([], _strict_output())

    assert event["browser"]["blocked"] == BrowserRunFailure.BLOCKED.value


async def test_a_blocked_page_is_retried_once_on_the_fallback_engine(flights_state) -> None:
    model, _, _, _ = _model(flights_state, [("BLOCKED", None)])
    model.fallback_available = True

    async with captured_wide_event() as event:
        result = await model.ainvoke([], _strict_output())

    assert _action(result.completion)["done"]["success"] is False
    assert model.fallback_url == "https://x"
    assert event["browser"]["fallback_reason"] == BROWSER_FALLBACK_PAGE_BLOCKED


# ---------------------------------------------------------------------------
# NAVIGATE
# ---------------------------------------------------------------------------


async def test_navigate_accepts_a_plain_http_url(flights_state) -> None:
    model, _, _, _ = _model(flights_state, [("NAVIGATE", None)], [{"text": "http://neverssl.com"}])

    result = await model.ainvoke([], _strict_output())

    assert _action(result.completion) == {
        "navigate": {"url": "http://neverssl.com", "new_tab": False}
    }


async def test_navigate_to_the_page_already_open_loads_nothing(flights_state) -> None:
    """Browser-Use's wait(1) sleeps zero seconds; reloading the open page would spend a step on nothing."""
    model, _, _, _ = _model(flights_state, [("NAVIGATE", None)], [{"text": "https://x/"}])

    result = await model.ainvoke([], _strict_output())

    assert _action(result.completion) == {"wait": {"seconds": 1}}


async def test_navigate_off_the_parts_own_site_goes_back_to_it_without_asking_the_writer() -> None:
    """The plan already names the part's site: no URL answer is spent on it."""
    books = "https://books.toscrape.com/"
    writer = RecordingWriter(
        plan=[
            {"goal": "Find the cheapest book in Travel", "url": books},
            {"goal": "Look it up on Wikipedia", "url": "https://en.wikipedia.org/"},
        ]
    )
    start = make_state({40: FakeNode("BUTTON", text="Travel")}, url=books)
    model, _, session = _recorded(start, [("WAIT", None), ("NAVIGATE", None)], writer)
    await model.ainvoke([], _strict_output())
    session.state = make_state({40: FakeNode("BUTTON", text="Ad")}, url="https://ads.example/")

    result = await model.ainvoke([], _strict_output())

    assert _action(result.completion) == {"navigate": {"url": books, "new_tab": False}}
    assert writer.asked_with(URL_VALUE) == []


# ---------------------------------------------------------------------------
# What the writer is told for each value it writes
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("script", "reply", "instructions"),
    [
        ([("NAVIGATE", None)], {"text": "https://www.google.com"}, URL_VALUE),
        (
            [("REQUEST_HUMAN", None)],
            {"text": "Sign in", "category": "credentials"},
            TAKEOVER_REASON,
        ),
        ([("SOLVE_CAPTCHA", None)], {"text": "Pick the buses"}, CAPTCHA_CHALLENGE),
    ],
)
async def test_the_writer_writes_each_value_for_this_steps_goal_and_page(
    flights_state, script, reply, instructions
) -> None:
    writer = RecordingWriter([reply])
    model, _, _ = _recorded(flights_state, script, writer)

    await model.ainvoke([], _strict_output())

    context = writer.context_for(instructions)
    assert context["goal"] == TASK
    assert context["page"]["url"] == "https://x"


async def test_a_blocked_step_asks_the_planning_agent_with_this_steps_goal_and_page(
    flights_state,
) -> None:
    async def allowed() -> bool:
        return True

    writer = RecordingWriter([{"text": "The fares need a login."}])
    model, _, _ = _recorded(flights_state, [("BLOCKED", None)], writer, guidance=allowed)

    result = await model.ainvoke([], _strict_output(guidance=True))

    assert _action(result.completion) == {
        "request_agent_guidance": {"reason": "The fares need a login."}
    }
    context = writer.context_for(GUIDANCE_REASON)
    assert context["goal"] == TASK
    assert context["page"]["url"] == "https://x"


async def test_the_closing_answer_is_written_against_the_page_the_run_ended_on(
    flights_state,
) -> None:
    writer = RecordingWriter([{"text": "Flights are listed."}])
    model, _, _ = _recorded(flights_state, [("DONE", None)], writer)

    await model.ainvoke([], _strict_output())

    assert writer.context_for(DONE_SUMMARY)["page"]["url"] == "https://x"


async def test_a_blocked_run_reports_what_it_read_against_the_whole_task_not_its_part(
    flights_state,
) -> None:
    """Blocked in part 1 of 2, the answer is still for the task the user gave, every part of it."""
    writer = RecordingWriter(
        [{"text": "Found the fares page; no fares shown."}],
        plan=[{"goal": "Find the flights"}, {"goal": "Pick the cheapest"}],
    )
    model, _, _ = _recorded(flights_state, [("BLOCKED", None)], writer)

    result = await model.ainvoke([], _strict_output())

    assert _action(result.completion)["done"] == {
        "text": "Found the fares page; no fares shown.",
        "success": False,
    }
    context = writer.context_for(DONE_SUMMARY)
    assert context["goal"] == TASK
    assert context["page"]["url"] == "https://x"


@pytest.mark.parametrize("script", [[("DONE", None)], [("BLOCKED", None)]])
async def test_a_run_bound_without_a_task_answers_the_request_in_browser_uses_prompt(
    flights_state, script
) -> None:
    writer = RecordingWriter([{"text": "Flights are listed."}])
    model, _, _ = _recorded(flights_state, script, writer, task="")

    await model.ainvoke(
        [UserMessage(content="<user_request>Fly Basel to Rome</user_request>")], _strict_output()
    )

    assert writer.context_for(DONE_SUMMARY)["goal"] == "Fly Basel to Rome"


async def test_the_closing_answer_reads_the_whole_run_while_a_value_reads_the_last_few_steps(
    flights_state,
) -> None:
    steps = JEV_TEXT_HELPER_RECENT_ACTIONS + 2
    writer = RecordingWriter([{"text": "London"}, {"text": "Flights are listed."}])
    model, _, _ = _recorded(
        flights_state,
        [("SCROLL_DOWN", None)] * steps + [("TYPE_TEXT", "2"), ("DONE", None)],
        writer,
    )
    for _ in range(steps + 2):
        await model.ainvoke([], _strict_output())

    typed = writer.context_for(TEXT_VALUE)["recent_actions"]
    closing = writer.context_for(DONE_SUMMARY)["recent_actions"]
    assert len(typed) == JEV_TEXT_HELPER_RECENT_ACTIONS
    assert len(closing) == steps + 1
    assert typed == closing[-JEV_TEXT_HELPER_RECENT_ACTIONS - 1 : -1]
    assert closing[-1] == {
        "action": "TYPE_TEXT [2] Where to?",
        "text": "London",
        "page_changed": False,
    }


async def test_the_writer_is_told_the_users_latest_note_and_what_was_found_so_far(
    flights_state,
) -> None:
    writer = RecordingWriter([{"text": "London"}])
    model, _, _ = _recorded(flights_state, [("SCROLL_DOWN", None), ("TYPE_TEXT", "2")], writer)
    await model.ainvoke([], _strict_output())
    model.note_from_user("fly to London, not Paris")

    await model.ainvoke([], _strict_output())

    context = writer.context_for(TEXT_VALUE)
    assert context["latest_note"] == "fly to London, not Paris"
    assert context["findings"] == []


async def test_each_writer_call_runs_on_its_own_label_and_deadline(flights_state) -> None:
    """The closing answer reads every page read, so it gets the long deadline; a typed value does not."""
    writer = RecordingWriter([{"text": "London"}, {"text": "Flights are listed."}])
    model, _, _ = _recorded(flights_state, [("TYPE_TEXT", "2"), ("DONE", None)], writer)

    await model.ainvoke([], _strict_output())
    await model.ainvoke([], _strict_output())

    assert writer.lane(TEXT_VALUE) == ("browser_textvalue", JEV_TEXT_TIMEOUT_SECONDS)
    assert writer.lane(DONE_SUMMARY) == (
        "browser_closinganswer",
        JEV_CLOSING_ANSWER_TIMEOUT_SECONDS,
    )


async def test_the_closing_answer_waits_longer_before_hedging_than_a_typed_value(
    flights_state, monkeypatch
) -> None:
    budgets: dict[str, tuple[float, float]] = {}
    real_first_answer = chat_model_mod.first_answer

    async def recording_first_answer(call, *, hedge_after, deadline):
        result = await real_first_answer(call, hedge_after=hedge_after, deadline=deadline)
        budgets[type(result).__name__] = (hedge_after, deadline)
        return result

    monkeypatch.setattr(chat_model_mod, "first_answer", recording_first_answer)
    model, _, _, _ = _model(
        flights_state,
        [("TYPE_TEXT", "2"), ("DONE", None)],
        [{"text": "London"}, {"text": "Flights are listed."}],
    )

    await model.ainvoke([], _strict_output())
    await model.ainvoke([], _strict_output())

    assert budgets["_TextValue"] == (JEV_TEXT_HEDGE_SECONDS, JEV_TEXT_TIMEOUT_SECONDS)
    assert budgets["_ClosingAnswer"] == (
        JEV_CLOSING_ANSWER_HEDGE_SECONDS,
        JEV_CLOSING_ANSWER_TIMEOUT_SECONDS,
    )


# ---------------------------------------------------------------------------
# The closing answer and a typed value, at and over their caps
# ---------------------------------------------------------------------------


async def test_the_closing_answer_is_sent_without_surrounding_whitespace(flights_state) -> None:
    model, _, _, _ = _model(flights_state, [("DONE", None)], [{"text": "  Flights are listed.\n"}])

    result = await model.ainvoke([], _strict_output())

    assert _action(result.completion)["done"] == {"text": "Flights are listed.", "success": True}


async def test_a_blank_closing_answer_is_no_answer(flights_state) -> None:
    model, _, _, _ = _model(flights_state, [("DONE", None)], [{"text": "   "}])

    result = await model.ainvoke([], _strict_output())

    assert _action(result.completion)["done"] == {
        "text": chat_model_mod._NO_SUMMARY,
        "success": False,
    }


async def test_a_closing_answer_exactly_at_the_cap_is_sent(flights_state, monkeypatch) -> None:
    monkeypatch.setattr(chat_model_mod, "JEV_SUMMARY_MAX_CHARS", 5)
    model, _, _, _ = _model(flights_state, [("DONE", None)], [{"text": "Done."}])

    result = await model.ainvoke([], _strict_output())

    assert _action(result.completion)["done"]["text"] == "Done."


async def test_an_overlong_closing_answer_is_dropped_and_said_so_on_the_wide_event(
    flights_state, monkeypatch
) -> None:
    monkeypatch.setattr(chat_model_mod, "JEV_SUMMARY_MAX_CHARS", 5)
    model, _, _, _ = _model(flights_state, [("DONE", None)], [{"text": "Done now."}])

    async with captured_wide_event() as event:
        result = await model.ainvoke([], _strict_output())

    assert _action(result.completion)["done"]["success"] is False
    (warning,) = [w for w in event["warnings"] if "closing answer discarded" in w["msg"]]
    assert (warning["step"], warning["chars"], warning["cap"]) == (1, 9, 5)


async def test_a_typed_value_exactly_at_the_cap_is_typed(flights_state, monkeypatch) -> None:
    monkeypatch.setattr(chat_model_mod, "JEV_TEXT_VALUE_MAX_CHARS", 6)
    model, _, _, _ = _model(flights_state, [("TYPE_TEXT", "2")], [{"text": "London"}])

    result = await model.ainvoke([], _strict_output())

    assert _action(result.completion)["input_text"]["text"] == "London"


async def test_an_overlong_typed_value_is_explained_on_the_wide_event(
    flights_state, monkeypatch
) -> None:
    monkeypatch.setattr(chat_model_mod, "JEV_TEXT_VALUE_MAX_CHARS", 3)
    model, _, _, _ = _model(flights_state, [("TYPE_TEXT", "2")], [{"text": "London"}])

    async with captured_wide_event() as event:
        await model.ainvoke([], _strict_output())

    (warning,) = [w for w in event["warnings"] if "value discarded" in w["msg"]]
    assert (warning["step"], warning["chars"], warning["cap"]) == (1, 6, 3)


async def test_a_failing_writer_is_explained_with_its_error_cut_to_200_characters(
    flights_state,
) -> None:
    model, _, _, _ = _model(flights_state, [("TYPE_TEXT", "2")], [RuntimeError("x" * 300)])

    async with captured_wide_event() as event:
        await model.ainvoke([], _strict_output())

    (warning,) = [w for w in event["warnings"] if "text helper failed" in w["msg"]]
    assert warning["error"] == "x" * 200


# ---------------------------------------------------------------------------
# Choosing, and a decision with nothing to act on
# ---------------------------------------------------------------------------


async def test_a_done_exactly_at_the_confidence_floor_is_not_re_asked(flights_state) -> None:
    model, gateway, _, _ = _model(
        flights_state,
        [("DONE", None, JEV_MIN_DONE_CONFIDENCE)],
        [{"text": "Flights are listed."}],
    )

    result = await model.ainvoke([], _strict_output())

    assert "done" in _action(result.completion)
    assert len(gateway.requests) == 1


async def test_jev_and_its_re_ask_both_see_the_pages_already_read_and_the_goal(
    flights_state,
) -> None:
    model, gateway, _, _ = _model(flights_state, [("DONE", None), ("CLICK", "4")], confidence=0.49)

    await model.ainvoke([], _strict_output())

    first, re_ask = gateway.requests
    assert [p["url"] for p in first.state["pages_read"]] == ["https://x"]
    assert [p["url"] for p in re_ask.state["pages_read"]] == ["https://x"]
    assert re_ask.questions["operation"].instructions["goal"] == TASK


async def test_a_decision_with_nothing_to_act_on_fails_the_step_naming_the_operation(
    flights_state, monkeypatch
) -> None:
    async def choose(client, observation, goal, history, offered, pages_read=()):
        return JevDecision(operation=JevOperation.SELECT, element=observation.element(3))

    monkeypatch.setattr(chat_model_mod, "choose", choose)
    model, _, _, _ = _model(flights_state, [])

    with pytest.raises(JevDecisionError) as failure:
        await model.ainvoke([], _strict_output())

    assert str(failure.value) == "Jev chose SELECT without a usable target."


async def test_a_wait_after_another_action_on_the_page_starts_from_the_shortest_wait(
    flights_state,
) -> None:
    model, _, _, session = _model(flights_state, [("WAIT", None), ("CLICK", "4"), ("WAIT", None)])
    await model.ainvoke([], _strict_output())
    await model.ainvoke([], _strict_output())

    result = await model.ainvoke([], _strict_output())

    assert _action(result.completion) == {"wait": {"seconds": 4}}


async def test_a_wait_on_a_new_page_starts_from_the_shortest_wait(flights_state) -> None:
    model, _, _, session = _model(flights_state, [("WAIT", None), ("WAIT", None)])
    await model.ainvoke([], _strict_output())
    session.state = make_state(flights_state.dom_state.selector_map, url="https://x/results")

    result = await model.ainvoke([], _strict_output())

    assert _action(result.completion) == {"wait": {"seconds": 4}}


async def test_a_done_that_finishes_the_last_part_is_answered_against_the_page_it_ended_on(
    flights_state,
) -> None:
    """Part 1's DONE moves the run to part 2 on the same screen; its DONE writes the answer there."""
    writer = RecordingWriter(
        [{"text": "Both parts are done."}],
        plan=[{"goal": "Find the flights"}, {"goal": "Pick the cheapest"}],
    )
    model, _, _ = _recorded(flights_state, [("DONE", None), ("DONE", None)], writer)

    result = await model.ainvoke([], _strict_output())

    assert _action(result.completion)["done"] == {"text": "Both parts are done.", "success": True}
    assert writer.context_for(DONE_SUMMARY)["page"]["url"] == "https://x"
