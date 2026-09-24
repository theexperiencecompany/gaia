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
    JEV_RECENT_ACTIONS,
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

# Literal values a goal spells out: quoted text, emails, dates, URLs.
_QUOTED = re.compile(r"\"([^\"]{1,200})\"|“([^”]{1,200})”|(?<![\w])'([^']{1,200})'(?![\w])")
_EMAIL = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
_DATE = re.compile(r"\b\d{1,4}[/.-]\d{1,2}[/.-]\d{1,4}\b")
_URL = re.compile(r"https?://[^\s<>\"'()\[\]]+")
_SITE = re.compile(r"\b(?:[a-z0-9-]+\.)+(?:com|org|net|io|dev|ai|edu|gov|co|uk|de|app|info)\b", re.I)
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


@dataclass
class _ActionSpace:
    elements: list[dict[str, object]] = field(default_factory=list)
    #: Per target operation: target index -> snapshot action.
    targets: dict[JevOperation, dict[str, PageAction]] = field(default_factory=dict)
    controls: dict[JevOperation, PageAction] = field(default_factory=dict)


def action_space(actions: list[PageAction]) -> _ActionSpace:
    """One index per observed element; each operation has its own valid targets."""
    space = _ActionSpace()
    indices: dict[int, str] = {}
    for action in actions:
        kind = action["kind"]
        if kind not in _KIND_OPERATION:
            operation = _CONTROL_OPERATION.get(action["id"])
            if operation is not None:
                space.controls[operation] = action
            continue
        node = action["node"]
        if node not in indices:
            if len(indices) >= JEV_MAX_ELEMENTS:
                continue
            index = str(len(space.elements) + 1)
            indices[node] = index
            element = {
                key: value for key, value in _fields(action, _ELEMENT_FIELDS).items() if value != ""
            }
            element.update(index=index, label=action["label"].split(" → ")[0], operations=[])
            if kind == "select":
                element["value"] = action.get("current_value", "")
                element["options"] = []
            space.elements.append(element)
        index = indices[node]
        operation = _KIND_OPERATION[kind]
        element = space.elements[int(index) - 1]
        operations = element["operations"]
        assert isinstance(operations, list)
        if operation not in operations:
            operations.append(operation)
        target = index
        if kind == "select":
            options = element["options"]
            assert isinstance(options, list)
            target = f"{index}:{len(options) + 1}"
            options.append({"index": target, "label": action["label"], "value": action["value"]})
        space.targets.setdefault(operation, {})[target] = action
    return space


def _fields(action: PageAction, keys: tuple[str, ...]) -> dict[str, object]:
    """The named fields an action carries, for Jev's element descriptors."""
    present: dict[str, object] = dict(action)
    return {key: present[key] for key in keys if present.get(key) is not None}


def literals(goal: str) -> list[str]:
    """The values a goal spells out, in order: quoted text, emails, dates, URLs."""
    found: list[str] = []
    for match in _QUOTED.finditer(goal):
        found.append(next(group for group in match.groups() if group))
    for pattern in (_EMAIL, _DATE, _URL):
        found.extend(match.group(0).rstrip(".,;:!?") for match in pattern.finditer(goal))
    return list(dict.fromkeys(value for value in found if not _SECRET_PLACEHOLDER.fullmatch(value)))


def goal_addresses(goal: str) -> list[str]:
    """The pages a goal names: its URLs, and bare sites as https addresses."""
    urls = [match.group(0).rstrip(".,;:!?") for match in _URL.finditer(goal)]
    sites = [f"https://{match.group(0).lower()}/" for match in _SITE.finditer(_URL.sub(" ", goal))]
    return list(dict.fromkeys([*urls, *sites]))


