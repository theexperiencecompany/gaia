"""One Jev decision per step: the operation and its target.

Ported from browser-use/jev-ultrafast (MIT) jev_ultrafast/model.py: one
decisions request carries an operation head and one target head per
operation that has targets, and only the head the chosen operation names is
read. What to type, and which option a chosen dropdown takes, are each a
second, small decision.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
import math
import re

from pydantic import ValidationError

from app.constants.browser import (
    JEV_MAX_ELEMENTS,
    JEV_PROBABILITY_SUM_TOLERANCE,
    JevOperation,
)
from app.services.browser.exceptions import BrowserAutomationError
from app.services.browser.jev.gateway import (
    JevChoiceAnswer,
    JevDecider,
    JevEvaluation,
    JevEvaluationRequest,
    JevQuestion,
    JsonInput,
)
from app.services.browser.jev.page import PageAction, PageState, SelectOption
from app.services.browser.jev.questions import (
    NAVIGATE_TARGET,
    NEXT_ACTION,
    OPERATIONS,
    OPTION,
    TARGET,
    VALUE,
    VALUE_GENERATE,
    VALUE_NONE,
)

_KIND_OPERATION = {
    "click": JevOperation.CLICK,
    "fill": JevOperation.TYPE_TEXT,
    "secret": JevOperation.TYPE_TEXT,
    "select": JevOperation.SELECT,
}
#: Operations on the page as a whole, offered only while the page offers them.
_CONTROL_OPERATION = {
    "wait": JevOperation.WAIT,
    "enter": JevOperation.PRESS_ENTER,
    "back": JevOperation.GO_BACK,
}
#: How the snapshot names every scroll that turns up: the page's, and each container's.
_SCROLL_UP_ID = "scroll_up"
#: The scroll target that is the page itself, beside any inner container's element index.
PAGE_TARGET = "page"
NONE_VALUE = "NONE"
GENERATE = "GENERATE"
_ELEMENT_FIELDS = (
    "role",
    "ident",
    "input_type",
    "value",
    "checked",
    "selected",
    "expanded",
    "filled",
)
#: What a target question shows of each candidate besides its label and current value.
_TARGET_FIELDS = ("role", "ident", "input_type", "checked", "selected", "expanded", "filled")
#: What the value question and the text model see of the field being typed into.
_FIELD_KEYS = ("label", "role", "ident", "input_type", "value")
#: A choice this close to the most likely option is a tie, not a lower-ranked pick.
_TIE_TOLERANCE = 1e-6
_TRAILING_PUNCTUATION = ".,;:!?"
_OPERATION_QUESTION = "operation"
_NAVIGATE_QUESTION = "navigate_target"
_VALUE_QUESTION = "value"
_OPTION_QUESTION = "option"
_NO_ANSWER = "Jev returned no answer for a question; no action executed."
_INVALID_ANSWER = "Invalid Jev response; no action executed."

# Literal values a goal spells out: quoted text, emails, dates, URLs.
_QUOTED = re.compile(r"\"([^\"]{1,200})\"|“([^”]{1,200})”|(?<![\w])'([^']{1,200})'(?![\w])")
_EMAIL = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
_DATE = re.compile(r"\b\d{1,4}[/.-]\d{1,2}[/.-]\d{1,4}\b")
_URL = re.compile(r"https?://[^\s<>\"'()\[\]]+")
_SECRET_PLACEHOLDER = re.compile(r"<secret>([\w.-]+)</secret>")

#: Replaces every secret value in a string with its placeholder.
Mask = Callable[[str], str]


class JevDecisionError(BrowserAutomationError):
    """Jev's answer was malformed; no action was executed."""


@dataclass(frozen=True)
class RecentAction:
    """One executed action as Jev's state shows it."""

    action: str
    kind: str
    text: str | None
    page_changed: bool | None


@dataclass(frozen=True)
class Visited:
    title: str
    url: str


@dataclass(frozen=True)
class Decision:
    """What to execute, with what the call cost."""

    operation: JevOperation
    #: The snapshot action the operation executes (for SELECT, the dropdown), else None.
    target: PageAction | None
    url: str | None
    latency_ms: int
    evaluation: JevEvaluation


