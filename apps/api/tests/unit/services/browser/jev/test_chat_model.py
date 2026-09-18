"""Jev decisions become Browser-Use actions; everything else is delegated."""

from __future__ import annotations

from dataclasses import dataclass, field
from types import SimpleNamespace
from typing import Any, Union
from unittest.mock import MagicMock

from browser_use.agent.views import ActionModel, AgentOutput
from browser_use.llm.messages import SystemMessage, UserMessage
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

from app.constants.browser import JevOperation
from app.constants.log_tags import LogTag
from app.services.browser.exceptions import BrowserUnavailableError
from app.services.browser.jev import chat_model as chat_model_mod
from app.services.browser.jev.chat_model import JevChatModel, build_jev_chat_model
from app.services.browser.jev.gateway import JevChoiceAnswer, JevEvaluation, JevUsage
from app.services.browser.jev.observation import observe
from app.services.browser.jev.prompts import (
    CAPTCHA_CHALLENGE,
    DONE_SUMMARY,
    TAKEOVER_REASON,
    TEXT_VALUE,
    URL_VALUE,
)

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


def _answer(choice: str, keys: list[str]) -> JevChoiceAnswer:
    rest = (1 - 0.8) / (len(keys) - 1) if len(keys) > 1 else 0
    return JevChoiceAnswer(
        type="choice",
        choice=choice,
        probabilities={k: (0.8 if k == choice else rest) for k in keys},
    )


@dataclass
class ScriptedGateway:
    """Answers each request from a script of (operation, target); records what it saw."""

    script: list[tuple[str, str | None]]
    model: str = "typesafe-ai/jev"
    requests: list[Any] = field(default_factory=list)

    async def evaluate(self, request):
        self.requests.append(request)
        operation, target = self.script.pop(0)
        ops = list(request.questions["operation"].criteria)
        answers = {"operation": _answer(operation, ops)}
        if target is not None:
            head = f"{operation.lower()}_target"
            answers[head] = _answer(target, list(request.questions[head].criteria))
        return JevEvaluation(
            answers=answers, usage=JevUsage(inputTokens=300, outputTokens=6), latency_ms=42
        )


@dataclass
class FakeTextModel:
    """The text helper: answers structured calls from a queue, records the prompts."""

    model: str = "text-helper"
    replies: list[dict[str, Any] | Exception] = field(default_factory=list)
    calls: list[tuple[list[Any], type[BaseModel] | None]] = field(default_factory=list)
    provider: str = "fake"
    name: str = "text-helper"

    async def ainvoke(self, messages, output_format=None, **kwargs):
        self.calls.append((messages, output_format))
        reply = self.replies.pop(0) if self.replies else {}
        if isinstance(reply, Exception):
            raise reply
        if output_format is None:
            return ChatInvokeCompletion(completion="plain", usage=None)
        return ChatInvokeCompletion(completion=output_format.model_validate(reply), usage=None)

    def system_prompt(self, call: int = 0) -> str:
        messages, _ = self.calls[call]
        assert isinstance(messages[0], SystemMessage)
        return messages[0].text

    def context(self, call: int = 0) -> dict[str, Any]:
        import json

        messages, _ = self.calls[call]
        assert isinstance(messages[1], UserMessage)
        return json.loads(messages[1].text)


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
    flights_state, script, replies=None
) -> tuple[JevChatModel, ScriptedGateway, FakeTextModel, FakeSession]:
    gateway = ScriptedGateway(script=list(script))
    text_model = FakeTextModel(replies=list(replies or []))
    model = JevChatModel(client=gateway, text_model=text_model)  # type: ignore[arg-type]  # the test hands a fake gateway client and a fake text model in place of the real ones
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
        ("WAIT", {"wait": {"seconds": 1}}),
        ("GO_BACK", {"go_back": {}}),
        (
            "BLOCKED",
            {
                "done": {
                    "text": "Could not make progress: no supported action can advance the task on this page.",
                    "success": False,
                    "files_to_display": [],
                }
            },
        ),
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
        flights_state, [("REQUEST_HUMAN", None)], [RuntimeError("provider down")]
    )

    result = await model.ainvoke([], _agent_output())

    assert _action(result.completion) == {
        "request_human_takeover": {
            "reason": "Complete this step in the live browser",
            "category": "irreversible",
        }
    }
    logger.warning.assert_called_once_with(
        f"{LogTag.BROWSER} Jev text helper failed", error_type="RuntimeError"
    )


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


