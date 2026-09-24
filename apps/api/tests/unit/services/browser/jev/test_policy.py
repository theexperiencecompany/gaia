"""Question building and answer validation — jev-ultrafast's choose/validate_choice."""

from __future__ import annotations

import pytest

from app.constants.browser import JEV_MAX_ELEMENTS, JevOperation
from app.services.browser.jev import prompts
from app.services.browser.jev.gateway import JevChoiceAnswer, JevEvaluation, JevUsage
from app.services.browser.jev.observation import observe
from app.services.browser.jev.policy import (
    JevDecisionError,
    JevHistoryEntry,
    build_request,
    resolve,
)
from app.services.browser.jev.prompts import (
    HUMAN_RULES,
    NAVIGATE_RULE,
    NEXT_ACTION,
    TARGET,
)

from .conftest import FakeAXNode, FakeNode, make_state

pytestmark = pytest.mark.unit

ALL = frozenset(JevOperation)


def _answer(choice: str, keys: list[str]) -> JevChoiceAnswer:
    rest = (1 - 0.9) / (len(keys) - 1) if len(keys) > 1 else 0
    return JevChoiceAnswer(
        type="choice",
        choice=choice,
        probabilities={k: (0.9 if k == choice else rest) for k in keys},
    )


def test_the_request_shares_one_state_across_an_operation_head_and_one_target_head_per_element_operation(
    flights_state,
) -> None:
    observation = observe(flights_state)
    history = [JevHistoryEntry(action="CLICK [1] Zurich", kind="click", page_changed=True)]

    request = build_request(observation, "Fly to London", history, ALL)

    assert set(request.questions) == {
        "operation",
        "click_target",
        "type_text_target",
        "select_target",
    }
    assert request.state["page"] == {"url": "https://x", "title": "X", "text": observation.text}
    assert [e["index"] for e in request.state["elements"]] == ["1", "2", "3", "4", "5"]
    assert request.state["recent_actions"] == [
        {
            "action": "CLICK [1] Zurich",
            "kind": "click",
            "text": None,
            "page_changed": True,
            "url": None,
            "note": None,
        }
    ]
    operation = request.questions["operation"]
    assert operation.instructions == {
        "goal": "Fly to London",
        "rules": [NEXT_ACTION, HUMAN_RULES, NAVIGATE_RULE, prompts.STILL_NEEDED_RULE],
    }
    assert set(operation.criteria) == {op.value for op in JevOperation}
    target = request.questions["type_text_target"]
    assert target.instructions == {
        "goal": "Fly to London",
        "operation": "TYPE_TEXT",
        "rules": [NEXT_ACTION, TARGET],
    }
    assert set(target.criteria) == {"1", "2"}
    assert (
        request.questions["select_target"].criteria["3:2"]["element"]
        == "[3] Cabin class → Business"
    )


def test_only_registered_operations_are_offered_and_targetless_ones_are_dropped(
    flights_state,
) -> None:
    observation = observe(flights_state)

    request = build_request(
        observation, "g", [], frozenset({JevOperation.CLICK, JevOperation.DONE, JevOperation.WAIT})
    )

    assert set(request.questions) == {"operation", "click_target"}
    assert set(request.questions["operation"].criteria) == {"CLICK", "DONE", "WAIT"}


def test_an_element_operation_with_no_candidates_is_not_offered() -> None:
    from .conftest import FakeNode, make_state

    observation = observe(make_state({1: FakeNode("BUTTON", text="Go")}))

    request = build_request(observation, "g", [], ALL)

    assert "TYPE_TEXT" not in request.questions["operation"].criteria
    assert "SELECT" not in request.questions["operation"].criteria
    assert "type_text_target" not in request.questions


def test_history_is_capped_to_the_most_recent_entries(flights_state, monkeypatch) -> None:
    monkeypatch.setattr("app.services.browser.jev.policy.JEV_RECENT_ACTIONS", 2)
    history = [JevHistoryEntry(action=str(i), kind="click") for i in range(5)]

    request = build_request(observe(flights_state), "g", history, ALL)

    assert [h["action"] for h in request.state["recent_actions"]] == ["3", "4"]


def test_resolve_reads_only_the_target_head_the_operation_selects(flights_state) -> None:
    observation = observe(flights_state)
    request = build_request(observation, "g", [], ALL)
    ops = list(request.questions["operation"].criteria)
    evaluation = JevEvaluation(
        answers={
            "operation": _answer("TYPE_TEXT", ops),
            "type_text_target": _answer("2", ["1", "2"]),
            # The unused click head is garbage; it must never be read.
            "click_target": JevChoiceAnswer(type="choice", choice="nope", probabilities={}),
        },
        usage=JevUsage(inputTokens=10, outputTokens=1),
    )

    decision = resolve(request, evaluation, observation)

    assert decision.operation is JevOperation.TYPE_TEXT
    assert decision.element is not None
    assert (decision.element.index, decision.element.browser_index) == (2, 23)
    assert decision.target == "2"
    assert decision.confidence == pytest.approx(0.9)
    assert decision.target_probabilities == {"1": pytest.approx(0.1), "2": pytest.approx(0.9)}
    assert decision.label == "TYPE_TEXT [2] Where to?"


def test_resolve_a_select_carries_the_option(flights_state) -> None:
    observation = observe(flights_state)
    request = build_request(observation, "g", [], ALL)
    ops = list(request.questions["operation"].criteria)
    evaluation = JevEvaluation(
        answers={
            "operation": _answer("SELECT", ops),
            "select_target": _answer("3:2", ["3:1", "3:2"]),
        }
    )

    decision = resolve(request, evaluation, observation)

    assert decision.option is not None
    assert decision.option.label == "Business"
    assert decision.label == "SELECT [3] Cabin class → Business"