@dataclass
class _Element:
    """One observed element as Jev's state lists it."""

    index: str
    label: str
    #: The descriptor fields it carries (role, id or name, value, states), none of them empty.
    fields: dict[str, object]
    operations: list[JevOperation] = field(default_factory=list)

    def described(self) -> dict[str, object]:
        """Return the element as Jev reads it."""
        return {
            **self.fields,
            "index": self.index,
            "label": self.label,
            "operations": self.operations,
        }


@dataclass
class _ActionSpace:
    elements: list[_Element] = field(default_factory=list)
    #: Per target operation: target index -> snapshot action.
    targets: dict[JevOperation, dict[str, PageAction]] = field(default_factory=dict)
    controls: dict[JevOperation, PageAction] = field(default_factory=dict)
    _by_node: dict[int, _Element] = field(default_factory=dict)
    #: The nodes the page offered beyond what one request may carry.
    _left_out: set[int] = field(default_factory=set)

    @property
    def left_out(self) -> int:
        return len(self._left_out)

    def add(self, action: PageAction) -> None:
        """Index one snapshot action: a page-level control, the page's own scroll, or an element's."""
        kind = action["kind"]
        if kind in _CONTROL_OPERATION:
            self.controls[_CONTROL_OPERATION[kind]] = action
            return
        operation = _KIND_OPERATION[kind] if kind != "scroll" else _scroll_operation(action)
        if kind == "scroll" and "node" not in action:
            self.targets.setdefault(operation, {})[PAGE_TARGET] = action
            return
        element = self._element(action)
        if element is None:
            return
        if operation not in element.operations:
            element.operations.append(operation)
        self.targets.setdefault(operation, {})[element.index] = action

    def _element(self, action: PageAction) -> _Element | None:
        """Return the element an action targets, indexed once; None past the request's limit."""
        node = action["node"]
        if node in self._by_node:
            return self._by_node[node]
        if len(self._by_node) >= JEV_MAX_ELEMENTS:
            self._left_out.add(node)
            return None
        fields = {k: v for k, v in _fields(action, _ELEMENT_FIELDS).items() if v != ""}
        if action["kind"] == "select":
            # A dropdown shows its current choice; its options are asked once it is chosen.
            fields["value"] = action["current_value"]
        element = _Element(index=str(len(self.elements) + 1), label=action["label"], fields=fields)
        self._by_node[node] = element
        self.elements.append(element)
        return element


def action_space(actions: list[PageAction]) -> _ActionSpace:
    """One index per observed element; each operation has its own valid targets."""
    space = _ActionSpace()
    for action in actions:
        space.add(action)
    return space


def _scroll_operation(action: PageAction) -> JevOperation:
    """Return which way a scroll turns, as the snapshot names it."""
    up = action["id"].startswith(_SCROLL_UP_ID)
    return JevOperation.SCROLL_UP if up else JevOperation.SCROLL_DOWN


def _fields(action: PageAction, keys: tuple[str, ...]) -> dict[str, object]:
    """Return the named fields an action carries, for Jev's element descriptors."""
    present: dict[str, object] = dict(action)
    return {key: present[key] for key in keys if present.get(key) is not None}


def literals(goal: str) -> list[str]:
    """Return the values a goal spells out, in order: quoted text, emails, dates, URLs."""
    found: list[str] = []
    for match in _QUOTED.finditer(goal):
        found.append(next(group for group in match.groups() if group))
    for pattern in (_EMAIL, _DATE, _URL):
        found.extend(
            match.group(0).rstrip(_TRAILING_PUNCTUATION) for match in pattern.finditer(goal)
        )
    return list(dict.fromkeys(value for value in found if not _SECRET_PLACEHOLDER.fullmatch(value)))


def describe_field(target: PageAction) -> dict[str, object]:
    """Return the field being typed into as the value question and the text model see it."""
    return {key: target.get(key) for key in _FIELD_KEYS}


def _target_question(operation: JevOperation) -> str:
    return f"{operation.value.lower()}_target"


