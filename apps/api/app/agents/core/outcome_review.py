"""The executor's declared outcome, checked against the tool calls that actually ran.

Deterministic on purpose: the model grading its own run is the failure this
exists to catch, so the evidence is what ran, never what the run says.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Protocol, cast

from langchain_core.messages import AIMessage, AnyMessage, HumanMessage, ToolCall, ToolMessage
from pydantic import ValidationError

from app.agents.core.delegation_window import current_delegation
from app.agents.core.report_review import RunCall, report_problem
from app.agents.core.subagents.call_record import is_error_envelope, parsed_result
from app.agents.tools.execute.unwrap import unwrap_execute_call
from app.constants.agents import (
    NO_REPORT_PROBLEM,
    OUTCOME_COMPLETE_TOOL,
    OUTCOME_SCHEDULE_ARGS,
    OUTCOME_SUBSCRIBE_TOOL,
    OUTCOME_TRACKED_TODO_TOOLS,
    TODO_REARM_TAG,
    TODO_WAKES_AGAIN_TAG,
    TOOL_REGISTRY_PROVIDER,
    OutcomeState,
)
from app.constants.general import FINISH_TASK_NAME
from app.constants.hil import HIL_EXEMPT_TOOLS
from app.constants.llm import COMPLETION_NON_WORK_TOOLS
from app.core.lazy_loader import providers
from app.models.task_report_models import FinishTaskArgs
from app.override.langgraph_bigtool.utils import State
from app.utils.multimodal import extract_text_content

#: Whether a tool, named as the registry knows it, changes the world.
WriteClassifier = Callable[[str], bool]


class _DestructivenessSource(Protocol):
    def is_tool_destructive(self, tool_name: str) -> bool | None: ...


def registered_is_write(tool_name: str) -> bool:
    """Return whether a tool changes the world: plumbing never does, an unclassified tool does."""
    if tool_name in HIL_EXEMPT_TOOLS:
        return False
    registry = cast(_DestructivenessSource, providers.get(TOOL_REGISTRY_PROVIDER))
    return registry.is_tool_destructive(tool_name) is not False


def is_successful_work(message: AnyMessage) -> bool:
    """Return whether this is a work result that came back without error."""
    return (
        isinstance(message, ToolMessage)
        and message.status != "error"
        and message.name not in COMPLETION_NON_WORK_TOOLS
    )


def _succeeded_ids(delegation: Sequence[AnyMessage]) -> set[str]:
    """Return the ids of work calls whose result came back without an error or an error body."""
    return {
        m.tool_call_id
        for m in delegation
        if isinstance(m, ToolMessage)
        and is_successful_work(m)
        and not is_error_envelope(parsed_result(m))
    }


def _successful_calls(delegation: Sequence[AnyMessage]) -> list[ToolCall]:
    """Return this delegation's work calls whose results came back without error, in order."""
    succeeded = _succeeded_ids(delegation)
    return [
        call
        for m in delegation
        if isinstance(m, AIMessage)
        for call in m.tool_calls
        if call["id"] in succeeded
    ]


def _run_calls(delegation: Sequence[AnyMessage], is_write: WriteClassifier) -> list[RunCall]:
    """Return every call of this delegation as the report review checks it against."""
    succeeded = _succeeded_ids(delegation)
    calls: list[RunCall] = []
    for message in delegation:
        if not isinstance(message, AIMessage):
            continue
        for call in message.tool_calls:
            tool = _effective_call(call)[0]
            ok = call["id"] in succeeded
            calls.append(RunCall(call["id"] or "", tool, ok, ok and is_write(tool)))
    return calls


def _effective_call(call: ToolCall) -> tuple[str, Mapping[str, object]]:
    """Return the tool a call really ran, seen through the execute proxy."""
    return unwrap_execute_call(call["name"], call["args"])


def _wakes_later(call: ToolCall) -> bool:
    """Return whether this successful call leaves something that wakes GAIA again."""
    name, args = _effective_call(call)
    if name in OUTCOME_TRACKED_TODO_TOOLS:
        return any(args.get(key) for key in OUTCOME_SCHEDULE_ARGS)
    return False