def test_resolve_a_control_operation_needs_no_target(flights_state) -> None:
    observation = observe(flights_state)
    request = build_request(observation, "g", [], ALL)
    ops = list(request.questions["operation"].criteria)

    decision = resolve(
        request, JevEvaluation(answers={"operation": _answer("DONE", ops)}), observation
    )

    assert decision.operation is JevOperation.DONE
    assert decision.element is None
    assert decision.label == "DONE"


@pytest.mark.parametrize(
    ("choice", "probabilities"),
    [
        ("NOPE", {"DONE": 1.0, "WAIT": 0.0}),  # not offered
        ("DONE", {"DONE": 1.0}),  # distribution missing a key
        ("DONE", {"DONE": 0.6, "WAIT": 0.6}),  # does not sum to 1
        ("DONE", {"DONE": 0.2, "WAIT": 0.8}),  # choice is not the argmax
        ("DONE", {"DONE": float("nan"), "WAIT": 0.0}),  # non-finite
    ],
)
def test_an_invalid_operation_answer_executes_nothing(flights_state, choice, probabilities) -> None:
    observation = observe(flights_state)
    request = build_request(observation, "g", [], frozenset({JevOperation.DONE, JevOperation.WAIT}))
    evaluation = JevEvaluation(
        answers={
            "operation": JevChoiceAnswer(type="choice", choice=choice, probabilities=probabilities)
        }
    )

    with pytest.raises(JevDecisionError, match="Invalid Jev response"):
        resolve(request, evaluation, observation)


def test_a_missing_target_head_executes_nothing(flights_state) -> None:
    observation = observe(flights_state)
    request = build_request(observation, "g", [], ALL)
    ops = list(request.questions["operation"].criteria)

    with pytest.raises(JevDecisionError, match="no answer"):
        resolve(request, JevEvaluation(answers={"operation": _answer("CLICK", ops)}), observation)


def _three_hundred_clickables():
    return make_state(
        {
            i: FakeNode(
                "BUTTON",
                text=f"Button {i}",
                ax_node=FakeAXNode(role="button", name=f"Button {i}"),
            )
            for i in range(300)
        }
    )


def test_a_target_head_never_exceeds_the_gateways_choice_limit() -> None:
    """The gateway 400s a question with more than 255 criteria, killing the run."""
    request = build_request(observe(_three_hundred_clickables()), "click something", [], ALL)

    assert len(request.questions["click_target"].criteria) == JEV_MAX_ELEMENTS


def test_jev_sees_one_capped_element_table_that_every_target_head_draws_from() -> None:
    """Regression: the whole page went as state.elements, so Wikipedia 400d on max_tokens_exceeded."""
    request = build_request(observe(_three_hundred_clickables()), "click something", [], ALL)

    indexes = {e["index"] for e in request.state["elements"]}

    assert len(request.state["elements"]) == JEV_MAX_ELEMENTS
    for name, question in request.questions.items():
        if name == "operation":
            continue
        assert {key.split(":")[0] for key in question.criteria} <= indexes
        assert question.criteria


def test_a_screen_too_dense_to_list_tells_jev_how_many_it_left_out_and_how_to_reach_them() -> None:
    """A silent cut made a control lower on a dense screen impossible to choose, with no way to know."""
    request = build_request(observe(_three_hundred_clickables()), "click something", [], ALL)

    page = request.state["page"]

    assert page["elements_listed"] == JEV_MAX_ELEMENTS
    assert page["elements_on_screen"] == 300
    assert page["elements_note"]


def test_a_screen_that_fits_carries_no_note_about_missing_elements(flights_state) -> None:
    request = build_request(observe(flights_state), "book a flight", [], ALL)

    assert "elements_note" not in request.state["page"]


def test_jev_is_told_when_the_end_of_the_page_is_on_screen(flights_state) -> None:
    """Twenty scrolls past the end of a list spent the whole step budget; the page's own answer stops that."""
    from app.services.browser.jev.viewport import ViewportRead

    at_end = build_request(
        observe(flights_state, screen=ViewportRead(at_bottom=True)), "g", [], ALL
    )
    unknown = build_request(observe(flights_state), "g", [], ALL)

    assert at_end.state["page"]["at_page_bottom"] is True
    assert "at_page_bottom" not in unknown.state["page"]


_FORM_URL = "https://forms.example/web-form.html"
_SENT_URL = "https://forms.example/submitted-form.html"


def _form_request(history: list[JevHistoryEntry]):
    form = make_state(
        {
            1: FakeNode("INPUT", {"type": "radio", "aria-label": "Radio 2"}),
            2: FakeNode("BUTTON", text="Submit", ax_node=FakeAXNode(role="button", name="Submit")),
        },
        url=_FORM_URL,
    )
    return build_request(observe(form), "g", history, ALL)


_SUBMITTED = [
    JevHistoryEntry(action="CLICK [2] Submit", kind="click", url=_FORM_URL, target_label="Submit"),
    JevHistoryEntry(action="GO_BACK", kind="go_back", url=_SENT_URL),
]


def test_a_form_submitted_and_come_back_to_unchanged_is_not_offered_for_sending_again() -> None:
    request = _form_request(_SUBMITTED)

    assert set(request.questions["click_target"].criteria) == {"1"}


@pytest.mark.regression
def test_a_form_changed_since_it_was_sent_may_be_sent_again() -> None:
    """Regression: back on a form for its skipped radio, the Submit it had used was no longer offered."""
    chose = JevHistoryEntry(
        action="CLICK [1] Radio 2", kind="click", url=_FORM_URL, target_label="Radio 2"
    )

    request = _form_request([*_SUBMITTED, chose])

    assert set(request.questions["click_target"].criteria) == {"1", "2"}
