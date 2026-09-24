"""Jev decisions become Browser-Use actions; everything else is delegated."""

from __future__ import annotations

import asyncio
import base64
import contextlib
from dataclasses import dataclass, field
import json
from types import SimpleNamespace
from typing import Any, Union, get_args
from unittest.mock import AsyncMock, MagicMock

from browser_use.agent.views import ActionModel, AgentOutput
from browser_use.llm.messages import UserMessage
from browser_use.llm.views import ChatInvokeCompletion
from browser_use.tools.views import (
    ClickElementActionIndexOnly,
    DoneAction,
    InputTextAction,
    NavigateAction,
    NoParamsAction,
    ScrollAction,
    SelectDropdownOptionAction,
)
from pydantic import BaseModel, RootModel, create_model
import pytest

from app.constants import browser as browser_constants
from app.constants.browser import (
    BROWSER_RUN_BLOCKED_SUMMARY,
    JEV_DONE_REASK_BUDGET,
    JevOperation,
)
from app.constants.llm import ReasoningLevel
from app.constants.log_tags import LogTag
from app.services.browser.exceptions import BrowserUnavailableError
from app.services.browser.jev import chat_model as chat_model_mod
from app.services.browser.jev.chat_model import JevChatModel, build_jev_chat_model
from app.services.browser.jev.gateway import (
    JevChoiceAnswer,
    JevEvaluation,
    JevFailoverClient,
    JevGatewayClient,
    JevUsage,
)
from app.services.browser.jev.prompts import (
    CAPTCHA_CHALLENGE,
    DONE_SUMMARY,
    GUIDANCE_REASON,
    PART_DONE,
    PLAN_STEPS,
    TAKEOVER_REASON,
    TEXT_VALUE,
    URL_VALUE,
)
from app.services.browser.jev.viewport import ViewportRead

from .conftest import FakeAXNode, FakeNode, make_state

pytestmark = pytest.mark.unit


class Takeover(BaseModel):
    reason: str
    category: str = "irreversible"


class Captcha(BaseModel):
    challenge: str


class Wait(BaseModel):
    seconds: int = 3


def _agent_output(
    *, captcha: bool = True, union: bool = False, input_name: str = "input_text"
) -> type[AgentOutput]:
    """Return the flash-mode AgentOutput Browser-Use builds for this codebase's registered tools.

    One optional field per action, or with union, 0.11's RootModel over single-field models.
    """
    fields: dict[str, Any] = {
        "click": (ClickElementActionIndexOnly | None, None),
        input_name: (InputTextAction | None, None),
        "select_dropdown": (SelectDropdownOptionAction | None, None),
        "scroll": (ScrollAction | None, None),
        "wait": (Wait | None, None),
        "navigate": (NavigateAction | None, None),
        "go_back": (NoParamsAction | None, None),
        "done": (DoneAction | None, None),
        "request_human_takeover": (Takeover | None, None),
    }
    if captcha:
        fields["solve_captcha_with_help"] = (Captcha | None, None)
    if union:
        members = [
            create_model(f"{name}ActionModel", __base__=ActionModel, **{name: (annotation, ...)})
            for name, (annotation, _) in fields.items()
        ]
        actions = RootModel[Union[tuple(members)]]  # type: ignore[misc]  # a dynamically built RootModel stands in for browser-use's action union
    else:
        actions = create_model("ActionModel", __base__=ActionModel, **fields)
    return AgentOutput.type_with_custom_actions_flash_mode(actions)


def _answer(choice: str, keys: list[str], confidence: float = 0.8) -> JevChoiceAnswer:
    rest = (1 - confidence) / (len(keys) - 1) if len(keys) > 1 else 0
    return JevChoiceAnswer(
        type="choice",
        choice=choice,
        probabilities={k: (confidence if k == choice else rest) for k in keys},
    )


@dataclass
class ScriptedGateway:
    """Answers each request from a script of (operation, target); records what it saw."""

    script: list[tuple[Any, ...]]
    model: str = "typesafe-ai/jev"
    requests: list[Any] = field(default_factory=list)
    confidence: float = 0.8
    costs: list[float | None] = field(default_factory=list)

    async def evaluate(self, request):
        self.requests.append(request)
        operation, target, *rest = self.script.pop(0)
        confidence = rest[0] if rest else self.confidence
        ops = list(request.questions["operation"].criteria)
        answers = {"operation": _answer(operation, ops, confidence)}
        if target is not None:
            head = f"{operation.lower()}_target"
            answers[head] = _answer(target, list(request.questions[head].criteria))
        metadata = None
        if self.costs:
            cost = self.costs.pop(0)
            metadata = {"gateway": {"cost": cost}} if cost is not None else None
        return JevEvaluation(
            answers=answers,
            usage=JevUsage(inputTokens=300, outputTokens=6),
            latency_ms=42,
            providerMetadata=metadata,
        )


@dataclass
class FakeTextModel:
    """The text helper: answers structured calls from a queue, records the prompts."""

    model: str = "text-helper"
    replies: list[dict[str, Any] | Exception] = field(default_factory=list)
    calls: list[tuple[list[Any], type[BaseModel] | None]] = field(default_factory=list)
    provider: str = "fake"
    name: str = "text-helper"
    #: How the DONE check answers: the part is done, cited by the page read.
    confirms_done: bool = True
    #: Every structured call as (instructions, reasoning asked for, context).
    asked: list[tuple[str, Any, dict[str, Any]]] = field(default_factory=list)

    def asked_with(self, instructions: str) -> list[tuple[Any, dict[str, Any]]]:
        return [(r, c) for i, r, c in self.asked if i.startswith(instructions)]

    async def ainvoke(self, messages, output_format=None, **kwargs):
        """Browser-Use's own calls, passed straight through the model."""
        self.calls.append((messages, output_format))
        reply = self.replies.pop(0) if self.replies else {}
        if isinstance(reply, Exception):
            raise reply
        if output_format is None:
            return ChatInvokeCompletion(completion="plain", usage=None)
        return ChatInvokeCompletion(completion=output_format.model_validate(reply), usage=None)

    async def structured(self, schema, prompt, *, label, timeout=None, reasoning=None):
        """Answer the loop's structured one-shots from the scripted queue (the writer seam)."""
        instructions = prompt[0].content
        self.asked.append((instructions, reasoning, json.loads(prompt[1].content)))
        # The loop's own housekeeping (a single-part plan, a part not yet done)
        # answers itself here so scripted replies stay for typed values.
        if instructions.startswith(PLAN_STEPS):
            return schema.model_validate({"steps": []})
        if instructions.startswith(PART_DONE):
            if label != "browser_done_check" or not self.confirms_done:
                return schema.model_validate({"done": False})
            pages = json.loads(prompt[1].content)["pages_read"]
            return schema.model_validate(
                {
                    "requirements": ["the page"],
                    "done": True,
                    "evidence": [pages[0]["url"]],
                    "findings": "",
                }
            )
        self.calls.append((prompt, schema))
        reply = self.replies.pop(0) if self.replies else {}
        if isinstance(reply, Exception):
            raise reply
        if "achieved" in schema.model_fields and isinstance(reply, dict):
            # A scripted closing answer achieves its goal unless the test says otherwise.
            reply = {"achieved": True, **reply}
        return schema.model_validate(reply)

    def system_prompt(self, call: int = 0) -> str:
        messages, _ = self.calls[call]
        return str(messages[0].content)

    def context(self, call: int = 0) -> dict[str, Any]:
        import json

        messages, _ = self.calls[call]
        return json.loads(str(messages[1].content))


class FakeSession:
    """The two things the policy asks the session for: the cached state and a DOM snapshot."""

    def __init__(self, state, snapshot: dict[str, Any] | None = None):
        self.state = state
        self.calls: list[dict[str, Any]] = []
        self.snapshot = snapshot or {"strings": [], "documents": []}

    async def get_browser_state_summary(self, **kwargs):
        self.calls.append(kwargs)
        return self.state

    async def get_or_create_cdp_session(self):
        snapshot = self.snapshot

        class _DOMSnapshot:
            async def captureSnapshot(self, params, session_id):
                return snapshot

        return SimpleNamespace(
            session_id="s",
            cdp_client=SimpleNamespace(send=SimpleNamespace(DOMSnapshot=_DOMSnapshot())),
        )


def _model(
    flights_state, script, replies=None, confidence: float = 0.8
) -> tuple[JevChatModel, ScriptedGateway, FakeTextModel, FakeSession]:
    gateway = ScriptedGateway(script=list(script), confidence=confidence)
    text_model = FakeTextModel(replies=list(replies or []))
    model = JevChatModel(
        client=gateway, text_model=text_model, structured_call=text_model.structured
    )  # type: ignore[arg-type]  # the test hands a fake gateway client and a fake text model in place of the real ones
    session = FakeSession(flights_state)
    model.bind(session, "Fly Zurich to London")  # type: ignore[arg-type]  # the test hands a fake session in place of Browser-Use's session
    return model, gateway, text_model, session


def _action(completion) -> dict[str, Any]:
    (action,) = completion.action
    return action.model_dump(exclude_none=True)


@pytest.mark.parametrize("union", [False, True])
async def test_a_click_decision_becomes_a_click_on_the_browser_index(flights_state, union) -> None:
    model, gateway, _, session = _model(flights_state, [("CLICK", "4")])

    result = await model.ainvoke([], _agent_output(union=union))

    assert _action(result.completion) == {"click": {"index": 40}}
    assert result.completion.next_goal == "CLICK [4] Search"
    assert result.completion.memory == "Step 1: CLICK [4] Search (p=0.80)"
    assert result.usage is not None
    assert (
        result.usage.prompt_tokens,
        result.usage.completion_tokens,
        result.usage.total_tokens,
    ) == (300, 6, 306)
    # The observation Browser-Use already took, no screenshot, no second DOM walk.
    assert session.calls == [{"cached": True, "include_screenshot": False}]
    assert gateway.requests[0].questions["operation"].instructions["goal"] == "Fly Zurich to London"


@pytest.mark.parametrize("union", [False, True])
async def test_only_operations_with_a_registered_action_are_offered(flights_state, union) -> None:
    model, gateway, _, _ = _model(flights_state, [("WAIT", None)])

    await model.ainvoke([], _agent_output(captcha=False, union=union))

    offered = set(gateway.requests[0].questions["operation"].criteria)
    assert "SOLVE_CAPTCHA" not in offered
    assert {
        "CLICK",
        "TYPE_TEXT",
        "SELECT",
        "REQUEST_HUMAN",
        "DONE",
        "BLOCKED",
        "NAVIGATE",
    } <= offered


async def test_type_text_asks_the_helper_for_the_value_then_types_it(flights_state) -> None:
    model, _, helper, _ = _model(flights_state, [("TYPE_TEXT", "2")], [{"text": "London"}])

    result = await model.ainvoke([], _agent_output())

    assert _action(result.completion) == {
        "input_text": {"index": 23, "text": "London", "clear": True}
    }
    assert helper.system_prompt() == TEXT_VALUE
    context = helper.context()
    assert context["goal"] == "Fly Zurich to London"
    assert context["field"] == {"label": "Where to?", "role": "combobox", "value": ""}
    assert context["page"]["url"] == "https://x"
    assert context["recent_actions"] == []