def _target_criteria(candidates: dict[str, PageAction]) -> dict[str, JsonInput]:
    """Return an operation's targets as Jev weighs them: label, current value and states."""
    return {
        index: {
            "element": f"[{index}] {action['label']}",
            "current_value": action.get("current_value", action.get("value", "")),
            **_fields(action, _TARGET_FIELDS),
        }
        for index, action in candidates.items()
    }


def _page(page: PageState) -> dict[str, object]:
    return {"url": page.url, "title": page.title, "text": page.text}


def masked_json(value: object, mask: Mask) -> object:
    """Return value with mask applied to every string in it; keys are code-owned ids and stay."""
    if isinstance(value, str):
        return mask(value)
    if isinstance(value, dict):
        return {key: masked_json(item, mask) for key, item in value.items()}
    if isinstance(value, list):
        return [masked_json(item, mask) for item in value]
    return value


async def _ask(
    client: JevDecider,
    state: dict[str, object],
    questions: dict[str, JevQuestion],
    mask: Mask,
) -> JevEvaluation:
    """Send one evaluation with no secret value anywhere in it: the page, the targets or the goal."""
    request = JevEvaluationRequest(state=state, questions=questions)
    return await client.evaluate(
        JevEvaluationRequest.model_validate(masked_json(request.model_dump(), mask))
    )


def _validate_choice(evaluation: JevEvaluation, question: str, ids: set[str]) -> str:
    """Return the option one question chose, once its answer is a distribution over exactly ids that ranks it first.

    Only the head a decision reads is validated: a malformed head nothing reads costs nothing.
    """
    raw = evaluation.answers.get(question)
    if raw is None:
        raise JevDecisionError(_NO_ANSWER)
    try:
        answer = JevChoiceAnswer.model_validate(raw)
    except ValidationError as exc:
        raise JevDecisionError(_INVALID_ANSWER) from exc
    probabilities = answer.probabilities
    if not (
        answer.choice in ids
        and set(probabilities) == ids
        and all(math.isfinite(n) and 0 <= n <= 1 for n in probabilities.values())
        and abs(sum(probabilities.values()) - 1) < JEV_PROBABILITY_SUM_TOLERANCE
        and probabilities[answer.choice] >= max(probabilities.values()) - _TIE_TOLERANCE
    ):
        raise JevDecisionError(_INVALID_ANSWER)
    return answer.choice


async def decide(
    client: JevDecider,
    page: PageState,
    goal: str,
    history: list[RecentAction],
    visited: list[Visited],
    addresses: list[str],
    mask: Mask,
) -> Decision:
    """Ask Jev for this step's operation and target; raises JevDecisionError on a malformed answer."""
    space = action_space(page.actions)
    controls: dict[JevOperation, PageAction] = space.controls
    operations: dict[str, JsonInput] = {op.value: OPERATIONS[op] for op in space.targets}
    operations.update({op.value: control["label"] for op, control in controls.items()})
    if addresses:
        operations[JevOperation.NAVIGATE.value] = OPERATIONS[JevOperation.NAVIGATE]
    operations[JevOperation.DONE.value] = OPERATIONS[JevOperation.DONE]
    operations[JevOperation.BLOCKED.value] = OPERATIONS[JevOperation.BLOCKED]

    questions: dict[str, JevQuestion] = {
        _OPERATION_QUESTION: JevQuestion(
            criteria=operations, instructions={"goal": goal, "rules": NEXT_ACTION}
        )
    }
    for operation, candidates in space.targets.items():
        questions[_target_question(operation)] = JevQuestion(
            criteria=_target_criteria(candidates),
            instructions={
                "goal": goal,
                "operation": operation.value,
                "rules": [NEXT_ACTION, TARGET],
            },
        )
    address_ids = {f"U{i + 1}": url for i, url in enumerate(addresses)}
    if address_ids:
        questions[_NAVIGATE_QUESTION] = JevQuestion(
            criteria=dict(address_ids),
            instructions={
                "goal": goal,
                "operation": JevOperation.NAVIGATE.value,
                "rules": NAVIGATE_TARGET,
            },
        )
    state: dict[str, object] = {
        "page": _page(page),
        "elements": [element.described() for element in space.elements],
        "recent_actions": [
            {"action": h.action, "kind": h.kind, "text": h.text, "page_changed": h.page_changed}
            for h in history
        ],
        "visited": [{"title": v.title, "url": v.url} for v in visited],
    }
    left_out = page.omitted_actions + space.left_out
    if left_out:
        state["elements_left_out"] = left_out
    evaluation = await _ask(client, state, questions, mask)
    operation = JevOperation(_validate_choice(evaluation, _OPERATION_QUESTION, set(operations)))
    chosen: PageAction | None = None
    url: str | None = None
    if operation in space.targets:
        targets = space.targets[operation]
        chosen = targets[_validate_choice(evaluation, _target_question(operation), set(targets))]
    elif operation in controls:
        chosen = controls[operation]
    elif operation is JevOperation.NAVIGATE:
        url = address_ids[_validate_choice(evaluation, _NAVIGATE_QUESTION, set(address_ids))]
    return Decision(
        operation=operation,
        target=chosen,
        url=url,
        latency_ms=evaluation.latency_ms,
        evaluation=evaluation,
    )


