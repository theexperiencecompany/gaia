"""What Jev is asked and what it may answer: offered operations, targets, values, and malformed answers refused."""

from __future__ import annotations

import math

import pytest

from app.constants.browser import JEV_MAX_ELEMENTS, JevOperation
from app.services.browser.jev import decision as decision_mod
from app.services.browser.jev.decision import (
    GENERATE,
    NONE_VALUE,
    JevDecisionError,
    RecentAction,
    Visited,
    action_space,
    choose_value,
    decide,
    goal_addresses,
    literals,
)
from app.services.browser.jev.gateway import (
    JevChoiceAnswer,
    JevEvaluation,
    JevEvaluationRequest,
    JevUsage,
)
from app.services.browser.jev.page import PageAction, PageState
from app.services.browser.jev.questions import (
    NAVIGATE_TARGET,
    NEXT_ACTION,
    OPERATIONS,
    TARGET,
    VALUE,
    VALUE_GENERATE,
    VALUE_NONE,
)

pytestmark = pytest.mark.unit


def _action(action_id: str, node: int, kind: str, label: str, **extra: object) -> PageAction:
    return PageAction(id=action_id, node=node, kind=kind, label=label, **extra)  # type: ignore[typeddict-item]  # a test's own snapshot row


def _page(*actions: PageAction) -> PageState:
    return PageState(
        url="https://shop.test/",
        title="Shop",
        text="Search the shop",
        actions=list(actions),
        marker=None,
        page_key=None,
        guards={},
        frames=[],
        fingerprint="f",
    )


SEARCH = _action("e1", 11, "fill", "Search", role="searchbox", ident="q", value="")
OPEN_SEARCH = _action("e9", 11, "click", "Open Search", role="searchbox", ident="q", value="")
BUY = _action("e2", 12, "click", "Buy now", role="button", ident="", value="")
SIZE_S = _action(
    "e3",
    13,
    "select",
    "Shirt size → Small",
    role="combobox",
    ident="size",
    value="s",
    current_value="Medium",
)
SIZE_L = _action(
    "e4",
    13,
    "select",
    "Shirt size → Large",
    role="combobox",
    ident="size",
    value="l",
    current_value="Medium",
)
PASSWORD = _action(
    "e5", 14, "secret", "Password", role="textbox", ident="pw", value="", filled=False
)
NAME = _action("e6", 15, "fill", "Name", role="textbox", ident="name", value="Ada")
REMEMBER = _action(
    "e7", 16, "click", "Remember me", role="checkbox", ident="", value="on", checked="true"
)
REVIEWS = _action(
    "e8", 17, "click", "Reviews", role="tab", ident="", value="", selected="false", expanded="true"
)
SCROLL = PageAction(id="scroll_down", kind="scroll", label="Scroll down", delta=560)
WAIT = PageAction(id="wait", kind="wait", label="Wait for the page to update")


def _answer(choice: str, keys: list[str]) -> JevChoiceAnswer:
    rest = 0.2 / (len(keys) - 1) if len(keys) > 1 else 0.0
    return JevChoiceAnswer(
        type="choice",
        choice=choice,
        probabilities={
            key: (0.8 if len(keys) > 1 else 1.0) if key == choice else rest for key in keys
        },
        confidence=0.8,
    )


class _Jev:
    """Answers each question with the scripted choice, and keeps the request it was sent."""

    model = "jev-test"

    def __init__(self, **choices: str) -> None:
        self._choices = choices
        self.request: JevEvaluationRequest | None = None

    async def evaluate(self, request: JevEvaluationRequest) -> JevEvaluation:
        self.request = request
        answers = {
            name: _answer(self._choices[name], list(question.criteria))
            for name, question in request.questions.items()
            if name in self._choices
        }
        return JevEvaluation(answers=answers, latency_ms=3, usage=JevUsage(inputTokens=9))