async def test_type_text_uses_browser_use_0_11s_input_action_name_when_that_is_registered(
    flights_state,
) -> None:
    model, gateway, _, _ = _model(flights_state, [("TYPE_TEXT", "2")], [{"text": "London"}])

    result = await model.ainvoke([], _agent_output(input_name="input", union=True))

    assert _action(result.completion) == {"input": {"index": 23, "text": "London", "clear": True}}
    assert "TYPE_TEXT" in gateway.requests[0].questions["operation"].criteria


async def test_a_value_the_helper_cannot_source_hands_the_field_to_the_human(flights_state) -> None:
    model, _, _, _ = _model(flights_state, [("TYPE_TEXT", "2")], [{"text": None}])

    result = await model.ainvoke([], _agent_output())

    assert _action(result.completion) == {
        "request_human_takeover": {"reason": "Enter the Where to?", "category": "irreversible"}
    }


@pytest.mark.regression
async def test_a_value_call_that_fails_idles_the_step_instead_of_handing_the_field_over(
    flights_state,
) -> None:
    model, _, _, _ = _model(flights_state, [("TYPE_TEXT", "2")], [RuntimeError("provider down")])

    result = await model.ainvoke([], _agent_output())

    assert _action(result.completion) == {"wait": {"seconds": 1}}


async def test_an_overlong_helper_value_is_treated_as_missing(flights_state, monkeypatch) -> None:
    monkeypatch.setattr("app.services.browser.jev.chat_model.JEV_TEXT_VALUE_MAX_CHARS", 3)
    model, _, _, _ = _model(flights_state, [("TYPE_TEXT", "2")], [{"text": "London"}])

    result = await model.ainvoke([], _agent_output())

    assert "request_human_takeover" in _action(result.completion)


async def test_select_becomes_select_dropdown_by_option_text(flights_state) -> None:
    model, _, helper, _ = _model(flights_state, [("SELECT", "3:2")])

    result = await model.ainvoke([], _agent_output())

    assert _action(result.completion) == {"select_dropdown": {"index": 31, "text": "Business"}}
    assert helper.calls == []


@pytest.mark.parametrize(
    ("operation", "expected"),
    [
        ("SCROLL_DOWN", {"scroll": {"down": True, "pages": 1.0}}),
        ("SCROLL_UP", {"scroll": {"down": False, "pages": 1.0}}),
        ("WAIT", {"wait": {"seconds": 4}}),
    ],
)
async def test_control_operations_map_without_the_helper(
    flights_state, operation, expected
) -> None:
    model, _, helper, _ = _model(flights_state, [(operation, None)])

    result = await model.ainvoke([], _agent_output())

    assert _action(result.completion) == expected
    assert helper.calls == []


async def test_navigate_takes_a_url_from_the_helper(flights_state) -> None:
    model, _, helper, _ = _model(
        flights_state, [("NAVIGATE", None)], [{"text": "https://www.google.com/travel/flights"}]
    )

    result = await model.ainvoke([], _agent_output())

    assert _action(result.completion) == {
        "navigate": {"url": "https://www.google.com/travel/flights", "new_tab": False}
    }
    assert helper.system_prompt() == URL_VALUE


@pytest.mark.parametrize(
    "reply", [{"text": None}, {"text": "javascript:alert(1)"}, {"text": "google.com"}]
)
async def test_navigate_without_an_http_url_waits_and_records_the_failure(
    flights_state, reply
) -> None:
    model, gateway, _, _ = _model(flights_state, [("NAVIGATE", None), ("WAIT", None)], [reply])

    first = await model.ainvoke([], _agent_output())
    await model.ainvoke([], _agent_output())

    assert _action(first.completion) == {"wait": {"seconds": 1}}
    (recent,) = gateway.requests[1].state["recent_actions"]
    assert recent["kind"] == "error"
    assert recent["text"] == "NAVIGATE needs a URL the goal implies; none found"


async def test_request_human_asks_the_helper_for_the_directive_and_category(flights_state) -> None:
    model, _, helper, _ = _model(
        flights_state,
        [("REQUEST_HUMAN", None)],
        [{"text": "Enter your password and sign in", "category": "credentials"}],
    )

    result = await model.ainvoke([], _agent_output())

    assert _action(result.completion) == {
        "request_human_takeover": {
            "reason": "Enter your password and sign in",
            "category": "credentials",
        }
    }
    assert helper.system_prompt() == TAKEOVER_REASON


async def test_a_failing_helper_still_hands_off_with_the_default_directive(
    flights_state, monkeypatch
) -> None:
    logger = MagicMock()
    monkeypatch.setattr(chat_model_mod, "log", logger)
    model, _, _, _ = _model(
        flights_state,
        [("REQUEST_HUMAN", None)],
        [RuntimeError("provider down")],
    )

    result = await model.ainvoke([], _agent_output())

    assert _action(result.completion) == {
        "request_human_takeover": {
            "reason": "Complete this step in the live browser",
            "category": "irreversible",
        }
    }
    failures = [c for c in logger.warning.call_args_list if "text helper failed" in c.args[0]]
    assert len(failures) == 1, "the writer's own lane retries; the loop logs the final failure once"
    assert failures[0].kwargs == {"error_type": "RuntimeError", "error": "provider down"}


async def test_solve_captcha_describes_the_challenge(flights_state) -> None:
    model, _, helper, _ = _model(
        flights_state, [("SOLVE_CAPTCHA", None)], [{"text": "Select all motorcycles, then Verify"}]
    )

    result = await model.ainvoke([], _agent_output())

    assert _action(result.completion) == {
        "solve_captcha_with_help": {"challenge": "Select all motorcycles, then Verify"}
    }
    assert helper.system_prompt() == CAPTCHA_CHALLENGE


async def test_done_reports_the_helpers_summary_of_the_page(flights_state) -> None:
    model, _, helper, _ = _model(
        flights_state, [("DONE", None)], [{"text": "Flights from Zurich to London are listed."}]
    )

    result = await model.ainvoke([], _agent_output())

    assert _action(result.completion) == {
        "done": {
            "text": "Flights from Zurich to London are listed.",
            "success": True,
            "files_to_display": [],
        }
    }
    assert helper.system_prompt() == DONE_SUMMARY


async def test_an_unconfident_done_is_re_asked_without_done_offered(flights_state) -> None:
    """Regression: DONE at p=0.49 finished the run and summarised whatever page was showing."""
    model, gateway, _, _ = _model(flights_state, [("DONE", None), ("CLICK", "4")], confidence=0.49)

    result = await model.ainvoke([], _agent_output())

    assert _action(result.completion) == {"click": {"index": 40}}
    assert "DONE" not in gateway.requests[1].questions["operation"].criteria
    assert "CLICK" in gateway.requests[1].questions["operation"].criteria


async def test_a_re_ask_that_only_finds_a_less_sure_wait_keeps_the_done(flights_state) -> None:
    """Two re-asks that surfaced WAIT at p=0.30 cost 12 s on a long page and changed nothing."""
    model, gateway, _, _ = _model(
        flights_state,
        [("DONE", None, 0.5), ("WAIT", None, 0.3)],
        [{"text": "The article says 2008."}],
    )

    result = await model.ainvoke([], _agent_output())

    assert "done" in _action(result.completion)
    assert len(gateway.requests) == 2


async def test_a_confident_done_is_never_re_asked(flights_state) -> None:
    model, gateway, _, _ = _model(
        flights_state, [("DONE", None)], [{"text": "The article says 2008."}], confidence=0.8
    )

    result = await model.ainvoke([], _agent_output())

    assert _action(result.completion)["done"]["success"] is True
    assert len(gateway.requests) == 1


async def test_a_later_unconfident_done_is_re_asked_too_while_the_budget_holds(
    flights_state,
) -> None:
    """Regression: a re-ask on step 4 made step 5's DONE at p=0.52 acceptable and it shipped."""
    model, _, _, _ = _model(
        flights_state,
        [("DONE", None), ("CLICK", "4"), ("DONE", None), ("CLICK", "4")],
        [{"text": "The article says 2008."}],
        confidence=0.49,
    )

    await model.ainvoke([], _agent_output())
    result = await model.ainvoke([], _agent_output())

    assert _action(result.completion) == {"click": {"index": 40}}


async def test_an_unconfident_done_is_accepted_once_the_re_ask_budget_is_spent(
    flights_state,
) -> None:
    """Re-asking forever would loop; the budget is per run, not per consecutive step."""
    script = [("DONE", None), ("CLICK", "4")] * JEV_DONE_REASK_BUDGET + [("DONE", None)]
    model, _, _, _ = _model(
        flights_state, script, [{"text": "The article says 2008."}], confidence=0.49
    )

    for _ in range(JEV_DONE_REASK_BUDGET):
        await model.ainvoke([], _agent_output())
    result = await model.ainvoke([], _agent_output())

    assert _action(result.completion)["done"] == {
        "text": "The article says 2008.",
        "success": True,
        "files_to_display": [],
    }


async def test_done_without_a_summary_is_an_honest_failure(flights_state) -> None:
    """The pages were read but no answer could be written: never a success the user never gets."""
    model, _, _, _ = _model(flights_state, [("DONE", None)], [{"text": None}])

    result = await model.ainvoke([], _agent_output())

    done = _action(result.completion)["done"]
    assert done["success"] is False
    assert done["text"] == "I read the pages but could not write the closing answer."


async def test_the_closing_summary_reads_every_screen_of_the_page_not_just_the_last(
    flights_state,
) -> None:
    """Regression: DONE named a 36.94 book because the cheapest had already scrolled off screen."""
    model, _, helper, session = _model(
        flights_state,
        [("SCROLL_DOWN", None), ("DONE", None)],
        [{"text": "The cheapest is The Road to Little Dribbling at 23.21."}],
    )
    await model.ainvoke([], _agent_output())

    session.state = make_state({1: FakeNode("DIV", text="The Road to Little Dribbling 23.21")})
    await model.ainvoke([], _agent_output())

    seen = helper.context(0)["seen_on_pages_read"]
    assert "Search" in seen
    assert "The Road to Little Dribbling 23.21" in seen


async def test_the_summary_memory_keeps_every_page_read_under_its_url(flights_state) -> None:
    """A task that reads several pages is answered from all of them, not the last one."""
    model, _, helper, session = _model(
        flights_state, [("CLICK", "4"), ("DONE", None)], [{"text": "Order confirmed."}]
    )
    await model.ainvoke([], _agent_output())

    session.state = make_state({1: FakeNode("H1", text="Form submitted")}, url="https://x/thanks")
    await model.ainvoke([], _agent_output())

    seen = helper.context(0)["seen_on_pages_read"]
    assert seen.index("## https://x\n") < seen.index("Search") < seen.index("## https://x/thanks\n")
    assert "Form submitted" in seen


async def test_history_carries_page_changed_and_typed_text_into_the_next_request(
    flights_state,
) -> None:
    model, gateway, _, _ = _model(
        flights_state,
        [("TYPE_TEXT", "2"), ("CLICK", "4"), ("DONE", None)],
        [{"text": "London"}, {"text": "ok"}],
    )

    await model.ainvoke([], _agent_output())
    flights_state.dom_state.selector_map[23].attributes["value"] = "London"
    await model.ainvoke([], _agent_output())
    await model.ainvoke([], _agent_output())

    assert gateway.requests[1].state["recent_actions"] == [
        {
            "action": "TYPE_TEXT [2] Where to?",
            "kind": "type_text",
            "text": "London",
            "page_changed": True,
            "url": "https://x",
            "note": None,
        }
    ]
    assert gateway.requests[2].state["recent_actions"][1] == {
        "action": "CLICK [4] Search",
        "kind": "click",
        "text": None,
        "page_changed": False,
        "url": "https://x",
        "note": None,
    }