async def choose_option(
    client: JevDecider,
    page: PageState,
    goal: str,
    dropdown: PageAction,
    history: list[RecentAction],
    mask: Mask,
) -> tuple[PageAction, JevEvaluation]:
    """Pick which of a chosen dropdown's options to set: asked apart, so a long list never swells the step."""
    options: list[SelectOption] = dropdown["options"]
    labels = [option["label"] for option in options]
    criteria: dict[str, JsonInput] = {f"O{n}": label for n, label in enumerate(labels, 1)}
    question = JevQuestion(
        criteria=criteria,
        instructions={
            "goal": goal,
            "field": {"label": dropdown["label"], "current_value": dropdown["current_value"]},
            "rules": OPTION,
        },
    )
    state: dict[str, object] = {
        "page": _page(page),
        "recent_actions": [{"action": h.action, "text": h.text} for h in history],
    }
    evaluation = await _ask(client, state, {_OPTION_QUESTION: question}, mask)
    option: SelectOption = options[
        int(_validate_choice(evaluation, _OPTION_QUESTION, set(criteria))[1:]) - 1
    ]
    chosen = dropdown.copy()
    del chosen["options"]
    chosen["value"] = option["value"]
    chosen["current_value"] = option["label"]
    return chosen, evaluation


async def choose_value(
    client: JevDecider,
    page: PageState,
    goal: str,
    target: PageAction,
    history: list[RecentAction],
    secrets: list[str],
    mask: Mask,
) -> tuple[str, JevEvaluation]:
    """Pick what to type into target: a literal from the goal, one of the run's secrets, GENERATE, or NONE.

    A password field is offered the run's secrets only; any other field the goal's
    literals and the secrets too, since a username or an account id can be one.
    history is the recent actions Jev may see, already cut to that window.
    """
    is_secret = target["kind"] == "secret"
    placeholders = [f"<secret>{name}</secret>" for name in secrets]
    options = placeholders if is_secret else [*literals(goal), *placeholders]
    criteria: dict[str, JsonInput] = {f"V{i + 1}": value for i, value in enumerate(options)}
    if not is_secret:
        criteria[GENERATE] = VALUE_GENERATE
    criteria[NONE_VALUE] = VALUE_NONE
    question = JevQuestion(
        criteria=criteria,
        instructions={"goal": goal, "field": describe_field(target), "rules": VALUE},
    )
    state: dict[str, object] = {
        "page": _page(page),
        "recent_actions": [{"action": h.action, "text": h.text} for h in history],
    }
    evaluation = await _ask(client, state, {_VALUE_QUESTION: question}, mask)
    answer = _validate_choice(evaluation, _VALUE_QUESTION, set(criteria))
    if answer in (GENERATE, NONE_VALUE):
        return answer, evaluation
    return options[int(answer[1:]) - 1], evaluation