class _Answers(_Jev):
    """Answers the operation question with a given answer, however malformed."""

    def __init__(self, answer: JevChoiceAnswer | None) -> None:
        super().__init__()
        self._answer = answer

    async def evaluate(self, request: JevEvaluationRequest) -> JevEvaluation:
        answers = {} if self._answer is None else {"operation": self._answer}
        return JevEvaluation(answers=answers)


def _asked(jev: _Jev) -> JevEvaluationRequest:
    assert jev.request is not None
    return jev.request


def test_each_element_gets_one_index_and_a_dropdowns_options_are_its_targets() -> None:
    space = action_space([SEARCH, BUY, SIZE_S, SIZE_L, SCROLL])

    assert [element.index for element in space.elements] == ["1", "2", "3"]
    assert space.targets[JevOperation.SELECT] == {"3:1": SIZE_S, "3:2": SIZE_L}
    assert space.targets[JevOperation.CLICK] == {"2": BUY}
    assert space.controls == {JevOperation.SCROLL_DOWN: SCROLL}


def test_controls_ahead_of_the_elements_do_not_hide_them() -> None:
    space = action_space([SCROLL, WAIT, BUY])

    assert space.controls == {JevOperation.SCROLL_DOWN: SCROLL, JevOperation.WAIT: WAIT}
    assert space.targets[JevOperation.CLICK] == {"1": BUY}


def test_a_page_with_more_controls_than_jev_is_offered_is_cut_at_the_limit_and_keeps_its_controls() -> (
    None
):
    many = [_action(f"e{n}", n, "click", f"Link {n}") for n in range(JEV_MAX_ELEMENTS + 5)]

    space = action_space([*many, SCROLL])

    assert len(space.elements) == JEV_MAX_ELEMENTS
    assert space.controls == {JevOperation.SCROLL_DOWN: SCROLL}


async def test_jev_is_asked_about_the_page_its_elements_what_it_did_and_where_it_has_been() -> None:
    jev = _Jev(operation="DONE")
    history = [RecentAction(action="Search", kind="TYPE_TEXT", text="shoes", page_changed=True)]
    visited = [Visited("Home", "https://shop.test/"), Visited("Results", "https://shop.test/r")]
    page = _page(
        SEARCH, OPEN_SEARCH, BUY, SIZE_S, SIZE_L, PASSWORD, NAME, REMEMBER, REVIEWS, SCROLL
    )

    await decide(jev, page, "buy shoes", history, visited, [])

    assert _asked(jev).state == {
        "page": {"url": "https://shop.test/", "title": "Shop", "text": "Search the shop"},
        "elements": [
            # An empty value says nothing, so it is left out; a field typed into keeps its value.
            {
                "role": "searchbox",
                "ident": "q",
                "index": "1",
                "label": "Search",
                "operations": ["TYPE_TEXT", "CLICK"],
            },
            {"role": "button", "index": "2", "label": "Buy now", "operations": ["CLICK"]},
            {
                "role": "combobox",
                "ident": "size",
                "value": "Medium",
                "index": "3",
                "label": "Shirt size",
                "operations": ["SELECT"],
                "options": [
                    {"index": "3:1", "label": "Shirt size → Small", "value": "s"},
                    {"index": "3:2", "label": "Shirt size → Large", "value": "l"},
                ],
            },
            {
                "role": "textbox",
                "ident": "pw",
                "filled": False,
                "index": "4",
                "label": "Password",
                "operations": ["TYPE_TEXT"],
            },
            {
                "role": "textbox",
                "ident": "name",
                "value": "Ada",
                "index": "5",
                "label": "Name",
                "operations": ["TYPE_TEXT"],
            },
            {
                "role": "checkbox",
                "value": "on",
                "checked": "true",
                "index": "6",
                "label": "Remember me",
                "operations": ["CLICK"],
            },
            {
                "role": "tab",
                "selected": "false",
                "expanded": "true",
                "index": "7",
                "label": "Reviews",
                "operations": ["CLICK"],
            },
        ],
        "recent_actions": [
            {"action": "Search", "kind": "TYPE_TEXT", "text": "shoes", "page_changed": True}
        ],
        "visited": [
            {"title": "Home", "url": "https://shop.test/"},
            {"title": "Results", "url": "https://shop.test/r"},
        ],
    }


