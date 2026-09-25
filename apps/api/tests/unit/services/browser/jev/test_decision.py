"""What Jev is asked and what it may answer: offered operations, targets, values, and malformed answers refused."""

from __future__ import annotations

import pytest

from app.constants.browser import JEV_MAX_ELEMENTS, JevOperation
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
from app.services.browser.jev.gateway import JevChoiceAnswer, JevEvaluation, JevEvaluationRequest
from app.services.browser.jev.page import PageAction, PageState

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
BUY = _action("e2", 12, "click", "Buy now", role="button")
SIZE_S = _action("e3", 13, "select", "Size → Small", value="s", current_value="Medium")
SIZE_L = _action("e4", 13, "select", "Size → Large", value="l", current_value="Medium")
PASSWORD = _action("e5", 14, "secret", "Password", role="password", value="")
SCROLL = PageAction(id="scroll_down", kind="scroll", label="Scroll down", delta=560)


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
        return JevEvaluation(answers=answers, latency_ms=3)


def test_each_element_gets_one_index_and_a_dropdowns_options_are_its_targets() -> None:
    space = action_space([SEARCH, BUY, SIZE_S, SIZE_L, SCROLL])

    assert [element["index"] for element in space.elements] == ["1", "2", "3"]
    assert space.targets[JevOperation.SELECT] == {"3:1": SIZE_S, "3:2": SIZE_L}
    assert space.targets[JevOperation.CLICK] == {"2": BUY}
    assert space.controls == {JevOperation.SCROLL_DOWN: SCROLL}


def test_a_page_with_more_controls_than_jev_is_offered_is_cut_at_the_limit() -> None:
    many = [_action(f"e{n}", n, "click", f"Link {n}") for n in range(JEV_MAX_ELEMENTS + 5)]

    assert len(action_space(many).elements) == JEV_MAX_ELEMENTS


async def test_the_chosen_element_comes_back_as_its_snapshot_id() -> None:
    jev = _Jev(operation="CLICK", click_target="2")

    decision = await decide(jev, _page(SEARCH, BUY), "buy it", [], [], [])

    assert (decision.operation, decision.action_id, decision.url) == (
        JevOperation.CLICK,
        "e2",
        None,
    )


async def test_only_operations_the_page_and_the_run_allow_are_offered() -> None:
    jev = _Jev(operation="DONE")
    await decide(jev, _page(BUY), "buy it", [], [Visited("Shop", "https://shop.test/")], [])
    assert jev.request is not None
    offered = set(jev.request.questions["operation"].criteria)
    # No field to type into, no address named, and nowhere to go back to.
    assert offered == {"CLICK", "DONE", "BLOCKED"}

    jev = _Jev(operation="DONE")
    visited = [Visited("A", "https://a.test/"), Visited("B", "https://b.test/")]
    await decide(jev, _page(SEARCH), "go to https://c.test", [], visited, ["https://c.test"])
    assert jev.request is not None
    assert {"TYPE_TEXT", "PRESS_ENTER", "NAVIGATE", "GO_BACK"} <= set(
        jev.request.questions["operation"].criteria
    )


async def test_navigate_opens_only_an_offered_address() -> None:
    jev = _Jev(operation="NAVIGATE", navigate_target="U2")

    decision = await decide(
        jev, _page(BUY), "compare", [], [], ["https://a.test/", "https://b.test/"]
    )

    assert decision.url == "https://b.test/"


async def test_an_answer_outside_the_offered_choices_is_refused() -> None:
    class _Rogue(_Jev):
        async def evaluate(self, request: JevEvaluationRequest) -> JevEvaluation:
            return JevEvaluation(answers={"operation": _answer("SUBMIT_ALL", ["SUBMIT_ALL"])})

    with pytest.raises(JevDecisionError):
        await decide(_Rogue(), _page(BUY), "buy it", [], [], [])


async def test_a_missing_confidence_is_a_malformed_answer() -> None:
    class _NoConfidence(_Jev):
        async def evaluate(self, request: JevEvaluationRequest) -> JevEvaluation:
            answer = _answer("DONE", list(request.questions["operation"].criteria))
            return JevEvaluation(
                answers={"operation": answer.model_copy(update={"confidence": None})}
            )

    with pytest.raises(JevDecisionError):
        await decide(_NoConfidence(), _page(BUY), "buy it", [], [], [])


async def test_a_password_field_is_offered_the_runs_secrets_and_nothing_else() -> None:
    jev = _Jev(value="V1")

    value, _ = await choose_value(
        jev, _page(PASSWORD), 'log in as "ada" with "hunter2"', PASSWORD, [], ["password"]
    )

    assert value == "<secret>password</secret>"
    assert jev.request is not None
    assert set(jev.request.questions["value"].criteria) == {"V1", NONE_VALUE}


async def test_any_other_field_is_offered_the_goals_literals_or_a_written_value() -> None:
    jev = _Jev(value="V2")
    history = [RecentAction(action="Search", kind="TYPE_TEXT", text="x", page_changed=False)]

    value, _ = await choose_value(
        jev, _page(SEARCH), 'search "red shoes" then email ada@example.com', SEARCH, history, ["pw"]
    )

    assert value == "ada@example.com"
    assert jev.request is not None
    assert set(jev.request.questions["value"].criteria) == {"V1", "V2", GENERATE, NONE_VALUE}


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


def test_the_pages_a_goal_names_are_its_urls_and_its_bare_sites() -> None:
    assert goal_addresses(
        "open https://a.test/x. then check Wikipedia.org and news.ycombinator.com"
    ) == [
        "https://a.test/x",
        "https://wikipedia.org/",
        "https://news.ycombinator.com/",
    ]
