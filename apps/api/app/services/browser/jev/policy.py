"""The step decision: one Jev request, operation + speculative target heads.

Port of jev-ultrafast's model.choose / validate_choice. Every operation
Jev may pick is offered as a criterion of the operation question; each
element-bound operation gets its own op_target question over only the
elements that support it. The heads answer in one round trip and only the
target head matching the chosen operation is read.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
import math
from typing import TypedDict, cast

from app.constants.browser import (
    JEV_PAGES_READ,
    JEV_PROBABILITY_SUM_TOLERANCE,
    JEV_RECENT_ACTIONS,
    JEV_TARGET_OPERATIONS,
    JevNoteSource,
    JevOperation,
)
from app.services.browser.jev.gateway import (
    JevChoiceAnswer,
    JevChoiceQuestion,
    JevDecisionsClient,
    JevEvaluation,
    JevEvaluationRequest,
    JsonInput,
)
from app.services.browser.jev.observation import JevElement, JevObservation, JevSelectOption
from app.services.browser.jev.prompts import (
    HUMAN_RULES,
    NAVIGATE_RULE,
    NEXT_ACTION,
    REQUEST_HUMAN_CRITERION,
    SOLVE_CAPTCHA_CRITERION,
    STILL_NEEDED_RULE,
    TARGET,
)
from app.services.browser.jev.seen_text import ReadPage


class JevDecisionError(ValueError):
    """Jev's answer did not name an offered operation/target; no action executed."""


class _OperationAnswers(TypedDict):
    """The gateway's answers, read only for the operation head (target heads use variable keys)."""

    operation: JevChoiceAnswer


class _OperationQuestions(TypedDict):
    """The request's questions, read only for the operation head."""

    operation: JevChoiceQuestion


_OPERATION_LABELS: dict[JevOperation, str] = {
    JevOperation.CLICK: (
        "Click an element, button, menu option, autocomplete suggestion, or calendar day."
    ),
    JevOperation.TYPE_TEXT: (
        "Enter or replace text in an editable field. A small LLM will supply the value from the goal."
    ),
    JevOperation.SELECT: "Select an observed dropdown value.",
    JevOperation.SCROLL_UP: "Scroll the page up one screen.",
    JevOperation.SCROLL_DOWN: "Scroll the page down one screen.",
    JevOperation.WAIT: "Wait one second for the page to load or settle.",
    JevOperation.NAVIGATE: "Open a different URL that the goal names or implies.",
    JevOperation.GO_BACK: "Go back to the previous page.",
    JevOperation.REQUEST_HUMAN: REQUEST_HUMAN_CRITERION,
    JevOperation.SOLVE_CAPTCHA: SOLVE_CAPTCHA_CRITERION,
    JevOperation.DONE: (
        "Every requirement is satisfied by what this run has read: this screen together with "
        "the pages in pages_read hold every answer the goal asks for, because each page that "
        "holds one was opened and read. A search result, a link title, a snippet about a page, "
        "or anything you already know is not enough: a page not in pages_read has not been read. "
        "When the goal asks for the cheapest, the most, the best, the first, the last, the newest, "
        "a count, a total, or every item of a list, that whole list must already have been seen: "
        "scrolled down until nothing new appeared, and paged through to its last page. Every step "
        "the goal lists was carried out by an action in this run; a control the goal names by a "
        "label the screen does not show is the one in that position or with the closest wording, "
        "never a step to skip."
    ),
    JevOperation.BLOCKED: "No supported operation can progress.",
}


@dataclass(frozen=True)
class JevHistoryEntry:
    """One executed step, as the policy replays it to Jev on later steps."""

    action: str
    kind: str
    text: str | None = None
    page_changed: bool | None = None
    #: The page this action was taken on, so a page already opened from a list
    #: reads as done rather than as the thing to click again.
    url: str | None = None
    #: The element's own label; the action string bakes in an index that
    #: renumbers between renders, so a repeat is matched by label.
    target_label: str | None = None
    #: The instruction handed back after this step: the user's after a takeover,
    #: or the executor's after this step asked it for guidance.
    note: str | None = None
    note_source: JevNoteSource | None = None

    def state_entry(self) -> dict[str, object]:
        return {
            "action": self.action,
            "kind": self.kind,
            "text": self.text,
            "page_changed": self.page_changed,
            "url": self.url,
            "note": self.note,
        }


