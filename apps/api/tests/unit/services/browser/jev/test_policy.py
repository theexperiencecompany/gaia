"""Question building and answer validation — jev-ultrafast's choose/validate_choice."""

from __future__ import annotations

import pytest

from app.constants.browser import JEV_MAX_ELEMENTS, JEV_PAGES_READ, JevOperation
from app.services.browser.jev import prompts
from app.services.browser.jev.gateway import (
    JevChoiceAnswer,
    JevEvaluation,
    JevEvaluationRequest,
    JevUsage,
)
from app.services.browser.jev.observation import JevObservation, observe
from app.services.browser.jev.policy import (
    INVALID_ANSWER_MESSAGE,
    NO_ANSWER_MESSAGE,
    JevDecisionError,
    JevHistoryEntry,
    build_request,
    choose,
    page_key,
    resolve,
)
from app.services.browser.jev.prompts import (
    HUMAN_RULES,
    NAVIGATE_RULE,
    NEXT_ACTION,
    TARGET,
)
from app.services.browser.jev.seen_text import ReadPage

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
        ("DONE", {"DONE": 1.2, "WAIT": -0.2}),  # sums to 1 but is no distribution
        ("DONE", {"DONE": 1.01, "WAIT": 0.0}),  # above 1, though the sum is within tolerance
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

    with pytest.raises(JevDecisionError) as raised:
        resolve(request, evaluation, observation)

    assert str(raised.value) == INVALID_ANSWER_MESSAGE


def test_a_missing_target_head_executes_nothing(flights_state) -> None:
    observation = observe(flights_state)
    request = build_request(observation, "g", [], ALL)
    ops = list(request.questions["operation"].criteria)

    with pytest.raises(JevDecisionError) as raised:
        resolve(request, JevEvaluation(answers={"operation": _answer("CLICK", ops)}), observation)

    # Jev reads this back in recent_actions: a silent head is not a bad answer.
    assert str(raised.value) == NO_ANSWER_MESSAGE


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


def _on_form(kind: str, label: str | None = None) -> JevHistoryEntry:
    return JevHistoryEntry(action=kind.upper(), kind=kind, url=_FORM_URL, target_label=label)


def _submit_offered(history: list[JevHistoryEntry]) -> bool:
    form = make_state(
        {
            1: FakeNode("INPUT", {"type": "radio", "aria-label": "Radio 2"}),
            2: FakeNode("BUTTON", text="Submit", ax_node=FakeAXNode(role="button", name="Submit")),
            3: FakeNode("INPUT", {"aria-label": "Date"}),
            4: FakeNode("BUTTON", text="Help", ax_node=FakeAXNode(role="button", name="Help")),
        },
        url=_FORM_URL,
    )
    return "2" in build_request(observe(form), "g", history, ALL).questions["click_target"].criteria


@pytest.mark.parametrize(
    "change",
    [
        # Typed or chosen since, even into a field no longer in view.
        _on_form("type_text", "Comments"),
        _on_form("select", "Country"),
        # A picker field set by clicking it, not by typing.
        _on_form("click", "Date"),
    ],
    ids=["typed", "selected", "picked"],
)
def test_a_form_filled_in_any_way_since_it_was_sent_may_be_sent_again(change) -> None:
    assert _submit_offered([*_SUBMITTED, change])


@pytest.mark.parametrize(
    "step", [_on_form("scroll_down"), _on_form("click", "Help")], ids=["scrolled", "button"]
)
def test_a_form_whose_fields_are_unchanged_since_it_was_sent_is_not_sent_again(step) -> None:
    assert not _submit_offered([*_SUBMITTED, step])


def test_a_field_filled_elsewhere_does_not_reopen_this_forms_send() -> None:
    typed_there = JevHistoryEntry(
        action="TYPE_TEXT", kind="type_text", url=_SENT_URL, target_label="Date"
    )

    assert not _submit_offered([*_SUBMITTED, typed_there])


def test_what_was_filled_before_the_send_does_not_reopen_it() -> None:
    assert not _submit_offered([_on_form("type_text", "Comments"), *_SUBMITTED])


def test_a_field_filled_right_after_the_send_reopens_it() -> None:
    """The change counts from the step after the send, even before the run left the page."""
    submit, went_back = _SUBMITTED

    assert _submit_offered([submit, _on_form("type_text", "Comments"), went_back])


# --- answer validation: the edges of a valid distribution -------------------


def _two_way(choice: str, probabilities: dict[str, float], flights_state):
    observation = observe(flights_state)
    request = build_request(observation, "g", [], frozenset({JevOperation.DONE, JevOperation.WAIT}))
    evaluation = JevEvaluation(
        answers={
            "operation": JevChoiceAnswer(type="choice", choice=choice, probabilities=probabilities)
        }
    )
    return resolve(request, evaluation, observation)


