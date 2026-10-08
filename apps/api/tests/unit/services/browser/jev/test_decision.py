"""What Jev is asked and what it may answer: offered operations, targets, options, values, and malformed answers refused."""

from __future__ import annotations

import math
from typing import cast

import pytest

from app.constants.browser import JEV_MAX_ELEMENTS, JevOperation
from app.services.browser.jev import decision as decision_mod
from app.services.browser.jev.decision import (
    GENERATE,
    NONE_VALUE,
    PAGE_TARGET,
    JevDecisionError,
    RecentAction,
    Situation,
    action_space,
    choose_option,
    choose_value,
    decide,
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
    NEXT_ACTION,
    OPERATIONS,
    OPTION,
    TARGET,
    VALUE,
    VALUE_GENERATE,
    VALUE_NONE,
)

pytestmark = pytest.mark.unit


def _action(action_id: str, node: int, kind: str, label: str, **extra: object) -> PageAction:
    return cast(
        "PageAction", {"id": action_id, "node": node, "kind": kind, "label": label, **extra}
    )


def _page(*actions: PageAction, omitted: int = 0) -> PageState:
    return PageState(
        url="https://shop.test/",
        title="Shop",
        text="Search the shop",
        text_cut=False,
        actions=list(actions),
        page_key=None,
        guards={},
        frames=[],
        fingerprint="f",
        omitted_actions=omitted,
    )


SEARCH = _action("e1", 11, "fill", "Search", role="searchbox", ident="q", value="")
OPEN_SEARCH = _action("e9", 11, "click", "Open Search", role="searchbox", ident="q", value="")
BUY = _action("e2", 12, "click", "Buy now", role="button", ident="", value="")
SIZE = _action(
    "e3",
    13,
    "select",
    "Shirt size",
    role="combobox",
    ident="size",
    value="m",
    current_value="Medium",
    options=[{"value": "s", "label": "Small"}, {"value": "l", "label": "Large"}],
)
PASSWORD = _action(
    "e5", 14, "secret", "Password", role="textbox", ident="pw", value="", filled=False
)
#: A date picker typed as text: the format its value takes is what the field states.
DAY = _action(
    "e6",
    15,
    "fill",
    "Day",
    role="textbox",
    ident="d",
    input_type="text",
    placeholder="dd/mm/yyyy",
    pattern=r"\d{2}/\d{2}/\d{4}",
    value="",
)
LIST = _action("scroll_down_16", 16, "scroll", "Scroll down in Results", delta=240)
SCROLL = PageAction(id="scroll_down", kind="scroll", label="Scroll down the page", delta=560)
LIST_UP = PageAction(
    id="scroll_up_16", node=16, kind="scroll", label="Scroll up in Results", delta=-240
)
WAIT = PageAction(id="wait", kind="wait", label="Wait for the page to update")
ENTER = PageAction(id="enter", kind="enter", node=11, label="Press Enter in Search")


def _answer(choice: str, keys: list[str]) -> dict[str, object]:
    rest = 0.2 / (len(keys) - 1) if len(keys) > 1 else 0.0
    return {
        "type": "choice",
        "choice": choice,
        "probabilities": {
            key: (0.8 if len(keys) > 1 else 1.0) if key == choice else rest for key in keys
        },
    }


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
        return JevEvaluation.model_validate(
            {"answers": answers, "latency_ms": 3, "usage": {"inputTokens": 9}}
        )


class _Answers(_Jev):
    """Answers with the given heads, however malformed."""

    def __init__(self, **answers: object) -> None:
        super().__init__()
        self._answers = answers

    async def evaluate(self, request: JevEvaluationRequest) -> JevEvaluation:
        return JevEvaluation.model_validate({"answers": self._answers})


def _unmasked(text: str) -> str:
    return text


def _asked(jev: _Jev) -> JevEvaluationRequest:
    assert jev.request is not None
    return jev.request


def test_each_element_gets_one_index_and_each_operation_its_own_targets() -> None:
    space = action_space([SEARCH, OPEN_SEARCH, BUY, SIZE, LIST, LIST_UP, SCROLL, WAIT, ENTER])

    assert [(e.index, e.label) for e in space.elements] == [
        ("1", "Search"),
        ("2", "Buy now"),
        ("3", "Shirt size"),
        ("4", "Scroll down in Results"),
    ]
    assert space.targets[JevOperation.TYPE_TEXT] == {"1": SEARCH}
    assert space.targets[JevOperation.CLICK] == {"1": OPEN_SEARCH, "2": BUY}
    # A dropdown is one target; which option it takes is asked once it is chosen.
    assert space.targets[JevOperation.SELECT] == {"3": SIZE}
    # The page scrolls as one target, beside each inner area that scrolls.
    assert space.targets[JevOperation.SCROLL_DOWN] == {PAGE_TARGET: SCROLL, "4": LIST}
    assert space.targets[JevOperation.SCROLL_UP] == {"4": LIST_UP}
    assert space.controls == {JevOperation.WAIT: WAIT, JevOperation.PRESS_ENTER: ENTER}