async def test_an_invalid_jev_answer_executes_nothing_but_a_wait(
    flights_state, monkeypatch
) -> None:
    logger = MagicMock()
    monkeypatch.setattr(chat_model_mod, "log", logger)

    class BadGateway(ScriptedGateway):
        async def evaluate(self, request):
            self.requests.append(request)
            return JevEvaluation(
                answers={
                    "operation": JevChoiceAnswer(type="choice", choice="NOPE", probabilities={})
                }
            )

    gateway = BadGateway(script=[])
    model = JevChatModel(
        client=gateway, text_model=(fake := FakeTextModel()), structured_call=fake.structured
    )  # type: ignore[arg-type]  # the test hands a fake gateway client and a fake text model in place of the real ones
    model.bind(FakeSession(flights_state), "g")  # type: ignore[arg-type]  # the test hands a fake session in place of Browser-Use's session

    result = await model.ainvoke([], _agent_output())

    assert _action(result.completion) == {"wait": {"seconds": 1}}
    assert result.usage is None
    rejected = [c for c in logger.warning.call_args_list if "Jev decision rejected" in c.args[0]]
    assert len(rejected) == 1
    assert rejected[0].args[0].startswith(f"{LogTag.BROWSER} Jev decision rejected")
    assert rejected[0].kwargs == {
        "error_type": "JevDecisionError",
        "error": "Invalid Jev response; no action executed.",
    }


async def test_calls_that_are_not_a_step_decision_go_to_the_text_helper(flights_state) -> None:
    class Extract(BaseModel):
        title: str

    model, gateway, helper, _ = _model(flights_state, [], [{"title": "T"}])
    messages = [UserMessage(content="extract")]

    structured = await model.ainvoke(messages, Extract)
    plain = await model.ainvoke(messages)

    assert structured.completion == Extract(title="T")
    assert plain.completion == "plain"
    assert [call[1] for call in helper.calls] == [Extract, None]
    assert gateway.requests == []


async def test_an_unbound_model_cannot_decide(flights_state) -> None:
    model = JevChatModel(
        client=ScriptedGateway(script=[]),
        text_model=(fake := FakeTextModel()),
        structured_call=fake.structured,
    )  # type: ignore[arg-type]  # the test hands a fake gateway client and a fake text model in place of the real ones

    with pytest.raises(BrowserUnavailableError, match="no browser session bound"):
        await model.ainvoke([], _agent_output())


async def test_the_goal_falls_back_to_browser_uses_own_user_request_block(flights_state) -> None:
    gateway = ScriptedGateway(script=[("WAIT", None)])
    model = JevChatModel(
        client=gateway, text_model=(fake := FakeTextModel()), structured_call=fake.structured
    )  # type: ignore[arg-type]  # the test hands a fake gateway client and a fake text model in place of the real ones
    model._browser = FakeSession(flights_state)  # bound without a task
    messages = [
        UserMessage(content="<user_request>\nOpen the article\n</user_request>\n<browser_state>x")
    ]

    await model.ainvoke(messages, _agent_output())

    assert gateway.requests[0].questions["operation"].instructions["goal"] == "Open the article"


def test_build_requires_the_gateway_key(monkeypatch) -> None:
    monkeypatch.setattr("app.services.browser.jev.chat_model.settings.OPENROUTER_API_KEY", None)

    with pytest.raises(BrowserUnavailableError, match="OPENROUTER_API_KEY"):
        build_jev_chat_model(text_model=FakeTextModel())  # type: ignore[arg-type]  # the test hands a fake text model in place of the real one


def test_build_vercel_uses_the_evaluate_endpoint(monkeypatch) -> None:
    monkeypatch.setattr(
        "app.services.browser.jev.chat_model.settings.BROWSER_JEV_PROVIDER", "vercel"
    )
    monkeypatch.setattr(
        "app.services.browser.jev.chat_model.settings.BROWSER_JEV_VERCEL_API_KEY", "vck-test"
    )

    monkeypatch.setattr("app.services.browser.jev.chat_model.settings.OPENROUTER_API_KEY", None)

    model = build_jev_chat_model(text_model=FakeTextModel())  # type: ignore[arg-type]  # the test hands a fake text model in place of the real one

    assert model.provider == "vercel"
    assert model.model == "typesafe-ai/jev"
    assert isinstance(model._client, JevGatewayClient), "no other key, so no fallback"
    assert model._client._url == "https://ai-gateway.vercel.sh/v1/evaluate"
    assert model._client._headers == {"Authorization": "Bearer vck-test"}


def test_build_wires_the_other_gateway_as_fallback_when_its_key_exists(monkeypatch) -> None:
    monkeypatch.setattr(
        "app.services.browser.jev.chat_model.settings.BROWSER_JEV_PROVIDER", "vercel"
    )
    monkeypatch.setattr(
        "app.services.browser.jev.chat_model.settings.BROWSER_JEV_VERCEL_API_KEY", "vck-test"
    )
    monkeypatch.setattr(
        "app.services.browser.jev.chat_model.settings.OPENROUTER_API_KEY", "sk-or-test"
    )

    model = build_jev_chat_model(text_model=FakeTextModel())  # type: ignore[arg-type]  # the test hands a fake text model in place of the real one

    assert model.provider == "vercel"
    assert isinstance(model._client, JevFailoverClient)
    assert model._client.primary.provider == "vercel"
    assert model._client.fallback.provider == "openrouter"
    assert model._client.fallback._url == "https://openrouter.ai/api/alpha/decisions"


def test_build_openrouter_falls_back_to_vercel_when_its_key_exists(monkeypatch) -> None:
    monkeypatch.setattr(
        "app.services.browser.jev.chat_model.settings.BROWSER_JEV_PROVIDER", "openrouter"
    )
    monkeypatch.setattr(
        "app.services.browser.jev.chat_model.settings.OPENROUTER_API_KEY", "sk-or-test"
    )
    monkeypatch.setattr(
        "app.services.browser.jev.chat_model.settings.BROWSER_JEV_VERCEL_API_KEY", "vck-test"
    )

    model = build_jev_chat_model(text_model=FakeTextModel())  # type: ignore[arg-type]  # the test hands a fake text model in place of the real one

    assert model.provider == "openrouter"
    assert isinstance(model._client, JevFailoverClient)
    assert model._client.fallback.provider == "vercel"


def test_build_vercel_requires_its_key(monkeypatch) -> None:
    monkeypatch.setattr(
        "app.services.browser.jev.chat_model.settings.BROWSER_JEV_PROVIDER", "vercel"
    )
    monkeypatch.setattr(
        "app.services.browser.jev.chat_model.settings.BROWSER_JEV_VERCEL_API_KEY", None
    )

    with pytest.raises(BrowserUnavailableError, match="BROWSER_JEV_VERCEL_API_KEY"):
        build_jev_chat_model(text_model=FakeTextModel())  # type: ignore[arg-type]  # the test hands a fake text model in place of the real one


async def test_gateway_costs_accumulate_across_decisions(flights_state) -> None:
    gateway = ScriptedGateway(script=[("CLICK", "4"), ("CLICK", "4")], costs=[0.0, 0.0])
    model = JevChatModel(
        client=gateway, text_model=(fake := FakeTextModel()), structured_call=fake.structured
    )  # type: ignore[arg-type]  # the test hands a fake gateway client and a fake text model in place of the real ones
    session = FakeSession(flights_state)
    model.bind(session, "Fly Zurich to London")  # type: ignore[arg-type]  # the test hands a fake session in place of Browser-Use's session

    await model.ainvoke([], _agent_output())
    await model.ainvoke([], _agent_output())

    assert model.actual_cost_usd == 0.0


async def test_cost_blind_decision_clears_the_actual_total(flights_state) -> None:
    gateway = ScriptedGateway(script=[("CLICK", "4"), ("CLICK", "4")], costs=[0.0, None])
    model = JevChatModel(
        client=gateway, text_model=(fake := FakeTextModel()), structured_call=fake.structured
    )  # type: ignore[arg-type]  # the test hands a fake gateway client and a fake text model in place of the real ones
    session = FakeSession(flights_state)
    model.bind(session, "Fly Zurich to London")  # type: ignore[arg-type]  # the test hands a fake session in place of Browser-Use's session

    await model.ainvoke([], _agent_output())
    assert model.actual_cost_usd == 0.0
    await model.ainvoke([], _agent_output())
    assert model.actual_cost_usd is None


async def test_every_operation_has_a_mapping(flights_state) -> None:
    """A new JevOperation member without an action mapping would raise mid-run."""
    for operation in JevOperation:
        target = {"CLICK": "4", "TYPE_TEXT": "2", "SELECT": "3:1"}.get(operation.value)
        model, _, _, _ = _model(
            flights_state,
            [(operation.value, target)],
            [{"text": "https://x/y", "category": "payment"}],
        )
        result = await model.ainvoke([], _agent_output())
        assert result.completion.action


async def test_a_rejected_decision_on_the_done_only_last_step_fails_the_run_honestly(
    flights_state, monkeypatch
) -> None:
    """Confirm the schema is narrowed to done on the final step, so wait is correctly rejected."""
    monkeypatch.setattr(chat_model_mod, "log", MagicMock())

    class BadGateway(ScriptedGateway):
        async def evaluate(self, request):
            return JevEvaluation(
                answers={
                    "operation": JevChoiceAnswer(type="choice", choice="NOPE", probabilities={})
                }
            )

    done_only = AgentOutput.type_with_custom_actions_flash_mode(
        create_model("ActionModel", __base__=ActionModel, done=(DoneAction | None, None))
    )
    model = JevChatModel(
        client=BadGateway(script=[]),
        text_model=(fake := FakeTextModel()),
        structured_call=fake.structured,
    )  # type: ignore[arg-type]  # the test hands a fake gateway client and a fake text model in place of the real ones
    model.bind(FakeSession(flights_state), "g")  # type: ignore[arg-type]  # the test hands a fake session in place of Browser-Use's session

    result = await model.ainvoke([], done_only)

    assert _action(result.completion)["done"]["success"] is False
    assert result.completion.next_goal == "DONE"


async def test_typed_text_shows_up_as_the_fields_live_value_on_the_next_step(flights_state) -> None:
    """The HTML value attribute never changes when the agent types; the DOM snapshot does."""
    gateway = ScriptedGateway(script=[("WAIT", None)])
    model = JevChatModel(
        client=gateway, text_model=(fake := FakeTextModel()), structured_call=fake.structured
    )  # type: ignore[arg-type]  # the test hands a fake gateway client and a fake text model in place of the real ones
    for index, node in flights_state.dom_state.selector_map.items():
        node.backend_node_id = index
    snapshot = {
        "strings": ["London"],
        "documents": [
            {"nodes": {"backendNodeId": [1, 23, 31], "inputValue": {"index": [1], "value": [0]}}}
        ],
    }
    model.bind(FakeSession(flights_state, snapshot), "g")  # type: ignore[arg-type]  # the test hands a fake session in place of Browser-Use's session

    await model.ainvoke([], _agent_output())

    elements = {e["label"]: e for e in gateway.requests[0].state["elements"]}
    assert elements["Where to?"]["value"] == "London"