def test_a_certain_answer_with_zero_elsewhere_is_valid(flights_state) -> None:
    decision = _two_way("DONE", {"DONE": 1.0, "WAIT": 0.0}, flights_state)

    assert decision.operation is JevOperation.DONE
    assert decision.confidence == 1.0


def test_a_choice_tied_with_the_top_within_rounding_is_accepted(flights_state) -> None:
    """The argmax check allows 1e-6 of float slack, inclusively."""
    decision = _two_way("DONE", {"DONE": 0.491078, "WAIT": 0.491079}, flights_state)

    assert decision.operation is JevOperation.DONE


def test_a_distribution_off_by_exactly_the_tolerance_is_refused(flights_state, monkeypatch) -> None:
    # A binary-exact tolerance, so the sum lands on the boundary without float noise.
    monkeypatch.setattr("app.services.browser.jev.policy.JEV_PROBABILITY_SUM_TOLERANCE", 0.25)

    with pytest.raises(JevDecisionError):
        _two_way("DONE", {"DONE": 0.75, "WAIT": 0.5}, flights_state)


def test_a_decision_carries_the_evaluation_it_came_from(flights_state) -> None:
    """The step's usage, cost and provider are read off it."""
    observation = observe(flights_state)
    request = build_request(observation, "g", [], ALL)
    ops = list(request.questions["operation"].criteria)
    usage = JevUsage(inputTokens=10, outputTokens=1)
    control = JevEvaluation(answers={"operation": _answer("DONE", ops)}, usage=usage)
    targeted = JevEvaluation(
        answers={
            "operation": _answer("TYPE_TEXT", ops),
            "type_text_target": _answer("2", ["1", "2"]),
        },
        usage=usage,
    )

    assert resolve(request, control, observation).evaluation is control
    assert resolve(request, targeted, observation).evaluation is targeted


# --- page identity ----------------------------------------------------------


def test_a_page_is_its_url_without_the_fragment_or_a_trailing_slash() -> None:
    assert page_key("https://news.example/item?id=1#comment-3#reply") == (
        "https://news.example/item?id=1"
    )
    assert page_key("https://shop.example/SKU-12X/") == "https://shop.example/SKU-12X"
    assert page_key("https://news.example/") == page_key("https://news.example")
    assert page_key(None) == ""


# --- rows the run already opened are not offered again ----------------------

NEWS = "https://news.example/"
ARTICLE = "https://blog.example/tiny-compilers"


def _link(text: str) -> FakeNode:
    return FakeNode("A", {"href": "/x"}, text=text, ax_node=FakeAXNode(role="link", name=text))


def _news_page():
    return observe(
        make_state(
            {
                1: _link("Tiny compilers in Rust"),
                2: _link("A history of the transistor"),
                3: _link("More"),
                4: FakeNode("BUTTON", text="Hide", ax_node=FakeAXNode(role="button", name="Hide")),
            },
            url=NEWS,
            title="News",
        )
    )


def _offered_rows(observation, history, pages_read=()) -> set[str]:
    request = build_request(observation, "read every story", history, ALL, pages_read)
    return {
        c["element"].split("] ", 1)[1] for c in request.questions["click_target"].criteria.values()
    }


def _click(label: str, url: str = NEWS, *, changed: bool | None = True) -> JevHistoryEntry:
    return JevHistoryEntry(
        action=f"CLICK {label}", kind="click", url=url, target_label=label, page_changed=changed
    )


def _step_on(url: str) -> JevHistoryEntry:
    return JevHistoryEntry(action="SCROLL_DOWN", kind="scroll_down", url=url)


def test_a_row_whose_page_the_run_went_on_to_is_not_offered_again() -> None:
    """Offering it again is how a list task re-reads its first item forever."""
    history = [
        JevHistoryEntry(action="NAVIGATE", kind="navigate", url=NEWS),
        # The engine reports the list with its fragment and without the slash.
        _click("Tiny compilers in Rust", url="https://news.example#top"),
        _step_on(ARTICLE),
    ]

    offered = _offered_rows(_news_page(), history)

    assert "Tiny compilers in Rust" not in offered
    assert {"A history of the transistor", "More", "Hide"} <= offered


def test_a_click_that_kept_the_run_on_this_page_stays_offered() -> None:
    """A next-page link or a toggle is clicked again on purpose."""
    history = [
        _step_on(ARTICLE),
        _click("More"),
        _step_on(NEWS),
    ]

    assert "More" in _offered_rows(_news_page(), history)


def test_the_same_label_clicked_on_another_page_withholds_nothing_here() -> None:
    history = [
        _click("Tiny compilers in Rust", url="https://other-list.example/"),
        _step_on(ARTICLE),
    ]

    assert "Tiny compilers in Rust" in _offered_rows(_news_page(), history)


def test_a_typed_field_is_not_a_row_the_run_opened() -> None:
    history = [
        JevHistoryEntry(
            action="TYPE_TEXT Tiny compilers in Rust",
            kind="type_text",
            url=NEWS,
            target_label="Tiny compilers in Rust",
            page_changed=True,
        ),
        _step_on(ARTICLE),
    ]

    assert "Tiny compilers in Rust" in _offered_rows(_news_page(), history)


