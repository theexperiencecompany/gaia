"""One Jev decision per step: the operation and its target.

Ported from browser-use/jev-ultrafast (MIT) jev_ultrafast/model.py: one
decisions request carries an operation head and one target head per
operation that has targets, and only the head the chosen operation names is
read. A typed value is a second, small decision over the literals the goal
spells out.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import math
import re

from app.constants.browser import (
    JEV_MAX_ELEMENTS,
    JEV_PROBABILITY_SUM_TOLERANCE,
    JevOperation,
)
from app.services.browser.exceptions import BrowserAutomationError
from app.services.browser.jev.gateway import (
    JevChoiceAnswer,
    JevDecisionsClient,
    JevEvaluation,
    JevEvaluationRequest,
    JevQuestion,
    JsonInput,
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

_KIND_OPERATION = {
    "click": JevOperation.CLICK,
    "fill": JevOperation.TYPE_TEXT,
    "secret": JevOperation.TYPE_TEXT,
    "select": JevOperation.SELECT,
}
_CONTROL_OPERATION = {
    "scroll_down": JevOperation.SCROLL_DOWN,
    "scroll_up": JevOperation.SCROLL_UP,
    "wait": JevOperation.WAIT,
}
NONE_VALUE = "NONE"
GENERATE = "GENERATE"
_ELEMENT_FIELDS = ("role", "ident", "value", "checked", "selected", "expanded", "filled")
#: What a target question shows of each candidate besides its label and current value.
_TARGET_FIELDS = ("role", "ident", "checked", "selected", "expanded", "filled")
#: What the value question and the text model see of the field being typed into.
_FIELD_KEYS = ("label", "role", "ident", "value")
#: A choice this close to the most likely option is a tie, not a lower-ranked pick.
_TIE_TOLERANCE = 1e-6
_TRAILING_PUNCTUATION = ".,;:!?"
_OPERATION_QUESTION = "operation"
_NAVIGATE_QUESTION = "navigate_target"
_VALUE_QUESTION = "value"
_NO_ANSWER = "Jev returned no answer for a question; no action executed."
_INVALID_ANSWER = "Invalid Jev response; no action executed."

# Literal values a goal spells out: quoted text, emails, dates, URLs.
_QUOTED = re.compile(r"\"([^\"]{1,200})\"|“([^”]{1,200})”|(?<![\w])'([^']{1,200})'(?![\w])")
_EMAIL = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
_DATE = re.compile(r"\b\d{1,4}[/.-]\d{1,2}[/.-]\d{1,4}\b")
_URL = re.compile(r"https?://[^\s<>\"'()\[\]]+")
_SITE = re.compile(
    r"\b(?:[a-z0-9-]+\.)+(?:com|org|net|io|dev|ai|edu|gov|co|uk|de|app|info)\b", re.I
)
_SECRET_PLACEHOLDER = re.compile(r"<secret>([\w.-]+)</secret>")


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
    #: The snapshot action id for an element or control operation, else None.
    action_id: str | None
    url: str | None
    confidence: float
    latency_ms: int
    evaluation: JevEvaluation


@dataclass(frozen=True)
class _Choice:
    """A validated answer: the option chosen, and how sure Jev was."""

    choice: str
    confidence: float


@dataclass
class _Element:
    """One observed element as Jev's state lists it; a dropdown's options are its targets."""

    index: str
    label: str
    #: The descriptor fields it carries (role, id or name, value, states), none of them empty.
    fields: dict[str, object]
    operations: list[JevOperation] = field(default_factory=list)
    options: list[dict[str, str]] | None = None

    def described(self) -> dict[str, object]:
        """Return the element as Jev reads it."""
        described = {
            **self.fields,
            "index": self.index,
            "label": self.label,
            "operations": self.operations,
        }
        if self.options is not None:
            described["options"] = self.options
        return described


@dataclass
class _ActionSpace:
    elements: list[_Element] = field(default_factory=list)
    #: Per target operation: target index -> snapshot action.
    targets: dict[JevOperation, dict[str, PageAction]] = field(default_factory=dict)
    controls: dict[JevOperation, PageAction] = field(default_factory=dict)


def action_space(actions: list[PageAction]) -> _ActionSpace:
    """One index per observed element; each operation has its own valid targets."""
    space = _ActionSpace()
    by_node: dict[int, _Element] = {}
    for action in actions:
        kind = action["kind"]
        if kind not in _KIND_OPERATION:
            operation = _CONTROL_OPERATION.get(action["id"])
            if operation is not None:
                space.controls[operation] = action
            continue
        node = action["node"]
        element = by_node.get(node)
        if element is None:
            if len(by_node) >= JEV_MAX_ELEMENTS:
                continue
            fields = {k: v for k, v in _fields(action, _ELEMENT_FIELDS).items() if v != ""}
            element = _Element(
                index=str(len(space.elements) + 1),
                label=action["label"].split(" → ")[0],
                fields=fields,
            )
            if kind == "select":
                # A dropdown shows its current choice; each option it offers is a target.
                element.fields["value"] = action["current_value"]
                element.options = []
            by_node[node] = element
            space.elements.append(element)
        operation = _KIND_OPERATION[kind]
        if operation not in element.operations:
            element.operations.append(operation)
        target = element.index
        if element.options is not None:
            target = f"{element.index}:{len(element.options) + 1}"
            element.options.append(
                {"index": target, "label": action["label"], "value": action["value"]}
            )
        space.targets.setdefault(operation, {})[target] = action
    return space


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


def goal_addresses(goal: str) -> list[str]:
    """Return the pages a goal names: its URLs, and bare sites outside them as https addresses."""
    urls = [match.group(0).rstrip(_TRAILING_PUNCTUATION) for match in _URL.finditer(goal)]
    sites = [
        f"https://{match.group(0).lower()}/"
        for text in _URL.split(goal)
        for match in _SITE.finditer(text)
    ]
    return list(dict.fromkeys([*urls, *sites]))


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
            "current_value": action.get("current_value", action["value"]),
            **_fields(action, _TARGET_FIELDS),
        }
        for index, action in candidates.items()
    }


def _page(page: PageState) -> dict[str, object]:
    return {"url": page.url, "title": page.title, "text": page.text}


def _validate_choice(answer: JevChoiceAnswer | None, ids: set[str]) -> _Choice:
    if answer is None:
        raise JevDecisionError(_NO_ANSWER)
    probabilities = answer.probabilities
    confidence = answer.confidence
    if confidence is None or not (
        answer.choice in ids
        and set(probabilities) == ids
        and all(math.isfinite(n) and 0 <= n <= 1 for n in [*probabilities.values(), confidence])
        and abs(sum(probabilities.values()) - 1) < JEV_PROBABILITY_SUM_TOLERANCE
        and probabilities[answer.choice] >= max(probabilities.values()) - _TIE_TOLERANCE
    ):
        raise JevDecisionError(_INVALID_ANSWER)
    return _Choice(answer.choice, confidence)


async def decide(
    client: JevDecisionsClient,
    page: PageState,
    goal: str,
    history: list[RecentAction],
    visited: list[Visited],
    addresses: list[str],
) -> Decision:
    """Ask Jev for this step's operation and target; raises JevDecisionError on a malformed answer."""
    space = action_space(page.actions)
    controls: dict[JevOperation, PageAction] = space.controls
    operations: dict[str, JsonInput] = {op.value: OPERATIONS[op] for op in space.targets}
    operations.update({op.value: control["label"] for op, control in controls.items()})
    if JevOperation.TYPE_TEXT in space.targets:
        operations[JevOperation.PRESS_ENTER.value] = OPERATIONS[JevOperation.PRESS_ENTER]
    if addresses:
        operations[JevOperation.NAVIGATE.value] = OPERATIONS[JevOperation.NAVIGATE]
    if len(visited) > 1:
        operations[JevOperation.GO_BACK.value] = OPERATIONS[JevOperation.GO_BACK]
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
    evaluation = await client.evaluate(JevEvaluationRequest(state=state, questions=questions))
    operation_answer = _validate_choice(
        evaluation.answers.get(_OPERATION_QUESTION), set(operations)
    )
    operation = JevOperation(operation_answer.choice)
    action_id: str | None = None
    url: str | None = None
    if operation in space.targets:
        target = _validate_choice(
            evaluation.answers.get(_target_question(operation)), set(space.targets[operation])
        )
        chosen: PageAction = space.targets[operation][target.choice]
        action_id = chosen["id"]
    elif operation in controls:
        control: PageAction = controls[operation]
        action_id = control["id"]
    elif operation is JevOperation.NAVIGATE:
        target = _validate_choice(evaluation.answers.get(_NAVIGATE_QUESTION), set(address_ids))
        url = address_ids[target.choice]
    return Decision(
        operation=operation,
        action_id=action_id,
        url=url,
        confidence=operation_answer.confidence,
        latency_ms=evaluation.latency_ms,
        evaluation=evaluation,
    )


async def choose_value(
    client: JevDecisionsClient,
    page: PageState,
    goal: str,
    target: PageAction,
    history: list[RecentAction],
    secrets: list[str],
) -> tuple[str, JevEvaluation]:
    """Pick what to type into target: a literal from the goal, one of the run's secrets, GENERATE, or NONE.

    A password field is offered the run's secrets only, and any other field never a secret.
    history is the recent actions Jev may see, already cut to that window.
    """
    is_secret = target["kind"] == "secret"
    options = [f"<secret>{name}</secret>" for name in secrets] if is_secret else literals(goal)
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
    evaluation = await client.evaluate(
        JevEvaluationRequest(state=state, questions={_VALUE_QUESTION: question})
    )
    answer = _validate_choice(evaluation.answers.get(_VALUE_QUESTION), set(criteria))
    if answer.choice in (GENERATE, NONE_VALUE):
        return answer.choice, evaluation
    return options[int(answer.choice[1:]) - 1], evaluation