async def test_a_takeover_note_amends_the_goal_jev_decides_against(flights_state) -> None:
    """Regression: the note only sat in recent_actions, so Jev kept handing off on the login page."""
    model, gateway, helper, _ = _model(
        flights_state,
        [("REQUEST_HUMAN", None), ("TYPE_TEXT", "2")],
        [
            {"text": "Enter your password and sign in", "category": "credentials"},
            {"text": "London"},
        ],
    )
    await model.ainvoke([], _agent_output())

    model.note_from_user("skip the login, just tell me the page title")
    await model.ainvoke([], _agent_output())

    goal = gateway.requests[1].questions["operation"].instructions["goal"]
    assert goal.startswith(
        "Latest instruction from the user, which overrides the task below: "
        "skip the login, just tell me the page title"
    )
    assert "Original task: Fly Zurich to London" in goal
    assert helper.context(1)["goal"] == goal


async def test_the_closing_answer_is_written_against_the_latest_instruction(flights_state) -> None:
    """Regression: DONE reported the original task as unfinished instead of answering the note."""
    model, _, helper, _ = _model(
        flights_state,
        [("REQUEST_HUMAN", None), ("DONE", None)],
        [
            {"text": "Sign in to continue", "category": "credentials"},
            {"text": "The page title is Flights."},
        ],
    )
    await model.ainvoke([], _agent_output())

    model.note_from_user("skip the login, just tell me the page title")
    await model.ainvoke([], _agent_output())

    assert helper.system_prompt(1) == DONE_SUMMARY
    assert helper.context(1)["goal"].startswith(
        "Latest instruction from the user, which overrides the task below: "
        "skip the login, just tell me the page title"
    )
    assert "Original task: Fly Zurich to London" in helper.context(1)["goal"]
    # The page the answer must be read off is still in the helper's context.
    assert set(helper.context(1)["page"]) == {"title", "url", "text"}


async def test_a_takeover_the_user_answered_takes_the_handoffs_off_the_table(
    flights_state,
) -> None:
    """Regression: Jev re-requested the same login wall 3s after the user answered it."""
    model, gateway, _, _ = _model(
        flights_state,
        [("REQUEST_HUMAN", None), ("CLICK", "4"), ("SCROLL_DOWN", None)],
        [{"text": "Sign in to your Reddit account", "category": "credentials"}],
    )
    await model.ainvoke([], _agent_output())

    model.note_from_user("skip the upvote, just tell me the title of the top post")
    await model.ainvoke([], _agent_output())
    await model.ainvoke([], _agent_output())

    for request in gateway.requests[1:]:
        offered = set(request.questions["operation"].criteria)
        assert "REQUEST_HUMAN" not in offered
        assert "SOLVE_CAPTCHA" not in offered
        assert "CLICK" in offered


@pytest.mark.parametrize("note", [None, ""])
async def test_a_takeover_resolved_without_an_instruction_keeps_the_handoffs(
    flights_state, note
) -> None:
    """The user just signed in and pressed Continue; a later, different wall may still need them."""
    model, gateway, _, _ = _model(
        flights_state,
        [("REQUEST_HUMAN", None), ("CLICK", "4")],
        [{"text": "Sign in to your Reddit account", "category": "credentials"}],
    )
    await model.ainvoke([], _agent_output())

    model.note_from_user(note)
    await model.ainvoke([], _agent_output())

    offered = set(gateway.requests[1].questions["operation"].criteria)
    assert {"REQUEST_HUMAN", "SOLVE_CAPTCHA"} <= offered


async def test_a_note_with_no_step_to_carry_it_is_a_wiring_error(flights_state) -> None:
    model, _, _, _ = _model(flights_state, [])

    with pytest.raises(RuntimeError, match="No step to attach a note to"):
        model.note_from_user("skip the login, just grab the photo")


# ---------------------------------------------------------------------------
# Agent guidance: a blocked step asks the agent that started the run
# ---------------------------------------------------------------------------


def _gate(allowed: bool):
    async def _allowed() -> bool:
        return allowed

    return _allowed


def _guided_model(flights_state, script, replies=None, allowed: bool = True):
    gateway = ScriptedGateway(script=list(script))
    text_model = FakeTextModel(replies=list(replies or []))
    model = JevChatModel(
        client=gateway, text_model=text_model, structured_call=text_model.structured
    )  # type: ignore[arg-type]  # the test hands a fake gateway client and a fake text model in place of the real ones
    model.bind(FakeSession(flights_state), "Fly Zurich to London", _gate(allowed))  # type: ignore[arg-type]  # the test hands a fake session in place of Browser-Use's session
    return model, gateway, text_model


def _guidance_output() -> type[AgentOutput]:
    """Return the AgentOutput of a run whose tools include the agent-guidance action."""
    base = _agent_output()
    fields: dict[str, Any] = {
        name: (annotation.annotation, None)
        for name, annotation in get_args(base.model_fields["action"].annotation)[
            0
        ].model_fields.items()
    }
    fields["request_agent_guidance"] = (Guidance | None, None)
    actions = create_model("GuidanceActionModel", __base__=ActionModel, **fields)
    return AgentOutput.type_with_custom_actions_flash_mode(actions)


class Guidance(BaseModel):
    reason: str


async def test_a_blocked_step_asks_the_agent_instead_of_ending_the_run(flights_state) -> None:
    """Ending on BLOCKED throws away a run the agent that asked for it could often unstick with one fact."""
    model, _, _ = _guided_model(
        flights_state, [("BLOCKED", None)], [{"text": "The date picker never opens."}]
    )

    result = await model.ainvoke([], _guidance_output())

    assert _action(result.completion) == {
        "request_agent_guidance": {"reason": "The date picker never opens."}
    }


async def test_the_guidance_reason_is_written_without_reasoning(flights_state) -> None:
    """With reasoning on, half the replies came back as prose with no tool call and fell to the generic reason."""
    model, _, text_model = _guided_model(
        flights_state, [("BLOCKED", None)], [{"text": "The date picker never opens."}]
    )

    await model.ainvoke([], _guidance_output())

    assert [r for r, _ in text_model.asked_with(GUIDANCE_REASON)] == [ReasoningLevel.OFF]


async def test_a_blocked_step_with_nobody_to_ask_still_ends_the_run_failed(flights_state) -> None:
    """The gate is the whole safety of this: with no agent joined, asking would stall the run for two minutes and answer nothing."""
    model, _, _ = _guided_model(flights_state, [("BLOCKED", None)], allowed=False)

    result = await model.ainvoke([], _guidance_output())

    action = _action(result.completion)
    assert action["done"]["success"] is False
    assert action["done"]["text"] == BROWSER_RUN_BLOCKED_SUMMARY


async def test_a_blocked_step_on_a_run_without_the_action_registered_ends_failed(
    flights_state,
) -> None:
    """Browser-Use narrows the last step to done only; an action it never registered would be rejected outright."""
    model, _, _ = _guided_model(flights_state, [("BLOCKED", None)])

    result = await model.ainvoke([], _agent_output())

    assert _action(result.completion)["done"]["success"] is False


async def test_the_guidance_request_carries_the_page_the_agent_has_to_reason_about(
    flights_state,
) -> None:
    """An agent asked "what now" with no page, no controls and no history can only guess."""
    model, _, _ = _guided_model(flights_state, [("BLOCKED", None)], [{"text": "No cabin control."}])
    await model.ainvoke([], _guidance_output())

    request = model.guidance_request("No cabin control.")

    assert request.task == "Fly Zurich to London"
    assert request.url == "https://x"
    assert request.title == "X"
    assert "Where to?" in [element.label for element in request.elements]
    assert [action.action for action in request.recent_actions] == ["BLOCKED"]


async def test_an_agent_note_leaves_the_human_handoffs_on_the_table(flights_state) -> None:
    """Agent guidance may legitimately be "this needs the user to sign in"; suppressing the handoff would make that instruction unactionable."""
    model, gateway, _ = _guided_model(
        flights_state,
        [("BLOCKED", None), ("CLICK", "4")],
        [{"text": "stuck"}],
    )
    await model.ainvoke([], _guidance_output())

    model.note_from_agent("sign in first, the seat map is behind the account")
    await model.ainvoke([], _guidance_output())

    offered = set(gateway.requests[1].questions["operation"].criteria)
    assert {"REQUEST_HUMAN", "SOLVE_CAPTCHA"} <= offered


async def test_a_user_note_still_takes_the_human_handoffs_off_the_table(flights_state) -> None:
    model, gateway, _ = _guided_model(
        flights_state,
        [("REQUEST_HUMAN", None), ("CLICK", "4")],
        [{"text": "Sign in", "category": "credentials"}],
    )
    await model.ainvoke([], _guidance_output())

    model.note_from_user("skip the login, just tell me the title")
    await model.ainvoke([], _guidance_output())

    offered = set(gateway.requests[1].questions["operation"].criteria)
    assert "REQUEST_HUMAN" not in offered


async def test_blocked_is_off_the_table_on_the_step_right_after_guidance(flights_state) -> None:
    """Giving up on the very step the agent just answered spends a guidance round and never tries what it said."""
    model, gateway, _ = _guided_model(
        flights_state,
        [("BLOCKED", None), ("CLICK", "4"), ("CLICK", "4")],
        [{"text": "stuck"}],
    )
    await model.ainvoke([], _guidance_output())

    model.note_from_agent("click Search, the filters are already set")
    await model.ainvoke([], _guidance_output())
    await model.ainvoke([], _guidance_output())

    assert "BLOCKED" not in set(gateway.requests[1].questions["operation"].criteria)
    assert "BLOCKED" in set(gateway.requests[2].questions["operation"].criteria)


async def test_an_agent_note_guides_the_goal_without_replacing_the_users_task(
    flights_state,
) -> None:
    """The user asked for the task; the agent only says how to get there, so an "overrides the task" wording would let the run answer the wrong question."""
    model, gateway, _ = _guided_model(
        flights_state, [("BLOCKED", None), ("CLICK", "4")], [{"text": "stuck"}]
    )
    await model.ainvoke([], _guidance_output())

    model.note_from_agent("use the mobile site, m.example.test")
    await model.ainvoke([], _guidance_output())

    goal = gateway.requests[1].questions["operation"].instructions["goal"]
    assert goal.startswith(
        "Guidance from the assistant that planned this task, on how to proceed: "
        "use the mobile site, m.example.test"
    )
    assert "Task, which still stands: Fly Zurich to London" in goal


async def test_an_agent_note_after_a_user_note_still_keeps_the_handoffs_off_the_table(
    flights_state,
) -> None:
    """Regression: the agent's guidance landed after the note, so the run re-asked the login the user had cancelled."""
    model, gateway, _ = _guided_model(
        flights_state,
        [("REQUEST_HUMAN", None), ("BLOCKED", None), ("CLICK", "4"), ("CLICK", "4")],
        [{"text": "Sign in to your Reddit account", "category": "credentials"}, {"text": "stuck"}],
    )
    await model.ainvoke([], _guidance_output())
    model.note_from_user("skip the upvote, just tell me the title of the top post")
    await model.ainvoke([], _guidance_output())

    model.note_from_agent("sign in with the saved password")
    await model.ainvoke([], _guidance_output())
    await model.ainvoke([], _guidance_output())

    for request in gateway.requests[1:]:
        offered = set(request.questions["operation"].criteria)
        assert "REQUEST_HUMAN" not in offered
        assert "SOLVE_CAPTCHA" not in offered