def test_one_dead_click_is_retried_but_a_second_withholds_the_control() -> None:
    once = [_click("Hide", changed=False)]
    twice = [_click("Hide", changed=False), _click("Hide", changed=False)]

    assert "Hide" in _offered_rows(_news_page(), once)
    assert "Hide" not in _offered_rows(_news_page(), twice)
    assert {"Tiny compilers in Rust", "More"} <= _offered_rows(_news_page(), twice)


def test_a_click_that_changed_the_page_in_place_is_not_a_dead_click() -> None:
    history = [_click("Hide"), _click("Hide")]

    assert "Hide" in _offered_rows(_news_page(), history)


def _read(url: str, title: str) -> ReadPage:
    return ReadPage(url=url, title=title, read="to the end")


def test_a_row_titled_like_a_page_already_read_is_not_offered_again() -> None:
    """A story's row names its article's title, even when the run got there by address."""
    pages = [_read(ARTICLE, "Tiny compilers in Rust")]

    offered = _offered_rows(_news_page(), [], pages)

    assert "Tiny compilers in Rust" not in offered
    assert "A history of the transistor" in offered


def test_reading_this_very_page_withholds_none_of_its_rows() -> None:
    pages = [_read("https://news.example", "A history of the transistor")]

    assert "A history of the transistor" in _offered_rows(_news_page(), [], pages)


def test_a_read_title_just_long_enough_to_match_withholds_its_row() -> None:
    pages = [_read(ARTICLE, "Hide replies")]  # exactly the 12-character floor
    page = observe(make_state({1: _link("Hide replies"), 2: _link("Next page")}, url=NEWS))

    assert _offered_rows(page, [], pages) == {"Next page"}


def test_a_short_title_already_read_withholds_nothing() -> None:
    """Short labels ("jobs", "hide") would match inside almost any title."""
    pages = [_read(ARTICLE, "Hide")]

    assert "Hide" in _offered_rows(_news_page(), [], pages)


def test_a_row_matches_a_read_page_whichever_title_holds_the_other() -> None:
    page = observe(
        make_state(
            {
                1: _link("Parser guide"),
                2: _link("Tiny Compilers | 120 points"),
                3: _link("Weather in Oslo today"),
            },
            url=NEWS,
        )
    )
    pages = [
        _read("https://a.example", "The parser guide for beginners"),
        _read("https://b.example", "tiny compilers"),
    ]

    assert _offered_rows(page, [], pages) == {"Weather in Oslo today"}


def test_when_every_row_was_opened_the_rows_are_offered_rather_than_none() -> None:
    page = observe(make_state({1: _link("Tiny compilers in Rust")}, url=NEWS))
    history = [_click("Tiny compilers in Rust"), _step_on(ARTICLE)]

    assert _offered_rows(page, history) == {"Tiny compilers in Rust"}


def test_an_offered_dropdown_gets_its_target_question_on_a_page_with_no_text_field() -> None:
    """SELECT is offered as an operation, so its head must exist or the answer cannot resolve."""
    page = observe(
        make_state(
            {
                31: FakeNode(
                    "SELECT",
                    {"value": "economy"},
                    ax_node=FakeAXNode(role="combobox", name="Cabin class"),
                    children_nodes=[
                        FakeNode("OPTION", {"value": "economy"}, text="Economy"),
                        FakeNode("OPTION", {"value": "business"}, text="Business"),
                    ],
                ),
                40: FakeNode(
                    "BUTTON", text="Search", ax_node=FakeAXNode(role="button", name="Search")
                ),
            }
        )
    )

    request = build_request(page, "g", [], ALL)

    assert "TYPE_TEXT" not in request.questions["operation"].criteria
    assert "SELECT" in request.questions["operation"].criteria
    assert "select_target" in request.questions


def test_jev_sees_only_the_most_recent_pages_read() -> None:
    pages = [_read(f"https://p{i}.example", f"Page {i}") for i in range(JEV_PAGES_READ + 3)]

    request = build_request(_news_page(), "g", [], ALL, pages)

    assert request.state["pages_read"] == [dict(p) for p in pages[-JEV_PAGES_READ:]]


async def test_choose_hands_jev_the_pages_already_read() -> None:
    seen: list[JevEvaluationRequest] = []

    class _Client:
        async def evaluate(self, request: JevEvaluationRequest) -> JevEvaluation:
            seen.append(request)
            ops = list(request.questions["operation"].criteria)
            return JevEvaluation(answers={"operation": _answer("DONE", ops)})

    pages = [_read(ARTICLE, "Tiny compilers in Rust")]
    observation: JevObservation = _news_page()

    decision = await choose(_Client(), observation, "g", [], ALL, pages)  # type: ignore[arg-type]

    assert decision.operation is JevOperation.DONE
    assert seen[0].state["pages_read"] == [dict(pages[0])]