async def test_the_operation_question_offers_what_the_page_and_the_run_allow_under_the_goal() -> (
    None
):
    jev = _Jev(operation="DONE")
    visited = [Visited("A", "https://a.test/"), Visited("B", "https://b.test/")]

    await decide(
        jev, _page(SEARCH, BUY, SIZE_S, SCROLL, WAIT), "go", [], visited, ["https://c.test/"]
    )

    question = _asked(jev).questions["operation"]
    assert question.instructions == {"goal": "go", "rules": NEXT_ACTION}
    assert question.criteria == {
        "TYPE_TEXT": OPERATIONS[JevOperation.TYPE_TEXT],
        "CLICK": OPERATIONS[JevOperation.CLICK],
        "SELECT": OPERATIONS[JevOperation.SELECT],
        # A control is offered under its own label.
        "SCROLL_DOWN": "Scroll down",
        "WAIT": "Wait for the page to update",
        "PRESS_ENTER": OPERATIONS[JevOperation.PRESS_ENTER],
        "NAVIGATE": OPERATIONS[JevOperation.NAVIGATE],
        "GO_BACK": OPERATIONS[JevOperation.GO_BACK],
        "DONE": OPERATIONS[JevOperation.DONE],
        "BLOCKED": OPERATIONS[JevOperation.BLOCKED],
    }


async def test_only_operations_the_page_and_the_run_allow_are_offered() -> None:
    jev = _Jev(operation="DONE")

    await decide(jev, _page(BUY), "buy it", [], [Visited("Shop", "https://shop.test/")], [])

    # No field to type into, no address named, and nowhere to go back to.
    assert set(_asked(jev).questions["operation"].criteria) == {"CLICK", "DONE", "BLOCKED"}


async def test_each_target_question_offers_that_operations_own_targets_as_they_stand_now() -> None:
    jev = _Jev(operation="DONE")
    page = _page(NAME, REMEMBER, REVIEWS, SIZE_S, SIZE_L, PASSWORD)

    await decide(jev, page, "check out", [], [], ["https://a.test/", "https://b.test/"])

    questions = _asked(jev).questions
    assert questions["type_text_target"].criteria == {
        "1": {"element": "[1] Name", "current_value": "Ada", "role": "textbox", "ident": "name"},
        "5": {
            "element": "[5] Password",
            "current_value": "",
            "role": "textbox",
            "ident": "pw",
            "filled": False,
        },
    }
    assert questions["click_target"].criteria == {
        "2": {
            "element": "[2] Remember me",
            "current_value": "on",
            "role": "checkbox",
            "ident": "",
            "checked": "true",
        },
        "3": {
            "element": "[3] Reviews",
            "current_value": "",
            "role": "tab",
            "ident": "",
            "selected": "false",
            "expanded": "true",
        },
    }
    # A dropdown option shows the dropdown's current choice, not its own value.
    assert questions["select_target"].criteria["4:2"] == {
        "element": "[4:2] Shirt size → Large",
        "current_value": "Medium",
        "role": "combobox",
        "ident": "size",
    }
    assert questions["select_target"].instructions == {
        "goal": "check out",
        "operation": "SELECT",
        "rules": [NEXT_ACTION, TARGET],
    }
    assert questions["navigate_target"].criteria == {
        "U1": "https://a.test/",
        "U2": "https://b.test/",
    }
    assert questions["navigate_target"].instructions == {
        "goal": "check out",
        "operation": "NAVIGATE",
        "rules": NAVIGATE_TARGET,
    }


