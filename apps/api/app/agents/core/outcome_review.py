"""The executor's declared outcome, checked against the tool calls that actually ran.

Deterministic on purpose: the model grading its own run is the failure this
exists to catch, so the evidence is what ran, never what the run says.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from langchain_core.messages import AIMessage, AnyMessage, HumanMessage, ToolCall, ToolMessage

from app.agents.core.delegation_window import current_delegation
from app.constants.agents import (
    OUTCOME_COMPLETE_TOOL,
    OUTCOME_SCHEDULE_ARGS,
    OUTCOME_SUBSCRIBE_TOOL,
    OUTCOME_TRACKED_TODO_TOOLS,
    TODO_REARM_TAG,
    OutcomeState,
)
from app.constants.execute import EXECUTE_TOOL_NAME
from app.constants.general import FINISH_TASK_NAME
from app.constants.llm import COMPLETION_NON_WORK_TOOLS
from app.override.langgraph_bigtool.utils import State
from app.utils.multimodal import extract_text_content


def is_successful_work(message: AnyMessage) -> bool:
    """Return whether this is a work result that came back without error."""
    return (
        isinstance(message, ToolMessage)
        and message.status != "error"
        and message.name not in COMPLETION_NON_WORK_TOOLS
    )


def _successful_calls(delegation: Sequence[AnyMessage]) -> list[ToolCall]:
    """Return this delegation's work calls whose results came back without error, in order."""
    answered = {
        m.tool_call_id for m in delegation if isinstance(m, ToolMessage) and is_successful_work(m)
    }
    return [
        call
        for m in delegation
        if isinstance(m, AIMessage)
        for call in m.tool_calls
        if _is_answered(call, answered)
    ]


def _is_answered(call: ToolCall, answered: set[str]) -> bool:
    return call["id"] in answered


def _effective_call(call: ToolCall) -> tuple[str, Mapping[str, object]]:
    """Return the tool a call really ran, seen through the execute proxy."""
    args: Mapping[str, object] = call.get("args") or {}
    if call["name"] == EXECUTE_TOOL_NAME:
        data = args.get("data")
        return str(args.get("tool_name") or ""), data if isinstance(data, Mapping) else {}
    return call["name"], args


def _wakes_later(call: ToolCall) -> bool:
    """Return whether this successful call leaves something that wakes GAIA again."""
    name, args = _effective_call(call)
    if name in OUTCOME_TRACKED_TODO_TOOLS:
        return any(args.get(key) for key in OUTCOME_SCHEDULE_ARGS)
    return False


def _keeps_a_todo_awake(call: ToolCall) -> bool:
    """Return whether this call closes a todo or gives it its next check."""
    return _effective_call(call)[0] == OUTCOME_COMPLETE_TOOL or _wakes_later(call)


def _briefed_to_rearm(delegation: Sequence[AnyMessage]) -> bool:
    task = delegation[0] if delegation else None
    if not isinstance(task, HumanMessage):
        return False
    return any(
        line.strip() == TODO_REARM_TAG for line in extract_text_content(task.content).splitlines()
    )


def todo_left_asleep(delegation: Sequence[AnyMessage]) -> str | None:
    """Name how this run left its tracked todo with no next step, if it did.

    A run briefed with the re-arm tag spent the check that woke it, so it must
    close the todo or set a new one. Creating a todo without one is refused in code.
    """
    if _briefed_to_rearm(delegation) and not any(
        _keeps_a_todo_awake(c) for c in _successful_calls(delegation)
    ):
        return "the todo was left open with no next check, so nothing will look at it again"
    return None


@dataclass(frozen=True)
class OutcomeReview:
    """The executor's declared outcome for a delegation, checked against what actually ran.

    declared is None when the run never called finish_task with an outcome; a
    plain-text stop is vetted by the completion nudge instead, so it carries no
    problem. problem names why a declaration is not backed by this run's calls.
    """

    declared: OutcomeState | None
    problem: str | None

    @property
    def verified(self) -> bool:
        return self.declared is not None and self.problem is None


def _declared_outcome(delegation: Sequence[AnyMessage]) -> OutcomeState | None:
    for message in reversed(delegation):
        if not isinstance(message, AIMessage):
            continue
        for call in message.tool_calls:
            if call["name"] == FINISH_TASK_NAME:
                raw = (call.get("args") or {}).get("outcome")
                return OutcomeState(raw) if isinstance(raw, str) and raw in OutcomeState else None
    return None


def review_outcome(delegation: Sequence[AnyMessage]) -> OutcomeReview:
    """Check the declared outcome against this delegation's successful tool calls."""
    declared = _declared_outcome(delegation)
    asleep = todo_left_asleep(delegation)
    if declared is None or asleep:
        return OutcomeReview(declared, asleep)
    calls = _successful_calls(delegation)
    if declared is OutcomeState.DONE and not calls:
        return OutcomeReview(declared, "done was declared but no work call succeeded")
    if declared is OutcomeState.SCHEDULE and not any(_wakes_later(c) for c in calls):
        return OutcomeReview(
            declared, "schedule was declared but no tracked todo was scheduled to wake GAIA"
        )
    if declared is OutcomeState.SUBSCRIBE and not any(
        _effective_call(c)[0] == OUTCOME_SUBSCRIBE_TOOL for c in calls
    ):
        return OutcomeReview(declared, "subscribe was declared but no trigger watch was set")
    return OutcomeReview(declared, None)


def outcome_unbacked(state: State) -> bool:
    """Return whether the run is ending on an outcome its own tool calls do not back."""
    return not review_outcome(current_delegation(state)).verified


def leaves_a_todo_asleep(state: State) -> bool:
    """Return whether the running delegation would leave a tracked todo with nothing to wake it."""
    return todo_left_asleep(current_delegation(state)) is not None


def review_run(messages: Sequence[AnyMessage]) -> OutcomeReview:
    """Review the delegation that ended a finished executor thread."""
    return review_outcome(current_delegation(State(messages=list(messages))))