def _validate_choice(answer: JevChoiceAnswer | None, ids: set[str]) -> JevChoiceAnswer:
    if answer is None:
        raise JevDecisionError("Jev returned no answer for a question; no action executed.")
    probabilities = answer.probabilities
    numbers = [*probabilities.values(), answer.confidence if answer.confidence is not None else -1.0]
    valid = (
        answer.choice in ids
        and set(probabilities) == ids
        and all(math.isfinite(n) and 0 <= n <= 1 for n in numbers)
        and abs(sum(probabilities.values()) - 1) < JEV_PROBABILITY_SUM_TOLERANCE
        and probabilities[answer.choice] >= max(probabilities.values()) - 1e-6
    )
    if not valid:
        raise JevDecisionError("Invalid Jev response; no action executed.")
    return answer


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
    operations: dict[str, JsonInput] = {op.value: OPERATIONS[op] for op in space.targets}
    operations.update({op.value: action["label"] for op, action in space.controls.items()})
    if JevOperation.TYPE_TEXT in space.targets:
        operations[JevOperation.PRESS_ENTER.value] = OPERATIONS[JevOperation.PRESS_ENTER]
    if addresses:
        operations[JevOperation.NAVIGATE.value] = OPERATIONS[JevOperation.NAVIGATE]
    if len(visited) > 1:
        operations[JevOperation.GO_BACK.value] = OPERATIONS[JevOperation.GO_BACK]
    operations[JevOperation.DONE.value] = OPERATIONS[JevOperation.DONE]
    operations[JevOperation.BLOCKED.value] = OPERATIONS[JevOperation.BLOCKED]

    questions: dict[str, JevQuestion] = {
        "operation": JevQuestion(
            criteria=operations, instructions={"goal": goal, "rules": NEXT_ACTION}
        )
    }
    for operation, candidates in space.targets.items():
        questions[operation.value.lower() + "_target"] = JevQuestion(
            criteria={
                index: {
                    "element": f"[{index}] {action['label']}",
                    "current_value": action.get("current_value", action.get("value", "")),
                    **_fields(action, ("role", "ident", "checked", "selected", "expanded", "filled")),
                }
                for index, action in candidates.items()
            },
            instructions={"goal": goal, "operation": operation.value, "rules": [NEXT_ACTION, TARGET]},
        )
    address_ids = {f"U{i + 1}": url for i, url in enumerate(addresses)}
    if address_ids:
        questions["navigate_target"] = JevQuestion(
            criteria=dict(address_ids),
            instructions={"goal": goal, "operation": "NAVIGATE", "rules": NAVIGATE_TARGET},
        )
    state: dict[str, object] = {
        "page": {"url": page.url, "title": page.title, "text": page.text},
        "elements": space.elements,
        "recent_actions": [
            {"action": h.action, "kind": h.kind, "text": h.text, "page_changed": h.page_changed}
            for h in history[-JEV_RECENT_ACTIONS:]
        ],
        "visited": [{"title": v.title, "url": v.url} for v in visited],
    }
    evaluation = await client.evaluate(JevEvaluationRequest(state=state, questions=questions))
    operation_answer = _validate_choice(evaluation.answers.get("operation"), set(operations))
    operation = JevOperation(operation_answer.choice)
    action_id: str | None = None
    url: str | None = None
    if operation in space.targets:
        target = _validate_choice(
            evaluation.answers.get(operation.value.lower() + "_target"), set(space.targets[operation])
        )
        action_id = space.targets[operation][target.choice]["id"]
    elif operation in space.controls:
        action_id = space.controls[operation]["id"]
    elif operation is JevOperation.NAVIGATE:
        target = _validate_choice(evaluation.answers.get("navigate_target"), set(address_ids))
        url = address_ids[target.choice]
    return Decision(
        operation=operation,
        action_id=action_id,
        url=url,
        confidence=operation_answer.confidence or 0.0,
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
    """
    is_secret = target["kind"] == "secret"
    options = [f"<secret>{name}</secret>" for name in secrets] if is_secret else literals(goal)
    criteria: dict[str, JsonInput] = {f"V{i + 1}": value for i, value in enumerate(options)}
    if not is_secret:
        criteria[GENERATE] = "None of these: write the value from what the goal implies."
    criteria[NONE_VALUE] = "The goal gives no value for this field."
    question = JevQuestion(
        criteria=criteria,
        instructions={
            "goal": goal,
            "field": {k: target.get(k) for k in ("label", "role", "ident", "value")},
            "rules": VALUE,
        },
    )
    state: dict[str, object] = {
        "page": {"url": page.url, "title": page.title, "text": page.text},
        "recent_actions": [
            {"action": h.action, "text": h.text} for h in history[-JEV_RECENT_ACTIONS:]
        ],
    }
    evaluation = await client.evaluate(
        JevEvaluationRequest(state=state, questions={"value": question})
    )
    answer = _validate_choice(evaluation.answers.get("value"), set(criteria))
    if answer.choice in (GENERATE, NONE_VALUE):
        return answer.choice, evaluation
    return options[int(answer.choice[1:]) - 1], evaluation