async def test_the_goal_leads_with_the_user_note_and_still_carries_the_agents_guidance(
    flights_state,
) -> None:
    """Regression: the later agent note replaced the user's instruction, so Jev was told the original task still stood."""
    model, gateway, _ = _guided_model(
        flights_state,
        [("REQUEST_HUMAN", None), ("BLOCKED", None), ("CLICK", "4")],
        [{"text": "Sign in", "category": "credentials"}, {"text": "stuck"}],
    )
    await model.ainvoke([], _guidance_output())
    model.note_from_user("skip the login, just tell me the page title")
    await model.ainvoke([], _guidance_output())

    model.note_from_agent("use the mobile site, m.example.test")
    await model.ainvoke([], _guidance_output())

    goal = gateway.requests[2].questions["operation"].instructions["goal"]
    assert goal.index("skip the login, just tell me the page title") < goal.index(
        "use the mobile site, m.example.test"
    )
    assert goal.index("use the mobile site, m.example.test") < goal.index("Fly Zurich to London")
    assert goal.startswith("Latest instruction from the user, which overrides the task below: ")
    assert "Original task: Fly Zurich to London" in goal


async def test_the_guidance_request_carries_what_the_user_changed_mid_run(flights_state) -> None:
    """Regression: the executor guided toward the original task because nothing told it the user had changed it."""
    model, _, _ = _guided_model(
        flights_state,
        [("REQUEST_HUMAN", None), ("BLOCKED", None)],
        [{"text": "Sign in", "category": "credentials"}, {"text": "stuck"}],
    )
    await model.ainvoke([], _guidance_output())
    model.note_from_user("skip the login, just tell me the page title")
    await model.ainvoke([], _guidance_output())

    assert model.guidance_request("stuck").user_notes == [
        "skip the login, just tell me the page title"
    ]


async def test_a_guidance_request_on_a_run_nobody_redirected_carries_no_notes(
    flights_state,
) -> None:
    model, _, _ = _guided_model(flights_state, [("BLOCKED", None)], [{"text": "stuck"}])
    await model.ainvoke([], _guidance_output())

    assert model.guidance_request("stuck").user_notes == []


async def test_the_step_photo_is_rendered_while_the_decision_is_made(flights_state) -> None:
    """Inside the state read the render queued ahead of the DOM on Obscura, 4 s on a long page."""
    model, _, _, session = _model(flights_state, [("CLICK", "4")])
    session.take_screenshot = AsyncMock(return_value=b"png-bytes")

    await model.ainvoke([], _agent_output())
    photo = await model.take_step_screenshot()

    assert photo == base64.b64encode(b"png-bytes").decode()
    assert session.take_screenshot.await_count == 1
    assert await model.take_step_screenshot() is None


async def test_a_failed_step_photo_costs_the_step_nothing(flights_state) -> None:
    model, _, _, session = _model(flights_state, [("CLICK", "4")])
    session.take_screenshot = AsyncMock(side_effect=RuntimeError("engine busy"))

    result = await model.ainvoke([], _agent_output())

    assert _action(result.completion) == {"click": {"index": 40}}
    assert await model.take_step_screenshot() is None


def _stalled_history(
    kinds: list[str], *, changed_at: int | None = None, url: str = "https://a.test/"
) -> list:
    from app.services.browser.jev.policy import JevHistoryEntry

    return [
        JevHistoryEntry(action=kind.upper(), kind=kind, page_changed=(i == changed_at), url=url)
        for i, kind in enumerate(kinds)
    ]


