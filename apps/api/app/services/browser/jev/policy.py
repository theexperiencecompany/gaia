"""The step decision: one Jev request, operation + speculative target heads.

Port of jev-ultrafast's model.choose / validate_choice. Every operation
Jev may pick is offered as a criterion of the operation question; each
element-bound operation gets its own op_target question over only the
elements that support it. The heads answer in one round trip and only the
target head matching the chosen operation is read.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import math

from app.constants.browser import (
    JEV_PROBABILITY_SUM_TOLERANCE,
    JEV_RECENT_ACTIONS,
    JEV_TARGET_OPERATIONS,
    JevOperation,
)
from app.services.browser.jev.gateway import (
    JevChoiceAnswer,
    JevChoiceQuestion,
    JevEvaluation,
    JevEvaluationRequest,
    JevGatewayClient,
    JsonInput,
)
from app.services.browser.jev.observation import JevElement, JevObservation, JevSelectOption
from app.services.browser.jev.prompts import (
    HUMAN_RULES,
    NAVIGATE_RULE,
    NEXT_ACTION,
    REQUEST_HUMAN_CRITERION,
    SOLVE_CAPTCHA_CRITERION,
    TARGET,
)


class JevDecisionError(ValueError):
    """Jev's answer did not name an offered operation/target; no action executed."""


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
    JevOperation.DONE: "Every requirement is visibly satisfied.",
    JevOperation.BLOCKED: "No supported operation can progress.",
}


@dataclass(frozen=True)
class JevHistoryEntry:
    """One executed step, as the policy replays it to Jev on later steps."""

    action: str
    kind: str
    text: str | None = None
    page_changed: bool | None = None
    #: What the user said when they handed the browser back after this step.
    note: str | None = None

    def state_entry(self) -> dict[str, object]:
        return {
            "action": self.action,
            "kind": self.kind,
            "text": self.text,
            "page_changed": self.page_changed,
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
) -> JevEvaluationRequest:
    """Return the shared state plus one operation head and one target head per offered element operation."""
    targets = {op: observation.targets(op) for op in JEV_TARGET_OPERATIONS if op in offered}
    operations = {
        op.value: _OPERATION_LABELS[op]
        for op in JevOperation
        if op in offered and (op not in JEV_TARGET_OPERATIONS or targets.get(op))
    }
    rules: JsonInput = [NEXT_ACTION, HUMAN_RULES, NAVIGATE_RULE]
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
    return JevEvaluationRequest(
        state={
            "page": observation.page_state(),
            "elements": [e.state_entry() for e in observation.elements],
            "recent_actions": [h.state_entry() for h in history[-JEV_RECENT_ACTIONS:]],
        },
        questions=questions,
    )


async def choose(
    client: JevGatewayClient,
    observation: JevObservation,
    goal: str,
    history: list[JevHistoryEntry],
    offered: frozenset[JevOperation],
) -> JevDecision:
    """Ask Jev for this step's operation and, when it needs one, its target."""
    request = build_request(observation, goal, history, offered)
    evaluation = await client.evaluate(request)
    return resolve(request, evaluation, observation)


def resolve(
    request: JevEvaluationRequest, evaluation: JevEvaluation, observation: JevObservation
) -> JevDecision:
    """Validate the operation head, then only the target head that operation selects."""
    operation_answer = _validate_choice(
        evaluation.answers.get("operation"), request.questions["operation"].criteria
    )
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