@dataclass(frozen=True)
class JevDecision:
    operation: JevOperation
    element: JevElement | None = None
    option: JevSelectOption | None = None
    target: str | None = None
    confidence: float = 0.0
    operation_probabilities: dict[str, float] = field(default_factory=dict)
    target_probabilities: dict[str, float] = field(default_factory=dict)
    evaluation: JevEvaluation | None = None

    @property
    def label(self) -> str:
        if self.option is not None and self.element is not None:
            return f"{self.operation.value} [{self.element.index}] {self.element.label} → {self.option.label}"
        if self.element is not None:
            return f"{self.operation.value} [{self.element.index}] {self.element.label}"
        return self.operation.value


def build_request(
    observation: JevObservation,
    goal: str,
    history: list[JevHistoryEntry],
    offered: frozenset[JevOperation],
    pages_read: Sequence[ReadPage] = (),
) -> JevEvaluationRequest:
    """Return the shared state plus one operation head and one target head per offered element operation."""
    targets = {op: observation.targets(op) for op in JEV_TARGET_OPERATIONS if op in offered}
    opened = _already_opened(history, observation, pages_read)
    clicks = targets.get(JevOperation.CLICK)
    if opened and clicks:
        # A row this page already opened leads to a page the run has been on;
        # offering it again is how a list task re-reads its first item forever.
        kept = {
            key: pair for key, pair in clicks.items() if not _opens_again(pair[0].label, opened)
        }
        if kept:
            targets[JevOperation.CLICK] = kept
    operations = {
        op.value: _OPERATION_LABELS[op]
        for op in JevOperation
        if op in offered and (op not in JEV_TARGET_OPERATIONS or targets.get(op))
    }
    rules: JsonInput = [NEXT_ACTION, HUMAN_RULES, NAVIGATE_RULE, STILL_NEEDED_RULE]
    questions: dict[str, JevChoiceQuestion] = {
        "operation": JevChoiceQuestion(
            instructions={"goal": goal, "rules": rules}, criteria=dict(operations)
        )
    }
    for op, candidates in targets.items():
        if not candidates:
            continue
        questions[_target_head(op)] = JevChoiceQuestion(
            instructions={"goal": goal, "operation": op.value, "rules": [NEXT_ACTION, TARGET]},
            criteria={
                key: element.criterion(f"{element.label} → {option.label}" if option else None)
                for key, (element, option) in candidates.items()
            },
        )
    state: dict[str, object] = {
        "page": observation.page_state(),
        "elements": [e.state_entry() for e in observation.elements],
        "recent_actions": [h.state_entry() for h in history[-JEV_RECENT_ACTIONS:]],
    }
    if pages_read:
        # What the run has already opened and read, so a listed item whose page
        # is here counts as done and the next item is the move.
        state["pages_read"] = [dict(page) for page in pages_read[-JEV_PAGES_READ:]]
    return JevEvaluationRequest(state=state, questions=questions)


def _already_opened(
    history: list[JevHistoryEntry], observation: JevObservation, pages_read: Sequence[ReadPage]
) -> frozenset[str]:
    """Labels on this page that name something the run has already opened and read.

    Two sources: a click from here followed by steps on another page, unless a
    field here was filled since (a form is sent again once changed), and the title
    of any page already read. A control clicked again on the same page is left alone.
    """
    here = page_key(observation.url)
    fields = frozenset(e.label for e in observation.elements if _is_field(e))
    opened: set[str] = set()
    dead_clicks: dict[str, int] = {}
    for position, entry in enumerate(history):
        if not (entry.target_label and entry.kind == "click" and page_key(entry.url) == here):
            continue
        if entry.page_changed is False:
            # Clicked here and nothing changed: a table row, a label, a slow
            # control. One retry is fair (the page may just have been slow);
            # a second dead click says the control does nothing.
            dead_clicks[entry.target_label] = dead_clicks.get(entry.target_label, 0) + 1
            if dead_clicks[entry.target_label] >= _DEAD_CLICKS_BEFORE_WITHHELD:
                opened.add(entry.target_label)
        elif any(
            later.url and page_key(later.url) != here for later in history[position + 1 :]
        ) and not _filled_since(history[position + 1 :], here, fields):
            opened.add(entry.target_label)
    for page in pages_read:
        if page_key(page["url"]) != here and len(page["title"]) >= _TITLE_MATCH_MIN_CHARS:
            opened.add(page["title"])
    return frozenset(opened)