def _keeps_a_todo_awake(call: ToolCall) -> bool:
    """Return whether this call closes a todo or gives it its next check."""
    return _effective_call(call)[0] == OUTCOME_COMPLETE_TOOL or _wakes_later(call)


def _briefed_with(delegation: Sequence[AnyMessage], tag: str) -> bool:
    task = delegation[0] if delegation else None
    if not isinstance(task, HumanMessage):
        return False
    return any(line.strip() == tag for line in extract_text_content(task.content).splitlines())


def todo_left_asleep(delegation: Sequence[AnyMessage]) -> str | None:
    """Name how this run left its tracked todo with no next step, if it did.

    A run briefed with the re-arm tag spent the check that woke it, so it must
    close the todo or set a new one. Creating a todo without one is refused in code.
    """
    if _briefed_with(delegation, TODO_REARM_TAG) and not any(
        _keeps_a_todo_awake(c) for c in _successful_calls(delegation)
    ):
        return "the todo was left open with no next check, so nothing will look at it again"
    return None


@dataclass(frozen=True)
class OutcomeReview:
    """The executor's declared outcome for a delegation, checked against what actually ran.

    declared is None when the run never filed a finish_task report that declares
    one, and problem then says so: a run without a report is unverified, never
    success. problem otherwise names why the report is not backed by this run's calls.
    """

    declared: OutcomeState | None
    problem: str | None

    @property
    def verified(self) -> bool:
        return self.declared is not None and self.problem is None


def _is_finish_task(call: ToolCall) -> bool:
    return call["name"] == FINISH_TASK_NAME


def _last_finish_call(delegation: Sequence[AnyMessage]) -> ToolCall | None:
    for message in reversed(delegation):
        if not isinstance(message, AIMessage):
            continue
        for call in message.tool_calls:
            if _is_finish_task(call):
                return call
    return None


def _schema_problem(error: ValidationError) -> str:
    first = error.errors()[0]
    where = ".".join(str(part) for part in first["loc"])
    return f"the finish_task report does not match its schema ({where}: {first['msg']})"


def review_outcome(delegation: Sequence[AnyMessage], is_write: WriteClassifier) -> OutcomeReview:
    """Check the finish_task report against this delegation's tool calls."""
    asleep = todo_left_asleep(delegation)
    finish = _last_finish_call(delegation)
    if finish is None:
        return OutcomeReview(None, asleep or NO_REPORT_PROBLEM)
    try:
        report = FinishTaskArgs.model_validate(finish["args"])
    except ValidationError as error:
        return OutcomeReview(None, asleep or _schema_problem(error))
    declared = report.outcome
    if declared is None:
        return OutcomeReview(None, asleep or NO_REPORT_PROBLEM)
    if asleep:
        return OutcomeReview(declared, asleep)
    calls = _successful_calls(delegation)
    if declared is OutcomeState.DONE and not calls:
        return OutcomeReview(declared, "done was declared but no work call succeeded")
    if (
        declared is OutcomeState.SCHEDULE
        and not _briefed_with(delegation, TODO_WAKES_AGAIN_TAG)
        and not any(_wakes_later(c) for c in calls)
    ):
        return OutcomeReview(
            declared, "schedule was declared but no tracked todo was scheduled to wake GAIA"
        )
    if declared is OutcomeState.SUBSCRIBE and not any(
        _effective_call(c)[0] == OUTCOME_SUBSCRIBE_TOOL for c in calls
    ):
        return OutcomeReview(declared, "subscribe was declared but no trigger watch was set")
    return OutcomeReview(declared, report_problem(report, _run_calls(delegation, is_write)))


def outcome_problem(state: State) -> str | None:
    """Return why the running delegation's report is not backed by its calls, None when it is."""
    return review_outcome(current_delegation(state), registered_is_write).problem


def leaves_a_todo_asleep(state: State) -> bool:
    """Return whether the running delegation would leave a tracked todo with nothing to wake it."""
    return todo_left_asleep(current_delegation(state)) is not None


def review_run(messages: Sequence[AnyMessage], is_write: WriteClassifier) -> OutcomeReview:
    """Review the delegation that ended a finished executor thread."""
    return review_outcome(current_delegation(State(messages=list(messages))), is_write)