@pytest.mark.parametrize(
    ("choices", "action_id", "url"),
    [
        ({"operation": "CLICK", "click_target": "2"}, "e2", None),
        ({"operation": "SELECT", "select_target": "3:2"}, "e4", None),
        ({"operation": "SCROLL_DOWN"}, "scroll_down", None),
        ({"operation": "NAVIGATE", "navigate_target": "U2"}, None, "https://b.test/"),
        ({"operation": "DONE"}, None, None),
    ],
)
async def test_the_decision_names_the_chosen_snapshot_action_or_address(
    choices: dict[str, str], action_id: str | None, url: str | None
) -> None:
    jev = _Jev(**choices)

    decision = await decide(
        jev,
        _page(SEARCH, BUY, SIZE_S, SIZE_L, SCROLL),
        "buy",
        [],
        [],
        ["https://a.test/", "https://b.test/"],
    )

    assert (decision.operation, decision.action_id, decision.url) == (
        JevOperation(choices["operation"]),
        action_id,
        url,
    )
    assert (decision.confidence, decision.latency_ms) == (0.8, 3)
    assert decision.evaluation.usage == JevUsage(inputTokens=9)


async def test_a_target_answer_is_validated_like_the_operation() -> None:
    jev = _Jev(operation="CLICK", click_target="7")

    with pytest.raises(JevDecisionError, match=decision_mod._NO_ANSWER):
        await decide(_Jev(operation="CLICK"), _page(BUY), "buy it", [], [], [])
    with pytest.raises(JevDecisionError, match=decision_mod._INVALID_ANSWER):
        await decide(jev, _page(BUY), "buy it", [], [], [])


def _choice(choice: str, confidence: float | None = 0.8, **probabilities: float) -> JevChoiceAnswer:
    return JevChoiceAnswer(
        type="choice", choice=choice, probabilities=probabilities, confidence=confidence
    )


@pytest.mark.parametrize(
    "answer",
    [
        pytest.param(_choice("SUBMIT_ALL", SUBMIT_ALL=1.0), id="not-offered"),
        pytest.param(_choice("DONE", DONE=1.0), id="probabilities-miss-options"),
        pytest.param(_choice("DONE", None, DONE=0.8, BLOCKED=0.2), id="no-confidence"),
        pytest.param(_choice("DONE", 1.2, DONE=0.8, BLOCKED=0.2), id="confidence-above-one"),
        pytest.param(_choice("DONE", -0.1, DONE=0.8, BLOCKED=0.2), id="confidence-below-zero"),
        pytest.param(_choice("DONE", 0.8, DONE=1.2, BLOCKED=-0.2), id="negative-probability"),
        pytest.param(_choice("DONE", math.nan, DONE=0.8, BLOCKED=0.2), id="not-a-number"),
        pytest.param(_choice("DONE", 0.8, DONE=0.5, BLOCKED=0.3), id="probabilities-sum-short"),
        pytest.param(_choice("BLOCKED", 0.8, DONE=0.8, BLOCKED=0.2), id="not-the-most-likely"),
    ],
)
async def test_a_malformed_answer_is_refused_and_nothing_is_executed(
    answer: JevChoiceAnswer,
) -> None:
    with pytest.raises(JevDecisionError, match=decision_mod._INVALID_ANSWER):
        await decide(_Answers(answer), _page(), "buy it", [], [], [])


async def test_no_answer_is_refused() -> None:
    with pytest.raises(JevDecisionError, match=decision_mod._NO_ANSWER):
        await decide(_Answers(None), _page(), "buy it", [], [], [])


@pytest.mark.parametrize(
    "answer",
    [
        pytest.param(_choice("DONE", 1.0, DONE=1.0, BLOCKED=0.0), id="certain"),
        pytest.param(_choice("DONE", 0.0, DONE=0.5, BLOCKED=0.5), id="tied-and-unsure"),
        pytest.param(
            _choice("DONE", 0.5, DONE=0.5 - decision_mod._TIE_TOLERANCE, BLOCKED=0.5),
            id="tied-within-noise",
        ),
    ],
)
async def test_an_answer_at_the_edges_of_valid_is_taken(answer: JevChoiceAnswer) -> None:
    decision = await decide(_Answers(answer), _page(), "buy it", [], [], [])

    assert (decision.operation, decision.confidence) == (JevOperation.DONE, answer.confidence)