def _is_field(element: JevElement) -> bool:
    """Whether the element holds a value a form sends: a text field, a select, a box or a radio."""
    return element.role in _CHOICE_ROLES or any(
        op in element.operations for op in (JevOperation.TYPE_TEXT, JevOperation.SELECT)
    )


def _filled_since(later: list[JevHistoryEntry], here: str, fields: frozenset[str]) -> bool:
    """Whether a later step on this page entered something into one of its fields."""
    return any(
        page_key(entry.url) == here
        and (entry.kind in ("type_text", "select") or entry.target_label in fields)
        for entry in later
    )


def page_key(url: str | None) -> str:
    """Return the page a URL names, ignoring a fragment and a trailing slash the engine adds and drops."""
    return (url or "").split("#", 1)[0].rstrip("/")


def _opens_again(label: str, opened: frozenset[str]) -> bool:
    """Whether a row's label names something already opened: a story's row, its link and its page's title share words."""
    if label in opened:
        return True
    if len(label) < _TITLE_MATCH_MIN_CHARS:
        return False
    low = label.lower()
    return any(low in seen.lower() or seen.lower() in low for seen in opened)


_CHOICE_ROLES = frozenset({"checkbox", "radio", "switch", "menuitemcheckbox", "menuitemradio"})
#: Shorter labels ("jobs", "hide") would match inside almost any page title.
_TITLE_MATCH_MIN_CHARS = 12
#: Dead clicks on one control on one page before it is no longer offered there.
_DEAD_CLICKS_BEFORE_WITHHELD = 2


async def choose(
    client: JevDecisionsClient,
    observation: JevObservation,
    goal: str,
    history: list[JevHistoryEntry],
    offered: frozenset[JevOperation],
    pages_read: Sequence[ReadPage] = (),
) -> JevDecision:
    """Ask Jev for this step's operation and, when it needs one, its target."""
    request = build_request(observation, goal, history, offered, pages_read)
    evaluation = await client.evaluate(request)
    return resolve(request, evaluation, observation)


def resolve(
    request: JevEvaluationRequest, evaluation: JevEvaluation, observation: JevObservation
) -> JevDecision:
    """Validate the operation head, then only the target head that operation selects."""
    answers: _OperationAnswers = cast(_OperationAnswers, evaluation.answers)
    questions: _OperationQuestions = cast(_OperationQuestions, request.questions)
    operation_answer = _validate_choice(answers.get("operation"), questions["operation"].criteria)
    operation = JevOperation(operation_answer.choice)
    if operation not in JEV_TARGET_OPERATIONS:
        return JevDecision(
            operation=operation,
            confidence=operation_answer.probabilities.get(operation.value, 0.0),
            operation_probabilities=operation_answer.probabilities,
            evaluation=evaluation,
        )
    head = _target_head(operation)
    target_answer = _validate_choice(evaluation.answers.get(head), request.questions[head].criteria)
    element, option = observation.targets(operation)[target_answer.choice]
    return JevDecision(
        operation=operation,
        element=element,
        option=option,
        target=target_answer.choice,
        confidence=operation_answer.probabilities.get(operation.value, 0.0),
        operation_probabilities=operation_answer.probabilities,
        target_probabilities=target_answer.probabilities,
        evaluation=evaluation,
    )


def _target_head(operation: JevOperation) -> str:
    return f"{operation.value.lower()}_target"


def _validate_choice(
    answer: JevChoiceAnswer | None, criteria: dict[str, JsonInput]
) -> JevChoiceAnswer:
    """jev-ultrafast's guard: the choice is offered, the distribution is over exactly the offered keys, sums to ~1, and the choice is its argmax.

    Anything else executes nothing."""
    if answer is None:
        raise JevDecisionError("Jev returned no answer for a question; no action executed.")
    probabilities = answer.probabilities
    valid = (
        answer.choice in criteria
        and set(probabilities) == set(criteria)
        and all(math.isfinite(p) and 0 <= p <= 1 for p in probabilities.values())
        and abs(sum(probabilities.values()) - 1) < JEV_PROBABILITY_SUM_TOLERANCE
        and probabilities[answer.choice] >= max(probabilities.values()) - 1e-6
    )
    if not valid:
        raise JevDecisionError("Invalid Jev response; no action executed.")
    return answer