def test_a_page_with_more_elements_than_one_request_carries_counts_the_ones_left_out() -> None:
    many = [_action(f"e{n}", n, "click", f"Link {n}") for n in range(JEV_MAX_ELEMENTS + 5)]

    space = action_space([*many, WAIT])

    assert len(space.elements) == JEV_MAX_ELEMENTS
    assert space.left_out == 5
    assert space.controls == {JevOperation.WAIT: WAIT}


async def test_jev_is_asked_about_the_page_its_elements_and_what_it_did(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(decision_mod, "JEV_MAX_ELEMENTS", 3)
    jev = _Jev(operation="DONE")
    history = [RecentAction(action="Search", kind="TYPE_TEXT", text="shoes", page_changed=True)]
    page = _page(SEARCH, SIZE, DAY, BUY, omitted=7)

    await decide(jev, Situation(page, "buy", "done", history, _unmasked))

    state = _asked(jev).state
    assert state["page"] == {
        "url": "https://shop.test/",
        "title": "Shop",
        "text": "Search the shop",
    }
    assert state["elements"] == [
        # An empty value says nothing, so it is left out.
        {
            "role": "searchbox",
            "ident": "q",
            "index": "1",
            "label": "Search",
            "operations": ["TYPE_TEXT"],
        },
        # A dropdown shows its current choice, never its options.
        {
            "role": "combobox",
            "ident": "size",
            "value": "Medium",
            "index": "2",
            "label": "Shirt size",
            "operations": ["SELECT"],
        },
        {
            "role": "textbox",
            "ident": "d",
            "input_type": "text",
            "index": "3",
            "label": "Day",
            "operations": ["TYPE_TEXT"],
        },
    ]
    assert state["recent_actions"] == [
        {"action": "Search", "kind": "TYPE_TEXT", "text": "shoes", "page_changed": True}
    ]
    # The snapshot's own cut, and the one a request makes.
    assert state["elements_left_out"] == 8


@pytest.mark.parametrize("href", ["http://[object Object]/", "https://[2001:db8::1/x"])
async def test_a_link_whose_href_is_no_address_is_offered_as_a_link(href: str) -> None:
    """Parsing it raised, which escaped the burst and lost every step the burst had taken."""
    broken = _action("e5", 15, "click", "Broken", role="link", href=href)
    jev = _Jev(operation="DONE")

    await decide(
        jev,
        Situation(_page(broken), "go", "done", [], _unmasked, left=frozenset({"https://x.test/"})),
    )

    assert [e["label"] for e in _asked(jev).state["elements"]] == ["Broken"]


async def test_a_link_to_a_page_this_burst_left_is_not_offered_to_click() -> None:
    """Jev clicked one story, went back and clicked it again, eight times in a burst, to the action cap."""
    story = _action("e5", 15, "click", "Clef", role="link", href="https://blog.test/clef")
    other = _action("e6", 16, "click", "Frog", role="link", href="https://blog.test/frog")
    # The blog's front page, written without its path and with a fragment: the same page.
    front = _action("e7", 17, "click", "Blog", role="link", href="https://blog.test#top")
    jev = _Jev(operation="DONE")

    await decide(
        jev,
        Situation(
            _page(story, other, front),
            "open each",
            "done",
            [],
            _unmasked,
            left=frozenset({"https://blog.test/clef", "https://blog.test/"}),
        ),
    )

    assert [e["label"] for e in _asked(jev).state["elements"]] == ["Frog"]


async def test_the_operation_question_offers_only_what_this_page_and_the_run_allow() -> None:
    jev = _Jev(operation="DONE")

    await decide(
        jev,
        Situation(_page(SEARCH, BUY, SCROLL, WAIT, ENTER), "go", "it went", [], _unmasked),
    )

    question = _asked(jev).questions["operation"]
    # Jev's DONE judges the agent's done_when and nothing else.
    assert question.instructions == {"goal": "go", "done_when": "it went", "rules": NEXT_ACTION}
    assert question.criteria == {
        "TYPE_TEXT": OPERATIONS[JevOperation.TYPE_TEXT],
        "CLICK": OPERATIONS[JevOperation.CLICK],
        "SCROLL_DOWN": OPERATIONS[JevOperation.SCROLL_DOWN],
        # A page-level control is offered under its own label.
        "WAIT": "Wait for the page to update",
        "PRESS_ENTER": "Press Enter in Search",
        "DONE": OPERATIONS[JevOperation.DONE],
        "BLOCKED": OPERATIONS[JevOperation.BLOCKED],
    }

    await decide(
        jev,
        Situation(_page(BUY), "buy it", "done", [], _unmasked),
    )

    # No focused field, so no Enter to press.
    assert set(_asked(jev).questions["operation"].criteria) == {"CLICK", "DONE", "BLOCKED"}


@pytest.mark.parametrize(
    ("choices", "target"),
    [
        ({"operation": "CLICK", "click_target": "2"}, BUY),
        ({"operation": "SELECT", "select_target": "3"}, SIZE),
        ({"operation": "SCROLL_DOWN", "scroll_down_target": "4"}, LIST),
        ({"operation": "SCROLL_DOWN", "scroll_down_target": PAGE_TARGET}, SCROLL),
        ({"operation": "WAIT"}, WAIT),
        ({"operation": "DONE"}, None),
    ],
)
async def test_the_decision_names_the_chosen_snapshot_action(
    choices: dict[str, str], target: PageAction | None
) -> None:
    decision = await decide(
        _Jev(**choices),
        Situation(_page(SEARCH, BUY, SIZE, LIST, SCROLL, WAIT), "buy", "done", [], _unmasked),
    )

    assert (decision.operation, decision.target) == (JevOperation(choices["operation"]), target)
    assert (decision.latency_ms, decision.evaluation.usage) == (3, JevUsage(inputTokens=9))


async def test_a_chosen_dropdown_is_asked_which_of_its_options_to_set() -> None:
    jev = _Jev(option="O2")
    history = [RecentAction(action="Buy now", kind="CLICK", text=None, page_changed=True)]

    chosen, evaluation = await choose_option(
        jev, Situation(_page(SIZE), "a large one", "done", history, _unmasked), SIZE
    )

    assert (chosen["value"], chosen["current_value"], "options" in chosen) == ("l", "Large", False)
    assert evaluation.latency_ms == 3
    question = _asked(jev).questions["option"]
    assert question.criteria == {"O1": "Small", "O2": "Large"}
    assert question.instructions == {
        "goal": "a large one",
        "field": {"label": "Shirt size", "current_value": "Medium"},
        "rules": OPTION,
    }
    assert _asked(jev).state == {
        "page": {"url": "https://shop.test/", "title": "Shop", "text": "Search the shop"},
        "recent_actions": [{"action": "Buy now", "text": None}],
    }


async def test_each_target_question_shows_its_candidates_as_they_stand_now() -> None:
    jev = _Jev(operation="DONE")
    named = _action("e7", 17, "fill", "Name", role="textbox", ident="name", value="Ada")

    await decide(
        jev, Situation(_page(named, BUY, SIZE, SCROLL), "check out", "done", [], _unmasked)
    )

    questions = _asked(jev).questions
    assert questions["type_text_target"].criteria == {
        "1": {"element": "[1] Name", "current_value": "Ada", "role": "textbox", "ident": "name"}
    }
    # A dropdown shows the option it holds, not its value; the page scrolls as one target.
    assert questions["select_target"].criteria == {
        "3": {
            "element": "[3] Shirt size",
            "current_value": "Medium",
            "role": "combobox",
            "ident": "size",
        }
    }
    assert questions["scroll_down_target"].criteria == {
        PAGE_TARGET: {"element": f"[{PAGE_TARGET}] Scroll down the page", "current_value": ""}
    }
    assert questions["click_target"].instructions == {
        "goal": "check out",
        "operation": "CLICK",
        "rules": [NEXT_ACTION, TARGET],
    }


def _choice(choice: str, **probabilities: float) -> JevChoiceAnswer:
    return JevChoiceAnswer(type="choice", choice=choice, probabilities=probabilities)


@pytest.mark.parametrize(
    "answer",
    [
        pytest.param(_choice("SUBMIT_ALL", SUBMIT_ALL=1.0).model_dump(), id="not-offered"),
        pytest.param(_choice("DONE", DONE=1.0).model_dump(), id="probabilities-miss-options"),
        pytest.param(
            _choice("DONE", DONE=1.2, BLOCKED=-0.2).model_dump(), id="negative-probability"
        ),
        pytest.param(_choice("DONE", DONE=1.01, BLOCKED=0.0).model_dump(), id="above-one"),
        pytest.param(_choice("DONE", DONE=math.nan, BLOCKED=0.2).model_dump(), id="not-a-number"),
        pytest.param(
            _choice("DONE", DONE=0.5, BLOCKED=0.3).model_dump(), id="probabilities-sum-short"
        ),
        pytest.param(
            _choice("BLOCKED", DONE=0.8, BLOCKED=0.2).model_dump(), id="not-the-most-likely"
        ),
        pytest.param({"type": "choice"}, id="no-choice"),
    ],
)
async def test_a_malformed_answer_is_refused_and_nothing_is_executed(answer: object) -> None:
    with pytest.raises(JevDecisionError, match=decision_mod._INVALID_ANSWER):
        await decide(
            _Answers(operation=answer), Situation(_page(), "buy it", "done", [], _unmasked)
        )


async def test_no_answer_is_refused() -> None:
    with pytest.raises(JevDecisionError, match=decision_mod._NO_ANSWER):
        await decide(_Answers(), Situation(_page(), "buy it", "done", [], _unmasked))


async def test_a_target_answer_is_validated_like_the_operation() -> None:
    with pytest.raises(JevDecisionError, match=decision_mod._NO_ANSWER):
        await decide(
            _Jev(operation="CLICK"), Situation(_page(BUY), "buy it", "done", [], _unmasked)
        )
    with pytest.raises(JevDecisionError, match=decision_mod._INVALID_ANSWER):
        await decide(
            _Jev(operation="CLICK", click_target="7"),
            Situation(_page(BUY), "buy it", "done", [], _unmasked),
        )


async def test_a_malformed_head_the_decision_does_not_read_costs_nothing() -> None:
    operation = _answer("DONE", ["CLICK", "DONE", "BLOCKED"])

    decision = await decide(
        _Answers(operation=operation, click_target={"type": "choice", "choice": 7}),
        Situation(_page(BUY), "buy it", "done", [], _unmasked),
    )

    assert decision.operation is JevOperation.DONE


@pytest.mark.parametrize(
    "answer",
    [
        pytest.param(_choice("DONE", DONE=1.0, BLOCKED=0.0), id="certain"),
        pytest.param(_choice("DONE", DONE=0.5, BLOCKED=0.5), id="tied"),
        pytest.param(
            _choice("DONE", DONE=0.5 - decision_mod._TIE_TOLERANCE, BLOCKED=0.5),
            id="tied-within-noise",
        ),
    ],
)
async def test_an_answer_at_the_edges_of_valid_is_taken(answer: JevChoiceAnswer) -> None:
    decision = await decide(
        _Answers(operation=answer.model_dump()), Situation(_page(), "buy it", "done", [], _unmasked)
    )

    assert decision.operation is JevOperation.DONE


async def test_probabilities_off_by_exactly_the_tolerance_are_refused(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(decision_mod, "JEV_PROBABILITY_SUM_TOLERANCE", 0.25)

    with pytest.raises(JevDecisionError):
        await decide(
            _Answers(operation=_choice("DONE", DONE=0.75, BLOCKED=0.5).model_dump()),
            Situation(_page(), "g", "done", [], _unmasked),
        )


async def test_a_password_field_is_offered_the_runs_secrets_and_nothing_else() -> None:
    jev = _Jev(value="V1")

    value, _ = await choose_value(
        jev,
        Situation(_page(PASSWORD), 'log in as "ada"', "done", [], _unmasked),
        PASSWORD,
        ["password"],
    )

    assert value == "<secret>password</secret>"
    assert _asked(jev).questions["value"].criteria == {
        "V1": "<secret>password</secret>",
        NONE_VALUE: VALUE_NONE,
    }


async def test_any_other_field_is_offered_the_goals_literals_the_secrets_or_a_written_value() -> (
    None
):
    jev = _Jev(value="V2")
    history = [RecentAction(action="Search", kind="TYPE_TEXT", text="x", page_changed=False)]

    value, evaluation = await choose_value(
        jev,
        Situation(_page(DAY), 'book "red shoes" for ada@example.com', "done", history, _unmasked),
        DAY,
        ["user"],
    )

    assert value == "ada@example.com"
    assert evaluation.latency_ms == 3
    request = _asked(jev)
    question = request.questions["value"]
    assert question.criteria == {
        "V1": "red shoes",
        "V2": "ada@example.com",
        "V3": "<secret>user</secret>",
        GENERATE: VALUE_GENERATE,
        NONE_VALUE: VALUE_NONE,
    }
    assert question.instructions == {
        "goal": 'book "red shoes" for ada@example.com',
        "field": {
            "label": "Day",
            "role": "textbox",
            "ident": "d",
            "input_type": "text",
            "placeholder": "dd/mm/yyyy",
            "pattern": r"\d{2}/\d{2}/\d{4}",
            "value": "",
        },
        "rules": VALUE,
    }
    assert request.state == {
        "page": {"url": "https://shop.test/", "title": "Shop", "text": "Search the shop"},
        "recent_actions": [{"action": "Search", "text": "x"}],
    }


@pytest.mark.parametrize("choice", [GENERATE, NONE_VALUE])
async def test_a_field_with_no_literal_comes_back_as_generate_or_none(choice: str) -> None:
    value, _ = await choose_value(
        _Jev(value=choice),
        Situation(_page(SEARCH), "find shoes", "done", [], _unmasked),
        SEARCH,
        [],
    )

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