async def test_probabilities_off_by_exactly_the_tolerance_are_refused(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(decision_mod, "JEV_PROBABILITY_SUM_TOLERANCE", 0.25)

    with pytest.raises(JevDecisionError):
        await decide(
            _Answers(_choice("DONE", 0.8, DONE=0.75, BLOCKED=0.5)), _page(), "g", [], [], []
        )


async def test_a_password_field_is_offered_the_runs_secrets_and_nothing_else() -> None:
    jev = _Jev(value="V1")

    value, _ = await choose_value(
        jev, _page(PASSWORD), 'log in as "ada" with "hunter2"', PASSWORD, [], ["password"]
    )

    assert value == "<secret>password</secret>"
    assert _asked(jev).questions["value"].criteria == {
        "V1": "<secret>password</secret>",
        NONE_VALUE: VALUE_NONE,
    }


async def test_any_other_field_is_offered_the_goals_literals_or_a_written_value() -> None:
    jev = _Jev(value="V2")
    history = [RecentAction(action="Search", kind="TYPE_TEXT", text="x", page_changed=False)]

    value, evaluation = await choose_value(
        jev, _page(SEARCH), 'search "red shoes" then email ada@example.com', SEARCH, history, ["pw"]
    )

    assert value == "ada@example.com"
    assert evaluation.latency_ms == 3
    request = _asked(jev)
    question = request.questions["value"]
    assert question.criteria == {
        "V1": "red shoes",
        "V2": "ada@example.com",
        GENERATE: VALUE_GENERATE,
        NONE_VALUE: VALUE_NONE,
    }
    assert question.instructions == {
        "goal": 'search "red shoes" then email ada@example.com',
        "field": {"label": "Search", "role": "searchbox", "ident": "q", "value": ""},
        "rules": VALUE,
    }
    assert request.state == {
        "page": {"url": "https://shop.test/", "title": "Shop", "text": "Search the shop"},
        "recent_actions": [{"action": "Search", "text": "x"}],
    }


@pytest.mark.parametrize("choice", [GENERATE, NONE_VALUE])
async def test_a_field_with_no_literal_comes_back_as_generate_or_none(choice: str) -> None:
    value, _ = await choose_value(_Jev(value=choice), _page(SEARCH), "find shoes", SEARCH, [], [])

    assert value == choice


def test_a_goal_spells_out_quoted_text_emails_dates_and_urls_but_never_a_secret() -> None:
    goal = (
        'type "Aryan" and “Two words”, mail ada@example.com on 09/22/2026 at '
        "https://forms.test/a?x=1, password <secret>password</secret>"
    )

    assert literals(goal) == [
        "Aryan",
        "Two words",
        "ada@example.com",
        "09/22/2026",
        "https://forms.test/a?x=1",
    ]


def test_a_literal_keeps_its_own_last_character_and_drops_the_sentences() -> None:
    assert literals("open https://a.test/?id=AX. then mail AX@EXAMPLE.BOX!") == [
        "AX@EXAMPLE.BOX",
        "https://a.test/?id=AX",
    ]


def test_the_pages_a_goal_names_are_its_urls_and_its_bare_sites() -> None:
    assert goal_addresses(
        "open https://a.test/X. then check Wikipedia.org and news.ycombinator.com"
    ) == [
        "https://a.test/X",
        "https://wikipedia.org/",
        "https://news.ycombinator.com/",
    ]


def test_a_site_inside_a_url_is_not_a_second_address() -> None:
    assert goal_addresses("see https://docs.example.com/guide") == [
        "https://docs.example.com/guide"
    ]