async def test_done_without_a_summary_still_completes(flights_state) -> None:
    model, _, _, _ = _model(flights_state, [("DONE", None)], [{"text": None}])

    result = await model.ainvoke([], _agent_output())

    assert _action(result.completion)["done"]["text"] == "Completed the task."


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
            "note": None,
        }
    ]
    assert gateway.requests[2].state["recent_actions"][1] == {
        "action": "CLICK [4] Search",
        "kind": "click",
        "text": None,
        "page_changed": False,
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
    model = JevChatModel(client=gateway, text_model=FakeTextModel())  # type: ignore[arg-type]  # the test hands a fake gateway client and a fake text model in place of the real ones
    model.bind(FakeSession(flights_state), "g")  # type: ignore[arg-type]  # the test hands a fake session in place of Browser-Use's session

    result = await model.ainvoke([], _agent_output())

    assert _action(result.completion) == {"wait": {"seconds": 1}}
    assert result.usage is None
    logger.warning.assert_called_once_with(
        f"{LogTag.BROWSER} Jev decision rejected", error_type="JevDecisionError"
    )


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
    model = JevChatModel(client=ScriptedGateway(script=[]), text_model=FakeTextModel())  # type: ignore[arg-type]  # the test hands a fake gateway client and a fake text model in place of the real ones

    with pytest.raises(BrowserUnavailableError, match="no browser session bound"):
        await model.ainvoke([], _agent_output())


async def test_the_goal_falls_back_to_browser_uses_own_user_request_block(flights_state) -> None:
    gateway = ScriptedGateway(script=[("WAIT", None)])
    model = JevChatModel(client=gateway, text_model=FakeTextModel())  # type: ignore[arg-type]  # the test hands a fake gateway client and a fake text model in place of the real ones
    model._browser = FakeSession(flights_state)  # bound without a task
    messages = [
        UserMessage(content="<user_request>\nOpen the article\n</user_request>\n<browser_state>x")
    ]

    await model.ainvoke(messages, _agent_output())

    assert gateway.requests[0].questions["operation"].instructions["goal"] == "Open the article"


def test_identity_is_the_gateway_model(flights_state) -> None:
    model = JevChatModel(client=ScriptedGateway(script=[]), text_model=FakeTextModel())  # type: ignore[arg-type]  # the test hands a fake gateway client and a fake text model in place of the real ones

    assert (model.model, model.name, model.model_name, model.provider) == (
        "typesafe-ai/jev",
        "typesafe-ai/jev",
        "typesafe-ai/jev",
        "vercel-ai-gateway",
    )


def test_build_requires_the_gateway_key(monkeypatch) -> None:
    monkeypatch.setattr("app.services.browser.jev.chat_model.settings.OPENROUTER_API_KEY", None)

    with pytest.raises(BrowserUnavailableError, match="OPENROUTER_API_KEY"):
        build_jev_chat_model(text_model=FakeTextModel())  # type: ignore[arg-type]  # the test hands a fake text model in place of the real one


def test_build_wires_the_configured_gateway_and_keeps_the_text_model(monkeypatch) -> None:
    monkeypatch.setattr(
        "app.services.browser.jev.chat_model.settings.OPENROUTER_API_KEY", "sk-or-x"
    )
    monkeypatch.setattr(
        "app.services.browser.jev.chat_model.settings.BROWSER_USE_JEV_MODEL", "~typesafe/jev-latest"
    )
    monkeypatch.setattr(
        "app.services.browser.jev.chat_model.settings.BROWSER_USE_JEV_DECISIONS_URL",
        "https://decisions.test/api/alpha/decisions",
    )
    helper = FakeTextModel()

    model = build_jev_chat_model(text_model=helper)  # type: ignore[arg-type]  # the test hands a fake text model in place of the real one

    assert isinstance(model, JevChatModel)
    assert model.text_model is helper
    assert model.model == "~typesafe/jev-latest"
    assert model._client._url == "https://decisions.test/api/alpha/decisions"
    assert model._client._headers["Authorization"] == "Bearer sk-or-x"


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
    model = JevChatModel(client=BadGateway(script=[]), text_model=FakeTextModel())  # type: ignore[arg-type]  # the test hands a fake gateway client and a fake text model in place of the real ones
    model.bind(FakeSession(flights_state), "g")  # type: ignore[arg-type]  # the test hands a fake session in place of Browser-Use's session

    result = await model.ainvoke([], done_only)

    assert _action(result.completion)["done"]["success"] is False
    assert result.completion.next_goal == "DONE"


async def test_typed_text_shows_up_as_the_fields_live_value_on_the_next_step(flights_state) -> None:
    """The HTML value attribute never changes when the agent types; the DOM snapshot does."""
    gateway = ScriptedGateway(script=[("WAIT", None)])
    model = JevChatModel(client=gateway, text_model=FakeTextModel())  # type: ignore[arg-type]  # the test hands a fake gateway client and a fake text model in place of the real ones
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


async def test_the_users_takeover_note_is_in_jevs_next_state(flights_state) -> None:
    model, gateway, helper, _ = _model(
        flights_state,
        [("REQUEST_HUMAN", None), ("TYPE_TEXT", "2")],
        [
            {"text": "Enter your password and sign in", "category": "credentials"},
            {"text": "London"},
        ],
    )
    await model.ainvoke([], _agent_output())

    model.note_from_user("skip the login, just grab the photo")
    await model.ainvoke([], _agent_output())

    assert (
        gateway.requests[1].state["recent_actions"][-1]["note"]
        == "skip the login, just grab the photo"
    )
    assert helper.system_prompt(1) == TEXT_VALUE
    assert helper.context(1)["user_note"] == "skip the login, just grab the photo"


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
    assert goal.startswith("Fly Zurich to London")
    assert "The user then said: skip the login, just tell me the page title" in goal
    assert "skip the login, just tell me the page title" in helper.context(1)["goal"]


async def test_a_note_survives_the_page_change_settle(flights_state) -> None:
    model, _, _, _ = _model(
        flights_state, [("REQUEST_HUMAN", None)], [{"text": "Log in", "category": "credentials"}]
    )
    await model.ainvoke([], _agent_output())
    model.note_from_user("skip the login, just grab the photo")

    model._settle_previous_step(observe(flights_state))

    assert model._history[-1].note == "skip the login, just grab the photo"
    assert model._history[-1].page_changed is False


async def test_a_note_with_no_step_to_carry_it_is_a_wiring_error(flights_state) -> None:
    model, _, _, _ = _model(flights_state, [])

    with pytest.raises(RuntimeError, match="No step to attach a note to"):
        model.note_from_user("skip the login, just grab the photo")