def test_a_page_that_a_run_of_actions_never_changed_is_stalled() -> None:
    from app.services.browser.jev.chat_model import _STALLED_STEPS, _page_stalled_in

    kinds = ["click", "scroll_down", "scroll_up", "wait"] * (_STALLED_STEPS // 4)
    assert _page_stalled_in(_stalled_history(kinds), 0) is True
    assert _page_stalled_in(_stalled_history(kinds[:-1]), 0) is False


def test_typing_or_a_page_change_in_the_run_means_it_is_not_stalled() -> None:
    from app.services.browser.jev.chat_model import _STALLED_STEPS, _page_stalled_in

    typed = ["click"] * (_STALLED_STEPS - 1) + ["type_text"]
    assert _page_stalled_in(_stalled_history(typed), 0) is False
    moved = ["click"] * _STALLED_STEPS
    assert _page_stalled_in(_stalled_history(moved, changed_at=3), 0) is False


def test_a_stall_already_acted_on_needs_a_whole_new_run_of_steps() -> None:
    from app.services.browser.jev.chat_model import _STALLED_STEPS, _page_stalled_in

    history = _stalled_history(["click"] * (_STALLED_STEPS + 2))
    assert _page_stalled_in(history, _STALLED_STEPS) is False
    assert _page_stalled_in(history, 0) is True


async def test_waits_in_a_row_on_one_page_grow_longer(flights_state) -> None:
    """Browser-Use sleeps a second less than asked, so each figure is the wait wanted plus one."""
    model, _, _, _ = _model(flights_state, [("WAIT", None)] * 4)

    seconds = [
        _action((await model.ainvoke([], _agent_output())).completion)["wait"]["seconds"]
        for _ in range(4)
    ]

    assert seconds == [4, 7, 11, 11]


async def test_a_site_that_never_loaded_is_named_when_the_run_is_blocked(flights_state) -> None:
    flights_state.url = "about:blank"
    model, _, _, _ = _model(
        flights_state,
        [("NAVIGATE", None), ("BLOCKED", None)],
        [{"text": "https://nowhere.invalid/"}],
    )
    await model.ainvoke([], _agent_output())

    result = await model.ainvoke([], _agent_output())

    assert _action(result.completion)["done"]["text"] == (
        "I couldn't open https://nowhere.invalid/: the page never loaded."
    )


async def test_a_blocked_run_that_read_pages_reports_them(flights_state) -> None:
    model, _, _, _ = _model(
        flights_state, [("BLOCKED", None)], [{"text": "Found the flights page; no fares shown."}]
    )

    result = await model.ainvoke([], _agent_output())

    done = _action(result.completion)["done"]
    assert done["text"] == "Found the flights page; no fares shown."
    assert done["success"] is False


async def test_a_done_the_evidence_check_rejects_is_withheld(flights_state) -> None:
    model, gateway, helper, _ = _model(flights_state, [("DONE", None), ("WAIT", None)])
    helper.confirms_done = False

    result = await model.ainvoke([], _agent_output())

    assert _action(result.completion) == {"wait": {"seconds": 4}}
    assert "DONE" not in gateway.requests[1].questions["operation"].criteria


async def test_an_honest_answer_to_a_goal_not_achieved_is_not_a_success(flights_state) -> None:
    model, _, _, _ = _model(
        flights_state,
        [("DONE", None)],
        [{"text": "There is no Buy now button on this page.", "achieved": False}],
    )

    result = await model.ainvoke([], _agent_output())

    done = _action(result.completion)["done"]
    assert done["text"] == "There is no Buy now button on this page."
    assert done["success"] is False


# ---------------------------------------------------------------------------
# Engine fallback: a blocked page is retried once on the other engine
# ---------------------------------------------------------------------------


async def test_a_blocked_page_asks_for_the_fallback_engine_once_and_resumes_there(
    flights_state,
) -> None:
    model, gateway, helper, _ = _model(
        flights_state,
        [("BLOCKED", None), ("BLOCKED", None)],
        [{"text": "Found the flights page; no fares shown."}],
    )
    model.fallback_available = True

    blocked = await model.ainvoke([], _agent_output())

    # Handing the page to the other engine is not a closing answer: no writer call.
    assert model.fallback_url == flights_state.url
    assert _action(blocked.completion)["done"]["success"] is False
    assert helper.calls == []

    model.continue_on_fallback()
    resumed = await model.ainvoke([], _agent_output())

    assert _action(resumed.completion) == {"navigate": {"url": flights_state.url, "new_tab": False}}
    assert len(gateway.requests) == 1

    blocked_again = await model.ainvoke([], _agent_output())

    # Blocked on the fallback too: the run ends with what it read, no second switch.
    done = _action(blocked_again.completion)["done"]
    assert (done["text"], done["success"]) == ("Found the flights page; no fares shown.", False)
    assert model.fallback_available is False


async def test_a_run_whose_engine_failed_resumes_on_the_fallback_at_the_page_it_last_read(
    flights_state,
) -> None:
    model, gateway, _, _ = _model(flights_state, [("CLICK", "4")])
    model.fallback_available = True
    await model.ainvoke([], _agent_output())

    model.fall_back_after_engine_failure()
    model.continue_on_fallback()
    resumed = await model.ainvoke([], _agent_output())

    assert _action(resumed.completion) == {"navigate": {"url": flights_state.url, "new_tab": False}}
    assert len(gateway.requests) == 1
    assert model.fallback_available is False


# ---------------------------------------------------------------------------
# A wall that clears on the same url: the page it turns into is judged again
# ---------------------------------------------------------------------------

_QUESTIONS_URL = "https://stackoverflow.com/questions"


async def test_a_list_that_replaces_a_wall_on_the_same_url_is_judged_and_answers_the_task(
    monkeypatch,
) -> None:
    """Regression: the wall was judged, the list that replaced it never was, and the run failed."""
    wall = make_state(
        {1: FakeNode("A", text="Privacy")}, url=_QUESTIONS_URL, title="Just a moment..."
    )
    questions = make_state(
        {1: FakeNode("A", text="How to keep direct initialization errors?")},
        url=_QUESTIONS_URL,
        title="Newest Questions - Stack Overflow",
    )
    screens = iter(
        [
            ViewportRead(
                text="Ray ID: a3f9\nPerformance and Security by Cloudflare", at_bottom=True
            ),
            ViewportRead(text="Newest Questions\nHow to keep direct initialization errors?"),
            ViewportRead(text="Newest Questions\nHow to keep direct initialization errors?"),
        ]
    )

    async def screen(*args: object) -> ViewportRead:
        return next(screens)

    monkeypatch.setattr(chat_model_mod, "read_viewport", screen)
    helper = FakeTextModel(replies=[{"text": 'The first question is "How to keep direct..."'}])
    judged: list[dict[str, Any]] = []

    async def writer(schema, prompt, *, label, timeout=None, reasoning=None):
        # Judges like the real writer: done when the page shows the list, not while the wall does.
        if not prompt[0].content.startswith(PART_DONE):
            return await helper.structured(schema, prompt, label=label, timeout=timeout)
        context = json.loads(prompt[1].content)
        judged.append(context)
        shown = "How to keep" in context["page"]["text"]
        return schema.model_validate(
            {
                "requirements": ["the first question"],
                "done": shown,
                "evidence": [_QUESTIONS_URL] if shown else [],
                "findings": "",
            }
        )

    gateway = ScriptedGateway(script=[("WAIT", None), ("SCROLL_DOWN", None)])
    model = JevChatModel(client=gateway, text_model=helper, structured_call=writer)  # type: ignore[arg-type]  # a scripted gateway and a fake text model stand in for the real ones
    session = FakeSession(wall)
    model.bind(
        session, f"Go to {_QUESTIONS_URL} and tell me the exact title of the first question listed."
    )  # type: ignore[arg-type]  # a fake session stands in for Browser-Use's
    await model.ainvoke([], _agent_output())
    for _ in range(20):  # the step's wait executes; the wall's judgement comes back
        await asyncio.sleep(0)
    session.state = questions
    # The list is judged while this step's scroll goes out; its verdict ends the run next step.
    await model.ainvoke([], _agent_output())
    for _ in range(20):
        await asyncio.sleep(0)

    result = await model.ainvoke([], _agent_output())

    assert _action(result.completion)["done"]["success"] is True
    # The list, not the wall: its own title, and only its top part read.
    assert judged[-1]["pages_read"] == [
        {
            "url": _QUESTIONS_URL,
            "title": "Newest Questions - Stack Overflow",
            "read": "top part only",
        }
    ]


# ---------------------------------------------------------------------------
# Latency: the writer's plan, part judgement and closing answer off the step's path
# ---------------------------------------------------------------------------

_HN_PART = "Read the top story on news.ycombinator.com"


def _writer_model(state, script, writer) -> tuple[JevChatModel, ScriptedGateway, FakeSession]:
    gateway = ScriptedGateway(script=list(script))
    model = JevChatModel(client=gateway, text_model=FakeTextModel(), structured_call=writer)  # type: ignore[arg-type]  # a scripted gateway and a fake text model stand in for the real ones
    session = FakeSession(state)
    model.bind(session, "Fly Zurich to London")  # type: ignore[arg-type]  # a fake session stands in for Browser-Use's
    return model, gateway, session


class _Judge:
    """The writer seam with a part judgement that answers only when the test releases it."""

    def __init__(self, *, done: bool = False) -> None:
        self.helper = FakeTextModel(replies=[{"text": "Flights are listed."}])
        self.done = done
        self.release = asyncio.Event()
        self.asked = asyncio.Event()
        self.judged = 0

    async def __call__(self, schema, prompt, *, label, timeout=None, reasoning=None):
        if not prompt[0].content.startswith(PART_DONE):
            return await self.helper.structured(schema, prompt, label=label, timeout=timeout)
        self.judged += 1
        self.asked.set()
        await self.release.wait()
        url = json.loads(prompt[1].content)["pages_read"][0]["url"]
        return schema.model_validate(
            {
                "requirements": ["the flights"],
                "done": self.done,
                "evidence": [url] if self.done else [],
                "findings": "",
            }
        )


async def test_the_plan_is_asked_for_while_the_first_page_is_still_being_read(
    flights_state,
) -> None:
    plan_asked = asyncio.Event()
    helper = FakeTextModel()

    async def writer(schema, prompt, *, label, timeout=None, reasoning=None):
        if prompt[0].content.startswith(PLAN_STEPS):
            plan_asked.set()
        return await helper.structured(schema, prompt, label=label, timeout=timeout)

    class _SlowPage(FakeSession):
        async def get_browser_state_summary(self, **kwargs):
            # The first read waits on the engine loading the page; the plan needs no page.
            await asyncio.wait_for(plan_asked.wait(), timeout=1)
            return await super().get_browser_state_summary(**kwargs)

    model = JevChatModel(
        client=ScriptedGateway(script=[("CLICK", "4")]), text_model=helper, structured_call=writer
    )  # type: ignore[arg-type]  # a scripted gateway and a fake text model stand in for the real ones
    model.bind(_SlowPage(flights_state), "Fly Zurich to London")  # type: ignore[arg-type]  # a fake session stands in for Browser-Use's

    result = await model.ainvoke([], _agent_output())

    assert _action(result.completion) == {"click": {"index": 40}}


async def test_a_finishing_step_is_named_after_the_part_it_finished(flights_state) -> None:
    helper = FakeTextModel(replies=[{"text": "The top story is X with 217 points."}])

    async def writer(schema, prompt, *, label, timeout=None, reasoning=None):
        if prompt[0].content.startswith(PLAN_STEPS):
            return schema.model_validate(
                {"steps": [{"goal": _HN_PART, "url": "https://news.ycombinator.com"}]}
            )
        return await helper.structured(schema, prompt, label=label, timeout=timeout)

    model, _, _ = _writer_model(flights_state, [("DONE", None)], writer)

    result = await model.ainvoke([], _agent_output())

    assert _action(result.completion)["done"]["success"] is True
    assert result.completion.next_goal == _HN_PART


async def test_a_step_jev_decides_does_not_wait_for_a_slow_part_judgement(flights_state) -> None:
    judge = _Judge()
    model, _, _ = _writer_model(flights_state, [("CLICK", "4")], judge)

    result = await asyncio.wait_for(model.ainvoke([], _agent_output()), timeout=1)

    assert _action(result.completion) == {"click": {"index": 40}}
    assert not judge.release.is_set()
    judge.release.set()


async def test_a_done_step_waits_for_the_part_judgement(flights_state) -> None:
    judge = _Judge(done=True)
    model, _, _ = _writer_model(flights_state, [("DONE", None)], judge)

    step = asyncio.create_task(model.ainvoke([], _agent_output()))
    await asyncio.wait_for(judge.asked.wait(), timeout=1)
    for _ in range(20):
        await asyncio.sleep(0)
    assert not step.done()

    judge.release.set()
    result = await asyncio.wait_for(step, timeout=1)

    assert _action(result.completion)["done"] == {
        "text": "Flights are listed.",
        "success": True,
        "files_to_display": [],
    }


async def test_a_part_judged_done_after_its_step_ends_the_run_on_the_next(flights_state) -> None:
    judge = _Judge(done=True)
    # One scripted choice: the next step must finish without asking Jev again.
    model, gateway, _ = _writer_model(flights_state, [("CLICK", "4")], judge)
    await asyncio.wait_for(model.ainvoke([], _agent_output()), timeout=1)
    judge.release.set()
    for _ in range(20):
        await asyncio.sleep(0)

    result = await asyncio.wait_for(model.ainvoke([], _agent_output()), timeout=1)

    assert _action(result.completion)["done"]["success"] is True
    assert len(gateway.requests) == 1
    assert judge.judged == 1


async def test_the_blank_tab_before_the_first_page_is_never_judged() -> None:
    blank = make_state({1: FakeNode("BUTTON", text="Search")}, url="about:blank", title="")
    judge = _Judge()
    judge.release.set()
    model, _, _ = _writer_model(blank, [("CLICK", "1")], judge)

    await model.ainvoke([], _agent_output())
    for _ in range(20):
        await asyncio.sleep(0)

    assert judge.judged == 0


async def test_the_part_judge_answers_without_reasoning_from_the_text_read(flights_state) -> None:
    """Reasoning made each judgement 8-33 s; without it the judge needs the text read, not the current screen alone."""
    helper = FakeTextModel(replies=[{"text": "Flights are listed."}])
    model, _, _ = _writer_model(flights_state, [("DONE", None)], helper.structured)

    await model.ainvoke([], _agent_output())

    judgements = helper.asked_with(PART_DONE)
    assert judgements
    assert all(reasoning is ReasoningLevel.OFF for reasoning, _ in judgements)
    assert "Search" in judgements[-1][1]["seen_on_pages_read"]
    assert [r for r, _ in helper.asked_with(PLAN_STEPS) + helper.asked_with(DONE_SUMMARY)] == [
        None,
        None,
    ]


async def test_the_closing_answer_is_written_while_the_evidence_check_runs(flights_state) -> None:
    order: list[str] = []
    answer_asked = asyncio.Event()
    helper = FakeTextModel(replies=[{"text": "Flights are listed."}])

    async def writer(schema, prompt, *, label, timeout=None, reasoning=None):
        if prompt[0].content.startswith(DONE_SUMMARY):
            order.append("answer asked")
            answer_asked.set()
        elif label == "browser_done_check":
            # A slow check: the answer is already being written when it returns.
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(answer_asked.wait(), timeout=1)
            order.append("check answered")
        return await helper.structured(schema, prompt, label=label, timeout=timeout)

    model, _, _ = _writer_model(flights_state, [("DONE", None)], writer)

    result = await model.ainvoke([], _agent_output())

    assert _action(result.completion)["done"]["text"] == "Flights are listed."
    assert order == ["answer asked", "check answered"]


async def test_no_answer_goes_out_when_the_evidence_check_says_the_part_is_not_done(
    flights_state,
) -> None:
    helper = FakeTextModel(confirms_done=False)
    never = asyncio.Event()

    async def writer(schema, prompt, *, label, timeout=None, reasoning=None):
        if prompt[0].content.startswith(DONE_SUMMARY):
            # An answer written ahead that is never needed must not hold the step.
            await never.wait()
        return await helper.structured(schema, prompt, label=label, timeout=timeout)

    model, gateway, _ = _writer_model(flights_state, [("DONE", None), ("WAIT", None)], writer)

    result = await asyncio.wait_for(model.ainvoke([], _agent_output()), timeout=1)

    assert _action(result.completion) == {"wait": {"seconds": 4}}
    assert "DONE" not in gateway.requests[1].questions["operation"].criteria


# ---------------------------------------------------------------------------
# GO_BACK only where this browser has a page to go back to
# ---------------------------------------------------------------------------

_BLANK = make_state({}, url="about:blank", title="")


async def test_go_back_returns_to_the_page_this_browser_came_from(flights_state) -> None:
    model, gateway, _, session = _model(flights_state, [("CLICK", "4"), ("GO_BACK", None)])
    await model.ainvoke([], _agent_output())
    session.state = make_state({1: FakeNode("A", text="Results")}, url="https://x/results")

    result = await model.ainvoke([], _agent_output())

    assert _action(result.completion) == {"go_back": {}}


async def test_the_first_page_after_the_engine_switch_offers_no_go_back(flights_state) -> None:
    """Regression: GO_BACK from the fallback's first page landed on about:blank, and the run ended there."""
    model, gateway, _, session = _model(flights_state, [("CLICK", "4"), ("SCROLL_DOWN", None)])
    model.fallback_available = True
    await model.ainvoke([], _agent_output())
    model.fall_back_after_engine_failure()
    model.continue_on_fallback()
    session.state = _BLANK
    await model.ainvoke([], _agent_output())
    session.state = flights_state

    await model.ainvoke([], _agent_output())

    assert "GO_BACK" not in gateway.requests[-1].questions["operation"].criteria


async def test_the_first_page_a_run_opened_from_the_blank_tab_offers_no_go_back(
    flights_state,
) -> None:
    """Regression: back from the run's first page is the blank tab the browser opened on."""
    model, gateway, _, session = _model(flights_state, [("CLICK", "1"), ("SCROLL_DOWN", None)])
    session.state = make_state({1: FakeNode("BUTTON", text="Go")}, url="about:blank", title="")
    await model.ainvoke([], _agent_output())
    session.state = flights_state

    await model.ainvoke([], _agent_output())

    assert "GO_BACK" not in gateway.requests[-1].questions["operation"].criteria


# ---------------------------------------------------------------------------
# A one-page list read to its bottom answers a "compare them all" part
# ---------------------------------------------------------------------------

_TRAVEL = "https://books.toscrape.com/catalogue/category/books/travel_2/index.html"


async def test_a_one_page_category_read_to_its_bottom_answers_the_cheapest_book(
    monkeypatch,
) -> None:
    """The Travel category: 11 books, no next link; the bottom scroll must make it read "to the end"."""
    travel = make_state(
        {1: FakeNode("A", text="Travel")}, url=_TRAVEL, title="Travel | Books to Scrape"
    )
    screens = iter(
        [
            ViewportRead(text="It's Only the Himalayas\n£45.17\nVagabonding\n£36.94"),
            ViewportRead(
                text="The Road to Little Dribbling\n£23.21\n1,000 Places to See Before You Die\n£26.08",
                at_bottom=True,
            ),
            ViewportRead(text="The Road to Little Dribbling\n£23.21", at_bottom=True),
        ]
    )

    async def screen(*args: object) -> ViewportRead:
        return next(screens)

    monkeypatch.setattr(chat_model_mod, "read_viewport", screen)
    helper = FakeTextModel(replies=[{"text": "The Road to Little Dribbling, £23.21."}])
    judged: list[list[dict[str, str]]] = []

    async def writer(schema, prompt, *, label, timeout=None, reasoning=None):
        if prompt[0].content.startswith(PLAN_STEPS):
            return schema.model_validate(
                {"steps": [{"goal": "Find the cheapest book in Travel", "url": _TRAVEL}]}
            )
        if not prompt[0].content.startswith(PART_DONE):
            return await helper.structured(schema, prompt, label=label, timeout=timeout)
        pages = json.loads(prompt[1].content)["pages_read"]
        judged.append(pages)
        # Judges like the real writer: a whole list is known only from a page read to the end.
        whole = any(p["url"] == _TRAVEL and p["read"] == "to the end" for p in pages)
        return schema.model_validate(
            {
                "requirements": ["the cheapest book"],
                "done": whole,
                "evidence": [_TRAVEL] if whole else [],
                "findings": "",
            }
        )

    gateway = ScriptedGateway(script=[("SCROLL_DOWN", None), ("SCROLL_DOWN", None)])
    model = JevChatModel(client=gateway, text_model=helper, structured_call=writer)  # type: ignore[arg-type]  # a scripted gateway and a fake text model stand in for the real ones
    model.bind(FakeSession(travel), "Find the cheapest book in the Travel category")  # type: ignore[arg-type]  # a fake session stands in for Browser-Use's
    for _ in range(2):
        await model.ainvoke([], _agent_output())
        for _ in range(20):  # the scroll executes; the judgement comes back
            await asyncio.sleep(0)

    result = await model.ainvoke([], _agent_output())

    assert judged[-1] == [
        {"url": _TRAVEL, "title": "Travel | Books to Scrape", "read": "to the end"}
    ]
    assert _action(result.completion)["done"] == {
        "text": "The Road to Little Dribbling, £23.21.",
        "success": True,
        "files_to_display": [],
    }


async def test_a_part_on_the_site_the_run_started_on_is_not_navigated_to_again() -> None:
    """The start URL is opened before Jev's first step; the plan opening its part there as well loaded the site twice."""
    home = make_state({40: FakeNode("BUTTON", text="Travel")}, url="https://books.toscrape.com/")

    async def writer(schema, prompt, *, label, timeout=None, reasoning=None):
        if prompt[0].content.startswith(PLAN_STEPS):
            return schema.model_validate(
                {
                    "steps": [
                        {"goal": "Find the cheapest book in Travel", "url": _TRAVEL},
                        {"goal": "Look it up on Wikipedia", "url": "https://en.wikipedia.org"},
                    ]
                }
            )
        return await FakeTextModel().structured(schema, prompt, label=label, timeout=timeout)

    model, gateway, _ = _writer_model(home, [("WAIT", None)], writer)

    result = await model.ainvoke([], _agent_output())

    assert "navigate" not in _action(result.completion)
    assert len(gateway.requests) == 1


class _SlowJudgeFastCheck:
    """Part judgements hang until released; the DONE evidence check answers at once."""

    def __init__(self) -> None:
        self.helper = FakeTextModel(replies=[{"text": "Flights are listed."}])
        self.release = asyncio.Event()
        self.plan: list[dict[str, Any]] = []

    async def __call__(self, schema, prompt, *, label, timeout=None, reasoning=None):
        if prompt[0].content.startswith(PLAN_STEPS) and self.plan:
            return schema.model_validate({"steps": self.plan})
        if not prompt[0].content.startswith(PART_DONE):
            return await self.helper.structured(schema, prompt, label=label, timeout=timeout)
        if label != "browser_done_check":
            await self.release.wait()
        url = json.loads(prompt[1].content)["pages_read"][-1]["url"]
        return schema.model_validate(
            {"requirements": ["the page"], "done": True, "evidence": [url], "findings": ""}
        )


async def test_a_done_on_newer_pages_is_not_held_by_a_judgement_of_older_ones(
    flights_state,
) -> None:
    writer = _SlowJudgeFastCheck()
    model, _, session = _writer_model(
        flights_state, [("SCROLL_DOWN", None), ("DONE", None)], writer
    )
    await asyncio.wait_for(model.ainvoke([], _agent_output()), timeout=1)
    session.state = make_state(flights_state.dom_state.selector_map, url="https://x/results")

    result = await asyncio.wait_for(model.ainvoke([], _agent_output()), timeout=1)

    assert _action(result.completion)["done"]["success"] is True
    writer.release.set()


async def test_a_judgement_of_a_finished_part_never_finishes_the_next(flights_state) -> None:
    writer = _SlowJudgeFastCheck()
    writer.plan = [{"goal": "Find the flights"}, {"goal": "Pick the cheapest"}]
    model, _, session = _writer_model(
        flights_state,
        [("SCROLL_DOWN", None), ("DONE", None), ("CLICK", "4"), ("CLICK", "4")],
        writer,
    )
    await asyncio.wait_for(model.ainvoke([], _agent_output()), timeout=1)
    session.state = make_state(flights_state.dom_state.selector_map, url="https://x/results")
    # Part 1 ends on its own evidence check; its slow judgement then says "done" too.
    await asyncio.wait_for(model.ainvoke([], _agent_output()), timeout=1)
    writer.release.set()
    for _ in range(20):
        await asyncio.sleep(0)

    result = await asyncio.wait_for(model.ainvoke([], _agent_output()), timeout=1)

    assert _action(result.completion) == {"click": {"index": 40}}


# ---------------------------------------------------------------------------
# Part evidence: what the run holds, and what a part's own start page can prove
# ---------------------------------------------------------------------------

_HN = "https://news.ycombinator.com/"
_ARTICLE = "https://blog.example/tts"
_LOGIN = "https://the-internet.herokuapp.com/login"
_SECURE = "https://the-internet.herokuapp.com/secure"


def _evidence_writer(
    parts: list[dict[str, Any]],
    evidence: list[Any],
    replies: list[dict[str, Any] | Exception],
    judged: list[dict[str, Any]] | None = None,
    requirements: list[str] | None = None,
):
    """Return a writer with this plan whose DONE check cites evidence; nothing else is judged done.

    Every judgement's context is appended to judged.
    """
    helper = FakeTextModel(replies=replies)

    async def writer(schema, prompt, *, label, timeout=None, reasoning=None):
        if prompt[0].content.startswith(PLAN_STEPS):
            return schema.model_validate({"steps": parts})
        if prompt[0].content.startswith(PART_DONE):
            if judged is not None:
                judged.append(json.loads(prompt[1].content))
            if label != "browser_done_check":
                return schema.model_validate({"done": False})
            return schema.model_validate(
                {
                    "requirements": requirements
                    if requirements is not None
                    else [e["requirement"] for e in evidence if isinstance(e, dict)] or ["it"],
                    "done": True,
                    "evidence": evidence,
                    "findings": "",
                }
            )
        return await helper.structured(schema, prompt, label=label, timeout=timeout)

    return writer


async def _run_to_done(start, then, script, writer, task: str):
    """Read start, move to then, and return the step Jev chose DONE on (or what replaced it).

    The gateway is returned too: its last request shows which part the run is on.
    """
    gateway = ScriptedGateway(script=list(script))
    model = JevChatModel(client=gateway, text_model=FakeTextModel(), structured_call=writer)  # type: ignore[arg-type]  # a scripted gateway and a fake text model stand in for the real ones
    session = FakeSession(start)
    model.bind(session, task)  # type: ignore[arg-type]  # a fake session stands in for Browser-Use's
    await model.ainvoke([], _agent_output())
    for _ in range(20):
        await asyncio.sleep(0)
    session.state = then
    return _action((await model.ainvoke([], _agent_output())).completion), gateway


_HN_TASK = (
    f"Go to {_HN}, give me the top story's title and points and summarise its article, "
    "then look the story up on Wikipedia."
)
#: A part only has a start page of its own in a plan of several parts.
_TOP_STORY_PLAN = [
    {"goal": "Top story's title, points and a summary of its article", "url": _HN},
    {"goal": "Look the story up on Wikipedia", "url": "https://en.wikipedia.org/"},
]


def _on_part(gateway: ScriptedGateway) -> str:
    goal = str(gateway.requests[-1].questions["operation"].instructions["goal"])
    return next(part for part in ("1 of 2", "2 of 2") if f"CURRENT PART ({part})" in goal)


async def test_facts_the_parts_own_listing_shows_are_evidence_for_it() -> None:
    """Regression: citations of the part's start page were refused, so the run wandered HN for 80 steps."""
    writer = _evidence_writer(
        _TOP_STORY_PLAN,
        [
            {"requirement": "title", "kind": "fact", "source": _HN},
            {"requirement": "points", "kind": "fact", "source": _HN},
            {"requirement": "article opened", "kind": "page opened", "source": _ARTICLE},
        ],
        [],
    )

    _, gateway = await _run_to_done(
        make_state({1: FakeNode("A", text="TTS")}, url=_HN),
        make_state({1: FakeNode("P", text="Gemini TTS")}, url=_ARTICLE),
        [("WAIT", None), ("DONE", None), ("WAIT", None)],
        writer,
        _HN_TASK,
    )

    assert _on_part(gateway) == "2 of 2"


@pytest.mark.parametrize(
    "citation",
    [
        {"requirement": "article opened", "kind": "page opened", "source": _HN},
        {"requirement": "article opened", "kind": "action", "source": _HN},
        _HN,
    ],
    ids=["opened", "as-an-action", "bare"],
)
async def test_the_listing_never_proves_a_page_was_opened_from_it(citation) -> None:
    writer = _evidence_writer(
        _TOP_STORY_PLAN,
        [{"requirement": "title", "kind": "fact", "source": _HN}, citation],
        [],
    )

    _, gateway = await _run_to_done(
        make_state({1: FakeNode("A", text="TTS")}, url=_HN),
        make_state({1: FakeNode("A", text="TTS")}, url=_HN),
        [("WAIT", None), ("DONE", None), ("WAIT", None)],
        writer,
        _HN_TASK,
    )

    assert _on_part(gateway) == "1 of 2"


@pytest.mark.parametrize(
    "source",
    [
        "Enter your username and password and sign in.",
        "REQUEST_HUMAN: Enter your username and password and sign in.",
    ],
    ids=["its-words", "labelled"],
)
async def test_a_login_the_user_completed_is_evidence_of_the_login(source) -> None:
    """Regression: the handoff cited by what it asked was refused, so a finished login stayed "not done"."""
    writer = _evidence_writer(
        [{"goal": "Log in", "url": _LOGIN}],
        [{"requirement": "logged in", "kind": "action", "source": source}],
        [
            {"text": "Enter your username and password and sign in.", "category": "credentials"},
            {"text": "You logged into a secure area!"},
        ],
    )

    action, _ = await _run_to_done(
        make_state({1: FakeNode("INPUT", {"name": "password"})}, url=_LOGIN),
        make_state({1: FakeNode("H2", text="Secure Area")}, url=_SECURE),
        [("REQUEST_HUMAN", None), ("DONE", None), ("WAIT", None)],
        writer,
        f"Go to {_LOGIN} and log me in; I'll type the password myself.",
    )

    assert action["done"]["success"] is True


async def test_an_action_the_run_never_took_is_not_evidence() -> None:
    writer = _evidence_writer(
        [{"goal": "Log in", "url": _LOGIN}],
        [{"requirement": "logged in", "kind": "action", "source": "CLICK [9] Login"}],
        [{"text": "Enter your username and password and sign in.", "category": "credentials"}],
    )

    action, _ = await _run_to_done(
        make_state({1: FakeNode("INPUT", {"name": "password"})}, url=_LOGIN),
        make_state({1: FakeNode("H2", text="Secure Area")}, url=_SECURE),
        [("REQUEST_HUMAN", None), ("DONE", None), ("WAIT", None)],
        writer,
        f"Go to {_LOGIN} and log me in; I'll type the password myself.",
    )

    assert "done" not in action, action


async def test_a_page_is_never_evidence_of_an_action() -> None:
    """The judge once called a login "handed to the user" on its first step, citing only the login page."""
    writer = _evidence_writer(
        [{"goal": "Log in", "url": _LOGIN}],
        [{"requirement": "session handed to the user", "kind": "action", "source": _LOGIN}],
        [],
    )

    action, _ = await _run_to_done(
        make_state({1: FakeNode("INPUT", {"name": "password"})}, url=_LOGIN),
        make_state({1: FakeNode("INPUT", {"name": "password"})}, url=_LOGIN),
        [("WAIT", None), ("DONE", None), ("WAIT", None)],
        writer,
        f"Go to {_LOGIN} and log me in; I'll type the password myself.",
    )

    assert "done" not in action, action


async def test_the_judge_is_told_the_page_the_part_started_on() -> None:
    """A login part's goal said "go to the login page"; the judge cited it as a page opened, and the finished login stayed "not done"."""
    judged: list[dict[str, Any]] = []
    writer = _evidence_writer(_TOP_STORY_PLAN, [], [], judged)

    await _run_to_done(
        make_state({1: FakeNode("A", text="TTS")}, url=_HN),
        make_state({1: FakeNode("A", text="TTS")}, url=_HN),
        [("WAIT", None), ("DONE", None), ("WAIT", None)],
        writer,
        _HN_TASK,
    )

    assert judged and all(context["start_page"] == _HN for context in judged)


async def test_a_part_is_not_done_while_a_requirement_it_named_has_no_evidence() -> None:
    """Regression: a login part was judged done on step one while still waiting on the handoff."""
    writer = _evidence_writer(
        [{"goal": "Go to the login page and hand the live view to the user"}],
        [{"requirement": "login page open", "kind": "fact", "source": _LOGIN}],
        [],
        requirements=["login page open", "live view handed to the user"],
    )

    action, _ = await _run_to_done(
        make_state({1: FakeNode("INPUT", {"name": "password"})}, url=_LOGIN),
        make_state({1: FakeNode("INPUT", {"name": "password"})}, url=_LOGIN),
        [("WAIT", None), ("DONE", None), ("WAIT", None)],
        writer,
        f"Go to {_LOGIN} and log me in; I'll type the password myself.",
    )

    assert "done" not in action, action


async def test_what_the_part_judge_found_missing_is_what_jev_is_told_to_do_next() -> None:
    """Regression: a part stayed "not done" for 37 steps because Jev never heard the judge's gap."""
    helper = FakeTextModel()

    async def writer(schema, prompt, *, label, timeout=None, reasoning=None):
        if prompt[0].content.startswith(PLAN_STEPS):
            return schema.model_validate({"steps": _TOP_STORY_PLAN})
        if prompt[0].content.startswith(PART_DONE):
            return schema.model_validate(
                {
                    "requirements": ["rank noted", "article body read past its headline"],
                    "evidence": [{"requirement": "rank noted", "kind": "fact", "source": _HN}],
                    "done": False,
                    "findings": "",
                }
            )
        return await helper.structured(schema, prompt, label=label, timeout=timeout)

    _, gateway = await _run_to_done(
        make_state({1: FakeNode("A", text="TTS")}, url=_HN),
        make_state({1: FakeNode("A", text="TTS")}, url=_HN),
        [("WAIT", None), ("WAIT", None)],
        writer,
        _HN_TASK,
    )

    goal = str(gateway.requests[-1].questions["operation"].instructions["goal"])
    assert "article body read past its headline" in goal
    assert "rank noted" not in goal


# ---------------------------------------------------------------------------
# A form submitted with a field skipped: back to the form, not BLOCKED
# ---------------------------------------------------------------------------

_FORM = "https://forms.example/web-form.html"
_SUBMITTED = "https://forms.example/submitted-form.html?my-text=Aryan"
_FORM_PAGE = make_state(
    {
        1: FakeNode("INPUT", {"type": "radio", "aria-label": "Radio 2"}),
        2: FakeNode("BUTTON", text="Submit", ax_node=FakeAXNode(role="button", name="Submit")),
    },
    url=_FORM,
    title="Web form",
)
_SUBMITTED_PAGE = make_state(
    {1: FakeNode("H1", text="Form submitted")}, url=_SUBMITTED, title="Web form - target page"
)
_FORM_TASK = f'Go to {_FORM}, choose "Radio 2", click Submit and tell me what the page shows.'


def _gap_judge(missing: list[str], *, on_done_check_only: bool = False):
    """Return a writer whose part check (one-part plan) finds nothing for missing and everything else held."""
    helper = FakeTextModel()

    async def writer(schema, prompt, *, label, timeout=None, reasoning=None):
        if prompt[0].content.startswith(PLAN_STEPS):
            return schema.model_validate({"steps": []})
        if prompt[0].content.startswith(PART_DONE):
            gap = missing if label == "browser_done_check" or not on_done_check_only else []
            return schema.model_validate(
                {"requirements": gap, "evidence": [], "done": False, "findings": ""}
            )
        return await helper.structured(schema, prompt, label=label, timeout=timeout)

    return writer


@pytest.mark.regression
async def test_a_one_part_task_is_told_what_the_judge_found_missing() -> None:
    """Regression: a form submitted without its radio was declared BLOCKED; the gap reached multi-part plans only."""
    _, gateway = await _run_to_done(
        _FORM_PAGE,
        _SUBMITTED_PAGE,
        [("CLICK", "2"), ("SCROLL_DOWN", None)],
        _gap_judge(["Radio 2 chosen"]),
        _FORM_TASK,
    )

    assert "Radio 2 chosen" in str(gateway.requests[-1].questions["operation"].instructions["goal"])


@pytest.mark.regression
async def test_a_withheld_done_is_re_decided_on_what_its_check_found_missing() -> None:
    """Regression: the re-ask after a withheld DONE ran on the goal from before that check, and chose BLOCKED."""
    action, gateway = await _run_to_done(
        _FORM_PAGE,
        _SUBMITTED_PAGE,
        [("CLICK", "2"), ("DONE", None), ("GO_BACK", None)],
        _gap_judge(["Radio 2 chosen"], on_done_check_only=True),
        _FORM_TASK,
    )

    re_ask = gateway.requests[-1].questions["operation"]
    assert "Radio 2 chosen" in str(re_ask.instructions["goal"])
    assert "BLOCKED" not in re_ask.criteria
    assert "GO_BACK" in re_ask.criteria
    assert action == {"go_back": {}}


async def test_blocked_stays_offered_while_something_is_missing_but_no_page_is_behind() -> None:
    _, gateway = await _run_to_done(
        _SUBMITTED_PAGE,
        _SUBMITTED_PAGE,
        [("SCROLL_DOWN", None), ("SCROLL_UP", None)],
        _gap_judge(["Radio 2 chosen"]),
        _FORM_TASK,
    )

    last = gateway.requests[-1].questions["operation"]
    assert "Radio 2 chosen" in str(last.instructions["goal"])
    assert "BLOCKED" in last.criteria


# ---------------------------------------------------------------------------
# The closing answer: every line of a confirmation, never a typed password
# ---------------------------------------------------------------------------


@pytest.mark.regression
async def test_the_closing_answer_reads_a_confirmations_heading_and_message_and_quotes_both() -> (
    None
):
    """Regression: "exactly what the page shows" was answered with the message alone, the prompt asking for one element."""
    confirmation = make_state(
        {1: FakeNode("H1", text="Form submitted"), 2: FakeNode("P", text="Received!")},
        url=_SUBMITTED,
    )
    model, _, helper, _ = _model(confirmation, [("DONE", None)], [{"text": "ok"}])

    await model.ainvoke([], _agent_output())

    context = helper.context(0)
    for line in ("Form submitted", "Received!"):
        assert line in context["page"]["text"]
        assert line in context["seen_on_pages_read"]
    assert helper.system_prompt(0) == DONE_SUMMARY
    assert "single element" not in DONE_SUMMARY
    assert "heading and its message" in DONE_SUMMARY


_LOGIN_FORM = make_state(
    {
        1: FakeNode("INPUT", {"type": "password", "name": "my-password"}),
        2: FakeNode("INPUT", {"name": "my-text"}),
    },
    url=_FORM,
)
_SECRET = "gaia test/123"


async def _typed_a_password(then, script, replies) -> tuple[JevChatModel, ScriptedGateway, Any]:
    model, gateway, helper, session = _model(
        _LOGIN_FORM, [("TYPE_TEXT", "1"), *script], [{"text": _SECRET}, *replies]
    )
    typed = _action((await model.ainvoke([], _agent_output())).completion)
    session.state = then
    return model, gateway, typed


@pytest.mark.regression
async def test_a_typed_password_is_masked_in_the_closing_answer_but_still_typed() -> None:
    landed = f"{_SUBMITTED}&my-password=gaia+test%2F123"
    model, gateway, typed = await _typed_a_password(
        make_state({1: FakeNode("H1", text="Form submitted")}, url=landed),
        [("DONE", None)],
        [{"text": f"Typed {_SECRET}; landed on {landed}"}],
    )

    done = _action((await model.ainvoke([], _agent_output())).completion)["done"]

    assert typed["input_text"]["text"] == _SECRET
    assert "gaia" not in done["text"]
    mask = browser_constants.JEV_SECRET_MASK
    assert done["text"].count(mask) == 2
    assert gateway.requests[-1].state["recent_actions"][0]["text"] == mask


@pytest.mark.regression
async def test_a_typed_password_is_masked_in_what_the_agent_is_asked_for_guidance() -> None:
    landed = f"{_SUBMITTED}&my-password=gaia+test%2F123"
    model, _, _ = await _typed_a_password(
        make_state({1: FakeNode("P", text=f"You sent {_SECRET}")}, url=landed), [("WAIT", None)], []
    )
    await model.ainvoke([], _agent_output())

    request = model.guidance_request("stuck")

    assert "gaia" not in request.url
    assert "gaia" not in request.page_text
